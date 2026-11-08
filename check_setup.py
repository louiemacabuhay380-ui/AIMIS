"""AIMIS setup check: tells you in seconds what this PC is missing.

    python check_setup.py          only checks, changes nothing
    python check_setup.py --fix    also adds missing database tables and columns (safe: never deletes data)
    python check_setup.py --gemini also sends one tiny test request to Gemini (uses 1 request of your quota)
"""
import os
import sys
import importlib
import urllib.request
import json

from dotenv import load_dotenv

FIX = "--fix" in sys.argv
TEST_GEMINI = "--gemini" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

problems, warnings = [], []


def ok(msg):
    print(f"  [OK]    {msg}")


def warn(msg, fix=None):
    warnings.append(msg)
    print(f"  [WARN]  {msg}" + (f"\n          -> {fix}" if fix else ""))


def fail(msg, fix=None):
    problems.append(msg)
    print(f"  [FAIL]  {msg}" + (f"\n          -> {fix}" if fix else ""))


# ---------------------------------------------------------------- 1. Python packages
print("\n1. Python packages")
PACKAGES = [("flask", "flask"), ("dotenv", "python-dotenv"), ("mysql.connector", "mysql-connector-python"),
            ("google.genai", "google-genai"), ("cryptography", "cryptography"), ("numpy", "numpy"),
            ("librosa", "librosa"), ("nltk", "nltk"), ("itsdangerous", "itsdangerous")]
for module, pip_name in PACKAGES:
    try:
        importlib.import_module(module)
        ok(pip_name)
    except ImportError:
        fail(f"{pip_name} is not installed", f"pip install {pip_name}")
try:
    importlib.import_module("faster_whisper")
    ok("faster-whisper (offline speech-to-text backup)")
except ImportError:
    warn("faster-whisper is not installed, so there is no backup if Gemini speech-to-text fails",
         "optional: pip install faster-whisper")
try:
    sys.path.insert(0, HERE)
    from nlp_service import analyze_text
    analyze_text("I led our group. We finished the project on time.", "Teamwork")
    ok("NLTK data (text analysis works)")
except Exception as e:
    fail(f"Text analysis failed: {e}", "python -m nltk.downloader punkt punkt_tab stopwords")

# ---------------------------------------------------------------- 2. .env settings
print("\n2. .env settings")
if not os.path.exists(os.path.join(HERE, ".env")):
    fail(".env file is missing", "copy .env.example to .env and fill it in")
for key in ("SECRET_KEY", "DB_HOST", "DB_USER", "DB_NAME", "GEMINI_API_KEY", "AUDIO_ENCRYPTION_KEY"):
    if os.getenv(key):
        ok(key)
    else:
        fail(f"{key} is empty or missing in .env", "see .env.example")
if os.getenv("DB_PASSWORD") is None:
    warn("DB_PASSWORD is not set (fine only if your MySQL root has no password)")
key = os.getenv("AUDIO_ENCRYPTION_KEY")
if key:
    try:
        from cryptography.fernet import Fernet
        Fernet(key.encode())
        ok("AUDIO_ENCRYPTION_KEY is a valid key")
    except Exception:
        fail("AUDIO_ENCRYPTION_KEY is not a valid key",
             'make one: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
             " (only for a NEW install: old recordings need the old key)")
if os.getenv("MAIL_USERNAME") and os.getenv("MAIL_PASSWORD"):
    ok("Email (Forgot password) is set up")
else:
    warn("MAIL_USERNAME / MAIL_PASSWORD not set: Forgot password prints the link in the terminal instead")
if os.getenv("FLASK_DEBUG") == "1":
    warn("FLASK_DEBUG=1 is on: turn it off (remove the line) before the defense or any shared network")

