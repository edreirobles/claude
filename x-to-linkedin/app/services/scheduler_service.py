"""
Servicio de programación de publicaciones.
Usa APScheduler con SQLite para persistir los trabajos.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Scheduler global (se inicializa en startup de la app)
scheduler = AsyncIOScheduler(
    jobstores={
        "default": SQLAlchemyJobStore(url=settings.scheduler_database_url)
    },
    job_defaults={"coalesce": True, "max_instances": 1},
    timezone="UTC",
)


def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler iniciado")
        _start_x_monitor_job()
        _start_metrics_refresh_job()
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(rehydrate_scheduled_posts())
        except RuntimeError:
            logger.warning(
                "No hay event loop activo para rehidratar posts programados al iniciar"
            )


def _start_metrics_refresh_job():
    """Registra el job periódico de auto-refresh de métricas de posts publicados."""
    scheduler.add_job(
        auto_refresh_metrics,
        trigger="interval",
        hours=6,
        id="metrics_auto_refresh",
        replace_existing=True,
    )
    logger.info("Métricas: job de auto-refresh registrado (cada 6 horas)")


async def rehydrate_scheduled_posts():
    """
    Reconstruye los jobs de APScheduler a partir de la BD principal.

    Si encuentra posts aún marcados como "scheduled" pero con fecha vencida,
    los mueve al próximo slot disponible en vez de publicarlos inmediatamente.
    """
    from sqlalchemy import select

    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost
    from .x_likes_monitor import get_next_auto_slot

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledPost)
            .where(ScheduledPost.status == "scheduled")
            .order_by(ScheduledPost.scheduled_at)
        )
        posts = result.scalars().all()

        if not posts:
            logger.info("Scheduler: no hay posts programados para rehidratar")
            return

        now_utc = datetime.utcnow()
        restored = 0
        requeued = 0
        skipped = 0

        for post in posts:
            if not post.scheduled_at:
                skipped += 1
                logger.warning(
                    f"Scheduler: post {post.id} está en estado 'scheduled' sin scheduled_at"
                )
                continue

            if post.scheduled_at <= now_utc:
                old_run_at = post.scheduled_at
                post.scheduled_at = await get_next_auto_slot(db)
                await db.flush()
                requeued += 1
                logger.warning(
                    "Scheduler: post %s vencido desde %s; reprogramado para %s",
                    post.id,
                    old_run_at,
                    post.scheduled_at,
                )
            else:
                restored += 1

            schedule_post(post.id, post.scheduled_at)

        if requeued or skipped:
            await db.commit()

        logger.info(
            "Scheduler: rehidratación completada (%s restaurados, %s reprogramados, %s omitidos)",
            restored,
            requeued,
            skipped,
        )


async def auto_refresh_metrics():
    """
    Actualiza automáticamente las métricas de posts publicados en los últimos 60 días
    que no se han actualizado en las últimas 6 horas.
    """
    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost, LinkedInToken
    from ..services.linkedin_client import LinkedInClient
    from sqlalchemy import select, and_

    logger.info("[AutoMetrics] Iniciando refresh automático de métricas...")

    async with AsyncSessionLocal() as db:
        # Obtener token de LinkedIn
        token_result = await db.execute(select(LinkedInToken).limit(1))
        token = token_result.scalar_one_or_none()
        if not token:
            logger.debug("[AutoMetrics] No hay token de LinkedIn, saltando")
            return

        # Posts publicados en los últimos 60 días con linkedin_post_id
        cutoff = datetime.utcnow() - timedelta(days=60)
        # Solo refrescar los que no se han actualizado en las últimas 6 horas
        refresh_cutoff = datetime.utcnow() - timedelta(hours=6)

        result = await db.execute(
            select(ScheduledPost).where(
                and_(
                    ScheduledPost.status == "published",
                    ScheduledPost.linkedin_post_id.isnot(None),
                    ScheduledPost.linkedin_post_id != "",
                    ScheduledPost.published_at >= cutoff,
                )
            )
        )
        posts = result.scalars().all()

        # Filtrar los que necesitan actualización
        to_refresh = [
            p for p in posts
            if p.metrics_updated_at is None or p.metrics_updated_at < refresh_cutoff
        ]

        if not to_refresh:
            logger.info("[AutoMetrics] Todos los posts tienen métricas recientes, nada que actualizar")
            return

        logger.info(f"[AutoMetrics] Actualizando métricas de {len(to_refresh)} posts...")
        li_client = LinkedInClient(token.access_token, token.person_urn)

        refreshed = 0
        for post in to_refresh:
            try:
                metrics = await li_client.get_post_metrics(post.linkedin_post_id)
                if metrics.get("likes") is not None:
                    post.li_likes = metrics["likes"]
                if metrics.get("comments") is not None:
                    post.li_comments = metrics["comments"]
                if metrics.get("impressions") is not None:
                    post.li_impressions = metrics["impressions"]
                if metrics.get("clicks") is not None:
                    post.li_clicks = metrics["clicks"]
                if metrics.get("shares") is not None:
                    post.li_shares = metrics["shares"]
                post.metrics_updated_at = datetime.utcnow()
                refreshed += 1
            except Exception as e:
                logger.warning(f"[AutoMetrics] Falló post {post.id}: {e}")

        await db.commit()
        logger.info(f"[AutoMetrics] Completado: {refreshed}/{len(to_refresh)} posts actualizados")


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
    """Envía notificación de Telegram 10 minutos antes de publicar un post."""
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
        media_type = getattr(post, "media_type", "") or ""

        # Construir detalle de multimedia para la notificación
        media_detail = ""
        if media_type == "image":
            urls = getattr(post, "image_urls", None) or []
            if urls:
                media_detail = urls[0]
        elif media_type == "document":
            media_detail = getattr(post, "document_title", "") or ""
        elif media_type == "video":
            media_detail = getattr(post, "tweet_url", "") or ""

    try:
        from .telegram_bot import notify_upcoming
        await notify_upcoming(post_id, linkedin_text, scheduled_at_str, media_type, media_detail)
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
            from .post_generator import generate_free_image, generate_nano_banana_image, download_tweet_video, download_pdf

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
                    # Usar nano banana (Gemini + Imagen 3 + Pollinations como fallback)
                    generated_image_bytes = await generate_nano_banana_image(post.linkedin_text)

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

    # Programar notificación 10 min antes si hay margen suficiente
    notify_at = run_date - timedelta(minutes=10)
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
        logger.info(f"Pre-notificación post {post_id} programada para {notify_at} (10 min antes)")

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
