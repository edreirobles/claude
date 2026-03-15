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
    monthly_limit: int
    freemium_posts_used: int
    can_post: bool
    posts_remaining: int
    current_period_end: Optional[datetime]

    class Config:
        from_attributes = True
