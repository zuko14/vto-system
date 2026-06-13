"""
ZukoLabs VTO — Help Flow

Handles help requests, greetings, and unknown intents.
Sends capability listing and usage instructions.
All messages are language-aware.
"""

import logging
from typing import Any, Dict

from core.constants import get_message
from models.customer import CustomerSession
from models.tenant import Tenant
from services.whatsapp import send_text_message

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
        # Build help message based on tenant's plan features
        help_text = _build_help_message(tenant, language)
        await send_text_message(
            phone_number=phone_number,
            message=help_text,
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


def _build_help_message(tenant: Tenant, language: str = "en") -> str:
    """
    Build a help message customized for the tenant's plan features.

    Args:
        tenant: Tenant object.
        language: Customer's language code.

    Returns:
        Formatted help text.
    """
    lines = [
        f"*{tenant.business_name}* Virtual Try-On 👕\n",
    ]

    # Add base help message
    lines.append(get_message("help", language))

    # Add plan-specific features
    categories = tenant.supported_categories

    extra = []
    if tenant.has_feature("occasion_agent"):
        occasion_labels = {
            "en": "\n🎉 *Occasion Outfit* — send 'wedding outfit' or 'office look'",
            "hi": "\n🎉 *Occasion Outfit* — 'wedding outfit' ya 'office look' bhejo",
            "te": "\n🎉 *Occasion Outfit* — 'wedding outfit' లేదా 'office look' పంపండి",
            "ta": "\n🎉 *Occasion Outfit* — 'wedding outfit' அல்லது 'office look' அனுப்புங்கள்",
        }
        extra.append(occasion_labels.get(language, occasion_labels["en"]))

    if tenant.has_feature("fit_verification"):
        fit_labels = {
            "en": "📐 *Fit Check* — send your wearing photo",
            "hi": "📐 *Fit Check* — wearing photo bhejo",
            "te": "📐 *Fit Check* — wearing photo పంపండి",
            "ta": "📐 *Fit Check* — wearing photo அனுப்புங்கள்",
        }
        extra.append(fit_labels.get(language, fit_labels["en"]))

    if extra:
        lines.extend(extra)

    return "\n".join(lines)
