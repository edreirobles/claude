"""
Punto de entrada principal de la aplicación FastAPI.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
import logging

from .database import init_db
from .routers import posts, auth
from .routers import x_monitor
from .services.scheduler_service import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    start_scheduler()
    yield
    # Shutdown
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

# Archivos estáticos
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/health")
async def health():
    return {"status": "ok"}
