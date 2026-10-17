"""
Forgot password: the user enters their email and receives a reset link that
works once and expires after 30 minutes.

Email settings go in .env (see .env.example). If they are missing, the link is
printed in the terminal instead, which is handy for testing and demos.
"""
import os
import smtplib
from email.message import EmailMessage

from flask import render_template, request, redirect, url_for, flash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.security import generate_password_hash

RESET_MINUTES = 30
MIN_PASSWORD_LENGTH = 8


def register(app, get_db):
    """Add the forgot-password pages to the app."""
    serializer = URLSafeTimedSerializer(app.secret_key, salt="aimis-password-reset")

    def make_token(user):
        # Includes part of the current password hash, so the link stops working
        # as soon as the password is changed (each link can be used only once).
        return serializer.dumps({"uid": user["user_id"], "h": user["password"][-16:]})

    def read_token(token):
        """Return the user for a valid link, or None if it's invalid, expired, or already used."""
        try:
            data = serializer.loads(token, max_age=RESET_MINUTES * 60)
        except (SignatureExpired, BadSignature):
            return None
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT user_id, full_name, email, password FROM users WHERE user_id = %s", (data.get("uid"),))
        user = cursor.fetchone()
        conn.close()
        if not user or user["password"][-16:] != data.get("h"):
            return None
        return user

    def send_reset_email(user, link):
        sender = os.getenv("MAIL_USERNAME")
        password = os.getenv("MAIL_PASSWORD")
        if not sender or not password:
            print("\n=== Password reset link (email is not set up in .env) ===")
            print(f"For {user['email']}: {link}\n")
            return
        msg = EmailMessage()
        msg["Subject"] = "Reset your AIMIS password"
        msg["From"] = f"AIMIS <{sender}>"
        msg["To"] = user["email"]
        msg.set_content(
            f"Hi {user['full_name'].split(' ')[0]},\n\n"
            f"We received a request to reset your AIMIS password. Open this link to choose a new one:\n\n"
            f"{link}\n\n"
            f"The link works once and expires in {RESET_MINUTES} minutes.\n"
            f"If you didn't ask for this, you can ignore this email; your password won't change.\n\n"
            f"AIMIS: AI Mock Interview System")
        with smtplib.SMTP_SSL(os.getenv("MAIL_SERVER", "smtp.gmail.com"),
                              int(os.getenv("MAIL_PORT", "465")), timeout=20) as smtp:
            smtp.login(sender, password)
            smtp.send_message(msg)

    def forgot_password():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            conn = get_db()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT user_id, full_name, email, password FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            conn.close()
            if user:
                link = url_for("reset_password", token=make_token(user), _external=True)
                try:
                    send_reset_email(user, link)
                except Exception as e:
                    print("Couldn't send the reset email:", e)
                    flash("We couldn't send the email right now. Please try again in a few minutes.")
                    return redirect(url_for("forgot_password"))
            # Same message either way, so nobody can use this page to check which emails have accounts
            flash(f"If an account uses {email}, a reset link is on its way. Check your inbox and spam folder.")
            return redirect(url_for("login"))
        return render_template("forgot_password.html")

    def reset_password(token):
        user = read_token(token)
        if not user:
            flash("That reset link is invalid, already used, or expired. Please request a new one.")
            return redirect(url_for("forgot_password"))
        if request.method == "POST":
            new = request.form.get("password", "")
            confirm = request.form.get("confirm", "")
            if len(new) < MIN_PASSWORD_LENGTH:
                flash(f"Your new password needs at least {MIN_PASSWORD_LENGTH} characters.")
            elif new != confirm:
                flash("The two passwords don't match.")
            else:
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET password = %s WHERE user_id = %s",
                               (generate_password_hash(new), user["user_id"]))
                conn.commit()
                conn.close()
                flash("Your password has been changed. You can log in now.")
                return redirect(url_for("login"))
            return redirect(url_for("reset_password", token=token))
        return render_template("reset_password.html", email=user["email"])

    app.add_url_rule("/forgot-password", "forgot_password", forgot_password, methods=["GET", "POST"])
    app.add_url_rule("/reset-password/<token>", "reset_password", reset_password, methods=["GET", "POST"])
