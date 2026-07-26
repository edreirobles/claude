"""
Mantenimiento del calendario editorial.

Responsabilidades:
- Regenerar el texto de posts no publicados con el prompt vigente.
- Rellenar huecos del calendario con fuentes confiables y no repetidas.
- Reponer automáticamente un slot cuando una verificación cancele un post.
"""
from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal
from ..models import AppSettings, ScheduledPost
from .post_generator import (
    _compress_custom_prompt,
    generate_linkedin_post,
    generate_linkedin_post_from_url_content,
    rewrite_linkedin_post_with_storytelling,
)
from .post_verifier import (
    _build_source_summary,
    _fetch_source_snapshot,
    _normalize_source_url,
    verify_scheduled_post,
)
from .url_scraper import UrlContent, scrape_url
from .x_likes_monitor import DAILY_SLOTS
from .x_scraper import (
    arxiv_pdf_url,
    fetch_paper_info,
    is_arxiv_paper,
    normalize_tweet_url,
    scrape_tweet,
)

logger = logging.getLogger(__name__)

MONTERREY_TZ = ZoneInfo("America/Mexico_City")
ProgressCallback = Callable[[dict], None]
ACTIVE_POST_STATUSES = ("scheduled", "published", "pending", "failed")
RECYCLED_SOURCE_REJECT_PATTERNS = (
    "retract",
    "[no_publicar]",
    "pdf puro",
    "no tiene suficiente contexto web",
    "fuente descartada por criterio editorial vigente",
)
RECYCLED_SOURCE_BANNED_MARKERS = (
    "salkhanacademy",
)


