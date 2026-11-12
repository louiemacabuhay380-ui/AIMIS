"""Local (offline) backups for the Gemini features, so a demo still works when Gemini is down or out of quota.

- Speech-to-text: faster-whisper (pip install faster-whisper). The model downloads once (internet needed
  the first time only, about 150 MB for "base"), then works offline.
- Scoring and feedback: the local Ollama model (same one the chatbot uses, or OLLAMA_MODEL).

Settings in .env (all optional):
  TRANSCRIBE_PROVIDER=gemini | whisper    gemini (default) uses Whisper only when Gemini fails
  EVAL_PROVIDER=gemini | ollama           gemini (default) uses Ollama only when Gemini fails
  AI_FALLBACK=1                           set to 0 to turn the automatic backups off
  WHISPER_MODEL=base                      tiny / base / small (bigger = more accurate, slower)
  OLLAMA_MODEL=gemma3:4b                  model for scoring (default: OLLAMA_CHAT_MODEL)
"""
import io
import os
import re
import json
import math
import time
import urllib.request
import urllib.error
import threading

FILLERS = re.compile(r"\b(um+|uh+m*|erm|ah+|eh+|ano|parang|kasi|yung|'yung|ganun|diba|you know|like)\b", re.I)
_whisper = None
_whisper_lock = threading.Lock()   # one transcription at a time (Whisper already uses all CPU cores)


def fallback_enabled():
    return (os.getenv("AI_FALLBACK") or "1") != "0"


# ---------------------------------------------------------------- speech-to-text (Whisper)

def whisper_available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _whisper_model():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        name = os.getenv("WHISPER_MODEL") or "base"
        print(f"Loading Whisper '{name}' (first time downloads the model)...")
        _whisper = WhisperModel(name, device="cpu", compute_type="int8")
    return _whisper


def _clamp(x, lo=0.0, hi=100.0):
    return float(max(lo, min(hi, x)))


def transcribe_local(audio_bytes):
    """Transcribe one answer with Whisper on this computer. Returns the same fields as the Gemini version.
    fluency_score and clarity_score are estimates from the recording (filler words, long pauses,
    and how confident Whisper was about the words)."""
    with _whisper_lock:
        return _transcribe_local(audio_bytes)


def _audio_array(audio_bytes):
    """The recording as 16 kHz mono samples, decoded here with librosa (the same reader the speech analysis uses).
    faster-whisper's own decoder needs the PyAV package, and some PyAV versions crash with
    "open() got an unexpected keyword argument 'metadata_errors'"; passing samples skips PyAV completely."""
    try:
        import librosa
        samples, _ = librosa.load(io.BytesIO(audio_bytes), sr=16000, mono=True)
        return samples.astype("float32")
    except Exception as e:
        print("Couldn't decode the recording with librosa, letting Whisper try:", e)
        return io.BytesIO(audio_bytes)


def _transcribe_local(audio_bytes):
    start = time.perf_counter()
    segments, info = _whisper_model().transcribe(
        _audio_array(audio_bytes), beam_size=1, vad_filter=False,
        # Hinting fillers makes Whisper keep "um", "uh", "ano" instead of cleaning them away
        initial_prompt="Um, uh, ano, parang, so, like, I think, kasi, yung.")
    segments = list(segments)
    transcript = " ".join(s.text.strip() for s in segments).strip()
    duration = max(info.duration or 0, 1.0)
    minutes = duration / 60

    fillers = len(FILLERS.findall(transcript))
    pauses = sum(1 for a, b in zip(segments, segments[1:]) if b.start - a.end >= 2.0)
    logprob = (sum(s.avg_logprob * (s.end - s.start) for s in segments) /
               max(sum(s.end - s.start for s in segments), 0.1)) if segments else -2.0

    fluency = _clamp(100 - 6 * (fillers / minutes) - 8 * (pauses / minutes))
    clarity = _clamp((logprob + 1.2) / 1.0 * 100)        # avg log-prob -0.2 → 100, -1.2 → 0
    print(f"Whisper transcribed {duration:.0f}s of audio in {time.perf_counter() - start:.1f}s")
    return {"transcript": transcript, "filler_word_count": fillers, "pause_count": pauses,
            "fluency_score": round(fluency), "clarity_score": round(clarity), "_provider": "whisper"}


# ---------------------------------------------------------------- scoring (Ollama)

def ollama_model():
    return os.getenv("OLLAMA_MODEL") or os.getenv("OLLAMA_CHAT_MODEL") or "gemma3:4b"


def ollama_available():
    host = (os.getenv("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
    try:
        with urllib.request.urlopen(host + "/api/tags", timeout=2) as r:
            names = [m.get("name", "") for m in json.loads(r.read().decode()).get("models", [])]
    except Exception:
        return False
    model = ollama_model()
    return any(n == model or n.split(":")[0] == model or n == model + ":latest" for n in names)


def ollama_json(prompt, validate=None, attempts=3, num_ctx=8192):
    """Send a prompt to the local Ollama model and return its JSON reply.
    validate(result) -> error text or None; an incomplete reply is retried."""
    host = (os.getenv("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
    model = ollama_model()
    last_error = None
    for attempt in range(attempts):
        body = json.dumps({"model": model, "stream": False, "format": "json", "keep_alive": "30m",
                           "messages": [{"role": "user", "content": prompt}],
                           "options": {"temperature": 0.2, "num_ctx": num_ctx}}).encode()
        request = urllib.request.Request(host + "/api/chat", data=body, headers={"Content-Type": "application/json"})
        try:
            start = time.perf_counter()
            with urllib.request.urlopen(request, timeout=600) as r:
                reply = json.loads(r.read().decode())
            print(f"Ollama {model} took {time.perf_counter() - start:.1f}s")
            result = json.loads(reply["message"]["content"])
            problem = validate(result) if validate else None
            if not problem:
                return result
            last_error = ValueError(f"Ollama reply was incomplete: {problem}")
            print(last_error, "- retrying...")
        except urllib.error.HTTPError as e:
            # Ollama is running but the model failed (often: not enough memory for a long request)
            try:
                detail = json.loads(e.read().decode()).get("error", "")
            except Exception:
                detail = ""
            last_error = RuntimeError(f"Ollama returned an error ({e.code}): {detail or e.reason}")
            print(last_error, "- retrying..." if attempt < attempts - 1 else "")
            time.sleep(2)
        except (urllib.error.URLError, OSError) as e:
            raise RuntimeError(f"Ollama is not running at {host} ({e})")
        except (json.JSONDecodeError, KeyError) as e:
            last_error = e
            print("Ollama returned invalid JSON, retrying...")
    raise last_error
