"""My data: students can see what AIMIS keeps about them and delete it.
Also deletes old voice recordings automatically (RECORDING_RETENTION_DAYS in .env, default 30)."""
import os
import threading
import time
from datetime import datetime, timedelta

from flask import render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash

CLEANUP_EVERY_SECONDS = 6 * 60 * 60   # check for old recordings at most every 6 hours


def retention_days():
    try:
        return max(1, int(os.getenv("RECORDING_RETENTION_DAYS") or 30))
    except ValueError:
        return 30


def _missing_table(e):
    return getattr(e, "errno", None) == 1146


def _in(ids):
    return ", ".join(["%s"] * len(ids))


def _delete(cursor, table, column, ids):
    """DELETE FROM table WHERE column IN ids. Skips tables that don't exist yet."""
    if not ids:
        return
    try:
        cursor.execute(f"DELETE FROM {table} WHERE {column} IN ({_in(ids)})", list(ids))
    except Exception as e:
        if not _missing_table(e):
            raise


def delete_user_data(conn, root_path, user_id, delete_account=False):
    """Delete every interview, recording, score, feedback, chatbot record and consent of one user
    (and the account itself if delete_account). Returns the number of recordings removed."""
    cursor = conn.cursor()
    cursor.execute("SELECT interview_id FROM interviews WHERE user_id = %s", (user_id,))
    interview_ids = [r[0] for r in cursor.fetchall()]
    question_ids, response_ids, audio_files, own_questions = [], [], [], []
    if interview_ids:
        cursor.execute(f"SELECT interview_question_id, question_id FROM interview_questions WHERE interview_id IN ({_in(interview_ids)})",
                       interview_ids)
        rows = cursor.fetchall()
        question_ids = [r[0] for r in rows]
        # Questions written only for this student (live questions and follow-ups about their answers)
        bank_ids = list({r[1] for r in rows})
        if bank_ids:
            try:
                cursor.execute(f"SELECT question_id FROM question_bank WHERE question_id IN ({_in(bank_ids)}) "
                               "AND review_status IN ('live', 'followup')", bank_ids)
                own_questions = [r[0] for r in cursor.fetchall()]
            except Exception as e:
                if getattr(e, "errno", None) != 1054:
                    raise
    if question_ids:
        cursor.execute(f"SELECT response_id, audio_path FROM responses WHERE interview_question_id IN ({_in(question_ids)})",
                       question_ids)
        for response_id, audio_path in cursor.fetchall():
            response_ids.append(response_id)
            if audio_path:
                audio_files.append(os.path.join(root_path, audio_path))

    try:
        # Children first, so foreign keys never block the delete
        for table in ("nlp_analysis", "speech_analysis", "behavior_analysis", "answer_feedback", "skill_labels",
                      "human_ratings"):
            _delete(cursor, table, "response_id", response_ids)
        _delete(cursor, "responses", "response_id", response_ids)
        _delete(cursor, "interview_questions", "interview_question_id", question_ids)
        _delete(cursor, "question_bank", "question_id", own_questions)
        for table in ("evaluations", "feedback", "feedback_items", "rag_chunks", "consents"):
            _delete(cursor, table, "interview_id", interview_ids)
        for table in ("rag_chunks", "chat_messages", "consents"):
            _delete(cursor, table, "user_id", [user_id])
        _delete(cursor, "interviews", "interview_id", interview_ids)
        if delete_account:
            _delete(cursor, "human_ratings", "rater_id", [user_id])   # ratings this person gave as an evaluator
            _delete(cursor, "users", "user_id", [user_id])
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    removed = 0
    for path in audio_files:            # files are removed only after the database delete succeeded
        try:
            if os.path.exists(path):
                os.remove(path)
                removed += 1
        except OSError as e:
            print("Could not delete recording:", path, e)
    return removed


