from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers import auth, dashboard


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Al arrancar: crear tablas si no existen
    await init_db()
    yield


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

# Archivos estáticos (frontend)
app.mount("/", StaticFiles(directory="static", html=True), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}
