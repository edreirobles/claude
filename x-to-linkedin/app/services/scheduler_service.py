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
        _start_editorial_radar_job()
        _start_x_monitor_job()
        _start_metrics_refresh_job()
        _start_linkedin_comment_monitor_job()
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(rehydrate_scheduled_posts())
            loop.create_task(maintain_editorial_radar_schedule())
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


def _start_linkedin_comment_monitor_job():
    """Registra el job periódico que vigila nuevos comentarios en posts publicados."""
    from .linkedin_comments import scan_linkedin_comments

    interval = max(int(settings.linkedin_comment_check_interval_minutes or 20), 5)
    scheduler.add_job(
        scan_linkedin_comments,
        trigger="interval",
        minutes=interval,
        id="linkedin_comment_monitor",
        replace_existing=True,
    )
    logger.info(
        "LinkedIn Comments: job registrado cada %s min",
        interval,
    )


def _start_editorial_radar_job():
    """Registra el mantenimiento periodico de slots del radar editorial."""
    if not settings.editorial_radar_enabled:
        logger.info("Radar editorial: desactivado")
        return

    scheduler.add_job(
        maintain_editorial_radar_schedule,
        trigger="interval",
        hours=6,
        id="editorial_radar_maintainer",
        replace_existing=True,
    )
    logger.info("Radar editorial: mantenimiento registrado cada 6 horas")


async def maintain_editorial_radar_schedule():
    """Crea y rehidrata slots del radar editorial."""
    if not settings.editorial_radar_enabled:
        return

    try:
        from .editorial_radar import ensure_radar_slots, list_active_radar_posts

        await ensure_radar_slots()
        posts = await list_active_radar_posts()
        for post in posts:
            if post.scheduled_at:
                schedule_radar_post(post.id, post.scheduled_at)
        logger.info("Radar editorial: %s slots activos rehidratados", len(posts))
    except Exception as exc:
        logger.warning("Radar editorial: mantenimiento fallo: %s", exc)


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
    from ..models import ScheduledPost
    from .linkedin_auth import LinkedInAuthError, get_linkedin_client_from_db
    from sqlalchemy import select, and_

    logger.info("[AutoMetrics] Iniciando refresh automático de métricas...")

    async with AsyncSessionLocal() as db:
        try:
            li_client = await get_linkedin_client_from_db(db)
        except LinkedInAuthError as exc:
            logger.info("[AutoMetrics] Saltando refresh de métricas: %s", exc)
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
    if not settings.x_auto_schedule_enabled:
        logger.info(
            "X Monitor: auto-calendarización desde likes desactivada "
            "(X_AUTO_SCHEDULE_ENABLED=false)."
        )
        return
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


def _remove_job_if_exists(job_id: str) -> bool:
    try:
        scheduler.remove_job(job_id)
        return True
    except Exception:
        return False


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
        elif media_type == "paper_image":
            media_detail = getattr(post, "document_title", "") or getattr(post, "pdf_url", "") or ""
        elif media_type == "video":
            media_detail = getattr(post, "tweet_url", "") or ""

    try:
        from .telegram_bot import notify_upcoming
        await notify_upcoming(post_id, linkedin_text, scheduled_at_str, media_type, media_detail)
    except Exception as e:
        logger.warning(f"Pre-notificación Telegram para post {post_id} falló: {e}")


async def execute_pre_publish_verification(post_id: int):
    """Verifica un post horas antes de publicarlo y lo cancela o actualiza si hace falta."""
    from .post_verifier import verify_scheduled_post
    from .calendar_maintenance import replace_cancelled_post

    try:
        outcome = await verify_scheduled_post(post_id)
        action = outcome.get("action")
        reason = outcome.get("reason", "")

        if action == "cancelled":
            cancel_scheduled_post(post_id, include_verify=False)
            replacement = await replace_cancelled_post(post_id)
            logger.warning(
                "Post %s cancelado por verificación previa: %s. Reemplazos creados: %s",
                post_id,
                reason,
                replacement.get("replaced", 0),
            )
        elif action == "updated":
            logger.info(
                "Post %s actualizado por verificación previa: %s",
                post_id,
                reason,
            )
        else:
            logger.info(
                "Post %s verificado antes de publicar: %s",
                post_id,
                reason or action,
            )
    except Exception as e:
        logger.warning(f"Verificación previa para post {post_id} falló: {e}")


