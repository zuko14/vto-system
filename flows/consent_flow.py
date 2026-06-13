"""
ZukoLabs VTO — Consent Flow

DPDP-compliant consent collection and management.
Consent must be explicit ("AGREE") — never implied by sending a photo.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from core.constants import (
    ConsentAction,
    SessionState,
    CONSENT_TEMPLATES,
    MESSAGES,
)
from core.database import get_db
from models.customer import CustomerSession
from models.tenant import Tenant
from services.whatsapp import send_text_message

logger = logging.getLogger(__name__)


async def request_consent(
    phone_number: str,
    tenant: Tenant,
    session: CustomerSession,
    language: str = "en",
) -> None:
    """
    Send the consent message to a customer and set session to AWAITING_CONSENT.

    Consent is sent ONCE per customer per tenant. Re-consent required if
    customer hasn't interacted in 12 months.

    Args:
        phone_number: Customer's phone number.
        tenant: The tenant object.
        session: Customer session to update.
        language: Customer's preferred language.
    """
    # Get consent template in customer's language
    template = CONSENT_TEMPLATES.get(language, CONSENT_TEMPLATES["en"])

    # Replace privacy URL placeholder
    privacy_url = tenant.settings.privacy_url or "https://zukolabs.com/privacy"
    consent_message = template.format(privacy_url=privacy_url)

    await send_text_message(
        phone_number=phone_number,
        message=consent_message,
        phone_number_id=tenant.phone_number_id,
    )

    # Update session state
    session.state = SessionState.AWAITING_CONSENT

    logger.info(
        "Consent requested for phone hash (tenant: %s, lang: %s)",
        tenant.business_name,
        language,
    )


async def handle_consent_response(
    phone_number: str,
    phone_hash: str,
    text: str,
    tenant: Tenant,
    session: CustomerSession,
    customer_id: Optional[str] = None,
) -> bool:
    """
    Process the customer's response to the consent message.

    Only explicit "AGREE" is accepted. Everything else is treated as decline.

    Args:
        phone_number: Customer's phone number.
        phone_hash: SHA-256 hash of the phone number.
        text: Customer's reply text.
        tenant: The tenant object.
        session: Customer session.
        customer_id: Customer UUID (if already exists in DB).

    Returns:
        True if consent was given, False otherwise.
    """
    # Normalize response
    response = text.strip().upper() if text else ""

    # Accept "AGREE", "I AGREE", "YES", "OK", "HAAN"
    consent_keywords = {"AGREE", "I AGREE", "YES", "OK", "HAAN", "HA", "हां", "అవును"}

    if response in consent_keywords:
        # Record consent in database
        await _record_consent(
            phone_hash=phone_hash,
            tenant_id=tenant.id,
            customer_id=customer_id,
            action=ConsentAction.GIVEN,
        )

        # Send confirmation
        await send_text_message(
            phone_number=phone_number,
            message=(
                "Thank you! ✅ Ab aap virtual try-on use kar sakte ho. "
                "Koi bhi outfit photo bhejo! 👗"
            ),
            phone_number_id=tenant.phone_number_id,
        )

        # Reset session to IDLE so deferred flow can proceed
        session.state = SessionState.IDLE

        logger.info(
            "Consent given by customer (tenant: %s)",
            tenant.business_name,
        )
        return True

    else:
        # Consent declined
        await send_text_message(
            phone_number=phone_number,
            message=MESSAGES["consent_declined"],
            phone_number_id=tenant.phone_number_id,
        )

        session.state = SessionState.IDLE

        logger.info(
            "Consent declined by customer (tenant: %s)",
            tenant.business_name,
        )
        return False


async def _record_consent(
    phone_hash: str,
    tenant_id: str,
    customer_id: Optional[str],
    action: ConsentAction,
) -> None:
    """
    Record consent action in the database.

    Updates customer record AND inserts an audit log entry.
    Consent log records are retained for 7 years (legal requirement).

    Args:
        phone_hash: SHA-256 hash of customer phone.
        tenant_id: Tenant UUID.
        customer_id: Customer UUID (if exists).
        action: The consent action being recorded.
    """
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    try:
        # Update or create customer record
        if customer_id:
            db.table("customers").update({
                "consent_given": action == ConsentAction.GIVEN,
                "consent_at": now if action == ConsentAction.GIVEN else None,
                "last_active": now,
            }).eq("id", customer_id).eq("tenant_id", tenant_id).execute()
        else:
            # Create new customer record
            db.table("customers").insert({
                "tenant_id": tenant_id,
                "phone_hash": phone_hash,
                "consent_given": action == ConsentAction.GIVEN,
                "consent_at": now if action == ConsentAction.GIVEN else None,
                "last_active": now,
            }).execute()

        # Insert consent log entry (audit trail — NEVER delete these)
        db.table("consent_log").insert({
            "tenant_id": tenant_id,
            "phone_hash": phone_hash,
            "action": action.value,
            "purpose": "virtual_tryon",
            "timestamp": now,
        }).execute()

        logger.info(
            "Consent %s recorded for phone_hash (tenant: %s)",
            action.value,
            tenant_id,
        )

    except Exception as e:
        logger.error("Failed to record consent: %s", str(e))
        raise


async def check_consent(
    phone_hash: str,
    tenant_id: str,
) -> dict:
    """
    Check if a customer has given consent.

    Args:
        phone_hash: SHA-256 hash of customer phone.
        tenant_id: Tenant UUID.

    Returns:
        Dict with 'consent_given' (bool), 'customer_id' (str or None),
        and 'needs_reconsent' (bool).
    """
    db = get_db()

    try:
        result = (
            db.table("customers")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("phone_hash", phone_hash)
            .execute()
        )

        if not result.data:
            return {
                "consent_given": False,
                "customer_id": None,
                "needs_reconsent": False,
            }

        customer = result.data[0]
        consent_given = customer.get("consent_given", False)

        # Check if re-consent is needed (12 months inactive)
        needs_reconsent = False
        if consent_given and customer.get("last_active"):
            try:
                last_active = datetime.fromisoformat(
                    customer["last_active"].replace("Z", "+00:00")
                )
                months_inactive = (
                    datetime.now(timezone.utc) - last_active
                ).days / 30
                if months_inactive > 12:
                    needs_reconsent = True
            except (ValueError, TypeError):
                pass

        return {
            "consent_given": consent_given and not needs_reconsent,
            "customer_id": customer.get("id"),
            "needs_reconsent": needs_reconsent,
        }

    except Exception as e:
        logger.error("Consent check failed: %s", str(e))
        return {
            "consent_given": False,
            "customer_id": None,
            "needs_reconsent": False,
        }