def cleanup_old_recordings(get_db, root_path, days=None):
    """Delete voice recordings older than the retention period. Transcripts and scores are kept."""
    days = days or retention_days()
    cutoff = datetime.now() - timedelta(days=days)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""SELECT r.response_id, r.audio_path FROM responses r
                      JOIN interview_questions iq ON iq.interview_question_id = r.interview_question_id
                      JOIN interviews i ON i.interview_id = iq.interview_id
                      WHERE r.audio_path IS NOT NULL
                        AND COALESCE(i.completed_at, i.started_at) < %s""", (cutoff,))
    rows = cursor.fetchall()
    removed = 0
    for response_id, audio_path in rows:
        path = os.path.join(root_path, audio_path)
        try:
            if os.path.exists(path):
                os.remove(path)
            cursor.execute("UPDATE responses SET audio_path = NULL WHERE response_id = %s", (response_id,))
            removed += 1
        except OSError as e:
            print("Could not delete old recording:", path, e)
    conn.commit()
    conn.close()
    if removed:
        print(f"Deleted {removed} voice recording(s) older than {days} days.")
    return removed


def register(app, get_db):
    last_cleanup = {"at": 0.0}
    lock = threading.Lock()

    @app.before_request
    def auto_delete_old_recordings():
        """Runs the retention cleanup in the background, at most every few hours."""
        if time.time() - last_cleanup["at"] < CLEANUP_EVERY_SECONDS or not lock.acquire(blocking=False):
            return
        last_cleanup["at"] = time.time()

        def work():
            try:
                cleanup_old_recordings(get_db, app.root_path)
            except Exception as e:
                print("Old recording cleanup failed:", e)
            finally:
                lock.release()
        threading.Thread(target=work, daemon=True).start()

    def summary(cursor, user_id):
        def count(sql, params=(user_id,)):
            try:
                cursor.execute(sql, params)
                return cursor.fetchone()[0] or 0
            except Exception as e:
                if _missing_table(e):
                    return 0
                raise
        return {
            "interviews": count("SELECT COUNT(*) FROM interviews WHERE user_id = %s"),
            "answers": count("""SELECT COUNT(*) FROM responses r
                                JOIN interview_questions iq ON iq.interview_question_id = r.interview_question_id
                                JOIN interviews i ON i.interview_id = iq.interview_id WHERE i.user_id = %s"""),
            "recordings": count("""SELECT COUNT(*) FROM responses r
                                   JOIN interview_questions iq ON iq.interview_question_id = r.interview_question_id
                                   JOIN interviews i ON i.interview_id = iq.interview_id
                                   WHERE i.user_id = %s AND r.audio_path IS NOT NULL"""),
            "chats": count("SELECT COUNT(*) FROM chat_messages WHERE user_id = %s"),
        }

    def check_password(cursor, user_id):
        cursor.execute("SELECT password, role FROM users WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()
        ok = bool(row) and check_password_hash(row[0], request.form.get("password", ""))
        return ok, (row[1] if row else None)

    def my_data():
        if "user_id" not in session:
            flash("Please log in first.")
            return redirect(url_for("login"))
        conn = get_db()
        cursor = conn.cursor()
        data = summary(cursor, session["user_id"])
        conn.close()
        return render_template("my_data.html", data=data, days=retention_days())

    def delete_interviews():
        if "user_id" not in session:
            return redirect(url_for("login"))
        conn = get_db()
        cursor = conn.cursor()
        ok, _ = check_password(cursor, session["user_id"])
        if not ok:
            conn.close()
            flash("Wrong password. Nothing was deleted.")
            return redirect(url_for("my_data"))
        try:
            delete_user_data(conn, app.root_path, session["user_id"])
            flash("All your interviews, recordings, scores, feedback and chats were deleted. Your account is still here.")
        except Exception as e:
            print("Delete my interviews failed:", e)
            flash("Your data couldn't be deleted because of a database error. Nothing was changed. "
                  "Please tell the administrator.")
        conn.close()
        return redirect(url_for("my_data"))

    def delete_account():
        if "user_id" not in session:
            return redirect(url_for("login"))
        if request.form.get("confirm", "").strip().upper() != "DELETE":
            flash('Type DELETE in the box to confirm. Nothing was deleted.')
            return redirect(url_for("my_data"))
        conn = get_db()
        cursor = conn.cursor()
        ok, role = check_password(cursor, session["user_id"])
        if not ok:
            conn.close()
            flash("Wrong password. Nothing was deleted.")
            return redirect(url_for("my_data"))
        if role == "admin":
            cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
            if cursor.fetchone()[0] <= 1:
                conn.close()
                flash("You are the only administrator. Make another account an admin before deleting yours.")
                return redirect(url_for("my_data"))
        try:
            delete_user_data(conn, app.root_path, session["user_id"], delete_account=True)
        except Exception as e:
            print("Delete account failed:", e)
            conn.close()
            flash("Your account couldn't be deleted because of a database error. Nothing was changed. "
                  "Please tell the administrator.")
            return redirect(url_for("my_data"))
        conn.close()
        session.clear()
        flash("Your account and all your data have been permanently deleted.")
        return redirect(url_for("login"))

    app.add_url_rule("/my-data", "my_data", my_data)
    app.add_url_rule("/my-data/delete-interviews", "delete_my_interviews", delete_interviews, methods=["POST"])
    app.add_url_rule("/my-data/delete-account", "delete_my_account", delete_account, methods=["POST"])
