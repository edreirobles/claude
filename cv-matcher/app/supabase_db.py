"""
Database layer using Supabase (production) or SQLite (local dev).
"""
import os
from datetime import datetime, timezone
from functools import lru_cache

AUTH_ENABLED = bool(os.environ.get("SUPABASE_URL"))
FREE_LIMIT = int(os.environ.get("FREE_GENERATIONS_LIMIT", "3"))


@lru_cache()
def _sb():
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


# ── Profile ────────────────────────────────────────────────

def get_or_create_profile(user_id: str, email: str) -> dict:
    sb = _sb()
    r = sb.table("profiles").select("*").eq("id", user_id).execute()
    if r.data:
        return r.data[0]
    new = {"id": user_id, "email": email, "free_generations_used": 0, "plan": "free", "credits": 0}
    return sb.table("profiles").insert(new).execute().data[0]


def get_profile(user_id: str) -> dict | None:
    r = _sb().table("profiles").select("*").eq("id", user_id).execute()
    return r.data[0] if r.data else None


# ── Usage gating ───────────────────────────────────────────

def can_generate(profile: dict) -> tuple[bool, str]:
    """Returns (allowed, reason)"""
    plan = profile.get("plan", "free")

    if plan == "monthly":
        end = profile.get("subscription_end")
        if end:
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            if end_dt > datetime.now(timezone.utc):
                return (True, "subscription") if profile.get("credits", 0) > 0 else (False, "no_credits_subscriber")
        return False, "subscription_expired"

    if plan == "credits":
        return (True, "credits") if profile.get("credits", 0) > 0 else (False, "no_credits")

    # free plan
    used = profile.get("free_generations_used", 0)
    return (True, "free") if used < FREE_LIMIT else (False, "free_limit_reached")


def consume_credit(user_id: str, profile: dict):
    sb = _sb()
    plan = profile.get("plan", "free")
    if plan in ("credits", "monthly"):
        sb.table("profiles").update({"credits": profile["credits"] - 1}).eq("id", user_id).execute()
    elif plan == "free":
        sb.table("profiles").update(
            {"free_generations_used": profile.get("free_generations_used", 0) + 1}
        ).eq("id", user_id).execute()


# ── Generations ────────────────────────────────────────────

def create_generation(user_id: str, job_title: str, company: str, job_url: str, job_text: str, cv_filename: str) -> str:
    r = _sb().table("generations").insert({
        "user_id": user_id,
        "job_title": job_title,
        "company": company,
        "job_url": job_url,
        "job_text": job_text[:2000],
        "status": "processing",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }).execute()
    return r.data[0]["id"]


def update_generation(gen_id: str, pdf_ref: str, job_title: str = "", company: str = "", status: str = "completed"):
    _sb().table("generations").update({
        "pdf_storage_path": pdf_ref,
        "job_title": job_title,
        "company": company,
        "status": status,
    }).eq("id", gen_id).execute()


def get_generation(gen_id: str) -> dict | None:
    r = _sb().table("generations").select("*").eq("id", gen_id).execute()
    return r.data[0] if r.data else None


def get_user_generations(user_id: str) -> list:
    r = _sb().table("generations").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    return r.data


# ── Stripe helpers ─────────────────────────────────────────

def get_or_create_stripe_customer(user_id: str, email: str) -> str:
    import stripe
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

    profile = get_profile(user_id)
    if profile and profile.get("stripe_customer_id"):
        return profile["stripe_customer_id"]

    customer = stripe.Customer.create(email=email, metadata={"user_id": user_id})
    _sb().table("profiles").update({"stripe_customer_id": customer.id}).eq("id", user_id).execute()
    return customer.id


def activate_subscription(stripe_customer_id: str, subscription_id: str, period_end_ts: int):
    from datetime import timezone
    end_dt = datetime.fromtimestamp(period_end_ts, tz=timezone.utc)
    r = _sb().table("profiles").select("id, plan, credits").eq("stripe_customer_id", stripe_customer_id).execute()
    if not r.data:
        return
    row = r.data[0]
    credits_per_month = int(os.environ.get("CREDITS_PER_MONTH", "30"))
    # Renewal: add to existing. New subscription: start fresh at 30.
    current = row.get("credits") or 0
    new_credits = current + credits_per_month if row.get("plan") == "monthly" else credits_per_month
    _sb().table("profiles").update({
        "plan": "monthly",
        "subscription_id": subscription_id,
        "subscription_end": end_dt.isoformat(),
        "credits": new_credits,
    }).eq("id", row["id"]).execute()


def add_credits(stripe_customer_id: str, qty: int):
    r = _sb().table("profiles").select("id, plan, credits").eq("stripe_customer_id", stripe_customer_id).execute()
    if not r.data:
        return
    row = r.data[0]
    update = {"credits": (row.get("credits") or 0) + qty}
    # Don't downgrade monthly subscribers to credits plan
    if row.get("plan") != "monthly":
        update["plan"] = "credits"
    _sb().table("profiles").update(update).eq("id", row["id"]).execute()


def cancel_subscription(stripe_customer_id: str):
    r = _sb().table("profiles").select("id").eq("stripe_customer_id", stripe_customer_id).execute()
    if not r.data:
        return
    _sb().table("profiles").update({
        "plan": "free",
        "subscription_id": None,
        "subscription_end": None,
    }).eq("id", r.data[0]["id"]).execute()
