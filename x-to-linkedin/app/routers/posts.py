"""
Rutas principales de la API:
- Scraping y generación de posts
- Publicación inmediata
- Programación de posts
- Historial
"""
import csv
import io
import re
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func

from ..database import AsyncSessionLocal, get_db
from ..models import AppSettings, ScheduledPost, LinkedInToken
from ..schemas import (
    ScrapeRequest,
    GenerateResponse,
    PublishRequest,
    ScheduleRequest,
    PostResponse,
    PostUpdate,
    SettingsUpdate,
    SettingsResponse,
    TweetData as TweetDataSchema,
)
from ..services.x_scraper import (
    arxiv_pdf_url,
    fetch_paper_info,
    is_arxiv_paper,
    is_x_post_url,
    scrape_tweet,
)
from ..services.post_generator import (
    generate_linkedin_post,
    download_tweet_video,
    download_pdf,
    render_pdf_first_page_image,
    get_text_generation_config_error,
    SYSTEM_PROMPT_ES,
)
from ..services.linkedin_client import LinkedInClient
from ..services.linkedin_auth import LinkedInAuthError, get_linkedin_client_from_db
from ..services.scheduler_service import schedule_post, cancel_scheduled_post
from ..config import get_settings

router = APIRouter(prefix="/api", tags=["posts"])
settings = get_settings()
metrics_refresh_status = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "processed": 0,
    "refreshed": 0,
    "failed": 0,
    "total": 0,
    "message": "",
    "error": None,
}
schedule_verification_status = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "processed": 0,
    "verified": 0,
    "updated": 0,
    "cancelled": 0,
    "skipped": 0,
    "missing": 0,
    "total": 0,
    "message": "",
    "error": None,
}
calendar_rebuild_status = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "phase": "",
    "processed": 0,
    "text_refreshed": 0,
    "updated": 0,
    "verified": 0,
    "cancelled": 0,
    "failed": 0,
    "created": 0,
    "filled_slots": 0,
    "target_slots": 0,
    "remaining_slots": 0,
    "message": "",
    "error": None,
}


async def get_linkedin_client(db: AsyncSession) -> LinkedInClient:
    """Obtiene el cliente de LinkedIn autenticado o lanza error."""
    try:
        return await get_linkedin_client_from_db(db)
    except LinkedInAuthError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
        )


