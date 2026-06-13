"""
ZukoLabs VTO — Catalog Browsing Flow

Handles customer catalog browsing: search, filter, view products.
All queries scoped to tenant_id.
"""

import logging
from typing import Any, Dict, List

from models.customer import CustomerSession
from models.tenant import Tenant
from services.catalog import search_catalog
from services.whatsapp import (
    send_text_message,
    send_image_message,
    send_interactive_buttons,
)
from core.constants import POST_TRYON_BUTTONS

logger = logging.getLogger(__name__)

# Max products per page
PAGE_SIZE = 3


async def handle_catalog_browse(
    phone_number: str,
    text: str,
    session: CustomerSession,
    tenant: Tenant,
    customer_data: Dict[str, Any],
) -> None:
    """
    Handle catalog browsing requests.

    Parses the text for filters (category, budget, occasion)
    and returns matching products.

    Args:
        phone_number: Customer's phone number.
        text: The customer's search query.
        session: Customer session.
        tenant: Tenant object.
        customer_data: Customer DB record.
    """
    if not tenant.catalog_enabled:
        await send_text_message(
            phone_number=phone_number,
            message="Catalog abhi available nahi hai. Seller se contact karo.",
            phone_number_id=tenant.phone_number_id,
        )
        return

    # Parse filters from text
    filters = _parse_catalog_query(text)

    try:
        # Search catalog
        items = await search_catalog(
            tenant_id=tenant.id,
            occasion=filters.get("occasion"),
            category=filters.get("category"),
            budget_max=filters.get("budget_max"),
            color_preference=filters.get("color"),
            limit=PAGE_SIZE,
        )

        if not items:
            await send_text_message(
                phone_number=phone_number,
                message=(
                    "Is search mein kuch nahi mila 😔\n"
                    "Try karo:\n"
                    "• 'show sarees'\n"
                    "• 'under 2000'\n"
                    "• 'wedding outfit'"
                ),
                phone_number_id=tenant.phone_number_id,
            )
            return

        # Send each product
        for item in items:
            price_str = f"₹{item['price']}" if item.get("price") else ""
            caption = f"*{item['name']}*\n{price_str}"

            if item.get("tags"):
                caption += f"\n🏷️ {', '.join(item['tags'][:3])}"

            caption += "\n\n👗 Try-on karna hai? Is photo ko reply karo!"

            if item.get("image_url"):
                await send_image_message(
                    phone_number=phone_number,
                    image_url=item["image_url"],
                    caption=caption,
                    phone_number_id=tenant.phone_number_id,
                )
            else:
                await send_text_message(
                    phone_number=phone_number,
                    message=caption,
                    phone_number_id=tenant.phone_number_id,
                )

        # Summary message
        await send_text_message(
            phone_number=phone_number,
            message=(
                f"🛍️ {len(items)} products dikha rahe hain.\n"
                "Kisi bhi product ka photo bhejo try-on ke liye!"
            ),
            phone_number_id=tenant.phone_number_id,
        )

        logger.info(
            "Catalog browse: %d items shown (tenant: %s, filters: %s)",
            len(items),
            tenant.business_name,
            filters,
        )

    except Exception as e:
        logger.error("Catalog browse failed: %s", str(e))
        await send_text_message(
            phone_number=phone_number,
            message="Catalog load karne mein error aaya. Dobara try karo 🙏",
            phone_number_id=tenant.phone_number_id,
        )


def _parse_catalog_query(text: str) -> Dict[str, Any]:
    """
    Parse a catalog search query for filters.

    Examples:
    - "show sarees" → {"category": "apparel"}
    - "under 2000" → {"budget_max": 2000}
    - "wedding outfit" → {"occasion": "wedding", "category": "apparel"}

    Args:
        text: The search query text.

    Returns:
        Dict of parsed filters.
    """
    if not text:
        return {}

    text_lower = text.lower()
    filters = {}

    # Category detection
    category_keywords = {
        "apparel": ["saree", "sarees", "dress", "kurti", "lehenga", "suit", "outfit", "cloth"],
        "jewelry": ["jewelry", "jewellery", "necklace", "earring", "bangle"],
        "eyewear": ["eyewear", "glasses", "sunglasses"],
        "footwear": ["shoes", "sandals", "heels", "footwear"],
        "watch": ["watch", "watches"],
        "makeup": ["makeup", "lipstick", "cosmetic"],
    }

    for cat, keywords in category_keywords.items():
        if any(kw in text_lower for kw in keywords):
            filters["category"] = cat
            break

    # Budget detection
    import re
    budget_match = re.search(r"(?:under|below|max|upto|up to)\s*(?:rs\.?|₹)?\s*(\d+)", text_lower)
    if budget_match:
        filters["budget_max"] = int(budget_match.group(1))
    else:
        price_match = re.search(r"(?:rs\.?|₹)\s*(\d+)", text_lower)
        if price_match:
            filters["budget_max"] = int(price_match.group(1))

    # Occasion detection
    occasions = ["wedding", "office", "casual", "festival", "party", "diwali", "eid", "puja"]
    for occ in occasions:
        if occ in text_lower:
            filters["occasion"] = occ
            break

    # Color detection
    colors = ["red", "blue", "green", "black", "white", "pink", "yellow",
              "gold", "silver", "maroon", "beige", "navy"]
    for color in colors:
        if color in text_lower:
            filters["color"] = color
            break

    return filters
