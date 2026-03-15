"""Resetea contadores mensuales para usuarios con planes activos."""
import logging
from sqlalchemy import select, update
from app.database import AsyncSessionLocal
from app.models import Subscription, SubscriptionPlan, SubscriptionStatus

logger = logging.getLogger(__name__)


async def reset_monthly_counters():
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Subscription)
            .where(
                Subscription.plan != SubscriptionPlan.FREEMIUM,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
            .values(posts_used_this_month=0)
        )
        await db.commit()
        logger.info("Contadores mensuales reseteados")