REPLACEMENT_SOURCE_CATALOG: list[dict[str, str]] = [
    # Anthropic
    {"url": "https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents", "theme": "agents"},
    {"url": "https://www.anthropic.com/engineering/building-effective-agents", "theme": "agents"},
    {"url": "https://www.anthropic.com/engineering/claude-code-best-practices", "theme": "agents"},
    {"url": "https://www.anthropic.com/news/anthropic-education-report-how-university-students-use-claude", "theme": "education"},
    {"url": "https://www.anthropic.com/product/claude-code", "theme": "agents"},
    {"url": "https://docs.anthropic.com/en/docs/overview", "theme": "agents"},
    {"url": "https://docs.anthropic.com/en/docs/prompt-engineering", "theme": "prompting"},
    {"url": "https://docs.anthropic.com/en/api/prompt-tools-generate", "theme": "prompting"},
    {"url": "https://docs.anthropic.com/en/docs/build-with-claude/context-windows", "theme": "agents"},
    {"url": "https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking", "theme": "agents"},
    {"url": "https://docs.anthropic.com/en/docs/agents-and-tools/computer-use", "theme": "agents"},
    {"url": "https://docs.anthropic.com/en/docs/claude-code/overview", "theme": "agents"},
    {"url": "https://docs.anthropic.com/en/docs/claude-code/getting-started", "theme": "agents"},
    {"url": "https://docs.anthropic.com/en/docs/claude-code/data-usage", "theme": "agents"},
    {"url": "https://docs.anthropic.com/en/docs/claude-code/settings", "theme": "agents"},
    {"url": "https://docs.anthropic.com/en/docs/claude-code/sdk", "theme": "agents"},
    # OpenAI
    {"url": "https://developers.openai.com/api/docs/guides/text", "theme": "agents"},
    {"url": "https://developers.openai.com/api/docs/guides/reasoning", "theme": "agents"},
    {"url": "https://developers.openai.com/api/docs/guides/background", "theme": "agents"},
    {"url": "https://developers.openai.com/api/docs/guides/batch", "theme": "agents"},
    {"url": "https://developers.openai.com/api/docs/guides/structured-outputs", "theme": "prompting"},
    {"url": "https://developers.openai.com/api/docs/guides/tools-web-search", "theme": "agents"},
    {"url": "https://developers.openai.com/api/docs/guides/tools-code-interpreter", "theme": "agents"},
    {"url": "https://developers.openai.com/api/docs/guides/image-generation", "theme": "multimodal"},
    {"url": "https://developers.openai.com/api/docs/guides/images-vision", "theme": "multimodal"},
    {"url": "https://developers.openai.com/api/docs/guides/conversation-state", "theme": "agents"},
    {"url": "https://developers.openai.com/api/docs/guides/prompting", "theme": "prompting"},
    {"url": "https://developers.openai.com/api/docs/guides/evals", "theme": "agents"},
    {"url": "https://developers.openai.com/api/docs/guides/flex-processing", "theme": "agents"},
    {"url": "https://developers.openai.com/api/docs/models", "theme": "agents"},
    {"url": "https://developers.openai.com/api/docs/models/gpt-5-mini", "theme": "agents"},
    {"url": "https://platform.openai.com/docs/guides/migrate-to-responses", "theme": "agents"},
    {"url": "https://platform.openai.com/docs/guides/structured-outputs", "theme": "prompting"},
    {"url": "https://platform.openai.com/docs/guides/reasoning", "theme": "agents"},
    {"url": "https://platform.openai.com/docs/guides/reasoning-best-practices", "theme": "agents"},
    {"url": "https://platform.openai.com/docs/guides/background", "theme": "agents"},
    {"url": "https://platform.openai.com/docs/guides/batch/getting-started", "theme": "agents"},
    {"url": "https://platform.openai.com/docs/guides/prompt-generation", "theme": "prompting"},
    {"url": "https://platform.openai.com/docs/guides/tools-image-generation", "theme": "multimodal"},
    {"url": "https://platform.openai.com/docs/guides/images/image-generation", "theme": "multimodal"},
    {"url": "https://platform.openai.com/docs/guides/images-vision", "theme": "multimodal"},
    # Google / Gemini / NotebookLM
    {"url": "https://blog.google/innovation-and-ai/models-and-research/google-labs/notebooklm-video-overviews-studio-upgrades/", "theme": "multimodal"},
    {"url": "https://blog.google/technology/google-labs/notebook-lm-audio-video-overviews-more-languages-longer-content/", "theme": "multimodal"},
    {"url": "https://blog.google/innovation-and-ai/products/developing-notebooklm/", "theme": "multimodal"},
    {"url": "https://blog.google/technology/google-labs/notebooklm-custom-personas-engine-upgrade/", "theme": "multimodal"},
    {"url": "https://blog.google/innovation-and-ai/models-and-research/google-labs/notebooklm-featured-notebooks/", "theme": "multimodal"},
    {"url": "https://blog.google/innovation-and-ai/models-and-research/google-labs/notebooklm-studying-help/", "theme": "education"},
    {"url": "https://blog.google/innovation-and-ai/products/gemini-app/notebooks-gemini-notebooklm/", "theme": "multimodal"},
    {"url": "https://blog.google/products-and-platforms/products/education/ai-and-learning/", "theme": "education"},
    {"url": "https://blog.google/products-and-platforms/products/education/our-life-with-ai-2025/", "theme": "education"},
    {"url": "https://blog.google/products-and-platforms/products/education/google-for-education-year-in-review-2025/", "theme": "education"},
    {"url": "https://ai.google.dev/gemini-api/docs/text-generation", "theme": "agents"},
    {"url": "https://ai.google.dev/gemini-api/docs/document-processing", "theme": "multimodal"},
    {"url": "https://ai.google.dev/gemini-api/docs/image-generation", "theme": "multimodal"},
    # UNESCO / OECD
    {"url": "https://www.unesco.org/en/articles/guidance-generative-ai-education-and-research", "theme": "education"},
    {"url": "https://www.unesco.org/en/articles/ai-and-education-protecting-rights-learners?hub=83250", "theme": "education"},
    {"url": "https://www.unesco.org/en/education/digital/artificial-intelligence", "theme": "education"},
    {"url": "https://www.unesco.org/en/articles/artificial-intelligence-education-unesco-advances-key-competencies-teachers-and-learners", "theme": "education"},
    {"url": "https://www.unesco.org/en/articles/artificial-intelligence-and-its-role-education-policies", "theme": "education"},
    {"url": "https://www.unesco.org/en/articles/ai-and-future-education-disruptions-dilemmas-and-directions-0?hub=343", "theme": "education"},
    {"url": "https://www.unesco.org/en/articles/unesco-dedicates-international-day-education-2025-artificial-intelligence", "theme": "education"},
    {"url": "https://www.unesco.org/en/articles/ai-and-futures-education", "theme": "education"},
    {"url": "https://www.unesco.org/en/node/217106", "theme": "education"},
    {"url": "https://www.unesco.org/en/artificial-intelligence", "theme": "education"},
    {"url": "https://www.oecd.org/digital/artificial-intelligence/", "theme": "education"},
    # McKinsey
    {"url": "https://www.mckinsey.com/capabilities/mckinsey-digital/our-insights/unleashing-developer-productivity-with-generative-ai", "theme": "agents"},
    {"url": "https://www.mckinsey.com/industries/technology-media-and-telecommunications/our-insights/how-generative-ai-could-accelerate-software-product-time-to-market", "theme": "agents"},
    {"url": "https://www.mckinsey.com/industries/technology-media-and-telecommunications/our-insights/how-an-ai-enabled-software-product-development-life-cycle-will-fuel-innovation", "theme": "agents"},
    {"url": "https://www.mckinsey.com/capabilities/risk-and-resilience/our-insights/implementing-generative-ai-with-speed-and-safety/", "theme": "agents"},
    {"url": "https://www.mckinsey.com/capabilities/tech-and-ai/our-insights/a-generative-ai-reset-rewiring-to-turn-potential-into-value-in-2024", "theme": "agents"},
    {"url": "https://www.mckinsey.com/capabilities/mckinsey-digital/our-insights/the-gen-ai-skills-revolution-rethinking-your-talent-strategy", "theme": "agents"},
    {"url": "https://www.mckinsey.com/capabilities/mckinsey-digital/our-insights/the-economic-potential-of-generative-ai-the-next-productivity-frontier", "theme": "agents"},
    {"url": "https://www.mckinsey.com/about-us/new-at-mckinsey-blog/generative-ai-can-give-you-superpowers-new-mckinsey-research-finds", "theme": "agents"},
    # Academic / Nature
    {"url": "https://www.nature.com/articles/d41586-024-03588-8", "theme": "research"},
    {"url": "https://www.nature.com/articles/s44159-025-00416-2", "theme": "research"},
    {"url": "https://www.nature.com/articles/s44286-026-00387-y", "theme": "research"},
    {"url": "https://www.nature.com/articles/s41598-025-97652-6", "theme": "education"},
    {"url": "https://www.nature.com/articles/s41539-025-00320-7", "theme": "education"},
    {"url": "https://www.nature.com/articles/s41598-025-95802-4", "theme": "education"},
    {"url": "https://www.nature.com/articles/s41539-024-00293-z", "theme": "education"},
    {"url": "https://www.nature.com/articles/s41599-025-05817-5", "theme": "education"},
    {"url": "https://www.nature.com/articles/s41598-025-25996-0", "theme": "education"},
    {"url": "https://www.nature.com/articles/s41598-025-19851-5", "theme": "education"},
    {"url": "https://www.nature.com/articles/s41598-025-19118-z", "theme": "education"},
    {"url": "https://www.nature.com/articles/s41598-025-21205-0", "theme": "education"},
    {"url": "https://www.nature.com/articles/s41599-025-04583-8", "theme": "education"},
    {"url": "https://www.nature.com/articles/s41599-025-04787-y", "theme": "education"},
    {"url": "https://www.nature.com/articles/s41598-026-35823-9", "theme": "education"},
    {"url": "https://www.nature.com/articles/s41598-025-24841-8", "theme": "education"},
    {"url": "https://www.nature.com/articles/s41599-025-06362-x", "theme": "education"},
    {"url": "https://www.nature.com/articles/s41599-026-06583-8", "theme": "education"},
    {"url": "https://www.nature.com/articles/s41599-026-06981-y", "theme": "education"},
    {"url": "https://www.nature.com/articles/s41598-026-48656-3", "theme": "education"},
    {"url": "https://arxiv.org/abs/2512.20780", "theme": "education"},
    {"url": "https://arxiv.org/abs/2510.13862", "theme": "education"},
    {"url": "https://arxiv.org/abs/2512.23036", "theme": "education"},
    {"url": "https://arxiv.org/abs/2403.15586", "theme": "education"},
    # Additional Google / OpenAI pages
    {"url": "https://blog.research.google/2023/08/responsible-ai-at-google-research.html", "theme": "education"},
    {"url": "https://blog.google/technology/ai/ai-tips-2025/", "theme": "multimodal"},
    {"url": "https://platform.openai.com/docs/guides/tools-web-search", "theme": "agents"},
    {"url": "https://platform.openai.com/docs/guides/tools-code-interpreter", "theme": "agents"},
]


