"""Validation: do the AI's answer scores agree with human experts?

Raters (teachers, HR practitioners) get accounts with role 'rater'. They score anonymous answers on the
same criteria as the AI (relevance, directness, structure, specific evidence, grammar) with a 1-5 rubric, without seeing
the AI's scores (blind rating). The admin's Validation tab compares them:
  - Pearson correlation (r) between AI and human scores, per criterion
  - Mean absolute difference (in points out of 100) and the share of answers within one rubric step
  - Agreement between the human raters themselves, when 2+ raters scored the same answer

Only answers from interviews whose consent includes review by evaluators (consent v1.3 or later) are shown,
never the demo account's, and raters never see the student's name, recording, scores or feedback.
"""
import csv
import io
import math
import random
from functools import wraps

from flask import render_template, request, redirect, url_for, flash, session, Response

import scoring

# Same criteria and level descriptions as the AI (scoring.py, rubric v2): the four Answer Effectiveness
# criteria (relevance, directness, structure, specific evidence) plus grammar.
CRITERIA = scoring.rater_criteria()
KEYS = [c[0] for c in CRITERIA]
RESEARCH_CONSENT_VERSIONS = ("v1.3",)     # consent versions that allow review by evaluators
DEMO_EMAIL = "demo@aimis.local"


def to_points(rubric):
    """1-5 rubric -> 0-100, the same scale as the AI (1 = 0, 2 = 25, 3 = 50, 4 = 75, 5 = 100)."""
    return (float(rubric) - 1) * 25


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def strength(r):
    """Common verbal labels for a correlation's strength."""
    if r is None:
        return "not enough data"
    a = abs(r)
    return ("very strong" if a >= 0.8 else "strong" if a >= 0.6 else "moderate" if a >= 0.4
            else "weak" if a >= 0.2 else "very weak")


