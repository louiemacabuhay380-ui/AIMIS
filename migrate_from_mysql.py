"""One-time copy of your old XAMPP / MySQL data into the new SQLite database (aimis.db).

Only needed if you want to keep the accounts, interviews and scores that are in MySQL now.
Run it ONCE, while XAMPP's MySQL is still running, then you can uninstall XAMPP:

    pip install mysql-connector-python      (already installed if AIMIS ran with MySQL before)
    python migrate_from_mysql.py

It reads DB_HOST, DB_USER, DB_PASSWORD and DB_NAME from .env (your old MySQL settings), copies every table into
aimis.db (backing up an existing aimis.db first), and keeps all IDs, so recordings and reports still match.
Your recordings stay in the uploads folder; they aren't in the database.

Groupmates who start fresh don't need this: AIMIS creates aimis.db by itself.
"""
import os
import shutil
import sys
from datetime import datetime

from dotenv import load_dotenv

import db

# Parents before children, so the foreign keys are satisfied
ORDER = ["users", "question_bank", "interviews", "interview_questions", "responses", "speech_analysis",
         "nlp_analysis", "behavior_analysis", "evaluations", "feedback", "feedback_items", "answer_feedback",
         "skill_labels", "consents", "rag_chunks", "chat_messages", "human_ratings"]


def main():
    load_dotenv(os.path.join(db.HERE, ".env"))
    try:
        import mysql.connector
    except ImportError:
        sys.exit("Install the MySQL driver first: pip install mysql-connector-python")
    settings = dict(host=os.getenv("DB_HOST") or "localhost", user=os.getenv("DB_USER") or "root",
                    password=os.getenv("DB_PASSWORD") or "", database=os.getenv("DB_NAME") or "aimis")
    try:
        src = mysql.connector.connect(**settings, connection_timeout=5)
    except Exception as e:
        sys.exit(f"Couldn't connect to MySQL ({e}).\nStart MySQL in the XAMPP Control Panel first, and check "
                 "DB_HOST, DB_USER, DB_PASSWORD and DB_NAME in .env.")
    target = db.db_path()
    if os.path.exists(target):
        backup = target + datetime.now().strftime(".before-migration-%Y%m%d-%H%M%S")
        shutil.copy2(target, backup)
        for extra in ("", "-wal", "-shm"):
            if os.path.exists(target + extra):
                os.remove(target + extra)
        print("Backed up the existing aimis.db to", backup)

    # Empty tables only (no seed questions): everything comes from MySQL
    out = db._raw_connect(target)
    out.execute("PRAGMA journal_mode = WAL")
    db._run_script(out, db.SCHEMA_FILE)
    out.execute("PRAGMA foreign_keys = OFF")          # copied as-is, checked at the end

    cur = src.cursor()
    cur.execute("SHOW TABLES")
    mysql_tables = {r[0] for r in cur.fetchall()}
    total = 0
    for table in ORDER:
        if table not in mysql_tables:
            print(f"  {table:22} not in MySQL, skipped")
            continue
        sqlite_cols = [r[1] for r in out.execute(f"PRAGMA table_info({table})")]
        cur.execute(f"SELECT * FROM `{table}`")
        mysql_cols = [d[0] for d in cur.description]
        cols = [c for c in mysql_cols if c in sqlite_cols]
        index = [mysql_cols.index(c) for c in cols]
        rows = [[row[i] for i in index] for row in cur.fetchall()]
        if rows:
            out.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", rows)
        total += len(rows)
        skipped = [c for c in mysql_cols if c not in sqlite_cols]
        print(f"  {table:22} {len(rows)} rows" + (f" (ignored old columns: {', '.join(skipped)})" if skipped else ""))
    out.commit()

    problems = out.execute("PRAGMA foreign_key_check").fetchall()
    if problems:
        # Old MySQL backups can have leftover rows whose parent was deleted; remove them like MySQL would have
        removed = 0
        for table, rowid, _parent, _ in problems:
            out.execute(f"DELETE FROM {table} WHERE rowid = ?", (rowid,))
            removed += 1
        out.commit()
        print(f"Removed {removed} leftover rows that pointed to deleted records.")
    out.execute("PRAGMA foreign_keys = ON")
    out.close()
    src.close()
    print(f"\nDone: {total} rows copied into {target}")
    print("You can now start AIMIS with: python app.py   (XAMPP is no longer needed)")


if __name__ == "__main__":
    main()
