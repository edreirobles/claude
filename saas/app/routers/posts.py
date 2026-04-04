"""
Rutas para generación de posts de LinkedIn.

  POST /posts/generate      → Genera un post a partir de una URL
  POST /posts/{id}/publish  → Publica un post directamente en LinkedIn
  GET  /posts/history       → Historial de posts del usuario
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import LinkedInCredential, PostLog, Subscription, SubscriptionPlan, User
from app.services.linkedin_client import LinkedInClient
from app.services.post_generator import (
    build_image_prompt,
    generate_image_with_google,
    generate_linkedin_post,
)
from app.services.url_scraper import scrape_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/posts", tags=["posts"])


class GenerateRequest(BaseModel):
    url: str


class GenerateResponse(BaseModel):
    post_text: str
    image_data: Optional[str] = None  # data URI o None
    source_title: str = ""
    source_type: str = ""
    posts_remaining: int
    log_id: int


@router.post("/generate", response_model=GenerateResponse)
async def generate_post(
    body: GenerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 1. Verificar que el usuario puede generar posts
    result = await db.execute(select(Subscription).where(Subscription.user_id == current_user.id))
    sub = result.scalar_one_or_none()

    if not sub:
        raise HTTPException(
            status_code=403,
            detail="No tienes una suscripción activa."
        )

    if not sub.can_post:
        if sub.plan == SubscriptionPlan.FREEMIUM:
            raise HTTPException(
                status_code=403,
                detail="Agotaste tus 5 posts gratuitos. Actualiza tu plan para continuar.",
            )
        raise HTTPException(
            status_code=403,
            detail=f"Alcanzaste el límite mensual de {sub.monthly_limit} posts. "
                   "El contador se resetea al inicio de tu siguiente período.",
        )

    # 2. Scrapear la URL
    try:
        content = await scrape_url(body.url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # 3. Generar el post con Claude
    try:
        post_text = await generate_linkedin_post(content)
    except Exception as e:
        logger.error(f"Error generando post para usuario {current_user.id}: {e}")
        raise HTTPException(status_code=500, detail="Error al generar el post. Intenta de nuevo.")

    # 4. Imagen: usar la de la fuente, o generar con Google Imagen si no hay
    image_data: Optional[str] = None
    if content.images:
        image_data = content.images[0]  # URL directa de la imagen original
    else:
        img_prompt = build_image_prompt(post_text, content.title)
        image_data = await generate_image_with_google(img_prompt)

    # 5. Registrar en el log y actualizar contador
    log = PostLog(
        user_id=current_user.id,
        source_url=body.url,
        source_title=content.title,
        source_type=content.source_type,
        linkedin_post_text=post_text,
        generated_image_url=image_data if image_data and image_data.startswith("http") else None,
        status="generated",
    )
    db.add(log)

    if sub.plan == SubscriptionPlan.FREEMIUM:
        sub.freemium_posts_used += 1
    else:
        sub.posts_used_this_month += 1

    await db.commit()
    await db.refresh(log)

    return GenerateResponse(
        post_text=post_text,
        image_data=image_data,
        source_title=content.title,
        source_type=content.source_type,
        posts_remaining=sub.posts_remaining,
        log_id=log.id,
    )


@router.get("/history")
async def get_post_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PostLog)
        .where(PostLog.user_id == current_user.id)
        .order_by(desc(PostLog.created_at))
        .limit(50)
    )
    logs = result.scalars().all()

    return [
        {
            "id": log.id,
            "source_url": log.source_url,
            "source_title": log.source_title,
            "source_type": log.source_type,
            "post_text": log.linkedin_post_text,
            "status": log.status,
            "created_at": log.created_at,
        }
        for log in logs
    ]


@router.post("/{log_id}/publish")
async def publish_to_linkedin(
    log_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Publica un post generado directamente en LinkedIn usando el token OAuth del usuario.
    """
    # 1. Obtener el log del post
    log_result = await db.execute(
        select(PostLog).where(PostLog.id == log_id, PostLog.user_id == current_user.id)
    )
    log = log_result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="Post no encontrado.")
    if not log.linkedin_post_text:
        raise HTTPException(status_code=400, detail="El post no tiene contenido.")

    # 2. Obtener credenciales de LinkedIn
    cred_result = await db.execute(
        select(LinkedInCredential).where(LinkedInCredential.user_id == current_user.id)
    )
    cred = cred_result.scalar_one_or_none()
    if not cred:
        raise HTTPException(
            status_code=403,
            detail="No tienes LinkedIn conectado. Ve a Configuración para conectar tu cuenta.",
        )

    from datetime import datetime
    if cred.expires_at and cred.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=403,
            detail="Tu sesión de LinkedIn expiró. Ve a Configuración para reconectar.",
        )

    # 3. Publicar en LinkedIn
    li = LinkedInClient(access_token=cred.access_token, person_urn=cred.person_id)
    try:
        image_urls = [log.generated_image_url] if log.generated_image_url else None
        result = await li.create_post(
            text=log.linkedin_post_text,
            image_urls=image_urls,
        )
    except Exception as e:
        logger.error(f"Error publicando en LinkedIn para usuario {current_user.id}: {e}")
        raise HTTPException(status_code=500, detail="Error al publicar en LinkedIn. Intenta de nuevo.")

    # 4. Actualizar estado en el log
    log.status = "published"
    await db.commit()

    return {"published": True, "linkedin_post_id": result.get("post_id", "")}
