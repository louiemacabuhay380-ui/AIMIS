"""AIMIS scoring rubric (v3: v2 plus the behavioral and speech formula of Nov 14, 2026).

Every criterion, weight and level description lives here, so the AI prompt, the human evaluators' rubric,
the report page and the research paper all use the same definitions. Change a weight here and it changes
everywhere.

Two separate scores (panel comment 10):
  1. Answer Effectiveness   = WHAT was said: would this answer work in a real interview?
                              Direct, relevant, structured and specific, even if the delivery is not polished.
  2. Communication Delivery = HOW it was said: an effective communicator's voice, language and body language.
     v3: Delivery = (Behavioral Score + Speech Score) / 2, where each section has 7 yes/no criteria and
         Section Score = criteria met / 7 x 100 (equal weights; cutoffs T1-T14 in thresholds.py).
  Overall Interview Readiness = 60% Answer Effectiveness + 40% Communication Delivery.

All scores are 0 to 100. The AI uses the same five levels as the human evaluators:
  level 5 = 100, level 4 = 75, level 3 = 50, level 2 = 25, level 1 = 0 (scores in between are allowed).
"""

import thresholds as T

RUBRIC_VERSION = "v3"
SCORED_VERSIONS = ("v2", "v3")      # both have Answer Effectiveness + Communication Delivery (v3 = new delivery)

# ---------------------------------------------------------------- weights
OVERALL_WEIGHTS = {"answer": 60, "delivery": 40}      # Overall Interview Readiness
DELIVERY_WEIGHTS = {"verbal": 50, "nonverbal": 50}     # inside Communication Delivery: (Speech + Behavioral) / 2
V2_DELIVERY_WEIGHTS = {"verbal": 60, "nonverbal": 40}  # how interviews scored with v2 were combined

# ---------------------------------------------------------------- 1. Answer Effectiveness (scored by the AI from the transcript)
# levels: descriptions for rubric level 1 to 5 (index 0 = level 1)
ANSWER_CRITERIA = [
    {"key": "relevance", "label": "Relevance", "weight": 25,
     "question": "Does the answer address the exact question that was asked?",
     "levels": ["Off-topic or no real answer",
                "Mostly off-topic; touches the question only briefly",
                "Partly answers the question; drifts to other topics",
                "Answers the question asked",
                "Fully and directly answers the exact question, in the context of the target job"]},
    {"key": "directness", "label": "Directness", "weight": 25,
     "question": "Does it get to the main point quickly and stay on it (to the point, no rambling)?",
     "levels": ["No clear main point",
                "Main point is buried in rambling or repetition",
                "Main point is there but comes late or wanders",
                "Main point is clear and stated early; little extra talk",
                "States the main point right away and every sentence supports it"]},
    {"key": "completeness", "label": "Structure (STAR)", "weight": 25,
     "question": "Does it cover what the question needs (for experience questions: situation, action and result)?",
     "levels": ["Almost nothing of what the question needs",
                "Only one part (for example only the situation)",
                "Some key parts missing (for example no action or no result)",
                "Mostly complete; one part is thin",
                "Complete: clear situation, what the candidate did, and how it ended"]},
    {"key": "specificity", "label": "Specific evidence", "weight": 25,
     "question": "Does it use a real, concrete example or details instead of general claims?",
     "levels": ["Only general claims (\"I am hardworking\")",
                "A vague example with no details",
                "A real example, but few details",
                "A real example with useful details",
                "A real example with concrete details (who, what, numbers or outcome)"]},
]

