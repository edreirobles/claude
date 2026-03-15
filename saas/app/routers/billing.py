"""
Rutas de facturación con Stripe.

  POST /billing/checkout      → Crea sesión de pago para un plan
  POST /billing/webhook       → Recibe eventos de Stripe
  GET  /billing/portal        → Portal de Stripe para gestionar suscripción
  GET  /billing/status        → Estado actual de la suscripción

Planes disponibles:
  - influencer: $6/mes — 10 posts/mes
  - top_voice:  $9/mes — 30 posts/mes
"""

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import Subscription, SubscriptionPlan, SubscriptionStatus, User

stripe.api_key = settings.stripe_secret_key

router = APIRouter(prefix="/billing", tags=["billing"])

PLAN_PRICE_MAP = {
    SubscriptionPlan.INFLUENCER: lambda: settings.stripe_price_id_influencer,
    SubscriptionPlan.TOP_VOICE: lambda: settings.stripe_price_id_top_voice,
}


class CheckoutRequest(BaseModel):
    plan: str  # "influencer" | "top_voice"


async def _get_or_create_stripe_customer(user: User, db: AsyncSession) -> str:
    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    sub = result.scalar_one_or_none()

    if sub and sub.stripe_customer_id:
        return sub.stripe_customer_id

    customer = stripe.Customer.create(
        email=user.email,
        name=user.display_name,
        metadata={"user_id": str(user.id)},
    )

    if sub:
        sub.stripe_customer_id = customer.id
        await db.commit()

    return customer.id


@router.post("/checkout")
async def create_checkout_session(
    body: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=500, detail="Stripe no está configurado")

    try:
        plan = SubscriptionPlan(body.plan)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Plan inválido: {body.plan}")

    price_id_fn = PLAN_PRICE_MAP.get(plan)
    if not price_id_fn:
        raise HTTPException(status_code=400, detail="Solo se pueden adquirir planes de pago")

    price_id = price_id_fn()
    if not price_id:
        raise HTTPException(status_code=500, detail=f"Precio de Stripe no configurado para {plan}")

    customer_id = await _get_or_create_stripe_customer(current_user, db)

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{settings.app_url}/app/?payment=success&plan={plan.value}",
        cancel_url=f"{settings.app_url}/app/?payment=canceled",
        metadata={"user_id": str(current_user.id), "plan": plan.value},
        allow_promotion_codes=True,
    )
    return {"url": session.url}


@router.get("/portal")
async def create_billing_portal(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Subscription).where(Subscription.user_id == current_user.id))
    sub = result.scalar_one_or_none()

    if not sub or not sub.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No tienes una suscripción activa con Stripe")

    session = stripe.billing_portal.Session.create(
        customer=sub.stripe_customer_id,
        return_url=f"{settings.app_url}/app/",
    )
    return {"url": session.url}


@router.get("/status")
async def get_billing_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Subscription).where(Subscription.user_id == current_user.id))
    sub = result.scalar_one_or_none()

    if not sub:
        return {
            "plan": "freemium",
            "status": "active",
            "can_post": True,
            "posts_remaining": 5,
            "freemium_posts_used": 0,
        }

    return {
        "plan": sub.plan,
        "status": sub.status,
        "can_post": sub.can_post,
        "posts_remaining": sub.posts_remaining,
        "posts_used_this_month": sub.posts_used_this_month,
        "monthly_limit": sub.monthly_limit,
        "freemium_posts_used": sub.freemium_posts_used,
        "current_period_end": sub.current_period_end,
    }


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Firma de webhook inválida")

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(data, db)
    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        await _handle_subscription_updated(data, db)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(data, db)
    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(data, db)
    elif event_type == "invoice.paid":
        await _handle_invoice_paid(data, db)

    return {"received": True}


async def _handle_checkout_completed(session: dict, db: AsyncSession):
    user_id = int(session.get("metadata", {}).get("user_id", 0))
    plan_value = session.get("metadata", {}).get("plan", "influencer")
    stripe_subscription_id = session.get("subscription")
    if not user_id:
        return

    try:
        new_plan = SubscriptionPlan(plan_value)
    except ValueError:
        new_plan = SubscriptionPlan.INFLUENCER

    stripe_sub = stripe.Subscription.retrieve(stripe_subscription_id)
    period_end = _ts_to_datetime(stripe_sub["current_period_end"])
    period_start = _ts_to_datetime(stripe_sub["current_period_start"])

    result = await db.execute(select(Subscription).where(Subscription.user_id == user_id))
    sub = result.scalar_one_or_none()
    if sub:
        sub.plan = new_plan
        sub.status = SubscriptionStatus.ACTIVE
        sub.stripe_subscription_id = stripe_subscription_id
        sub.current_period_start = period_start
        sub.current_period_end = period_end
        sub.posts_used_this_month = 0
        await db.commit()


async def _handle_subscription_updated(stripe_sub: dict, db: AsyncSession):
    stripe_customer_id = stripe_sub.get("customer")
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_customer_id == stripe_customer_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return

    sub.status = _map_stripe_status(stripe_sub.get("status"))
    sub.current_period_end = _ts_to_datetime(stripe_sub.get("current_period_end"))
    sub.current_period_start = _ts_to_datetime(stripe_sub.get("current_period_start"))
    await db.commit()


async def _handle_subscription_deleted(stripe_sub: dict, db: AsyncSession):
    stripe_customer_id = stripe_sub.get("customer")
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_customer_id == stripe_customer_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return

    sub.plan = SubscriptionPlan.FREEMIUM
    sub.status = SubscriptionStatus.CANCELED
    sub.stripe_subscription_id = None
    await db.commit()


async def _handle_payment_failed(invoice: dict, db: AsyncSession):
    stripe_customer_id = invoice.get("customer")
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_customer_id == stripe_customer_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return
    sub.status = SubscriptionStatus.PAST_DUE
    await db.commit()


async def _handle_invoice_paid(invoice: dict, db: AsyncSession):
    """Al pagar la factura mensual, resetear el contador del mes."""
    stripe_customer_id = invoice.get("customer")
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_customer_id == stripe_customer_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return
    sub.posts_used_this_month = 0
    sub.status = SubscriptionStatus.ACTIVE
    await db.commit()


def _map_stripe_status(stripe_status: str) -> SubscriptionStatus:
    mapping = {
        "active": SubscriptionStatus.ACTIVE,
        "trialing": SubscriptionStatus.TRIALING,
        "past_due": SubscriptionStatus.PAST_DUE,
        "canceled": SubscriptionStatus.CANCELED,
        "incomplete": SubscriptionStatus.PAST_DUE,
        "incomplete_expired": SubscriptionStatus.CANCELED,
        "unpaid": SubscriptionStatus.PAST_DUE,
    }
    return mapping.get(stripe_status, SubscriptionStatus.PAST_DUE)


def _ts_to_datetime(timestamp):
    if not timestamp:
        return None
    from datetime import datetime
    return datetime.utcfromtimestamp(timestamp)
