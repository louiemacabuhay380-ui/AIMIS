"""Personalized feedback: per-answer feedback, sub-skill labels, and comparison with past interviews."""
import re
from ai_service import SKILL_LABELS

RATINGS = ("strong", "okay", "weak")
_SKILL_LOOKUP = {s.lower(): s for s in SKILL_LABELS}


def _num(value):
    return float(value) if value is not None else None


def _missing_table(error):
    """True if MySQL says a table doesn't exist yet (schema block 7 not run)."""
    return getattr(error, "errno", None) == 1146


def _plain(text):
    """Lowercase words only, so a quote still matches if the AI changed punctuation or spacing."""
    return " ".join(re.sub(r"[^\w\s']", " ", (text or "").lower()).split())


def clean_answer_feedback(item, transcript):
    """Tidy one answer's AI feedback; drop anything the AI made up or got wrong."""
    item = item or {}
    feedback = str(item.get("feedback") or "").strip()[:1000]
    better = str(item.get("better_answer") or "").strip()[:1000]
    quote = str(item.get("weak_quote") or "").strip().strip('"').strip()[:300]
    # Keep the quote only if those words really appear in the answer (small local models sometimes invent one)
    if quote and _plain(quote)[:40] not in _plain(transcript):
        quote = ""

    skills, seen = [], set()
    for s in item.get("skills") or []:
        if not isinstance(s, dict):
            continue
        name = _SKILL_LOOKUP.get(str(s.get("skill") or "").strip().lower())
        rating = str(s.get("rating") or "").strip().lower()
        if not name or rating not in RATINGS or name in seen:
            continue
        seen.add(name)
        skills.append({"skill": name, "rating": rating, "reason": str(s.get("reason") or "").strip()[:300]})
    good = str(item.get("good") or "").strip()[:600]
    good_quote = str(item.get("good_quote") or "").strip().strip('"').strip()[:300]
    if good_quote and _plain(good_quote)[:40] not in _plain(transcript):
        good_quote = ""
    example = str(item.get("example") or "").strip()[:600]
    return {"feedback": feedback, "weak_quote": quote, "better_answer": better, "skills": skills[:4],
            "good": good, "good_quote": good_quote, "example": example}


def save_answer_feedback(cursor, qa_list, ai_answers):
    """Save per-answer feedback and skill labels. Returns False if the tables don't exist yet."""
    ids = [qa["response_id"] for qa in qa_list]
    if not ids:
        return True
    placeholders = ", ".join(["%s"] * len(ids))
    try:
        cursor.execute(f"DELETE FROM answer_feedback WHERE response_id IN ({placeholders})", ids)
        cursor.execute(f"DELETE FROM skill_labels WHERE response_id IN ({placeholders})", ids)
    except Exception as e:
        if _missing_table(e):
            print("answer_feedback / skill_labels tables are missing: run block 7 of schema_updates.sql")
            return False
        raise

    for qa, item in zip(qa_list, ai_answers or []):
        fb = clean_answer_feedback(item, qa.get("transcript"))
        cursor.execute("""INSERT INTO answer_feedback (response_id, feedback, weak_quote, better_answer)
                          VALUES (%s, %s, %s, %s)""",
                       (qa["response_id"], fb["feedback"], fb["weak_quote"], fb["better_answer"]))
        for s in fb["skills"]:
            cursor.execute("""INSERT INTO skill_labels (response_id, skill, rating, reason)
                              VALUES (%s, %s, %s, %s)""",
                           (qa["response_id"], s["skill"], s["rating"], s["reason"]))
    return True


def attach_answer_feedback(cursor, answers):
    """Add .feedback, .weak_quote, .better_answer and .skills to each answer row (empty if none)."""
    for a in answers:
        a.setdefault("answer_feedback", None)
        a.setdefault("weak_quote", None)
        a.setdefault("better_answer", None)
        a.setdefault("skills", [])
    ids = [a["response_id"] for a in answers if a.get("response_id")]
    if not ids:
        return answers
    placeholders = ", ".join(["%s"] * len(ids))
    try:
        cursor.execute(f"SELECT * FROM answer_feedback WHERE response_id IN ({placeholders})", ids)
        fb = {row["response_id"]: row for row in cursor.fetchall()}
        cursor.execute(f"""SELECT response_id, skill, rating, reason FROM skill_labels
                           WHERE response_id IN ({placeholders}) ORDER BY label_id""", ids)
        labels = cursor.fetchall()
    except Exception as e:
        if _missing_table(e):
            return answers
        raise
    order = {"weak": 0, "okay": 1, "strong": 2}
    for a in answers:
        row = fb.get(a.get("response_id"))
        if row:
            a["answer_feedback"] = row["feedback"] or None
            a["weak_quote"] = row["weak_quote"] or None
            a["better_answer"] = row["better_answer"] or None
        a["skills"] = sorted([l for l in labels if l["response_id"] == a.get("response_id")],
                             key=lambda l: order.get(l["rating"], 3))
    return answers