# ---------------------------------------------------------------- 2. Communication Delivery
# Verbal delivery (from the recording and transcript) and nonverbal delivery (camera, on the student's device).
# "source" = which column holds the score in the database rows used by the reports.
V2_VERBAL_CRITERIA = [
    {"key": "fluency", "source": "fluency_score", "label": "Fluency", "weight": 25,
     "how": "AI listens to the recording and rates how smoothly the candidate speaks (hesitations, restarts).",
     "levels": ["Very broken speech", "Frequent hesitations", "Some hesitations", "Mostly smooth", "Smooth and natural"]},
    {"key": "speech_clarity", "source": "speech_clarity", "label": "Speech clarity", "weight": 25,
     "how": "AI rates how easy the words are to understand (mumbling, speaking too fast). An accent is not penalized.",
     "levels": ["Mostly not understandable", "Often unclear", "Understandable with effort", "Clear", "Very clear"]},
    {"key": "vocal_confidence", "source": "confidence_score", "label": "Vocal confidence", "weight": 25,
     "how": "Measured from the audio (librosa): average of four 0-100 parts: long pauses per minute, "
            "pitch variation (2-5 semitones is natural, under 1 is monotone), volume steadiness, filler words per minute.",
     "levels": ["Very hesitant", "Hesitant", "Somewhat steady", "Steady", "Steady and engaged"]},
    {"key": "grammar", "source": "grammar_score", "label": "Grammar", "weight": 25,
     "question": "Spoken grammar and sentence structure (ignore fillers like um/uh and punctuation).",
     "how": "AI rates the transcript's spoken grammar and sentence structure. Fillers and punctuation are ignored.",
     "levels": ["Many errors, hard to understand", "Frequent errors", "Some errors, still understandable",
                "Few errors", "Correct and natural"]},
]
V2_NONVERBAL_CRITERIA = [
    {"key": "eye_contact", "source": "eye_contact_score", "label": "Eye contact", "weight": 50,
     "how": "Share of camera frames where the head faces the camera (turned and tilted 25 degrees or less) and "
            "both eyes are not looking away.",
     "levels": ["Under 20% of the time", "20-39%", "40-59%", "60-79%", "80% or more"]},
    {"key": "facial_expression", "source": "facial_expression_score", "label": "Facial expression", "weight": 25,
     "how": "Smiling in at least 10% of the frames scores 100; less smiling scores 70 to 100; frequent frowning lowers it.",
     "levels": ["Tense or frowning throughout", "Mostly tense", "Neutral, no smiling", "Some natural smiling",
                "Natural, friendly expression"]},
    {"key": "gestures", "source": "gesture_score", "label": "Gestures", "weight": 25,
     "how": "Open-hand gestures while speaking in 10-60% of the time scores 100; fewer or nonstop gestures score lower; "
            "touching the face or hair and very fast movements lower it.",
     "levels": ["Distracting movements or constant face touching", "Frequent nervous habits", "Hands still or hidden",
                "Some natural gestures", "Natural open gestures that support the words"]},
]

VERBAL_CRITERIA = V2_VERBAL_CRITERIA          # grammar (index 3) is still rated by the AI for the feedback

# ---------------------------------------------------------------- 2b. v3 Communication Delivery: 7 + 7 yes/no criteria
# Each criterion: c = 1 if met, 0 if not. "rule": "min" (more is better, value >= T), "range" (moderate is best,
# low <= value <= high) or "max" (less is better, value <= T). "measure" = the field the value comes from.
BEHAVIORAL_CRITERIA = [
    {"key": "B1", "label": "Eye contact", "measure": "eye_contact_pct", "rule": "min", "t": "T1_EYE_CONTACT_PCT",
     "unit": "% of time", "basis": "Martín-Raugh et al. 2023; Mastrella et al. 2023",
     "how": "Share of camera frames where the head faces the camera and the eyes aren't looking away."},
    {"key": "B2", "label": "Head nodding", "measure": "nods_per_min", "rule": "min", "t": "T2_NODS_PER_MIN",
     "unit": "nods per minute", "basis": "Martín-Raugh et al. 2023; Scientific Reports 2024",
     "how": "Counted from the head's up-down angle: a quick dip of the head and back."},
    {"key": "B3", "label": "Smiling", "measure": "smile_pct", "rule": "min", "t": "T3_SMILE_PCT",
     "unit": "% of time", "basis": "Scientific Reports 2024",
     "how": "Share of frames with a smile (MediaPipe face expression)."},
    {"key": "B4", "label": "Hand gestures", "measure": "gestures_per_min", "rule": "range", "t": "T4_GESTURES_PER_MIN",
     "unit": "gestures per minute", "basis": "Rodero et al. 2022",
     "how": "Open-hand movements counted as separate gestures; a moderate number is best."},
    {"key": "B5", "label": "Posture", "measure": "upright_pct", "rule": "min", "t": "T5_UPRIGHT_PCT",
     "unit": "% of time", "basis": "Scientific Reports 2024",
     "how": "Share of frames sitting upright or leaning forward (shoulders level, head up, not leaning back)."},
    {"key": "B6", "label": "Body orientation", "measure": "facing_pct", "rule": "min", "t": "T6_FACING_PCT",
     "unit": "% of time", "basis": "Scientific Reports 2024",
     "how": "Share of frames with the shoulders (or the head, without the body model) facing the camera."},
    {"key": "B7", "label": "No anxiety signs", "measure": "fidgets_per_min", "rule": "max", "t": "T7_FIDGETS_PER_MIN",
     "unit": "events per minute", "basis": "Mastrella et al. 2023",
     "how": "Times the hand touches the face or hair, plus sudden jerky movements."},
]
SPEECH_CRITERIA = [
    {"key": "S1", "label": "Tone / pitch variation", "measure": "pitch_variation", "rule": "range", "t": "T8_PITCH_RANGE_ST",
     "unit": "semitones", "basis": "Martín-Raugh et al. 2023; Rodero et al. 2022",
     "how": "How much the voice goes up and down (spread of pitch in semitones); moderate is best."},
    {"key": "S2", "label": "Speech rate", "measure": "words_per_min", "rule": "range", "t": "T9_WORDS_PER_MIN",
     "unit": "words per minute", "basis": "Rodero et al. 2022",
     "how": "Words in the transcript divided by the time from the first word to the last (silence before and after is left out)."},
    {"key": "S3", "label": "Volume", "measure": "loudness_db", "rule": "range", "t": "T10_LOUDNESS_DB",
     "unit": "dBFS", "basis": "Martín-Raugh et al. 2023",
     "how": "Average loudness while speaking (before AIMIS boosts a quiet microphone)."},
    {"key": "S4", "label": "Clarity", "measure": "clarity", "rule": "min", "t": "T11_CLARITY",
     "unit": "of 100", "basis": "Schütze et al. 2026",
     "how": "How sure the speech-to-text was about the words (Whisper confidence, or Gemini's clarity rating)."},
    {"key": "S5", "label": "Fluency", "measure": "fillers_per_min", "rule": "max", "t": "T12_FILLERS_PER_MIN",
     "unit": "fillers per minute", "basis": "Vanderbilt Young Scientist Journal 2025; Schütze et al. 2026",
     "how": "Filler words (um, uh, like, ano, parang...) per minute."},
    {"key": "S6", "label": "Pauses", "measure": "long_pauses_per_min", "rule": "max", "t": "T13_LONG_PAUSES_PER_MIN",
     "unit": "long pauses per minute", "basis": "Vanderbilt Young Scientist Journal 2025",
     "how": "Silences between words of " + str(T.LONG_PAUSE_SECONDS).rstrip("0").rstrip(".") + " seconds or more, per minute."},
    {"key": "S7", "label": "Voice quality", "measure": "voice_steadiness", "rule": "min", "t": "T14_VOICE_STEADINESS",
     "unit": "of 100", "basis": "Schütze et al. 2026",
     "how": "Voice steadiness from jitter and shimmer (tiny wobbles in pitch and loudness)."},
]


