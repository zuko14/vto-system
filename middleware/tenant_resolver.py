"""
ZukoLabs VTO — Tenant Resolver Middleware

Resolves the tenant (seller) from the incoming WhatsApp webhook
using the phone_number_id from Meta's payload.
"""

import logging
from typing import Optional

from core.database import get_db
from models.tenant import Tenant, TenantSettings

logger = logging.getLogger(__name__)


class TenantNotFoundError(Exception):
    """Raised when no active tenant is found for the given phone_number_id."""
    pass


# In-memory tenant cache (refreshed on miss)
_tenant_cache: dict[str, Tenant] = {}


async def resolve_tenant(phone_number_id: str) -> Tenant:
    """
    Look up the active tenant by their Meta phone_number_id.

    This is called at the very start of webhook processing to determine
    which seller/client this message belongs to.

    Args:
        phone_number_id: The phone_number_id from Meta's webhook payload.

    Returns:
        Tenant object for the matching seller.

    Raises:
        TenantNotFoundError: If no active tenant matches.
    """
    # Check cache first
    if phone_number_id in _tenant_cache:
        cached = _tenant_cache[phone_number_id]
        if cached.active:
            return cached

    db = get_db()

    try:
        result = (
            db.table("tenants")
            .select("*")
            .eq("phone_number_id", phone_number_id)
            .eq("active", True)
            .execute()
        )

        if not result.data:
            logger.warning(
                "No active tenant found for phone_number_id: %s",
                phone_number_id,
            )
            raise TenantNotFoundError(
                f"No active tenant for phone_number_id: {phone_number_id}"
            )

        tenant_data = result.data[0]

        # Parse nested settings JSONB
        settings_raw = tenant_data.get("settings", {})
        if isinstance(settings_raw, dict):
            tenant_data["settings"] = TenantSettings(**settings_raw)
        else:
            tenant_data["settings"] = TenantSettings()

        tenant = Tenant(**tenant_data)

        # Cache the tenant
        _tenant_cache[phone_number_id] = tenant

        logger.info(
            "Resolved tenant: %s (%s) — plan: %s",
            tenant.business_name,
            tenant.id,
            tenant.plan,
        )
        return tenant

    except TenantNotFoundError:
        raise
    except Exception as e:
        logger.error(
            "Failed to resolve tenant for %s: %s",
            phone_number_id,
            str(e),
        )
        raise TenantNotFoundError(
            f"Error resolving tenant for {phone_number_id}: {str(e)}"
        )


def invalidate_tenant_cache(phone_number_id: Optional[str] = None) -> None:
    """
    Invalidate the tenant cache. Call this when tenant settings change.

    Args:
        phone_number_id: Specific tenant to invalidate. None = clear all.
    """
    if phone_number_id:
        _tenant_cache.pop(phone_number_id, None)
    else:
        _tenant_cache.clear()
    logger.debug("Tenant cache invalidated: %s", phone_number_id or "ALL")
