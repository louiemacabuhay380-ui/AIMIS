import os
import wave
from functools import wraps
from nlp_service import analyze_text
from flask import (Flask, render_template, request, redirect, url_for, session,
                   flash, jsonify, send_from_directory, abort)
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import mysql.connector
from ai_service import analyze_interview, transcribe_answer
import io
from flask import Response
from cryptography.fernet import Fernet, InvalidToken
from concurrent.futures import ThreadPoolExecutor
from speech_service import analyze_audio

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024   # max 25 MB upload
AUDIO_DIR = os.path.join(app.root_path, "uploads", "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)
CONSENT_VERSION = "v1.1"
_audio_key = os.getenv("AUDIO_ENCRYPTION_KEY")
if not _audio_key:
    raise RuntimeError("AUDIO_ENCRYPTION_KEY is missing from .env")
fernet = Fernet(_audio_key.encode())

def get_db():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"), database=os.getenv("DB_NAME"),
        buffered=True)

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def evaluate_interview(interview_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT category, difficulty FROM interviews WHERE interview_id = %s", (interview_id,))
    iv = cursor.fetchone()
    cursor.execute("""SELECT r.response_id, qb.question_text, r.transcript
                      FROM interview_questions iq
                      JOIN question_bank qb ON qb.question_id = iq.question_id
                      JOIN responses r ON r.interview_question_id = iq.interview_question_id
                      WHERE iq.interview_id = %s ORDER BY iq.question_order""", (interview_id,))
    qa_list = cursor.fetchall()
    if any(qa["transcript"] is None for qa in qa_list):
            conn.close()
            raise RuntimeError("Some answers haven't been transcribed yet. Run process_interview instead.")

    result = analyze_interview(iv["category"], iv["difficulty"], qa_list)

    # Clear any old results so re-evaluating doesn't create duplicates
    response_ids = [qa["response_id"] for qa in qa_list]
    placeholders = ", ".join(["%s"] * len(response_ids))
    cursor.execute(f"DELETE FROM nlp_analysis WHERE response_id IN ({placeholders})", response_ids)
    cursor.execute("DELETE FROM evaluations WHERE interview_id = %s", (interview_id,))
    cursor.execute("DELETE FROM feedback WHERE interview_id = %s", (interview_id,))

    all_scores = []
    all_scores = []
    for qa, scores in zip(qa_list, result["answers"]):
        s = [min(max(float(scores[k]), 0), 100)
             for k in ("relevance", "clarity", "completeness", "grammar")]
        all_scores.extend(s)
        stats = analyze_text(qa["transcript"], iv["category"])
        cursor.execute("""INSERT INTO nlp_analysis
                          (response_id, relevance_score, clarity_score, completeness_score, grammar_score,
                           word_count, sentence_count, vocabulary_diversity, keyword_count, keywords_found)
                          VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                       (qa["response_id"], *s, stats["word_count"], stats["sentence_count"],
                        stats["vocabulary_diversity"], stats["keyword_count"], stats["keywords_found"]))

        quality = round(sum(all_scores) / len(all_scores), 2)

        cursor.execute("""SELECT AVG((sa.fluency_score + COALESCE(sa.confidence_score, sa.fluency_score)
                                  + COALESCE(sa.clarity_score, sa.fluency_score)) / 3) AS speech_score                      FROM speech_analysis sa
                      JOIN responses r ON r.response_id = sa.response_id
                      JOIN interview_questions iq ON iq.interview_question_id = r.interview_question_id
                      WHERE iq.interview_id = %s""", (interview_id,))
    speech = cursor.fetchone()["speech_score"]
    if speech is not None:
        speech = round(float(speech), 2)
        overall = round(quality * 0.7 + speech * 0.3, 2)   # adjust weights to match your paper
    else:
        overall = quality   # older typed-answer interviews have no speech data

    cursor.execute("""INSERT INTO evaluations
                      (interview_id, response_quality_score, speech_performance_score, overall_score)
                      VALUES (%s, %s, %s, %s)""", (interview_id, quality, speech, overall))
    cursor.execute("""INSERT INTO feedback (interview_id, strengths, areas_to_improve, recommendations)
                      VALUES (%s, %s, %s, %s)""",
                   (interview_id, result["strengths"], result["areas_to_improve"], result["recommendations"]))
    cursor.execute("UPDATE interviews SET overall_score = %s WHERE interview_id = %s", (overall, interview_id))
    conn.commit()
    conn.close()
    
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
    with ThreadPoolExecutor(max_workers=3) as pool:   # process 3 answers at a time
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
            conn.commit()
    conn.close()

    if failed:
        raise RuntimeError(f"{failed} answer(s) could not be transcribed.")


def process_interview(interview_id):
    """Transcribe all answers, then evaluate the whole interview."""
    transcribe_pending(interview_id)
    evaluate_interview(interview_id)

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

        cursor.execute(
            "INSERT INTO users (full_name, email, password) VALUES (%s, %s, %s)",
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
            session["user_id"] = user["user_id"]
            session["full_name"] = user["full_name"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))

        flash("Incorrect email or password.")
        return redirect(url_for("login"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You've been logged out.")
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""SELECT * FROM interviews WHERE user_id = %s
                      ORDER BY started_at DESC""", (session["user_id"],))
    interviews = cursor.fetchall()

    cursor.execute("""SELECT i.category, i.completed_at, e.overall_score,
                             e.response_quality_score, e.speech_performance_score
                      FROM interviews i
                      JOIN evaluations e ON e.interview_id = i.interview_id
                      WHERE i.user_id = %s AND i.status = 'completed'
                      ORDER BY i.completed_at""", (session["user_id"],))
    history = cursor.fetchall()
    conn.close()

    def num(value):
        return float(value) if value is not None else None

    chart = {
        "labels": [f"#{n} ({h['completed_at'].strftime('%b %d')})" if h["completed_at"] else f"#{n}"
                   for n, h in enumerate(history, start=1)],
        "overall": [num(h["overall_score"]) for h in history],
        "quality": [num(h["response_quality_score"]) for h in history],
        "speech": [num(h["speech_performance_score"]) for h in history],
        "categories": [h["category"] for h in history],
    }

    stats = None
    scores = [s for s in chart["overall"] if s is not None]
    if scores:
        stats = {
            "count": len(scores),
            "average": round(sum(scores) / len(scores), 2),
            "best": max(scores),
            "latest": scores[-1],
            "change": round(scores[-1] - scores[0], 2) if len(scores) > 1 else None,
        }

    return render_template("dashboard.html", interviews=interviews, chart=chart, stats=stats)

@app.route("/interview/start", methods=["GET", "POST"])
@login_required
def start_interview():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        if request.form.get("consent") != "yes":
            conn.close()
            flash("You need to agree to be recorded before starting the interview.")
            return redirect(url_for("start_interview"))
        category = request.form["category"]
        difficulty = request.form["difficulty"]
        try:
            count = min(max(int(request.form["number_of_questions"]), 1), 10)
        except ValueError:
            count = 5

        cursor.execute("""SELECT question_id FROM question_bank
                          WHERE is_active = 1 AND category = %s AND difficulty = %s
                          ORDER BY RAND() LIMIT %s""", (category, difficulty, count))
        questions = cursor.fetchall()

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
    if iv["status"] != "in_progress":
        conn.close()
        return redirect(url_for("interview_summary", interview_id=interview_id))
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

        audio_bytes = audio.read()   # keep the recording in memory; never save it unencrypted

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
        conn.commit()
        conn.close()
        return jsonify(ok=True)

    conn.close()
    return render_template("interview.html", iv=iv, current=current)

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

    cursor.execute("""SELECT iq.question_order, qb.question_text, r.transcript, r.audio_path,
                    n.relevance_score, n.clarity_score, n.completeness_score, n.grammar_score,
                    n.word_count, n.vocabulary_diversity, n.keyword_count, n.keywords_found,
                    s.speaking_rate, s.filler_word_count, s.pause_count, s.fluency_score, s.total_pause_time,
                    s.longest_pause, s.pitch_variation,
                    s.volume_variation, s.speech_ratio, s.confidence_score, s.volume_variation, s.speech_ratio, s.confidence_score, s.clarity_score AS speech_clarity
                    FROM interview_questions iq
                    JOIN question_bank qb ON qb.question_id = iq.question_id
                    LEFT JOIN responses r ON r.interview_question_id = iq.interview_question_id
                    LEFT JOIN nlp_analysis n ON n.response_id = r.response_id
                    LEFT JOIN speech_analysis s ON s.response_id = r.response_id
                    WHERE iq.interview_id = %s
                    ORDER BY iq.question_order""", (interview_id,))
    answers = cursor.fetchall()
    cursor.execute("SELECT * FROM evaluations WHERE interview_id = %s", (interview_id,))
    evaluation = cursor.fetchone()
    cursor.execute("SELECT * FROM feedback WHERE interview_id = %s ORDER BY created_at DESC LIMIT 1",
                   (interview_id,))
    fb = cursor.fetchone()
    conn.close()
    return render_template("interview_summary.html", iv=iv, answers=answers,
                           evaluation=evaluation, fb=fb)

@app.route("/interview/<int:interview_id>/evaluate", methods=["POST"])
@login_required
def retry_evaluation(interview_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""SELECT interview_id FROM interviews
                      WHERE interview_id = %s AND user_id = %s AND status = 'completed'""",
                   (interview_id, session["user_id"]))
    found = cursor.fetchone()
    conn.close()
    if not found:
        flash("Interview not found.")
        return redirect(url_for("dashboard"))
    try:
        process_interview(interview_id)(interview_id)
        flash("Evaluation complete!")
    except Exception as e:
        print("Evaluation failed:", e)
        flash("The AI evaluation failed again. Check the terminal for the error.")
    return redirect(url_for("interview_summary", interview_id=interview_id))

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
        return jsonify(ok=False, error="We couldn't finish analyzing your interview. "
                                       "Your answers are saved. Please try again."), 503

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


if __name__ == "__main__":
    app.run(debug=True)