def threshold(c):
    return getattr(T, c["t"])


def with_unit(value, unit):
    """60 + "% of time" -> "60% of time"; 2 + "nods per minute" -> "2 nods per minute"."""
    return f"{value:g}{'' if unit.startswith('%') else ' '}{unit}"


def threshold_text(c):
    t = threshold(c)
    if c["rule"] == "range":
        return f"{t[0]:g} to {with_unit(t[1], c['unit'])}"
    return f"{'at least' if c['rule'] == 'min' else 'at most'} {with_unit(t, c['unit'])}"


def criterion_met(c, value):
    """1 if met, 0 if not, None if there was no measurement."""
    value = _num(value)
    if value is None:
        return None
    t = threshold(c)
    if c["rule"] == "min":
        return int(value >= t)
    if c["rule"] == "max":
        return int(value <= t)
    return int(t[0] <= value <= t[1])


def closeness(c, value):
    """For the report colors only: "met", "near" (not met but within T.NEAR_MARGIN of the cutoff) or "far"."""
    met = criterion_met(c, value)
    if met is None:
        return None
    if met:
        return "met"
    value, t, m = _num(value), threshold(c), T.NEAR_MARGIN
    if c["rule"] == "range":
        slack = (t[1] - t[0]) * m
        near = t[0] - slack <= value <= t[1] + slack
    elif c["rule"] == "min":
        near = value >= t - abs(t) * m
    else:
        near = value <= t + abs(t) * m
    return "near" if near else "far"


def _per_min(count, seconds):
    count, seconds = _num(count), _num(seconds)
    if count is None or not seconds:
        return None
    return round(count / (seconds / 60), 2)