def _default_backfill_end_date(today_local: date | None = None) -> date:
    base = today_local or datetime.now(MONTERREY_TZ).date()
    year = base.year
    month = base.month + 1
    if month == 13:
        month = 1
        year += 1
    return date(year, month, monthrange(year, month)[1])


async def _load_custom_prompt(db: AsyncSession) -> str | None:
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    cfg = result.scalar_one_or_none()
    return cfg.custom_prompt if cfg else None


def _is_x_url(url: str) -> bool:
    lowered = (url or "").lower()
    return "x.com/" in lowered or "twitter.com/" in lowered


def _is_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def _document_title_from_url(url: str) -> str:
    filename = urlparse(url).path.rsplit("/", 1)[-1].strip() or "Documento"
    return filename[:500]


def _coerce_slot_utc(run_at: datetime) -> datetime:
    if run_at.tzinfo is None:
        return run_at
    return run_at.astimezone(timezone.utc).replace(tzinfo=None)


def _generate_candidate_slots(
    *,
    start_after_local: datetime,
    end_date_local: date,
) -> list[datetime]:
    slots: list[datetime] = []
    cursor = start_after_local.date()

    while cursor <= end_date_local:
        for hour in DAILY_SLOTS:
            slot_local = datetime.combine(cursor, time(hour=hour, minute=0), tzinfo=MONTERREY_TZ)
            if slot_local <= start_after_local:
                continue
            slots.append(slot_local.astimezone(timezone.utc).replace(tzinfo=None))
        cursor += timedelta(days=1)

    return slots