async def execute_scheduled_post(post_id: int):
    """Función que ejecuta un post programado. Se llama desde el scheduler."""
    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost
    from .calendar_maintenance import replace_cancelled_post
    from .linkedin_auth import (
        LinkedInAuthError,
        get_linkedin_client_from_db,
        looks_like_linkedin_auth_failure,
    )
    from .post_verifier import verify_scheduled_post
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        post = None
        try:
            # Obtener el post
            post_result = await db.execute(
                select(ScheduledPost).where(ScheduledPost.id == post_id)
            )
            post = post_result.scalar_one_or_none()
            if not post:
                return
            if post.status == "approval_pending" and getattr(post, "source", "") == "radar":
                logger.info(
                    "Radar editorial: post %s sigue pendiente de aprobación; "
                    "la solicitud permanece abierta sin vencimiento",
                    post_id,
                )
                return
            if post.status != "scheduled":
                return

            verification = await verify_scheduled_post(post_id, db)
            if verification.get("action") == "cancelled":
                replacement = await replace_cancelled_post(post_id)
                logger.warning(
                    "Post %s cancelado justo antes de publicar: %s. Reemplazos creados: %s",
                    post_id,
                    verification.get("reason", ""),
                    replacement.get("replaced", 0),
                )
                return
            if verification.get("action") == "skipped":
                return

            await db.refresh(post)

            try:
                client = await get_linkedin_client_from_db(db)
            except LinkedInAuthError as exc:
                post.status = "failed"
                post.error_message = str(exc)
                await db.commit()
                try:
                    from .telegram_bot import notify_failed
                    await notify_failed(post_id, str(exc))
                except Exception:
                    pass
                return

            # Descargar media según tipo
            from .post_generator import (
                download_tweet_video,
                download_pdf,
                render_pdf_first_page_image,
            )

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
            elif media_type == "paper_image":
                pdf_url = getattr(post, "pdf_url", None)
                if pdf_url:
                    generated_image_bytes = await render_pdf_first_page_image(pdf_url)
                    if not generated_image_bytes:
                        logger.warning(
                            f"Post {post_id}: no se pudo renderizar paper como imagen, usando PDF"
                        )
                        media_type = "document"
                        document_bytes = await download_pdf(pdf_url)
            elif media_type == "generate":
                logger.info(
                    "Post %s usa media_type=generate heredado; se publicará sin imagen por la regla editorial vigente",
                    post_id,
                )
                media_type = "none"

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
            message = str(e)
            if looks_like_linkedin_auth_failure(message):
                message = (
                    "LinkedIn rechazó la autenticación de la cuenta. "
                    "Reconecta LinkedIn desde la app web para reanudar publicaciones."
                )
            logger.error(f"Error publicando post programado {post_id}: {message}")
            if post:
                post.status = "failed"
                post.error_message = message
                await db.commit()

                # Notificación de Telegram
                try:
                    from .telegram_bot import notify_failed
                    await notify_failed(post_id, message)
                except Exception:
                    pass


async def execute_radar_preparation(post_id: int):
    """Prepara un slot radar con una fuente fresca antes de pedir aprobacion."""
    try:
        from .editorial_radar import prepare_radar_post

        await prepare_radar_post(post_id)
    except Exception as exc:
        logger.warning("Radar editorial: preparacion del post %s fallo: %s", post_id, exc)
        try:
            from .telegram_bot import notify_failed

            await notify_failed(post_id, f"Radar editorial no pudo preparar el post: {exc}")
        except Exception:
            pass


async def execute_radar_approval_request(post_id: int):
    """Pide aprobacion por Telegram una hora antes de publicar."""
    from sqlalchemy import select
    from zoneinfo import ZoneInfo

    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost
    from .editorial_radar import RADAR_APPROVAL_STATUS, RADAR_SLOT_STATUS, prepare_radar_post

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        post = result.scalar_one_or_none()
        if not post:
            return
        status = post.status

    if status in {RADAR_SLOT_STATUS, "failed"}:
        try:
            await prepare_radar_post(post_id)
        except Exception as exc:
            logger.warning("Radar editorial: no se pudo preparar post %s para aprobacion: %s", post_id, exc)
            try:
                from .telegram_bot import notify_failed

                await notify_failed(post_id, f"Radar editorial no encontro una publicacion lista: {exc}")
            except Exception:
                pass
            return

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        post = result.scalar_one_or_none()
        if not post or post.status != RADAR_APPROVAL_STATUS:
            return

        scheduled_at_str = ""
        if post.scheduled_at:
            mty_tz = ZoneInfo("America/Mexico_City")
            sched_mty = post.scheduled_at.replace(tzinfo=timezone.utc).astimezone(mty_tz)
            scheduled_at_str = sched_mty.strftime("%H:%M")

        payload = {
            "post_id": post.id,
            "linkedin_text": post.linkedin_text or "",
            "scheduled_at_str": scheduled_at_str,
            "source_url": post.tweet_url or "",
            "source_label": post.tweet_author or "",
            "media_type": post.media_type or "none",
            "radar_reason": post.error_message or "",
        }

    try:
        from .telegram_bot import notify_radar_approval

        await notify_radar_approval(**payload)
    except Exception as exc:
        logger.warning("Radar editorial: notificacion de aprobacion fallo para post %s: %s", post_id, exc)


