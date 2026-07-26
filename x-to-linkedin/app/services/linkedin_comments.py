from __future__ import annotations

import logging
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from ..config import get_settings
from ..database import AsyncSessionLocal
from ..models import AppSettings, LinkedInComment, ScheduledPost
from .linkedin_auth import LinkedInAuthError, get_linkedin_client_from_db
from .post_generator import generate_linkedin_comment_reply

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class ScrapedComment:
    comment_urn: str
    object_urn: str
    commenter_name: str
    commenter_profile_url: str
    commenter_headline: str
    comment_text: str
    comment_age_label: str
    parent_comment_urn: str | None = None


def _cookie_header() -> dict[str, str]:
    raw_jid = settings.linkedin_jsessionid.strip('"') if settings.linkedin_jsessionid else ""
    cookie = ""
    if settings.linkedin_li_at:
        cookie = f"li_at={settings.linkedin_li_at}"
    if raw_jid:
        cookie += f'; JSESSIONID="{raw_jid}"' if cookie else f'JSESSIONID="{raw_jid}"'

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
        "Referer": "https://www.linkedin.com/feed/",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _build_feed_update_url(post_urn: str) -> str:
    encoded = urllib.parse.quote((post_urn or "").strip(), safe="")
    return f"https://www.linkedin.com/feed/update/{encoded}/"


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _extract_owner_name(soup: BeautifulSoup) -> str:
    h1 = soup.select_one("h1")
    title = _clean_text(h1.get_text(" ", strip=True) if h1 else "")
    if not title:
        return ""
    suffixes = (
        "’s Post",
        "'s Post",
        " post",
        " publicación",
    )
    for suffix in suffixes:
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    if title.lower().startswith("publicación de "):
        return title[len("publicación de "):].strip()
    return title


def _extract_public_post_url(soup: BeautifulSoup, fallback_url: str) -> str:
    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        return canonical["href"]
    meta = soup.find("meta", attrs={"property": "og:url"})
    if meta and meta.get("content"):
        return meta["content"]
    return fallback_url


def _activity_urn_from_comment_urn(comment_urn: str) -> str:
    match = re.match(r"urn:li:comment:\((urn:li:activity:[^,]+),", comment_urn or "")
    return match.group(1) if match else ""


def _fallback_reply(comment_text: str) -> dict[str, str]:
    lowered = (comment_text or "").lower()
    critical_markers = ("no ", "nunca", "pero", "aunque", "riesgo", "problema", "qué pasará", "que pasará")
    if any(marker in lowered for marker in critical_markers):
        return {
            "stance": "critical",
            "reply": "Sí te compro esa parte. Yo lo veo más como una ayuda para pensar mejor, no como atajo para dejar de pensar.",
        }
    return {
        "stance": "supportive",
        "reply": "Sí, justo por ahí va. Lo bueno empieza cuando esto no solo ahorra tiempo, sino que te deja ver cosas que antes ni estabas mirando.",
    }