async def _existing_normalized_sources(db: AsyncSession) -> set[str]:
    result = await db.execute(
        select(ScheduledPost.tweet_url).where(
            ScheduledPost.tweet_url.isnot(None),
            ScheduledPost.status.in_(ACTIVE_POST_STATUSES),
        )
    )
    urls = [row[0] for row in result.all() if row[0]]
    return {_normalize_source_url(url) for url in urls if url}


async def _load_reusable_cancelled_sources(
    db: AsyncSession,
    *,
    used_sources: set[str],
) -> list[dict[str, str]]:
    result = await db.execute(
        select(ScheduledPost.tweet_url, ScheduledPost.error_message)
        .where(
            ScheduledPost.status == "cancelled",
            ScheduledPost.tweet_url.isnot(None),
        )
        .order_by(ScheduledPost.scheduled_at, ScheduledPost.id)
    )

    reusable: list[dict[str, str]] = []
    seen: set[str] = set()
    for tweet_url, error_message in result.all():
        normalized = _normalize_source_url(tweet_url or "")
        if not normalized or normalized in used_sources or normalized in seen:
            continue

        lowered_url = normalized.lower()
        if any(marker in lowered_url for marker in RECYCLED_SOURCE_BANNED_MARKERS):
            continue

        lowered_error = (error_message or "").lower()
        if any(pattern in lowered_error for pattern in RECYCLED_SOURCE_REJECT_PATTERNS):
            continue

        if lowered_url.endswith(".pdf"):
            continue

        theme = "education"
        if any(marker in lowered_url for marker in ("openai", "anthropic", "claude", "gemini", "notebooklm", "code", "agent")):
            theme = "agents"
        if any(marker in lowered_url for marker in ("nature.com", "arxiv.org")):
            theme = "research"
        if any(marker in lowered_url for marker in ("image", "video", "audio", "vision")):
            theme = "multimodal"

        reusable.append({"url": tweet_url, "theme": theme})
        seen.add(normalized)

    return reusable