def measures(row):
    """The 14 measured values of one answer (None when not measured, e.g. no camera or an older interview)."""
    seconds = _num(row.get("duration")) or _num(row.get("speech_duration"))
    has_camera = row.get("eye_contact_score") is not None
    m = {
        "eye_contact_pct": row.get("eye_contact_score") if has_camera else None,
        "nods_per_min": row.get("nods_per_min"),
        "smile_pct": row.get("smile_ratio") if has_camera else None,
        "gestures_per_min": row.get("gestures_per_min"),
        "upright_pct": row.get("upright_ratio"),
        "facing_pct": row.get("facing_ratio"),
        "fidgets_per_min": row.get("fidgets_per_min"),
        "pitch_variation": row.get("pitch_variation"),
        "words_per_min": row.get("speaking_rate") if row.get("transcript") or row.get("speaking_rate") else None,
        "loudness_db": row.get("average_volume"),
        "clarity": row.get("speech_clarity", row.get("clarity_score")),
        "fillers_per_min": _per_min(row.get("filler_word_count"), seconds) if row.get("transcript") is not None else None,
        "long_pauses_per_min": _per_min(row.get("long_pause_count"), seconds),
        "voice_steadiness": row.get("voice_steadiness"),
    }
    return {k: _num(v) for k, v in m.items()}


def section(criteria, values):
    """{"score": met / measured x 100, "met": n, "measured": n, "items": [...]}. Score None if nothing measured.
    The formula divides by 7; when a measurement is missing (no camera, an older interview) that criterion is
    left out and the score is out of the criteria that were measured."""
    items = []
    for c in criteria:
        v = values.get(c["measure"])
        items.append({**c, "value": v, "met": criterion_met(c, v), "close": closeness(c, v), "target": threshold_text(c)})
    measured = [i for i in items if i["met"] is not None]
    met = sum(i["met"] for i in measured)
    score = round(met / len(measured) * 100, 2) if measured else None
    return {"score": score, "met": met, "measured": len(measured), "total": len(criteria), "items": items}


def delivery_sections(values):
    return section(BEHAVIORAL_CRITERIA, values), section(SPEECH_CRITERIA, values)


def combine_measures(rows):
    """Interview-level measurements: each answer's value weighted by how long the answer was
    (so rates per minute and shares of time are for the whole interview)."""
    out = {}
    all_m = [(measures(r), _num(r.get("duration")) or _num(r.get("speech_duration")) or 1.0) for r in rows]
    for key in (all_m[0][0].keys() if all_m else []):
        pairs = [(m[key], w) for m, w in all_m if m[key] is not None]
        out[key] = round(sum(v * w for v, w in pairs) / sum(w for _, w in pairs), 2) if pairs else None
    return out


# Interpretation of any 0-100 score (shown next to scores, and used for the performance profile)
BANDS = [(85, "Excellent"), (70, "Proficient"), (50, "Developing"), (0, "Needs improvement")]
PASS_MARK = 70      # "Proficient" or better counts as meeting the standard


def band_ranges():
    """["Excellent 85-100", "Proficient 70-84", ...] for the report and the paper."""
    out, top = [], 100
    for low, label in BANDS:
        out.append(f"{label} {low}–{top}")
        top = low - 1
    return out


def band(score):
    if score is None:
        return None
    for low, label in BANDS:
        if score >= low:
            return label
    return BANDS[-1][1]


def level_class(score):
    """CSS level used by the report: good / ok / low."""
    if score is None:
        return "none"
    return "good" if score >= PASS_MARK else "ok" if score >= 50 else "low"


