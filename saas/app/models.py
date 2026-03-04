"""
Modelos de la base de datos del SaaS.

Hay 4 tablas principales:
  - users: los clientes que se registran
  - subscriptions: su estado de pago con Stripe
  - user_credentials: sus tokens de X y LinkedIn (cifrados)
  - automation_logs: historial de posts publicados
"""

from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Integer, Text, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.database import Base


class SubscriptionPlan(str, enum.Enum):
    FREE = "free"          # Sin pago, puede probar 3 posts
    MONTHLY = "monthly"    # $XX/mes, sin límite


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    CANCELED = "canceled"
    PAST_DUE = "past_due"
    TRIALING = "trialing"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relaciones
    subscription: Mapped["Subscription"] = relationship(back_populates="user", uselist=False)
    credentials: Mapped["UserCredentials"] = relationship(back_populates="user", uselist=False)
    logs: Mapped[list["AutomationLog"]] = relationship(back_populates="user")


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

    # Límites del plan FREE
    posts_used_this_month: Mapped[int] = mapped_column(Integer, default=0)
    free_posts_limit: Mapped[int] = mapped_column(Integer, default=3)

    current_period_end: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    user: Mapped["User"] = relationship(back_populates="subscription")

    @property
    def can_post(self) -> bool:
        """¿Puede este usuario publicar más posts?"""
        if self.plan == SubscriptionPlan.MONTHLY and self.status == SubscriptionStatus.ACTIVE:
            return True
        return self.posts_used_this_month < self.free_posts_limit


class UserCredentials(Base):
    """
    Almacena los tokens de X y LinkedIn de cada usuario.
    En producción estos deberían estar cifrados con Fernet o similar.
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
    post_frequency_hours: Mapped[int] = mapped_column(Integer, default=24)  # cada cuántas horas revisar X

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

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relaciones
    user: Mapped["User"] = relationship(back_populates="logs")