async def _build_post_payload_from_source(
    *,
    source_url: str,
    custom_prompt: str | None,
    language: str = "es",
    editorial_context: str | None = None,
) -> dict:
    if _is_x_url(source_url):
        normalized_url = normalize_tweet_url(source_url)
        tweet = await scrape_tweet(normalized_url)
        linkedin_text = await generate_linkedin_post(
            tweet=tweet,
            language=language,
            custom_prompt=custom_prompt,
            editorial_context=editorial_context,
        )
        if linkedin_text.strip().startswith("[NO_PUBLICAR]:"):
            raise ValueError(linkedin_text.strip())

        if is_arxiv_paper(tweet.paper_info) and tweet.pdf_url:
            media_type = "paper_image"
        elif tweet.has_video:
            media_type = "video"
        elif tweet.pdf_url:
            media_type = "document"
        elif tweet.images:
            media_type = "image"
        else:
            media_type = "none"

        return {
            "tweet_url": normalized_url,
            "tweet_text": tweet.text,
            "tweet_author": tweet.author_name or tweet.author_handle or "",
            "linkedin_text": linkedin_text,
            "image_urls": tweet.images[:4],
            "use_first_image": True,
            "media_type": media_type,
            "pdf_url": tweet.pdf_url,
            "document_title": (
                tweet.paper_info.get("title", "Documento")
                if tweet.paper_info else (_document_title_from_url(tweet.pdf_url) if tweet.pdf_url else "Documento")
            ),
        }

    if _is_pdf_url(source_url):
        raise ValueError("La fuente es PDF puro y no tiene suficiente contexto web para regenerar con calidad")

    paper_info = None
    pdf_url = arxiv_pdf_url(source_url)
    if pdf_url:
        paper_info = await fetch_paper_info(source_url)

    if paper_info:
        content = UrlContent(
            url=source_url,
            title=paper_info.get("title", ""),
            text=paper_info.get("abstract", ""),
            author=", ".join(paper_info.get("authors", [])[:3]),
            images=[],
            source_domain="arxiv.org",
        )
    else:
        content = await scrape_url(source_url)
    linkedin_text = await generate_linkedin_post_from_url_content(
        url_content=content,
        language=language,
        custom_prompt=custom_prompt,
        editorial_context=editorial_context,
    )
    if linkedin_text.strip().startswith("[NO_PUBLICAR]:"):
        raise ValueError(linkedin_text.strip())

    media_type = "paper_image" if paper_info and pdf_url else ("image" if content.images else "none")
    return {
        "tweet_url": source_url,
        "tweet_text": content.title or content.text[:500],
        "tweet_author": content.author or content.source_domain or "",
        "linkedin_text": linkedin_text,
        "image_urls": content.images[:4],
        "use_first_image": media_type == "image",
        "media_type": media_type,
        "pdf_url": pdf_url,
        "document_title": paper_info.get("title", "Documento") if paper_info else "Documento",
    }


def _matches_banned_editorial_pattern(post: ScheduledPost, banned_patterns: tuple[str, ...]) -> bool:
    if not banned_patterns:
        return False
    haystack = " ".join(
        part for part in (
            post.tweet_url or "",
            post.tweet_text or "",
            post.tweet_author or "",
            post.linkedin_text or "",
        ) if part
    ).lower()
    return any(pattern.lower() in haystack for pattern in banned_patterns)


