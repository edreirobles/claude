"""
Auth dependency for FastAPI.
When SUPABASE_URL is not set (local dev), auth is bypassed.
"""
import os
from fastapi import Header, HTTPException
from functools import lru_cache

AUTH_ENABLED = bool(os.environ.get("SUPABASE_URL"))

_DEV_USER = type("User", (), {"id": "local-dev", "email": "dev@local.com"})()


@lru_cache()
def _supabase():
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


async def get_current_user(authorization: str = Header(None)):
    if not AUTH_ENABLED:
        return _DEV_USER
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1]
    try:
        resp = _supabase().auth.get_user(token)
        if not resp.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return resp.user
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
