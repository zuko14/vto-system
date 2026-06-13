"""
ZukoLabs VTO — Help Flow

Handles help requests, greetings, and unknown intents.
Sends capability listing and usage instructions.
"""

import logging
from typing import Any, Dict

from core.constants import MESSAGES
from models.customer import CustomerSession
from models.tenant import Tenant
from services.whatsapp import send_text_message

logger = logging.getLogger(__name__)


async def handle_help(
    phone_number: str,
    tenant: Tenant,
    action: str = "help",
) -> None:
    """
    Handle help, greeting, and unknown intent messages.

    Args:
        phone_number: Customer's phone number.
        tenant: Tenant object.
        action: The specific action (help, greeting, unknown, etc.).
    """
    if action == "greeting":
        # Use custom greeting if tenant has one, otherwise default
        greeting = (
            tenant.settings.custom_greeting
            or MESSAGES["greeting"]
        )
        await send_text_message(
            phone_number=phone_number,
            message=greeting,
            phone_number_id=tenant.phone_number_id,
        )

    elif action == "help":
        # Build help message based on tenant's plan features
        help_text = _build_help_message(tenant)
        await send_text_message(
            phone_number=phone_number,
            message=help_text,
            phone_number_id=tenant.phone_number_id,
        )

    elif action == "feature_not_available":
        await send_text_message(
            phone_number=phone_number,
            message=(
                "Yeh feature aapke current plan mein available nahi hai. 😊\n"
                f"{tenant.business_name} se baat karo upgrade ke liye!"
            ),
            phone_number_id=tenant.phone_number_id,
        )

    elif action == "voice_not_understood":
        await send_text_message(
            phone_number=phone_number,
            message=(
                "Voice message samajh nahi aaya 😅\n"
                "Text mein bhejo ya 'help' likh ke bhejo."
            ),
            phone_number_id=tenant.phone_number_id,
        )

    elif action == "empty_message":
        await send_text_message(
            phone_number=phone_number,
            message="Kuch to bhejo! 😄 'help' bhejo options dekhne ke liye.",
            phone_number_id=tenant.phone_number_id,
        )

    else:
        # Unknown intent
        await send_text_message(
            phone_number=phone_number,
            message=MESSAGES["unknown_intent"],
            phone_number_id=tenant.phone_number_id,
        )

    logger.debug("Help flow: action=%s, tenant=%s", action, tenant.business_name)


def _build_help_message(tenant: Tenant) -> str:
    """
    Build a help message customized for the tenant's plan features.

    Args:
        tenant: Tenant object.

    Returns:
        Formatted help text.
    """
    lines = [
        f"*{tenant.business_name}* Virtual Try-On 👗\n",
        "Main kya kar sakta hoon:\n",
        "👗 *Outfit Try-On* — Product photo bhejo",
    ]

    # Add plan-specific features
    categories = tenant.supported_categories
    if "jewelry" in categories:
        lines.append("💍 *Jewellery Try-On*")
    if "eyewear" in categories:
        lines.append("👓 *Eyewear Try-On*")
    if "footwear" in categories:
        lines.append("👟 *Footwear Try-On*")
    if "watch" in categories:
        lines.append("⌚ *Watch Try-On*")
    if "makeup" in categories:
        lines.append("💄 *Makeup Try-On*")

    if tenant.has_feature("occasion_agent"):
        lines.append("\n🎉 *Occasion Outfit* — 'wedding outfit' ya 'office look' bhejo")

    if tenant.has_feature("fit_verification"):
        lines.append("📐 *Fit Check* — Wearing photo bhejo")

    if tenant.catalog_enabled:
        lines.append("\n🛍️ *Catalog* — CATALOG bhejo")

    lines.extend([
        "\n🗑️ *Data Delete* — DELETE bhejo",
        "❓ *Help* — HELP bhejo",
    ])

    return "\n".join(lines)
