from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers import auth, billing, dashboard
from app.routers import telegram as telegram_router

scheduler = AsyncIOScheduler(timezone="UTC")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    from app.services.automation_engine import check_all_users, reset_monthly_counters

    scheduler.add_job(
        check_all_users,
        trigger="interval",
        hours=1,
        id="automation_check",
        replace_existing=True,
    )
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

    # Inicializar bot de Telegram
    from app.services.telegram_saas_bot import setup_bot, teardown_bot
    await setup_bot()

    yield

    await teardown_bot()
    scheduler.shutdown()


app = FastAPI(
    title="X to LinkedIn SaaS",
    description="Automatiza tus posts de X a LinkedIn",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(billing.router)
app.include_router(telegram_router.router)

app.mount("/", StaticFiles(directory="static", html=True), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}