def schedule_radar_post(post_id: int, run_date: datetime) -> str:
    """Agenda jobs auxiliares de un slot radar sin aprobarlo todavia."""
    if not settings.editorial_radar_enabled:
        return ""

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    if run_date <= now_utc:
        return ""

    job_id = f"post_{post_id}"
    scheduler.add_job(
        execute_scheduled_post,
        trigger="date",
        run_date=run_date,
        args=[post_id],
        id=job_id,
        replace_existing=True,
    )

    prepare_at = run_date - timedelta(hours=max(int(settings.editorial_radar_lead_hours or 48), 1))
    if prepare_at <= now_utc:
        prepare_at = now_utc + timedelta(seconds=10)
    if prepare_at < run_date:
        scheduler.add_job(
            execute_radar_preparation,
            trigger="date",
            run_date=prepare_at,
            args=[post_id],
            id=f"radar_prepare_{post_id}",
            replace_existing=True,
        )

    approval_at = run_date - timedelta(
        minutes=max(int(settings.editorial_radar_approval_lead_minutes or 60), 5)
    )
    if approval_at <= now_utc:
        approval_at = now_utc + timedelta(seconds=20)
    if approval_at < run_date:
        scheduler.add_job(
            execute_radar_approval_request,
            trigger="date",
            run_date=approval_at,
            args=[post_id],
            id=f"radar_approval_{post_id}",
            replace_existing=True,
        )

    logger.info(
        "Radar editorial: post %s armado para preparar %s, aprobar %s y publicar %s",
        post_id,
        prepare_at,
        approval_at,
        run_date,
    )
    return job_id


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

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    if settings.pre_publish_verification_enabled and settings.pre_publish_verification_hours > 0:
        verify_at = run_date - timedelta(hours=settings.pre_publish_verification_hours)
        if verify_at > now_utc:
            verify_job_id = f"pre_verify_{post_id}"
            scheduler.add_job(
                execute_pre_publish_verification,
                trigger="date",
                run_date=verify_at,
                args=[post_id],
                id=verify_job_id,
                replace_existing=True,
            )
            logger.info(
                "Verificación previa post %s programada para %s (%s h antes)",
                post_id,
                verify_at,
                settings.pre_publish_verification_hours,
            )

    # Programar notificación 10 min antes si hay margen suficiente
    notify_at = run_date - timedelta(minutes=10)
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


def cancel_scheduled_post(post_id: int, include_verify: bool = True) -> bool:
    """Cancela un trabajo programado y sus jobs auxiliares. Retorna True si se canceló."""
    job_id = f"post_{post_id}"
    notify_job_id = f"pre_notify_{post_id}"
    verify_job_id = f"pre_verify_{post_id}"
    radar_prepare_job_id = f"radar_prepare_{post_id}"
    radar_approval_job_id = f"radar_approval_{post_id}"
    cancelled = _remove_job_if_exists(job_id)
    _remove_job_if_exists(notify_job_id)
    _remove_job_if_exists(radar_prepare_job_id)
    _remove_job_if_exists(radar_approval_job_id)
    if include_verify:
        _remove_job_if_exists(verify_job_id)
    return cancelled


async def recover_failed_posts_after_auth(db=None) -> int:
    """Reencola posts que fallaron solo porque LinkedIn pedía reautenticación."""
    from sqlalchemy import select

    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost
    from .linkedin_auth import looks_like_linkedin_auth_failure
    from .x_likes_monitor import get_next_auto_slot

    owns_session = db is None
    if owns_session:
        async with AsyncSessionLocal() as session:
            return await recover_failed_posts_after_auth(session)

    result = await db.execute(
        select(ScheduledPost)
        .where(ScheduledPost.status == "failed")
        .order_by(ScheduledPost.scheduled_at, ScheduledPost.id)
    )
    posts = [
        post
        for post in result.scalars().all()
        if looks_like_linkedin_auth_failure(post.error_message)
    ]
    if not posts:
        return 0

    recovered = 0
    for post in posts:
        run_at = await get_next_auto_slot(db)
        post.status = "scheduled"
        post.error_message = None
        post.scheduled_at = run_at
        await db.flush()
        schedule_post(post.id, run_at)
        recovered += 1

    await db.commit()
    logger.info("Scheduler: %s posts fallidos por auth fueron reencolados", recovered)
    return recovered
