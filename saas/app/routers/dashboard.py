"""
Rutas del dashboard del usuario:
  GET  /dashboard           - Resumen: suscripción, credenciales, logs recientes
  GET  /dashboard/logs      - Historial completo de posts
  PUT  /dashboard/credentials - Guardar X username y token de LinkedIn
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import AutomationLog, User
from app.schemas import AutomationLogResponse, CredentialsResponse, CredentialsUpdate, DashboardResponse, SubscriptionResponse, UserResponse

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
