"""
ZukoLabs VTO — Help Flow

Handles help requests, greetings, and unknown intents.
Sends interactive buttons for help menu (Try Outfit, Delete Data, Catalog).
All messages are language-aware.
"""

import logging
from typing import Any, Dict

from core.constants import get_message, get_help_buttons
from models.customer import CustomerSession
from models.tenant import Tenant
from services.whatsapp import send_text_message, send_interactive_buttons

logger = logging.getLogger(__name__)


async def handle_help(
    phone_number: str,
    tenant: Tenant,
    action: str = "help",
    language: str = "en",
) -> None:
    """
    Handle help, greeting, and unknown intent messages.

    Args:
        phone_number: Customer's phone number.
        tenant: Tenant object.
        action: The specific action (help, greeting, unknown, etc.).
        language: Customer's language code (en, hi, te, ta).
    """
    if action == "greeting":
        # Use custom greeting if tenant has one, otherwise language-aware default
        if tenant.settings.custom_greeting:
            message = tenant.settings.custom_greeting
        else:
            message = get_message(
                "greeting", language, business_name=tenant.business_name
            )
        await send_text_message(
            phone_number=phone_number,
            message=message,
            phone_number_id=tenant.phone_number_id,
        )

    elif action == "help":
        # Send interactive help buttons instead of plain text
        help_buttons = get_help_buttons(language)

        # Add plan-specific info as header text
        header_text = f"*{tenant.business_name}* Virtual Try-On 👕"
        help_buttons["interactive"]["header"] = {
            "type": "text",
            "text": header_text,
        }

        # Add extra feature info to body if available
        body_parts = [get_message("help", language)]

        if tenant.has_feature("occasion_agent"):
            occasion_labels = {
                "en": "\n🎉 *Occasion Outfit* — send 'wedding outfit' or 'office look'",
                "hi": "\n🎉 *Occasion Outfit* — 'wedding outfit' ya 'office look' bhejo",
                "te": "\n🎉 *Occasion Outfit* — 'wedding outfit' లేదా 'office look' పంపండి",
                "ta": "\n🎉 *Occasion Outfit* — 'wedding outfit' அல்லது 'office look' அனுப்புங்கள்",
            }
            body_parts.append(occasion_labels.get(language, occasion_labels["en"]))

        if tenant.has_feature("fit_verification"):
            fit_labels = {
                "en": "📐 *Fit Check* — send your wearing photo",
                "hi": "📐 *Fit Check* — wearing photo bhejo",
                "te": "📐 *Fit Check* — wearing photo పంపండి",
                "ta": "📐 *Fit Check* — wearing photo அனுப்புங்கள்",
            }
            body_parts.append(fit_labels.get(language, fit_labels["en"]))

        help_buttons["interactive"]["body"]["text"] = "\n".join(body_parts)

        await send_interactive_buttons(
            phone_number=phone_number,
            interactive_payload=help_buttons,
            phone_number_id=tenant.phone_number_id,
        )

    elif action == "feature_not_available":
        await send_text_message(
            phone_number=phone_number,
            message=get_message(
                "feature_not_available",
                language,
                business_name=tenant.business_name,
            ),
            phone_number_id=tenant.phone_number_id,
        )

    elif action == "voice_not_understood":
        await send_text_message(
            phone_number=phone_number,
            message=get_message("voice_not_understood", language),
            phone_number_id=tenant.phone_number_id,
        )

    elif action == "empty_message":
        await send_text_message(
            phone_number=phone_number,
            message=get_message("empty_message", language),
            phone_number_id=tenant.phone_number_id,
        )

    else:
        # Unknown intent
        await send_text_message(
            phone_number=phone_number,
            message=get_message("unknown_intent", language),
            phone_number_id=tenant.phone_number_id,
        )

    logger.debug("Help flow: action=%s, tenant=%s, lang=%s", action, tenant.business_name, language)