@router.post("/generate", response_model=GenerateResponse)
async def generate_post(request: ScrapeRequest, db: AsyncSession = Depends(get_db)):
    """
    Extrae el contenido de un tweet o cualquier URL web y genera una publicación LinkedIn con IA.
    No requiere LinkedIn conectado.
    """
    text_generation_error = get_text_generation_config_error()
    if text_generation_error:
        raise HTTPException(status_code=500, detail=text_generation_error)

    # Cargar prompt personalizado si existe
    cfg_result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    cfg = cfg_result.scalar_one_or_none()
    custom_prompt = cfg.custom_prompt if cfg else None

    is_tweet = is_x_post_url(request.url)

    if is_tweet:
        # ── Tweet de X ──────────────────────────────────────────────────────
        try:
            tweet = await scrape_tweet(request.url)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"No se pudo extraer el tweet: {e}")

        try:
            linkedin_text = await generate_linkedin_post(
                tweet=tweet,
                language=request.language or settings.post_language,
                custom_prompt=custom_prompt,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error generando el post: {e}")

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

        tweet_schema = TweetDataSchema(
            text=tweet.text,
            author_name=tweet.author_name,
            author_handle=tweet.author_handle,
            images=tweet.images,
            links=tweet.links,
            tweet_url=tweet.tweet_url,
            paper_info=tweet.paper_info,
            has_video=tweet.has_video,
            pdf_url=tweet.pdf_url,
            is_article=tweet.is_article,
        )

        return GenerateResponse(
            tweet=tweet_schema,
            linkedin_text=linkedin_text,
            suggested_images=tweet.images[:4],
            media_type=media_type,
        )

    else:
        # ── URL genérica: artículo, blog, noticia, etc. ──────────────────────
        from ..services.url_scraper import UrlContent, scrape_url
        from ..services.post_generator import generate_linkedin_post_from_url_content

        paper_info = None
        pdf_url = arxiv_pdf_url(request.url)
        if pdf_url:
            paper_info = await fetch_paper_info(request.url)

        try:
            if paper_info:
                url_content = UrlContent(
                    url=request.url,
                    title=paper_info.get("title", ""),
                    text=paper_info.get("abstract", ""),
                    author=", ".join(paper_info.get("authors", [])[:3]),
                    images=[],
                    source_domain="arxiv.org",
                )
            else:
                url_content = await scrape_url(request.url)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"No se pudo acceder al enlace: {e}")

        if not url_content.text and not url_content.title:
            raise HTTPException(
                status_code=422,
                detail=(
                    "No se pudo extraer contenido útil del enlace. "
                    "Puede que la página requiera JavaScript, esté detrás de un muro de pago, o bloquee bots."
                ),
            )

        try:
            linkedin_text = await generate_linkedin_post_from_url_content(
                url_content=url_content,
                language=request.language or settings.post_language,
                custom_prompt=custom_prompt,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error generando el post: {e}")

        media_type = "paper_image" if paper_info and pdf_url else ("image" if url_content.images else "none")

        tweet_schema = TweetDataSchema(
            text=url_content.title or url_content.text[:200],
            author_name=url_content.author or url_content.source_domain or "",
            author_handle=url_content.source_domain or "",
            images=url_content.images,
            links=[],
            tweet_url=request.url,
            paper_info=paper_info,
            has_video=url_content.has_video,
            pdf_url=pdf_url,
            is_article=False,
        )

        return GenerateResponse(
            tweet=tweet_schema,
            linkedin_text=linkedin_text,
            suggested_images=url_content.images[:4],
            media_type=media_type,
        )


@router.post("/publish")
async def publish_now(
    request: PublishRequest,
    db: AsyncSession = Depends(get_db),
):
    """Publica inmediatamente en LinkedIn."""
    li_client = await get_linkedin_client(db)

    # Descargar media según el tipo detectado
    video_bytes = None
    document_bytes = None
    generated_image_bytes = None

    if request.media_type == "video":
        video_bytes = await download_tweet_video(request.tweet_url)
        if not video_bytes:
            # Si falla la descarga del video, intentar con imagen del tweet
            request = request.model_copy(update={"media_type": "image"})
    elif request.media_type == "document" and request.pdf_url:
        document_bytes = await download_pdf(request.pdf_url)
    elif request.media_type == "paper_image" and request.pdf_url:
        generated_image_bytes = await render_pdf_first_page_image(request.pdf_url)
        if not generated_image_bytes:
            document_bytes = await download_pdf(request.pdf_url)
            request = request.model_copy(update={"media_type": "document"})
    elif request.media_type == "generate":
        request = request.model_copy(update={"media_type": "none"})

    try:
        result = await li_client.create_post(
            text=request.linkedin_text,
            image_urls=request.image_urls if request.media_type == "image" else None,
            use_first_image=request.media_type == "image" and request.use_first_image,
            video_bytes=video_bytes,
            document_bytes=document_bytes,
            document_title=request.document_title,
            generated_image_bytes=generated_image_bytes,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error publicando en LinkedIn: {e}")

    # Guardar en historial
    post = ScheduledPost(
        tweet_url=request.tweet_url,
        tweet_text=request.tweet_text,
        tweet_author=request.tweet_author,
        linkedin_text=request.linkedin_text,
        image_urls=request.image_urls,
        status="published",
        published_at=datetime.utcnow(),
        linkedin_post_id=result.get("post_id", ""),
        use_first_image=request.use_first_image,
        media_type=request.media_type,
        pdf_url=request.pdf_url,
        document_title=request.document_title,
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)

    return {"message": "¡Publicado en LinkedIn exitosamente!", "post_id": post.id}


@router.post("/schedule", response_model=PostResponse)
async def schedule_linkedin_post(
    request: ScheduleRequest,
    db: AsyncSession = Depends(get_db),
):
    """Programa una publicación en el próximo slot disponible (5 AM o 4 PM CDMX)."""
    # Verificar que LinkedIn está conectado antes de programar
    await get_linkedin_client(db)

    from ..services.x_likes_monitor import get_next_auto_slot
    run_at = await get_next_auto_slot(db)

    post = ScheduledPost(
        tweet_url=request.tweet_url,
        tweet_text=request.tweet_text,
        tweet_author=request.tweet_author,
        linkedin_text=request.linkedin_text,
        image_urls=request.image_urls,
        status="scheduled",
        scheduled_at=run_at,
        use_first_image=request.use_first_image,
        media_type=request.media_type,
        pdf_url=request.pdf_url,
        document_title=request.document_title,
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)

    # Registrar en el scheduler
    schedule_post(post.id, run_at)

    return post


@router.get("/posts", response_model=list[PostResponse])
async def list_posts(
    limit: int = 500,
    db: AsyncSession = Depends(get_db),
):
    """Retorna el historial de posts publicados y programados, más recientes/próximos primero."""
    sort_key = func.coalesce(ScheduledPost.scheduled_at, ScheduledPost.published_at, ScheduledPost.created_at)
    result = await db.execute(
        select(ScheduledPost).order_by(desc(sort_key)).limit(limit)
    )
    return result.scalars().all()


@router.post("/posts/verify-scheduled")
async def verify_scheduled_posts(background_tasks: BackgroundTasks):
    """Lanza una verificación masiva del calendario en segundo plano."""
    if schedule_verification_status["running"]:
        return {
            **schedule_verification_status,
            "started": False,
            "message": schedule_verification_status["message"] or "Ya hay una verificación en curso",
        }

    schedule_verification_status.update(
        {
            "running": True,
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": None,
            "processed": 0,
            "verified": 0,
            "updated": 0,
            "cancelled": 0,
            "skipped": 0,
            "missing": 0,
            "total": 0,
            "message": "Verificación del calendario iniciada en segundo plano",
            "error": None,
        }
    )
    background_tasks.add_task(_verify_scheduled_posts_job)
    return {
        **schedule_verification_status,
        "started": True,
    }


@router.get("/posts/verify-scheduled/status")
async def verify_scheduled_posts_status():
    """Devuelve el estado actual de la verificación masiva del calendario."""
    return schedule_verification_status


@router.post("/posts/rebuild-calendar")
async def rebuild_calendar(background_tasks: BackgroundTasks):
    """
    Regenera el texto de todo lo no publicado con el prompt actual y
    rellena huecos del calendario con fuentes nuevas y verificadas.
    """
    if calendar_rebuild_status["running"]:
        return {
            **calendar_rebuild_status,
            "started": False,
            "message": calendar_rebuild_status["message"] or "Ya hay una reconstrucción en curso",
        }

    calendar_rebuild_status.update(
        {
            "running": True,
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": None,
            "phase": "starting",
            "processed": 0,
            "text_refreshed": 0,
            "updated": 0,
            "verified": 0,
            "cancelled": 0,
            "failed": 0,
            "created": 0,
            "filled_slots": 0,
            "target_slots": 0,
            "remaining_slots": 0,
            "message": "Reconstrucción editorial iniciada en segundo plano",
            "error": None,
        }
    )
    background_tasks.add_task(_rebuild_calendar_job)
    return {
        **calendar_rebuild_status,
        "started": True,
    }


@router.get("/posts/rebuild-calendar/status")
async def rebuild_calendar_status():
    """Devuelve el estado actual de la reconstrucción editorial masiva."""
    return calendar_rebuild_status


@router.post("/posts/backfill-calendar")
async def backfill_calendar_only(background_tasks: BackgroundTasks):
    """Rellena huecos del calendario sin regenerar de nuevo el resto del contenido."""
    if calendar_rebuild_status["running"]:
        return {
            **calendar_rebuild_status,
            "started": False,
            "message": calendar_rebuild_status["message"] or "Ya hay un proceso editorial en curso",
        }

    calendar_rebuild_status.update(
        {
            "running": True,
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": None,
            "phase": "backfilling",
            "processed": 0,
            "text_refreshed": 0,
            "updated": 0,
            "verified": 0,
            "cancelled": 0,
            "failed": 0,
            "created": 0,
            "filled_slots": 0,
            "target_slots": 0,
            "remaining_slots": 0,
            "message": "Relleno de calendario iniciado en segundo plano",
            "error": None,
        }
    )
    background_tasks.add_task(_backfill_calendar_only_job)
    return {
        **calendar_rebuild_status,
        "started": True,
    }


@router.get("/posts/export")
async def export_posts_csv(
    from_date: Optional[str] = Query(None, description="Fecha inicio ISO (ej: 2025-01-01)"),
    to_date: Optional[str] = Query(None, description="Fecha fin ISO (ej: 2025-12-31)"),
    db: AsyncSession = Depends(get_db),
):
    """Exporta el historial de publicaciones como CSV, con filtro opcional por rango de fechas."""
    query = select(ScheduledPost).order_by(desc(ScheduledPost.created_at))

    if from_date:
        try:
            from_dt = datetime.fromisoformat(from_date)
            query = query.where(ScheduledPost.created_at >= from_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de from_date inválido. Usa YYYY-MM-DD")

    if to_date:
        try:
            # Incluir hasta el final del día indicado
            to_dt = datetime.fromisoformat(to_date).replace(hour=23, minute=59, second=59)
            query = query.where(ScheduledPost.created_at <= to_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de to_date inválido. Usa YYYY-MM-DD")

    result = await db.execute(query)
    posts = result.scalars().all()

    fields = [
        "id", "created_at", "tweet_url", "tweet_author", "tweet_text",
        "linkedin_text", "status", "source", "scheduled_at", "published_at",
        "linkedin_post_id", "media_type", "use_first_image", "pdf_url",
        "document_title", "error_message",
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()

    for post in posts:
        writer.writerow({
            "id": post.id,
            "created_at": post.created_at,
            "tweet_url": post.tweet_url,
            "tweet_author": post.tweet_author,
            "tweet_text": post.tweet_text,
            "linkedin_text": post.linkedin_text,
            "status": post.status,
            "source": getattr(post, "source", "manual"),
            "scheduled_at": post.scheduled_at or "",
            "published_at": post.published_at or "",
            "linkedin_post_id": post.linkedin_post_id or "",
            "media_type": post.media_type,
            "use_first_image": post.use_first_image,
            "pdf_url": post.pdf_url or "",
            "document_title": post.document_title,
            "error_message": post.error_message or "",
        })

    output.seek(0)
    filename = "publicaciones.csv"
    if from_date or to_date:
        filename = f"publicaciones_{from_date or 'inicio'}_{to_date or 'hoy'}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.delete("/posts/{post_id}")
async def cancel_post(
    post_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Cancela un post programado."""
    result = await db.execute(
        select(ScheduledPost).where(ScheduledPost.id == post_id)
    )
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post no encontrado")
    if post.status not in ("scheduled", "approval_pending", "radar_slot", "failed"):
        raise HTTPException(
            status_code=400,
            detail="Solo se pueden cancelar posts programados o pendientes de radar.",
        )

    cancel_scheduled_post(post_id)
    post.status = "cancelled"
    await db.commit()

    return {"message": "Post cancelado exitosamente"}


@router.put("/posts/{post_id}", response_model=PostResponse)
async def update_post(
    post_id: int,
    data: PostUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Actualiza contenido y/o fecha de un post programado."""

    result = await db.execute(
        select(ScheduledPost).where(ScheduledPost.id == post_id)
    )
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post no encontrado")
    if post.status not in ("scheduled", "pending", "approval_pending"):
        raise HTTPException(
            status_code=400,
            detail="Solo se pueden editar posts en estado 'scheduled', 'pending' o 'approval_pending'.",
        )

    if data.linkedin_text is not None:
        post.linkedin_text = data.linkedin_text.strip()
        post.manual_edited_at = datetime.utcnow()
        post.manual_edited_via = "web"
        if post.media_type == "generate":
            post.media_type = "none"
            post.generated_image_path = None
    if data.scheduled_at is not None:
        cancel_scheduled_post(post_id)
        post.scheduled_at = data.scheduled_at
        schedule_post(post_id, data.scheduled_at)
    if data.use_first_image is not None:
        post.use_first_image = data.use_first_image
    if data.media_type is not None:
        post.media_type = data.media_type
    if data.pdf_url is not None:
        post.pdf_url = data.pdf_url or None
    if data.document_title is not None:
        post.document_title = data.document_title
    await db.commit()
    await db.refresh(post)
    return post


# ── Configuración del prompt ────────────────────────────────────────────────

@router.get("/settings", response_model=SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)):
    """Devuelve el prompt personalizado actual y el prompt default del sistema."""
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    cfg = result.scalar_one_or_none()
    return SettingsResponse(
        custom_prompt=cfg.custom_prompt if cfg else None,
        default_prompt=SYSTEM_PROMPT_ES,
    )


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(data: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    """
    Guarda el prompt personalizado.
    Enviar custom_prompt=null restablece al prompt default del sistema.
    """
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    cfg = result.scalar_one_or_none()
    if cfg:
        cfg.custom_prompt = data.custom_prompt
    else:
        cfg = AppSettings(id=1, custom_prompt=data.custom_prompt)
        db.add(cfg)
    await db.commit()
    return SettingsResponse(
        custom_prompt=cfg.custom_prompt,
        default_prompt=SYSTEM_PROMPT_ES,
    )


# ── Métricas de LinkedIn ────────────────────────────────────────────────────

@router.get("/analytics")
async def get_analytics(db: AsyncSession = Depends(get_db)):
    """Devuelve estadísticas agregadas para el dashboard."""
    from datetime import timedelta, timezone
    from zoneinfo import ZoneInfo

    result = await db.execute(select(ScheduledPost))
    posts = result.scalars().all()

    published = [p for p in posts if p.status == "published"]
    metrics_posts = [
        p
        for p in published
        if any(
            value is not None
            for value in (
                p.li_likes,
                p.li_comments,
                p.li_impressions,
                getattr(p, "li_clicks", None),
                getattr(p, "li_shares", None),
            )
        )
    ]
    posts_missing_metrics = len(published) - len(metrics_posts)
    metrics_coverage_pct = round(
        (len(metrics_posts) / len(published)) * 100, 1
    ) if published else 0.0
    mx_tz = ZoneInfo("America/Mexico_City")

    # KPIs
    total_published = len(published)
    total_likes = sum(p.li_likes or 0 for p in metrics_posts)
    total_comments = sum(p.li_comments or 0 for p in metrics_posts)
    total_impressions = sum(p.li_impressions or 0 for p in metrics_posts)
    total_clicks = sum((getattr(p, "li_clicks", None) or 0) for p in metrics_posts)
    total_shares = sum((getattr(p, "li_shares", None) or 0) for p in metrics_posts)

    avg_likes = round(total_likes / len(metrics_posts), 1) if metrics_posts else 0
    avg_impressions = round(total_impressions / len(metrics_posts), 0) if metrics_posts else 0

    # Engagement rate: (likes + comments + clicks) / impressions * 100
    engagement_numerator = total_likes + total_comments + total_clicks
    engagement_rate = round(engagement_numerator / total_impressions * 100, 2) if total_impressions > 0 else 0

    # Posts por día — últimos 60 días (hora CDMX)
    today = datetime.now(mx_tz).date()
    days: dict = {(today - timedelta(days=i)).isoformat(): 0 for i in range(59, -1, -1)}
    for p in published:
        if not p.published_at:
            continue
        published_local = p.published_at.replace(tzinfo=timezone.utc).astimezone(mx_tz)
        local_day = published_local.date().isoformat()
        if local_day in days:
            days[local_day] += 1
    posts_by_day = [{"date": d, "count": c} for d, c in days.items()]

    # Posts por hora del día (de publicados, hora CDMX)
    hours: dict = {i: 0 for i in range(24)}
    for p in published:
        if p.published_at:
            published_local = p.published_at.replace(tzinfo=timezone.utc).astimezone(mx_tz)
            hours[published_local.hour] += 1
    posts_by_hour = [{"hour": h, "count": hours[h]} for h in range(24)]

    # Breakdown de estado
    status_counts: dict = {}
    for p in posts:
        status_counts[p.status] = status_counts.get(p.status, 0) + 1

    # Breakdown de tipo de media
    media_counts: dict = {}
    for p in published:
        k = p.media_type or "auto"
        media_counts[k] = media_counts.get(k, 0) + 1

    # Top posts por likes (desempate por engagement total)
    top_posts = sorted(
        [
            {
                "id": p.id,
                "text": (p.linkedin_text or "")[:120],
                "likes": p.li_likes or 0,
                "comments": p.li_comments or 0,
                "impressions": p.li_impressions or 0,
                "clicks": getattr(p, 'li_clicks', None) or 0,
                "shares": getattr(p, 'li_shares', None) or 0,
                "total": (p.li_likes or 0) + (p.li_comments or 0) + (getattr(p, 'li_clicks', None) or 0),
                "engagement_rate": round(
                    ((p.li_likes or 0) + (p.li_comments or 0) + (getattr(p, 'li_clicks', None) or 0))
                    / (p.li_impressions or 1) * 100, 2
                ) if p.li_impressions else 0,
                "published_at": p.published_at.isoformat() if p.published_at else None,
            }
            for p in metrics_posts
        ],
        key=lambda x: (x["likes"], x["total"], x["impressions"]),
        reverse=True,
    )[:10]

    return {
        "total_published": total_published,
        "posts_with_metrics": len(metrics_posts),
        "posts_missing_metrics": posts_missing_metrics,
        "metrics_coverage_pct": metrics_coverage_pct,
        "total_likes": total_likes,
        "total_comments": total_comments,
        "total_impressions": total_impressions,
        "total_clicks": total_clicks,
        "total_shares": total_shares,
        "avg_likes": avg_likes,
        "avg_impressions": int(avg_impressions),
        "engagement_rate": engagement_rate,
        "posts_by_day": posts_by_day,
        "posts_by_hour": posts_by_hour,
        "status_breakdown": status_counts,
        "media_type_breakdown": media_counts,
        "top_posts": top_posts,
    }


@router.post("/posts/{post_id}/refresh-metrics", response_model=PostResponse)
async def refresh_post_metrics(post_id: int, db: AsyncSession = Depends(get_db)):
    """
    Actualiza las métricas (likes, comentarios, impresiones) de un post publicado
    via API Voyager de LinkedIn (con cookies li_at) o la API pública como fallback.
    """
    import logging
    log = logging.getLogger(__name__)

    result = await db.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post no encontrado")
    if post.status != "published":
        raise HTTPException(status_code=400, detail="Este post aún no fue publicado en LinkedIn")
    if not post.linkedin_post_id:
        raise HTTPException(
            status_code=400,
            detail="Este post no tiene ID de LinkedIn guardado. "
                   "Fue publicado antes de que se implementara el tracking.",
        )

    log.info(f"[Metrics] Solicitando métricas para post DB={post_id}, LI_ID={post.linkedin_post_id}")

    li_client = await get_linkedin_client(db)
    metrics = await li_client.get_post_metrics(post.linkedin_post_id)

    log.info(f"[Metrics] Resultado para post {post_id}: {metrics}")

    # Actualizar todos los valores disponibles
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
    await db.commit()
    await db.refresh(post)
    return post


@router.post("/posts/refresh-all-metrics")
async def refresh_all_metrics(background_tasks: BackgroundTasks):
    """
    Inicia la actualización de métricas de todos los posts publicados
    sin bloquear la UI mientras se completa el proceso.
    """
    if metrics_refresh_status["running"]:
        return {
            **metrics_refresh_status,
            "started": False,
            "message": metrics_refresh_status["message"] or "Ya hay una actualización en curso",
        }

    metrics_refresh_status.update(
        {
            "running": True,
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": None,
            "processed": 0,
            "refreshed": 0,
            "failed": 0,
            "total": 0,
            "message": "Actualización de métricas iniciada en segundo plano",
            "error": None,
        }
    )
    background_tasks.add_task(_refresh_all_metrics_job)
    return {
        **metrics_refresh_status,
        "started": True,
    }


@router.get("/posts/refresh-all-metrics/status")
async def refresh_all_metrics_status():
    """Devuelve el estado actual del refresh masivo de métricas."""
    return metrics_refresh_status


async def _refresh_all_metrics_job():
    import logging

    log = logging.getLogger(__name__)

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ScheduledPost)
                .where(ScheduledPost.status == "published")
                .where(ScheduledPost.linkedin_post_id.isnot(None))
                .where(ScheduledPost.linkedin_post_id != "")
            )
            posts = result.scalars().all()
            metrics_refresh_status["total"] = len(posts)

            if not posts:
                metrics_refresh_status.update(
                    {
                        "running": False,
                        "finished_at": datetime.utcnow().isoformat(),
                        "message": "No hay posts publicados con ID de LinkedIn",
                    }
                )
                return

            li_client = await get_linkedin_client(db)

            refreshed = 0
            failed = 0
            for index, post in enumerate(posts, start=1):
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
                except Exception as exc:
                    log.warning(f"[RefreshAll] Falló post {post.id}: {exc}")
                    failed += 1

                metrics_refresh_status.update(
                    {
                        "processed": index,
                        "refreshed": refreshed,
                        "failed": failed,
                        "message": f"Actualizando métricas: {index}/{len(posts)} posts",
                    }
                )

            await db.commit()
            log.info(f"[RefreshAll] Completado: {refreshed} actualizados, {failed} fallidos")
            metrics_refresh_status.update(
                {
                    "running": False,
                    "finished_at": datetime.utcnow().isoformat(),
                    "processed": len(posts),
                    "refreshed": refreshed,
                    "failed": failed,
                    "message": f"Métricas actualizadas: {refreshed}/{len(posts)} posts",
                }
            )
    except Exception as exc:
        log.exception("[RefreshAll] Error inesperado")
        metrics_refresh_status.update(
            {
                "running": False,
                "finished_at": datetime.utcnow().isoformat(),
                "message": "La actualización de métricas terminó con error",
                "error": str(exc),
            }
        )


async def _verify_scheduled_posts_job():
    import logging

    log = logging.getLogger(__name__)

    try:
        from ..services.post_verifier import verify_scheduled_post

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ScheduledPost.id)
                .where(ScheduledPost.status == "scheduled")
                .order_by(ScheduledPost.scheduled_at, ScheduledPost.id)
            )
            post_ids = [row[0] for row in result.all()]
            schedule_verification_status["total"] = len(post_ids)

            if not post_ids:
                schedule_verification_status.update(
                    {
                        "running": False,
                        "finished_at": datetime.utcnow().isoformat(),
                        "message": "No hay posts programados por verificar",
                    }
                )
                return

            counts = {
                "verified": 0,
                "updated": 0,
                "cancelled": 0,
                "skipped": 0,
                "missing": 0,
            }

            for index, post_id in enumerate(post_ids, start=1):
                outcome = await verify_scheduled_post(post_id, db)
                action = outcome.get("action") or "skipped"
                if action in counts:
                    counts[action] += 1
                else:
                    counts["skipped"] += 1

                schedule_verification_status.update(
                    {
                        "processed": index,
                        "verified": counts["verified"],
                        "updated": counts["updated"],
                        "cancelled": counts["cancelled"],
                        "skipped": counts["skipped"],
                        "missing": counts["missing"],
                        "message": f"Verificando calendario: {index}/{len(post_ids)} posts",
                    }
                )

            log.info(
                "[VerifySchedule] Completado: %s verificados, %s actualizados, %s cancelados, %s omitidos, %s faltantes",
                counts["verified"],
                counts["updated"],
                counts["cancelled"],
                counts["skipped"],
                counts["missing"],
            )
            schedule_verification_status.update(
                {
                    "running": False,
                    "finished_at": datetime.utcnow().isoformat(),
                    "processed": len(post_ids),
                    "verified": counts["verified"],
                    "updated": counts["updated"],
                    "cancelled": counts["cancelled"],
                    "skipped": counts["skipped"],
                    "missing": counts["missing"],
                    "message": (
                        "Verificación completada: "
                        f"{counts['verified']} verificados, "
                        f"{counts['updated']} actualizados, "
                        f"{counts['cancelled']} cancelados."
                    ),
                }
            )
    except Exception as exc:
        log.exception("[VerifySchedule] Error inesperado")
        schedule_verification_status.update(
            {
                "running": False,
                "finished_at": datetime.utcnow().isoformat(),
                "message": "La verificación del calendario terminó con error",
                "error": str(exc),
            }
        )


async def _rebuild_calendar_job():
    import logging

    log = logging.getLogger(__name__)

    def _progress(update: dict):
        phase = update.get("phase", "")
        calendar_rebuild_status["phase"] = phase
        calendar_rebuild_status["message"] = update.get("message", "")
        if phase == "regenerating":
            calendar_rebuild_status["processed"] = update.get("processed", 0)
            calendar_rebuild_status["text_refreshed"] = update.get("text_refreshed", 0)
            calendar_rebuild_status["updated"] = update.get("updated", 0)
            calendar_rebuild_status["verified"] = update.get("verified", 0)
            calendar_rebuild_status["cancelled"] = update.get("cancelled", 0)
            calendar_rebuild_status["failed"] = update.get("failed", 0)
        elif phase == "backfilling":
            calendar_rebuild_status["created"] = update.get("created", 0)
            calendar_rebuild_status["filled_slots"] = update.get("filled_slots", 0)
            calendar_rebuild_status["target_slots"] = update.get("target_slots", 0)
            calendar_rebuild_status["remaining_slots"] = update.get("remaining_slots", 0)
            calendar_rebuild_status["cancelled"] = update.get("cancelled", calendar_rebuild_status["cancelled"])
            calendar_rebuild_status["updated"] = update.get("updated", calendar_rebuild_status["updated"])
            calendar_rebuild_status["verified"] = update.get("verified", calendar_rebuild_status["verified"])
            calendar_rebuild_status["failed"] = update.get("failed_sources", calendar_rebuild_status["failed"])

    try:
        from ..services.calendar_maintenance import rebuild_calendar_with_current_prompt

        result = await rebuild_calendar_with_current_prompt(progress_callback=_progress)
        regen = result.get("regeneration", {})
        backfill = result.get("backfill", {})

        calendar_rebuild_status.update(
            {
                "running": False,
                "finished_at": datetime.utcnow().isoformat(),
                "phase": "done",
                "processed": regen.get("processed", 0),
                "text_refreshed": regen.get("text_refreshed", 0),
                "updated": regen.get("updated", 0) + backfill.get("updated", 0),
                "verified": regen.get("verified", 0) + backfill.get("verified", 0),
                "cancelled": regen.get("cancelled", 0) + backfill.get("cancelled", 0),
                "failed": regen.get("failed", 0) + backfill.get("failed_sources", 0),
                "created": backfill.get("created", 0),
                "filled_slots": backfill.get("filled_slots", 0),
                "target_slots": backfill.get("target_slots", 0),
                "remaining_slots": backfill.get("remaining_slots", 0),
                "message": (
                    "Reconstrucción completada: "
                    f"{regen.get('text_refreshed', 0)} textos regenerados, "
                    f"{backfill.get('filled_slots', 0)} slots cubiertos, "
                    f"{backfill.get('remaining_slots', 0)} pendientes."
                ),
            }
        )
        log.info(
            "[RebuildCalendar] Completado: regen=%s backfill=%s",
            regen,
            backfill,
        )
    except Exception as exc:
        log.exception("[RebuildCalendar] Error inesperado")
        calendar_rebuild_status.update(
            {
                "running": False,
                "finished_at": datetime.utcnow().isoformat(),
                "phase": "error",
                "message": "La reconstrucción editorial terminó con error",
                "error": str(exc),
            }
        )


async def _backfill_calendar_only_job():
    import logging

    log = logging.getLogger(__name__)

    def _progress(update: dict):
        calendar_rebuild_status["phase"] = update.get("phase", "backfilling")
        calendar_rebuild_status["message"] = update.get("message", "")
        calendar_rebuild_status["created"] = update.get("created", 0)
        calendar_rebuild_status["filled_slots"] = update.get("filled_slots", 0)
        calendar_rebuild_status["target_slots"] = update.get("target_slots", 0)
        calendar_rebuild_status["remaining_slots"] = update.get("remaining_slots", 0)
        calendar_rebuild_status["updated"] = update.get("updated", 0)
        calendar_rebuild_status["verified"] = update.get("verified", 0)
        calendar_rebuild_status["cancelled"] = update.get("cancelled", 0)
        calendar_rebuild_status["failed"] = update.get("failed_sources", 0)

    try:
        from ..services.calendar_maintenance import backfill_calendar

        result = await backfill_calendar(progress_callback=_progress)
        calendar_rebuild_status.update(
            {
                "running": False,
                "finished_at": datetime.utcnow().isoformat(),
                "phase": "done",
                "created": result.get("created", 0),
                "filled_slots": result.get("filled_slots", 0),
                "target_slots": result.get("target_slots", 0),
                "remaining_slots": result.get("remaining_slots", 0),
                "updated": result.get("updated", 0),
                "verified": result.get("verified", 0),
                "cancelled": result.get("cancelled", 0),
                "failed": result.get("failed_sources", 0),
                "message": (
                    "Backfill completado: "
                    f"{result.get('filled_slots', 0)} slots cubiertos, "
                    f"{result.get('remaining_slots', 0)} pendientes."
                ),
            }
        )
        log.info("[BackfillCalendar] Completado: %s", result)
    except Exception as exc:
        log.exception("[BackfillCalendar] Error inesperado")
        calendar_rebuild_status.update(
            {
                "running": False,
                "finished_at": datetime.utcnow().isoformat(),
                "phase": "error",
                "message": "El backfill del calendario terminó con error",
                "error": str(exc),
            }
        )


@router.get("/linkedin-scraper/status")
async def linkedin_scraper_status():
    """
    Informa si las cookies de LinkedIn para scraping de métricas están configuradas.
    """
    s = get_settings()
    return {
        "configured": bool(s.linkedin_li_at),
        "has_jsessionid": bool(s.linkedin_jsessionid),
    }


@router.get("/linkedin-scraper/debug/{post_id}")
async def linkedin_scraper_debug(post_id: int, db: AsyncSession = Depends(get_db)):
    """
    Diagnóstico: muestra el post_id guardado y la respuesta cruda de los
    endpoints Voyager de LinkedIn para ese post.
    """
    from ..services.linkedin_scraper import debug_post_metrics

    result = await db.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post no encontrado")

    s = get_settings()
    if not s.linkedin_li_at:
        return {"error": "LINKEDIN_LI_AT no configurado en .env"}

    debug_info = await debug_post_metrics(
        post_id=post.linkedin_post_id or "",
        li_at=s.linkedin_li_at,
        jsessionid=s.linkedin_jsessionid,
    )
    return {
        "db_post_id": post.id,
        "db_linkedin_post_id": post.linkedin_post_id,
        "db_status": post.status,
        **debug_info,
    }


@router.post("/posts/{post_id}/generate-image", response_model=PostResponse)
async def generate_post_image(
    post_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint heredado. La estrategia editorial vigente no genera imagenes.
    """
    raise HTTPException(
        status_code=410,
        detail="La generación de imágenes fue desactivada. Si la fuente no trae imagen real, el post se publica sin adjunto.",
    )


@router.post("/posts/repack-schedule")
async def repack_schedule_endpoint():
    """
    Reordena todos los posts 'scheduled' futuros para que ocupen
    el slot de 9 AM (hora Monterrey) consecutivamente sin huecos.
    """
    from ..services.x_likes_monitor import repack_schedule
    result = await repack_schedule()
    return result
