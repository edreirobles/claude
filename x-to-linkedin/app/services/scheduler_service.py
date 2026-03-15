"""
Servicio de programación de publicaciones.
Usa APScheduler con SQLite para persistir los trabajos.
"""
import logging
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

logger = logging.getLogger(__name__)

# Scheduler global (se inicializa en startup de la app)
scheduler = AsyncIOScheduler(
    jobstores={
        "default": SQLAlchemyJobStore(url="sqlite:///./scheduler_jobs.db")
    },
    job_defaults={"coalesce": True, "max_instances": 1},
    timezone="UTC",
)


def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler iniciado")
        _start_x_monitor_job()


def _start_x_monitor_job():
    """Registra el job periódico de monitoreo de likes en X si hay credenciales."""
    from ..config import get_settings
    settings = get_settings()
    if not settings.x_username or not settings.x_auth_token or not settings.x_ct0:
        logger.info(
            "X Monitor: credenciales de sesión no configuradas "
            "(X_USERNAME / X_AUTH_TOKEN / X_CT0), job no registrado"
        )
        return

    from .x_likes_monitor import check_and_process_likes
    from zoneinfo import ZoneInfo
    from datetime import timezone as dt_timezone

    job_kwargs: dict = dict(
        trigger="interval",
        minutes=settings.x_check_interval_minutes,
        id="x_likes_monitor",
        replace_existing=True,
    )

    if settings.x_monitor_start_date:
        try:
            mty_tz = ZoneInfo("America/Monterrey")
            start_mty = datetime.fromisoformat(settings.x_monitor_start_date).replace(tzinfo=mty_tz)
            start_utc = start_mty.astimezone(dt_timezone.utc)
            # Solo aplicar start_date si aún está en el futuro
            if start_utc > datetime.now(dt_timezone.utc):
                job_kwargs["start_date"] = start_utc
                logger.info(f"X Monitor: primer disparo programado para {start_utc} UTC")
        except Exception as e:
            logger.warning(f"X Monitor: no se pudo parsear X_MONITOR_START_DATE: {e}")

    scheduler.add_job(check_and_process_likes, **job_kwargs)
    logger.info(f"X Monitor: job registrado cada {settings.x_check_interval_minutes} min")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler detenido")


async def execute_pre_notify(post_id: int):
    """Envía notificación de Telegram 5 minutos antes de publicar un post."""
    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost
    from sqlalchemy import select
    from zoneinfo import ZoneInfo

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledPost).where(ScheduledPost.id == post_id)
        )
        post = result.scalar_one_or_none()
        if not post or post.status != "scheduled":
            return

        scheduled_at_str = ""
        if post.scheduled_at:
            mty_tz = ZoneInfo("America/Monterrey")
            sched_mty = post.scheduled_at.replace(tzinfo=timezone.utc).astimezone(mty_tz)
            scheduled_at_str = sched_mty.strftime("%H:%M")

        linkedin_text = post.linkedin_text or ""

    try:
        from .telegram_bot import notify_upcoming
        await notify_upcoming(post_id, linkedin_text, scheduled_at_str)
    except Exception as e:
        logger.warning(f"Pre-notificación Telegram para post {post_id} falló: {e}")