def skill_tally(cursor, user_id, before_interview_id=None):
    """How often each sub-skill was rated strong / okay / weak across the user's answers."""
    sql = """SELECT sl.skill, sl.rating, COUNT(*) AS n
             FROM skill_labels sl
             JOIN responses r ON r.response_id = sl.response_id
             JOIN interview_questions iq ON iq.interview_question_id = r.interview_question_id
             JOIN interviews i ON i.interview_id = iq.interview_id
             WHERE i.user_id = %s"""
    params = [user_id]
    if before_interview_id:
        sql += " AND i.interview_id < %s"
        params.append(before_interview_id)
    sql += " GROUP BY sl.skill, sl.rating"
    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    except Exception as e:
        if _missing_table(e):
            return {}
        raise
    tally = {}
    for r in rows:
        tally.setdefault(r["skill"], {"strong": 0, "okay": 0, "weak": 0})[r["rating"]] = int(r["n"])
    return tally


def weakest_skill(cursor, user_id):
    """The sub-skill most often rated weak (name, times), or None."""
    tally = skill_tally(cursor, user_id)
    ranked = sorted(((v["weak"], k) for k, v in tally.items() if v["weak"]), reverse=True)
    return {"name": ranked[0][1], "times": ranked[0][0]} if ranked else None


def past_scores(cursor, user_id, before_interview_id):
    """Scores of the user's scored interviews before this one, oldest first."""
    cursor.execute("""SELECT i.interview_id, i.category, i.difficulty, i.completed_at,
                             e.overall_score, e.response_quality_score,
                             e.speech_performance_score, e.behavioral_score
                      FROM interviews i JOIN evaluations e ON e.interview_id = i.interview_id
                      WHERE i.user_id = %s AND i.interview_id < %s
                      ORDER BY i.interview_id""", (user_id, before_interview_id))
    return cursor.fetchall()


PARTS = [("Overall", "overall_score"), ("Response quality", "response_quality_score"),
         ("Speech", "speech_performance_score"), ("Behavior", "behavioral_score")]


def _average(rows, key):
    vals = [_num(r[key]) for r in rows if r.get(key) is not None]
    return round(sum(vals) / len(vals)) if vals else None


def history_summary(cursor, user_id, interview_id):
    """Short text about earlier interviews, given to the AI so its feedback can mention progress."""
    past = past_scores(cursor, user_id, interview_id)
    if not past:
        return ""
    lines = [f"- {len(past)} earlier scored interview(s). Averages: " + ", ".join(
        f"{label.lower()} {_average(past, key)}%" for label, key in PARTS if _average(past, key) is not None)]
    last = past[-1]
    when = last["completed_at"].strftime("%b %d") if last.get("completed_at") else "earlier"
    lines.append(f"- Most recent ({last['category']}, {when}): " + ", ".join(
        f"{label.lower()} {round(_num(last[key]))}%" for label, key in PARTS if last.get(key) is not None))
    tally = skill_tally(cursor, user_id, before_interview_id=interview_id)
    weak = sorted(((v["weak"], k) for k, v in tally.items() if v["weak"]), reverse=True)[:3]
    strong = sorted(((v["strong"], k) for k, v in tally.items() if v["strong"]), reverse=True)[:2]
    if weak:
        lines.append("- Sub-skills often rated weak before: " + ", ".join(f"{k} ({n} answers)" for n, k in weak))
    if strong:
        lines.append("- Sub-skills often rated strong before: " + ", ".join(f"{k} ({n} answers)" for n, k in strong))
    return "\n".join(lines)


def progress_compare(cursor, user_id, interview_id, evaluation):
    """This interview's scores next to the user's average before it (for the report page)."""
    if not evaluation:
        return None
    past = past_scores(cursor, user_id, interview_id)
    if not past:
        return None
    rows = []
    for label, key in PARTS:
        now, before = _num(evaluation.get(key)), _average(past, key)
        if now is None or before is None:
            continue
        rows.append({"label": label, "now": round(now), "before": before, "diff": round(now) - before})
    return {"count": len(past), "rows": rows} if rows else None


# ---------------------------------------------------------------- whole-interview feedback, item by item
# Each item points to one answer: what was good or weak, the student's own words, a fix and an example.

FILLER_WORDS = re.compile(r"\b(um+|uh+m*|erm|ah+|eh+|ano|parang|kasi|you know|like)\b", re.I)
DELIVERY_LOW = 60   # camera scores below this get their own feedback item


