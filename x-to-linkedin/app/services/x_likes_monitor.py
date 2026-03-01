"""
Monitor de tweets con "me gusta" en X.

Cada N minutos consulta la API de X para obtener los tweets que el usuario
marcó como "me gusta". Por cada tweet nuevo, genera un post de LinkedIn y
lo calendariza automáticamente a las 5 AM hora de Monterrey.

Regla de calendarización automática:
- Máximo 1 publicación automática (x_auto) por día.
- Si ya hay una programada para hoy, se mueve al siguiente día disponible.
- Las publicaciones manuales desde la app NO cuentan para este límite.
"""
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, func

from ..database import AsyncSessionLocal
from ..models import XLikedTweet, ScheduledPost
from ..config import get_settings

logger = logging.getLogger(__name__)

MONTERREY_TZ = ZoneInfo("America/Monterrey")


async def fetch_liked_tweets(bearer_token: str, user_id: str) -> list[dict]:
    """Consulta la API de X v2 para obtener los tweets recientes con 'me gusta'."""
    url = f"https://api.twitter.com/2/users/{user_id}/liked_tweets"
    params = {
        "max_results": 10,
        "expansions": "author_id",
        "user.fields": "username,name",
        "tweet.fields": "created_at,author_id",
    }
    headers = {"Authorization": f"Bearer {bearer_token}"}

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params, headers=headers)
        r.raise_for_status()
        data = r.json()

    # Construir mapa de usuarios para obtener usernames
    user_map: dict[str, dict] = {}
    for user in data.get("includes", {}).get("users", []):
        user_map[user["id"]] = user

    tweets = []
    for tweet in data.get("data", []):
        author = user_map.get(tweet.get("author_id", ""), {})
        tweets.append({
            "id": tweet["id"],
            "text": tweet.get("text", ""),
            "author_id": tweet.get("author_id", ""),
            "username": author.get("username", ""),
            "name": author.get("name", ""),
        })

    return tweets


async def get_next_auto_slot(db) -> datetime:
    """
    Retorna el próximo datetime UTC disponible para un auto-post a las 5 AM Monterrey.
    Garantiza máximo 1 auto-post (x_auto) por día.
    """
    # Obtener todos los auto-posts futuros programados
    result = await db.execute(
        select(ScheduledPost).where(
            ScheduledPost.source == "x_auto",
            ScheduledPost.status == "scheduled",
        )
    )
    scheduled = result.scalars().all()

    # Fechas (en TZ Monterrey) ya ocupadas por auto-posts
    taken_dates: set = set()
    for post in scheduled:
        if post.scheduled_at:
            mty_dt = post.scheduled_at.replace(tzinfo=timezone.utc).astimezone(MONTERREY_TZ)
            taken_dates.add(mty_dt.date())

    # Buscar el primer día disponible comenzando desde hoy
    now_mty = datetime.now(MONTERREY_TZ)
    candidate_date = now_mty.date()

    while True:
        candidate_mty = datetime(
            candidate_date.year,
            candidate_date.month,
            candidate_date.day,
            5, 0, 0,
            tzinfo=MONTERREY_TZ,
        )
        # Debe ser en el futuro y la fecha no debe estar ocupada
        if candidate_mty > now_mty and candidate_date not in taken_dates:
            return candidate_mty.astimezone(timezone.utc).replace(tzinfo=None)

        candidate_date += timedelta(days=1)


