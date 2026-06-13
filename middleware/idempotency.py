"""
ZukoLabs VTO — Idempotency Middleware

Ensures each WhatsApp message is processed exactly once.
Meta may deliver the same webhook multiple times — this deduplicates.
"""

import logging
from datetime import datetime, timezone

from core.database import get_db

logger = logging.getLogger(__name__)


async def is_duplicate(message_id: str, tenant_id: str = None) -> bool:
    """
    Check if a message has already been processed.
    If not, mark it as processed immediately (before actual processing)
    to prevent race conditions with duplicate deliveries.

    Args:
        message_id: The unique message ID from Meta's webhook payload.
        tenant_id: Optional tenant ID for the processed_messages record.

    Returns:
        True if this message was already processed (skip it).
        False if this is a new message (proceed with processing).
    """
    db = get_db()

    try:
        # Check if message already exists
        result = (
            db.table("processed_messages")
            .select("message_id")
            .eq("message_id", message_id)
            .execute()
        )

        if result.data:
            logger.info("Duplicate message detected: %s — skipping", message_id)
            return True

        # Insert immediately BEFORE processing to claim this message.
        # If another webhook delivery arrives, it will find this record.
        insert_data = {
            "message_id": message_id,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        if tenant_id:
            insert_data["tenant_id"] = tenant_id

        db.table("processed_messages").insert(insert_data).execute()

        logger.debug("Message %s marked for processing", message_id)
        return False

    except Exception as e:
        # On DB error, allow processing (better to double-process than drop)
        logger.error(
            "Idempotency check failed for message %s: %s — allowing processing",
            message_id,
            str(e),
        )
        return False
