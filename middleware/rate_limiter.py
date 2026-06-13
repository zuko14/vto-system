"""
ZukoLabs VTO — Rate Limiter Middleware

Per-tenant monthly try-on limit enforcement using usage_tracking table.
Checks plan limits before allowing any new try-on job.
"""

import logging
from datetime import datetime, timezone

from core.constants import get_monthly_limit
from core.database import get_db

logger = logging.getLogger(__name__)


async def check_rate_limit(tenant_id: str, plan: str) -> dict:
    """
    Check if the tenant has remaining try-on quota for the current month.

    Args:
        tenant_id: The tenant's UUID.
        plan: The tenant's plan name (starter, essential, enterprise).

    Returns:
        dict with:
          - allowed: bool — True if the tenant can proceed with a try-on.
          - remaining: int|None — Remaining try-ons this month (None = unlimited).
          - limit: int|None — Monthly limit (None = unlimited).
          - used: int — Try-ons used this month.
    """
    monthly_limit = get_monthly_limit(plan)

    # Enterprise plan = unlimited
    if monthly_limit is None:
        return {
            "allowed": True,
            "remaining": None,
            "limit": None,
            "used": 0,
        }

    db = get_db()
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")

    try:
        # Get or create usage record for this month
        result = (
            db.table("usage_tracking")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("month", current_month)
            .execute()
        )

        if result.data:
            used = result.data[0]["tryons_count"]
        else:
            # No record yet for this month — create one
            db.table("usage_tracking").insert({
                "tenant_id": tenant_id,
                "month": current_month,
                "tryons_count": 0,
            }).execute()
            used = 0

        remaining = monthly_limit - used
        allowed = remaining > 0

        if not allowed:
            logger.warning(
                "Tenant %s has reached monthly limit (%d/%d)",
                tenant_id,
                used,
                monthly_limit,
            )

        return {
            "allowed": allowed,
            "remaining": max(0, remaining),
            "limit": monthly_limit,
            "used": used,
        }

    except Exception as e:
        logger.error(
            "Rate limit check failed for tenant %s: %s — allowing",
            tenant_id,
            str(e),
        )
        # On error, allow the request (fail open for user experience)
        return {
            "allowed": True,
            "remaining": None,
            "limit": monthly_limit,
            "used": 0,
        }


async def increment_usage(tenant_id: str) -> None:
    """
    Increment the monthly try-on count for a tenant.
    Called after a try-on job is successfully created.

    Args:
        tenant_id: The tenant's UUID.
    """
    db = get_db()
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")

    try:
        # Check if record exists
        result = (
            db.table("usage_tracking")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("month", current_month)
            .execute()
        )

        if result.data:
            new_count = result.data[0]["tryons_count"] + 1
            (
                db.table("usage_tracking")
                .update({"tryons_count": new_count})
                .eq("tenant_id", tenant_id)
                .eq("month", current_month)
                .execute()
            )
        else:
            db.table("usage_tracking").insert({
                "tenant_id": tenant_id,
                "month": current_month,
                "tryons_count": 1,
            }).execute()

        logger.debug("Usage incremented for tenant %s (month: %s)", tenant_id, current_month)

    except Exception as e:
        logger.error(
            "Failed to increment usage for tenant %s: %s",
            tenant_id,
            str(e),
        )
