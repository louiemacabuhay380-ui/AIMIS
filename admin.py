"""
AIMIS admin panel: overview, users, interview records (with CSV export), and questions.

Admins log in on the normal login page; accounts with role = 'admin' are sent here.
Make the first admin in SQLyog:
    UPDATE users SET role = 'admin' WHERE email = 'your@email.com';

Privacy: admins see scores and feedback only, never transcripts or recordings.
"""
import csv
import io
import secrets
import string
from datetime import date, timedelta
from functools import wraps

from flask import render_template, request, redirect, url_for, flash, session, Response
from werkzeug.security import generate_password_hash

PAGE_SIZE = 30
DIFFICULTIES = ["Beginner", "Intermediate", "Advanced"]
WEAK = 60   # a score below this counts as "needs work" on the overview


def register(app, get_db, load_report, generate_questions):

    # ------------------------------------------------------------------ helpers
    def admin_required(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                flash("Please log in first.")
                return redirect(url_for("login"))
            if session.get("role") != "admin":
                flash("That page is for administrators only.")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return wrapper

    def db():
        conn = get_db()
        return conn, conn.cursor(dictionary=True)

    def categories(cursor):
        cursor.execute("SELECT DISTINCT category FROM question_bank ORDER BY category")
        return [r["category"] for r in cursor.fetchall()]

    def num(v):
        return float(v) if v is not None else None

    def safe_next(default):
        """Only go back to a page on this site (blocks redirects to other websites)."""
        nxt = request.form.get("next") or ""
        return nxt if nxt.startswith("/") and not nxt.startswith("//") else default

    def interview_filters(args):
        """SQL WHERE clause + values from the filter bar (shared by the list and the CSV)."""
        where, values = ["1 = 1"], []
        if args.get("category"):
            where.append("i.category = %s"); values.append(args["category"])
        if args.get("difficulty"):
            where.append("i.difficulty = %s"); values.append(args["difficulty"])
        if args.get("status"):
            where.append("i.status = %s"); values.append(args["status"])
        if args.get("date_from"):
            where.append("DATE(i.started_at) >= %s"); values.append(args["date_from"])
        if args.get("date_to"):
            where.append("DATE(i.started_at) <= %s"); values.append(args["date_to"])
        if args.get("q"):
            where.append("(u.full_name LIKE %s OR u.email LIKE %s)")
            values += [f"%{args['q']}%", f"%{args['q']}%"]
        if args.get("user_id"):
            where.append("i.user_id = %s"); values.append(args["user_id"])
        return " AND ".join(where), values

    # ------------------------------------------------------------------ overview
    @admin_required
    def admin_overview():
        conn, cursor = db()
        cursor.execute("SELECT COUNT(*) AS n FROM users WHERE role IS NULL OR role <> 'admin'")
        students = cursor.fetchone()["n"]
        cursor.execute("""SELECT COUNT(DISTINCT user_id) AS n FROM interviews
                          WHERE started_at >= NOW() - INTERVAL 7 DAY""")
        active_week = cursor.fetchone()["n"]
        cursor.execute("""SELECT COUNT(*) AS total,
                                 SUM(completed_at >= NOW() - INTERVAL 7 DAY) AS week
                          FROM interviews WHERE status = 'completed'""")
        done = cursor.fetchone()
        cursor.execute("""SELECT AVG(e.overall_score) AS overall, AVG(e.response_quality_score) AS quality,
                                 AVG(e.speech_performance_score) AS speech, AVG(e.behavioral_score) AS behavior,
                                 COUNT(*) AS scored
                          FROM evaluations e JOIN interviews i ON i.interview_id = e.interview_id""")
        avg = cursor.fetchone()

        # Completed interviews per day, last 14 days (days with none show as 0)
        cursor.execute("""SELECT DATE(completed_at) AS d, COUNT(*) AS n FROM interviews
                          WHERE status = 'completed' AND completed_at >= CURDATE() - INTERVAL 13 DAY
                          GROUP BY DATE(completed_at)""")
        per_day = {r["d"]: r["n"] for r in cursor.fetchall()}
        days = [date.today() - timedelta(days=13 - k) for k in range(14)]
        daily = [{"label": d.strftime("%b %d"), "short": d.strftime("%a")[0], "n": int(per_day.get(d, 0))}
                 for d in days]
        daily_max = max([d["n"] for d in daily] + [1])

        # Categories: how often practiced and the average score
        cursor.execute("""SELECT i.category, COUNT(*) AS n, AVG(e.overall_score) AS avg_score
                          FROM interviews i LEFT JOIN evaluations e ON e.interview_id = i.interview_id
                          WHERE i.status = 'completed'
                          GROUP BY i.category ORDER BY n DESC""")
        cats = cursor.fetchall()
        cat_max = max([c["n"] for c in cats] + [1])

        # Common weak areas: share of scored interviews where each part was below 60
        cursor.execute(f"""SELECT COUNT(*) AS scored,
                                  SUM(response_quality_score < {WEAK}) AS quality,
                                  SUM(speech_performance_score < {WEAK}) AS speech,
                                  SUM(behavioral_score < {WEAK}) AS behavior,
                                  SUM(behavioral_score IS NOT NULL) AS with_camera
                           FROM evaluations""")
        w = cursor.fetchone()
        cursor.execute(f"""SELECT COUNT(*) AS n, SUM(eye < {WEAK}) AS low_eye, SUM(fillers >= 3) AS many_fillers
                           FROM (SELECT iq.interview_id, AVG(b.eye_contact_score) AS eye,
                                        AVG(s.filler_word_count) AS fillers
                                 FROM interview_questions iq
                                 JOIN responses r ON r.interview_question_id = iq.interview_question_id
                                 LEFT JOIN behavior_analysis b ON b.response_id = r.response_id
                                 LEFT JOIN speech_analysis s ON s.response_id = r.response_id
                                 GROUP BY iq.interview_id) per_interview""")
        d = cursor.fetchone()
        scored = int(w["scored"] or 0)
        camera = int(w["with_camera"] or 0)
        weak = []
        if scored:
            weak = [
                ("Answer quality below 60", int(w["quality"] or 0), scored),
                ("Speech delivery below 60", int(w["speech"] or 0), scored),
                ("Body language below 60", int(w["behavior"] or 0), camera),
                ("Eye contact below 60%", int(d["low_eye"] or 0), camera),
                ("3 or more filler words per answer", int(d["many_fillers"] or 0), scored),
            ]
            weak = [{"label": l, "n": n, "of": of, "pct": round(n * 100 / of) if of else 0} for l, n, of in weak]

        cursor.execute("""SELECT i.interview_id, i.category, i.difficulty, i.completed_at, u.full_name,
                                 e.overall_score
                          FROM interviews i JOIN users u ON u.user_id = i.user_id
                          LEFT JOIN evaluations e ON e.interview_id = i.interview_id
                          WHERE i.status = 'completed'
                          ORDER BY i.completed_at DESC LIMIT 8""")
        recent = cursor.fetchall()
        pending = 0
        try:
            cursor.execute("SELECT COUNT(*) AS n FROM question_bank WHERE review_status = 'pending'")
            pending = cursor.fetchone()["n"]
        except Exception:
            pass   # the review column isn't added yet (schema block 6)
        conn.close()
        return render_template("admin/overview.html", active="overview",
                               stats={"students": students, "active_week": active_week,
                                      "done": int(done["total"] or 0), "done_week": int(done["week"] or 0),
                                      "overall": num(avg["overall"]), "quality": num(avg["quality"]),
                                      "speech": num(avg["speech"]), "behavior": num(avg["behavior"]),
                                      "scored": int(avg["scored"] or 0)},
                               daily=daily, daily_max=daily_max, cats=cats, cat_max=cat_max,
                               weak=weak, recent=recent, pending=pending)

    # ------------------------------------------------------------------ users
    @admin_required
    def admin_users():
        q = request.args.get("q", "").strip()
        conn, cursor = db()
        sql = """SELECT u.*, COALESCE(s.total, 0) AS total, COALESCE(s.done, 0) AS done, s.last_at, a.avg_score
                 FROM users u
                 LEFT JOIN (SELECT user_id, COUNT(*) AS total, SUM(status = 'completed') AS done,
                                   MAX(started_at) AS last_at
                            FROM interviews GROUP BY user_id) s ON s.user_id = u.user_id
                 LEFT JOIN (SELECT i.user_id, AVG(e.overall_score) AS avg_score
                            FROM interviews i JOIN evaluations e ON e.interview_id = i.interview_id
                            GROUP BY i.user_id) a ON a.user_id = u.user_id"""
        values = []
        if q:
            sql += " WHERE u.full_name LIKE %s OR u.email LIKE %s"
            values = [f"%{q}%", f"%{q}%"]
        sql += " ORDER BY (u.role = 'admin') DESC, u.full_name"
        cursor.execute(sql, values)
        users = cursor.fetchall()
        conn.close()
        return render_template("admin/users.html", active="users", users=users, q=q)

    @admin_required
    def admin_user(user_id):
        conn, cursor = db()
        cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            conn.close()
            flash("User not found.")
            return redirect(url_for("admin_users"))
        cursor.execute("""SELECT i.*, e.overall_score, e.response_quality_score, e.speech_performance_score,
                                 e.behavioral_score
                          FROM interviews i LEFT JOIN evaluations e ON e.interview_id = i.interview_id
                          WHERE i.user_id = %s ORDER BY i.started_at DESC""", (user_id,))
        interviews = cursor.fetchall()
        conn.close()
        scored = [i for i in interviews if i["overall_score"] is not None]
        def avg(key):
            vals = [float(i[key]) for i in scored if i[key] is not None]
            return round(sum(vals) / len(vals)) if vals else None
        summary = {"total": len(interviews), "done": sum(i["status"] == "completed" for i in interviews),
                   "overall": avg("overall_score"), "quality": avg("response_quality_score"),
                   "speech": avg("speech_performance_score"), "behavior": avg("behavioral_score")}
        return render_template("admin/user.html", active="users", user=user,
                               interviews=interviews, summary=summary)

    @admin_required
    def admin_user_action(user_id, action):
        if user_id == session["user_id"] and action in ("deactivate", "remove_admin"):
            flash("You can't do that to your own account.")
            return redirect(url_for("admin_user", user_id=user_id))
        conn, cursor = db()
        cursor.execute("SELECT user_id, full_name FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            conn.close()
            flash("User not found.")
            return redirect(url_for("admin_users"))
        name = user["full_name"]
        try:
            if action == "deactivate":
                cursor.execute("UPDATE users SET is_active = 0 WHERE user_id = %s", (user_id,))
                flash(f"{name}'s account is deactivated. They can no longer log in.")
            elif action == "activate":
                cursor.execute("UPDATE users SET is_active = 1 WHERE user_id = %s", (user_id,))
                flash(f"{name}'s account is active again.")
            elif action == "make_admin":
                cursor.execute("UPDATE users SET role = 'admin' WHERE user_id = %s", (user_id,))
                flash(f"{name} is now an admin. They need to log out and log in again.")
            elif action == "remove_admin":
                cursor.execute("UPDATE users SET role = DEFAULT WHERE user_id = %s", (user_id,))   # back to the normal user role
                flash(f"{name} is no longer an admin.")
            elif action == "reset_password":
                temp = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
                cursor.execute("UPDATE users SET password = %s WHERE user_id = %s",
                               (generate_password_hash(temp), user_id))
                flash(f"Temporary password for {name}: {temp}  (give it to them privately; "
                      f"they can change it with Forgot password).")
            conn.commit()
        except Exception as e:
            print("Admin action failed:", e)
            flash("That didn't work. If it mentions is_active, run block 6 of database/schema_updates.sql.")
        conn.close()
        return redirect(safe_next(url_for("admin_user", user_id=user_id)))

    # ------------------------------------------------------------------ interviews
    def interview_rows(cursor, args, limit=None, offset=0):
        where, values = interview_filters(args)
        sql = f"""SELECT i.interview_id, i.user_id, u.full_name, u.email, i.category, i.difficulty,
                         i.number_of_questions, i.status, i.started_at, i.completed_at,
                         e.overall_score, e.response_quality_score, e.speech_performance_score,
                         e.behavioral_score
                  FROM interviews i
                  JOIN users u ON u.user_id = i.user_id
                  LEFT JOIN evaluations e ON e.interview_id = i.interview_id
                  WHERE {where}
                  ORDER BY i.started_at DESC"""
        if limit:
            sql += " LIMIT %s OFFSET %s"
            values = values + [limit, offset]
        cursor.execute(sql, values)
        return cursor.fetchall()

    @admin_required
    def admin_interviews():
        page = max(int(request.args.get("page", 1) or 1), 1)
        conn, cursor = db()
        where, values = interview_filters(request.args)
        cursor.execute(f"""SELECT COUNT(*) AS n FROM interviews i JOIN users u ON u.user_id = i.user_id
                           WHERE {where}""", values)
        total = cursor.fetchone()["n"]
        rows = interview_rows(cursor, request.args, PAGE_SIZE, (page - 1) * PAGE_SIZE)
        cats = categories(cursor)
        conn.close()
        args = {k: v for k, v in request.args.items() if k != "page" and v}
        return render_template("admin/interviews.html", active="interviews", rows=rows, total=total,
                               page=page, pages=max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1),
                               args=args, cats=cats, difficulties=DIFFICULTIES)

    @admin_required
    def admin_interviews_csv():
        include_names = request.args.get("names") == "1"
        conn, cursor = db()
        rows = interview_rows(cursor, request.args)
        ids = [r["interview_id"] for r in rows]
        details = {}
        if ids:
            placeholders = ", ".join(["%s"] * len(ids))
            cursor.execute(f"""SELECT iq.interview_id,
                                      AVG(n.relevance_score) AS relevance, AVG(n.clarity_score) AS answer_clarity,
                                      AVG(n.completeness_score) AS completeness, AVG(n.grammar_score) AS grammar,
                                      AVG(s.fluency_score) AS fluency, AVG(s.clarity_score) AS speech_clarity,
                                      AVG(s.confidence_score) AS confidence, AVG(s.speaking_rate) AS speaking_rate,
                                      SUM(s.filler_word_count) AS filler_words,
                                      AVG(b.eye_contact_score) AS eye_contact,
                                      AVG(b.facial_expression_score) AS facial_expression,
                                      AVG(b.gesture_score) AS gestures
                               FROM interview_questions iq
                               JOIN responses r ON r.interview_question_id = iq.interview_question_id
                               LEFT JOIN nlp_analysis n ON n.response_id = r.response_id
                               LEFT JOIN speech_analysis s ON s.response_id = r.response_id
                               LEFT JOIN behavior_analysis b ON b.response_id = r.response_id
                               WHERE iq.interview_id IN ({placeholders})
                               GROUP BY iq.interview_id""", ids)
            details = {d["interview_id"]: d for d in cursor.fetchall()}
        conn.close()

        detail_cols = ["relevance", "answer_clarity", "completeness", "grammar", "fluency", "speech_clarity",
                       "confidence", "speaking_rate", "filler_words", "eye_contact", "facial_expression", "gestures"]
        out = io.StringIO()
        writer = csv.writer(out)
        head = ["interview_id", "student_id"] + (["student_name"] if include_names else []) + [
            "category", "difficulty", "questions", "status", "started_at", "completed_at",
            "overall", "response_quality", "speech_performance", "behavioral"] + detail_cols
        writer.writerow(head)
        def fmt(v):
            if v is None:
                return ""
            return round(float(v), 2) if not isinstance(v, (str, int)) else v
        for r in rows:
            d = details.get(r["interview_id"], {})
            writer.writerow([r["interview_id"], r["user_id"]] + ([r["full_name"]] if include_names else []) + [
                r["category"], r["difficulty"], r["number_of_questions"], r["status"],
                r["started_at"] or "", r["completed_at"] or "",
                fmt(r["overall_score"]), fmt(r["response_quality_score"]),
                fmt(r["speech_performance_score"]), fmt(r["behavioral_score"])] +
                [fmt(d.get(c)) for c in detail_cols])
        filename = f"aimis_interviews_{date.today().isoformat()}.csv"
        # utf-8-sig so Excel shows names with ñ and accents correctly
        return Response(out.getvalue().encode("utf-8-sig"), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={filename}"})

    @admin_required
    def admin_report(interview_id):
        conn, cursor = db()
        cursor.execute("""SELECT i.*, u.full_name, u.email FROM interviews i
                          JOIN users u ON u.user_id = i.user_id WHERE i.interview_id = %s""", (interview_id,))
        iv = cursor.fetchone()
        if not iv:
            conn.close()
            flash("Interview not found.")
            return redirect(url_for("admin_interviews"))
        answers, evaluation, fb = load_report(cursor, interview_id)
        conn.close()
        # Scores and feedback only: transcripts and recordings stay private to the student
        for a in answers:
            a["transcript"] = None
            a["audio_path"] = None
        return render_template("interview_summary.html", iv=iv, answers=answers, evaluation=evaluation,
                               fb=fb, admin_view=True)

    # ------------------------------------------------------------------ questions
    @admin_required
    def admin_questions():
        view = request.args.get("view", "active")         # active | pending | off
        category = request.args.get("category", "")
        difficulty = request.args.get("difficulty", "")
        conn, cursor = db()
        cats = categories(cursor)
        where, values = [], []
        if view == "pending":
            where.append("qb.review_status = 'pending'")
        elif view == "off":
            where.append("qb.is_active = 0 AND COALESCE(qb.review_status, 'approved') <> 'pending'")
        else:
            where.append("qb.is_active = 1")
        if category:
            where.append("qb.category = %s"); values.append(category)
        if difficulty:
            where.append("qb.difficulty = %s"); values.append(difficulty)
        try:
            cursor.execute(f"""SELECT qb.*, COALESCE(u.times_asked, 0) AS times_asked
                               FROM question_bank qb
                               LEFT JOIN (SELECT question_id, COUNT(*) AS times_asked
                                          FROM interview_questions GROUP BY question_id) u
                                      ON u.question_id = qb.question_id
                               WHERE {' AND '.join(where)}
                               ORDER BY qb.category, FIELD(qb.difficulty, 'Beginner', 'Intermediate', 'Advanced'),
                                        qb.question_id DESC""", values)
            questions = cursor.fetchall()
            cursor.execute("""SELECT SUM(is_active = 1) AS active, SUM(review_status = 'pending') AS pending,
                                     SUM(is_active = 0 AND review_status <> 'pending') AS off
                              FROM question_bank""")
            counts = cursor.fetchone()
            ready = True
        except Exception as e:
            print("Question page needs schema block 6:", e)
            questions, counts, ready = [], {"active": 0, "pending": 0, "off": 0}, False
        conn.close()
        return render_template("admin/questions.html", active="questions", questions=questions,
                               counts=counts, view=view, category=category, difficulty=difficulty,
                               cats=cats, difficulties=DIFFICULTIES, ready=ready)

    def back_to_questions():
        return redirect(safe_next(url_for("admin_questions")))

    @admin_required
    def admin_questions_generate():
        category = request.form.get("category", "")
        difficulty = request.form.get("difficulty", "")
        try:
            count = min(max(int(request.form.get("count", 5)), 1), 10)
        except ValueError:
            count = 5
        if not category or difficulty not in DIFFICULTIES:
            flash("Choose a category and a difficulty first.")
            return back_to_questions()
        conn, cursor = db()
        cursor.execute("SELECT question_text FROM question_bank WHERE category = %s AND difficulty = %s",
                       (category, difficulty))
        existing = [r["question_text"] for r in cursor.fetchall()]
        try:
            new = generate_questions(category, difficulty, count, existing)
        except Exception as e:
            conn.close()
            print("Question generation failed:", e)
            flash("The AI couldn't create questions right now (it may be busy or out of quota). Try again later.")
            return back_to_questions()
        for text in new:
            cursor.execute("""INSERT INTO question_bank (question_text, category, difficulty, is_active,
                                                         source, review_status)
                              VALUES (%s, %s, %s, 0, 'ai', 'pending')""", (text, category, difficulty))
        conn.commit()
        conn.close()
        flash(f"The AI wrote {len(new)} new {difficulty} {category} question{'s' if len(new) != 1 else ''}. "
              f"Review them below: approve the good ones and reject the rest.")
        return redirect(url_for("admin_questions", view="pending", category=category, difficulty=difficulty))

    @admin_required
    def admin_question_add():
        text = " ".join(request.form.get("question_text", "").split())
        category = request.form.get("category", "").strip()
        difficulty = request.form.get("difficulty", "")
        if len(text) < 15 or not category or difficulty not in DIFFICULTIES:
            flash("Write the question (at least 15 characters) and choose its category and difficulty.")
            return back_to_questions()
        conn, cursor = db()
        cursor.execute("""INSERT INTO question_bank (question_text, category, difficulty, is_active,
                                                     source, review_status)
                          VALUES (%s, %s, %s, 1, 'admin', 'approved')""", (text, category, difficulty))
        conn.commit()
        conn.close()
        flash("Question added. Students can get it in their next interview.")
        return back_to_questions()

    @admin_required
    def admin_question_action(question_id, action):
        conn, cursor = db()
        if action == "edit":
            text = " ".join(request.form.get("question_text", "").split())
            difficulty = request.form.get("difficulty", "")
            if len(text) < 15 or difficulty not in DIFFICULTIES:
                conn.close()
                flash("The question needs at least 15 characters and a difficulty.")
                return back_to_questions()
            cursor.execute("UPDATE question_bank SET question_text = %s, difficulty = %s WHERE question_id = %s",
                           (text, difficulty, question_id))
            flash("Question updated.")
        elif action == "approve":
            cursor.execute("""UPDATE question_bank SET is_active = 1, review_status = 'approved'
                              WHERE question_id = %s""", (question_id,))
            flash("Question approved. Students can get it now.")
        elif action == "reject":
            # Pending questions were never asked, so they can be deleted
            cursor.execute("""DELETE FROM question_bank
                              WHERE question_id = %s AND review_status = 'pending'""", (question_id,))
            flash("Question rejected and removed.")
        elif action == "turn_off":
            cursor.execute("UPDATE question_bank SET is_active = 0 WHERE question_id = %s", (question_id,))
            flash("Question turned off. It won't be asked anymore, but old reports still show it.")
        elif action == "turn_on":
            cursor.execute("""UPDATE question_bank SET is_active = 1, review_status = 'approved'
                              WHERE question_id = %s""", (question_id,))
            flash("Question turned back on.")
        conn.commit()
        conn.close()
        return back_to_questions()

    @admin_required
    def admin_questions_approve_all():
        ids = [int(i) for i in request.form.getlist("ids") if i.isdigit()]
        if ids:
            conn, cursor = db()
            placeholders = ", ".join(["%s"] * len(ids))
            cursor.execute(f"""UPDATE question_bank SET is_active = 1, review_status = 'approved'
                               WHERE review_status = 'pending' AND question_id IN ({placeholders})""", ids)
            conn.commit()
            conn.close()
            flash(f"Approved {len(ids)} question{'s' if len(ids) != 1 else ''}.")
        return back_to_questions()

    # ------------------------------------------------------------------ routes
    rules = [
        ("/admin", admin_overview, ["GET"]),
        ("/admin/users", admin_users, ["GET"]),
        ("/admin/users/<int:user_id>", admin_user, ["GET"]),
        ("/admin/users/<int:user_id>/<action>", admin_user_action, ["POST"]),
        ("/admin/interviews", admin_interviews, ["GET"]),
        ("/admin/interviews.csv", admin_interviews_csv, ["GET"]),
        ("/admin/interviews/<int:interview_id>", admin_report, ["GET"]),
        ("/admin/questions", admin_questions, ["GET"]),
        ("/admin/questions/generate", admin_questions_generate, ["POST"]),
        ("/admin/questions/add", admin_question_add, ["POST"]),
        ("/admin/questions/approve-all", admin_questions_approve_all, ["POST"]),
        ("/admin/questions/<int:question_id>/<action>", admin_question_action, ["POST"]),
    ]
    for rule, view, methods in rules:
        app.add_url_rule(rule, view.__name__, view, methods=methods)
