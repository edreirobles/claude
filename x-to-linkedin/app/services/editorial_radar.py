"""
Radar editorial diario.

Busca fuentes recientes y confiables, elige una con criterio editorial y prepara
un post que queda esperando aprobacion por Telegram antes de publicarse.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import AsyncSessionLocal
from ..models import AppSettings, ScheduledPost
from .calendar_maintenance import _build_post_payload_from_source
from .editorial_learning import get_editorial_learning_profile
from .post_generator import _generate_text_with_provider, get_text_generation_config_error
from .post_verifier import _normalize_source_url
from .url_scraper import HEADERS
from .x_likes_monitor import DAILY_SLOTS

logger = logging.getLogger(__name__)
settings = get_settings()

MEXICO_CITY_TZ = ZoneInfo("America/Mexico_City")
RADAR_SLOT_STATUS = "radar_slot"
RADAR_APPROVAL_STATUS = "approval_pending"
RADAR_SOURCE = "radar"
RADAR_ACTIVE_STATUSES = (
    RADAR_SLOT_STATUS,
    RADAR_APPROVAL_STATUS,
    "scheduled",
    "published",
    "pending",
    "failed",
)


@dataclass(slots=True)
class RadarCandidate:
    url: str
    title: str
    summary: str
    source_name: str
    source_domain: str
    kind: str
    published_at: datetime | None = None
    source_weight: int = 1


@dataclass(slots=True)
class RadarDecision:
    candidate: RadarCandidate
    reason: str = ""
    intent: str = ""
    angle: str = ""


RADAR_FEEDS: tuple[dict[str, Any], ...] = (
    {
        "name": "OpenAI News",
        "url": "https://openai.com/news/rss.xml",
        "kind": "news",
        "weight": 4,
    },
    {
        "name": "Anthropic News",
        "url": "https://www.anthropic.com/news/rss.xml",
        "kind": "news",
        "weight": 4,
    },
    {
        "name": "Anthropic Engineering",
        "url": "https://www.anthropic.com/engineering/rss.xml",
        "kind": "practice",
        "weight": 5,
    },
    {
        "name": "Google AI Blog",
        "url": "https://blog.google/technology/ai/rss/",
        "kind": "news",
        "weight": 4,
    },
    {
        "name": "Google Research",
        "url": "https://blog.research.google/feeds/posts/default?alt=rss",
        "kind": "paper",
        "weight": 4,
    },
    {
        "name": "Hugging Face Blog",
        "url": "https://huggingface.co/blog/feed.xml",
        "kind": "tool",
        "weight": 4,
    },
    {
        "name": "MIT News AI",
        "url": "https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml",
        "kind": "news",
        "weight": 4,
    },
    {
        "name": "Stanford HAI",
        "url": "https://hai.stanford.edu/news/rss.xml",
        "kind": "news",
        "weight": 4,
    },
    {
        "name": "DeepLearning.AI The Batch",
        "url": "https://www.deeplearning.ai/the-batch/feed/",
        "kind": "practice",
        "weight": 3,
    },
    {
        "name": "VentureBeat AI",
        "url": "https://venturebeat.com/category/ai/feed/",
        "kind": "news",
        "weight": 2,
    },
)

SIGNAL_KEYWORDS = (
    "education",
    "educacion",
    "educación",
    "teacher",
    "student",
    "school",
    "university",
    "learning",
    "aprendizaje",
    "assessment",
    "grading",
    "exam",
    "cognitive",
    "tutor",
    "classroom",
    "agent",
    "workflow",
    "evaluation",
    "eval",
    "responsible",
    "safety",
    "privacy",
    "governance",
    "open source",
    "multimodal",
    "notebook",
    "research",
    "paper",
    "tool",
    "productivity",
    "best practice",
    "prompt",
)

RESEARCH_SIGNAL_KEYWORDS = (
    "education",
    "educacion",
    "educación",
    "learning",
    "aprendizaje",
    "teacher",
    "student",
    "school",
    "classroom",
    "assessment",
    "grading",
    "exam",
    "tutor",
    "agent",
    "workflow",
    "evaluation",
    "eval",
    "governance",
    "privacy",
    "safety",
    "responsible",
    "unlearning",
    "multimodal",
    "tool",
)

GENERIC_LLM_MARKERS = (
    "chatgpt",
    "gpt-",
    "gpt ",
    "claude",
    "gemini",
    "grok",
    "llama",
    "mistral",
)

GENERIC_LAUNCH_MARKERS = (
    "launch",
    "released",
    "release",
    "announces",
    "announced",
    "introduces",
    "presenta",
    "lanza",
    "modelo",
    "model",
    "available",
)


def _strip_html(value: str) -> str:
    if not value:
        return ""
    text = BeautifulSoup(value, "lxml").get_text(" ")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None

    try:
        dt = parsedate_to_datetime(raw)
    except Exception:
        dt = None

    if dt is None:
        candidates = [raw, raw.replace("Z", "+00:00")]
        for candidate in candidates:
            try:
                dt = datetime.fromisoformat(candidate)
                break
            except ValueError:
                continue

    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().replace("www.", "")


def _entry_text(entry, names: tuple[str, ...]) -> str:
    for name in names:
        node = entry.find(name)
        if node:
            text = node.get_text(" ").strip()
            if text:
                return text
    return ""


def _entry_link(entry) -> str:
    link = entry.find("link")
    if not link:
        return ""
    href = link.get("href")
    if href:
        return href.strip()
    return (link.get_text(" ") or "").strip()


def _looks_like_generic_llm_launch(candidate: RadarCandidate) -> bool:
    haystack = f"{candidate.title} {candidate.summary}".lower()
    has_llm = any(marker in haystack for marker in GENERIC_LLM_MARKERS)
    has_launch = any(marker in haystack for marker in GENERIC_LAUNCH_MARKERS)
    has_specific_use = any(
        marker in haystack
        for marker in (
            "education",
            "aprendizaje",
            "teacher",
            "student",
            "agent",
            "workflow",
            "tool",
            "research",
            "safety",
            "governance",
            "classroom",
            "notebook",
        )
    )
    return has_llm and has_launch and not has_specific_use


def _candidate_score(candidate: RadarCandidate, now_utc: datetime) -> float:
    haystack = f"{candidate.title} {candidate.summary}".lower()
    score = float(candidate.source_weight)

    kind_bonus = {
        "paper": 4,
        "practice": 4,
        "tool": 4,
        "news": 2,
    }
    score += kind_bonus.get(candidate.kind, 1)

    score += sum(1.2 for keyword in SIGNAL_KEYWORDS if keyword in haystack)

    if candidate.published_at:
        age_hours = max(
            0.0,
            (now_utc - candidate.published_at).total_seconds() / 3600,
        )
        if age_hours <= 48:
            score += 5
        elif age_hours <= settings.editorial_radar_source_max_age_hours:
            score += 2
        else:
            score -= 5
    else:
        score -= 1

    if _looks_like_generic_llm_launch(candidate):
        score -= 8

    if len(candidate.summary) < 80:
        score -= 1

    return score


def _is_recent_enough(candidate: RadarCandidate, now_utc: datetime) -> bool:
    if not candidate.published_at:
        return True
    max_age = max(int(settings.editorial_radar_source_max_age_hours or 168), 24)
    return candidate.published_at >= now_utc - timedelta(hours=max_age)


async def _get_text_with_ssl_fallback(url: str, *, headers: dict[str, str] | None = None, timeout: int = 20) -> str:
    request_headers = headers or HEADERS
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=request_headers,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text
    except Exception as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise

    logger.warning("Radar: SSL local fallo para %s; reintentando sin verificacion", url)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers=request_headers,
        verify=False,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def _fetch_feed_candidates(feed: dict[str, Any], now_utc: datetime) -> list[RadarCandidate]:
    try:
        raw_xml = await _get_text_with_ssl_fallback(feed["url"], timeout=12)
    except Exception as exc:
        logger.info("Radar: feed no disponible %s: %s", feed.get("name"), exc)
        return []

    soup = BeautifulSoup(raw_xml, "xml")
    entries = soup.find_all("entry") or soup.find_all("item")
    candidates: list[RadarCandidate] = []

    for entry in entries[:20]:
        title = _strip_html(_entry_text(entry, ("title",)))
        url = _entry_link(entry)
        summary = _strip_html(
            _entry_text(entry, ("summary", "description", "content", "content:encoded"))
        )
        published_at = _parse_datetime(
            _entry_text(entry, ("published", "pubDate", "updated", "dc:date"))
        )
        if not title or not url:
            continue

        candidate = RadarCandidate(
            url=url,
            title=title,
            summary=summary,
            source_name=str(feed["name"]),
            source_domain=_domain(url),
            kind=str(feed.get("kind") or "news"),
            published_at=published_at,
            source_weight=int(feed.get("weight") or 1),
        )
        if _is_recent_enough(candidate, now_utc):
            candidates.append(candidate)

    return candidates


async def _fetch_arxiv_candidates(now_utc: datetime) -> list[RadarCandidate]:
    query = (
        "(cat:cs.AI OR cat:cs.CL OR cat:cs.HC OR cat:cs.CY) "
        "AND (education OR learning OR tutor OR assessment OR agent OR workflow OR governance)"
    )
    params = urlencode(
        {
            "search_query": query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": "25",
        }
    )
    url = f"https://export.arxiv.org/api/query?{params}"

    try:
        raw_xml = await _get_text_with_ssl_fallback(
            url,
            headers={"User-Agent": HEADERS["User-Agent"]},
            timeout=18,
        )
    except Exception as exc:
        logger.info("Radar: arXiv no disponible: %s", exc)
        return []

    soup = BeautifulSoup(raw_xml, "xml")
    candidates: list[RadarCandidate] = []
    for entry in soup.find_all("entry"):
        title = _strip_html(_entry_text(entry, ("title",)))
        entry_url = _entry_text(entry, ("id",)).strip()
        summary = _strip_html(_entry_text(entry, ("summary",)))
        published_at = _parse_datetime(_entry_text(entry, ("published", "updated")))
        if not title or not entry_url:
            continue
        haystack = f"{title} {summary}".lower()
        if not any(keyword in haystack for keyword in RESEARCH_SIGNAL_KEYWORDS):
            continue
        candidate = RadarCandidate(
            url=entry_url,
            title=title,
            summary=summary,
            source_name="arXiv",
            source_domain="arxiv.org",
            kind="paper",
            published_at=published_at,
            source_weight=4,
        )
        if _is_recent_enough(candidate, now_utc):
            candidates.append(candidate)

    return candidates


async def _load_used_sources(
    db: AsyncSession,
    *,
    current_post_id: int | None = None,
) -> set[str]:
    result = await db.execute(
        select(ScheduledPost.id, ScheduledPost.tweet_url).where(
            ScheduledPost.tweet_url.isnot(None),
            ScheduledPost.status.in_(RADAR_ACTIVE_STATUSES),
        )
    )
    used: set[str] = set()
    for post_id, url in result.all():
        if current_post_id and post_id == current_post_id:
            continue
        normalized = _normalize_source_url(url or "")
        if normalized and not normalized.startswith("radar://"):
            used.add(normalized)
    return used


async def collect_radar_candidates(
    db: AsyncSession,
    *,
    current_post_id: int | None = None,
) -> list[RadarCandidate]:
    now_utc = datetime.now(timezone.utc)
    used_sources = await _load_used_sources(db, current_post_id=current_post_id)

    tasks = [
        asyncio.wait_for(_fetch_feed_candidates(feed, now_utc), timeout=30)
        for feed in RADAR_FEEDS
    ]
    tasks.append(asyncio.wait_for(_fetch_arxiv_candidates(now_utc), timeout=35))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    candidates: list[RadarCandidate] = []
    for result in results:
        if isinstance(result, Exception):
            logger.info("Radar: fuente fallida: %s", result)
            continue
        candidates.extend(result)

    deduped: list[RadarCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _normalize_source_url(candidate.url)
        if not normalized or normalized in seen or normalized in used_sources:
            continue
        if _looks_like_generic_llm_launch(candidate):
            logger.info("Radar: descartado por lanzamiento LLM general: %s", candidate.title)
            continue
        seen.add(normalized)
        deduped.append(candidate)

    deduped.sort(key=lambda c: _candidate_score(c, now_utc), reverse=True)
    return deduped[:35]


def _candidate_brief(index: int, candidate: RadarCandidate) -> str:
    published = candidate.published_at.isoformat() if candidate.published_at else "sin fecha"
    summary = candidate.summary[:650]
    return (
        f"{index}. [{candidate.kind}] {candidate.title}\n"
        f"Fuente: {candidate.source_name} ({candidate.source_domain})\n"
        f"Publicado: {published}\n"
        f"URL: {candidate.url}\n"
        f"Resumen: {summary}"
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _compact_editorial_profile(profile: str, *, limit: int = 2200) -> str:
    compact = re.sub(r"\s+\n", "\n", (profile or "").strip())
    compact = re.sub(r"\n{3,}", "\n\n", compact)
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit].rstrip()}..."


async def rank_radar_candidates(
    candidates: list[RadarCandidate],
    *,
    editorial_profile: str | None = None,
) -> list[RadarDecision]:
    if not candidates:
        return []

    config_error = get_text_generation_config_error()
    if config_error:
        logger.warning("Radar: sin modelo para ranking fino: %s", config_error)
        return [RadarDecision(candidate=c) for c in candidates]

    compact = "\n\n".join(
        _candidate_brief(index, candidate)
        for index, candidate in enumerate(candidates[:25], start=1)
    )
    system_prompt = (
        "Eres un radar editorial senior para una cuenta de LinkedIn sobre inteligencia artificial "
        "e IA en educacion.\n\n"
        "Tu trabajo es decidir, no automatizar. Elige fuentes concretas, frescas y publicables.\n"
        "Prioriza papers utiles, noticias relevantes, herramientas con IA que no sean LLMs generales, "
        "y buenas practicas aplicables.\n"
        "Usa la memoria editorial aprendida para detectar temas, enfoques y tipos de fuente con mayor probabilidad "
        "de funcionar en esta cuenta, sin repetir formulas antiguas.\n"
        "Evita lanzamientos genericos de modelos conversacionales salvo que tengan una implicacion educativa "
        "o profesional muy clara.\n"
        "Para cada candidata fuerte decide la intencion del post: presentar, describir, invitar a usar, "
        "explicar, advertir, analizar o reflexionar.\n\n"
        "Devuelve solo JSON valido con este formato:\n"
        "{\"ranked\":[{\"index\":1,\"reason\":\"...\",\"intent\":\"...\",\"angle\":\"...\"}]}\n"
        "Incluye de 3 a 7 candidatas en orden de prioridad."
    )
    profile_section = ""
    if editorial_profile:
        profile_section = (
            "MEMORIA EDITORIAL APRENDIDA:\n"
            f"{_compact_editorial_profile(editorial_profile, limit=2400)}\n\n"
        )
    user_message = f"{profile_section}CANDIDATAS:\n\n{compact}"

    try:
        raw = await _generate_text_with_provider(
            system_prompt=system_prompt,
            user_message=user_message,
            max_output_tokens=900,
        )
        payload = _extract_json_object(raw) or {}
    except Exception as exc:
        logger.warning("Radar: ranking con IA fallo, usando heuristica: %s", exc)
        return [RadarDecision(candidate=c) for c in candidates]

    decisions: list[RadarDecision] = []
    seen: set[int] = set()
    for item in payload.get("ranked", []):
        try:
            idx = int(item.get("index"))
        except Exception:
            continue
        if idx < 1 or idx > len(candidates) or idx in seen:
            continue
        seen.add(idx)
        decisions.append(
            RadarDecision(
                candidate=candidates[idx - 1],
                reason=str(item.get("reason") or "").strip(),
                intent=str(item.get("intent") or "").strip(),
                angle=str(item.get("angle") or "").strip(),
            )
        )

    if not decisions:
        return [RadarDecision(candidate=c) for c in candidates]

    for index, candidate in enumerate(candidates, start=1):
        if index not in seen:
            decisions.append(RadarDecision(candidate=candidate))
    return decisions


def _build_editorial_context(
    decision: RadarDecision,
    *,
    editorial_profile: str | None = None,
) -> str:
    bits = [
        "Esta fuente fue elegida por el radar editorial diario.",
        "No fuerces una reflexion si la fuente funciona mejor como presentacion, descripcion o invitacion practica.",
        "No uses markdown, asteriscos, viñetas ni guiones medios.",
        "Si no hay imagen real de la fuente, escribe una primera linea mas fuerte como frase ancla.",
    ]
    if decision.intent:
        bits.append(f"Intencion recomendada del post: {decision.intent}.")
    if decision.angle:
        bits.append(f"Angulo recomendado: {decision.angle}.")
    if decision.reason:
        bits.append(f"Motivo de seleccion: {decision.reason}.")
    if editorial_profile:
        bits.append(
            "Perfil editorial aprendido desde publicaciones historicas: "
            f"{_compact_editorial_profile(editorial_profile, limit=1800)}"
        )
    return " ".join(bits)


async def _load_custom_prompt(db: AsyncSession) -> str | None:
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    cfg = result.scalar_one_or_none()
    return cfg.custom_prompt if cfg else None


async def prepare_radar_post(post_id: int, *, force: bool = False) -> dict[str, Any]:
    """
    Convierte un radar_slot en approval_pending con una fuente elegida y copy listo.
    """
    config_error = get_text_generation_config_error()
    if config_error:
        raise RuntimeError(config_error)

    async with AsyncSessionLocal() as db:
        post = await db.get(ScheduledPost, post_id)
        if not post:
            raise ValueError(f"Post #{post_id} no encontrado")
        if post.status == "scheduled" and not force:
            return {"prepared": False, "reason": "ya aprobado", "post_id": post_id}
        if post.status == RADAR_APPROVAL_STATUS and not force:
            return {"prepared": False, "reason": "ya preparado", "post_id": post_id}
        if post.status not in {RADAR_SLOT_STATUS, RADAR_APPROVAL_STATUS, "failed"}:
            raise ValueError(f"Post #{post_id} no es un slot radar editable")

        custom_prompt = await _load_custom_prompt(db)
        try:
            editorial_profile = await get_editorial_learning_profile(db)
        except Exception as exc:
            logger.warning("Radar: no se pudo cargar memoria editorial aprendida: %s", exc)
            editorial_profile = ""

        candidates = await collect_radar_candidates(
            db,
            current_post_id=None if force else post_id,
        )
        if not candidates:
            raise RuntimeError("El radar no encontro candidatos recientes y no repetidos.")

        decisions = await rank_radar_candidates(
            candidates,
            editorial_profile=editorial_profile,
        )
        last_error = ""
        for decision in decisions[:8]:
            candidate = decision.candidate
            try:
                editorial_context = _build_editorial_context(
                    decision,
                    editorial_profile=editorial_profile,
                )
                if post.editorial_revision_notes:
                    editorial_context += (
                        " Indicaciones acumuladas pedidas por el autor para este post: "
                        f"{post.editorial_revision_notes[:2000]}"
                    )
                payload = await _build_post_payload_from_source(
                    source_url=candidate.url,
                    custom_prompt=custom_prompt,
                    language=settings.post_language or "es",
                    editorial_context=editorial_context,
                )
                media_type = payload.get("media_type") or "none"
                if media_type == "generate":
                    media_type = "none"
                if media_type == "image" and not payload.get("image_urls"):
                    media_type = "none"

                post.tweet_url = payload["tweet_url"]
                post.tweet_text = payload["tweet_text"]
                post.tweet_author = payload["tweet_author"] or candidate.source_name
                post.linkedin_text = payload["linkedin_text"]
                post.image_urls = payload["image_urls"] if media_type == "image" else []
                post.use_first_image = media_type == "image"
                post.media_type = media_type
                post.pdf_url = payload.get("pdf_url")
                post.document_title = payload.get("document_title", "Documento")
                post.generated_image_path = None
                post.status = RADAR_APPROVAL_STATUS
                post.source = RADAR_SOURCE
                post.error_message = (
                    f"Radar eligio: {candidate.title}. "
                    f"Intencion: {decision.intent or 'decidida por el copy'}. "
                    f"Motivo: {decision.reason or 'mejor senal editorial disponible'}."
                )[:1200]
                await db.commit()
                await db.refresh(post)
                logger.info(
                    "Radar: post %s preparado con %s (%s)",
                    post_id,
                    candidate.title,
                    candidate.url,
                )
                return {
                    "prepared": True,
                    "post_id": post_id,
                    "source_url": candidate.url,
                    "title": candidate.title,
                    "reason": decision.reason,
                    "intent": decision.intent,
                    "angle": decision.angle,
                }
            except Exception as exc:
                last_error = f"{candidate.url}: {exc}"
                logger.warning("Radar: candidata descartada durante preparacion: %s", last_error)

        post.status = "failed"
        post.error_message = (
            "El radar encontro candidatos, pero ninguno pudo convertirse en post publicable. "
            f"Ultimo error: {last_error}"
        )[:1200]
        await db.commit()
        raise RuntimeError(post.error_message)


async def ensure_radar_slots(
    *,
    days_ahead: int | None = None,
) -> list[ScheduledPost]:
    """
    Crea slots diarios vacios para que el radar los prepare cerca de la publicacion.
    """
    if not settings.editorial_radar_enabled:
        return []

    horizon = max(days_ahead or settings.editorial_radar_days_ahead or 14, 1)
    now_local = datetime.now(MEXICO_CITY_TZ)
    now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledPost).where(
                ScheduledPost.scheduled_at.isnot(None),
                ScheduledPost.scheduled_at >= now_utc_naive - timedelta(days=1),
                ScheduledPost.status.in_(RADAR_ACTIVE_STATUSES),
            )
        )
        existing_posts = result.scalars().all()
        existing_slots = {
            post.scheduled_at.replace(microsecond=0)
            for post in existing_posts
            if post.scheduled_at
        }

        created: list[ScheduledPost] = []
        for offset in range(horizon):
            slot_date = now_local.date() + timedelta(days=offset)
            for hour in DAILY_SLOTS:
                slot_local = datetime.combine(
                    slot_date,
                    time(hour=hour, minute=0),
                    tzinfo=MEXICO_CITY_TZ,
                )
                if slot_local <= now_local:
                    continue
                slot_utc = slot_local.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)
                if slot_utc in existing_slots:
                    continue

                post = ScheduledPost(
                    tweet_url=f"radar://slot/{slot_local.isoformat()}",
                    tweet_text="Radar editorial pendiente",
                    tweet_author="Radar editorial",
                    linkedin_text="",
                    image_urls=[],
                    scheduled_at=slot_utc,
                    status=RADAR_SLOT_STATUS,
                    use_first_image=False,
                    media_type="none",
                    source=RADAR_SOURCE,
                )
                db.add(post)
                created.append(post)
                existing_slots.add(slot_utc)

        if created:
            await db.commit()
            for post in created:
                await db.refresh(post)
            logger.info("Radar: %s slots diarios creados", len(created))

        return created


async def list_active_radar_posts() -> list[ScheduledPost]:
    now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledPost)
            .where(ScheduledPost.source == RADAR_SOURCE)
            .where(ScheduledPost.status.in_((RADAR_SLOT_STATUS, RADAR_APPROVAL_STATUS)))
            .where(ScheduledPost.scheduled_at.isnot(None))
            .where(ScheduledPost.scheduled_at > now_utc_naive)
            .order_by(ScheduledPost.scheduled_at)
        )
        return result.scalars().all()
