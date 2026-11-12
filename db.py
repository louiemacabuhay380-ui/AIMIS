"""AIMIS database: SQLite (one file, aimis.db), so XAMPP / MySQL is no longer needed.

The rest of AIMIS was written for MySQL (mysql-connector). This module gives the same interface on top of
Python's built-in sqlite3, so the queries in app.py and the other files work unchanged:
  - get_db() returns a connection; conn.cursor(dictionary=True) gives rows as dicts
  - %s placeholders are turned into SQLite's ?
  - NOW(), CURDATE() and RAND() work inside queries (local time, like MySQL on the same PC)
  - DATETIME / TIMESTAMP columns come back as Python datetimes, DECIMAL columns as floats
  - errors keep MySQL's numbers where AIMIS checks them (1054 unknown column, 1146 unknown table, 1062 duplicate)

The first time AIMIS starts, aimis.db is created from database/aimis_sqlite.sql and filled with the approved
question bank and the admin account (database/seed_sqlite.sql).

Commands:
    python db.py init      create aimis.db if it is missing (AIMIS also does this when it starts)
    python db.py reset     back up aimis.db, then start again with an empty database (questions + admin only)
    python db.py info      where the database is and how many rows each table has
    python db.py make-admin you@email.com     make a registered account an admin (no SQLyog needed)
"""
import os
import random
import re
import shutil
import sqlite3
import sys
from datetime import date, datetime
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_FILE = os.path.join(HERE, "database", "aimis_sqlite.sql")
SEED_FILE = os.path.join(HERE, "database", "seed_sqlite.sql")


def db_path():
    """The database file: DB_PATH in .env, or aimis.db in the AIMIS folder."""
    path = os.getenv("DB_PATH") or "aimis.db"
    return path if os.path.isabs(path) else os.path.join(HERE, path)


# ---------------------------------------------------------------- errors (MySQL error numbers kept)

class Error(Exception):
    def __init__(self, msg, errno=None):
        super().__init__(msg)
        self.msg = msg
        self.errno = errno


class ProgrammingError(Error):
    pass


class IntegrityError(Error):
    pass


class OperationalError(Error):
    pass


def _convert_error(e):
    text = str(e)
    if isinstance(e, sqlite3.IntegrityError):
        return IntegrityError(text, 1062 if "UNIQUE" in text else 1452 if "FOREIGN KEY" in text else None)
    if "no such column" in text or "has no column named" in text:
        return ProgrammingError(text, 1054)
    if "no such table" in text:
        return ProgrammingError(text, 1146)
    if "duplicate column name" in text:
        return ProgrammingError(text, 1060)
    return OperationalError(text)


# ---------------------------------------------------------------- dates and numbers

def _to_datetime(value):
    text = value.decode() if isinstance(value, bytes) else str(value)
    text = text.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return text


def _to_date(value):
    d = _to_datetime(value)
    return d.date() if isinstance(d, datetime) else d


def _to_number(value):
    text = value.decode() if isinstance(value, bytes) else str(value)
    try:
        return float(text)
    except ValueError:
        return text


sqlite3.register_converter("DATETIME", _to_datetime)
sqlite3.register_converter("TIMESTAMP", _to_datetime)
sqlite3.register_converter("DATE", _to_date)
sqlite3.register_converter("DECIMAL", _to_number)
sqlite3.register_adapter(datetime, lambda d: d.strftime("%Y-%m-%d %H:%M:%S"))
sqlite3.register_adapter(date, lambda d: d.isoformat())
sqlite3.register_adapter(Decimal, float)
sqlite3.register_adapter(bool, int)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- connection and cursor

_PLACEHOLDER = re.compile(r"%(s|%)")


def _translate(sql):
    """MySQL-style %s placeholders -> SQLite ?  (and %% -> %)."""
    return _PLACEHOLDER.sub(lambda m: "?" if m.group(1) == "s" else "%", sql)


_DATETIME_TEXT = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def _fix(value):
    """Computed columns (MAX(started_at), COALESCE(...)) have no declared type, so SQLite returns their dates as
    text; turn "2026-11-12 18:30:00" back into a datetime like MySQL does."""
    if isinstance(value, str) and len(value) == 19 and _DATETIME_TEXT.match(value):
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return value


def _dict_row(cursor, row):
    return {col[0]: _fix(value) for col, value in zip(cursor.description, row)}


