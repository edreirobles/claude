"""
Modelos de la base de datos del SaaS.

Tablas:
  - users: clientes (identificados por Telegram ID o email)
  - subscriptions: plan y estado de pago (Stripe)
  - user_credentials: tokens de X y LinkedIn por usuario
  - automation_logs: historial de posts generados/publicados
"""

from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Integer, Text, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.database import Base


class SubscriptionPlan(str, enum.Enum):
    FREE = "free"       # $0/mes — 5 posts
    PRO = "pro"         # $10/mes — posts ilimitados + prompt personalizado


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    CANCELED = "canceled"
    PAST_DUE = "past_due"
    TRIALING = "trialing"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Telegram es el método de auth principal; email es opcional
    telegram_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=True, index=True)
    telegram_chat_id: Mapped[str] = mapped_column(String(100), nullable=True)
    telegram_username: Mapped[str] = mapped_column(String(255), nullable=True)

    # Auth tradicional (opcional, para acceso web directo)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=True)

    full_name: Mapped[str] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relaciones
    subscription: Mapped["Subscription"] = relationship(back_populates="user", uselist=False)
    credentials: Mapped["UserCredentials"] = relationship(back_populates="user", uselist=False)
    logs: Mapped[list["AutomationLog"]] = relationship(back_populates="user")

    @property
    def display_name(self) -> str:
        return self.full_name or self.telegram_username or self.email or f"Usuario #{self.id}"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), unique=True, nullable=False)

    # Stripe
    stripe_customer_id: Mapped[str] = mapped_column(String(255), nullable=True)
    stripe_subscription_id: Mapped[str] = mapped_column(String(255), nullable=True)

    plan: Mapped[SubscriptionPlan] = mapped_column(
        Enum(SubscriptionPlan), default=SubscriptionPlan.FREE
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus), default=SubscriptionStatus.ACTIVE
    )

    # Contador mensual (se aplica al plan FREE)
    posts_used_this_month: Mapped[int] = mapped_column(Integer, default=0)
    free_posts_limit: Mapped[int] = mapped_column(Integer, default=5)

    current_period_end: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    user: Mapped["User"] = relationship(back_populates="subscription")

    @property
    def can_post(self) -> bool:
        if self.plan == SubscriptionPlan.PRO and self.status == SubscriptionStatus.ACTIVE:
            return True
        return self.posts_used_this_month < self.free_posts_limit


class UserCredentials(Base):
    """
    Almacena los tokens de X y LinkedIn de cada usuario.
    En producción estos deberían estar cifrados (Fernet o similar).
    """
    __tablename__ = "user_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), unique=True, nullable=False)

    # Cuenta de X a monitorear (solo el username, scraping público)
    x_username: Mapped[str] = mapped_column(String(255), nullable=True)

    # Tokens de LinkedIn para publicar
    linkedin_access_token: Mapped[str] = mapped_column(Text, nullable=True)
    linkedin_person_id: Mapped[str] = mapped_column(String(255), nullable=True)
    linkedin_token_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    # Configuración de automatización
    automation_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    post_frequency_hours: Mapped[int] = mapped_column(Integer, default=24)

    # Prompt personalizado (solo plan Pro)
    custom_prompt: Mapped[str] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    user: Mapped["User"] = relationship(back_populates="credentials")

    @property
    def is_configured(self) -> bool:
        return bool(self.x_username and self.linkedin_access_token)


class AutomationLog(Base):
    """Historial de cada post generado y publicado."""
    __tablename__ = "automation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    # Tweet original
    tweet_id: Mapped[str] = mapped_column(String(255), nullable=True)
    tweet_url: Mapped[str] = mapped_column(String(500), nullable=True)
    tweet_text: Mapped[str] = mapped_column(Text, nullable=True)

    # Post generado
    linkedin_post_text: Mapped[str] = mapped_column(Text, nullable=True)
    linkedin_post_id: Mapped[str] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, published, failed
    error_message: Mapped[str] = mapped_column(Text, nullable=True)

    # Métricas de LinkedIn
    li_likes: Mapped[int] = mapped_column(Integer, nullable=True)
    li_comments: Mapped[int] = mapped_column(Integer, nullable=True)
    li_impressions: Mapped[int] = mapped_column(Integer, nullable=True)
    metrics_updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relaciones
    user: Mapped["User"] = relationship(back_populates="logs")
