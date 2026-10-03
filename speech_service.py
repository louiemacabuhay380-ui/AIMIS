import io
import numpy as np
import librosa

SAMPLE_RATE = 16000
PAUSE_MIN_SECONDS = 1.0   # silence at least this long counts as a pause
SILENCE_DB = 30           # sound this far below the loudest part counts as silence


def _clamp(value, low=0.0, high=100.0):
    return float(max(low, min(high, value)))


def analyze_audio(audio_bytes, filler_count=0):
    """Measure pauses, pitch variation (tone), volume, and a rule-based confidence score."""
    y, sr = librosa.load(io.BytesIO(audio_bytes), sr=SAMPLE_RATE, mono=True)
    duration = len(y) / sr
    intervals = librosa.effects.split(y, top_db=SILENCE_DB)   # parts where the person is speaking
    if duration == 0 or len(intervals) == 0:
        return None   # nothing but silence

    # --- Pauses: gaps between speaking parts (silence before the first word and after the last is ignored)
    speech_time = sum(end - start for start, end in intervals) / sr
    gaps = [(intervals[i + 1][0] - intervals[i][1]) / sr for i in range(len(intervals) - 1)]
    pauses = [g for g in gaps if g >= PAUSE_MIN_SECONDS]

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
    average_volume = float(np.mean(speaking_db))
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

    return {
        "pause_count": int(len(pauses)),
        "total_pause_time": round(float(sum(pauses)), 2),
        "longest_pause": round(float(longest), 2),
        "average_pause": round(float(sum(pauses) / len(pauses)), 2) if pauses else 0.0,
        "pitch_variation": round(float(pitch_variation), 2),
        "average_volume": round(float(average_volume), 2),
        "volume_variation": round(float(volume_variation), 2),
        "speech_ratio": round(float(speech_time / duration * 100), 2),
        "confidence_score": float(confidence),
    }