def register(app, get_db):

    def role_required(role):
        def decorator(view):
            @wraps(view)
            def wrapped(*args, **kwargs):
                if "user_id" not in session:
                    flash("Please log in first.")
                    return redirect(url_for("login"))
                if session.get("role") != role:
                    flash("That page is only for " + ("evaluators." if role == "rater" else "administrators."))
                    return redirect(url_for("dashboard"))
                return view(*args, **kwargs)
            return wrapped
        return decorator

    def eligible_sql():
        marks = ", ".join(["%s"] * len(RESEARCH_CONSENT_VERSIONS))
        return (f"""FROM responses r
                   JOIN interview_questions iq ON iq.interview_question_id = r.interview_question_id
                   JOIN question_bank qb ON qb.question_id = iq.question_id
                   JOIN interviews i ON i.interview_id = iq.interview_id
                   JOIN users u ON u.user_id = i.user_id
                   JOIN nlp_analysis n ON n.response_id = r.response_id
                   WHERE r.transcript IS NOT NULL AND r.transcript <> '' AND u.email <> %s
                     AND EXISTS (SELECT 1 FROM consents c WHERE c.interview_id = i.interview_id
                                 AND c.consent_version IN ({marks}))""",
                [DEMO_EMAIL, *RESEARCH_CONSENT_VERSIONS])

    # ---------------------------------------------------------------- rater: score answers blind
    @role_required("rater")
    def rate():
        rater = session["user_id"]
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        if request.method == "POST":
            try:
                response_id = int(request.form["response_id"])
                values = [int(request.form[k]) for k in KEYS]
                if not all(1 <= v <= 5 for v in values):
                    raise ValueError
            except (KeyError, ValueError):
                flash(f"Choose a score from 1 to 5 for all {len(KEYS)} criteria.")
                conn.close()
                return redirect(url_for("rate_answers", r=request.form.get("response_id")))
            base, params = eligible_sql()
            cursor.execute(f"SELECT r.response_id {base} AND r.response_id = %s", params + [response_id])
            if not cursor.fetchone():
                conn.close()
                flash("That answer can't be rated.")
                return redirect(url_for("rate_answers"))
            cursor.execute("DELETE FROM human_ratings WHERE response_id = %s AND rater_id = %s", (response_id, rater))
            cursor.execute(f"""INSERT INTO human_ratings (response_id, rater_id, {", ".join(KEYS)}, comment)
                               VALUES (%s, %s, {", ".join(["%s"] * len(KEYS))}, %s)""",
                           (response_id, rater, *values, (request.form.get("comment") or "").strip()[:500] or None))
            conn.commit()
            flash("Saved. Here is the next answer.")
            conn.close()
            return redirect(url_for("rate_answers"))

        if request.args.get("skip"):
            skipped = set(session.get("rate_skipped", []))
            skipped.add(int(request.args["skip"]))
            session["rate_skipped"] = list(skipped)[-200:]
        skipped = session.get("rate_skipped", [])

        base, params = eligible_sql()
        cursor.execute(f"""SELECT COUNT(*) AS n {base}""", params)
        total = cursor.fetchone()["n"]
        cursor.execute("SELECT COUNT(*) AS n FROM human_ratings WHERE rater_id = %s", (rater,))
        done = cursor.fetchone()["n"]
        # Answers this rater hasn't scored; ones other raters already scored come first (overlap is needed
        # to measure agreement between raters), then the rest in random order
        cursor.execute(f"""SELECT r.response_id, r.transcript, qb.question_text, i.category, i.difficulty,
                                  (SELECT COUNT(*) FROM human_ratings h WHERE h.response_id = r.response_id) AS others
                           {base}
                             AND NOT EXISTS (SELECT 1 FROM human_ratings h
                                             WHERE h.response_id = r.response_id AND h.rater_id = %s)""",
                       params + [rater])
        todo = [a for a in cursor.fetchall() if a["response_id"] not in skipped]
        conn.close()
        answer = None
        if request.args.get("r"):
            answer = next((a for a in todo if str(a["response_id"]) == request.args["r"]), None)
        if not answer and todo:
            top = max(a["others"] for a in todo)
            answer = random.choice([a for a in todo if a["others"] == top])
        return render_template("rate.html", answer=answer, criteria=CRITERIA, total=total, done=done,
                               remaining=len(todo), skipped=len(skipped))

    # ---------------------------------------------------------------- admin: results
    def collect(cursor, ai=None):
        """AI vs human scores per answer (human = average of all raters), plus rater-vs-rater pairs.
        ai: only answers scored by this AI ('gemini' / 'ollama'), or None for all."""
        sql = f"""SELECT h.response_id, h.rater_id, {", ".join("h." + k for k in KEYS)},
                        {", ".join(f"n.{k}_score" for k in KEYS)},
                        i.category, COALESCE(e.scored_by, 'gemini') AS scored_by
                 FROM human_ratings h
                 JOIN nlp_analysis n ON n.response_id = h.response_id
                 JOIN responses r ON r.response_id = h.response_id
                 JOIN interview_questions iq ON iq.interview_question_id = r.interview_question_id
                 JOIN interviews i ON i.interview_id = iq.interview_id
                 LEFT JOIN evaluations e ON e.interview_id = i.interview_id
                 ORDER BY h.response_id, h.rater_id"""
        try:
            cursor.execute(sql)
        except Exception as e:
            if getattr(e, "errno", None) != 1054:    # no scored_by column yet: every answer counts as Gemini
                raise
            cursor.execute(sql.replace("COALESCE(e.scored_by, 'gemini')", "'gemini'"))
        rows = [r for r in cursor.fetchall() if not ai or r["scored_by"] == ai]
        answers = {}
        for row in rows:
            a = answers.setdefault(row["response_id"], {"category": row["category"], "scored_by": row["scored_by"],
                                                        "ai": {}, "raters": {}})
            for k in KEYS:
                a["ai"][k] = float(row[f"{k}_score"]) if row[f"{k}_score"] is not None else None
            a["raters"][row["rater_id"]] = {k: int(row[k]) if row[k] is not None else None for k in KEYS}
        return answers

    def statistics(answers):
        results = []
        answer_keys = [c["key"] for c in scoring.ANSWER_CRITERIA]
        for key, label, _, _ in CRITERIA + [("overall", "Answer effectiveness (weighted, as in the report)", "", [])]:
            ai, human = [], []
            for a in answers.values():
                keys = answer_keys if key == "overall" else [key]
                given = {k: [r[k] for r in a["raters"].values() if r.get(k) is not None] for k in keys}
                if any(a["ai"].get(k) is None or not given[k] for k in keys):
                    continue      # e.g. rated with the older rubric that had no directness / specificity
                if key == "overall":
                    ai.append(scoring.answer_score({f"{k}_score": a["ai"][k] for k in keys}))
                    human.append(scoring.answer_score({f"{k}_score": to_points(sum(given[k]) / len(given[k]))
                                                       for k in keys}))
                else:
                    ai.append(a["ai"][key])
                    human.append(to_points(sum(given[key]) / len(given[key])))
            n = len(ai)
            r = pearson(ai, human)
            diffs = [abs(x - y) for x, y in zip(ai, human)]
            results.append({
                "key": key, "label": label, "n": n, "r": r, "strength": strength(r),
                "mae": sum(diffs) / n if n else None,
                "within": 100 * sum(d <= 25 for d in diffs) / n if n else None,
                "ai_mean": sum(ai) / n if n else None, "human_mean": sum(human) / n if n else None,
            })
        # Agreement between human raters (answers with 2+ raters)
        multi = [a for a in answers.values() if len(a["raters"]) >= 2]
        inter = []
        for key, label, _, _ in CRITERIA:
            pairs = []
            for a in multi:
                vals = [r[key] for r in a["raters"].values() if r.get(key) is not None]
                pairs += [(x, y) for i, x in enumerate(vals) for y in vals[i + 1:]]
            if pairs:
                inter.append({"label": label, "pairs": len(pairs),
                              "exact": 100 * sum(x == y for x, y in pairs) / len(pairs),
                              "adjacent": 100 * sum(abs(x - y) <= 1 for x, y in pairs) / len(pairs),
                              "r": pearson([p[0] for p in pairs], [p[1] for p in pairs])})
        return results, inter, len(multi)

    @role_required("admin")
    def admin_validation():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        if request.method == "POST":
            email = (request.form.get("email") or "").strip().lower()
            action = request.form.get("action")
            cursor.execute("SELECT user_id, role FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            if not user:
                flash(f"No account uses {email}. Ask the evaluator to register first, then add them here.")
            elif user["role"] == "admin":
                flash("Admins can't be evaluators. Use a separate account for rating.")
            elif action == "add":
                cursor.execute("UPDATE users SET role = 'rater' WHERE user_id = %s", (user["user_id"],))
                conn.commit()
                flash(f"{email} is now an evaluator. They'll see 'Rate answers' after logging in again.")
            elif action == "remove":
                cursor.execute("UPDATE users SET role = 'student' WHERE user_id = %s AND role = 'rater'",
                               (user["user_id"],))
                conn.commit()
                flash(f"{email} is no longer an evaluator. Their ratings are kept.")
            conn.close()
            return redirect(url_for("admin_validation"))

        ai = request.args.get("ai") if request.args.get("ai") in ("gemini", "ollama") else None
        try:
            answers = collect(cursor, ai)
            counts = {"all": len(collect(cursor)), "gemini": len(collect(cursor, "gemini")),
                      "ollama": len(collect(cursor, "ollama"))}
            ready = True
        except Exception as e:
            if getattr(e, "errno", None) != 1146:
                raise
            answers, ready, counts = {}, False, {"all": 0, "gemini": 0, "ollama": 0}
        results, inter, multi = statistics(answers)
        raters, eligible = [], 0
        if ready:
            cursor.execute("""SELECT u.user_id, u.full_name, u.email,
                                     (SELECT COUNT(*) FROM human_ratings h WHERE h.rater_id = u.user_id) AS rated
                              FROM users u WHERE u.role = 'rater' ORDER BY u.full_name""")
            raters = cursor.fetchall()
            base, params = eligible_sql()
            cursor.execute(f"SELECT COUNT(*) AS n {base}", params)
            eligible = cursor.fetchone()["n"]
        conn.close()
        return render_template("admin/validation.html", active="validation", ai=ai, counts=counts, results=results, inter=inter, multi=multi,
                               raters=raters, answers=len(answers), eligible=eligible, ready=ready,
                               consent_versions=", ".join(RESEARCH_CONSENT_VERSIONS))

    @role_required("admin")
    def admin_validation_csv():
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        answers = collect(cursor)
        conn.close()
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["answer", "category", "scored_by", "rater"] + [f"ai_{k}" for k in KEYS] +
                        [f"human_{k}_1to5" for k in KEYS] + [f"human_{k}_0to100" for k in KEYS])
        for n, (response_id, a) in enumerate(sorted(answers.items()), start=1):
            for rater_no, (rater_id, r) in enumerate(sorted(a["raters"].items()), start=1):
                writer.writerow([f"A{n}", a["category"], a["scored_by"], f"R{rater_id}"] +
                                [a["ai"][k] for k in KEYS] + [r[k] for k in KEYS] +
                                [to_points(r[k]) if r[k] is not None else None for k in KEYS])
        return Response("﻿" + out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=aimis_validation.csv"})

    app.add_url_rule("/rate", "rate_answers", rate, methods=["GET", "POST"])
    app.add_url_rule("/admin/validation", "admin_validation", admin_validation, methods=["GET", "POST"])
    app.add_url_rule("/admin/validation.csv", "admin_validation_csv", admin_validation_csv)
