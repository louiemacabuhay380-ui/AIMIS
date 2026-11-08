import os
import re
import io
import json
import wave
import random
from functools import wraps
from concurrent.futures import ThreadPoolExecutor

from flask import (Flask, render_template, request, redirect, url_for, session,
                   flash, jsonify, abort, Response)
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import mysql.connector
from cryptography.fernet import Fernet, InvalidToken

load_dotenv()

from ai_service import analyze_interview, transcribe_answer
from nlp_service import analyze_text
from speech_service import analyze_audio
import password_reset
import personal_feedback
import rag

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024   # max 25 MB upload

AUDIO_DIR = os.path.join(app.root_path, "uploads", "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

CONSENT_VERSION = "v1.3"   # v1.3 = anonymous answers may be reviewed by evaluators (validation); v1.2 = Gemini, retention

# Overall score weights (answer content, speech delivery, behavior)
WEIGHT_QUALITY = 0.60
WEIGHT_SPEECH = 0.25
WEIGHT_BEHAVIOR = 0.15

_audio_key = os.getenv("AUDIO_ENCRYPTION_KEY")
if not _audio_key:
    raise RuntimeError("AUDIO_ENCRYPTION_KEY is missing from .env")
fernet = Fernet(_audio_key.encode())


# ---------------------------------------------------------------- helpers

def get_db():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"), database=os.getenv("DB_NAME"),
        buffered=True)


import security
security.register(app, get_db)         # CSRF tokens, login lockout, secure cookies, security headers
password_reset.register(app, get_db)   # adds the Forgot password pages

import my_data
my_data.register(app, get_db)          # My data page, Delete my data, automatic deletion of old recordings


@app.context_processor
def privacy_settings():
    return {"recording_days": my_data.retention_days()}


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.template_filter("fill_in")
def fill_in(text):
    """Show [details the student must fill in] as highlighted blanks in example answers."""
    from markupsafe import escape, Markup
    return Markup(re.sub(r"\[([^\]]{1,80})\]", r'<span class="fill-in">\1</span>', str(escape(text or ""))))


def num(value):
    """Convert a database number (Decimal) to float, keeping None."""
    return float(value) if value is not None else None


# ---------------------------------------------------------------- AI processing

