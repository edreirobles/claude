from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers import auth, billing, posts

scheduler = AsyncIOScheduler(timezone="UTC")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    # Resetear contadores mensuales el día 1 de cada mes
    from app.services.reset_service import reset_monthly_counters
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
    title="PostLinked — X to LinkedIn SaaS",
    description="Transforma cualquier URL en publicaciones profesionales para LinkedIn",
    version="2.0.0",
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
app.include_router(billing.router)
app.include_router(posts.router)

app.mount("/", StaticFiles(directory="static", html=True), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}
