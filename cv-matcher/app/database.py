import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cv_matcher.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS generations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            job_title TEXT,
            company TEXT,
            job_url TEXT,
            job_text TEXT,
            original_cv_filename TEXT,
            output_pdf_path TEXT,
            status TEXT DEFAULT 'pending',
            cv_data TEXT,
            interview_tips TEXT
        )
    """)
    # Add columns if upgrading an existing DB
    for col, typedef in [("cv_data", "TEXT"), ("interview_tips", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE generations ADD COLUMN {col} {typedef}")
        except Exception:
            pass
    conn.commit()
    conn.close()


def create_generation(job_title, company, job_url, job_text, original_cv_filename):
    conn = get_db()
    cursor = conn.execute(
        """INSERT INTO generations (created_at, job_title, company, job_url, job_text, original_cv_filename, status)
           VALUES (?, ?, ?, ?, ?, ?, 'processing')""",
        (datetime.now().isoformat(), job_title, company, job_url, job_text, original_cv_filename),
    )
    gen_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return gen_id


def update_generation(gen_id, output_pdf_path="", job_title=None, company=None, status="completed", cv_data=None):
    import json as _json
    conn = get_db()
    cv_data_str = _json.dumps(cv_data) if cv_data is not None else None
    if job_title and company:
        conn.execute(
            "UPDATE generations SET output_pdf_path=?, job_title=?, company=?, status=?, cv_data=? WHERE id=?",
            (output_pdf_path, job_title, company, status, cv_data_str, gen_id),
        )
    else:
        conn.execute(
            "UPDATE generations SET output_pdf_path=?, status=?, cv_data=? WHERE id=?",
            (output_pdf_path, status, cv_data_str, gen_id),
        )
    conn.commit()
    conn.close()


def save_generation_tips(gen_id, tips: dict):
    import json as _json
    conn = get_db()
    conn.execute("UPDATE generations SET interview_tips=? WHERE id=?", (_json.dumps(tips), gen_id))
    conn.commit()
    conn.close()


def get_all_generations():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM generations ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_generation(gen_id):
    import json as _json
    conn = get_db()
    row = conn.execute("SELECT * FROM generations WHERE id=?", (gen_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for key in ("cv_data", "interview_tips"):
        if d.get(key):
            try:
                d[key] = _json.loads(d[key])
            except Exception:
                pass
    return d
