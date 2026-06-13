"""
ZukoLabs VTO — Intent Router

Classifies incoming messages using Groq and routes to the correct flow.
Checks consent before allowing photo-processing flows.
"""

import logging
from typing import Any, Dict, Optional

from core.constants import Intent, SessionState, MESSAGES
from models.customer import CustomerSession
from models.tenant import Tenant
from services.groq_client import classify_intent

logger = logging.getLogger(__name__)


async def route_message(
    text: str,
    message_type: str,
    session: CustomerSession,
    tenant: Tenant,
    customer_data: Optional[Dict[str, Any]] = None,
    button_reply_id: Optional[str] = None,
    media_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Route an incoming message to the correct flow handler.

    Process:
    1. Handle button replies directly
    2. Check session state for mid-flow routing (e.g., awaiting selfie)
    3. Classify intent via Groq for text messages
    4. Check consent before photo-processing flows
    5. Return routing instructions

    Args:
        text: Message text (or transcription for voice).
        message_type: Message type (text, image, audio, interactive).
        session: Current customer session state.
        tenant: Resolved tenant object.
        customer_data: Customer DB record (for consent check).
        button_reply_id: Interactive button reply ID (if applicable).
        media_id: Media ID for image/audio messages.

    Returns:
        Dict with 'flow' (handler name), 'intent', and additional context.
    """

    # ── 1. Handle interactive button replies ──────────────────
    if button_reply_id:
        return _route_button_reply(button_reply_id, session, tenant)

    # ── 2. Handle mid-flow states ─────────────────────────────
    if session.state == SessionState.AWAITING_SELFIE:
        if message_type == "image" and media_id:
            return {
                "flow": "tryon_flow",
                "action": "receive_selfie",
                "intent": Intent.TRYON_SINGLE,
                "media_id": media_id,
            }
        else:
            return {
                "flow": "tryon_flow",
                "action": "remind_selfie",
                "intent": Intent.TRYON_SINGLE,
                "message": MESSAGES["awaiting_selfie"],
            }

    if session.state == SessionState.AWAITING_CONSENT:
        return {
            "flow": "consent_flow",
            "action": "check_response",
            "intent": Intent.CONSENT_GIVE,
            "text": text,
        }

    if session.state == SessionState.AWAITING_FRIEND_NUMBER:
        return {
            "flow": "friend_share_flow",
            "action": "receive_number",
            "intent": Intent.FRIEND_SHARE,
            "text": text,
        }

    # ── 3. CONSENT GATE ─────────────────────────────────────
    # For users without consent: only allow DELETE and HELP through.
    # Everything else (including greeting, images, try-on) goes to
    # consent_flow first. This prevents the triple-message bug.
    #
    # IMPORTANT: Also catch consent keywords (AGREE, YES, etc.) here
    # so they work even if in-memory session was lost (multi-worker).
    has_consent = customer_data and customer_data.get("consent_given", False)

    if not has_consent:
        if message_type == "text" and text:
            upper = text.strip().upper()

            # Allow deletion even without consent
            if upper in ("DELETE", "MUJHE HATAO", "REMOVE ME"):
                return {
                    "flow": "deletion_flow",
                    "action": "handle",
                    "intent": Intent.CONSENT_WITHDRAW,
                    "text": text,
                }

            # Allow HELP without consent
            if upper in ("HELP", "MADAD"):
                return {
                    "flow": "help_flow",
                    "action": "help",
                    "intent": Intent.HELP,
                    "text": text,
                }

            # Recognize consent keywords (AGREE, YES, OK, HAAN, etc.)
            # This handles the case where session state was lost across
            # workers or restarts — we process AGREE regardless.
            consent_keywords = {
                "AGREE", "I AGREE", "YES", "OK",
                "HAAN", "HA", "हां", "అవును",
                "ஆம்", "OKAY", "SURE",
            }
            if upper in consent_keywords:
                return {
                    "flow": "consent_flow",
                    "action": "check_response",
                    "intent": Intent.CONSENT_GIVE,
                    "text": text,
                }

        # Everything else (greeting, image, product, etc.) → consent first
        return {
            "flow": "consent_flow",
            "action": "request_consent",
            "intent": Intent.GREETING,
            "deferred_media_id": media_id,
        }

    # ── 4. Handle image messages (product photo or selfie) ────
    if message_type == "image" and media_id:
        return {
            "flow": "tryon_flow",
            "action": "receive_product",
            "intent": Intent.TRYON_SINGLE,
            "media_id": media_id,
            "caption": text,
        }

    # ── 5. Handle voice messages ──────────────────────────────
    if message_type == "audio" and media_id:
        # Voice is handled upstream (transcribed before reaching here)
        # If we reach here, transcription failed
        return {
            "flow": "help_flow",
            "action": "voice_not_understood",
            "intent": Intent.UNKNOWN,
        }

    # ── 6. Classify intent for text messages ──────────────────
    if not text:
        return {
            "flow": "help_flow",
            "action": "empty_message",
            "intent": Intent.UNKNOWN,
        }

    language = customer_data.get("language", "en") if customer_data else "en"
    intent = await classify_intent(text, language)

    logger.info("Intent classified: %s for text: '%s...'", intent.value, text[:50])

    # ── 7. Route to the correct flow (consent already verified above) ──────
    flow_map = {
        Intent.TRYON_SINGLE: "tryon_flow",
        Intent.TRYON_OCCASION: "occasion_agent",
        Intent.CONSENT_GIVE: "consent_flow",
        Intent.CONSENT_WITHDRAW: "deletion_flow",
        Intent.CATALOG_BROWSE: "catalog_flow",
        Intent.FIT_CHECK: "fit_verification_flow",
        Intent.FRIEND_SHARE: "friend_share_flow",
        Intent.HELP: "help_flow",
        Intent.GREETING: "help_flow",
        Intent.UNKNOWN: "help_flow",
    }

    flow = flow_map.get(intent, "help_flow")

    # Check if flow requires a plan feature
    feature_map = {
        "occasion_agent": "occasion_agent",
        "fit_verification_flow": "fit_verification",
        "friend_share_flow": "friend_share_loop",
    }

    required_feature = feature_map.get(flow)
    if required_feature and not tenant.has_feature(required_feature):
        return {
            "flow": "help_flow",
            "action": "feature_not_available",
            "intent": intent,
            "feature": required_feature,
        }

    return {
        "flow": flow,
        "action": "handle",
        "intent": intent,
        "text": text,
    }


def _route_button_reply(
    button_id: str,
    session: CustomerSession,
    tenant: Tenant,
) -> Dict[str, Any]:
    """Route interactive button replies to the correct flow."""

    button_routes = {
        "try_another": {
            "flow": "tryon_flow",
            "action": "start_new",
            "intent": Intent.TRYON_SINGLE,
        },
        "view_catalog": {
            "flow": "catalog_flow",
            "action": "browse",
            "intent": Intent.CATALOG_BROWSE,
        },
        "buy_now": {
            "flow": "catalog_flow",
            "action": "buy",
            "intent": Intent.CATALOG_BROWSE,
        },
        "share_friend": {
            "flow": "friend_share_flow",
            "action": "initiate",
            "intent": Intent.FRIEND_SHARE,
        },
    }

    route = button_routes.get(button_id, {
        "flow": "help_flow",
        "action": "unknown_button",
        "intent": Intent.UNKNOWN,
    })

    return route
