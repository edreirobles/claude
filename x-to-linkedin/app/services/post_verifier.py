"""
Verificador previo a publicacion.

Objetivos:
- Evitar publicar fuentes caidas o inaccesibles.
- Cancelar repeticiones exactas por URL de fuente.
- Reescribir lenguaje temporal cuando la fuente siga vigente pero el framing ya sea viejo.
- Dejar un motivo visible cuando un post se cancele por verificacion.
"""
import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal
from ..models import ScheduledPost
from .post_generator import (
    _sanitize_source_text_for_storytelling,
    refresh_linkedin_post_for_currentness,
)
from .url_scraper import scrape_url
from .x_scraper import normalize_tweet_url, scrape_tweet

logger = logging.getLogger(__name__)

TIME_SENSITIVE_PATTERNS = [
    r"\bacaba de\b",
    r"\bjust (launched|released|announced)\b",
    r"\bhoy\b",
    r"\btoday\b",
    r"\bahora\b",
    r"\bnew\b",
    r"\bnuevo\b",
    r"\brolling out\b",
    r"\bstarting today\b",
    r"\bya (esta|está|es)\b",
    r"\bavailable now\b",
    r"\bdisponible (hoy|ahora)\b",
    r"\bacaba de publicar\b",
]

PROMO_OR_LAUNCH_PATTERNS = [
    r"\blanza\b",
    r"\blaunch\b",
    r"\bannounc",
    r"\bpresent",
    r"\bdisponible\b",
    r"\bgratis\b",
    r"\bfree\b",
    r"\bya no solo\b",
    r"\bnow\b",
]

ACADEMIC_DOMAINS = {
    "nature.com",
    "arxiv.org",
    "web.stanford.edu",
    "web.mit.edu",
}

TRACKING_QUERY_PREFIXES = (
    "utm_",
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "ref_src",
)

SOURCE_FETCH_TIMEOUT_SECONDS = 45
MODEL_REFRESH_TIMEOUT_SECONDS = 60

SUMMARY_STYLE_PATTERNS = (
    "la documentación",
    "la documentación de",
    "el artículo presenta",
    "la guía describe",
    "openai, en su guía",
    "anthropic, en su guía",
    "google, en su guía",
    "entre sus funciones",
    "en resumen",
    "en conclusión",
)

TECHNICAL_STYLE_MARKERS = (
    "api ",
    " api",
    "sdk",
    "endpoint",
    "payload",
    "json",
    "schema",
    "timeout",
    "backoff",
    "service_tier",
    "custom_id",
    ".jsonl",
    "responses api",
    "chat completions",
    "sandbox",
    "thinking_level",
    "inline_data",
    "latencia",
    "parámetro",
    "parametro",
    "token",
)


