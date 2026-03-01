"""
Rutas para gestionar el monitoreo automático de "me gusta" en X.
"""
from datetime import datetime
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from ..database import get_db
from ..models import XLikedTweet, ScheduledPost
from ..config import get_settings

router = APIRouter(prefix="/api/x-monitor", tags=["x-monitor"])


@router.get("/status")
async def x_monitor_status(db: AsyncSession = Depends(get_db)):
    """
    Retorna el estado actual del monitoreo de likes en X:
    - Si las credenciales están configuradas
    - Último tweet procesado
    - Posts auto-calendarizados pendientes
    - Próximo chequeo programado
    """
    settings = get_settings()
    configured = bool(settings.x_bearer_token and settings.x_user_id)

    # Último tweet procesado
    last_result = await db.execute(
        select(XLikedTweet).order_by(desc(XLikedTweet.processed_at)).limit(1)
    )
    last = last_result.scalar_one_or_none()

    # Posts auto-programados futuros
    pending_result = await db.execute(
        select(func.count(ScheduledPost.id)).where(
            ScheduledPost.source == "x_auto",
            ScheduledPost.status == "scheduled",
        )
    )
    pending_auto = pending_result.scalar_one()

    # Total de tweets procesados
    total_result = await db.execute(select(func.count(XLikedTweet.id)))
    total_processed = total_result.scalar_one()

    # Últimos 5 likes procesados
    recent_result = await db.execute(
        select(XLikedTweet).order_by(desc(XLikedTweet.processed_at)).limit(5)
    )
    recent = recent_result.scalars().all()

    return {
        "configured": configured,
        "user_id": settings.x_user_id if configured else "",
        "check_interval_minutes": settings.x_check_interval_minutes,
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
