"""
Rutas del dashboard del usuario:
  GET  /dashboard           - Resumen: suscripción, credenciales, logs recientes
  GET  /dashboard/logs      - Historial completo de posts
  PUT  /dashboard/credentials - Guardar X username y token de LinkedIn
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import AutomationLog, User, UserCredentials
from app.schemas import (
    AutomationLogResponse,
    CredentialsResponse,
    CredentialsUpdate,
    DashboardResponse,
    SettingsResponse,
    SettingsUpdate,
    SubscriptionResponse,
    UserResponse,
)
from app.services.linkedin_client import LinkedInClient
from app.services.post_generator import DEFAULT_SYSTEM_PROMPT

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Cargar relaciones
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.subscription),
            selectinload(User.credentials),
        )
        .where(User.id == current_user.id)
    )
    user = result.scalar_one()

    # Últimos 10 logs
    logs_result = await db.execute(
        select(AutomationLog)
        .where(AutomationLog.user_id == current_user.id)
        .order_by(AutomationLog.created_at.desc())
        .limit(10)
    )
    recent_logs = logs_result.scalars().all()

    # Total publicados
    count_result = await db.execute(
        select(func.count()).where(
            AutomationLog.user_id == current_user.id,
            AutomationLog.status == "published",
        )
    )
    total_published = count_result.scalar_one()

    return DashboardResponse(
        user=UserResponse.model_validate(user),
        subscription=SubscriptionResponse.model_validate(user.subscription) if user.subscription else None,
        credentials=CredentialsResponse.model_validate(user.credentials) if user.credentials else None,
        recent_logs=[AutomationLogResponse.model_validate(log) for log in recent_logs],
        total_posts_published=total_published,
    )


@router.get("/logs", response_model=list[AutomationLogResponse])
async def get_logs(
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AutomationLog)
        .where(AutomationLog.user_id == current_user.id)
        .order_by(AutomationLog.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Devuelve el prompt personalizado del usuario y el prompt default del sistema."""
    result = await db.execute(
        select(User).options(selectinload(User.credentials)).where(User.id == current_user.id)
    )
    user = result.scalar_one()
    return SettingsResponse(
        custom_prompt=user.credentials.custom_prompt if user.credentials else None,
        default_prompt=DEFAULT_SYSTEM_PROMPT,
    )


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(
    data: SettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Guarda el prompt personalizado del usuario.
    Enviar custom_prompt=null (o no incluirlo) restablece al prompt default del sistema.
    """
    result = await db.execute(
        select(User).options(selectinload(User.credentials)).where(User.id == current_user.id)
    )
    user = result.scalar_one()
    if not user.credentials:
        raise HTTPException(status_code=400, detail="Configura tus credenciales antes de personalizar el prompt")

    user.credentials.custom_prompt = data.custom_prompt  # None = usar default
    await db.commit()
    return SettingsResponse(
        custom_prompt=user.credentials.custom_prompt,
        default_prompt=DEFAULT_SYSTEM_PROMPT,
    )


@router.post("/logs/{log_id}/refresh-metrics", response_model=AutomationLogResponse)
async def refresh_post_metrics(
    log_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Actualiza las métricas (likes, comentarios) de un post publicado consultando la API de LinkedIn.
    Las impresiones solo están disponibles para páginas de empresa, no para perfiles personales.
    """
    log_result = await db.execute(
        select(AutomationLog).where(
            AutomationLog.id == log_id,
            AutomationLog.user_id == current_user.id,
        )
    )
    log = log_result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")
    if log.status != "published" or not log.linkedin_post_id:
        raise HTTPException(status_code=400, detail="Esta publicación aún no fue publicada en LinkedIn")

    # Obtener credenciales del usuario
    creds_result = await db.execute(
        select(UserCredentials).where(UserCredentials.user_id == current_user.id)
    )
    creds = creds_result.scalar_one_or_none()
    if not creds or not creds.linkedin_access_token or not creds.linkedin_person_id:
        raise HTTPException(status_code=400, detail="No hay credenciales de LinkedIn configuradas")

    li = LinkedInClient(
        access_token=creds.linkedin_access_token,
        person_urn=creds.linkedin_person_id,
    )
    metrics = await li.get_post_metrics(log.linkedin_post_id)

    log.li_likes = metrics["likes"]
    log.li_comments = metrics["comments"]
    log.li_impressions = metrics["impressions"]
    log.metrics_updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(log)
    return log


@router.put("/credentials", response_model=CredentialsResponse)
async def update_credentials(
    data: CredentialsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User)
        .options(selectinload(User.credentials))
        .where(User.id == current_user.id)
    )
    user = result.scalar_one()
    creds = user.credentials

    if data.x_username is not None:
        creds.x_username = data.x_username.lstrip("@")
    if data.linkedin_access_token is not None:
        creds.linkedin_access_token = data.linkedin_access_token
    if data.linkedin_person_id is not None:
        creds.linkedin_person_id = data.linkedin_person_id
    if data.automation_enabled is not None:
        creds.automation_enabled = data.automation_enabled
    if data.post_frequency_hours is not None:
        creds.post_frequency_hours = data.post_frequency_hours

    await db.commit()
    await db.refresh(creds)
    return creds