def _is_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def _parse_iso_dt(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _tweet_datetime_from_url(url: str) -> Optional[datetime]:
    match = re.search(r"/(?:status|article)/(\d+)", url)
    if not match:
        return None
    try:
        tweet_id = int(match.group(1))
        epoch_ms = 1288834974657
        timestamp_ms = (tweet_id >> 22) + epoch_ms
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    except Exception:
        return None


def _normalize_web_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = "https" if parsed.scheme in {"", "http", "https"} else parsed.scheme
    netloc = parsed.netloc.lower().replace("www.", "")
    path = parsed.path or "/"

    if netloc == "platform.openai.com":
        if path == "/docs/guides/images/image-generation":
            netloc = "developers.openai.com"
            path = "/api/docs/guides/image-generation"
        elif path == "/docs/guides/images-vision":
            netloc = "developers.openai.com"
            path = "/api/docs/guides/images-vision"
        elif path == "/docs/guides/tools-image-generation":
            netloc = "developers.openai.com"
            path = "/api/docs/guides/image-generation"
        elif path == "/docs/guides/prompt-generation":
            netloc = "developers.openai.com"
            path = "/api/docs/guides/prompting"
        elif path == "/docs/guides/batch/getting-started":
            netloc = "developers.openai.com"
            path = "/api/docs/guides/batch"
        elif path.startswith("/docs/guides/"):
            netloc = "developers.openai.com"
            path = "/api" + path

    if path != "/":
        path = path.rstrip("/")

    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not any(key.lower().startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES)
    ]
    query = urlencode(sorted(query_items), doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def _normalize_source_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "x.com/" in raw or "twitter.com/" in raw:
        return normalize_tweet_url(raw)
    return _normalize_web_url(raw)


def _has_time_sensitive_language(text: str) -> bool:
    lowered = (text or "").lower()
    return any(re.search(pattern, lowered) for pattern in TIME_SENSITIVE_PATTERNS)


def _looks_stylistically_artificial(text: str) -> bool:
    lowered = (text or "").lower()
    colon_count = lowered.count(":")
    summary_hits = sum(1 for pattern in SUMMARY_STYLE_PATTERNS if pattern in lowered)
    return (
        colon_count > 2
        or summary_hits >= 2
        or "\n-" in lowered
        or "\n•" in lowered
    )


def _has_source_line(text: str) -> bool:
    return bool(re.search(r"(?mi)^Fuente:\s*https?://\S+\s*$", (text or "").strip()))


def _looks_overly_technical(text: str) -> bool:
    lowered = (text or "").lower()
    hits = sum(1 for marker in TECHNICAL_STYLE_MARKERS if marker in lowered)
    return hits >= 3 or ("documentación" in lowered and hits >= 2)


def _looks_like_launch_or_promo(text: str) -> bool:
    lowered = (text or "").lower()
    return any(re.search(pattern, lowered) for pattern in PROMO_OR_LAUNCH_PATTERNS)


def _is_news_like_source(snapshot: dict[str, Any]) -> bool:
    domain = (snapshot.get("source_domain") or "").lower()
    url = (snapshot.get("url") or "").lower()
    if snapshot.get("kind") == "tweet":
        return True
    if domain in ACADEMIC_DOMAINS:
        return False
    return any(
        marker in url
        for marker in ("/news/", "/blog/", "/features/", "/product", "/products/")
    ) or domain.startswith("blog.")


async def _fetch_pdf_snapshot(url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
    return {
        "kind": "pdf",
        "url": url,
        "accessible": True,
        "title": urlparse(url).path.split("/")[-1] or "PDF",
        "text": "",
        "source_domain": urlparse(url).netloc.replace("www.", ""),
        "source_datetime": None,
        "content_type": content_type,
    }


async def _fetch_source_snapshot(url: str) -> dict[str, Any]:
    normalized_url = _normalize_source_url(url)

    if _is_pdf_url(normalized_url):
        return await _fetch_pdf_snapshot(normalized_url)

    if "x.com/" in normalized_url or "twitter.com/" in normalized_url:
        tweet = await scrape_tweet(normalized_url)
        if not tweet.text or "No se pudo extraer" in tweet.text:
            raise ValueError("La fuente en X no devolvio contenido verificable")
        return {
            "kind": "tweet",
            "url": normalized_url,
            "accessible": True,
            "title": f"{tweet.author_name} en X".strip(),
            "text": tweet.article_content or tweet.text,
            "source_domain": "x.com",
            "source_datetime": _tweet_datetime_from_url(normalized_url),
            "images": tweet.images,
            "links": tweet.links,
        }

    content = await scrape_url(normalized_url)
    if not content.title and not content.text:
        raise ValueError("La fuente web no devolvio contenido suficiente")

    return {
        "kind": "web",
        "url": normalized_url,
        "accessible": True,
        "title": content.title,
        "text": content.text,
        "source_domain": content.source_domain,
        "source_datetime": _parse_iso_dt(content.updated_at or content.published_at),
        "published_at": content.published_at,
        "updated_at": content.updated_at,
        "images": content.images,
        "content_type": content.content_type,
    }


def _build_source_summary(snapshot: dict[str, Any]) -> str:
    parts = []
    if snapshot.get("title"):
        parts.append(f"Titulo: {snapshot['title']}")
    if snapshot.get("source_domain"):
        parts.append(f"Dominio: {snapshot['source_domain']}")
    if snapshot.get("source_datetime"):
        parts.append(
            f"Fecha relevante de fuente: {snapshot['source_datetime'].date().isoformat()}"
        )
    text = _sanitize_source_text_for_storytelling(
        (snapshot.get("text") or "").strip(),
        source_url=snapshot.get("url") or "",
        source_domain=snapshot.get("source_domain") or "",
    )
    if text:
        parts.append(f"Contenido:\n{text[:5000]}")
    return "\n\n".join(parts).strip()


async def _cancel_post(
    post: ScheduledPost,
    reason: str,
    db: AsyncSession,
) -> dict[str, Any]:
    post.status = "cancelled"
    post.error_message = f"Cancelado por verificacion previa: {reason}"
    await db.commit()
    logger.warning("Post %s cancelado por verificacion: %s", post.id, reason)
    return {
        "post_id": post.id,
        "action": "cancelled",
        "reason": reason,
    }


async def _load_post(db: AsyncSession, post_id: int) -> ScheduledPost | None:
    result = await db.execute(
        select(ScheduledPost).where(ScheduledPost.id == post_id)
    )
    return result.scalar_one_or_none()


async def _find_posts_with_same_source(
    db: AsyncSession,
    *,
    source_url: str,
    statuses: tuple[str, ...],
    exclude_post_id: int | None = None,
) -> list[ScheduledPost]:
    result = await db.execute(
        select(ScheduledPost).where(ScheduledPost.status.in_(statuses))
    )
    matches: list[ScheduledPost] = []
    for candidate in result.scalars().all():
        if exclude_post_id is not None and candidate.id == exclude_post_id:
            continue
        candidate_url = _normalize_source_url(candidate.tweet_url or "")
        if candidate_url and candidate_url == source_url:
            matches.append(candidate)
    return matches


def _should_run_model_review(
    *,
    post_text: str,
    snapshot: dict[str, Any],
    source_age_days: int | None,
) -> bool:
    if not (snapshot.get("text") or "").strip():
        return False
    if not _has_source_line(post_text or ""):
        return True
    if _looks_stylistically_artificial(post_text or ""):
        return True
    if _looks_overly_technical(post_text or ""):
        return True
    if _has_time_sensitive_language(post_text):
        return True
    if _looks_like_launch_or_promo(post_text):
        return True
    if snapshot.get("kind") == "tweet":
        return True
    if _is_news_like_source(snapshot):
        return True
    if source_age_days is not None and source_age_days > 120:
        return True
    return False


async def verify_scheduled_post(
    post_id: int,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    owns_session = db is None
    if owns_session:
        async with AsyncSessionLocal() as own_db:
            return await verify_scheduled_post(post_id, own_db)

    post = await _load_post(db, post_id)
    if not post:
        return {"post_id": post_id, "action": "missing", "reason": "Post no encontrado"}
    if post.status != "scheduled":
        return {
            "post_id": post_id,
            "action": "skipped",
            "reason": f"Estado actual: {post.status}",
        }

    source_url = _normalize_source_url(post.tweet_url or "")
    if not source_url:
        return await _cancel_post(post, "no tiene fuente asociada", db)

    published_duplicates = await _find_posts_with_same_source(
        db,
        source_url=source_url,
        statuses=("published",),
        exclude_post_id=post.id,
    )
    if published_duplicates:
        return await _cancel_post(
            post,
            "la misma fuente exacta ya fue publicada anteriormente",
            db,
        )

    scheduled_duplicates = await _find_posts_with_same_source(
        db,
        source_url=source_url,
        statuses=("scheduled",),
        exclude_post_id=post.id,
    )
    scheduled_duplicates.sort(
        key=lambda candidate: (
            candidate.scheduled_at or datetime.max,
            candidate.id,
        )
    )
    for earlier in scheduled_duplicates:
        if not earlier.scheduled_at or not post.scheduled_at:
            continue
        if (earlier.scheduled_at, earlier.id) < (post.scheduled_at, post.id):
            return await _cancel_post(
                post,
                "fuente repetida: ya existe otro post programado antes con la misma URL",
                db,
            )

    try:
        snapshot = await asyncio.wait_for(
            _fetch_source_snapshot(source_url),
            timeout=SOURCE_FETCH_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        return await _cancel_post(
            post,
            f"la fuente ya no esta disponible o no pudo verificarse ({exc})",
            db,
        )

    source_dt: Optional[datetime] = snapshot.get("source_datetime")
    now_utc = datetime.now(timezone.utc)
    source_age_days = None
    if source_dt:
        source_age_days = max((now_utc - source_dt).days, 0)

    if getattr(post, "manual_edited_at", None):
        post.error_message = None
        await db.commit()
        return {
            "post_id": post.id,
            "action": "verified",
            "reason": "texto editado manualmente; se respeto sin reescritura automatica",
        }

    if _should_run_model_review(
        post_text=post.linkedin_text or "",
        snapshot=snapshot,
        source_age_days=source_age_days,
    ):
        source_summary = _build_source_summary(snapshot)
        try:
            refreshed = await asyncio.wait_for(
                refresh_linkedin_post_for_currentness(
                    original_post=post.linkedin_text or "",
                    source_summary=source_summary,
                    source_url=source_url,
                    today_iso=now_utc.date().isoformat(),
                    language="es",
                ),
                timeout=MODEL_REFRESH_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            return await _cancel_post(
                post,
                f"no se pudo refrescar el copy para validarlo ({exc})",
                db,
            )

        refreshed = (refreshed or "").strip()
        if refreshed.startswith("[CANCELAR]:"):
            reason = refreshed.split(":", 1)[1].strip() if ":" in refreshed else refreshed
            return await _cancel_post(post, reason or "copy no vigente", db)

        if refreshed and refreshed != (post.linkedin_text or "").strip():
            post.linkedin_text = refreshed
            post.error_message = None
            if post.media_type == "generate":
                post.media_type = "none"
                post.generated_image_path = None
            await db.commit()
            logger.info("Post %s actualizado por verificacion previa", post.id)
            return {
                "post_id": post.id,
                "action": "updated",
                "reason": "copy actualizado para mantener vigencia",
            }

    post.error_message = None
    await db.commit()
    return {
        "post_id": post.id,
        "action": "verified",
        "reason": "fuente accesible y sin cambios criticos",
    }


async def verify_all_scheduled_posts() -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledPost.id)
            .where(ScheduledPost.status == "scheduled")
            .order_by(ScheduledPost.scheduled_at, ScheduledPost.id)
        )
        post_ids = [row[0] for row in result.all()]

    outcomes: list[dict[str, Any]] = []
    for post_id in post_ids:
        outcomes.append(await verify_scheduled_post(post_id))
    return outcomes
