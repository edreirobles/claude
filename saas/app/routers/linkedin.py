"""
LinkedIn OAuth 2.0 — conectar y desconectar cuenta de LinkedIn.

  GET  /linkedin/connect       → URL de autorización de LinkedIn (requiere auth)
  GET  /linkedin/callback      → recibe el código de LinkedIn, guarda token
  DELETE /linkedin/disconnect  → elimina credenciales de LinkedIn del usuario
  GET  /linkedin/status        → estado de la conexión de LinkedIn
"""

import secrets
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import LinkedInCredential, User

router = APIRouter(prefix="/linkedin", tags=["linkedin"])

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"

# El scope mínimo para leer perfil y publicar
LINKEDIN_SCOPE = "openid profile email w_member_social"


def _redirect_uri() -> str:
    return f"{settings.app_url}/linkedin/callback"


def _make_state(user_id: int) -> str:
    """JWT firmado de corta duración que transporta el user_id durante el OAuth."""
    payload = {
        "sub": str(user_id),
        "exp": datetime.utcnow() + timedelta(minutes=10),
        "nonce": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def _verify_state(state: str) -> int:
    """Verifica el estado y devuelve el user_id."""
    try:
        payload = jwt.decode(state, settings.secret_key, algorithms=[settings.algorithm])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=400, detail="Estado OAuth inválido o expirado.")


@router.get("/connect")
async def linkedin_connect(current_user: User = Depends(get_current_user)):
    """Devuelve la URL a la que redirigir al usuario para autorizar LinkedIn."""
    if not settings.linkedin_client_id:
        raise HTTPException(status_code=500, detail="LinkedIn OAuth no está configurado.")

    state = _make_state(current_user.id)
    params = (
        f"response_type=code"
        f"&client_id={settings.linkedin_client_id}"
        f"&redirect_uri={_redirect_uri()}"
        f"&state={state}"
        f"&scope={LINKEDIN_SCOPE.replace(' ', '%20')}"
    )
    return {"url": f"{LINKEDIN_AUTH_URL}?{params}"}


@router.get("/callback")
async def linkedin_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    LinkedIn redirige aquí con `code` y `state`.
    Intercambia el código por un token, guarda las credenciales y redirige al dashboard.
    """
    user_id = _verify_state(state)

    # 1. Intercambiar código por access token
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_resp = await client.post(
                LINKEDIN_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": _redirect_uri(),
                    "client_id": settings.linkedin_client_id,
                    "client_secret": settings.linkedin_client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()
    except Exception:
        return RedirectResponse(url="/app/?linkedin=error")

    access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in", 0)  # segundos

    if not access_token:
        return RedirectResponse(url="/app/?linkedin=error")

    # 2. Obtener perfil del usuario de LinkedIn
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            profile_resp = await client.get(
                LINKEDIN_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            profile_resp.raise_for_status()
            profile = profile_resp.json()
    except Exception:
        return RedirectResponse(url="/app/?linkedin=error")

    person_id = profile.get("sub", "")          # LinkedIn person ID (sin "urn:li:person:")
    person_name = profile.get("name", "")
    person_email = profile.get("email", "")

    if not person_id:
        return RedirectResponse(url="/app/?linkedin=error")

    # 3. Guardar o actualizar credenciales
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in) if expires_in else None

    result = await db.execute(
        select(LinkedInCredential).where(LinkedInCredential.user_id == user_id)
    )
    cred = result.scalar_one_or_none()

    if cred:
        cred.access_token = access_token
        cred.person_id = person_id
        cred.person_name = person_name
        cred.person_email = person_email
        cred.expires_at = expires_at
    else:
        cred = LinkedInCredential(
            user_id=user_id,
            access_token=access_token,
            person_id=person_id,
            person_name=person_name,
            person_email=person_email,
            expires_at=expires_at,
        )
        db.add(cred)

    await db.commit()
    return RedirectResponse(url="/app/?linkedin=connected")


@router.get("/status")
async def linkedin_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(LinkedInCredential).where(LinkedInCredential.user_id == current_user.id)
    )
    cred = result.scalar_one_or_none()

    if not cred:
        return {"connected": False}

    expired = cred.expires_at and cred.expires_at < datetime.utcnow()
    return {
        "connected": not expired,
        "person_name": cred.person_name,
        "person_email": cred.person_email,
        "expires_at": cred.expires_at,
    }


@router.delete("/disconnect")
async def linkedin_disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(LinkedInCredential).where(LinkedInCredential.user_id == current_user.id)
    )
    cred = result.scalar_one_or_none()
    if cred:
        await db.delete(cred)
        await db.commit()
    return {"disconnected": True}
