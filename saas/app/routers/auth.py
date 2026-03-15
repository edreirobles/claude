"""
Rutas de autenticación:
  POST /auth/register         - Crear cuenta con email/password
  POST /auth/login            - Obtener token JWT (email/password)
  GET  /auth/telegram-login   - Canjear token de Telegram por JWT
  GET  /auth/me               - Ver tu perfil
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.config import settings
from app.database import get_db
from app.models import Subscription, User, UserCredentials
from app.schemas import LoginResponse, RegisterRequest, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Este email ya está registrado")

    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
    )
    db.add(user)
    await db.flush()

    db.add(Subscription(user_id=user.id))
    db.add(UserCredentials(user_id=user.id))
    await db.commit()

    return LoginResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=LoginResponse)
async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == form.username))
    user = result.scalar_one_or_none()

    if not user or not user.hashed_password or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
        )

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Cuenta desactivada")

    return LoginResponse(access_token=create_access_token(user.id))


@router.get("/telegram-login", response_model=LoginResponse)
async def telegram_login(token: str, db: AsyncSession = Depends(get_db)):
    """
    Canjea el token de corta duración generado por el bot de Telegram
    por un JWT de larga duración para usar en el dashboard web.
    """
    invalid = HTTPException(status_code=400, detail="Token inválido o expirado")
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        if payload.get("type") != "tg_login":
            raise invalid
        user_id = int(payload["sub"])
    except (JWTError, TypeError, ValueError):
        raise invalid

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise invalid

    return LoginResponse(access_token=create_access_token(user_id))


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return current_user
