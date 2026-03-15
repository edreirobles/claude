"""
Schemas Pydantic: validan los datos que entran y salen de la API.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr

from app.models import SubscriptionPlan, SubscriptionStatus


# --- Auth ---

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: Optional[str]
    full_name: Optional[str]
    telegram_username: Optional[str]
    display_name: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# --- Suscripción ---

class SubscriptionResponse(BaseModel):
    plan: SubscriptionPlan
    status: SubscriptionStatus
    posts_used_this_month: int
    free_posts_limit: int
    can_post: bool
    current_period_end: Optional[datetime]

    class Config:
        from_attributes = True


# --- Credenciales ---

class CredentialsUpdate(BaseModel):
    x_username: Optional[str] = None
    linkedin_access_token: Optional[str] = None
    linkedin_person_id: Optional[str] = None
    automation_enabled: Optional[bool] = None
    post_frequency_hours: Optional[int] = None


class CredentialsResponse(BaseModel):
    x_username: Optional[str]
    linkedin_person_id: Optional[str]
    automation_enabled: bool
    post_frequency_hours: int
    is_configured: bool
    has_linkedin_token: bool  # true si hay token guardado (sin exponer el valor)

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_with_token_flag(cls, creds):
        return cls(
            x_username=creds.x_username,
            linkedin_person_id=creds.linkedin_person_id,
            automation_enabled=creds.automation_enabled,
            post_frequency_hours=creds.post_frequency_hours,
            is_configured=creds.is_configured,
            has_linkedin_token=bool(creds.linkedin_access_token),
        )


# --- Configuración del prompt ---

class SettingsUpdate(BaseModel):
    custom_prompt: Optional[str] = None  # None = restablecer al default del sistema


class SettingsResponse(BaseModel):
    custom_prompt: Optional[str]
    default_prompt: str

    class Config:
        from_attributes = True


# --- Logs ---

class AutomationLogResponse(BaseModel):
    id: int
    tweet_url: Optional[str]
    tweet_text: Optional[str]
    linkedin_post_text: Optional[str]
    linkedin_post_id: Optional[str]
    status: str
    error_message: Optional[str]
    li_likes: Optional[int]
    li_comments: Optional[int]
    li_impressions: Optional[int]
    metrics_updated_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


# --- Dashboard ---

class DashboardResponse(BaseModel):
    user: UserResponse
    subscription: Optional[SubscriptionResponse]
    credentials: Optional[CredentialsResponse]
    recent_logs: list[AutomationLogResponse]
    total_posts_published: int
