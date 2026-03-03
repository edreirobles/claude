"""
Monitor de tweets con "me gusta" en X.

Cada N minutos consulta la API de X para obtener los tweets que el usuario
marcó como "me gusta". Por cada tweet nuevo, genera un post de LinkedIn y
lo calendariza automáticamente a las 5 AM hora de Monterrey.

Regla de calendarización automática:
- Máximo 1 publicación automática (x_auto) por día.
- Si ya hay una programada para hoy, se mueve al siguiente día disponible.
- Las publicaciones manuales desde la app NO cuentan para este límite.

Autenticación:
- Usa OAuth 1.0a (User Context) con las 4 credenciales de la Developer App.
- Los likes son privados para todos desde 2024; Bearer Token ya no funciona.
"""
import base64
import hashlib
import hmac
import logging
import secrets
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, func

from ..database import AsyncSessionLocal
from ..models import XLikedTweet, ScheduledPost
from ..config import get_settings

logger = logging.getLogger(__name__)

MONTERREY_TZ = ZoneInfo("America/Monterrey")


# ── OAuth 1.0a helpers ─────────────────────────────────────────────────────────

def _oauth1_header(
    method: str,
    url: str,
    query_params: dict,
    api_key: str,
    api_key_secret: str,
    access_token: str,
    access_token_secret: str,
) -> str:
    """
    Genera el header Authorization: OAuth 1.0a (HMAC-SHA1) para la URL y
    parámetros de query dados.
    """
    oauth_params = {
        "oauth_consumer_key": api_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }

    # Todos los parámetros juntos para la firma
    all_params = {**query_params, **oauth_params}
    encoded_params = "&".join(
        f"{urllib.parse.quote(k, safe='')}"
        f"="
        f"{urllib.parse.quote(str(v), safe='')}"
        for k, v in sorted(all_params.items())
    )

    # Base string
    base_string = "&".join([
        method.upper(),
        urllib.parse.quote(url, safe=""),
        urllib.parse.quote(encoded_params, safe=""),
    ])

    # Signing key
    signing_key = (
        urllib.parse.quote(api_key_secret, safe="")
        + "&"
        + urllib.parse.quote(access_token_secret, safe="")
    )

    # HMAC-SHA1 signature
    signature = base64.b64encode(
        hmac.new(
            signing_key.encode("ascii"),
            base_string.encode("ascii"),
            hashlib.sha1,
        ).digest()
    ).decode("ascii")

    oauth_params["oauth_signature"] = signature

    header_value = "OAuth " + ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
        for k, v in sorted(oauth_params.items())
    )
    return header_value


async def fetch_liked_tweets(
    api_key: str,
    api_key_secret: str,
    access_token: str,
    access_token_secret: str,
    user_id: str,
) -> list[dict]:
    """Consulta la API de X v2 con OAuth 1.0a para obtener los likes del usuario."""
    url = f"https://api.twitter.com/2/users/{user_id}/liked_tweets"
    params = {
        "max_results": "10",
        "expansions": "author_id",
        "user.fields": "username,name",
        "tweet.fields": "created_at,author_id",
    }

    auth_header = _oauth1_header(
        method="GET",
        url=url,
        query_params=params,
        api_key=api_key,
        api_key_secret=api_key_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
    )

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            url,
            params=params,
            headers={"Authorization": auth_header},
        )
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

    oauth_ready = all([
        settings.x_api_key,
        settings.x_api_key_secret,
        settings.x_access_token,
        settings.x_access_token_secret,
        settings.x_user_id,
    ])
    if not oauth_ready:
        logger.debug(
            "[X Monitor] Faltan credenciales OAuth 1.0a de X "
            "(X_API_KEY, X_API_KEY_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET, X_USER_ID). "
            "Saltando chequeo."
        )
        return

    logger.info("[X Monitor] Chequeando tweets con 'me gusta' (OAuth 1.0a)...")

    try:
        tweets = await fetch_liked_tweets(
            api_key=settings.x_api_key,
            api_key_secret=settings.x_api_key_secret,
            access_token=settings.x_access_token,
            access_token_secret=settings.x_access_token_secret,
            user_id=settings.x_user_id,
        )
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
