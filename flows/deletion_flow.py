"""
ZukoLabs VTO — Deletion Flow (DPDP Right to Erasure)

Handles data deletion requests. Must complete within 5 seconds (target)
and 90 days (DPDP maximum). Consent log records are NEVER deleted
(7-year retention requirement).
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from core.constants import ConsentAction, MESSAGES
from core.database import get_db
from models.customer import CustomerSession
from models.tenant import Tenant
from services.image_store import delete_customer_images
from services.whatsapp import send_text_message

logger = logging.getLogger(__name__)


async def handle_deletion(
    phone_number: str,
    phone_hash: str,
    session: CustomerSession,
    tenant: Tenant,
    customer_data: Dict[str, Any],
) -> None:
    """
    Handle a data deletion request (DPDP Right to Erasure).

    Process:
    1. Delete all tryon_jobs for this customer
    2. Delete output images from Supabase Storage
    3. Reset customer consent (consent_given = false)
    4. Insert consent_log record (action: 'deleted')
    5. Keep consent_log records (7-year legal requirement)
    6. Send confirmation message

    Args:
        phone_number: Customer's phone number.
        phone_hash: SHA-256 hash of the phone number.
        session: Customer session.
        tenant: Tenant object.
        customer_data: Customer DB record.
    """
    db = get_db()
    customer_id = customer_data.get("id")
    now = datetime.now(timezone.utc).isoformat()

    try:
        # 1. Delete all try-on jobs (soft delete with audit trail)
        if customer_id:
            db.table("tryon_jobs").update({
                "deleted_at": now,
                "selfie_path": None,
                "output_path": None,
                "output_url": None,
            }).eq(
                "customer_id", customer_id
            ).eq(
                "tenant_id", tenant.id
            ).execute()

            logger.info(
                "Soft-deleted tryon_jobs for customer %s",
                customer_id,
            )

        # 2. Delete images from storage
        if customer_id:
            deleted_count = await delete_customer_images(
                tenant_id=tenant.id,
                customer_id=customer_id,
            )
            logger.info(
                "Deleted %d images for customer %s",
                deleted_count,
                customer_id,
            )

        # 3. Reset customer consent and clear personal data
        if customer_id:
            db.table("customers").update({
                "consent_given": False,
                "consent_at": None,
                "skin_tone_code": None,
                "last_active": None,
            }).eq(
                "id", customer_id
            ).eq(
                "tenant_id", tenant.id
            ).execute()

        # 4. Insert consent_log record (audit trail — NEVER delete)
        db.table("consent_log").insert({
            "tenant_id": tenant.id,
            "phone_hash": phone_hash,
            "action": ConsentAction.DELETED.value,
            "purpose": "virtual_tryon",
            "timestamp": now,
        }).execute()

        # 5. Send confirmation
        await send_text_message(
            phone_number=phone_number,
            message=MESSAGES["deletion_complete"],
            phone_number_id=tenant.phone_number_id,
        )

        # Reset session
        session.reset()

        logger.info(
            "Data deletion completed for customer (tenant: %s)",
            tenant.business_name,
        )

    except Exception as e:
        logger.error(
            "Data deletion failed for customer: %s",
            str(e),
        )

        await send_text_message(
            phone_number=phone_number,
            message=(
                "Data deletion mein error aaya. 😔 "
                "Please dobara try karo ya seller se contact karo."
            ),
            phone_number_id=tenant.phone_number_id,
        )
