"""
ZukoLabs VTO — Intent Router

Classifies incoming messages using Groq and routes to the correct flow.
New user flow: Language Selection → Consent → Main flows.

KEY DESIGN: Every mid-flow state has escape hatches for "help", "delete",
"cancel" — users are never trapped in a state machine loop.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from core.constants import Intent, SessionState, MESSAGES, LANGUAGE_BUTTON_MAP, get_image_type_buttons
from models.customer import CustomerSession
from models.tenant import Tenant
from services.groq_client import classify_intent

logger = logging.getLogger(__name__)

# ── Global escape keywords ────────────────────────────────────
# These keywords ALWAYS break out of mid-flow states
_HELP_KEYWORDS = {"HELP", "MADAD", "MENU", "OPTIONS"}
_DELETE_KEYWORDS = {"DELETE", "MUJHE HATAO", "REMOVE ME", "DATA DELETE"}
_CANCEL_KEYWORDS = {"CANCEL", "BACK", "STOP", "QUIT", "EXIT", "RESET"}

# Session timeout in seconds (30 minutes)
_SESSION_TIMEOUT_SECONDS = 30 * 60


def _check_session_timeout(session: CustomerSession) -> bool:
    """
    Check if a session has timed out (30 minutes of inactivity).
    Returns True if the session was expired and reset.
    """
    if session.state == SessionState.IDLE:
        return False

    elapsed = (datetime.now(timezone.utc) - session.last_updated).total_seconds()
    if elapsed > _SESSION_TIMEOUT_SECONDS:
        logger.info(
            "Session timed out (%.0fs idle, state=%s) — resetting to IDLE",
            elapsed,
            session.state.value,
        )
        session.reset()
        return True
    return False


def _check_escape_keywords(text: str, session: CustomerSession) -> Optional[Dict[str, Any]]:
    """
    Check if a text message is a global escape keyword.
    If so, reset the session and return the appropriate route.
    Returns None if no escape keyword matched.
    """
    if not text:
        return None

    upper = text.strip().upper()

    # Help escape — always works, resets session
    if upper in _HELP_KEYWORDS:
        session.reset()
        return {
            "flow": "help_flow",
            "action": "help",
            "intent": Intent.HELP,
        }

    # Delete escape — always works, resets to deletion flow
    if upper in _DELETE_KEYWORDS:
        session.reset()
        return {
            "flow": "deletion_flow",
            "action": "confirm",
            "intent": Intent.CONSENT_WITHDRAW,
            "text": text,
        }

    # Cancel escape — resets session, shows greeting
    if upper in _CANCEL_KEYWORDS:
        session.reset()
        return {
            "flow": "help_flow",
            "action": "greeting",
            "intent": Intent.GREETING,
        }

    return None


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

    Flow for new users:
    1. Language picker (3 buttons: English / हिंदी / తెలుగు)
    2. Consent request (in selected language)
    3. Main flow routing

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

    # ── 0. Session timeout check ─────────────────────────────
    if _check_session_timeout(session):
        # Session was expired — treat as fresh message
        # Send a session expired notification then process normally
        return {
            "flow": "help_flow",
            "action": "session_expired",
            "intent": Intent.GREETING,
        }

    # ── 1. Handle language picker button replies ──────────────
    if button_reply_id and button_reply_id in LANGUAGE_BUTTON_MAP:
        selected_lang = LANGUAGE_BUTTON_MAP[button_reply_id]
        session.pending_language = selected_lang
        session.state = SessionState.AWAITING_CONSENT
        return {
            "flow": "consent_flow",
            "action": "request_consent",
            "intent": Intent.GREETING,
            "language_override": selected_lang,
        }

    # ── 2. Handle other interactive button replies ────────────
    if button_reply_id:
        return _route_button_reply(button_reply_id, session, tenant)

    # ── 3. Handle mid-flow states (with escape hatches) ───────

    # -- Check escape keywords for ALL mid-flow states --
    if session.state not in (SessionState.IDLE, SessionState.AWAITING_CONSENT) and message_type == "text":
        escape = _check_escape_keywords(text, session)
        if escape:
            return escape

    # -- AWAITING_LANGUAGE --
    if session.state == SessionState.AWAITING_LANGUAGE:
        if message_type == "text" and text:
            upper = text.strip().upper()
            lang_text_map = {
                "ENGLISH": "en", "ENG": "en", "EN": "en", "1": "en",
                "HINDI": "hi", "HIND": "hi", "HI": "hi", "2": "hi",
                "हिंदी": "hi", "हिन्दी": "hi",
                "TELUGU": "te", "TEL": "te", "TE": "te", "3": "te",
                "తెలుగు": "te",
            }
            selected = lang_text_map.get(upper)
            if selected:
                session.pending_language = selected
                session.state = SessionState.AWAITING_CONSENT
                return {
                    "flow": "consent_flow",
                    "action": "request_consent",
                    "intent": Intent.GREETING,
                    "language_override": selected,
                }
        # Didn't understand — re-send language picker
        return {
            "flow": "language_flow",
            "action": "send_picker",
            "intent": Intent.GREETING,
        }

    # -- AWAITING_IMAGE_TYPE --
    if session.state == SessionState.AWAITING_IMAGE_TYPE:
        # If they send another image, update pending media and re-ask type
        if message_type == "image" and media_id:
            session.pending_media_id = media_id
            session.pending_media_caption = text
            return {
                "flow": "image_type_flow",
                "action": "ask_type",
                "intent": Intent.TRYON_SINGLE,
            }

        # Text messages in this state: try to match common responses
        if message_type == "text" and text:
            upper = text.strip().upper()
            # User might type "selfie", "my photo", "outfit", "product"
            selfie_keywords = {"SELFIE", "MY PHOTO", "PHOTO", "MERI PHOTO", "FACE"}
            outfit_keywords = {"OUTFIT", "PRODUCT", "DRESS", "CLOTH", "GARMENT", "CLOTHES"}
            if upper in selfie_keywords or any(kw in upper for kw in selfie_keywords):
                return {
                    "flow": "image_type_flow",
                    "action": "handle_selection",
                    "intent": Intent.TRYON_SINGLE,
                    "button_id": "type_selfie",
                }
            if upper in outfit_keywords or any(kw in upper for kw in outfit_keywords):
                return {
                    "flow": "image_type_flow",
                    "action": "handle_selection",
                    "intent": Intent.TRYON_SINGLE,
                    "button_id": "type_product",
                }

        # Fallback: re-ask the type with buttons
        return {
            "flow": "image_type_flow",
            "action": "ask_type",
            "intent": Intent.UNKNOWN,
        }

    # -- AWAITING_SELFIE --
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
            }

    # -- AWAITING_PRODUCT --
    if session.state == SessionState.AWAITING_PRODUCT:
        if message_type == "image" and media_id:
            return {
                "flow": "tryon_flow",
                "action": "receive_product",
                "intent": Intent.TRYON_SINGLE,
                "media_id": media_id,
                "caption": text,
            }
        else:
            return {
                "flow": "tryon_flow",
                "action": "remind_product",
                "intent": Intent.TRYON_SINGLE,
            }

    # -- AWAITING_CONSENT --
    if session.state == SessionState.AWAITING_CONSENT:
        # Allow DELETE even during consent flow
        if message_type == "text" and text:
            upper = text.strip().upper()
            if upper in _DELETE_KEYWORDS:
                session.reset()
                return {
                    "flow": "deletion_flow",
                    "action": "confirm",
                    "intent": Intent.CONSENT_WITHDRAW,
                    "text": text,
                }
        return {
            "flow": "consent_flow",
            "action": "check_response",
            "intent": Intent.CONSENT_GIVE,
            "text": text,
        }

    # -- AWAITING_DELETION_CONFIRM --
    if session.state == SessionState.AWAITING_DELETION_CONFIRM:
        # Only accept text confirmation, otherwise re-ask
        if message_type == "text" and text:
            upper = text.strip().upper()
            confirm_keywords = {"YES", "CONFIRM", "HAAN", "HA", "हां", "అవును", "ஆம்", "DELETE"}
            cancel_keywords = {"NO", "CANCEL", "NAHI", "BACK", "NOPE"}
            if upper in confirm_keywords:
                session.reset()
                return {
                    "flow": "deletion_flow",
                    "action": "execute",
                    "intent": Intent.CONSENT_WITHDRAW,
                }
            if upper in cancel_keywords:
                session.reset()
                return {
                    "flow": "deletion_flow",
                    "action": "cancelled",
                    "intent": Intent.UNKNOWN,
                }
        # Unrecognized — re-ask
        return {
            "flow": "deletion_flow",
            "action": "confirm",
            "intent": Intent.CONSENT_WITHDRAW,
        }

    # -- AWAITING_FRIEND_NUMBER --
    if session.state == SessionState.AWAITING_FRIEND_NUMBER:
        return {
            "flow": "friend_share_flow",
            "action": "receive_number",
            "intent": Intent.FRIEND_SHARE,
            "text": text,
        }

    # ── 4. CONSENT GATE ─────────────────────────────────────
    has_consent = customer_data and customer_data.get("consent_given", False)
    has_language = customer_data and customer_data.get("language")

    if not has_consent:
        if message_type == "text" and text:
            upper = text.strip().upper()

            # Allow deletion even without consent
            if upper in _DELETE_KEYWORDS:
                return {
                    "flow": "deletion_flow",
                    "action": "confirm",
                    "intent": Intent.CONSENT_WITHDRAW,
                    "text": text,
                }

            # Allow HELP without consent
            if upper in _HELP_KEYWORDS:
                return {
                    "flow": "help_flow",
                    "action": "help",
                    "intent": Intent.HELP,
                    "text": text,
                }

            # Recognize consent keywords (AGREE, YES, etc.)
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

        # New user with no language selected → show language picker first
        if not has_language and session.pending_language is None:
            session.state = SessionState.AWAITING_LANGUAGE
            return {
                "flow": "language_flow",
                "action": "send_picker",
                "intent": Intent.GREETING,
            }

        # Has language but no consent → send consent in their language
        return {
            "flow": "consent_flow",
            "action": "request_consent",
            "intent": Intent.GREETING,
            "deferred_media_id": media_id,
        }

    # ── 5. Handle image messages (product photo or selfie) ────
    if message_type == "image" and media_id:
        session.pending_media_id = media_id
        session.pending_media_caption = text
        session.state = SessionState.AWAITING_IMAGE_TYPE
        return {
            "flow": "image_type_flow",
            "action": "ask_type",
            "intent": Intent.TRYON_SINGLE,
        }

    # ── 6. Handle voice messages ──────────────────────────────
    if message_type == "audio" and media_id:
        return {
            "flow": "help_flow",
            "action": "voice_not_understood",
            "intent": Intent.UNKNOWN,
        }

    # ── 7. Keyword matching BEFORE Groq LLM ──────────────────
    # Direct keyword matching for common commands — avoids LLM dependency
    if text:
        upper = text.strip().upper()

        # Help keywords
        if upper in _HELP_KEYWORDS:
            return {
                "flow": "help_flow",
                "action": "help",
                "intent": Intent.HELP,
            }

        # Delete keywords
        if upper in _DELETE_KEYWORDS:
            return {
                "flow": "deletion_flow",
                "action": "confirm",
                "intent": Intent.CONSENT_WITHDRAW,
                "text": text,
            }

        # Greeting keywords
        greeting_keywords = {"HI", "HELLO", "HEY", "NAMASTE", "NAMASKAR", "VANAKKAM"}
        if upper in greeting_keywords:
            return {
                "flow": "help_flow",
                "action": "greeting",
                "intent": Intent.GREETING,
            }

        # Catalog keywords
        catalog_keywords = {"CATALOG", "CATALOGUE", "BROWSE", "SHOP", "PRODUCTS"}
        if upper in catalog_keywords:
            return {
                "flow": "catalog_flow",
                "action": "browse",
                "intent": Intent.CATALOG_BROWSE,
            }

    # ── 8. Classify intent for text messages via Groq LLM ─────
    if not text:
        return {
            "flow": "help_flow",
            "action": "empty_message",
            "intent": Intent.UNKNOWN,
        }

    language = customer_data.get("language", "en") if customer_data else "en"
    intent = await classify_intent(text, language)

    logger.info("Intent classified: %s for text: '%s...'", intent.value, text[:50])

    # ── 9. Route to the correct flow ──────────────────────────
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

    # Map deletion intent to confirm action (not direct execute)
    action = "handle"
    if flow == "deletion_flow":
        action = "confirm"

    return {
        "flow": flow,
        "action": action,
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
        "type_selfie": {
            "flow": "image_type_flow",
            "action": "handle_selection",
            "intent": Intent.TRYON_SINGLE,
            "button_id": "type_selfie",
        },
        "type_product": {
            "flow": "image_type_flow",
            "action": "handle_selection",
            "intent": Intent.TRYON_SINGLE,
            "button_id": "type_product",
        },
        # Help menu buttons
        "help_tryon": {
            "flow": "help_flow",
            "action": "greeting",
            "intent": Intent.GREETING,
        },
        "help_delete": {
            "flow": "deletion_flow",
            "action": "confirm",
            "intent": Intent.CONSENT_WITHDRAW,
        },
        "help_catalog": {
            "flow": "catalog_flow",
            "action": "browse",
            "intent": Intent.CATALOG_BROWSE,
        },
        # Deletion confirmation buttons
        "confirm_delete": {
            "flow": "deletion_flow",
            "action": "execute",
            "intent": Intent.CONSENT_WITHDRAW,
        },
        "cancel_delete": {
            "flow": "deletion_flow",
            "action": "cancelled",
            "intent": Intent.UNKNOWN,
        },
    }

    route = button_routes.get(button_id, {
        "flow": "help_flow",
        "action": "unknown_button",
        "intent": Intent.UNKNOWN,
    })

    return route