async def regenerate_unpublished_posts(
    *,
    progress_callback: ProgressCallback | None = None,
    language: str = "es",
) -> dict:
    """
    Regenera el texto de los posts no publicados usando el prompt actual.
    """
    from .scheduler_service import cancel_scheduled_post

    counts = {
        "processed": 0,
        "text_refreshed": 0,
        "updated": 0,
        "verified": 0,
        "cancelled": 0,
        "failed": 0,
        "total": 0,
    }

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledPost)
            .where(ScheduledPost.status.in_(("scheduled", "pending")))
            .order_by(ScheduledPost.scheduled_at, ScheduledPost.id)
        )
        posts = result.scalars().all()
        counts["total"] = len(posts)
        custom_prompt = await _load_custom_prompt(db)
        custom_prompt_brief = _compress_custom_prompt(custom_prompt)

        for index, post in enumerate(posts, start=1):
            try:
                payload = await _build_post_payload_from_source(
                    source_url=post.tweet_url,
                    custom_prompt=custom_prompt,
                    language=language,
                )
                post.linkedin_text = payload["linkedin_text"]
                post.error_message = None
                if (post.media_type or "").strip().lower() == "generate":
                    # Si el texto cambió, la imagen generada vieja deja de ser confiable.
                    post.media_type = "none"
                    post.generated_image_path = None
                await db.commit()
                counts["text_refreshed"] += 1

                outcome = await verify_scheduled_post(post.id, db)
                action = outcome.get("action")
                if action == "cancelled":
                    counts["cancelled"] += 1
                    cancel_scheduled_post(post.id)
                elif action == "updated":
                    counts["updated"] += 1
                else:
                    counts["verified"] += 1

            except Exception as exc:
                logger.warning("No se pudo regenerar el post %s: %s", post.id, exc)
                counts["failed"] += 1
                post.status = "cancelled"
                post.error_message = f"Cancelado durante regeneración con prompt vigente: {exc}"
                await db.commit()
                cancel_scheduled_post(post.id)
                counts["cancelled"] += 1

            counts["processed"] = index
            if progress_callback:
                progress_callback(
                    {
                        "phase": "regenerating",
                        "message": f"Regenerando textos: {index}/{len(posts)}",
                        **counts,
                    }
                )

    return counts


