"""
Rutas principales de la API:
- Scraping y generación de posts
- Publicación inmediata
- Programación de posts
- Historial
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from ..database import get_db
from ..models import ScheduledPost, LinkedInToken
from ..schemas import (
    ScrapeRequest,
    GenerateResponse,
    PublishRequest,
    ScheduleRequest,
    PostResponse,
    TweetData as TweetDataSchema,
)
from ..services.x_scraper import scrape_tweet
from ..services.post_generator import (
    generate_linkedin_post,
    generate_free_image,
    download_tweet_video,
    download_pdf,
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
async def generate_post(request: ScrapeRequest):
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

    # Generación con Claude
    try:
        linkedin_text = await generate_linkedin_post(
            tweet=tweet,
            language=request.language or settings.post_language,
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
    """Programa una publicación para una fecha y hora específicas."""
    # Verificar que LinkedIn está conectado antes de programar
    await get_linkedin_client(db)

    if request.scheduled_at <= datetime.utcnow():
        raise HTTPException(
            status_code=400,
            detail="La fecha programada debe ser en el futuro.",
        )

    post = ScheduledPost(
        tweet_url=request.tweet_url,
        tweet_text=request.tweet_text,
        tweet_author=request.tweet_author,
        linkedin_text=request.linkedin_text,
        image_urls=request.image_urls,
        status="scheduled",
        scheduled_at=request.scheduled_at,
        use_first_image=request.use_first_image,
        media_type=request.media_type,
        pdf_url=request.pdf_url,
        document_title=request.document_title,
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)

    # Registrar en el scheduler
    schedule_post(post.id, request.scheduled_at)

    return post


@router.get("/posts", response_model=list[PostResponse])
async def list_posts(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Retorna el historial de posts publicados y programados."""
    result = await db.execute(
        select(ScheduledPost).order_by(desc(ScheduledPost.created_at)).limit(limit)
    )
    return result.scalars().all()


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


@router.put("/posts/{post_id}")
async def update_post_text(
    post_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Actualiza el texto de un post programado antes de que se publique."""
    result = await db.execute(
        select(ScheduledPost).where(ScheduledPost.id == post_id)
    )
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post no encontrado")
    if post.status != "scheduled":
        raise HTTPException(
            status_code=400,
            detail="Solo se pueden editar posts con estado 'scheduled'.",
        )

    if "linkedin_text" in body:
        post.linkedin_text = body["linkedin_text"]
    await db.commit()

    return {"message": "Post actualizado"}
