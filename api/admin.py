"""
ZukoLabs VTO — Seller Admin Dashboard API

Routes for seller/tenant management:
- Tenant stats and usage
- Catalog CRUD (add, update, delete, bulk upload)
- Customer analytics (anonymized)
- Tenant onboarding
"""

import csv
import io
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile

from core.database import get_db
from core.constants import get_plan_features
from middleware.tenant_resolver import invalidate_tenant_cache
from models.tenant import Tenant, TenantCreate, TenantStats
from services.catalog import (
    add_catalog_item,
    delete_catalog_item,
    get_catalog_count,
    search_catalog,
    update_catalog_item,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ═══════════════════════════════════════════════════════════════
# TENANT STATS
# ═══════════════════════════════════════════════════════════════


@router.get("/tenants/{tenant_id}/stats")
async def get_tenant_stats(tenant_id: str) -> dict:
    """
    Get tenant usage statistics.

    Returns:
        Tenant stats including try-on count, customer count, etc.
    """
    db = get_db()

    try:
        # Get tenant info
        tenant_result = (
            db.table("tenants")
            .select("*")
            .eq("id", tenant_id)
            .execute()
        )

        if not tenant_result.data:
            raise HTTPException(status_code=404, detail="Tenant not found")

        tenant = tenant_result.data[0]

        # Get current month usage
        from datetime import datetime, timezone
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")

        usage_result = (
            db.table("usage_tracking")
            .select("tryons_count")
            .eq("tenant_id", tenant_id)
            .eq("month", current_month)
            .execute()
        )
        tryons_this_month = (
            usage_result.data[0]["tryons_count"]
            if usage_result.data
            else 0
        )

        # Get customer counts
        total_customers = (
            db.table("customers")
            .select("id", count="exact")
            .eq("tenant_id", tenant_id)
            .execute()
        ).count or 0

        # Get catalog count
        catalog_count = await get_catalog_count(tenant_id)

        plan_features = get_plan_features(tenant["plan"])

        return {
            "tenant_id": tenant_id,
            "business_name": tenant["business_name"],
            "plan": tenant["plan"],
            "tryons_this_month": tryons_this_month,
            "monthly_limit": plan_features.get("monthly_tryon_limit"),
            "total_customers": total_customers,
            "catalog_items_count": catalog_count,
            "plan_features": plan_features,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get tenant stats: %s", str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# ═══════════════════════════════════════════════════════════════
# CATALOG MANAGEMENT
# ═══════════════════════════════════════════════════════════════


@router.get("/tenants/{tenant_id}/catalog")
async def list_catalog(
    tenant_id: str,
    category: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List catalog items for a tenant."""
    items = await search_catalog(
        tenant_id=tenant_id,
        category=category,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "count": len(items)}


@router.post("/tenants/{tenant_id}/catalog")
async def create_catalog_item(
    tenant_id: str,
    item: Dict[str, Any],
) -> dict:
    """Add a new catalog item."""
    required_fields = ["product_id", "name", "category", "image_url"]
    for field in required_fields:
        if field not in item:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required field: {field}",
            )

    result = await add_catalog_item(tenant_id, item)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to create item")

    return {"status": "created", "item": result}


@router.put("/tenants/{tenant_id}/catalog/{item_id}")
async def edit_catalog_item(
    tenant_id: str,
    item_id: str,
    updates: Dict[str, Any],
) -> dict:
    """Update an existing catalog item."""
    result = await update_catalog_item(tenant_id, item_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail="Item not found")

    return {"status": "updated", "item": result}


@router.delete("/tenants/{tenant_id}/catalog/{item_id}")
async def remove_catalog_item(
    tenant_id: str,
    item_id: str,
) -> dict:
    """Remove (soft-delete) a catalog item."""
    success = await delete_catalog_item(tenant_id, item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found")

    return {"status": "deleted"}


@router.post("/tenants/{tenant_id}/catalog/bulk")
async def bulk_upload_catalog(
    tenant_id: str,
    file: UploadFile = File(...),
) -> dict:
    """
    Bulk upload catalog items via CSV.

    CSV format:
    product_id,name,category,price,image_url,tags
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Only CSV files are accepted",
        )

    content = await file.read()
    text_content = content.decode("utf-8")

    reader = csv.DictReader(io.StringIO(text_content))

    created = 0
    errors = []

    for row_num, row in enumerate(reader, start=2):
        try:
            item_data = {
                "product_id": row["product_id"],
                "name": row["name"],
                "category": row["category"],
                "price": float(row["price"]) if row.get("price") else None,
                "image_url": row["image_url"],
                "tags": (
                    [t.strip() for t in row["tags"].split("|")]
                    if row.get("tags")
                    else []
                ),
            }

            result = await add_catalog_item(tenant_id, item_data)
            if result:
                created += 1
            else:
                errors.append(f"Row {row_num}: Failed to insert")

        except Exception as e:
            errors.append(f"Row {row_num}: {str(e)}")

    return {
        "status": "completed",
        "created": created,
        "errors": errors,
        "total_rows": created + len(errors),
    }


# ═══════════════════════════════════════════════════════════════
# CUSTOMER ANALYTICS (Anonymized)
# ═══════════════════════════════════════════════════════════════


@router.get("/tenants/{tenant_id}/customers")
async def get_customer_analytics(tenant_id: str) -> dict:
    """
    Get anonymized customer statistics.
    Never returns raw phone numbers or personal data.
    """
    db = get_db()

    try:
        # Total customers
        total = (
            db.table("customers")
            .select("id", count="exact")
            .eq("tenant_id", tenant_id)
            .execute()
        ).count or 0

        # Consented customers
        consented = (
            db.table("customers")
            .select("id", count="exact")
            .eq("tenant_id", tenant_id)
            .eq("consent_given", True)
            .execute()
        ).count or 0

        # Total try-ons
        tryons = (
            db.table("tryon_jobs")
            .select("id", count="exact")
            .eq("tenant_id", tenant_id)
            .execute()
        ).count or 0

        # Successful try-ons
        successful = (
            db.table("tryon_jobs")
            .select("id", count="exact")
            .eq("tenant_id", tenant_id)
            .eq("status", "completed")
            .execute()
        ).count or 0

        return {
            "total_customers": total,
            "consented_customers": consented,
            "total_tryons": tryons,
            "successful_tryons": successful,
            "success_rate": (
                round(successful / tryons * 100, 1)
                if tryons > 0
                else 0
            ),
        }

    except Exception as e:
        logger.error("Customer analytics failed: %s", str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# ═══════════════════════════════════════════════════════════════
# TENANT ONBOARDING
# ═══════════════════════════════════════════════════════════════


@router.post("/onboard")
async def onboard_tenant(tenant_data: TenantCreate) -> dict:
    """
    Onboard a new tenant (seller/client).

    Creates:
    1. Tenant row in DB
    2. Zero redeployment required — new tenant = new DB row only
    """
    db = get_db()

    try:
        # Check if phone_number_id already exists
        existing = (
            db.table("tenants")
            .select("id")
            .eq("phone_number_id", tenant_data.phone_number_id)
            .execute()
        )

        if existing.data:
            raise HTTPException(
                status_code=409,
                detail="Tenant with this phone_number_id already exists",
            )

        # Create tenant
        result = db.table("tenants").insert({
            "phone_number_id": tenant_data.phone_number_id,
            "business_name": tenant_data.business_name,
            "plan": tenant_data.plan,
            "whatsapp_number": tenant_data.whatsapp_number,
            "language": tenant_data.language,
            "catalog_enabled": tenant_data.catalog_enabled,
            "settings": tenant_data.settings.model_dump(),
            "active": True,
        }).execute()

        if not result.data:
            raise HTTPException(
                status_code=500,
                detail="Failed to create tenant",
            )

        tenant = result.data[0]

        # Invalidate cache
        invalidate_tenant_cache()

        logger.info(
            "New tenant onboarded: %s (%s) — plan: %s",
            tenant_data.business_name,
            tenant["id"],
            tenant_data.plan,
        )

        return {
            "status": "created",
            "tenant_id": tenant["id"],
            "business_name": tenant_data.business_name,
            "plan": tenant_data.plan,
            "message": (
                "Tenant created successfully. "
                "Configure Meta App with their WhatsApp Business number, "
                "then send a test message to verify webhook routing."
            ),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Tenant onboarding failed: %s", str(e))
        raise HTTPException(status_code=500, detail="Internal server error")