async def rebuild_future_scheduled_posts(
    *,
    start_date_local: date | None = None,
    progress_callback: ProgressCallback | None = None,
    language: str = "es",
    banned_patterns: tuple[str, ...] = (),
) -> dict:
    """
    Rehace los posts programados a partir de una fecha local, conservando sus slots.
    Si un post falla o cae por criterio editorial, cancela y repone ese slot.
    """
    from .scheduler_service import cancel_scheduled_post, schedule_post

    counts = {
        "processed": 0,
        "rewritten": 0,
        "updated": 0,
        "verified": 0,
        "cancelled": 0,
        "replaced": 0,
        "failed": 0,
        "total": 0,
    }

    start_local = start_date_local or (datetime.now(MONTERREY_TZ).date() + timedelta(days=1))
    threshold_local = datetime.combine(start_local, time.min, tzinfo=MONTERREY_TZ)
    threshold_utc = threshold_local.astimezone(timezone.utc).replace(tzinfo=None)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledPost)
            .where(
                ScheduledPost.status == "scheduled",
                ScheduledPost.scheduled_at.isnot(None),
                ScheduledPost.scheduled_at >= threshold_utc,
            )
            .order_by(ScheduledPost.scheduled_at, ScheduledPost.id)
        )
        posts = result.scalars().all()
        counts["total"] = len(posts)
        custom_prompt = await _load_custom_prompt(db)
        custom_prompt_brief = _compress_custom_prompt(custom_prompt)

        for index, post in enumerate(posts, start=1):
            slot = post.scheduled_at
            try:
                if _matches_banned_editorial_pattern(post, banned_patterns):
                    raise ValueError("fuente descartada por criterio editorial vigente")

                source_url = _normalize_source_url(post.tweet_url or "")
                snapshot = await _fetch_source_snapshot(source_url)
                source_summary = _build_source_summary(snapshot)
                rewritten = await rewrite_linkedin_post_with_storytelling(
                    original_post=post.linkedin_text or "",
                    source_summary=source_summary,
                    source_url=source_url,
                    language=language,
                    custom_prompt=custom_prompt_brief,
                )
                rewritten = (rewritten or "").strip()
                if rewritten.startswith("[CANCELAR]:"):
                    reason = rewritten.split(":", 1)[1].strip() if ":" in rewritten else rewritten
                    raise ValueError(reason or "copy cancelado por revisión editorial")

                post.linkedin_text = rewritten
                if (post.media_type or "").strip().lower() == "generate":
                    post.media_type = "none"
                    post.generated_image_path = None
                post.error_message = None

                await db.commit()
                if slot:
                    schedule_post(post.id, slot)
                counts["rewritten"] += 1

                outcome = await verify_scheduled_post(post.id, db)
                action = outcome.get("action")
                if action == "cancelled":
                    counts["cancelled"] += 1
                    cancel_scheduled_post(post.id)
                    replacement = await replace_cancelled_post(post.id)
                    counts["replaced"] += replacement.get("replaced", 0)
                elif action == "updated":
                    counts["updated"] += 1
                else:
                    counts["verified"] += 1

            except Exception as exc:
                logger.warning("No se pudo rehacer el post %s: %s", post.id, exc)
                counts["failed"] += 1
                post.status = "cancelled"
                post.error_message = f"Cancelado durante reconstrucción editorial: {exc}"
                await db.commit()
                if slot:
                    cancel_scheduled_post(post.id)
                replacement = await replace_cancelled_post(post.id)
                counts["cancelled"] += 1
                counts["replaced"] += replacement.get("replaced", 0)

            counts["processed"] = index
            if progress_callback:
                progress_callback(
                    {
                        "phase": "rebuilding_future",
                        "message": f"Rehaciendo calendario futuro: {index}/{len(posts)}",
                        **counts,
                    }
                )

        if posts:
            last_local_date = posts[-1].scheduled_at.replace(tzinfo=timezone.utc).astimezone(MONTERREY_TZ).date()
            top_up = await backfill_calendar(
                end_date_local=last_local_date,
                progress_callback=progress_callback,
                language=language,
            )
            counts["replaced"] += top_up.get("filled_slots", 0)

    return counts


