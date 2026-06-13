"""
ZukoLabs VTO — Catalog Service

Catalog search, filter, and management for per-tenant product catalogs.
All queries are scoped to tenant_id (multi-tenancy isolation).
"""

import logging
from typing import Any, Dict, List, Optional

from core.database import get_db

logger = logging.getLogger(__name__)


async def search_catalog(
    tenant_id: str,
    occasion: Optional[str] = None,
    category: Optional[str] = None,
    budget_max: Optional[int] = None,
    color_preference: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Search a tenant's catalog with optional filters.

    Every query is scoped to tenant_id — no cross-tenant data leakage.

    Args:
        tenant_id: The tenant's UUID (mandatory).
        occasion: Filter by occasion tag (wedding, office, casual, etc.).
        category: Filter by category (apparel, jewelry, etc.).
        budget_max: Maximum price in INR.
        color_preference: Filter by color tag.
        limit: Max results to return.
        offset: Pagination offset.

    Returns:
        List of catalog item dicts.
    """
    db = get_db()

    try:
        query = (
            db.table("catalog_items")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("active", True)
        )

        if category:
            query = query.eq("category", category)

        if budget_max:
            query = query.lte("price", budget_max)

        if occasion:
            query = query.contains("tags", [occasion])

        if color_preference:
            query = query.contains("tags", [color_preference])

        query = query.range(offset, offset + limit - 1)

        result = query.execute()

        logger.debug(
            "Catalog search for tenant %s: %d results (filters: %s)",
            tenant_id,
            len(result.data),
            {
                "occasion": occasion,
                "category": category,
                "budget_max": budget_max,
                "color": color_preference,
            },
        )

        return result.data or []

    except Exception as e:
        logger.error(
            "Catalog search failed for tenant %s: %s",
            tenant_id,
            str(e),
        )
        return []


async def get_catalog_item(
    tenant_id: str,
    product_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Get a specific catalog item by product_id.

    Args:
        tenant_id: Tenant UUID.
        product_id: The product ID.

    Returns:
        Catalog item dict or None.
    """
    db = get_db()

    try:
        result = (
            db.table("catalog_items")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("product_id", product_id)
            .eq("active", True)
            .execute()
        )

        if result.data:
            return result.data[0]
        return None

    except Exception as e:
        logger.error(
            "Failed to get catalog item %s for tenant %s: %s",
            product_id,
            tenant_id,
            str(e),
        )
        return None


async def add_catalog_item(
    tenant_id: str,
    product_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Add a new item to a tenant's catalog.

    Args:
        tenant_id: Tenant UUID.
        product_data: Dict with name, category, price, image_url, tags, product_id.

    Returns:
        The created catalog item or None on error.
    """
    db = get_db()

    try:
        item = {
            "tenant_id": tenant_id,
            "product_id": product_data["product_id"],
            "name": product_data["name"],
            "category": product_data["category"],
            "price": product_data.get("price"),
            "image_url": product_data["image_url"],
            "tags": product_data.get("tags", []),
            "active": True,
        }

        result = db.table("catalog_items").insert(item).execute()

        if result.data:
            logger.info(
                "Added catalog item '%s' for tenant %s",
                product_data["name"],
                tenant_id,
            )
            return result.data[0]
        return None

    except Exception as e:
        logger.error(
            "Failed to add catalog item for tenant %s: %s",
            tenant_id,
            str(e),
        )
        return None


async def update_catalog_item(
    tenant_id: str,
    item_id: str,
    updates: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Update an existing catalog item.

    Args:
        tenant_id: Tenant UUID.
        item_id: The catalog item's UUID.
        updates: Dict of fields to update.

    Returns:
        Updated catalog item or None.
    """
    db = get_db()

    try:
        result = (
            db.table("catalog_items")
            .update(updates)
            .eq("id", item_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )

        if result.data:
            return result.data[0]
        return None

    except Exception as e:
        logger.error(
            "Failed to update catalog item %s: %s",
            item_id,
            str(e),
        )
        return None


async def delete_catalog_item(
    tenant_id: str,
    item_id: str,
) -> bool:
    """
    Soft-delete a catalog item (set active=false).

    Args:
        tenant_id: Tenant UUID.
        item_id: The catalog item's UUID.

    Returns:
        True if deleted, False otherwise.
    """
    db = get_db()

    try:
        result = (
            db.table("catalog_items")
            .update({"active": False})
            .eq("id", item_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )

        return bool(result.data)

    except Exception as e:
        logger.error(
            "Failed to delete catalog item %s: %s",
            item_id,
            str(e),
        )
        return False


async def get_catalog_count(tenant_id: str) -> int:
    """Get total active catalog items for a tenant."""
    db = get_db()

    try:
        result = (
            db.table("catalog_items")
            .select("id", count="exact")
            .eq("tenant_id", tenant_id)
            .eq("active", True)
            .execute()
        )

        return result.count or 0

    except Exception as e:
        logger.error("Failed to count catalog items: %s", str(e))
        return 0
