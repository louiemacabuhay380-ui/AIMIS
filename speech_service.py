import io
import math
import numpy as np
import librosa
import thresholds as T

try:                      # optional: Praat's standard jitter/shimmer (pip install praat-parselmouth)
    import parselmouth
    from parselmouth.praat import call as praat
except Exception:
    parselmouth = None

SAMPLE_RATE = 16000
PAUSE_MIN_SECONDS = 1.0   # silence at least this long counts as a pause
SILENCE_DB = 30           # sound this far below the loudest part counts as silence


def _clamp(value, low=0.0, high=100.0):
    return float(max(low, min(high, value)))


def _smooth(x, size=5):
    """Running median: the slow movement (intonation) to subtract, leaving the tiny wobbles."""
    if len(x) < size:
        return x
    pad = size // 2
    padded = np.pad(x, pad, mode="edge")
    return np.array([np.median(padded[i:i + size]) for i in range(len(x))])


def voice_quality(y, sr):
    """Jitter and shimmer (%), and a 0-100 voice steadiness score (S7).
    With praat-parselmouth installed: Praat's jitter (local) and shimmer (local), the standard measures.
    Without it: AIMIS finds every vocal cycle's peak itself (same idea as Praat's peak picking)."""
    if parselmouth is not None:
        try:
            snd = parselmouth.Sound(y.astype("float64"), sampling_frequency=sr)
            pp = praat(snd, "To PointProcess (periodic, cc)", 75, 500)
            jitter = praat(pp, "Get jitter (local)", 0, 0, 0.0001, 0.02, 1.3) * 100
            shimmer = praat([snd, pp], "Get shimmer (local)", 0, 0, 0.0001, 0.02, 1.3, 1.6) * 100
            if not (math.isnan(jitter) or math.isnan(shimmer)):
                return _steadiness(jitter, shimmer, T.JITTER_NORMAL, T.SHIMMER_NORMAL, "praat")
        except Exception as e:
            print("Praat voice quality failed, using the estimate:", e)
    # Estimate without Praat: find each vocal cycle's peak (like Praat's peak picking), then
    # jitter = average change in cycle length, shimmer = average change in peak height, between neighbouring cycles.
    hop, win = 160, 640                                       # 10 ms steps, 40 ms window for the pitch guide
    f0 = librosa.yin(y, fmin=65, fmax=400, sr=sr, frame_length=win, hop_length=hop)
    amp = librosa.feature.rms(y=y, frame_length=win, hop_length=hop)[0]
    n = min(len(f0), len(amp))
    f0, amp = f0[:n], amp[:n]
    db = librosa.amplitude_to_db(amp, ref=1.0)
    voiced = (db > db.max() - 25) & (f0 > 70) & (f0 < 395)
    jit, shim = [], []
    start = None
    for i, v in enumerate(list(voiced) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= 10:                              # steady voiced stretch of at least 100 ms
                j, s_ = _cycles(y, sr, start * hop, i * hop, f0[start:i], hop)
                if j is not None:
                    jit.append(j)
                    shim.append(s_)
            start = None
    if not jit:
        return None
    return _steadiness(float(np.median(jit)), float(np.median(shim)),
                       T.JITTER_NORMAL, T.SHIMMER_NORMAL, "estimate")


def _cycles(y, sr, a, b, f0, hop):
    """Jitter and shimmer (%) of one voiced stretch y[a:b], from the peak of every vocal cycle.
    Real voices have several peaks per cycle (from the mouth's resonances), so the stretch is first filtered to
    keep only the fundamental (0.5 to 1.5 x the voice's pitch); then each cycle has one clear peak.
    Like Praat, neighbouring cycles only count when their lengths differ by less than 1.3 x (period factor) and
    their heights by less than 1.6 x (amplitude factor): bigger jumps are tracking errors, not voice wobble."""
    seg = y[a:b]
    median_f0 = float(np.median(f0))
    if len(seg) < 64 or median_f0 <= 0:
        return None, None
    spec = np.fft.rfft(seg)
    freqs = np.fft.rfftfreq(len(seg), 1 / sr)
    spec[(freqs > 1.5 * median_f0) | (freqs < 0.5 * median_f0)] = 0       # band around the fundamental
    seg = np.fft.irfft(spec, len(seg))
    period = sr / median_f0
    pos = int(np.argmax(seg[:int(period)]))
    peaks = [pos]
    while True:
        k = min(len(f0) - 1, max(0, pos // hop))
        p = sr / float(f0[k]) if f0[k] > 0 else period
        lo, hi = pos + int(0.7 * p), pos + int(1.3 * p)
        if hi >= len(seg):
            break
        pos = lo + int(np.argmax(seg[lo:hi]))
        peaks.append(pos)
    # sub-sample peak position and height (parabola through the peak and its two neighbours)
    exact, h = [], []
    for q in peaks:
        if 0 < q < len(seg) - 1:
            l, c, r = seg[q - 1], seg[q], seg[q + 1]
            d = l - 2 * c + r
            off = 0.5 * (l - r) / d if d else 0.0
            exact.append(q + off)
            h.append(abs(c - 0.25 * (l - r) * off))
    if len(exact) < 6:
        return None, None
    t = np.diff(np.array(exact)) / sr
    h = np.array(h)
    ok_t = (t >= 1 / 500) & (t <= 1 / 70)                                   # possible voice periods only
    pairs_t = [(t[i], t[i + 1]) for i in range(len(t) - 1)
               if ok_t[i] and ok_t[i + 1] and max(t[i], t[i + 1]) / min(t[i], t[i + 1]) < 1.3]
    pairs_h = [(h[i], h[i + 1]) for i in range(len(h) - 1)
               if min(h[i], h[i + 1]) > 0 and max(h[i], h[i + 1]) / min(h[i], h[i + 1]) < 1.6]
    if len(pairs_t) < 4 or len(pairs_h) < 4:
        return None, None
    jitter = np.mean([abs(x - z) for x, z in pairs_t]) / np.mean([x for x, _ in pairs_t]) * 100
    shimmer = np.mean([abs(x - z) for x, z in pairs_h]) / np.mean([x for x, _ in pairs_h]) * 100
    return float(jitter), float(shimmer)


def _steadiness(jitter, shimmer, jitter_normal, shimmer_normal, method):
    """100 when both are within a normal voice's values; each one at double the normal value takes 40 off."""
    score = 100 - 40 * max(0, jitter / jitter_normal - 1) - 40 * max(0, shimmer / shimmer_normal - 1)
    return {"jitter": round(jitter, 3), "shimmer": round(shimmer, 3),
            "voice_steadiness": round(_clamp(score), 2), "voice_method": method}


def analyze_audio(audio_bytes, filler_count=0, gain=1.0):
    """Measure pauses, pitch variation (tone), volume, voice quality, and a rule-based confidence score.
    gain: how much the browser boosted a quiet recording, so the volume is measured as it really was."""
    y, sr = librosa.load(io.BytesIO(audio_bytes), sr=SAMPLE_RATE, mono=True)
    duration = len(y) / sr
    intervals = librosa.effects.split(y, top_db=SILENCE_DB)   # parts where the person is speaking
    if duration == 0 or len(intervals) == 0:
        return None   # nothing but silence

    # --- Pauses: gaps between speaking parts (silence before the first word and after the last is ignored)
    speech_time = sum(end - start for start, end in intervals) / sr
    gaps = [(intervals[i + 1][0] - intervals[i][1]) / sr for i in range(len(intervals) - 1)]
    pauses = [g for g in gaps if g >= PAUSE_MIN_SECONDS]
    long_pauses = [g for g in gaps if g >= T.LONG_PAUSE_SECONDS]

        # --- Pitch variation (tone), in semitones so it's comparable between low and high voices
    f0 = librosa.yin(y, fmin=65, fmax=400, sr=sr, frame_length=1024, hop_length=256)
    frame_db = librosa.amplitude_to_db(
        librosa.feature.rms(y=y, frame_length=1024, hop_length=256)[0], ref=1.0)
    n = min(len(f0), len(frame_db))
    speaking = frame_db[:n] > frame_db.max() - SILENCE_DB          # only frames where they're talking
    f0 = f0[:n][speaking & (f0[:n] > 70) & (f0[:n] < 395)]          # drop silence and edge readings
    if len(f0) > 10:
        semitones = 12 * np.log2(f0 / np.median(f0))
        pitch_variation = float(np.std(semitones))
    else:
        pitch_variation = 0.0

    # --- Volume, measured only while the person is speaking
    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=256)[0]
    db = librosa.amplitude_to_db(rms, ref=1.0)
    speaking_db = db[db > db.max() - SILENCE_DB]
    try:
        boost_db = 20 * math.log10(float(gain)) if gain and float(gain) > 0 else 0.0
    except (TypeError, ValueError):
        boost_db = 0.0
    average_volume = float(np.mean(speaking_db)) - boost_db     # loudness before the browser's boost
    volume_variation = float(np.std(speaking_db))

    # --- Rule-based confidence score: four components, each 0-100
    minutes = duration / 60
    longest = max(pauses) if pauses else 0.0
    pause_score = _clamp(100 - 15 * (len(pauses) / minutes) - 10 * max(0, longest - 2))

    if pitch_variation < 1.0:            # monotone
        pitch_score = 40.0
    elif pitch_variation < 2.0:
        pitch_score = 40 + (pitch_variation - 1.0) * 60
    elif pitch_variation <= 5.0:         # natural, expressive range
        pitch_score = 100.0
    else:                                # very unsteady
        pitch_score = _clamp(100 - (pitch_variation - 5.0) * 15)

    volume_score = _clamp(100 - max(0, volume_variation - 8) * 8)
    filler_score = _clamp(100 - (filler_count / minutes) * 10)

    confidence = round((pause_score + pitch_score + volume_score + filler_score) / 4, 2)

    quality = voice_quality(y, sr) or {}

    # time from the first word to the last word (silence before starting and after finishing left out)
    talk_span = (intervals[-1][1] - intervals[0][0]) / sr

    return {
        "talk_span": round(float(talk_span), 2),
        "pause_count": int(len(pauses)),
        "long_pause_count": int(len(long_pauses)),
        "jitter": quality.get("jitter"),
        "shimmer": quality.get("shimmer"),
        "voice_steadiness": quality.get("voice_steadiness"),
        "total_pause_time": round(float(sum(pauses)), 2),
        "longest_pause": round(float(longest), 2),
        "average_pause": round(float(sum(pauses) / len(pauses)), 2) if pauses else 0.0,
        "pitch_variation": round(float(pitch_variation), 2),
        "average_volume": round(float(average_volume), 2),
        "volume_variation": round(float(volume_variation), 2),
        "speech_ratio": round(float(speech_time / duration * 100), 2),
        "confidence_score": float(confidence),
    }