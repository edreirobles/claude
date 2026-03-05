"""
Rutas de facturación con Stripe:

  POST /billing/checkout    → Crea sesión de pago para upgrade a Pro
  POST /billing/webhook     → Recibe eventos de Stripe (suscripción creada/cancelada/etc)
  GET  /billing/portal      → Abre el portal de Stripe para gestionar suscripción
  GET  /billing/status      → Estado actual de la suscripción del usuario

Flujo:
  1. Usuario hace click en "Upgrade"
  2. Frontend llama a POST /billing/checkout → recibe una URL de Stripe
  3. Usuario paga en Stripe
  4. Stripe llama a POST /billing/webhook con el evento "checkout.session.completed"
  5. Nosotros actualizamos la suscripción en la DB a "monthly / active"
"""

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import Subscription, SubscriptionPlan, SubscriptionStatus, User

stripe.api_key = settings.stripe_secret_key

router = APIRouter(prefix="/billing", tags=["billing"])


# --- Helpers ---

async def _get_or_create_stripe_customer(user: User, db: AsyncSession) -> str:
    """Crea un Customer en Stripe si el usuario no tiene uno todavía."""
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    sub = result.scalar_one_or_none()

    if sub and sub.stripe_customer_id:
        return sub.stripe_customer_id

    customer = stripe.Customer.create(
        email=user.email,
        name=user.full_name or user.email,
        metadata={"user_id": str(user.id)},
    )

    if sub:
        sub.stripe_customer_id = customer.id
        await db.commit()

    return customer.id


# --- Endpoints ---

@router.post("/checkout")
async def create_checkout_session(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Crea una sesión de pago en Stripe Checkout.
    El frontend redirige al usuario a la URL devuelta.
    """
    if not settings.stripe_secret_key or not settings.stripe_price_id_monthly:
        raise HTTPException(status_code=500, detail="Stripe no está configurado")

    customer_id = await _get_or_create_stripe_customer(current_user, db)

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": settings.stripe_price_id_monthly, "quantity": 1}],
        success_url=f"{settings.app_url}/app/?payment=success",
        cancel_url=f"{settings.app_url}/app/?payment=canceled",
        metadata={"user_id": str(current_user.id)},
        allow_promotion_codes=True,
    )

    return {"url": session.url}


@router.get("/portal")
async def create_billing_portal(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Abre el portal de Stripe donde el usuario puede:
    - Cancelar su suscripción
    - Actualizar tarjeta de crédito
    - Ver facturas
    """
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == current_user.id)
    )
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
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == current_user.id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return {"plan": "free", "status": "active", "can_post": True}

    return {
        "plan": sub.plan,
        "status": sub.status,
        "can_post": sub.can_post,
        "posts_used_this_month": sub.posts_used_this_month,
        "free_posts_limit": sub.free_posts_limit,
        "current_period_end": sub.current_period_end,
    }


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Stripe llama a este endpoint cada vez que ocurre un evento.
    Verificamos la firma para asegurarnos de que viene de Stripe.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
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

    return {"received": True}


# --- Handlers de eventos Stripe ---

async def _handle_checkout_completed(session: dict, db: AsyncSession):
    """El usuario completó el pago. Activamos el plan Pro."""
    user_id = int(session.get("metadata", {}).get("user_id", 0))
    stripe_subscription_id = session.get("subscription")

    if not user_id:
        return

    # Obtener detalles de la suscripción de Stripe
    stripe_sub = stripe.Subscription.retrieve(stripe_subscription_id)
    period_end = _ts_to_datetime(stripe_sub["current_period_end"])

    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    )
    sub = result.scalar_one_or_none()

    if sub:
        sub.plan = SubscriptionPlan.MONTHLY
        sub.status = SubscriptionStatus.ACTIVE
        sub.stripe_subscription_id = stripe_subscription_id
        sub.current_period_end = period_end
        await db.commit()


async def _handle_subscription_updated(stripe_sub: dict, db: AsyncSession):
    """La suscripción cambió (renovación, cambio de plan, etc)."""
    stripe_customer_id = stripe_sub.get("customer")
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_customer_id == stripe_customer_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return

    stripe_status = stripe_sub.get("status")
    sub.status = _map_stripe_status(stripe_status)
    sub.current_period_end = _ts_to_datetime(stripe_sub.get("current_period_end"))

    # Si la suscripción volvió a estar activa (ej: pago reintentado con éxito)
    if sub.status == SubscriptionStatus.ACTIVE:
        sub.plan = SubscriptionPlan.MONTHLY

    await db.commit()


async def _handle_subscription_deleted(stripe_sub: dict, db: AsyncSession):
    """El usuario canceló o venció sin renovar. Volvemos a FREE."""
    stripe_customer_id = stripe_sub.get("customer")
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_customer_id == stripe_customer_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return

    sub.plan = SubscriptionPlan.FREE
    sub.status = SubscriptionStatus.CANCELED
    sub.stripe_subscription_id = None
    await db.commit()


async def _handle_payment_failed(invoice: dict, db: AsyncSession):
    """Pago fallido: marcamos como past_due para bloquear el servicio."""
    stripe_customer_id = invoice.get("customer")
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_customer_id == stripe_customer_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return

    sub.status = SubscriptionStatus.PAST_DUE
    await db.commit()


# --- Utilidades ---

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