def evaluate_interview(interview_id):
    """Score the transcribed answers, combine all scores, and save feedback."""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT user_id, category, difficulty FROM interviews WHERE interview_id = %s", (interview_id,))
    iv = cursor.fetchone()
    cursor.execute("""SELECT r.response_id, qb.question_text, qb.category, r.transcript,
                             COALESCE(sa.filler_word_count, 0) AS filler_word_count,
                             ba.eye_contact_score, ba.facial_expression_score,
                             ba.gesture_score, ba.face_visibility_score
                      FROM interview_questions iq
                      JOIN question_bank qb ON qb.question_id = iq.question_id
                      JOIN responses r ON r.interview_question_id = iq.interview_question_id
                      LEFT JOIN speech_analysis sa ON sa.response_id = r.response_id
                      LEFT JOIN behavior_analysis ba ON ba.response_id = r.response_id
                      WHERE iq.interview_id = %s ORDER BY iq.question_order""", (interview_id,))
    qa_list = attach_gesture_extras(cursor, cursor.fetchall())

    if not qa_list:
        conn.close()
        raise RuntimeError("This interview has no saved answers.")
    if any(qa["transcript"] is None for qa in qa_list):
        conn.close()
        raise RuntimeError("Some answers haven't been transcribed yet. Run process_interview instead.")

    # Earlier interviews of this student, so the feedback can mention their progress
    history_text = personal_feedback.history_summary(cursor, iv["user_id"], interview_id)
    result = analyze_interview(iv["category"], iv["difficulty"], qa_list, history_text)

    # Clear old results so re-evaluating doesn't create duplicates
    response_ids = [qa["response_id"] for qa in qa_list]
    placeholders = ", ".join(["%s"] * len(response_ids))
    cursor.execute(f"DELETE FROM nlp_analysis WHERE response_id IN ({placeholders})", response_ids)
    cursor.execute("DELETE FROM evaluations WHERE interview_id = %s", (interview_id,))
    cursor.execute("DELETE FROM feedback WHERE interview_id = %s", (interview_id,))

    all_scores = []
    for qa, scores in zip(qa_list, result.get("answers", [])):
        s = [min(max(float(scores.get(k, 0)), 0), 100)
             for k in ("relevance", "clarity", "completeness", "grammar")]
        all_scores.extend(s)
        stats = analyze_text(qa["transcript"], qa["category"])
        cursor.execute("""INSERT INTO nlp_analysis
                          (response_id, relevance_score, clarity_score, completeness_score, grammar_score,
                           word_count, sentence_count, vocabulary_diversity, keyword_count, keywords_found)
                          VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                       (qa["response_id"], *s, stats["word_count"], stats["sentence_count"],
                        stats["vocabulary_diversity"], stats["keyword_count"], stats["keywords_found"]))

    quality = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0.0

    # Speech delivery = average of fluency, confidence and speech clarity
    cursor.execute("""SELECT AVG((sa.fluency_score
                                  + COALESCE(sa.confidence_score, sa.fluency_score)
                                  + COALESCE(sa.clarity_score, sa.fluency_score)) / 3) AS speech_score
                      FROM speech_analysis sa
                      JOIN responses r ON r.response_id = sa.response_id
                      JOIN interview_questions iq ON iq.interview_question_id = r.interview_question_id
                      WHERE iq.interview_id = %s""", (interview_id,))
    speech = cursor.fetchone()["speech_score"]
    speech = round(float(speech), 2) if speech is not None else None

    # Behavior = average of eye contact, facial expression and gestures
    cursor.execute("""SELECT AVG((ba.eye_contact_score + ba.facial_expression_score
                                  + ba.gesture_score) / 3) AS behavior_score
                      FROM behavior_analysis ba
                      JOIN responses r ON r.response_id = ba.response_id
                      JOIN interview_questions iq ON iq.interview_question_id = r.interview_question_id
                      WHERE iq.interview_id = %s""", (interview_id,))
    behavior = cursor.fetchone()["behavior_score"]
    behavior = round(float(behavior), 2) if behavior is not None else None

    # Missing parts (e.g. no camera data) are left out and the other weights scale up
    parts = [(quality, WEIGHT_QUALITY), (speech, WEIGHT_SPEECH), (behavior, WEIGHT_BEHAVIOR)]
    available = [(v, w) for v, w in parts if v is not None]
    overall = round(sum(v * w for v, w in available) / sum(w for _, w in available), 2)

    cursor.execute("""INSERT INTO evaluations
                      (interview_id, response_quality_score, speech_performance_score,
                       behavioral_score, overall_score)
                      VALUES (%s, %s, %s, %s, %s)""",
                   (interview_id, quality, speech, behavior, overall))
    # Which AI scored it (Gemini online, or the local Ollama backup / offline mode)
    save_ai_name(cursor, "UPDATE evaluations SET scored_by = %s WHERE interview_id = %s",
                 (result.get("_provider", "gemini"), interview_id))
    # Feedback item by item: each one points to an exact answer, with the student's words and a fix
    items = personal_feedback.build_feedback_items(result, qa_list)
    strengths, areas, tips = personal_feedback.feedback_text(items)
    cursor.execute("""INSERT INTO feedback (interview_id, strengths, areas_to_improve, recommendations)
                      VALUES (%s, %s, %s, %s)""",
                   (interview_id, strengths, areas, tips))
    personal_feedback.save_feedback_items(cursor, interview_id, items)
    cursor.execute("UPDATE interviews SET overall_score = %s WHERE interview_id = %s", (overall, interview_id))
    # Feedback and sub-skill labels for each answer (needs block 7 of schema_updates.sql)
    personal_feedback.save_answer_feedback(cursor, qa_list, result.get("answers", []))
    conn.commit()

    # Add this interview to the chatbot's knowledge base (RAG). Never let this break the scoring.
    try:
        rag.index_interview(conn, interview_id, load_report)
    except Exception as e:
        print("Could not add the interview to the chatbot knowledge base:", e)
    conn.close()


GESTURE_EXTRAS = ("hands_visible_ratio", "expressive_gesture_ratio", "face_touch_ratio")


def attach_gesture_extras(cursor, rows):
    """Add the detailed gesture numbers to each answer row (None if the database doesn't have them yet)."""
    ids = [r["response_id"] for r in rows if r.get("response_id")]
    for r in rows:
        for k in GESTURE_EXTRAS:
            r.setdefault(k, None)
    if not ids:
        return rows
    placeholders = ", ".join(["%s"] * len(ids))
    cursor.execute(f"SELECT * FROM behavior_analysis WHERE response_id IN ({placeholders})", ids)
    extra = {b["response_id"]: b for b in cursor.fetchall()}
    for r in rows:
        b = extra.get(r.get("response_id"))
        if b:
            for k in GESTURE_EXTRAS:
                if k in b:
                    r[k] = b[k]
    return rows


def transcribe_pending(interview_id):
    """Transcribe and measure every answer in this interview that hasn't been processed yet."""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""SELECT r.response_id, r.audio_path, r.duration, qb.question_text
                      FROM responses r
                      JOIN interview_questions iq ON iq.interview_question_id = r.interview_question_id
                      JOIN question_bank qb ON qb.question_id = iq.question_id
                      WHERE iq.interview_id = %s
                        AND r.transcript IS NULL AND r.audio_path IS NOT NULL""", (interview_id,))
    pending = cursor.fetchall()

    def work(row):
        with open(os.path.join(app.root_path, row["audio_path"]), "rb") as file:
            audio_bytes = fernet.decrypt(file.read())
        result = transcribe_answer(row["question_text"], audio_bytes)
        features = analyze_audio(audio_bytes, int(result.get("filler_word_count", 0)))
        return row, result, features

    failed = 0
    with ThreadPoolExecutor(max_workers=2) as pool:   # process 2 answers at a time
        futures = [pool.submit(work, row) for row in pending]
        for future in futures:
            try:
                row, result, features = future.result()
            except Exception as e:
                print("Transcription failed:", e)
                failed += 1
                continue

            transcript = (result.get("transcript") or "").strip()
            duration = float(row["duration"])
            speaking_rate = round(len(transcript.split()) / (duration / 60), 2) if duration else 0
            f = features or {}

            cursor.execute("UPDATE responses SET transcript = %s WHERE response_id = %s",
                           (transcript, row["response_id"]))
            cursor.execute("DELETE FROM speech_analysis WHERE response_id = %s", (row["response_id"],))
            cursor.execute("""INSERT INTO speech_analysis
                              (response_id, speaking_rate, filler_word_count, pause_count,
                               speech_duration, fluency_score, total_pause_time, longest_pause,
                               average_pause, pitch_variation, average_volume, volume_variation,
                               speech_ratio, confidence_score, clarity_score)
                              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                           (row["response_id"], speaking_rate, int(result.get("filler_word_count", 0)),
                            f.get("pause_count", 0), duration,
                            min(max(float(result.get("fluency_score", 0)), 0), 100),
                            f.get("total_pause_time"), f.get("longest_pause"), f.get("average_pause"),
                            f.get("pitch_variation"), f.get("average_volume"), f.get("volume_variation"),
                            f.get("speech_ratio"), f.get("confidence_score", 0),
                            min(max(float(result.get("clarity_score", 0)), 0), 100)))
            save_ai_name(cursor, "UPDATE speech_analysis SET transcribed_by = %s WHERE response_id = %s",
                         (result.get("_provider", "gemini"), row["response_id"]))
            conn.commit()
    conn.close()

    if failed:
        raise RuntimeError(f"{failed} answer(s) could not be transcribed.")


def process_interview(interview_id):
    """Transcribe all answers, then evaluate the whole interview."""
    transcribe_pending(interview_id)
    evaluate_interview(interview_id)


# ---------------------------------------------------------------- accounts

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form["full_name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if not full_name or not email or len(password) < 8:
            flash("Fill in all fields. Password must be at least 8 characters.")
            return redirect(url_for("register"))

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            conn.close()
            flash("That email is already registered.")
            return redirect(url_for("register"))

        cursor.execute("INSERT INTO users (full_name, email, password) VALUES (%s, %s, %s)",
                       (full_name, email, generate_password_hash(password)))
        conn.commit()
        conn.close()
        flash("Account created! You can now log in.")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            if not user.get("is_active", 1):
                flash("This account has been deactivated. Please contact the AIMIS administrator.")
                return redirect(url_for("login"))
            session.clear()
            session["user_id"] = user["user_id"]
            session["full_name"] = user["full_name"]
            session["role"] = user["role"]
            if user["role"] == "admin":
                return redirect(url_for("admin_overview"))
            if user["role"] == "rater":
                return redirect(url_for("rate_answers"))
            return redirect(url_for("dashboard"))

        flash("Incorrect email or password.")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You've been logged out.")
    return redirect(url_for("login"))


# ---------------------------------------------------------------- dashboard

@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""SELECT i.*, e.evaluation_id
                      FROM interviews i
                      LEFT JOIN evaluations e ON e.interview_id = i.interview_id
                      WHERE i.user_id = %s
                      ORDER BY i.started_at DESC""", (session["user_id"],))
    interviews = cursor.fetchall()

    cursor.execute("""SELECT i.category, i.completed_at, e.overall_score, e.response_quality_score,
                             e.speech_performance_score, e.behavioral_score
                      FROM interviews i
                      JOIN evaluations e ON e.interview_id = i.interview_id
                      WHERE i.user_id = %s AND i.status = 'completed'
                      ORDER BY i.completed_at""", (session["user_id"],))
    history = cursor.fetchall()
    skills = skill_breakdown(cursor, session["user_id"])
    weak_skill = personal_feedback.weakest_skill(cursor, session["user_id"])
    subskills = personal_feedback.subskill_progress(cursor, session["user_id"])
    conn.close()

    chart = {
        "labels": [f"#{n} ({h['completed_at'].strftime('%b %d')})" if h["completed_at"] else f"#{n}"
                   for n, h in enumerate(history, start=1)],
        "overall": [num(h["overall_score"]) for h in history],
        "quality": [num(h["response_quality_score"]) for h in history],
        "speech": [num(h["speech_performance_score"]) for h in history],
        "behavior": [num(h["behavioral_score"]) for h in history],
        "categories": [h["category"] for h in history],
    }

    stats = None
    scores = [s for s in chart["overall"] if s is not None]
    if scores:
        recent = scores[-3:]
        earlier = scores[-6:-3]
        trend = None
        if earlier:
            diff = sum(recent) / len(recent) - sum(earlier) / len(earlier)
            trend = "Improving" if diff > 3 else "Dropping" if diff < -3 else "Steady"
        stats = {
            "count": len(scores),
            "average": round(sum(scores) / len(scores), 2),
            "best": max(scores),
            "latest": scores[-1],
            "change": round(scores[-1] - scores[0], 2) if len(scores) > 1 else None,
            "trend": trend,
        }

    focus = min(skills, key=lambda s: s["value"]) if skills else None
    return render_template("dashboard.html", interviews=interviews, chart=chart, stats=stats,
                           skills=skills, focus=focus, weak_skill=weak_skill, subskills=subskills)


# Skill rings on the dashboard: name, how it's computed, and a tip for improving it
SKILL_TIPS = {
    "Relevance": "Answer the exact question asked before adding extra details.",
    "Answer structure": "Use STAR: describe the Situation, your Task, the Action you took, and the Result.",
    "Clarity": "Speak at a steady pace and organize your answer into a clear beginning, middle, and end.",
    "Fluency": "Practice your answer out loud a few times so the words come smoothly.",
    "Confidence": "Pause briefly instead of saying \"um\", and vary your tone to sound engaged.",
    "Body language": "Look at the camera, smile naturally, and use small hand gestures.",
}


def skill_breakdown(cursor, user_id, last_n=5):
    """Average each skill over the user's last few scored interviews (0-100)."""
    cursor.execute("""SELECT i.interview_id FROM interviews i
                      JOIN evaluations e ON e.interview_id = i.interview_id
                      WHERE i.user_id = %s AND i.status = 'completed'
                      ORDER BY i.completed_at DESC LIMIT %s""", (user_id, last_n))
    ids = [row["interview_id"] for row in cursor.fetchall()]
    if not ids:
        return []

    placeholders = ", ".join(["%s"] * len(ids))
    cursor.execute(f"""SELECT AVG(n.relevance_score) AS relevance,
                              AVG(n.completeness_score) AS completeness,
                              AVG(n.clarity_score) AS answer_clarity,
                              AVG(s.clarity_score) AS speech_clarity,
                              AVG(s.fluency_score) AS fluency,
                              AVG(s.confidence_score) AS confidence,
                              AVG((b.eye_contact_score + b.facial_expression_score + b.gesture_score) / 3) AS body
                       FROM responses r
                       JOIN interview_questions iq ON iq.interview_question_id = r.interview_question_id
                       LEFT JOIN nlp_analysis n ON n.response_id = r.response_id
                       LEFT JOIN speech_analysis s ON s.response_id = r.response_id
                       LEFT JOIN behavior_analysis b ON b.response_id = r.response_id
                       WHERE iq.interview_id IN ({placeholders})""", ids)
    row = cursor.fetchone()

    clarity_parts = [num(row["answer_clarity"]), num(row["speech_clarity"])]
    clarity_parts = [v for v in clarity_parts if v is not None]
    values = {
        "Relevance": num(row["relevance"]),
        "Answer structure": num(row["completeness"]),
        "Clarity": sum(clarity_parts) / len(clarity_parts) if clarity_parts else None,
        "Fluency": num(row["fluency"]),
        "Confidence": num(row["confidence"]),
        "Body language": num(row["body"]),
    }
    skills = [{"name": name, "value": round(v), "tip": SKILL_TIPS[name]}
              for name, v in values.items() if v is not None]
    return sorted(skills, key=lambda s: s["value"], reverse=True)   # strongest = outer ring


# ---------------------------------------------------------------- interview

@app.route("/interview/start", methods=["GET", "POST"])
@login_required
def start_interview():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        if request.form.get("consent") != "yes":
            conn.close()
            flash("You need to agree to the recording terms before starting the interview.")
            return redirect(url_for("start_interview"))

        category = request.form["category"]
        difficulty = request.form["difficulty"]
        try:
            count = min(max(int(request.form["number_of_questions"]), 1), 10)
        except ValueError:
            count = 5

        # Random questions from the chosen category, preferring ones this user has been asked
        # the fewest times, so repeated practice brings new questions before any repeats.
        cursor.execute("""SELECT qb.question_id
                           FROM question_bank qb
                           LEFT JOIN (SELECT iq.question_id, COUNT(*) AS times_asked
                                      FROM interview_questions iq
                                      JOIN interviews i ON i.interview_id = iq.interview_id
                                      WHERE i.user_id = %s
                                      GROUP BY iq.question_id) seen ON seen.question_id = qb.question_id
                           WHERE qb.is_active = 1 AND qb.category = %s AND qb.difficulty = %s
                           ORDER BY COALESCE(seen.times_asked, 0), RAND()
                           LIMIT %s""", (session["user_id"], category, difficulty, count))
        questions = cursor.fetchall()
        random.shuffle(questions)   # mix the order so new and repeated questions aren't grouped

        if not questions:
            conn.close()
            flash("No questions available for that category and difficulty yet.")
            return redirect(url_for("start_interview"))

        cursor.execute("""INSERT INTO interviews (user_id, category, difficulty, number_of_questions)
                          VALUES (%s, %s, %s, %s)""",
                       (session["user_id"], category, difficulty, len(questions)))
        interview_id = cursor.lastrowid
        cursor.execute("""INSERT INTO consents (user_id, interview_id, consent_given, consent_version)
                          VALUES (%s, %s, 1, %s)""",
                       (session["user_id"], interview_id, CONSENT_VERSION))

        for order, q in enumerate(questions, start=1):
            cursor.execute("""INSERT INTO interview_questions (interview_id, question_id, question_order)
                              VALUES (%s, %s, %s)""", (interview_id, q["question_id"], order))
        conn.commit()
        conn.close()

        if len(questions) < count:
            flash(f"Only {len(questions)} question(s) are available for {category} ({difficulty}), "
                  f"so this interview has {len(questions)} instead of {count}.")
        return redirect(url_for("interview", interview_id=interview_id))

    cursor.execute("SELECT DISTINCT category FROM question_bank WHERE is_active = 1 ORDER BY category")
    categories = [row["category"] for row in cursor.fetchall()]
    conn.close()
    return render_template("start_interview.html", categories=categories)


@app.route("/interview/<int:interview_id>/check", methods=["GET", "POST"])
@login_required
def device_check(interview_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM interviews WHERE interview_id = %s AND user_id = %s",
                   (interview_id, session["user_id"]))
    iv = cursor.fetchone()
    conn.close()
    if not iv:
        flash("Interview not found.")
        return redirect(url_for("dashboard"))
    if iv["status"] != "in_progress":
        return redirect(url_for("interview_summary", interview_id=interview_id))

    if request.method == "POST":
        checked = session.get("device_checked", [])
        if interview_id not in checked:
            checked.append(interview_id)
        session["device_checked"] = checked
        return redirect(url_for("interview", interview_id=interview_id))

    return render_template("device_check.html", iv=iv)


@app.route("/interview/<int:interview_id>", methods=["GET", "POST"])
@login_required
def interview(interview_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM interviews WHERE interview_id = %s AND user_id = %s",
                   (interview_id, session["user_id"]))
    iv = cursor.fetchone()

    if not iv:
        conn.close()
        flash("Interview not found.")
        return redirect(url_for("dashboard"))
    if iv["status"] == "completed":
        conn.close()
        return redirect(url_for("processing", interview_id=interview_id))
    if iv["status"] != "in_progress":
        conn.close()
        flash("That interview was cancelled.")
        return redirect(url_for("dashboard"))
    if interview_id not in session.get("device_checked", []):
        conn.close()
        return redirect(url_for("device_check", interview_id=interview_id))

    # The next question in this interview that has no answer yet
    cursor.execute("""SELECT iq.interview_question_id, iq.question_order, qb.question_text
                      FROM interview_questions iq
                      JOIN question_bank qb ON qb.question_id = iq.question_id
                      LEFT JOIN responses r ON r.interview_question_id = iq.interview_question_id
                      WHERE iq.interview_id = %s AND r.response_id IS NULL
                      ORDER BY iq.question_order LIMIT 1""", (interview_id,))
    current = cursor.fetchone()

    if not current:
        cursor.execute("""UPDATE interviews SET status = 'completed', completed_at = NOW()
                          WHERE interview_id = %s AND status = 'in_progress'""", (interview_id,))
        conn.commit()
        conn.close()
        return redirect(url_for("processing", interview_id=interview_id))

    if request.method == "POST":
        submitted_id = int(request.form.get("interview_question_id", 0))
        audio = request.files.get("audio")
        if submitted_id != current["interview_question_id"]:
            conn.close()
            return jsonify(ok=False, error="This question was already answered."), 409
        if not audio:
            conn.close()
            return jsonify(ok=False, error="No recording received."), 400

        audio_bytes = audio.read()   # kept in memory; never saved unencrypted
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as w:
                duration = round(w.getnframes() / w.getframerate(), 2)
        except wave.Error:
            conn.close()
            return jsonify(ok=False, error="The recording file was invalid. Please record again."), 400
        if duration < 2:
            conn.close()
            return jsonify(ok=False, error="That recording is too short. Please answer again."), 400

        filename = f"interview{interview_id}_q{submitted_id}.wav.enc"
        with open(os.path.join(AUDIO_DIR, filename), "wb") as f:
            f.write(fernet.encrypt(audio_bytes))

        # Save the answer now. Transcription and analysis happen after the last question.
        cursor.execute("""INSERT INTO responses (interview_question_id, audio_path, duration)
                          VALUES (%s, %s, %s)""",
                       (submitted_id, f"uploads/audio/{filename}", duration))
        response_id = cursor.lastrowid

        # Behavior scores calculated in the browser (eye contact, expression, gestures)
        behavior = request.form.get("behavior")
        if behavior:
            try:
                b = json.loads(behavior)
                values = [min(max(float(b.get(k, 0)), 0), 100) for k in
                          ("eye_contact_score", "face_visibility_score", "facial_expression_score",
                           "gesture_score", "smile_ratio", "gesture_ratio")]
                extras = [min(max(float(b.get(k, 0) or 0), 0), 100) for k in GESTURE_EXTRAS]
                try:
                    cursor.execute("""INSERT INTO behavior_analysis
                                      (response_id, eye_contact_score, face_visibility_score,
                                       facial_expression_score, gesture_score, smile_ratio,
                                       gesture_ratio, frames_analyzed,
                                       hands_visible_ratio, expressive_gesture_ratio, face_touch_ratio)
                                      VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                                   (response_id, *values, int(b.get("frames_analyzed", 0)), *extras))
                except mysql.connector.errors.ProgrammingError as e:
                    if e.errno != 1054:      # 1054 = unknown column
                        raise
                    print("Note: run block 5 of database/schema_updates.sql to save the detailed gesture data.")
                    cursor.execute("""INSERT INTO behavior_analysis
                                      (response_id, eye_contact_score, face_visibility_score,
                                       facial_expression_score, gesture_score, smile_ratio,
                                       gesture_ratio, frames_analyzed)
                                      VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                                   (response_id, *values, int(b.get("frames_analyzed", 0))))
            except (ValueError, TypeError, AttributeError):
                pass   # invalid data from the browser: skip behavior for this answer
        conn.commit()

        # Continuous session: send back the next question, or finish the interview
        cursor.execute("""SELECT iq.interview_question_id, iq.question_order, qb.question_text
                          FROM interview_questions iq
                          JOIN question_bank qb ON qb.question_id = iq.question_id
                          LEFT JOIN responses r ON r.interview_question_id = iq.interview_question_id
                          WHERE iq.interview_id = %s AND r.response_id IS NULL
                          ORDER BY iq.question_order LIMIT 1""", (interview_id,))
        nxt = cursor.fetchone()
        if not nxt:
            cursor.execute("""UPDATE interviews SET status = 'completed', completed_at = NOW()
                              WHERE interview_id = %s AND status = 'in_progress'""", (interview_id,))
            conn.commit()
            conn.close()
            return jsonify(ok=True, done=True,
                           next_url=url_for("processing", interview_id=interview_id))
        conn.close()
        return jsonify(ok=True, done=False, next=nxt)

    conn.close()
    return render_template("interview.html", iv=iv, current=current)


@app.route("/interview/<int:interview_id>/cancel", methods=["POST"])
@login_required
def cancel_interview(interview_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""UPDATE interviews SET status = 'cancelled'
                      WHERE interview_id = %s AND user_id = %s AND status = 'in_progress'""",
                   (interview_id, session["user_id"]))
    conn.commit()
    if cursor.rowcount == 0:
        conn.close()
        flash("That interview can't be cancelled.")
        return redirect(url_for("dashboard"))

    # Delete the recordings saved so far; a cancelled interview is never evaluated
    cursor.execute("""SELECT r.response_id, r.audio_path FROM responses r
                      JOIN interview_questions iq ON iq.interview_question_id = r.interview_question_id
                      WHERE iq.interview_id = %s AND r.audio_path IS NOT NULL""", (interview_id,))
    for response_id, audio_path in cursor.fetchall():
        full_path = os.path.join(app.root_path, audio_path)
        if os.path.exists(full_path):
            os.remove(full_path)
        cursor.execute("UPDATE responses SET audio_path = NULL WHERE response_id = %s", (response_id,))
    conn.commit()
    conn.close()

    flash("Interview cancelled.")
    return redirect(url_for("dashboard"))


@app.route("/interview/<int:interview_id>/processing")
@login_required
def processing(interview_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""SELECT * FROM interviews WHERE interview_id = %s AND user_id = %s
                      AND status = 'completed'""", (interview_id, session["user_id"]))
    iv = cursor.fetchone()
    cursor.execute("SELECT evaluation_id FROM evaluations WHERE interview_id = %s", (interview_id,))
    already_done = cursor.fetchone()
    conn.close()
    if not iv:
        flash("Interview not found.")
        return redirect(url_for("dashboard"))
    if already_done:
        return redirect(url_for("interview_summary", interview_id=interview_id))
    return render_template("processing.html", iv=iv)


@app.route("/interview/<int:interview_id>/process", methods=["POST"])
@login_required
def run_processing(interview_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""SELECT interview_id FROM interviews WHERE interview_id = %s AND user_id = %s
                      AND status = 'completed'""", (interview_id, session["user_id"]))
    found = cursor.fetchone()
    conn.close()
    if not found:
        return jsonify(ok=False, error="Interview not found."), 404
    try:
        process_interview(interview_id)
        return jsonify(ok=True)
    except Exception as e:
        print("Processing failed:", e)
        return jsonify(ok=False, error=explain_failure(e)), 503


def explain_failure(e):
    """A clear reason for the student when the AI evaluation fails (the full error goes to the terminal)."""
    import traceback
    traceback.print_exc()
    text = str(e)
    if getattr(e, "code", None) == 429 or "429" in text or "RESOURCE_EXHAUSTED" in text:
        return ("Gemini's free limit has been reached for now, so the AI couldn't score this interview. "
                "Your answers are saved. Try again later (the limit resets daily), or set EVAL_PROVIDER=ollama in .env.")
    if getattr(e, "code", None) in (500, 503) or "UNAVAILABLE" in text:
        return "Gemini is busy right now. Your answers are saved. Please try again in a few minutes."
    if "Ollama" in text or "ollama" in text:
        return "The local AI (Ollama) isn't running or the model is missing. Open Ollama and try again."
    if getattr(e, "errno", None) in (1054, 1146):
        return "The database is missing a new table or column. Run the latest blocks of database/schema_updates.sql."
    if "API key" in text or getattr(e, "code", None) in (400, 401, 403):
        return "The Gemini API key in .env was rejected. Check GEMINI_API_KEY."
    return "The AI evaluation failed: " + text[:180]


@app.route("/interview/<int:interview_id>/evaluate", methods=["POST"])
@login_required
def retry_evaluation(interview_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""SELECT interview_id FROM interviews
                      WHERE interview_id = %s AND user_id = %s AND status = 'completed'""",
                   (interview_id, session["user_id"]))
    found = cursor.fetchone()
    conn.close()
    if not found:
        flash("Interview not found.")
        return redirect(url_for("dashboard"))
    try:
        process_interview(interview_id)
        flash("Evaluation complete!")
    except Exception as e:
        print("Evaluation failed:", e)
        flash(explain_failure(e))
    return redirect(url_for("interview_summary", interview_id=interview_id))


AI_NAMES = {"gemini": "Gemini (online)", "ollama": "Local AI, offline (Ollama)",
            "whisper": "Local AI, offline (Whisper)"}


def save_ai_name(cursor, sql, params):
    """Record which AI did the work. Skipped quietly on a database without the column (run check_setup --fix)."""
    try:
        cursor.execute(sql, params)
    except Exception as e:
        if getattr(e, "errno", None) != 1054:
            raise


def attach_transcriber(cursor, answers):
    """Add .transcribed_by to each answer (None on older databases or older interviews)."""
    ids = [a["response_id"] for a in answers if a.get("response_id")]
    for a in answers:
        a["transcribed_by"] = None
    if not ids:
        return
    try:
        cursor.execute(f"SELECT response_id, transcribed_by FROM speech_analysis WHERE response_id IN "
                       f"({', '.join(['%s'] * len(ids))})", ids)
        found = {r["response_id"]: r["transcribed_by"] for r in cursor.fetchall()}
    except Exception as e:
        if getattr(e, "errno", None) == 1054:
            return
        raise
    for a in answers:
        a["transcribed_by"] = found.get(a.get("response_id"))


app.jinja_env.globals["AI_NAMES"] = AI_NAMES


def load_report(cursor, interview_id):
    """Answers, scores and feedback for one interview (used by the student report and the admin view)."""
    cursor.execute("""SELECT iq.question_order, qb.question_text, r.response_id, r.transcript, r.audio_path,
                             n.relevance_score, n.clarity_score, n.completeness_score, n.grammar_score,
                             n.word_count, n.vocabulary_diversity, n.keyword_count, n.keywords_found,
                             s.speaking_rate, s.filler_word_count, s.pause_count, s.fluency_score,
                             s.total_pause_time, s.longest_pause, s.pitch_variation,
                             s.volume_variation, s.speech_ratio, s.confidence_score,
                             s.clarity_score AS speech_clarity,
                             b.eye_contact_score, b.face_visibility_score, b.facial_expression_score,
                             b.gesture_score, b.smile_ratio, b.gesture_ratio
                      FROM interview_questions iq
                      JOIN question_bank qb ON qb.question_id = iq.question_id
                      LEFT JOIN responses r ON r.interview_question_id = iq.interview_question_id
                      LEFT JOIN nlp_analysis n ON n.response_id = r.response_id
                      LEFT JOIN speech_analysis s ON s.response_id = r.response_id
                      LEFT JOIN behavior_analysis b ON b.response_id = r.response_id
                      WHERE iq.interview_id = %s
                      ORDER BY iq.question_order""", (interview_id,))
    answers = attach_gesture_extras(cursor, cursor.fetchall())
    answers = personal_feedback.attach_answer_feedback(cursor, answers)
    attach_transcriber(cursor, answers)
    cursor.execute("SELECT * FROM evaluations WHERE interview_id = %s", (interview_id,))
    evaluation = cursor.fetchone()
    cursor.execute("SELECT * FROM feedback WHERE interview_id = %s ORDER BY created_at DESC LIMIT 1",
                   (interview_id,))
    fb = cursor.fetchone()
    if fb:
        fb["feedback_items"] = personal_feedback.load_feedback_items(cursor, interview_id)
    return answers, evaluation, fb


@app.route("/interview/<int:interview_id>/summary")
@login_required
def interview_summary(interview_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM interviews WHERE interview_id = %s AND user_id = %s",
                   (interview_id, session["user_id"]))
    iv = cursor.fetchone()
    if not iv:
        conn.close()
        flash("Interview not found.")
        return redirect(url_for("dashboard"))

    answers, evaluation, fb = load_report(cursor, interview_id)
    progress = personal_feedback.progress_compare(cursor, session["user_id"], interview_id, evaluation)
    conn.close()
    return render_template("interview_summary.html", iv=iv, answers=answers,
                           evaluation=evaluation, fb=fb, progress=progress)


@app.route("/audio/<path:filename>")
@login_required
def audio_file(filename):
    filename = os.path.basename(filename)   # blocks paths like ../../.env
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""SELECT r.response_id FROM responses r
                      JOIN interview_questions iq ON iq.interview_question_id = r.interview_question_id
                      JOIN interviews i ON i.interview_id = iq.interview_id
                      WHERE r.audio_path = %s AND i.user_id = %s""",
                   (f"uploads/audio/{filename}", session["user_id"]))
    found = cursor.fetchone()
    conn.close()
    path = os.path.join(AUDIO_DIR, filename)
    if not found or not os.path.exists(path):
        abort(404)

    with open(path, "rb") as f:
        encrypted = f.read()
    try:
        audio_bytes = fernet.decrypt(encrypted)
    except InvalidToken:
        abort(500)   # wrong key or damaged file
    return Response(audio_bytes, mimetype="audio/wav")


# Admin panel pages (placed here so every function above already exists)
import admin
from ai_service import generate_questions
admin.register(app, get_db, load_report, generate_questions)

# Validation: human evaluators score anonymous answers; the admin compares them with the AI
import validation
validation.register(app, get_db)

# AIMIS Coach chatbot (RAG over the student's own interviews)
import chatbot
chatbot.register(app, get_db, load_report)


if __name__ == "__main__":
    # Debug mode shows code and lets the browser run Python if an error happens, so it is OFF unless
    # FLASK_DEBUG=1 is set in .env (only on your own computer, never on a shared network).
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
