"""Cutoffs (T1 to T14) for the behavioral and speech criteria.

Source: "AIMIS Scoring Formula: Behavioral and Speech Analysis" (Nov 14, 2026).
The studies give the DIRECTION of each rule (more is better, a moderate range is best, or less is better);
they don't give exact numbers. These are STARTING VALUES. Change them here after the pilot test, where HR
practitioners rate 10-20 recorded mock interviews on the same 14 criteria and each T is set at the cutoff
that best matches the raters (see Section 5 of the formula doc). Nothing else needs to change: scoring.py,
the report page and the admin export all read these numbers.

Old interviews are re-checked with the new cutoffs whenever their report is opened again.
"""

# ---------------------------------------------------------------- Behavioral analysis (camera, on the student's device)
T1_EYE_CONTACT_PCT = 60        # B1 Eye contact: % of time looking at the camera >= T1
T2_NODS_PER_MIN = 1.0          # B2 Head nodding: nods per minute >= T2
T3_SMILE_PCT = 10              # B3 Smiling: % of time smiling >= T3
T4_GESTURES_PER_MIN = (3, 15)  # B4 Hand gestures: T4low <= gestures per minute <= T4high
T5_UPRIGHT_PCT = 70            # B5 Posture: % of time upright or leaning forward >= T5
T6_FACING_PCT = 70             # B6 Body orientation: % of time facing the camera >= T6
T7_FIDGETS_PER_MIN = 2.0       # B7 No anxiety signs: fidgeting/self-touch events per minute <= T7

# ---------------------------------------------------------------- Speech analysis (the recording, on the server)
T8_PITCH_RANGE_ST = (1.5, 5.0)     # S1 Tone/pitch variation: semitones (std. dev. of pitch) in this range
T9_WORDS_PER_MIN = (110, 170)      # S2 Speech rate: words per minute in this range
T10_LOUDNESS_DB = (-35, -12)       # S3 Volume: average loudness while speaking, dBFS, in this range
T11_CLARITY = 60                   # S4 Clarity: speech-to-text confidence (0-100) >= T11
T12_FILLERS_PER_MIN = 4.0          # S5 Fluency: filler words per minute <= T12
T13_LONG_PAUSES_PER_MIN = 2.0      # S6 Pauses: long pauses per minute <= T13
T14_VOICE_STEADINESS = 60          # S7 Voice quality: steadiness (0-100, from jitter and shimmer) >= T14

# Colors on the report (display only, never changes the score): green = met, orange = not met but close
# ("almost": within this share of the cutoff, or of the range's width), red = not met and far from the target.
NEAR_MARGIN = 0.20

# ---------------------------------------------------------------- how the measurements are taken
LONG_PAUSE_SECONDS = 2.0       # a silence this long (between words) counts as a long pause
# Voice steadiness (S7) = 100 when jitter and shimmer are at or below these values; each one at double its
# value takes 40 points off. Praat's well-known 1.04% / 3.81% cutoffs are for a held vowel ("aaa"); in normal
# running speech both read higher, so these starting values are higher. Calibrate them in the pilot test too.
JITTER_NORMAL = 2.0            # % (jitter, local)
SHIMMER_NORMAL = 8.0           # % (shimmer, local)

# Behavioral measurement settings live in templates/interview.html (BEHAVIOR_SETTINGS), because the camera is
# analyzed in the browser: nod size, what counts as upright, facing and a fidget.


def as_dict():
    """All cutoffs, for the report page and the admin export."""
    return {k: v for k, v in globals().items() if k[:1] == "T" and k[1:2].isdigit()}
