"""
Punto de entrada principal de la aplicación FastAPI.
"""
import asyncio
from contextlib import asynccontextmanager
import ssl
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
import logging
import httpx

from .config import get_settings
from .database import init_db
from .logging_security import install_log_redaction
from .routers import posts, auth
from .routers import x_monitor
from .routers import admin
from .services.scheduler_service import start_scheduler, stop_scheduler
from .services.telegram_bot import is_bot_running, start_bot, stop_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
install_log_redaction()
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
settings = get_settings()

TELEGRAM_STARTUP_TIMEOUT_SECONDS = 15
TELEGRAM_RETRY_DELAY_SECONDS = 30
bot_startup_task: asyncio.Task | None = None


def _configure_http_ssl_behavior() -> None:
    if not settings.allow_insecure_ssl_fallback:
        return
    if getattr(httpx, "_x_to_linkedin_ssl_patched", False):
        return

    original_async_client = httpx.AsyncClient
    original_client = httpx.Client

    class InsecureAsyncClient(original_async_client):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("verify", False)
            super().__init__(*args, **kwargs)

    class InsecureClient(original_client):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("verify", False)
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = InsecureAsyncClient
    httpx.Client = InsecureClient
    httpx._x_to_linkedin_ssl_patched = True
    os.environ.setdefault("PYTHONHTTPSVERIFY", "0")
    ssl._create_default_https_context = ssl._create_unverified_context
    logger.warning(
        "ALLOW_INSECURE_SSL_FALLBACK=true. Se desactiva la verificación SSL para mantener funcionando OpenAI, Telegram y el scraping en este equipo."
    )


_configure_http_ssl_behavior()


async def _maintain_telegram_bot():
    while True:
        try:
            if not is_bot_running():
                await asyncio.wait_for(
                    start_bot(),
                    timeout=TELEGRAM_STARTUP_TIMEOUT_SECONDS,
                )

            while is_bot_running():
                await asyncio.sleep(TELEGRAM_RETRY_DELAY_SECONDS)
        except asyncio.TimeoutError:
            logger.warning(
                "El bot de Telegram tardó más de %s s en iniciar; reintentaré en %s s",
                TELEGRAM_STARTUP_TIMEOUT_SECONDS,
                TELEGRAM_RETRY_DELAY_SECONDS,
            )
            await stop_bot()
            await asyncio.sleep(TELEGRAM_RETRY_DELAY_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "No se pudo iniciar o mantener el bot de Telegram; reintentaré en %s s. Error: %s",
                TELEGRAM_RETRY_DELAY_SECONDS,
                exc,
            )
            await stop_bot()
            await asyncio.sleep(TELEGRAM_RETRY_DELAY_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot_startup_task
    # Startup
    await init_db()
    start_scheduler()
    bot_startup_task = asyncio.create_task(_maintain_telegram_bot())
    yield
    # Shutdown
    if bot_startup_task and not bot_startup_task.done():
        bot_startup_task.cancel()
        try:
            await bot_startup_task
        except asyncio.CancelledError:
            pass
    bot_startup_task = None
    await stop_bot()
    stop_scheduler()


app = FastAPI(
    title="X → LinkedIn Automation",
    description="Convierte tweets en publicaciones LinkedIn con IA",
    version="1.0.0",
    lifespan=lifespan,
)

# Rutas API
app.include_router(posts.router)
app.include_router(auth.router)
app.include_router(x_monitor.router)
app.include_router(admin.router)

# Archivos estáticos
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/health")
async def health():
    return {"status": "ok"}