async def backfill_calendar(
    *,
    end_date_local: date | None = None,
    preferred_slots: list[datetime] | None = None,
    progress_callback: ProgressCallback | None = None,
    language: str = "es",
) -> dict:
    """
    Rellena slots faltantes con nuevas publicaciones generadas desde un catálogo curado.
    """
    from .scheduler_service import cancel_scheduled_post, schedule_post

    counts = {
        "processed_sources": 0,
        "created": 0,
        "verified": 0,
        "updated": 0,
        "cancelled": 0,
        "failed_sources": 0,
        "filled_slots": 0,
        "target_slots": 0,
        "remaining_slots": 0,
    }

    async with AsyncSessionLocal() as db:
        custom_prompt = await _load_custom_prompt(db)
        used_sources = await _existing_normalized_sources(db)
        supplemental_sources = await _load_reusable_cancelled_sources(
            db,
            used_sources=used_sources,
        )
        candidate_sources = REPLACEMENT_SOURCE_CATALOG + supplemental_sources

        if preferred_slots:
            raw_slots = [_coerce_slot_utc(slot) for slot in preferred_slots]
            target_slots = [slot for slot in raw_slots if slot > datetime.utcnow()]
        else:
            local_now = datetime.now(MONTERREY_TZ)
            final_date = end_date_local or _default_backfill_end_date(local_now.date())
            candidate_slots = _generate_candidate_slots(
                start_after_local=local_now,
                end_date_local=final_date,
            )
            result = await db.execute(
                select(ScheduledPost.scheduled_at).where(
                    ScheduledPost.status == "scheduled",
                    ScheduledPost.scheduled_at.isnot(None),
                    ScheduledPost.scheduled_at <= datetime.combine(
                        final_date,
                        time.max,
                    ),
                )
            )
            taken_slots = {row[0] for row in result.all() if row[0]}
            target_slots = [slot for slot in candidate_slots if slot not in taken_slots]

        counts["target_slots"] = len(target_slots)
        slot_index = 0

        for source in candidate_sources:
            if slot_index >= len(target_slots):
                break

            source_url = source["url"].strip()
            normalized_source = _normalize_source_url(source_url)
            if not normalized_source or normalized_source in used_sources:
                continue

            counts["processed_sources"] += 1
            slot = target_slots[slot_index]

            try:
                payload = await _build_post_payload_from_source(
                    source_url=source_url,
                    custom_prompt=custom_prompt,
                    language=language,
                )
                post = ScheduledPost(
                    tweet_url=payload["tweet_url"],
                    tweet_text=payload["tweet_text"],
                    tweet_author=payload["tweet_author"],
                    linkedin_text=payload["linkedin_text"],
                    image_urls=payload["image_urls"],
                    scheduled_at=slot,
                    status="scheduled",
                    use_first_image=payload["use_first_image"],
                    media_type=payload["media_type"],
                    pdf_url=payload["pdf_url"],
                    document_title=payload["document_title"],
                    source="manual",
                )
                db.add(post)
                await db.commit()
                await db.refresh(post)
                schedule_post(post.id, slot)
                counts["created"] += 1

                outcome = await verify_scheduled_post(post.id, db)
                action = outcome.get("action")
                if action == "cancelled":
                    counts["cancelled"] += 1
                    cancel_scheduled_post(post.id)
                    continue
                if action == "updated":
                    counts["updated"] += 1
                else:
                    counts["verified"] += 1

                used_sources.add(normalized_source)
                counts["filled_slots"] += 1
                slot_index += 1

            except Exception as exc:
                logger.warning("Fuente descartada para backfill (%s): %s", source_url, exc)
                counts["failed_sources"] += 1

            counts["remaining_slots"] = max(0, len(target_slots) - slot_index)
            if progress_callback:
                progress_callback(
                    {
                        "phase": "backfilling",
                        "message": (
                            f"Rellenando calendario: {counts['filled_slots']}/{len(target_slots)} "
                            "slots cubiertos"
                        ),
                        **counts,
                    }
                )

    counts["remaining_slots"] = max(0, counts["target_slots"] - counts["filled_slots"])
    return counts


async def replace_cancelled_post(post_id: int) -> dict:
    """
    Intenta reponer el slot de un post cancelado. Si ya venció, rellena el siguiente hueco futuro.
    """
    async with AsyncSessionLocal() as db:
        post = await db.get(ScheduledPost, post_id)
        if not post:
            return {"replaced": 0, "reason": "post no encontrado"}

        preferred_slots: list[datetime] | None = None
        if post.scheduled_at and post.scheduled_at > datetime.utcnow():
            preferred_slots = [post.scheduled_at]

    result = await backfill_calendar(preferred_slots=preferred_slots)
    return {
        "replaced": result.get("filled_slots", 0),
        "target_slots": result.get("target_slots", 0),
        "remaining_slots": result.get("remaining_slots", 0),
    }


async def rebuild_calendar_with_current_prompt(
    *,
    progress_callback: ProgressCallback | None = None,
    language: str = "es",
    end_date_local: date | None = None,
) -> dict:
    """
    Orquesta:
    1. Regenerar texto de lo no publicado con el prompt actual.
    2. Rellenar el calendario hasta el final del próximo mes.
    """
    regen = await regenerate_unpublished_posts(
        progress_callback=progress_callback,
        language=language,
    )
    backfill = await backfill_calendar(
        end_date_local=end_date_local,
        progress_callback=progress_callback,
        language=language,
    )
    return {
        "regeneration": regen,
        "backfill": backfill,
    }
