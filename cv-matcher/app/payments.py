"""
Stripe Checkout and webhook handling.
"""
import os
import stripe
from fastapi import HTTPException, Request


def _stripe():
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    return stripe


def create_checkout(customer_id: str, price_id: str, mode: str,
                    success_url: str, cancel_url: str, metadata: dict | None = None) -> str:
    """Create a Stripe Checkout session and return the redirect URL."""
    s = _stripe()
    session = s.checkout.Session.create(
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        mode=mode,  # "payment" or "subscription"
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata or {},
        allow_promotion_codes=True,
    )
    return session.url


def create_portal(customer_id: str, return_url: str) -> str:
    """Create a Stripe Customer Portal session (manage subscription/billing)."""
    s = _stripe()
    session = s.billing_portal.Session.create(customer=customer_id, return_url=return_url)
    return session.url


def verify_webhook(payload: bytes, sig_header: str) -> stripe.Event:
    s = _stripe()
    try:
        return s.Webhook.construct_event(
            payload, sig_header, os.environ["STRIPE_WEBHOOK_SECRET"]
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
