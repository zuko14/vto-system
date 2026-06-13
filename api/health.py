"""
ZukoLabs VTO — Health Check Endpoint

GET /health — Returns system status and active tenant count.
Used by Render.com for health monitoring.
"""

import logging

from fastapi import APIRouter
from core.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health_check() -> dict:
    """
    Health check endpoint.

    Returns:
        {"status": "ok", "tenants": N} where N is active tenant count.
    """
    try:
        db = get_db()
        result = (
            db.table("tenants")
            .select("id", count="exact")
            .eq("active", True)
            .execute()
        )
        tenant_count = result.count or 0
    except Exception as e:
        logger.warning("Health check: DB query failed: %s", str(e))
        tenant_count = -1

    return {
        "status": "ok",
        "tenants": tenant_count,
        "service": "zukolabs-vto",
    }
