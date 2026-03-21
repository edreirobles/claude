"""
Rutas principales de la API:
- Scraping y generación de posts
- Publicación inmediata
- Programación de posts
- Historial
"""
import csv
import io
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func

from ..database import get_db
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
from ..services.x_scraper import scrape_tweet
from ..services.post_generator import (
    generate_linkedin_post,
    generate_free_image,
    generate_nano_banana_image,
    download_tweet_video,
    download_pdf,
    SYSTEM_PROMPT_ES,
)
from ..services.linkedin_client import LinkedInClient
from ..services.scheduler_service import schedule_post, cancel_scheduled_post
from ..config import get_settings

router = APIRouter(prefix="/api", tags=["posts"])
settings = get_settings()


async def get_linkedin_client(db: AsyncSession) -> LinkedInClient:
    """Obtiene el cliente de LinkedIn autenticado o lanza error."""
    result = await db.execute(select(LinkedInToken).limit(1))
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="LinkedIn no está conectado. Ve a Configuración y conecta tu cuenta.",
        )
    if token.expires_at and token.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=401,
            detail="El token de LinkedIn expiró. Reconecta tu cuenta en Configuración.",
        )
    return LinkedInClient(token.access_token, token.person_urn)


@router.post("/generate", response_model=GenerateResponse)
async def generate_post(request: ScrapeRequest, db: AsyncSession = Depends(get_db)):
    """
    Extrae el contenido del tweet y genera una publicación LinkedIn con IA.
    No requiere LinkedIn conectado.
    """
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY no está configurada.",
        )

    # Scraping del tweet
    try:
        tweet = await scrape_tweet(request.url)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"No se pudo extraer el tweet: {e}")

    # Cargar prompt personalizado si existe
    cfg_result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    cfg = cfg_result.scalar_one_or_none()
    custom_prompt = cfg.custom_prompt if cfg else None

    # Generación con Claude
    try:
        linkedin_text = await generate_linkedin_post(
            tweet=tweet,
            language=request.language or settings.post_language,
            custom_prompt=custom_prompt,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando el post: {e}")

    # Determinar tipo de media
    if tweet.has_video:
        media_type = "video"
    elif tweet.pdf_url:
        media_type = "document"
    elif tweet.images:
        media_type = "image"
    else:
        media_type = "generate"  # Se generará imagen automáticamente al publicar

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
    )

    return GenerateResponse(
        tweet=tweet_schema,
        linkedin_text=linkedin_text,
        suggested_images=tweet.images[:4],
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
    elif request.media_type == "generate":
        generated_image_bytes = await generate_free_image(request.linkedin_text)

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
    if post.status != "scheduled":
        raise HTTPException(
            status_code=400,
            detail="Solo se pueden cancelar posts con estado 'scheduled'.",
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
    if post.status not in ("scheduled", "pending"):
        raise HTTPException(
            status_code=400,
            detail="Solo se pueden editar posts en estado 'scheduled' o 'pending'.",
        )

    if data.linkedin_text is not None:
        post.linkedin_text = data.linkedin_text.strip()
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
    from datetime import timedelta

    result = await db.execute(select(ScheduledPost))
    posts = result.scalars().all()

    published = [p for p in posts if p.status == "published"]

    # KPIs
    total_published = len(published)
    posts_with_metrics = [p for p in published if p.li_likes is not None or p.li_impressions is not None]

    total_likes = sum(p.li_likes or 0 for p in published)
    total_comments = sum(p.li_comments or 0 for p in published)
    total_impressions = sum(p.li_impressions or 0 for p in published)
    total_clicks = sum((getattr(p, 'li_clicks', None) or 0) for p in published)
    total_shares = sum((getattr(p, 'li_shares', None) or 0) for p in published)

    avg_likes = round(total_likes / len(posts_with_metrics), 1) if posts_with_metrics else 0
    avg_impressions = round(total_impressions / len(posts_with_metrics), 0) if posts_with_metrics else 0

    # Engagement rate: (likes + comments + clicks) / impressions * 100
    engagement_numerator = total_likes + total_comments + total_clicks
    engagement_rate = round(engagement_numerator / total_impressions * 100, 2) if total_impressions > 0 else 0

    # Posts por día — últimos 60 días
    today = datetime.utcnow().date()
    days: dict = {(today - timedelta(days=i)).isoformat(): 0 for i in range(59, -1, -1)}
    for p in posts:
        d = (p.published_at or p.created_at).date().isoformat()
        if d in days:
            days[d] += 1
    posts_by_day = [{"date": d, "count": c} for d, c in days.items()]

    # Posts por hora del día (de publicados)
    hours: dict = {i: 0 for i in range(24)}
    for p in published:
        if p.published_at:
            hours[p.published_at.hour] += 1
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

    # Top posts por engagement total (likes + comments + clicks)
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
            for p in published
        ],
        key=lambda x: x["total"],
        reverse=True,
    )[:10]

    return {
        "total_published": total_published,
        "posts_with_metrics": len(posts_with_metrics),
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
async def refresh_all_metrics(db: AsyncSession = Depends(get_db)):
    """
    Actualiza las métricas de TODOS los posts publicados que tienen linkedin_post_id.
    Útil para hacer un refresh masivo desde el dashboard.
    """
    import logging
    log = logging.getLogger(__name__)

    result = await db.execute(
        select(ScheduledPost)
        .where(ScheduledPost.status == "published")
        .where(ScheduledPost.linkedin_post_id.isnot(None))
        .where(ScheduledPost.linkedin_post_id != "")
    )
    posts = result.scalars().all()

    if not posts:
        return {"refreshed": 0, "message": "No hay posts publicados con ID de LinkedIn"}

    li_client = await get_linkedin_client(db)

    refreshed = 0
    failed = 0
    for post in posts:
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
            log.warning(f"[RefreshAll] Falló post {post.id}: {e}")
            failed += 1

    await db.commit()
    log.info(f"[RefreshAll] Completado: {refreshed} actualizados, {failed} fallidos")
    return {
        "refreshed": refreshed,
        "failed": failed,
        "total": len(posts),
        "message": f"Métricas actualizadas: {refreshed}/{len(posts)} posts",
    }


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
    Genera una imagen con Nano Banana (Gemini) para un post programado o pendiente.
    Guarda la imagen en static/generated_images/ y actualiza el post.
    """
    import os

    result = await db.execute(
        select(ScheduledPost).where(ScheduledPost.id == post_id)
    )
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post no encontrado")
    if post.status not in ("scheduled", "pending"):
        raise HTTPException(
            status_code=400,
            detail="Solo se puede generar imagen para posts programados o pendientes.",
        )

    image_bytes = await generate_nano_banana_image(post.linkedin_text)
    if not image_bytes:
        raise HTTPException(
            status_code=500,
            detail="No se pudo generar la imagen. Todos los servicios fallaron (Google Imagen 3, Gemini Flash, Pollinations.ai, Pillow). Revisa los logs del servidor.",
        )

    # Guardar imagen en static/generated_images/
    images_dir = os.path.join("static", "generated_images")
    os.makedirs(images_dir, exist_ok=True)
    image_filename = f"{post_id}.jpg"
    image_path = os.path.join(images_dir, image_filename)
    with open(image_path, "wb") as f:
        f.write(image_bytes)

    post.generated_image_path = f"/static/generated_images/{image_filename}"
    post.media_type = "generate"
    await db.commit()
    await db.refresh(post)
    return post


@router.post("/posts/repack-schedule")
async def repack_schedule_endpoint():
    """
    Reordena todos los posts 'scheduled' futuros para que ocupen
    los slots 5 AM y 4 PM (hora Monterrey) consecutivamente sin huecos.
    """
    from ..services.x_likes_monitor import repack_schedule
    result = await repack_schedule()
    return result
