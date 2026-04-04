"""
Modelos de la base de datos del SaaS.

Tablas:
  - users: clientes (identificados por email)
  - subscriptions: plan y estado de pago (Stripe)
  - post_logs: historial de posts generados
"""

from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Integer, Text, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.database import Base


class SubscriptionPlan(str, enum.Enum):
    FREEMIUM = "freemium"     # $0  — 5 posts de por vida (nunca se reponen)
    INFLUENCER = "influencer" # $6/mes — 10 posts/mes
    TOP_VOICE = "top_voice"   # $9/mes — 30 posts/mes


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    CANCELED = "canceled"
    PAST_DUE = "past_due"
    TRIALING = "trialing"


PLAN_MONTHLY_LIMITS = {
    SubscriptionPlan.FREEMIUM: 5,
    SubscriptionPlan.INFLUENCER: 10,
    SubscriptionPlan.TOP_VOICE: 30,
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    subscription: Mapped["Subscription"] = relationship(back_populates="user", uselist=False)
    logs: Mapped[list["PostLog"]] = relationship(back_populates="user")

    @property
    def display_name(self) -> str:
        return self.full_name or self.email or f"Usuario #{self.id}"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), unique=True, nullable=False)

    stripe_customer_id: Mapped[str] = mapped_column(String(255), nullable=True)
    stripe_subscription_id: Mapped[str] = mapped_column(String(255), nullable=True)

    plan: Mapped[SubscriptionPlan] = mapped_column(
        Enum(SubscriptionPlan), default=SubscriptionPlan.FREEMIUM
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus), default=SubscriptionStatus.ACTIVE
    )

    # Freemium: contador de vida (nunca se repone)
    freemium_posts_used: Mapped[int] = mapped_column(Integer, default=0)

    # Planes pagos: contador mensual (se resetea cada ciclo de Stripe)
    posts_used_this_month: Mapped[int] = mapped_column(Integer, default=0)
    current_period_start: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    current_period_end: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="subscription")

    @property
    def monthly_limit(self) -> int:
        return PLAN_MONTHLY_LIMITS.get(self.plan, 5)

    @property
    def can_post(self) -> bool:
        if self.plan == SubscriptionPlan.FREEMIUM:
            return self.freemium_posts_used < 5
        if self.status != SubscriptionStatus.ACTIVE:
            return False
        return self.posts_used_this_month < self.monthly_limit

    @property
    def posts_remaining(self) -> int:
        if self.plan == SubscriptionPlan.FREEMIUM:
            return max(0, 5 - self.freemium_posts_used)
        return max(0, self.monthly_limit - self.posts_used_this_month)


class PasswordResetToken(Base):
    """Token de un solo uso para recuperar contraseña."""
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PostLog(Base):
    """Historial de cada post generado."""
    __tablename__ = "post_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    # Fuente
    source_url: Mapped[str] = mapped_column(String(1000), nullable=True)
    source_title: Mapped[str] = mapped_column(String(500), nullable=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=True)  # tweet, article, blog

    # Post generado
    linkedin_post_text: Mapped[str] = mapped_column(Text, nullable=True)
    generated_image_url: Mapped[str] = mapped_column(String(1000), nullable=True)

    status: Mapped[str] = mapped_column(String(50), default="generated")  # generated, published, failed
    error_message: Mapped[str] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="logs")
