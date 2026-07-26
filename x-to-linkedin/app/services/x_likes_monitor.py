"""
Monitor de tweets con "me gusta" en X.

Cada N minutos scrapea la página de likes del usuario con Playwright
(gratis, sin API de pago). Por cada tweet nuevo, genera un post de
LinkedIn y lo calendariza automáticamente a las 9 AM hora de Monterrey.

Regla de calendarización automática:
- Máximo 1 publicación por día.
- Si ya hay una programada para hoy, se mueve al siguiente día disponible.

Configuración necesaria en .env:
    X_USERNAME     → tu @ handle sin el @ (ej: johndoe)
    X_AUTH_TOKEN   → cookie "auth_token" de x.com (DevTools → Application → Cookies)
    X_CT0          → cookie "ct0" de x.com
"""
import re
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, func

from ..database import AsyncSessionLocal
from ..models import XLikedTweet, ScheduledPost
from ..config import get_settings
from .x_scraper import parse_x_post_url

logger = logging.getLogger(__name__)

MONTERREY_TZ = ZoneInfo("America/Mexico_City")

X_EPOCH_MS = 1288834974657


def tweet_id_to_datetime(tweet_id: str) -> datetime | None:
    """Convierte un tweet ID (snowflake) a datetime UTC aproximado de creación."""
    try:
        timestamp_ms = (int(tweet_id) >> 22) + X_EPOCH_MS
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    except Exception:
        return None


# ── Playwright scraper ─────────────────────────────────────────────────────────

