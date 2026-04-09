import os
import sqlite3
import pathlib

FREE_LIMIT = int(os.environ.get("FREE_GENERATIONS_LIMIT", 3))
USE_SUPABASE = bool(os.environ.get("SUPABASE_URL"))

DB_PATH = pathlib.Path(__file__).parent.parent / "cv_matcher_telegram.db"


def _supabase():
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


def _init_sqlite():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS telegram_profiles (
            telegram_user_id TEXT PRIMARY KEY,
            username TEXT,
            plan TEXT DEFAULT 'free',
            credits INTEGER DEFAULT 0,
            free_generations_used INTEGER DEFAULT 0,
            stripe_customer_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS telegram_generations (
            id TEXT PRIMARY KEY,
            telegram_user_id TEXT,
            status TEXT DEFAULT 'completed',
            job_text TEXT,
            job_title TEXT,
            company TEXT,
            output_language TEXT DEFAULT 'auto',
            pdf_path TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def get_or_create_profile(telegram_user_id: int, username: str = None) -> dict:
    uid = str(telegram_user_id)
    if USE_SUPABASE:
        sb = _supabase()
        res = sb.table("telegram_profiles").select("*").eq("telegram_user_id", uid).execute()
        if res.data:
            return res.data[0]
        sb.table("telegram_profiles").insert({
            "telegram_user_id": uid,
            "username": username,
            "plan": "free",
            "credits": 0,
            "free_generations_used": 0,
        }).execute()
        return sb.table("telegram_profiles").select("*").eq("telegram_user_id", uid).execute().data[0]
    else:
        _init_sqlite()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM telegram_profiles WHERE telegram_user_id=?", (uid,)).fetchone()
        if row:
            conn.close()
            return dict(row)
        conn.execute("INSERT INTO telegram_profiles (telegram_user_id, username) VALUES (?,?)", (uid, username))
        conn.commit()
        row = conn.execute("SELECT * FROM telegram_profiles WHERE telegram_user_id=?", (uid,)).fetchone()
        conn.close()
        return dict(row)


def can_generate(profile: dict) -> tuple[bool, str]:
    plan = profile.get("plan", "free")
    if plan == "monthly":
        return True, ""
    if plan == "credits":
        return (True, "") if profile.get("credits", 0) > 0 else (False, "no_credits")
    used = profile.get("free_generations_used", 0)
    return (True, "") if used < FREE_LIMIT else (False, "limit_reached")


def consume_credit(telegram_user_id: int, profile: dict):
    uid = str(telegram_user_id)
    plan = profile.get("plan", "free")
    if USE_SUPABASE:
        sb = _supabase()
        if plan == "credits":
            sb.table("telegram_profiles").update({"credits": profile["credits"] - 1}).eq("telegram_user_id", uid).execute()
        elif plan == "free":
            sb.table("telegram_profiles").update({"free_generations_used": profile["free_generations_used"] + 1}).eq("telegram_user_id", uid).execute()
    else:
        conn = sqlite3.connect(DB_PATH)
        if plan == "credits":
            conn.execute("UPDATE telegram_profiles SET credits=credits-1 WHERE telegram_user_id=?", (uid,))
        elif plan == "free":
            conn.execute("UPDATE telegram_profiles SET free_generations_used=free_generations_used+1 WHERE telegram_user_id=?", (uid,))
        conn.commit()
        conn.close()


def save_generation(telegram_user_id: int, gen_id: str, job_text: str,
                    job_title: str = None, company: str = None,
                    pdf_path: str = None, output_language: str = "auto"):
    uid = str(telegram_user_id)
    job_snippet = (job_text or "")[:500]
    if USE_SUPABASE:
        sb = _supabase()
        sb.table("telegram_generations").insert({
            "id": gen_id,
            "telegram_user_id": uid,
            "job_text": job_snippet,
            "job_title": job_title,
            "company": company,
            "pdf_path": pdf_path,
            "output_language": output_language,
        }).execute()
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO telegram_generations "
            "(id, telegram_user_id, job_text, job_title, company, pdf_path, output_language) "
            "VALUES (?,?,?,?,?,?,?)",
            (gen_id, uid, job_snippet, job_title, company, pdf_path, output_language),
        )
        conn.commit()
        conn.close()


def get_history(telegram_user_id: int, limit: int = 5) -> list:
    uid = str(telegram_user_id)
    if USE_SUPABASE:
        sb = _supabase()
        res = (sb.table("telegram_generations")
               .select("*")
               .eq("telegram_user_id", uid)
               .order("created_at", desc=True)
               .limit(limit)
               .execute())
        return res.data
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM telegram_generations WHERE telegram_user_id=? ORDER BY created_at DESC LIMIT ?",
            (uid, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