async def process_liked_tweet(tweet_id: str, tweet_url: str, tweet_username: str) -> None:
    """
    Procesa un tweet con 'me gusta':
    1. Verifica que no haya sido procesado antes.
    2. Hace scraping del tweet.
    3. Genera el post de LinkedIn con Claude.
    4. Calendariza a la próxima ranura de 5 AM Monterrey disponible.
    """
    from .x_scraper import scrape_tweet
    from .post_generator import generate_linkedin_post
    from .scheduler_service import schedule_post

    async with AsyncSessionLocal() as db:
        # Verificar si ya fue procesado
        existing_result = await db.execute(
            select(XLikedTweet).where(XLikedTweet.tweet_id == tweet_id)
        )
        if existing_result.scalar_one_or_none():
            return  # Ya procesado, saltar

        # Crear registro de seguimiento
        liked = XLikedTweet(
            tweet_id=tweet_id,
            tweet_url=tweet_url,
            tweet_author=tweet_username,
            status="processing",
        )
        db.add(liked)
        await db.commit()
        await db.refresh(liked)

        try:
            settings = get_settings()

            # Scraping del tweet
            tweet_data = await scrape_tweet(tweet_url)
            liked.tweet_author = tweet_data.author_name or tweet_username

            # Generar post de LinkedIn
            linkedin_text = await generate_linkedin_post(
                tweet=tweet_data,
                language=settings.post_language,
            )

            # Calcular próxima ranura disponible a 5 AM Monterrey
            run_at_utc = await get_next_auto_slot(db)

            # Determinar tipo de media
            if tweet_data.has_video:
                media_type = "video"
            elif tweet_data.pdf_url:
                media_type = "document"
            elif tweet_data.images:
                media_type = "image"
            else:
                media_type = "generate"

            # Crear post programado
            post = ScheduledPost(
                tweet_url=tweet_url,
                tweet_text=tweet_data.text,
                tweet_author=tweet_data.author_name or tweet_username,
                linkedin_text=linkedin_text,
                image_urls=tweet_data.images[:4],
                status="scheduled",
                scheduled_at=run_at_utc,
                source="x_auto",
                use_first_image=media_type == "image",
                media_type=media_type,
                pdf_url=tweet_data.pdf_url,
                document_title=(
                    tweet_data.paper_info.get("title", "Documento")
                    if tweet_data.paper_info else "Documento"
                ),
            )
            db.add(post)
            await db.commit()
            await db.refresh(post)

            # Registrar en el scheduler
            schedule_post(post.id, run_at_utc)

            # Actualizar registro de liked tweet
            liked.post_id = post.id
            liked.status = "processed"
            liked.processed_at = datetime.utcnow()
            await db.commit()

            logger.info(
                f"[X Monitor] Tweet {tweet_id} auto-calendarizado como post {post.id} "
                f"para {run_at_utc} UTC (5 AM Monterrey)"
            )

        except Exception as e:
            logger.error(f"[X Monitor] Error procesando tweet {tweet_id}: {e}")
            liked.status = "failed"
            liked.error_message = str(e)
            await db.commit()


async def _seed_existing_likes(tweets: list[dict]) -> int:
    """
    Primera ejecución: marca todos los likes actuales como 'skipped' sin procesarlos.
    Retorna cuántos se registraron.
    """
    count = 0
    async with AsyncSessionLocal() as db:
        for tweet in tweets:
            tweet_id = tweet["id"]
            username = tweet.get("username", "")
            tweet_url = f"https://x.com/{username}/status/{tweet_id}" if username else ""

            existing = await db.execute(
                select(XLikedTweet).where(XLikedTweet.tweet_id == tweet_id)
            )
            if existing.scalar_one_or_none():
                continue

            liked = XLikedTweet(
                tweet_id=tweet_id,
                tweet_url=tweet_url,
                tweet_author=tweet.get("username", ""),
                status="skipped",
                processed_at=datetime.utcnow(),
            )
            db.add(liked)
            count += 1

        await db.commit()
    return count


async def check_and_process_likes() -> None:
    """
    Función principal del monitor. Llamada periódicamente por el scheduler.

    - Primera ejecución (tabla XLikedTweet vacía): semilla — marca todos los
      likes actuales como 'skipped' para no procesarlos retroactivamente.
    - Ejecuciones posteriores: procesa solo los likes genuinamente nuevos.
    """
    settings = get_settings()

    if not settings.x_bearer_token or not settings.x_user_id:
        logger.debug("[X Monitor] Sin credenciales de X configuradas, saltando chequeo")
        return

    logger.info("[X Monitor] Chequeando tweets con 'me gusta'...")

    try:
        tweets = await fetch_liked_tweets(settings.x_bearer_token, settings.x_user_id)
    except httpx.HTTPStatusError as e:
        logger.error(
            f"[X Monitor] Error HTTP al consultar la API de X: "
            f"{e.response.status_code} - {e.response.text}"
        )
        return
    except Exception as e:
        logger.error(f"[X Monitor] Error al consultar la API de X: {e}")
        return

    # ── Semilla en primera ejecución ─────────────────────────────────────────
    async with AsyncSessionLocal() as db:
        count_result = await db.execute(select(func.count(XLikedTweet.id)))
        is_first_run = count_result.scalar_one() == 0

    if is_first_run:
        seeded = await _seed_existing_likes(tweets)
        logger.info(
            f"[X Monitor] Primera ejecución — semilla completada: "
            f"{seeded} likes existentes marcados como 'skipped'. "
            f"Solo se procesarán los nuevos likes a partir de ahora."
        )
        return

    # ── Procesamiento normal ─────────────────────────────────────────────────
    for tweet in tweets:
        tweet_id = tweet["id"]
        username = tweet.get("username", "")
        if not username:
            logger.warning(f"[X Monitor] Tweet {tweet_id} sin username, saltando")
            continue
        tweet_url = f"https://x.com/{username}/status/{tweet_id}"
        await process_liked_tweet(tweet_id, tweet_url, username)

    logger.info(f"[X Monitor] Chequeo completo. Revisados: {len(tweets)} tweets.")