# ---------------------------------------------------------------- 3. Database
print("\n3. Database")
# table -> {column: definition used when --fix adds it (None = part of the original database)}
DEC = "DECIMAL(5,2) NULL"
SCHEMA = {
    "users": {"user_id": None, "full_name": None, "email": None, "password": None, "role": None,
              "is_active": "TINYINT(1) NOT NULL DEFAULT 1"},
    "interviews": {"interview_id": None, "user_id": None, "category": None, "difficulty": None,
                   "number_of_questions": None, "status": None, "started_at": None, "completed_at": None,
                   "overall_score": None},
    "question_bank": {"question_id": None, "category": None, "difficulty": None, "question_text": None,
                      "is_active": None, "source": "VARCHAR(10) NOT NULL DEFAULT 'manual'",
                      "review_status": "VARCHAR(10) NOT NULL DEFAULT 'approved'"},
    "interview_questions": {"interview_question_id": None, "interview_id": None, "question_id": None,
                            "question_order": None},
    "responses": {"response_id": None, "interview_question_id": None, "transcript": None, "audio_path": None,
                  "duration": None},
    "consents": {"user_id": None, "interview_id": None, "consent_given": None, "consent_version": None},
    "nlp_analysis": {"response_id": None, "relevance_score": None, "clarity_score": None,
                     "completeness_score": None, "grammar_score": None, "word_count": "INT NULL",
                     "sentence_count": "INT NULL", "vocabulary_diversity": DEC, "keyword_count": "INT NULL",
                     "keywords_found": "VARCHAR(500) NULL"},
    "speech_analysis": {"response_id": None, "speaking_rate": None, "filler_word_count": None, "pause_count": None,
                        "speech_duration": None, "fluency_score": None, "total_pause_time": "DECIMAL(6,2) NULL",
                        "longest_pause": "DECIMAL(6,2) NULL", "average_pause": "DECIMAL(6,2) NULL",
                        "pitch_variation": DEC, "average_volume": "DECIMAL(6,2) NULL", "volume_variation": DEC,
                        "speech_ratio": DEC, "confidence_score": DEC, "clarity_score": DEC,
                        "transcribed_by": "VARCHAR(20) NULL"},
    "behavior_analysis": {"response_id": None, "eye_contact_score": None, "face_visibility_score": None,
                          "facial_expression_score": DEC, "gesture_score": DEC, "smile_ratio": DEC,
                          "gesture_ratio": DEC, "frames_analyzed": "INT NULL", "hands_visible_ratio": DEC,
                          "expressive_gesture_ratio": DEC, "face_touch_ratio": DEC},
    "evaluations": {"interview_id": None, "response_quality_score": None, "speech_performance_score": None,
                    "behavioral_score": None, "overall_score": None, "scored_by": "VARCHAR(20) NULL"},
    "feedback": {"interview_id": None, "strengths": None, "areas_to_improve": None, "recommendations": None},
}
# New tables, created whole by --fix (same as the SQL files in database/, kept here so no file is needed)
NEW_TABLES = {
    "answer_feedback": """CREATE TABLE IF NOT EXISTS answer_feedback (
        response_id INT PRIMARY KEY, feedback TEXT, weak_quote TEXT, better_answer TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    "skill_labels": """CREATE TABLE IF NOT EXISTS skill_labels (
        label_id INT AUTO_INCREMENT PRIMARY KEY, response_id INT NOT NULL, skill VARCHAR(40) NOT NULL,
        rating VARCHAR(10) NOT NULL, reason VARCHAR(300),
        INDEX idx_label_response (response_id), INDEX idx_label_skill (skill))""",
    "rag_chunks": """CREATE TABLE IF NOT EXISTS rag_chunks (
        chunk_id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, interview_id INT NOT NULL,
        response_id INT NULL, question_order INT NULL, kind VARCHAR(20) NOT NULL, content TEXT NOT NULL,
        embedding MEDIUMTEXT NULL, embed_model VARCHAR(80) NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_chunk_user (user_id), INDEX idx_chunk_interview (interview_id))""",
    "chat_messages": """CREATE TABLE IF NOT EXISTS chat_messages (
        message_id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, interview_id INT NULL,
        role VARCHAR(10) NOT NULL, content TEXT NOT NULL, sources TEXT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, INDEX idx_chat_user (user_id))""",
    "feedback_items": """CREATE TABLE IF NOT EXISTS feedback_items (
        item_id INT AUTO_INCREMENT PRIMARY KEY, interview_id INT NOT NULL, kind VARCHAR(12) NOT NULL,
        answer_no INT NULL, point TEXT, quote TEXT, fix TEXT, example TEXT, sort_order INT NOT NULL DEFAULT 0,
        INDEX idx_item_interview (interview_id))""",
    "human_ratings": """CREATE TABLE IF NOT EXISTS human_ratings (
        rating_id INT AUTO_INCREMENT PRIMARY KEY, response_id INT NOT NULL, rater_id INT NOT NULL,
        relevance TINYINT NOT NULL, clarity TINYINT NOT NULL, completeness TINYINT NOT NULL, grammar TINYINT NOT NULL,
        comment VARCHAR(500) NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_rating (response_id, rater_id), INDEX idx_rating_rater (rater_id))""",
}


try:
    import mysql.connector
    conn = mysql.connector.connect(host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"),
                                   password=os.getenv("DB_PASSWORD"), database=os.getenv("DB_NAME"),
                                   buffered=True, connection_timeout=5)
    ok(f"Connected to MySQL database '{os.getenv('DB_NAME')}'")
except Exception as e:
    conn = None
    fail(f"Can't connect to MySQL: {e}",
         "start MySQL (XAMPP/Services), and check DB_HOST, DB_USER, DB_PASSWORD, DB_NAME in .env")

if conn:
    cursor = conn.cursor()
    cursor.execute("""SELECT TABLE_NAME, COLUMN_NAME, IS_NULLABLE, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
                      WHERE TABLE_SCHEMA = DATABASE()""")
    existing = {}
    for table, column, nullable, dtype in cursor.fetchall():
        existing.setdefault(table.lower(), {})[column.lower()] = (nullable, dtype)

    changed = False
    for table, columns in SCHEMA.items():
        if table not in existing:
            fail(f"Table '{table}' is missing (part of the original AIMIS database)",
                 "import the group's original AIMIS database first")
            continue
        missing = [c for c in columns if c not in existing[table]]
        base_missing = [c for c in missing if columns[c] is None]
        addable = [c for c in missing if columns[c] is not None]
        if base_missing:
            fail(f"{table} is missing original columns: {', '.join(base_missing)}",
                 "this database doesn't match AIMIS; import the group's original database")
        if addable and FIX:
            for c in addable:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {c} {columns[c]}")
            changed = True
            ok(f"{table}: added {', '.join(addable)}")
        elif addable:
            fail(f"{table} is missing: {', '.join(addable)}", "run: python check_setup.py --fix")
        elif not base_missing:
            ok(table)

    # Old columns that make inserts fail
    behavior = existing.get("behavior_analysis", {})
    old_fixes = []
    if "posture_score" in behavior and behavior["posture_score"][0] == "NO":
        old_fixes.append(("behavior_analysis.posture_score must allow empty values (posture was removed)",
                          "ALTER TABLE behavior_analysis MODIFY posture_score DECIMAL(5,2) NULL"))
    for c in ("eye_contact_score", "face_visibility_score"):
        if c in behavior and behavior[c][0] == "NO":
            old_fixes.append((f"behavior_analysis.{c} must allow empty values (no camera)",
                              f"ALTER TABLE behavior_analysis MODIFY {c} DECIMAL(5,2) NULL"))
    if existing.get("users", {}).get("role", ("", ""))[1] == "enum":
        old_fixes.append(("users.role can't hold 'admin'/'rater' (it is a fixed list)",
                          "ALTER TABLE users MODIFY role VARCHAR(20) NOT NULL DEFAULT 'student'"))
    for msg, sql in old_fixes:
        if FIX:
            cursor.execute(sql)
            changed = True
            ok("fixed: " + msg)
        else:
            fail(msg, "run: python check_setup.py --fix")

    for table, create_sql in NEW_TABLES.items():
        if table in existing:
            ok(table)
        elif FIX:
            cursor.execute(create_sql)
            existing[table] = {}
            changed = True
            ok(f"{table}: created")
        else:
            fail(f"Table '{table}' is missing", "run: python check_setup.py --fix")
    if changed:
        conn.commit()

    # Content checks
    try:
        cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        if cursor.fetchone()[0]:
            ok("At least one admin account exists")
        else:
            warn("No admin account yet",
                 "in SQLyog: UPDATE users SET role = 'admin' WHERE email = 'your@email.com';")
        cursor.execute("""SELECT category, difficulty, COUNT(*) FROM question_bank WHERE is_active = 1
                          GROUP BY category, difficulty""")
        rows = cursor.fetchall()
        thin = [f"{c} ({d}): {n}" for c, d, n in rows if n < 3]
        ok(f"Question bank: {sum(n for _, _, n in rows)} active questions in {len({c for c, _, _ in rows})} skills")
        if thin:
            warn("Some skill/level pairs have fewer than 3 questions: " + "; ".join(thin),
                 "add questions in Admin > Questions")
    except Exception as e:
        warn(f"Couldn't check accounts/questions: {e}")
    conn.close()

# ---------------------------------------------------------------- 4. Local AI (Ollama)
print("\n4. Local AI (Ollama: chatbot, and backup scoring)")
host = (os.getenv("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
try:
    with urllib.request.urlopen(host + "/api/tags", timeout=3) as r:
        names = [m.get("name", "") for m in json.loads(r.read().decode()).get("models", [])]
    ok(f"Ollama is running at {host}")
    for label, model in (("chat", os.getenv("OLLAMA_CHAT_MODEL") or "gemma3:4b"),
                         ("embedding", os.getenv("OLLAMA_EMBED_MODEL") or "nomic-embed-text")):
        if any(n == model or n.split(":")[0] == model or n == model + ":latest" for n in names):
            ok(f"{label} model {model}")
        else:
            fail(f"The {label} model {model} isn't downloaded", f"ollama pull {model}")
except Exception:
    warn(f"Ollama is not running at {host}: the chatbot won't work and there is no scoring backup",
         "open the Ollama app (or run: ollama serve)")

# ---------------------------------------------------------------- 5. Files and folders
print("\n5. Files and folders")
audio_dir = os.path.join(HERE, "uploads", "audio")
try:
    os.makedirs(audio_dir, exist_ok=True)
    test = os.path.join(audio_dir, ".write_test")
    open(test, "w").close()
    os.remove(test)
    ok("uploads/audio is writable")
except OSError as e:
    fail(f"Can't write to uploads/audio: {e}")
mp = os.path.join(HERE, "static", "mediapipe")
if os.path.isdir(mp) and os.listdir(mp):
    ok("MediaPipe files are saved locally (camera works offline)")
else:
    warn("MediaPipe isn't saved locally: the camera analysis needs internet", "python download_mediapipe.py")
if os.path.exists(os.path.join(HERE, ".gitignore")):
    with open(os.path.join(HERE, ".gitignore"), encoding="utf-8") as f:
        ignored = f.read()
    for item in (".env", "uploads"):
        if item in ignored:
            ok(f"{item} is excluded from GitHub")
        else:
            fail(f"{item} is NOT in .gitignore: secrets or recordings could be pushed", f"add a line: {item}")
else:
    fail(".gitignore is missing: .env and recordings could be pushed to GitHub")

# ---------------------------------------------------------------- 6. Gemini (optional live test)
if TEST_GEMINI:
    print("\n6. Gemini (live test, uses 1 request)")
    try:
        from google import genai
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        reply = client.models.generate_content(model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
                                               contents="Reply with the word OK.")
        ok(f"Gemini answered: {(reply.text or '').strip()[:20]}")
    except Exception as e:
        fail(f"Gemini test failed: {e}", "check GEMINI_API_KEY / GEMINI_MODEL, or wait if the limit was reached")

print("\n" + "=" * 60)
if problems:
    print(f"{len(problems)} problem(s) to fix and {len(warnings)} warning(s). Fix the [FAIL] lines above.")
    if not FIX and any("--fix" in p or "missing" in p for p in problems):
        print("Database problems can usually be fixed with:  python check_setup.py --fix")
else:
    print(f"Everything needed is ready ({len(warnings)} optional warning(s)). Start AIMIS with: python app.py")
sys.exit(1 if problems else 0)