def _text(value, limit=600):
    return " ".join(str(value or "").split())[:limit]


def _answer_no(value, total):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= total else None


def _checked_quote(quote, transcript):
    """Keep a quote only if the student really said it (small AI models sometimes make one up)."""
    quote = _text(quote, 300).strip('"“”\' ')
    return quote if quote and _plain(quote)[:40] in _plain(transcript) else ""


def _short_question(text, words=9):
    parts = (text or "").split()
    return " ".join(parts[:words]) + ("…" if len(parts) > words else "")


def _ai_items(result, qa_list):
    """The AI's strengths and improvements, cleaned and checked against the real answers."""
    total = len(qa_list)
    items = []
    for kind, key in (("strength", "strengths"), ("improve", "improvements")):
        raw = result.get(key)
        if not isinstance(raw, list):
            continue
        for r in raw[:3]:
            if not isinstance(r, dict):
                continue
            n = _answer_no(r.get("answer"), total)
            point = _text(r.get("point"))
            if not n or not point:
                continue
            items.append({"kind": kind, "answer_no": n, "point": point,
                          "quote": _checked_quote(r.get("quote"), qa_list[n - 1].get("transcript")),
                          "fix": _text(r.get("fix")) if kind == "improve" else "",
                          "example": _text(r.get("example")) if kind == "improve" else ""})
    return items


def _fallback_items(result, qa_list, have_strength, have_improve):
    """If the AI gave no usable items (e.g. a small local model), build them from the per-answer feedback."""
    rated = []
    for n, (qa, a) in enumerate(zip(qa_list, result.get("answers") or []), start=1):
        if not isinstance(a, dict):
            continue
        scores = [float(a.get(k) or 0) for k in ("relevance", "clarity", "completeness", "grammar")]
        rated.append((sum(scores) / 4, n, qa, clean_answer_feedback(a, qa.get("transcript"))))
    rated.sort(key=lambda t: t[0])
    items = []
    if not have_improve:
        for avg, n, qa, fb in rated[:2]:
            if fb["feedback"] and avg < 80:
                items.append({"kind": "improve", "answer_no": n, "point": fb["feedback"], "quote": fb["weak_quote"],
                              "fix": fb["better_answer"], "example": ""})
    if not have_strength and rated:
        avg, n, qa, fb = rated[-1]
        if fb["feedback"] and avg >= 60:
            items.append({"kind": "strength", "answer_no": n, "point": fb["feedback"], "quote": "",
                          "fix": "", "example": ""})
    return items


def _delivery_items(qa_list):
    """Filler words and body language, with the exact answer and numbers (never general)."""
    items = []
    fillers = [(int(qa.get("filler_word_count") or 0), n, qa) for n, qa in enumerate(qa_list, start=1)]
    total = sum(f[0] for f in fillers)
    if total >= 3:
        count, n, qa = max(fillers, key=lambda f: f[0])
        found = {}
        for m in FILLER_WORDS.finditer(qa.get("transcript") or ""):
            word = m.group(0).lower()
            found[word] = found.get(word, 0) + 1
        words = ", ".join(f'"{w}"' for w, c in sorted(found.items(), key=lambda kv: -kv[1])[:3])
        quote = ""
        said = (qa.get("transcript") or "").split()
        for k, w in enumerate(said):           # a few words around the first filler, exactly as said
            if FILLER_WORDS.fullmatch(re.sub(r"[^\w']", "", w)):
                quote = " ".join(said[max(0, k - 6):k + 7])
                break
        items.append({"kind": "delivery", "answer_no": n,
                      "point": f"You used {total} filler words in this interview, most in answer {n} ({count} times)"
                               + (f", for example {words}." if words else "."),
                      "quote": quote,
                      "fix": f"In answer {n}, when you need a moment to think, stop and pause silently for one second "
                             "instead of saying a filler. Say your main point first, then explain.",
                      "example": ""})

    cam = [(n, qa) for n, qa in enumerate(qa_list, start=1) if qa.get("eye_contact_score") is not None]
    if cam:
        n, qa = min(cam, key=lambda c: float(c[1]["eye_contact_score"]))
        eye = round(float(qa["eye_contact_score"]))
        if eye < DELIVERY_LOW:
            items.append({"kind": "delivery", "answer_no": n,
                          "point": f"Your eye contact dropped to {eye}% in answer {n} "
                                   f"(\"{_short_question(qa.get('question_text'))}\"), so you looked away for much of it.",
                          "quote": "",
                          "fix": "Look at the camera lens (not your own video) while you talk. It's fine to glance away "
                                 "for a second to think, then come back to the lens.",
                          "example": ""})
        n, qa = min(cam, key=lambda c: float(c[1].get("facial_expression_score") or 0))
        face = round(float(qa.get("facial_expression_score") or 0))
        if face < DELIVERY_LOW:
            items.append({"kind": "delivery", "answer_no": n,
                          "point": f"Your face looked tense or serious in answer {n} (facial expression {face}%).",
                          "quote": "",
                          "fix": f"Smile briefly when you start answer {n} and when you talk about a good result.",
                          "example": ""})
        touch = [(n, qa) for n, qa in cam if qa.get("face_touch_ratio") is not None]
        if touch:
            n, qa = max(touch, key=lambda c: float(c[1]["face_touch_ratio"]))
            t = round(float(qa["face_touch_ratio"]))
            if t >= 15:
                items.append({"kind": "delivery", "answer_no": n,
                              "point": f"You touched your face or hair {t}% of the time during answer {n}, which can look nervous.",
                              "quote": "",
                              "fix": "Rest your hands on the table or in your lap, and use them only to stress a point.",
                              "example": ""})
        n, qa = min(cam, key=lambda c: float(c[1].get("face_visibility_score") or 0))
        vis = round(float(qa.get("face_visibility_score") or 0))
        if vis < 70:
            items.append({"kind": "delivery", "answer_no": n,
                          "point": f"Your face was only visible {vis}% of the time in answer {n}.",
                          "quote": "",
                          "fix": "Sit centered in front of the camera with a light in front of you, not behind.",
                          "example": ""})
    return items


