"""
ZukoLabs VTO — Fit Verification Flow

Post-purchase fit check using Groq vision analysis.
Sent 2 days after delivery — customer sends a wearing photo
and gets fit feedback + styling tips or return instructions.
Essential/Enterprise plans only.
"""

import logging
from typing import Any, Dict

from models.customer import CustomerSession
from models.tenant import Tenant
from services.groq_client import analyze_fit
from services.whatsapp import send_text_message, download_media

logger = logging.getLogger(__name__)


async def handle_fit_check(
    phone_number: str,
    text: str,
    session: CustomerSession,
    tenant: Tenant,
    customer_data: Dict[str, Any],
    media_id: str = None,
) -> None:
    """
    Handle a fit verification request.

    Flow:
    1. If no wearing photo → ask for one
    2. If wearing photo received → analyze with Groq
    3. If GOOD_FIT → styling suggestions + upsell
    4. If SIZE_ISSUE → offer return flow
    5. If UNCLEAR → ask for better photo

    Args:
        phone_number: Customer's phone number.
        text: Customer's text message.
        session: Customer session.
        tenant: Tenant object.
        customer_data: Customer DB record.
        media_id: Media ID if an image was sent.
    """
    language = customer_data.get("language", "en")

    if not media_id:
        # Ask for a wearing photo
        await send_text_message(
            phone_number=phone_number,
            message=(
                "Aapka order aa gaya! 📦\n"
                "Wearing karke ek photo bhejo — hum check karenge "
                "fit perfect hai ya nahi 😊"
            ),
            phone_number_id=tenant.phone_number_id,
        )
        return

    try:
        # Download wearing photo
        photo_bytes = await download_media(media_id)

        # For now, use text description for analysis
        # In production, this would use Groq's vision capability
        description = text or "Customer sent a wearing photo for fit check"

        # Analyze fit using Groq
        result = await analyze_fit(description, language)
        fit_status = result.get("fit_status", "unclear")

        if fit_status == "good_fit":
            message = result.get(
                "message",
                "Perfect fit lag raha hai! 🎉"
            )
            tips = result.get("styling_tips", [])
            if tips:
                message += "\n\nStyling tips:\n" + "\n".join(
                    f"• {tip}" for tip in tips
                )
            message += "\n\nMatching dupatta dekhna hai? MATCH bhejo 🛍️"

            await send_text_message(
                phone_number=phone_number,
                message=message,
                phone_number_id=tenant.phone_number_id,
            )

        elif fit_status == "size_issue":
            issue = result.get("issue", "")
            message = result.get(
                "message",
                f"Haan, size thoda {issue} lag raha hai."
            )
            message += "\nReturn ke liye RETURN bhejo — hum process kar denge"

            await send_text_message(
                phone_number=phone_number,
                message=message,
                phone_number_id=tenant.phone_number_id,
            )

        else:  # unclear
            await send_text_message(
                phone_number=phone_number,
                message=(
                    "Thoda better photo bhejo? "
                    "Good lighting mein, full length 📸"
                ),
                phone_number_id=tenant.phone_number_id,
            )

        logger.info(
            "Fit check result: %s (tenant: %s)",
            fit_status,
            tenant.business_name,
        )

    except Exception as e:
        logger.error("Fit verification failed: %s", str(e))
        await send_text_message(
            phone_number=phone_number,
            message="Fit check mein error aaya. Ek aur photo try karo? 📸",
            phone_number_id=tenant.phone_number_id,
        )

    # Reset session
    session.reset()


async def send_fit_check_reminder(
    phone_number: str,
    tenant: Tenant,
) -> None:
    """
    Send automated fit check reminder 2 days after delivery.
    Called by a scheduled task (not by webhook).

    Args:
        phone_number: Customer's phone number.
        tenant: Tenant object.
    """
    await send_text_message(
        phone_number=phone_number,
        message=(
            "Aapka order aa gaya! 📦\n"
            "Wearing karke ek photo bhejo — hum check karenge "
            "fit perfect hai ya nahi 😊"
        ),
        phone_number_id=tenant.phone_number_id,
    )
