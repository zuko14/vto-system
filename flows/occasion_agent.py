"""
ZukoLabs VTO — Occasion Agent Flow

Mini-agent with max 3 tool calls for occasion-based outfit discovery.
Uses Groq tool-calling to search catalog, check skin tone compatibility,
and generate try-ons. Essential/Enterprise plans only.
"""

import logging
from typing import Any, Dict, List, Optional

from core.constants import OCCASION_AGENT_SYSTEM_PROMPT
from models.customer import CustomerSession
from models.tenant import Tenant
from services.catalog import search_catalog, get_catalog_item
from services.groq_client import agent_call
from services.skin_tone import check_color_compatibility
from services.tryon_engine import generate
from services.whatsapp import (
    send_text_message,
    send_image_message,
    send_interactive_buttons,
)
from core.constants import POST_TRYON_BUTTONS

logger = logging.getLogger(__name__)

# Maximum tool calls per agent run
MAX_TOOL_CALLS = 3

# Tool definitions for Groq
OCCASION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_catalog",
            "description": (
                "Search seller's catalog by occasion, category, budget, color"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "occasion": {
                        "type": "string",
                        "description": "Occasion: wedding, office, casual, festival, party",
                    },
                    "budget_max": {
                        "type": "integer",
                        "description": "Maximum budget in INR",
                    },
                    "category": {
                        "type": "string",
                        "description": "Product category",
                    },
                    "color_preference": {
                        "type": "string",
                        "description": "Preferred color",
                    },
                },
                "required": ["occasion"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_skin_tone_compatibility",
            "description": (
                "Given a skin tone code and garment colors, return "
                "compatibility score and recommendation"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skin_tone_code": {
                        "type": "string",
                        "description": "Monk scale: MST-1 to MST-10",
                    },
                    "garment_colors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of garment colors",
                    },
                },
                "required": ["skin_tone_code", "garment_colors"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_tryon",
            "description": "Generate try-on for a specific product",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "Product ID from catalog",
                    },
                    "selfie_url": {
                        "type": "string",
                        "description": "Customer's selfie URL",
                    },
                },
                "required": ["product_id", "selfie_url"],
            },
        },
    },
]


async def handle_occasion_request(
    phone_number: str,
    text: str,
    session: CustomerSession,
    tenant: Tenant,
    customer_data: Dict[str, Any],
) -> None:
    """
    Handle an occasion-based outfit discovery request.

    Runs the mini-agent with max 3 tool calls to:
    1. Search catalog for relevant products
    2. Check color compatibility with skin tone (if available)
    3. Generate a try-on for the best match

    Args:
        phone_number: Customer's phone number.
        text: The user's occasion description.
        session: Customer session.
        tenant: Tenant object.
        customer_data: Customer DB record.
    """
    language = customer_data.get("language", "en")
    skin_tone = customer_data.get("skin_tone_code")

    # Acknowledge the request
    await send_text_message(
        phone_number=phone_number,
        message="🔍 Aapke liye perfect outfit dhundh raha hoon...",
        phone_number_id=tenant.phone_number_id,
    )

    # Build context for the agent
    context = f"Customer message: {text}"
    if skin_tone:
        context += f"\nCustomer's skin tone: {skin_tone}"

    # Call the agent
    result = await agent_call(
        system_prompt=OCCASION_AGENT_SYSTEM_PROMPT,
        user_message=context,
        tools=OCCASION_TOOLS,
        language=language,
    )

    # Process tool calls (max 3)
    tool_call_count = 0
    products_found = []
    tryon_generated = False

    for tool_call in result.get("tool_calls", [])[:MAX_TOOL_CALLS]:
        tool_call_count += 1
        name = tool_call["name"]
        args = tool_call["arguments"]

        try:
            if name == "search_catalog":
                items = await search_catalog(
                    tenant_id=tenant.id,
                    occasion=args.get("occasion"),
                    category=args.get("category"),
                    budget_max=args.get("budget_max"),
                    color_preference=args.get("color_preference"),
                    limit=3,
                )
                products_found = items

                if items:
                    # Send product options to customer
                    product_list = "\n".join(
                        f"• {item['name']} — ₹{item.get('price', 'N/A')}"
                        for item in items[:3]
                    )
                    await send_text_message(
                        phone_number=phone_number,
                        message=f"Yeh rahi options:\n{product_list}",
                        phone_number_id=tenant.phone_number_id,
                    )
                else:
                    await send_text_message(
                        phone_number=phone_number,
                        message="Is occasion ke liye abhi catalog mein items nahi hain 😔",
                        phone_number_id=tenant.phone_number_id,
                    )

            elif name == "check_skin_tone_compatibility":
                compatibility = check_color_compatibility(
                    skin_tone_code=args["skin_tone_code"],
                    garment_colors=args["garment_colors"],
                )
                await send_text_message(
                    phone_number=phone_number,
                    message=compatibility["recommendation"],
                    phone_number_id=tenant.phone_number_id,
                )

            elif name == "generate_tryon":
                product_id = args["product_id"]
                product = await get_catalog_item(tenant.id, product_id)

                if product and session.pending_selfie_url:
                    output_url = await generate(
                        selfie_url=session.pending_selfie_url,
                        product_url=product["image_url"],
                        category=product.get("category", "apparel"),
                    )

                    await send_image_message(
                        phone_number=phone_number,
                        image_url=output_url,
                        caption="🎉 Yeh raha aapka look!",
                        phone_number_id=tenant.phone_number_id,
                    )

                    tryon_generated = True

        except Exception as e:
            logger.error("Agent tool call '%s' failed: %s", name, str(e))

    # Send agent's text response
    if result.get("message"):
        await send_text_message(
            phone_number=phone_number,
            message=result["message"],
            phone_number_id=tenant.phone_number_id,
        )

    # Send post-interaction buttons if no try-on was generated
    if not tryon_generated and products_found:
        await send_interactive_buttons(
            phone_number=phone_number,
            interactive_payload=POST_TRYON_BUTTONS,
            phone_number_id=tenant.phone_number_id,
        )

    # Reset session
    session.reset()

    logger.info(
        "Occasion agent completed — %d tool calls, %d products found",
        tool_call_count,
        len(products_found),
    )
