"""
Motor de automatización multi-usuario.

Cada N horas (configurado por el usuario en post_frequency_hours) este motor:
  1. Obtiene todos los usuarios con automation_enabled = True
  2. Para cada usuario, verifica si puede publicar (límite de plan)
  3. Scrapeaa los últimos tweets del perfil de X del usuario
  4. Filtra los que ya fueron procesados (via automation_logs)
  5. Genera un post de LinkedIn con Claude AI
  6. Publica en LinkedIn
  7. Guarda el resultado en automation_logs

El scheduler global llama a check_all_users() cada hora y cada usuario
se ejecuta solo si le toca según su post_frequency_hours.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models import AutomationLog, Subscription, SubscriptionPlan, SubscriptionStatus, User, UserCredentials

logger = logging.getLogger(__name__)


# ── Entry point del scheduler ──────────────────────────────────────────────────

async def check_all_users() -> None:
    """
    Revisión global: itera todos los usuarios activos con automatización
    habilitada y procesa los que les toca según su frecuencia configurada.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User)
            .join(UserCredentials, UserCredentials.user_id == User.id)
            .options(
                selectinload(User.credentials),
                selectinload(User.subscription),
            )
            .where(
                User.is_active == True,
                UserCredentials.automation_enabled == True,
            )
        )
        users = result.scalars().all()

    logger.info(f"[Automation] Revisando {len(users)} usuarios con automatización activa")

    for user in users:
        try:
            await _maybe_process_user(user)
        except Exception as e:
            logger.error(f"[Automation] Error procesando usuario {user.id}: {e}")


async def _maybe_process_user(user: User) -> None:
    """
    Verifica si le toca ejecutar al usuario según su frecuencia,
    y si es así, procesa sus tweets nuevos.
    """
    creds = user.credentials

    if not creds or not creds.is_configured:
        logger.debug(f"[Automation] Usuario {user.id}: credenciales incompletas, saltando")
        return

    # ¿Le toca según la frecuencia?
    async with AsyncSessionLocal() as db:
        last_log_result = await db.execute(
            select(AutomationLog)
            .where(AutomationLog.user_id == user.id)
            .order_by(AutomationLog.created_at.desc())
            .limit(1)
        )
        last_log = last_log_result.scalar_one_or_none()

    if last_log:
        next_run = last_log.created_at + timedelta(hours=creds.post_frequency_hours)
        if datetime.utcnow() < next_run:
            logger.debug(
                f"[Automation] Usuario {user.id}: próximo ciclo a las {next_run} UTC, saltando"
            )
            return

    # ¿Tiene cupo para publicar?
    sub = user.subscription
    if sub and not sub.can_post:
        logger.info(
            f"[Automation] Usuario {user.id}: límite de plan alcanzado "
            f"({sub.posts_used_this_month}/{sub.free_posts_limit}), saltando"
        )
        return

    logger.info(f"[Automation] Procesando usuario {user.id} (@{creds.x_username})")
    await _process_new_tweets(user)


async def _process_new_tweets(user: User) -> None:
    """
    Obtiene tweets recientes del perfil X del usuario,
    descarta los ya procesados y publica en LinkedIn.
    """
    from app.services.x_profile_scraper import get_recent_tweet_urls
    from app.services.x_scraper import scrape_tweet
    from app.services.post_generator import generate_linkedin_post
    from app.services.linkedin_client import LinkedInClient

    creds = user.credentials
    tweet_refs = await get_recent_tweet_urls(creds.x_username, max_tweets=5)

    if not tweet_refs:
        logger.warning(f"[Automation] Usuario {user.id}: no se encontraron tweets en @{creds.x_username}")
        return

    # Obtener IDs de tweets ya procesados para este usuario
    async with AsyncSessionLocal() as db:
        processed_result = await db.execute(
            select(AutomationLog.tweet_id).where(AutomationLog.user_id == user.id)
        )
        already_processed: set[str] = {row[0] for row in processed_result.all() if row[0]}

    new_tweets = [ref for ref in tweet_refs if ref.tweet_id not in already_processed]

    if not new_tweets:
        logger.info(f"[Automation] Usuario {user.id}: ningún tweet nuevo, nada que publicar")
        return

    # Procesar solo el tweet más reciente nuevo (1 publicación por ciclo)
    tweet_ref = new_tweets[0]
    logger.info(f"[Automation] Usuario {user.id}: procesando tweet {tweet_ref.tweet_id}")

    # Crear log en estado pending para evitar doble procesamiento
    async with AsyncSessionLocal() as db:
        log = AutomationLog(
            user_id=user.id,
            tweet_id=tweet_ref.tweet_id,
            tweet_url=tweet_ref.tweet_url,
            status="pending",
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)
        log_id = log.id

    try:
        # Scraping del tweet
        tweet_data = await scrape_tweet(tweet_ref.tweet_url)

        # Generar post de LinkedIn
        linkedin_text = await generate_linkedin_post(tweet=tweet_data, language="es")

        # Si Claude dice que no es publicable, marcar como rechazado
        if linkedin_text.startswith("[NO_PUBLICAR]"):
            reason = linkedin_text.split(":", 1)[-1].strip()
            await _update_log(log_id, status="failed", error_message=f"No publicable: {reason}",
                              tweet_text=tweet_data.text)
            logger.info(f"[Automation] Tweet {tweet_ref.tweet_id} rechazado: {reason}")
            return

        # Publicar en LinkedIn
        linkedin_client = LinkedInClient(
            access_token=creds.linkedin_access_token,
            person_urn=creds.linkedin_person_id,
        )

        result = await linkedin_client.create_post(
            text=linkedin_text,
            image_urls=tweet_data.images if tweet_data.images else None,
            use_first_image=bool(tweet_data.images),
        )

        linkedin_post_id = result.get("post_id", "")

        # Marcar como publicado
        await _update_log(
            log_id,
            status="published",
            tweet_text=tweet_data.text,
            linkedin_post_text=linkedin_text,
            linkedin_post_id=linkedin_post_id,
        )

        # Incrementar contador de posts del mes
        await _increment_post_count(user.id)

        logger.info(
            f"[Automation] Usuario {user.id}: tweet {tweet_ref.tweet_id} "
            f"publicado como LinkedIn post {linkedin_post_id}"
        )

    except Exception as e:
        logger.error(f"[Automation] Error publicando tweet {tweet_ref.tweet_id} para usuario {user.id}: {e}")
        await _update_log(log_id, status="failed", error_message=str(e))


# ── Helpers de DB ──────────────────────────────────────────────────────────────

async def _update_log(log_id: int, **fields) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AutomationLog).where(AutomationLog.id == log_id))
        log = result.scalar_one_or_none()
        if log:
            for key, value in fields.items():
                setattr(log, key, value)
            await db.commit()


async def _increment_post_count(user_id: int) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        sub = result.scalar_one_or_none()
        if sub:
            sub.posts_used_this_month += 1
            await db.commit()


# ── Reset mensual de contadores ────────────────────────────────────────────────

async def reset_monthly_counters() -> None:
    """
    Corre el 1° de cada mes a medianoche UTC.
    Resetea posts_used_this_month a 0 para todos los usuarios.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Subscription))
        subscriptions = result.scalars().all()
        for sub in subscriptions:
            sub.posts_used_this_month = 0
        await db.commit()
    logger.info(f"[Automation] Contadores mensuales reseteados para {len(subscriptions)} suscripciones")
