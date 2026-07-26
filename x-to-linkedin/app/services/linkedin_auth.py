from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import LinkedInToken
from .linkedin_client import LinkedInClient, exchange_refresh_token_for_token

settings = get_settings()

TOKEN_REFRESH_SKEW_SECONDS = 300
AUTH_FAILURE_MARKERS = (
    "expired_access_token",
    "401 unauthorized",
    "token de linkedin expiró",
    "token de linkedin expiro",
    "reconecta tu cuenta de linkedin",
    "linkedin requiere reconexión",
    "linkedin requiere reconexion",
)


class LinkedInAuthError(RuntimeError):
    def __init__(self, message: str, *, needs_reconnect: bool = False):
        super().__init__(message)
        self.needs_reconnect = needs_reconnect


def _utcnow() -> datetime:
    return datetime.utcnow()


def looks_like_linkedin_auth_failure(error_message: str | None) -> bool:
    lowered = (error_message or "").strip().lower()
    return any(marker in lowered for marker in AUTH_FAILURE_MARKERS)


async def load_linkedin_token(db: AsyncSession) -> LinkedInToken | None:
    result = await db.execute(select(LinkedInToken).limit(1))
    return result.scalar_one_or_none()


async def refresh_linkedin_access_token(
    db: AsyncSession,
    token: LinkedInToken,
) -> LinkedInToken:
    if not token.refresh_token:
        raise LinkedInAuthError(
            "El token de LinkedIn expiró y esta conexión no tiene refresh token. "
            "Reconecta tu cuenta en la app web.",
            needs_reconnect=True,
        )

    if (
        token.refresh_token_expires_at
        and token.refresh_token_expires_at <= _utcnow()
    ):
        raise LinkedInAuthError(
            "El refresh token de LinkedIn ya expiró. Reconecta tu cuenta en la app web.",
            needs_reconnect=True,
        )

    if not settings.linkedin_client_id or not settings.linkedin_client_secret:
        raise LinkedInAuthError(
            "Falta LINKEDIN_CLIENT_ID o LINKEDIN_CLIENT_SECRET para renovar el token. "
            "Reconecta tu cuenta en la app web.",
            needs_reconnect=True,
        )

    try:
        token_data = await exchange_refresh_token_for_token(
            refresh_token=token.refresh_token,
            client_id=settings.linkedin_client_id,
            client_secret=settings.linkedin_client_secret,
            redirect_uri=settings.linkedin_redirect_uri,
        )
    except Exception as exc:
        raise LinkedInAuthError(
            "No se pudo renovar el token de LinkedIn automáticamente. "
            "Reconecta tu cuenta en la app web.",
            needs_reconnect=True,
        ) from exc

    access_token = (token_data.get("access_token") or "").strip()
    if not access_token:
        raise LinkedInAuthError(
            "LinkedIn no devolvió un access token nuevo. Reconecta tu cuenta en la app web.",
            needs_reconnect=True,
        )

    expires_in = int(token_data.get("expires_in") or 0)
    refresh_token = (token_data.get("refresh_token") or "").strip()
    refresh_expires_in = token_data.get("refresh_token_expires_in")

    token.access_token = access_token
    if expires_in > 0:
        token.expires_at = _utcnow() + timedelta(seconds=expires_in)
    else:
        token.expires_at = None

    if refresh_token:
        token.refresh_token = refresh_token
    if refresh_expires_in:
        token.refresh_token_expires_at = _utcnow() + timedelta(
            seconds=int(refresh_expires_in)
        )

    await db.commit()
    await db.refresh(token)
    return token


async def ensure_valid_linkedin_token(
    db: AsyncSession,
    *,
    min_seconds_remaining: int = TOKEN_REFRESH_SKEW_SECONDS,
    allow_refresh: bool = True,
) -> LinkedInToken:
    token = await load_linkedin_token(db)
    if not token:
        raise LinkedInAuthError(
            "LinkedIn no está conectado. Conecta tu cuenta desde la app web.",
            needs_reconnect=True,
        )

    if token.expires_at:
        refresh_deadline = _utcnow() + timedelta(seconds=max(min_seconds_remaining, 0))
        if token.expires_at <= refresh_deadline:
            if allow_refresh and token.refresh_token:
                return await refresh_linkedin_access_token(db, token)
            raise LinkedInAuthError(
                "El token de LinkedIn expiró. Reconecta tu cuenta desde la app web.",
                needs_reconnect=True,
            )

    return token


async def get_linkedin_client_from_db(
    db: AsyncSession,
    *,
    min_seconds_remaining: int = TOKEN_REFRESH_SKEW_SECONDS,
    allow_refresh: bool = True,
) -> LinkedInClient:
    token = await ensure_valid_linkedin_token(
        db,
        min_seconds_remaining=min_seconds_remaining,
        allow_refresh=allow_refresh,
    )
    return LinkedInClient(token.access_token, token.person_urn)
