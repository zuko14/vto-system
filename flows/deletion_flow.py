"""
ZukoLabs VTO — Deletion Flow (DPDP Right to Erasure)

Handles data deletion requests. Fully removes all customer data
from Supabase (customer row, tryon_jobs, images). After deletion,
the same phone number will start fresh from language selection.

Consent log records are retained for audit (7-year requirement)
but only store the phone_hash — no PII.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from core.constants import ConsentAction, get_message
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
    language: str = "en",
) -> None:
    """
    Handle a data deletion request (DPDP Right to Erasure).

    Process:
    1. Hard-delete all tryon_jobs for this customer
    2. Delete output images from Supabase Storage
    3. Hard-delete the customer row from the customers table
    4. Insert consent_log record (action: 'deleted') — audit trail only
    5. Clear in-memory session so next message starts fresh
    6. Send confirmation message

    Args:
        phone_number: Customer's phone number.
        phone_hash: SHA-256 hash of the phone number.
        session: Customer session.
        tenant: Tenant object.
        customer_data: Customer DB record.
        language: Customer's preferred language code.
    """
    db = get_db()
    customer_id = customer_data.get("id")
    now = datetime.now(timezone.utc).isoformat()

    try:
        # 1. Hard-delete all try-on jobs
        if customer_id:
            db.table("tryon_jobs").delete().eq(
                "customer_id", customer_id
            ).eq(
                "tenant_id", tenant.id
            ).execute()

            logger.info(
                "Hard-deleted tryon_jobs for customer %s",
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

        # 3. Hard-delete the customer row (phone_hash, language, consent, etc.)
        if customer_id:
            db.table("customers").delete().eq(
                "id", customer_id
            ).eq(
                "tenant_id", tenant.id
            ).execute()

            logger.info(
                "Hard-deleted customer row %s for tenant %s",
                customer_id,
                tenant.id,
            )

        # 4. Insert consent_log record (audit trail — NEVER delete)
        # Only stores phone_hash (not raw phone number) — no PII
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
            message=get_message("deletion_complete", language),
            phone_number_id=tenant.phone_number_id,
        )

        # 6. Reset in-memory session completely
        session.reset()

        # 7. Also remove from the session cache so next message creates a fresh session
        _invalidate_session_cache(phone_hash, tenant.id)

        logger.info(
            "Full data deletion completed for customer (tenant: %s)",
            tenant.business_name,
        )

    except Exception as e:
        logger.error(
            "Data deletion failed for customer: %s",
            str(e),
            exc_info=True,
        )

        await send_text_message(
            phone_number=phone_number,
            message=get_message("unknown_error", language),
            phone_number_id=tenant.phone_number_id,
        )


def _invalidate_session_cache(phone_hash: str, tenant_id: str) -> None:
    """
    Remove a customer's session from the in-memory session cache.
    This forces a fresh session on their next message.
    """
    try:
        from api.webhook import _sessions
        key = f"{tenant_id}:{phone_hash}"
        if key in _sessions:
            del _sessions[key]
            logger.debug("Invalidated session cache for %s", key)
    except ImportError:
        logger.warning("Could not import _sessions for cache invalidation")
