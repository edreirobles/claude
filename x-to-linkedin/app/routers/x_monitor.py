"""
Rutas para gestionar el monitoreo automático de "me gusta" en X.
"""
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from ..database import get_db
from ..models import XLikedTweet, ScheduledPost
from ..config import get_settings

router = APIRouter(prefix="/api/x-monitor", tags=["x-monitor"])

MONTERREY_TZ = ZoneInfo("America/Monterrey")


class XBackfillRequest(BaseModel):
    year: int | None = None


def _parse_start_date_utc(start_date_str: str):
    """Convierte la fecha de inicio (hora Monterrey) a UTC. Retorna None si vacía o inválida."""
    if not start_date_str:
        return None
    try:
        local = datetime.fromisoformat(start_date_str).replace(tzinfo=MONTERREY_TZ)
        return local.astimezone(dt_timezone.utc)
    except Exception:
        return None


@router.get("/status")
async def x_monitor_status(db: AsyncSession = Depends(get_db)):
    """Retorna el estado actual del monitoreo de likes en X."""
    settings = get_settings()
    configured = bool(
        settings.x_username and settings.x_auth_token and settings.x_ct0
    )

    # Calcular si el monitor ya está activo (pasó la start_date)
    start_utc = _parse_start_date_utc(settings.x_monitor_start_date)
    now_utc = datetime.now(dt_timezone.utc)
    waiting_for_start = start_utc is not None and now_utc < start_utc

    # Conteo de todos los tweets en tabla (incluyendo skipped)
    total_result = await db.execute(select(func.count(XLikedTweet.id)))
    total_in_db = total_result.scalar_one()

    # Conteo de skipped (semilla)
    skipped_result = await db.execute(
        select(func.count(XLikedTweet.id)).where(XLikedTweet.status == "skipped")
    )
    total_skipped = skipped_result.scalar_one()

    # Conteo de rechazados (no publicables)
    rejected_result = await db.execute(
        select(func.count(XLikedTweet.id)).where(XLikedTweet.status == "rejected")
    )
    total_rejected = rejected_result.scalar_one()

    # Conteo de procesados (solo los que generaron un post)
    total_processed = total_in_db - total_skipped - total_rejected

    # ¿Ya se hizo la semilla? (si hay registros en la tabla)
    seeded = total_in_db > 0

    # Posts auto-programados futuros
    pending_result = await db.execute(
        select(func.count(ScheduledPost.id)).where(
            ScheduledPost.source == "x_auto",
            ScheduledPost.status == "scheduled",
        )
    )
    pending_auto = pending_result.scalar_one()

    # Último tweet procesado (excluye skipped)
    last_result = await db.execute(
        select(XLikedTweet)
        .where(XLikedTweet.status != "skipped")
        .order_by(desc(XLikedTweet.processed_at))
        .limit(1)
    )
    last = last_result.scalar_one_or_none()

    # Últimos 5 likes no-skipped
    recent_result = await db.execute(
        select(XLikedTweet)
        .where(XLikedTweet.status != "skipped")
        .order_by(desc(XLikedTweet.processed_at))
        .limit(5)
    )
    recent = recent_result.scalars().all()

    return {
        "configured": configured,
        "username": settings.x_username if configured else "",
        "check_interval_minutes": settings.x_check_interval_minutes,
        "start_date": settings.x_monitor_start_date,
        "start_date_utc": start_utc.isoformat() if start_utc else None,
        "waiting_for_start": waiting_for_start,
        "seeded": seeded,
        "total_skipped": total_skipped,
        "total_rejected": total_rejected,
        "pending_auto_posts": pending_auto,
        "total_processed": total_processed,
        "last_tweet_url": last.tweet_url if last else None,
        "last_tweet_author": last.tweet_author if last else None,
        "last_processed_at": last.processed_at if last else None,
        "recent_likes": [
            {
                "tweet_id": t.tweet_id,
                "tweet_url": t.tweet_url,
                "tweet_author": t.tweet_author,
                "status": t.status,
                "processed_at": t.processed_at,
                "error_message": t.error_message,
            }
            for t in recent
        ],
    }


@router.post("/check-now")
async def x_monitor_check_now(background_tasks: BackgroundTasks):
    """Dispara un chequeo inmediato de likes en X (sin esperar al intervalo automático)."""
    from ..services.x_likes_monitor import check_and_process_likes
    background_tasks.add_task(check_and_process_likes)
    return {"message": "Chequeo de likes iniciado en segundo plano"}


@router.post("/backfill")
async def x_monitor_backfill(
    data: XBackfillRequest,
    background_tasks: BackgroundTasks,
):
    """
    Dispara un backfill profundo de likes para el año indicado.
    Si el tweet quedó sembrado como skipped en la primera ejecución, lo reintenta.
    """
    year = data.year or datetime.now(MONTERREY_TZ).year
    current_year = datetime.now(MONTERREY_TZ).year

    if year < 2006 or year > current_year:
        return {
            "message": (
                f"Año inválido: {year}. Usa un año entre 2006 y {current_year}."
            )
        }

    from ..services.x_likes_monitor import backfill_likes_from_year

    background_tasks.add_task(backfill_likes_from_year, year)
    return {
        "message": (
            f"Backfill iniciado para {year}. "
            "Escaneará likes no considerados y reintentará los skipped de ese año."
        )
    }
