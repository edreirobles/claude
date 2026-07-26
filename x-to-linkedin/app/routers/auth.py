"""
Rutas de autenticación OAuth 2.0 con LinkedIn.
"""
import secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..database import get_db
from ..models import LinkedInToken
from ..schemas import AuthStatusResponse
from ..config import get_settings
from ..services.linkedin_client import get_oauth_url, exchange_code_for_token, LinkedInClient
from ..services.linkedin_auth import (
    LinkedInAuthError,
    ensure_valid_linkedin_token,
    load_linkedin_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

# Estado temporal para prevenir CSRF (en producción usar Redis)
_oauth_states: dict[str, float] = {}


@router.get("/linkedin")
async def linkedin_oauth_start():
    """Inicia el flujo OAuth con LinkedIn. Redirige al usuario a LinkedIn."""
    if not settings.linkedin_client_id:
        raise HTTPException(
            status_code=500,
            detail="LINKEDIN_CLIENT_ID no está configurado en las variables de entorno.",
        )
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = datetime.utcnow().timestamp()

    url = get_oauth_url(
        client_id=settings.linkedin_client_id,
        redirect_uri=settings.linkedin_redirect_uri,
        state=state,
    )
    return RedirectResponse(url)


@router.get("/linkedin/callback")
async def linkedin_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Callback de LinkedIn. Intercambia el código por token y guarda en BD."""
    if error:
        return RedirectResponse(f"/?error={error}")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Parámetros faltantes")

    # Validar state (anti-CSRF)
    if state not in _oauth_states:
        raise HTTPException(status_code=400, detail="Estado OAuth inválido")
    del _oauth_states[state]

    # Intercambiar código por token
    try:
        token_data = await exchange_code_for_token(
            code=code,
            client_id=settings.linkedin_client_id,
            client_secret=settings.linkedin_client_secret,
            redirect_uri=settings.linkedin_redirect_uri,
        )
    except Exception as e:
        return RedirectResponse(f"/?error=token_exchange_failed&detail={str(e)}")

    access_token = token_data.get("access_token", "")
    expires_in = token_data.get("expires_in", 5184000)  # 60 días por defecto
    refresh_token = (token_data.get("refresh_token") or "").strip()
    refresh_token_expires_in = token_data.get("refresh_token_expires_in")

    # Obtener perfil del usuario
    try:
        # Necesitamos el sub (person_urn) del token de OpenID
        id_token = token_data.get("id_token", "")
        person_name = ""
        person_picture = ""
        person_urn = ""

        # Usar userinfo endpoint
        li_client_temp = LinkedInClient(access_token, "")
        profile = await li_client_temp.get_profile()
        person_urn = profile.get("sub", "")
        person_name = profile.get("name", "")
        person_picture = profile.get("picture", "")

    except Exception as e:
        return RedirectResponse(f"/?error=profile_failed&detail={str(e)}")

    # Guardar/actualizar token en BD
    result = await db.execute(select(LinkedInToken).limit(1))
    existing = result.scalar_one_or_none()

    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
    refresh_token_expires_at = None
    if refresh_token_expires_in:
        refresh_token_expires_at = datetime.utcnow() + timedelta(
            seconds=int(refresh_token_expires_in)
        )

    if existing:
        existing.access_token = access_token
        if refresh_token:
            existing.refresh_token = refresh_token
        existing.person_urn = person_urn
        existing.person_name = person_name
        existing.person_picture = person_picture
        existing.expires_at = expires_at
        if refresh_token_expires_at:
            existing.refresh_token_expires_at = refresh_token_expires_at
    else:
        db.add(
            LinkedInToken(
                access_token=access_token,
                refresh_token=refresh_token or None,
                person_urn=person_urn,
                person_name=person_name,
                person_picture=person_picture,
                expires_at=expires_at,
                refresh_token_expires_at=refresh_token_expires_at,
            )
        )
    await db.commit()

    requeued = 0
    try:
        from ..services.scheduler_service import recover_failed_posts_after_auth

        requeued = await recover_failed_posts_after_auth(db)
    except Exception:
        requeued = 0

    return RedirectResponse(f"/?connected=true&requeued={requeued}")


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(db: AsyncSession = Depends(get_db)):
    """Devuelve si LinkedIn está conectado y los datos del usuario."""
    token = await load_linkedin_token(db)

    if not token:
        return AuthStatusResponse(connected=False)

    try:
        valid_token = await ensure_valid_linkedin_token(db)
    except LinkedInAuthError as exc:
        return AuthStatusResponse(
            connected=False,
            person_name=token.person_name,
            person_picture=token.person_picture,
            person_urn=token.person_urn,
            expires_at=token.expires_at,
            needs_reconnect=exc.needs_reconnect,
            can_refresh=bool(token.refresh_token),
            message=str(exc),
        )

    return AuthStatusResponse(
        connected=True,
        person_name=valid_token.person_name,
        person_picture=valid_token.person_picture,
        person_urn=valid_token.person_urn,
        expires_at=valid_token.expires_at,
        can_refresh=bool(valid_token.refresh_token),
    )


@router.delete("/linkedin")
async def disconnect_linkedin(db: AsyncSession = Depends(get_db)):
    """Desconecta la cuenta de LinkedIn eliminando el token guardado."""
    result = await db.execute(select(LinkedInToken).limit(1))
    token = result.scalar_one_or_none()
    if token:
        await db.delete(token)
        await db.commit()
    return {"message": "Cuenta de LinkedIn desconectada"}
