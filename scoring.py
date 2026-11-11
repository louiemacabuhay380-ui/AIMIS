"""AIMIS scoring rubric (v2, after the panel review).

Every criterion, weight and level description lives here, so the AI prompt, the human evaluators' rubric,
the report page and the research paper all use the same definitions. Change a weight here and it changes
everywhere.

Two separate scores (panel comment 10):
  1. Answer Effectiveness   = WHAT was said: would this answer work in a real interview?
                              Direct, relevant, structured and specific, even if the delivery is not polished.
  2. Communication Delivery = HOW it was said: an effective communicator's voice, language and body language.
  Overall Interview Readiness = 60% Answer Effectiveness + 40% Communication Delivery.

All scores are 0 to 100. The AI uses the same five levels as the human evaluators:
  level 5 = 100, level 4 = 75, level 3 = 50, level 2 = 25, level 1 = 0 (scores in between are allowed).
"""

RUBRIC_VERSION = "v2"

# ---------------------------------------------------------------- weights
OVERALL_WEIGHTS = {"answer": 60, "delivery": 40}      # Overall Interview Readiness
DELIVERY_WEIGHTS = {"verbal": 60, "nonverbal": 40}     # inside Communication Delivery

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
VERBAL_CRITERIA = [
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
NONVERBAL_CRITERIA = [
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


def verbal_score(row):
    return weighted([(row.get(c["source"]), c["weight"]) for c in VERBAL_CRITERIA])


def nonverbal_score(row):
    if row.get("eye_contact_score") is None:      # no camera for this answer
        return None
    return weighted([(row.get(c["source"]), c["weight"]) for c in NONVERBAL_CRITERIA])


def delivery_from(verbal, nonverbal):
    return weighted([(verbal, DELIVERY_WEIGHTS["verbal"]), (nonverbal, DELIVERY_WEIGHTS["nonverbal"])])


def overall_from(answer, delivery):
    return weighted([(answer, OVERALL_WEIGHTS["answer"]), (delivery, OVERALL_WEIGHTS["delivery"])])


def _mean(values):
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def interview_scores(rows):
    """All scores of one interview from its answer rows. Every answer counts equally."""
    answer = _mean([answer_score(r) for r in rows])
    verbal = _mean([verbal_score(r) for r in rows])
    nonverbal = _mean([nonverbal_score(r) for r in rows])
    delivery = delivery_from(verbal, nonverbal)
    overall = overall_from(answer, delivery)
    return {"answer": answer, "verbal": verbal, "nonverbal": nonverbal, "delivery": delivery,
            "overall": overall, "profile": profile(answer, delivery)}


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


def attach_answer_scores(rows):
    """Add .answer_score, .verbal_score, .nonverbal_score and .delivery_score to each answer row (for reports)."""
    for r in rows:
        r["answer_score"] = answer_score(r) if r.get("directness_score") is not None else None
        r["verbal_score"] = verbal_score(r)
        r["nonverbal_score"] = nonverbal_score(r)
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
    return {"version": RUBRIC_VERSION, "overall": OVERALL_WEIGHTS, "delivery": DELIVERY_WEIGHTS,
            "answer_criteria": ANSWER_CRITERIA, "verbal": VERBAL_CRITERIA, "nonverbal": NONVERBAL_CRITERIA,
            "bands": BANDS, "band_ranges": band_ranges(), "pass_mark": PASS_MARK, "profiles": PROFILES}