def build_feedback_items(result, qa_list):
    """All feedback items for one interview, in the order they are shown."""
    items = _ai_items(result, qa_list)
    items += _fallback_items(result, qa_list,
                             have_strength=any(i["kind"] == "strength" for i in items),
                             have_improve=any(i["kind"] == "improve" for i in items))
    items += _delivery_items(qa_list)
    # Cards for each answer in "Your Answers": what worked, and what to fix with an example
    for n, (qa, raw) in enumerate(zip(qa_list, result.get("answers") or []), start=1):
        fb = clean_answer_feedback(raw if isinstance(raw, dict) else {}, qa.get("transcript"))
        if fb["good"]:
            items.append({"kind": "answer_good", "answer_no": n, "point": fb["good"], "quote": fb["good_quote"],
                          "fix": "", "example": ""})
        if fb["feedback"] or fb["better_answer"]:
            items.append({"kind": "answer_fix", "answer_no": n, "point": fb["feedback"], "quote": fb["weak_quote"],
                          "fix": fb["better_answer"], "example": fb["example"]})
    progress = _text(result.get("progress_note"))
    if progress:
        items.append({"kind": "progress", "answer_no": None, "point": progress, "quote": "", "fix": "", "example": ""})
    focus = _text(result.get("next_focus"))
    if focus:
        items.append({"kind": "next", "answer_no": None, "point": focus, "quote": "", "fix": "", "example": ""})
    order = {"progress": 0, "strength": 1, "improve": 2, "delivery": 3, "next": 4, "answer_good": 5, "answer_fix": 6}
    return sorted(items, key=lambda i: order[i["kind"]])


def feedback_text(items):
    """Plain-text version for the feedback table (used by the chatbot, admin pages and older screens)."""
    def joined(kinds, field="point"):
        return " ".join(f"In answer {i['answer_no']}: {i[field]}"
                        if i["answer_no"] and "answer " + str(i["answer_no"]) not in i[field].lower() else i[field]
                        for i in items if i["kind"] in kinds and i[field])
    strengths = joined(("strength",))
    areas = joined(("improve", "delivery"))
    tips = joined(("improve", "delivery"), "fix")
    nxt = [i["point"] for i in items if i["kind"] == "next"]
    if nxt:
        tips = (tips + " " if tips else "") + "Next: " + nxt[0]
    return strengths, areas, tips


def save_feedback_items(cursor, interview_id, items):
    try:
        cursor.execute("DELETE FROM feedback_items WHERE interview_id = %s", (interview_id,))
    except Exception as e:
        if _missing_table(e):
            print("feedback_items table is missing: run block 8 of schema_updates.sql")
            return False
        raise
    for n, i in enumerate(items):
        cursor.execute("""INSERT INTO feedback_items (interview_id, kind, answer_no, point, quote, fix, example, sort_order)
                          VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                       (interview_id, i["kind"], i["answer_no"], i["point"], i["quote"], i["fix"], i["example"], n))
    return True


def load_feedback_items(cursor, interview_id):
    try:
        cursor.execute("SELECT * FROM feedback_items WHERE interview_id = %s ORDER BY sort_order", (interview_id,))
        return cursor.fetchall()
    except Exception as e:
        if _missing_table(e):
            return []
        raise
