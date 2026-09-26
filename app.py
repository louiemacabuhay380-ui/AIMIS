import os
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import mysql.connector

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

def get_db():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"), database=os.getenv("DB_NAME"))

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

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
    conn.close()
    return render_template("dashboard.html", interviews=interviews)

@app.route("/interview/start", methods=["GET", "POST"])
@login_required
def start_interview():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
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

        for order, q in enumerate(questions, start=1):
            cursor.execute("""INSERT INTO interview_questions (interview_id, question_id, question_order)
                              VALUES (%s, %s, %s)""", (interview_id, q["question_id"], order))
        conn.commit()
        conn.close()
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
                          WHERE interview_id = %s""", (interview_id,))
        conn.commit()
        conn.close()
        return redirect(url_for("interview_summary", interview_id=interview_id))

    if request.method == "POST":
        answer = request.form["answer"].strip()
        submitted_id = int(request.form["interview_question_id"])
        if not answer:
            flash("Please type an answer before continuing.")
        elif submitted_id == current["interview_question_id"]:
            cursor.execute("""INSERT INTO responses (interview_question_id, transcript)
                              VALUES (%s, %s)""", (submitted_id, answer))
            conn.commit()
        conn.close()
        return redirect(url_for("interview", interview_id=interview_id))

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

    cursor.execute("""SELECT iq.question_order, qb.question_text, r.transcript
                      FROM interview_questions iq
                      JOIN question_bank qb ON qb.question_id = iq.question_id
                      LEFT JOIN responses r ON r.interview_question_id = iq.interview_question_id
                      WHERE iq.interview_id = %s
                      ORDER BY iq.question_order""", (interview_id,))
    answers = cursor.fetchall()
    conn.close()
    return render_template("interview_summary.html", iv=iv, answers=answers)

if __name__ == "__main__":
    app.run(debug=True)