async def scrape_liked_tweets(
    username: str,
    auth_token: str,
    ct0: str,
    max_tweets: int | None = 10,
    max_scrolls: int = 0,
    stop_after_no_new_rounds: int = 3,
    min_tweet_date: datetime | None = None,
    scroll_wait_ms: int = 1200,
) -> list[dict]:
    """
    Navega a x.com/{username}/likes con las cookies de sesión y extrae
    los últimos tweets con 'me gusta'. Retorna lista de dicts con
    {id, username, name, created_at}.

    Parámetros:
    - max_tweets: límite duro de tweets a recolectar. None = sin límite fijo.
    - max_scrolls: cuántos scrolls profundos intentar. 0 = solo vista inicial.
    - stop_after_no_new_rounds: corta si deja de encontrar likes nuevos.
    - min_tweet_date: si se provee, termina antes cuando ya no encuentra tweets
      de esa fecha en adelante durante varias rondas consecutivas.
    """
    try:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    except ImportError:
        logger.error("[X Monitor] playwright no está instalado")
        return []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
            )

            await context.add_cookies([
                {
                    "name": "auth_token",
                    "value": auth_token,
                    "domain": ".x.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                },
                {
                    "name": "ct0",
                    "value": ct0,
                    "domain": ".x.com",
                    "path": "/",
                    "secure": True,
                },
            ])

            page = await context.new_page()
            await page.goto(
                f"https://x.com/{username}/likes",
                wait_until="domcontentloaded",
                timeout=30000,
            )

            # Esperar que carguen los tweets
            try:
                await page.wait_for_selector('[data-testid="tweet"]', timeout=15000)
            except PWTimeout:
                # Detectar si fuimos redirigidos al login (cookie expirada)
                current_url = page.url
                if "login" in current_url or "i/flow" in current_url:
                    logger.warning(
                        "[X Monitor] Redirigido al login — las cookies X_AUTH_TOKEN / X_CT0 "
                        "expiraron o son incorrectas. Actualízalas en el .env."
                    )
                else:
                    logger.warning(
                        "[X Monitor] Timeout esperando tweets en la página de likes. "
                        f"URL actual: {current_url}"
                    )
                await browser.close()
                return []

            tweets: list[dict] = []
            seen_ids: set[str] = set()
            scrolls = 0
            no_new_rounds = 0
            old_only_rounds = 0

            while True:
                before = len(tweets)
                newer_in_round = 0

                # Extraer IDs desde links de posts de X: /status/ o /article/
                link_els = await page.query_selector_all('a[href*="/status/"], a[href*="/article/"]')
                for link_el in link_els:
                    href = await link_el.get_attribute("href")
                    if not href:
                        continue

                    parsed = parse_x_post_url(f"https://x.com{href}")
                    author_handle = parsed.get("username", "")
                    tweet_id = parsed.get("tweet_id", "")
                    kind = parsed.get("kind", "")
                    if not tweet_id or kind not in {"status", "article"}:
                        continue

                    # Saltar handles del sistema
                    if author_handle in ("i", "search", "home", "explore"):
                        continue
                    if tweet_id in seen_ids:
                        continue

                    created_at = tweet_id_to_datetime(tweet_id)
                    if min_tweet_date and created_at and created_at >= min_tweet_date:
                        newer_in_round += 1

                    seen_ids.add(tweet_id)
                    tweets.append({
                        "id": tweet_id,
                        "username": author_handle,
                        "name": author_handle,
                        "kind": kind,
                        "created_at": created_at.isoformat() if created_at else None,
                    })

                    if max_tweets and len(tweets) >= max_tweets:
                        break

                found_new = len(tweets) - before
                if found_new == 0:
                    no_new_rounds += 1
                else:
                    no_new_rounds = 0

                if min_tweet_date:
                    if found_new > 0 and newer_in_round == 0:
                        old_only_rounds += 1
                    elif newer_in_round > 0:
                        old_only_rounds = 0

                if max_tweets and len(tweets) >= max_tweets:
                    break
                if max_scrolls <= 0:
                    break
                if no_new_rounds >= stop_after_no_new_rounds:
                    break
                if min_tweet_date and old_only_rounds >= 6:
                    break
                if scrolls >= max_scrolls:
                    break

                scrolls += 1
                await page.mouse.wheel(0, 7000)
                await page.wait_for_timeout(scroll_wait_ms)

            await browser.close()
            if min_tweet_date:
                tweets = [
                    t for t in tweets
                    if not t.get("created_at")
                    or datetime.fromisoformat(t["created_at"]) >= min_tweet_date
                ]
            logger.info(
                f"[X Monitor] Playwright: {len(tweets)} likes encontrados en la página "
                f"(scrolls={scrolls})"
            )
            return tweets

    except Exception as e:
        logger.error(f"[X Monitor] Error en scraping de likes con Playwright: {e}")
        return []


# ── Scheduler helpers ──────────────────────────────────────────────────────────

DAILY_SLOTS = [9]  # Hora en Monterrey: 9 AM


async def get_next_auto_slot(db) -> datetime:
    """
    Retorna el próximo datetime UTC disponible para un auto-post.
    Slot por día (hora Monterrey): 9 AM — máximo 1 post por día.
    """
    result = await db.execute(
        select(ScheduledPost).where(
            ScheduledPost.status.in_(("scheduled", "approval_pending", "radar_slot")),
        )
    )
    scheduled = result.scalars().all()

    # Slots ya ocupados: set de (date, hour)
    taken_slots: set[tuple] = set()
    for post in scheduled:
        if post.scheduled_at:
            mty_dt = post.scheduled_at.replace(tzinfo=timezone.utc).astimezone(MONTERREY_TZ)
            taken_slots.add((mty_dt.date(), mty_dt.hour))

    now_mty = datetime.now(MONTERREY_TZ)
    candidate_date = now_mty.date()

    while True:
        for hour in DAILY_SLOTS:
            candidate_mty = datetime(
                candidate_date.year,
                candidate_date.month,
                candidate_date.day,
                hour, 0, 0,
                tzinfo=MONTERREY_TZ,
            )
            if candidate_mty > now_mty and (candidate_date, hour) not in taken_slots:
                return candidate_mty.astimezone(timezone.utc).replace(tzinfo=None)

        candidate_date += timedelta(days=1)


# ── Tweet processing ───────────────────────────────────────────────────────────

async def process_liked_tweet(
    tweet_id: str,
    tweet_url: str,
    tweet_username: str,
    allow_retry_skipped: bool = False,
) -> str:
    """
    Procesa un tweet con 'me gusta':
    1. Verifica que no haya sido procesado antes.
    2. Hace scraping del tweet.
    3. Genera el post de LinkedIn con Claude.
    4. Calendariza a la próxima ranura de 9 AM Monterrey disponible.
    """
    from .x_scraper import is_arxiv_paper, scrape_tweet
    from .post_generator import generate_linkedin_post
    from .scheduler_service import schedule_post

    async with AsyncSessionLocal() as db:
        existing_result = await db.execute(
            select(XLikedTweet).where(XLikedTweet.tweet_id == tweet_id)
        )
        existing = existing_result.scalar_one_or_none()
        retried_skipped = False

        if existing:
            if allow_retry_skipped and existing.status in {"skipped", "failed", "rejected"}:
                liked = existing
                liked.status = "processing"
                liked.error_message = None
                liked.post_id = None
                liked.processed_at = datetime.utcnow()
                retried_skipped = True
                await db.commit()
                await db.refresh(liked)
                logger.info(
                    "[X Monitor] Reintentando like %s con estado previo %s",
                    tweet_id,
                    existing.status,
                )
            else:
                return "already_considered"
        else:
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

            tweet_data = await scrape_tweet(tweet_url)
            liked.tweet_author = tweet_data.author_name or tweet_username

            linkedin_text = await generate_linkedin_post(
                tweet=tweet_data,
                language=settings.post_language,
            )

            # Si Claude indica que el tweet no tiene sustancia para publicar, rechazarlo
            if linkedin_text.startswith("[NO_PUBLICAR]"):
                reason = linkedin_text.split(":", 1)[-1].strip()
                liked.status = "rejected"
                liked.error_message = reason
                liked.processed_at = datetime.utcnow()
                await db.commit()
                logger.info(
                    f"[X Monitor] Tweet {tweet_id} rechazado (no publicable): {reason}"
                )
                return "rejected_skipped" if retried_skipped else "rejected_new"

            run_at_utc = await get_next_auto_slot(db)

            if is_arxiv_paper(tweet_data.paper_info) and tweet_data.pdf_url:
                media_type = "paper_image"
            elif tweet_data.has_video:
                media_type = "video"
            elif tweet_data.pdf_url:
                media_type = "document"
            elif tweet_data.images:
                media_type = "image"
            else:
                media_type = "none"

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

            schedule_post(post.id, run_at_utc)

            liked.post_id = post.id
            liked.status = "processed"
            liked.processed_at = datetime.utcnow()
            await db.commit()

            logger.info(
                f"[X Monitor] Tweet {tweet_id} auto-calendarizado como post {post.id} "
                f"para {run_at_utc} UTC (5 AM Monterrey)"
            )
            return "processed_skipped" if retried_skipped else "processed_new"

        except Exception as e:
            logger.error(f"[X Monitor] Error procesando tweet {tweet_id}: {e}")
            liked.status = "failed"
            liked.error_message = str(e)
            await db.commit()
            return "failed_skipped" if retried_skipped else "failed_new"


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
            kind = tweet.get("kind", "status")
            tweet_url = f"https://x.com/{username}/{kind}/{tweet_id}" if username else ""

            existing = await db.execute(
                select(XLikedTweet).where(XLikedTweet.tweet_id == tweet_id)
            )
            if existing.scalar_one_or_none():
                continue

            liked = XLikedTweet(
                tweet_id=tweet_id,
                tweet_url=tweet_url,
                tweet_author=username,
                status="skipped",
                processed_at=datetime.utcnow(),
            )
            db.add(liked)
            count += 1

        await db.commit()
    return count


async def backfill_likes_from_year(year: int) -> dict:
    """
    Escanea profundamente la página de likes y procesa los tweets no considerados
    desde el 1 de enero del año indicado.

    "No considerados" incluye:
    - likes que no existían aún en x_liked_tweets
    - likes sembrados como skipped en la primera ejecución
    """
    settings = get_settings()

    if not settings.x_username or not settings.x_auth_token or not settings.x_ct0:
        raise RuntimeError(
            "Faltan credenciales de sesión de X (X_USERNAME, X_AUTH_TOKEN, X_CT0)"
        )

    cutoff = datetime(year, 1, 1, tzinfo=timezone.utc)
    logger.info(
        f"[X Monitor] Iniciando backfill para tweets desde {cutoff.isoformat()} "
        f"de @{settings.x_username}"
    )

    tweets = await scrape_liked_tweets(
        username=settings.x_username,
        auth_token=settings.x_auth_token,
        ct0=settings.x_ct0,
        max_tweets=None,
        max_scrolls=80,
        stop_after_no_new_rounds=4,
        min_tweet_date=cutoff,
        scroll_wait_ms=700,
    )

    if not tweets:
        return {
            "year": year,
            "scanned": 0,
            "eligible": 0,
            "processed_new": 0,
            "processed_skipped": 0,
            "rejected": 0,
            "failed": 0,
            "already_considered": 0,
            "message": "No se obtuvieron likes del rango solicitado.",
        }

    counts = {
        "processed_new": 0,
        "processed_skipped": 0,
        "rejected": 0,
        "failed": 0,
        "already_considered": 0,
    }

    for tweet in tweets:
        tweet_id = tweet["id"]
        username = tweet.get("username", "")
        if not username:
            continue
        kind = tweet.get("kind", "status")
        tweet_url = f"https://x.com/{username}/{kind}/{tweet_id}"
        result = await process_liked_tweet(
            tweet_id,
            tweet_url,
            username,
            allow_retry_skipped=True,
        )

        if result == "processed_new":
            counts["processed_new"] += 1
        elif result == "processed_skipped":
            counts["processed_skipped"] += 1
        elif result in ("rejected_new", "rejected_skipped"):
            counts["rejected"] += 1
        elif result in ("failed_new", "failed_skipped"):
            counts["failed"] += 1
        else:
            counts["already_considered"] += 1

    total_scheduled = counts["processed_new"] + counts["processed_skipped"]
    logger.info(
        "[X Monitor] Backfill %s completado: %s nuevos, %s skipped reintentados, "
        "%s rechazados, %s fallidos, %s ya considerados",
        year,
        counts["processed_new"],
        counts["processed_skipped"],
        counts["rejected"],
        counts["failed"],
        counts["already_considered"],
    )

    return {
        "year": year,
        "scanned": len(tweets),
        "eligible": len(tweets),
        "processed_new": counts["processed_new"],
        "processed_skipped": counts["processed_skipped"],
        "rejected": counts["rejected"],
        "failed": counts["failed"],
        "already_considered": counts["already_considered"],
        "scheduled_total": total_scheduled,
        "message": (
            f"Backfill {year} completado: {total_scheduled} likes llevados al calendario "
            f"({counts['processed_new']} nuevos + {counts['processed_skipped']} skipped)."
        ),
    }


# ── Reempaquetado de schedule ───────────────────────────────────────────────────

async def repack_schedule() -> dict:
    """
    Reordena todos los posts 'scheduled' futuros para que ocupen los slots
    de 9 AM (hora Monterrey) de forma consecutiva sin huecos.
    Si hoy a las 9 AM ya está ocupado, empieza desde el siguiente slot libre.
    Retorna {"repacked": N, "slots": [lista de nuevos datetimes como strings]}.
    """
    from .scheduler_service import schedule_post

    async with AsyncSessionLocal() as db:
        now_utc = datetime.utcnow()

        result = await db.execute(
            select(ScheduledPost)
            .where(
                ScheduledPost.status == "scheduled",
                ScheduledPost.scheduled_at > now_utc,
            )
            .order_by(ScheduledPost.scheduled_at)
        )
        future_posts = result.scalars().all()

        if not future_posts:
            return {"repacked": 0, "slots": []}

        now_mty = datetime.now(MONTERREY_TZ)
        candidate_date = now_mty.date()

        # Generar suficientes slots consecutivos
        slots: list[datetime] = []
        while len(slots) < len(future_posts):
            for hour in DAILY_SLOTS:
                candidate_mty = datetime(
                    candidate_date.year, candidate_date.month, candidate_date.day,
                    hour, 0, 0, tzinfo=MONTERREY_TZ,
                )
                if candidate_mty > now_mty:
                    slots.append(candidate_mty.astimezone(timezone.utc).replace(tzinfo=None))
                if len(slots) >= len(future_posts):
                    break
            candidate_date += timedelta(days=1)

        count = 0
        slot_strs = []
        for post, new_dt in zip(future_posts, slots):
            slot_strs.append(
                new_dt.replace(tzinfo=timezone.utc)
                .astimezone(MONTERREY_TZ)
                .strftime("%Y-%m-%d %H:%M MTY")
            )
            if abs((post.scheduled_at - new_dt).total_seconds()) > 60:
                post.scheduled_at = new_dt
                schedule_post(post.id, new_dt)
                count += 1

        await db.commit()
        return {"repacked": count, "slots": slot_strs}


# ── Main entry point ───────────────────────────────────────────────────────────

async def check_and_process_likes() -> None:
    """
    Función principal del monitor. Llamada periódicamente por el scheduler.

    - Primera ejecución (tabla XLikedTweet vacía): semilla — marca todos los
      likes actuales como 'skipped' para no procesarlos retroactivamente.
    - Ejecuciones posteriores: procesa solo los likes genuinamente nuevos.
    """
    settings = get_settings()

    if not settings.x_username or not settings.x_auth_token or not settings.x_ct0:
        logger.debug(
            "[X Monitor] Faltan credenciales de sesión de X "
            "(X_USERNAME, X_AUTH_TOKEN, X_CT0). Saltando chequeo."
        )
        return

    logger.info(
        f"[X Monitor] Chequeando likes de @{settings.x_username} con Playwright..."
    )

    tweets = await scrape_liked_tweets(
        username=settings.x_username,
        auth_token=settings.x_auth_token,
        ct0=settings.x_ct0,
    )

    if not tweets:
        logger.warning(
            "[X Monitor] No se obtuvieron likes — revisa X_AUTH_TOKEN y X_CT0 en el .env."
        )
        return

    # ── Semilla en primera ejecución ─────────────────────────────────────────
    async with AsyncSessionLocal() as db:
        count_result = await db.execute(select(func.count(XLikedTweet.id)))
        is_first_run = count_result.scalar_one() == 0

    if is_first_run:
        seeded = await _seed_existing_likes(tweets)
        logger.info(
            f"[X Monitor] Primera ejecución — semilla: "
            f"{seeded} likes existentes marcados como 'skipped'. "
            f"Solo se procesarán los nuevos a partir de ahora."
        )
        return

    # ── Procesamiento normal ─────────────────────────────────────────────────
    for tweet in tweets:
        tweet_id = tweet["id"]
        username = tweet.get("username", "")
        if not username:
            continue
        kind = tweet.get("kind", "status")
        tweet_url = f"https://x.com/{username}/{kind}/{tweet_id}"
        await process_liked_tweet(tweet_id, tweet_url, username)

    logger.info(f"[X Monitor] Chequeo completo. Revisados: {len(tweets)} tweets.")
