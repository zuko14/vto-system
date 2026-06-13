"""
ZukoLabs VTO — Webhook Security

HMAC SHA-256 signature verification for Meta WhatsApp Cloud API webhooks.
Rejects tampered payloads while still returning 200 to Meta.
"""

import hashlib
import hmac
import logging

from core.config import get_settings

logger = logging.getLogger(__name__)


def verify_webhook_signature(payload: bytes, signature_header: str) -> bool:
    """
    Verify the X-Hub-Signature-256 header from Meta webhook payloads.

    Args:
        payload: Raw request body bytes.
        signature_header: Value of the X-Hub-Signature-256 header
                         (format: "sha256=<hex_digest>").

    Returns:
        True if signature is valid, False otherwise.
    """
    if not signature_header:
        logger.warning("Missing X-Hub-Signature-256 header")
        return False

    settings = get_settings()
    if not settings.whatsapp_app_secret:
        logger.error("WHATSAPP_APP_SECRET not configured — cannot verify signatures")
        return False

    # Meta sends: "sha256=<hex_digest>"
    try:
        algorithm, expected_signature = signature_header.split("=", 1)
    except ValueError:
        logger.warning("Malformed signature header: %s", signature_header)
        return False

    if algorithm != "sha256":
        logger.warning("Unexpected signature algorithm: %s", algorithm)
        return False

    # Compute HMAC
    computed_signature = hmac.new(
        key=settings.whatsapp_app_secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison to prevent timing attacks
    is_valid = hmac.compare_digest(computed_signature, expected_signature)

    if not is_valid:
        logger.warning("Invalid webhook signature — possible tampering")

    return is_valid


def hash_phone_number(phone_number: str) -> str:
    """
    Hash a phone number using SHA-256.
    NEVER store raw phone numbers in the database — DPDP compliance.

    Args:
        phone_number: Raw phone number string.

    Returns:
        SHA-256 hex digest of the phone number.
    """
    return hashlib.sha256(phone_number.encode("utf-8")).hexdigest()
