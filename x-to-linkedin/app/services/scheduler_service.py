"""
Servicio de programación de publicaciones.
Usa APScheduler con SQLite para persistir los trabajos.
"""
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

logger = logging.getLogger(__name__)

# Scheduler global (se inicializa en startup de la app)
scheduler = AsyncIOScheduler(
    jobstores={
        "default": SQLAlchemyJobStore(url="sqlite:///./scheduler_jobs.db")
    },
    job_defaults={"coalesce": True, "max_instances": 1},
    timezone="UTC",
)


def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler iniciado")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler detenido")


async def execute_scheduled_post(post_id: int):
    """Función que ejecuta un post programado. Se llama desde el scheduler."""
    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost, LinkedInToken
    from .linkedin_client import LinkedInClient
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        try:
            # Obtener el post
            post_result = await db.execute(
                select(ScheduledPost).where(ScheduledPost.id == post_id)
            )
            post = post_result.scalar_one_or_none()
            if not post or post.status != "scheduled":
                return

            # Obtener el token de LinkedIn
            token_result = await db.execute(select(LinkedInToken).limit(1))
            token = token_result.scalar_one_or_none()
            if not token:
                post.status = "failed"
                post.error_message = "No hay cuenta de LinkedIn conectada"
                await db.commit()
                return

            # Publicar
            client = LinkedInClient(token.access_token, token.person_urn)
            result = await client.create_post(
                text=post.linkedin_text,
                image_urls=post.image_urls,
                use_first_image=post.use_first_image,
            )

            post.status = "published"
            post.published_at = datetime.utcnow()
            post.linkedin_post_id = result.get("post_id", "")
            await db.commit()
            logger.info(f"Post {post_id} publicado correctamente")

        except Exception as e:
            logger.error(f"Error publicando post programado {post_id}: {e}")
            if post:
                post.status = "failed"
                post.error_message = str(e)
                await db.commit()


def schedule_post(post_id: int, run_date: datetime) -> str:
    """Agrega un trabajo al scheduler. Retorna el job_id."""
    job_id = f"post_{post_id}"
    scheduler.add_job(
        execute_scheduled_post,
        trigger="date",
        run_date=run_date,
        args=[post_id],
        id=job_id,
        replace_existing=True,
    )
    logger.info(f"Post {post_id} programado para {run_date}")
    return job_id


def cancel_scheduled_post(post_id: int) -> bool:
    """Cancela un trabajo programado. Retorna True si se canceló."""
    job_id = f"post_{post_id}"
    try:
        scheduler.remove_job(job_id)
        return True
    except Exception:
        return False