def _tuple_row(cursor, row):
    return tuple(_fix(value) for value in row)


class Cursor:
    def __init__(self, raw, dictionary):
        self._c = raw
        self._c.row_factory = _dict_row if dictionary else _tuple_row

    def execute(self, sql, params=None):
        try:
            if params is None:
                self._c.execute(_translate(sql) if "%" in sql else sql)
            else:
                self._c.execute(_translate(sql), tuple(params))
        except sqlite3.Error as e:
            err = _convert_error(e)
            if os.getenv("DB_DEBUG"):
                print("SQL failed:", " ".join(sql.split())[:300])
            raise err from e
        return self

    def executemany(self, sql, seq):
        try:
            self._c.executemany(_translate(sql), [tuple(p) for p in seq])
        except sqlite3.Error as e:
            raise _convert_error(e) from e
        return self

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return self._c.fetchall()

    def fetchmany(self, size=1):
        return self._c.fetchmany(size)

    def __iter__(self):
        return iter(self._c)

    @property
    def lastrowid(self):
        return self._c.lastrowid

    @property
    def rowcount(self):
        return self._c.rowcount

    @property
    def description(self):
        return self._c.description

    def close(self):
        self._c.close()


class Connection:
    def __init__(self, raw):
        self._conn = raw

    def cursor(self, dictionary=False, buffered=None, **_):
        return Cursor(self._conn.cursor(), dictionary)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def is_connected(self):
        return True

    def ping(self, *_, **__):
        return True

    def start_transaction(self, *_, **__):
        pass

    def __enter__(self):
        return self

    def __exit__(self, kind, *_):
        (self.rollback if kind else self.commit)()
        self.close()


def _raw_connect(path=None):
    conn = sqlite3.connect(path or db_path(), timeout=30, detect_types=sqlite3.PARSE_DECLTYPES,
                           check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.create_function("NOW", 0, _now)
    conn.create_function("CURDATE", 0, lambda: date.today().isoformat())
    conn.create_function("RAND", 0, random.random)
    return conn


_ready = False


def get_db(autocommit=False):
    """A new connection to aimis.db (created and filled the first time).
    Keep write transactions short: SQLite lets only one connection write at a time (others wait up to 30 s)."""
    global _ready
    if not _ready:
        init()
        _ready = True
    raw = _raw_connect()
    if autocommit:
        raw.isolation_level = None
    return Connection(raw)


# ---------------------------------------------------------------- creating the database

def _run_script(conn, path):
    with open(path, encoding="utf-8") as f:
        conn.executescript(f.read())


def init(path=None, quiet=True):
    """Create the tables if they're missing; add the questions and the admin account to an empty database."""
    path = path or db_path()
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    new = not os.path.exists(path)
    conn = _raw_connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")       # lets the interview and the chatbot use it at the same time
        _run_script(conn, SCHEMA_FILE)
        empty = conn.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0] == 0 \
            and conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        if empty and os.path.exists(SEED_FILE):
            _run_script(conn, SEED_FILE)
        conn.commit()
        if new and not quiet:
            print("Created", path)
    finally:
        conn.close()
    return new


def table_counts(path=None):
    conn = _raw_connect(path)
    try:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {n: conn.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0] for n in names}
    finally:
        conn.close()


def main(argv):
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HERE, ".env"))
    command = argv[1] if len(argv) > 1 else "info"
    path = db_path()
    if command == "init":
        print("Created" if init(path) else "Already exists (missing tables were added):", path)
    elif command == "reset":
        if os.path.exists(path):
            backup = path + datetime.now().strftime(".backup-%Y%m%d-%H%M%S")
            shutil.copy2(path, backup)
            for extra in ("", "-wal", "-shm"):
                if os.path.exists(path + extra):
                    os.remove(path + extra)
            print("Backed up the old database to", backup)
        init(path)
        print("New empty database (approved questions + admin account):", path)
    elif command == "info":
        init(path)
        print("Database file:", path)
        for name, n in table_counts(path).items():
            print(f"  {name:22} {n}")
    elif command == "make-admin" and len(argv) > 2:
        init(path)
        conn = _raw_connect(path)
        n = conn.execute("UPDATE users SET role = 'admin' WHERE email = ?", (argv[2].strip().lower(),)).rowcount
        conn.commit()
        conn.close()
        print(f"{argv[2]} is now an admin." if n else f"No account with the email {argv[2]}. Register it first.")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
