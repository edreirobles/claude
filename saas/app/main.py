from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers import auth, billing, dashboard

# Scheduler global
scheduler = AsyncIOScheduler(timezone="UTC")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Crear tablas si no existen
    await init_db()

    # Arrancar el scheduler de automatización
    from app.services.automation_engine import check_all_users, reset_monthly_counters

    # Revisar todos los usuarios cada hora
    scheduler.add_job(
        check_all_users,
        trigger="interval",
        hours=1,
        id="automation_check",
        replace_existing=True,
    )

    # Resetear contadores el 1° de cada mes a medianoche UTC
    scheduler.add_job(
        reset_monthly_counters,
        trigger="cron",
        day=1,
        hour=0,
        minute=0,
        id="monthly_reset",
        replace_existing=True,
    )

    scheduler.start()

    yield

    scheduler.shutdown()


app = FastAPI(
    title="X to LinkedIn SaaS",
    description="Automatiza tus posts de X a LinkedIn",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, limitar al dominio real
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers de la API
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(billing.router)

# Archivos estáticos (frontend)
app.mount("/", StaticFiles(directory="static", html=True), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}