async def execute_scheduled_post(post_id: int):
    """Función que ejecuta un post programado. Se llama desde el scheduler."""
    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost, LinkedInToken
    from .linkedin_client import LinkedInClient
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        try:
            # Obtener el post
            post_result = await db.execute(
                select(ScheduledPost).where(ScheduledPost.id == post_id)
            )
            post = post_result.scalar_one_or_none()
            if not post or post.status != "scheduled":
                return

            # Obtener el token de LinkedIn
            token_result = await db.execute(select(LinkedInToken).limit(1))
            token = token_result.scalar_one_or_none()
            if not token:
                post.status = "failed"
                post.error_message = "No hay cuenta de LinkedIn conectada"
                await db.commit()
                return

            # Descargar media según tipo
            from .post_generator import generate_free_image, download_tweet_video, download_pdf

            media_type = getattr(post, "media_type", "auto")
            video_bytes = None
            document_bytes = None
            generated_image_bytes = None

            if media_type == "video":
                video_bytes = await download_tweet_video(post.tweet_url)
                if not video_bytes:
                    # Fallback: usar imagen del poster del tweet si yt-dlp falla
                    logger.warning(f"Post {post_id}: descarga de video fallida, usando imagen de poster")
                    media_type = "image"
            elif media_type == "document":
                pdf_url = getattr(post, "pdf_url", None)
                if pdf_url:
                    document_bytes = await download_pdf(pdf_url)
            elif media_type == "generate":
                # Usar imagen pre-generada con Nano Banana si existe
                pre_generated_path = getattr(post, "generated_image_path", None)
                if pre_generated_path:
                    import os
                    disk_path = pre_generated_path.lstrip("/")
                    if os.path.exists(disk_path):
                        with open(disk_path, "rb") as f:
                            generated_image_bytes = f.read()
                        logger.info(f"Post {post_id}: usando imagen pre-generada {disk_path}")
                    else:
                        logger.warning(f"Post {post_id}: imagen pre-generada no encontrada en {disk_path}, regenerando")
                if not generated_image_bytes:
                    generated_image_bytes = await generate_free_image(post.linkedin_text)

            # Publicar
            client = LinkedInClient(token.access_token, token.person_urn)
            result = await client.create_post(
                text=post.linkedin_text,
                image_urls=post.image_urls if media_type == "image" else None,
                use_first_image=media_type == "image" and post.use_first_image,
                video_bytes=video_bytes,
                document_bytes=document_bytes,
                document_title=getattr(post, "document_title", "Documento"),
                generated_image_bytes=generated_image_bytes,
            )

            post.status = "published"
            post.published_at = datetime.utcnow()
            post.linkedin_post_id = result.get("post_id", "")
            await db.commit()
            logger.info(f"Post {post_id} publicado correctamente")

            # Notificación de Telegram
            try:
                from .telegram_bot import notify_published
                await notify_published(post_id, post.linkedin_text or "")
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Error publicando post programado {post_id}: {e}")
            if post:
                post.status = "failed"
                post.error_message = str(e)
                await db.commit()

                # Notificación de Telegram
                try:
                    from .telegram_bot import notify_failed
                    await notify_failed(post_id, str(e))
                except Exception:
                    pass


def schedule_post(post_id: int, run_date: datetime) -> str:
    """Agrega un trabajo al scheduler. Retorna el job_id."""
    job_id = f"post_{post_id}"
    scheduler.add_job(
        execute_scheduled_post,
        trigger="date",
        run_date=run_date,
        args=[post_id],
        id=job_id,
        replace_existing=True,
    )
    logger.info(f"Post {post_id} programado para {run_date}")

    # Programar notificación 5 min antes si hay margen suficiente
    notify_at = run_date - timedelta(minutes=5)
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    if notify_at > now_utc:
        notify_job_id = f"pre_notify_{post_id}"
        scheduler.add_job(
            execute_pre_notify,
            trigger="date",
            run_date=notify_at,
            args=[post_id],
            id=notify_job_id,
            replace_existing=True,
        )
        logger.info(f"Pre-notificación post {post_id} programada para {notify_at}")

    return job_id


def cancel_scheduled_post(post_id: int) -> bool:
    """Cancela un trabajo programado y su pre-notificación. Retorna True si se canceló."""
    job_id = f"post_{post_id}"
    notify_job_id = f"pre_notify_{post_id}"
    cancelled = False
    try:
        scheduler.remove_job(job_id)
        cancelled = True
    except Exception:
        pass
    try:
        scheduler.remove_job(notify_job_id)
    except Exception:
        pass
    return cancelled
