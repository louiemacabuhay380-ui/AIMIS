"""Security protections for AIMIS (registered in app.py with security.register(app, get_db)).

1. CSRF tokens   - every POST (forms and fetch requests) must carry a secret token from this site,
                   so another website can't submit actions as a logged-in student.
2. Login lockout - 5 wrong passwords for the same email from the same computer locks login for 15 minutes.
                   Password reset emails are limited too (3 per 15 minutes).
3. Cookies and security headers - session cookie can't be read by JavaScript or sent by other sites;
                   the browser is told not to sniff file types or show AIMIS inside other websites.
4. Account check on every request - a deactivated, deleted or demoted account is logged out right away.
(Debug mode is controlled by FLASK_DEBUG in .env; see the bottom of app.py.)
"""
import os
import secrets
import time
import threading

from flask import request, session, redirect, url_for, flash, jsonify, g

MAX_LOGIN_FAILURES = 5
LOCK_SECONDS = 15 * 60
MAX_RESET_EMAILS = 3
RESET_WINDOW_SECONDS = 15 * 60

_lock = threading.Lock()
_login_failures = {}   # (email, ip) -> [time of each failure]
_reset_requests = {}   # (email or ip) -> [time of each request]


def _recent(times, window):
    now = time.time()
    return [t for t in times if now - t < window]


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def register(app, get_db):
    # ---------------------------------------------------------------- 3. cookies
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,      # JavaScript can't read the login cookie
        SESSION_COOKIE_SAMESITE="Lax",     # other websites can't send it with their requests
        # Only send the cookie over HTTPS. Turn on when AIMIS is served with HTTPS (SESSION_COOKIE_SECURE=1).
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE") == "1",
    )
    app.jinja_env.globals["csrf_token"] = csrf_token

    def wants_json():
        return request.is_json or request.headers.get("X-CSRF-Token") is not None \
            or request.accept_mimetypes.best == "application/json"

    # ---------------------------------------------------------------- 1. CSRF
    @app.before_request
    def check_csrf():
        if request.method != "POST":
            return
        sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
        expected = session.get("csrf_token")
        if expected and sent and secrets.compare_digest(sent, expected):
            return
        g.request_blocked = True
        print(f"Blocked a POST to {request.path} without a valid CSRF token")
        if wants_json() or request.path.startswith("/chat/"):
            return jsonify(ok=False, error="Your session expired. Please reload the page and try again."), 400
        flash("Your session expired or the form was out of date. Please try again.")
        return redirect(request.referrer if request.referrer and request.referrer.startswith(request.host_url)
                        else url_for("login"))

    # ---------------------------------------------------------------- 2. login lockout + reset email limit
    def login_key():
        return ((request.form.get("email") or "").strip().lower(), request.remote_addr or "")

    @app.before_request
    def check_login_lock():
        if request.method != "POST":
            return
        if request.endpoint == "login":
            with _lock:
                fails = _recent(_login_failures.get(login_key(), []), LOCK_SECONDS)
                _login_failures[login_key()] = fails
            if len(fails) >= MAX_LOGIN_FAILURES:
                g.request_blocked = True
                minutes = max(1, int((LOCK_SECONDS - (time.time() - fails[0])) // 60) + 1)
                flash(f"Too many wrong passwords. For your security, login for this account is locked "
                      f"for about {minutes} minute{'s' if minutes != 1 else ''}. You can also reset your password.")
                return redirect(url_for("login"))
        if request.endpoint == "forgot_password":
            keys = [(request.form.get("email") or "").strip().lower(), request.remote_addr or ""]
            with _lock:
                if any(len(_recent(_reset_requests.get(k, []), RESET_WINDOW_SECONDS)) >= MAX_RESET_EMAILS for k in keys):
                    flash("Too many reset requests. Please wait 15 minutes, then check your inbox and spam folder.")
                    return redirect(url_for("forgot_password"))
                for k in keys:
                    _reset_requests[k] = _recent(_reset_requests.get(k, []), RESET_WINDOW_SECONDS) + [time.time()]

    @app.after_request
    def count_login_result(response):
        if (request.method == "POST" and request.endpoint == "login" and not g.get("request_blocked")
                and response.status_code in (301, 302, 303)):
            failed = response.location and response.location.rstrip("/").endswith(url_for("login").rstrip("/"))
            with _lock:
                if failed:
                    _login_failures[login_key()] = _recent(_login_failures.get(login_key(), []), LOCK_SECONDS) + [time.time()]
                elif not failed:
                    _login_failures.pop(login_key(), None)   # logged in: forget the failures
        return response

    # ---------------------------------------------------------------- 3. security headers
    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")   # don't guess file types
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")        # no AIMIS inside other sites
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(self), geolocation=()")
        if request.endpoint and request.endpoint != "static" and "user_id" in session:
            response.headers.setdefault("Cache-Control", "no-store")         # no private pages in the browser cache
        return response

    # ---------------------------------------------------------------- 4. account check on every request
    @app.before_request
    def check_account_still_valid():
        if "user_id" not in session or request.endpoint in (None, "static", "logout"):
            return
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE user_id = %s", (session["user_id"],))
        user = cursor.fetchone()
        conn.close()
        if not user or not user.get("is_active", 1):
            session.clear()
            flash("Your account is no longer active. Please contact the AIMIS administrator."
                  if user else "Your account no longer exists.")
            if request.path.startswith("/chat/") or request.is_json:
                return jsonify(ok=False, error="Please log in again."), 401
            return redirect(url_for("login"))
        if session.get("role") != user.get("role"):
            session["role"] = user.get("role")     # e.g. admin rights removed: takes effect immediately