def _looks_like_tag_only_comment(comment_text: str) -> bool:
    cleaned = re.sub(r"\s+", " ", (comment_text or "").strip())
    cleaned = re.sub(r"[\U00010000-\U0010ffff]", " ", cleaned)
    cleaned = re.sub(r"[^\wÁÉÍÓÚáéíóúÑñüÜ@.\-'\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.strip(".,;:!?¡¿()[]{}")
    if not cleaned:
        return True

    if re.fullmatch(r"(?:@[\w.\-]+(?:\s+|$)){1,5}", cleaned):
        return True

    tokens = cleaned.split()
    if not (1 <= len(tokens) <= 12 and len(cleaned) <= 120):
        return False

    connector_tokens = {"de", "del", "la", "las", "los", "y"}
    for token in tokens:
        if token.lower() in connector_tokens:
            continue
        if re.fullmatch(r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:[-'][A-ZÁÉÍÓÚÑa-záéíóúñ]+)?", token):
            continue
        if re.fullmatch(r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ]*\.?", token):
            continue
        return False
    return True


def _parse_visible_comments(html: str, fallback_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    owner_name = _extract_owner_name(soup)
    public_post_url = _extract_public_post_url(soup, fallback_url)

    comments: list[ScrapedComment] = []
    seen: set[str] = set()

    for anchor in soup.select("a[data-semaphore-content-urn]"):
        comment_urn = (anchor.get("data-semaphore-content-urn") or "").strip()
        if not comment_urn.startswith("urn:li:comment:"):
            continue
        if comment_urn in seen:
            continue

        section = anchor.find_parent("section")
        if not section:
            continue

        author_el = section.select_one(".comment__author")
        text_el = section.select_one(".comment__text")
        if not author_el or not text_el:
            continue

        seen.add(comment_urn)
        comments.append(
            ScrapedComment(
                comment_urn=comment_urn,
                object_urn=_activity_urn_from_comment_urn(comment_urn),
                commenter_name=_clean_text(author_el.get_text(" ", strip=True)),
                commenter_profile_url=(author_el.get("href") or "").strip(),
                commenter_headline=_clean_text(
                    section.select_one(".comment__author-headline").get_text(" ", strip=True)
                    if section.select_one(".comment__author-headline")
                    else ""
                ),
                comment_text=_clean_text(text_el.get_text(" ", strip=True)),
                comment_age_label=_clean_text(
                    section.select_one(".comment__duration-since").get_text(" ", strip=True)
                    if section.select_one(".comment__duration-since")
                    else ""
                ),
            )
        )

    return {
        "owner_name": owner_name,
        "public_post_url": public_post_url,
        "comments": comments,
    }


async def fetch_visible_post_comments(post_urn: str) -> dict:
    page_url = _build_feed_update_url(post_urn)
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(page_url, headers=_cookie_header())
        response.raise_for_status()
    return _parse_visible_comments(response.text, page_url)


async def _load_custom_prompt(db) -> str | None:
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    settings_row = result.scalar_one_or_none()
    return settings_row.custom_prompt if settings_row else None


async def _notify_new_comment(comment: LinkedInComment, post: ScheduledPost):
    from .telegram_bot import notify_new_linkedin_comment

    return await notify_new_linkedin_comment(
        comment_id=comment.id,
        post_id=post.id,
        commenter_name=comment.commenter_name,
        comment_text=comment.comment_text,
        suggested_reply=comment.suggested_reply or "",
        post_url=comment.post_public_url or "",
        post_preview=(post.linkedin_text or "")[:240],
    )


async def _notify_comment_gap(post: ScheduledPost, *, visible_count: int, total_count: int, unseen_count: int):
    from .telegram_bot import notify_linkedin_comment_gap

    await notify_linkedin_comment_gap(
        post_id=post.id,
        total_count=total_count,
        visible_count=visible_count,
        unseen_count=unseen_count,
        post_url=_build_feed_update_url(post.linkedin_post_id or ""),
        post_preview=(post.linkedin_text or "")[:240],
    )


async def scan_linkedin_comments(
    *,
    notify: bool = True,
    days: Optional[int] = None,
    only_post_ids: Optional[list[int]] = None,
    refresh_totals: bool = False,
) -> dict:
    lookback_days = days or settings.linkedin_comment_monitor_days
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    stats = {
        "scanned_posts": 0,
        "new_comments": 0,
        "manual_review_alerts": 0,
        "errors": 0,
    }

    async with AsyncSessionLocal() as db:
        custom_prompt = await _load_custom_prompt(db)

        li_client = None
        if refresh_totals:
            try:
                li_client = await get_linkedin_client_from_db(db)
            except LinkedInAuthError as exc:
                logger.info(
                    "LinkedIn comments scan seguirá sin refrescar totales porque LinkedIn requiere reconexión: %s",
                    exc,
                )
                li_client = None

        query = (
            select(ScheduledPost)
            .where(ScheduledPost.status == "published")
            .where(ScheduledPost.linkedin_post_id.isnot(None))
            .where(ScheduledPost.linkedin_post_id != "")
        )
        if only_post_ids:
            query = query.where(ScheduledPost.id.in_(only_post_ids))
        else:
            query = query.where(ScheduledPost.published_at >= cutoff)
        query = query.order_by(ScheduledPost.published_at.desc())

        result = await db.execute(query)
        posts = result.scalars().all()

        for post in posts:
            stats["scanned_posts"] += 1
            previous_total = post.li_comments or 0
            current_total = previous_total

            if li_client:
                try:
                    metrics = await li_client.get_post_metrics(post.linkedin_post_id or "")
                    if metrics.get("comments") is not None:
                        current_total = int(metrics["comments"])
                        post.li_comments = current_total
                        post.metrics_updated_at = datetime.utcnow()
                except Exception as exc:
                    logger.warning("No se pudieron refrescar comentarios del post %s: %s", post.id, exc)

            try:
                scraped = await fetch_visible_post_comments(post.linkedin_post_id or "")
            except Exception as exc:
                stats["errors"] += 1
                logger.warning("No se pudieron leer comentarios visibles del post %s: %s", post.id, exc)
                await db.commit()
                continue

            owner_name = (scraped.get("owner_name") or "").strip().lower()
            public_post_url = scraped.get("public_post_url") or _build_feed_update_url(post.linkedin_post_id or "")
            visible_comments: list[ScrapedComment] = scraped.get("comments", [])

            existing_result = await db.execute(
                select(LinkedInComment).where(LinkedInComment.linkedin_post_urn == (post.linkedin_post_id or ""))
            )
            existing_rows = existing_result.scalars().all()
            existing_by_urn = {row.linkedin_comment_urn: row for row in existing_rows}

            created_rows: list[LinkedInComment] = []
            for comment in visible_comments:
                commenter_name = (comment.commenter_name or "").strip()
                if not commenter_name or not comment.comment_text:
                    continue
                if commenter_name.lower() == owner_name:
                    continue
                if _looks_like_tag_only_comment(comment.comment_text):
                    logger.info(
                        "Saltando comentario %s en post %s porque parece solo un tag a otra persona",
                        comment.comment_urn,
                        post.id,
                    )
                    continue
                if comment.comment_urn in existing_by_urn:
                    row = existing_by_urn[comment.comment_urn]
                    if not row.post_public_url and public_post_url:
                        row.post_public_url = public_post_url
                    continue

                try:
                    suggestion = await generate_linkedin_comment_reply(
                        post_text=post.linkedin_text or "",
                        comment_text=comment.comment_text,
                        custom_prompt=custom_prompt,
                    )
                except Exception as exc:
                    logger.warning(
                        "No se pudo generar sugerencia para comentario %s en post %s: %s",
                        comment.comment_urn,
                        post.id,
                        exc,
                    )
                    suggestion = _fallback_reply(comment.comment_text)
                if not (suggestion.get("reply") or "").strip():
                    suggestion = _fallback_reply(comment.comment_text)
                row = LinkedInComment(
                    scheduled_post_id=post.id,
                    linkedin_post_urn=post.linkedin_post_id or "",
                    linkedin_object_urn=comment.object_urn,
                    linkedin_comment_urn=comment.comment_urn,
                    parent_comment_urn=comment.parent_comment_urn,
                    commenter_name=comment.commenter_name,
                    commenter_profile_url=comment.commenter_profile_url,
                    commenter_headline=comment.commenter_headline,
                    comment_text=comment.comment_text,
                    comment_age_label=comment.comment_age_label,
                    post_public_url=public_post_url,
                    suggested_reply=suggestion.get("reply") or "",
                    reply_status="pending",
                    raw_payload={
                        "stance": suggestion.get("stance", "neutral"),
                        "source": "public_post_html",
                    },
                )
                db.add(row)
                await db.flush()
                created_rows.append(row)
                existing_by_urn[row.linkedin_comment_urn] = row
                stats["new_comments"] += 1

            await db.commit()

            if notify:
                for row in created_rows:
                    try:
                        message_id = await _notify_new_comment(row, post)
                        async with AsyncSessionLocal() as notify_db:
                            result = await notify_db.execute(
                                select(LinkedInComment).where(LinkedInComment.id == row.id)
                            )
                            fresh_row = result.scalar_one_or_none()
                            if fresh_row:
                                fresh_row.last_notified_at = datetime.utcnow()
                                fresh_row.telegram_message_id = message_id
                                await notify_db.commit()
                    except Exception as exc:
                        logger.warning("No se pudo notificar comentario %s: %s", row.id, exc)

            visible_known_count = len(existing_by_urn)
            delta_total = max(current_total - previous_total, 0)
            if (
                notify
                and delta_total > 0
                and visible_known_count < current_total
                and len(created_rows) < delta_total
            ):
                unseen_count = current_total - visible_known_count
                try:
                    await _notify_comment_gap(
                        post,
                        visible_count=visible_known_count,
                        total_count=current_total,
                        unseen_count=unseen_count,
                    )
                    stats["manual_review_alerts"] += 1
                except Exception as exc:
                    logger.warning("No se pudo notificar gap de comentarios del post %s: %s", post.id, exc)

    return stats


async def update_comment_suggested_reply(comment_id: int, reply_text: str) -> LinkedInComment | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(LinkedInComment).where(LinkedInComment.id == comment_id))
        comment = result.scalar_one_or_none()
        if not comment:
            return None
        comment.suggested_reply = reply_text.strip()
        comment.reply_status = "pending"
        comment.error_message = None
        await db.commit()
        await db.refresh(comment)
        return comment


async def dismiss_comment_reply(comment_id: int) -> LinkedInComment | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(LinkedInComment).where(LinkedInComment.id == comment_id))
        comment = result.scalar_one_or_none()
        if not comment:
            return None
        comment.reply_status = "dismissed"
        await db.commit()
        await db.refresh(comment)
        return comment


async def publish_comment_reply(comment_id: int, reply_text: str | None = None) -> dict:
    async with AsyncSessionLocal() as db:
        comment_result = await db.execute(select(LinkedInComment).where(LinkedInComment.id == comment_id))
        comment = comment_result.scalar_one_or_none()
        if not comment:
            raise ValueError("Comentario no encontrado")

        if comment.reply_status == "published" and (comment.published_reply_text or comment.published_reply_urn):
            return {
                "comment_id": comment_id,
                "reply_text": comment.published_reply_text or comment.suggested_reply or "",
                "published_reply_urn": comment.published_reply_urn or "",
                "status": "published",
                "already_published": True,
            }

        try:
            client = await get_linkedin_client_from_db(db)
        except LinkedInAuthError as exc:
            comment.error_message = str(exc)[:1000]
            comment.reply_status = "pending"
            await db.commit()
            raise RuntimeError(str(exc)) from exc

        text_to_publish = (reply_text or comment.suggested_reply or "").strip()
        if not text_to_publish:
            raise ValueError("No hay respuesta para publicar")

        try:
            result = await client.create_comment(
                target_urn=comment.linkedin_post_urn,
                object_urn=comment.linkedin_object_urn or _activity_urn_from_comment_urn(comment.linkedin_comment_urn),
                parent_comment_urn=comment.linkedin_comment_urn,
                text=text_to_publish,
            )
        except Exception as exc:
            comment.error_message = str(exc)[:1000]
            comment.reply_status = "pending"
            await db.commit()
            raise

        comment.reply_status = "published"
        comment.owner_replied = True
        comment.owner_reply_text = text_to_publish
        comment.published_reply_text = text_to_publish
        comment.published_reply_urn = result.get("comment_urn", "")
        comment.error_message = None
        await db.commit()
        await db.refresh(comment)

    return {
        "comment_id": comment_id,
        "reply_text": text_to_publish,
        "published_reply_urn": result.get("comment_urn", ""),
        "status": "published",
    }


async def list_pending_visible_comments(*, days: Optional[int] = None) -> list[LinkedInComment]:
    cutoff = datetime.utcnow() - timedelta(days=days or settings.linkedin_comment_monitor_days)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(LinkedInComment)
            .where(LinkedInComment.reply_status == "pending")
            .where(LinkedInComment.created_at >= cutoff)
            .order_by(LinkedInComment.created_at.asc())
        )
        return list(result.scalars().all())