# ---------------------------------------------------------------- calculations
def _num(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def weighted(parts):
    """parts: [(score or None, weight)]. Weighted mean of the parts that have a score; missing parts are
    left out and the remaining weights are rescaled. None if nothing is available."""
    have = [(v, w) for v, w in ((_num(v), w) for v, w in parts) if v is not None]
    if not have:
        return None
    return round(sum(v * w for v, w in have) / sum(w for _, w in have), 2)


def answer_score(row):
    """Answer Effectiveness of one answer (row has relevance_score, directness_score, ...)."""
    return weighted([(row.get(c["key"] + "_score"), c["weight"]) for c in ANSWER_CRITERIA])


def v2_verbal_score(row):
    return weighted([(row.get(c["source"]), c["weight"]) for c in V2_VERBAL_CRITERIA])


def v2_nonverbal_score(row):
    if row.get("eye_contact_score") is None:      # no camera for this answer
        return None
    return weighted([(row.get(c["source"]), c["weight"]) for c in V2_NONVERBAL_CRITERIA])


def verbal_score(row):
    """v3 Speech Score of one answer (S1-S7)."""
    return section(SPEECH_CRITERIA, measures(row))["score"]


def nonverbal_score(row):
    """v3 Behavioral Score of one answer (B1-B7); None without camera data."""
    if row.get("eye_contact_score") is None:
        return None
    return section(BEHAVIORAL_CRITERIA, measures(row))["score"]


def delivery_from(verbal, nonverbal, weights=None):
    w = weights or DELIVERY_WEIGHTS
    return weighted([(verbal, w["verbal"]), (nonverbal, w["nonverbal"])])


def overall_from(answer, delivery):
    return weighted([(answer, OVERALL_WEIGHTS["answer"]), (delivery, OVERALL_WEIGHTS["delivery"])])


def _mean(values):
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def interview_scores(rows):
    """All scores of one interview from its answer rows.
    Answer Effectiveness: every answer counts equally. Delivery (v3): the 14 criteria are checked once on the
    whole interview's measurements, Behavioral = met/7 x 100, Speech = met/7 x 100, Delivery = their average."""
    answer = _mean([answer_score(r) for r in rows])
    behavioral, speech = delivery_sections(combine_measures(rows))
    verbal, nonverbal = speech["score"], behavioral["score"]
    delivery = delivery_from(verbal, nonverbal)
    overall = overall_from(answer, delivery)
    return {"answer": answer, "verbal": verbal, "nonverbal": nonverbal, "delivery": delivery,
            "overall": overall, "profile": profile(answer, delivery),
            "behavioral_section": behavioral, "speech_section": speech}


# Performance profile: the two kinds of performance the panel asked to distinguish
PROFILES = {
    "ready": ("Interview-ready",
              "Your answers would work in a real interview and you delivered them well."),
    "content": ("Effective answers, delivery needs polish",
                "Your answers were direct and to the point, which is what interviewers look for. "
                "Work on how you say them (voice, eye contact) to make them stronger."),
    "delivery": ("Effective communicator, answers need substance",
                 "You spoke well, but your answers need to be more direct, specific or complete "
                 "to work in a real interview."),
    "practice": ("Keep practicing both",
                 "Focus first on answering directly with a real example, then on your delivery."),
}


def profile(answer, delivery):
    if answer is None:
        return None
    if delivery is None:
        return "ready" if answer >= PASS_MARK else "practice"
    good_answer, good_delivery = answer >= PASS_MARK, delivery >= PASS_MARK
    if good_answer and good_delivery:
        return "ready"
    if good_answer:
        return "content"
    if good_delivery:
        return "delivery"
    return "practice"


def attach_answer_scores(rows, version=RUBRIC_VERSION):
    """Add .answer_score, .verbal_score, .nonverbal_score and .delivery_score to each answer row (for reports).
    version: the rubric the interview was scored with, so an older report keeps its own numbers."""
    for r in rows:
        r["answer_score"] = answer_score(r) if r.get("directness_score") is not None else None
        if version == "v2":
            r["verbal_score"], r["nonverbal_score"] = v2_verbal_score(r), v2_nonverbal_score(r)
            r["delivery_score"] = delivery_from(r["verbal_score"], r["nonverbal_score"], V2_DELIVERY_WEIGHTS)
        else:
            r["verbal_score"], r["nonverbal_score"] = verbal_score(r), nonverbal_score(r)
            r["delivery_score"] = delivery_from(r["verbal_score"], r["nonverbal_score"])
    return rows


# ---------------------------------------------------------------- text for prompts and pages
def _anchors(levels):
    points = [0, 25, 50, 75, 100]
    return "; ".join(f"{p} = {text}" for p, text in reversed(list(zip(points, levels))))


def prompt_criteria():
    """The criteria block given to the AI, with the same level descriptions the human evaluators use."""
    lines = []
    for c in ANSWER_CRITERIA + [VERBAL_CRITERIA[3]]:
        lines.append(f"- {c['key']}: {c.get('question') or c['how']}\n    ({_anchors(c['levels'])})")
    return "\n".join(lines)


# For human evaluators (validation): the four Answer Effectiveness criteria plus grammar
def rater_criteria():
    return [(c["key"], c["label"], c.get("question") or c.get("how"), c["levels"])
            for c in ANSWER_CRITERIA + [VERBAL_CRITERIA[3]]]


def summary():
    """Everything the report page needs to explain the scoring."""
    return {"version": RUBRIC_VERSION, "versions": SCORED_VERSIONS, "overall": OVERALL_WEIGHTS,
            "delivery": DELIVERY_WEIGHTS, "v2_delivery": V2_DELIVERY_WEIGHTS,
            "answer_criteria": ANSWER_CRITERIA, "verbal": V2_VERBAL_CRITERIA, "nonverbal": V2_NONVERBAL_CRITERIA,
            "behavioral_criteria": [{**c, "target": threshold_text(c)} for c in BEHAVIORAL_CRITERIA],
            "speech_criteria": [{**c, "target": threshold_text(c)} for c in SPEECH_CRITERIA],
            "bands": BANDS, "band_ranges": band_ranges(), "pass_mark": PASS_MARK, "profiles": PROFILES}
