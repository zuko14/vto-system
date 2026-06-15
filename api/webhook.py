"""
ZukoLabs VTO — WhatsApp Webhook Handler

POST /webhook — Receives WhatsApp messages from Meta Cloud API.
GET /webhook — Handles Meta's webhook verification challenge.

CRITICAL: Always return HTTP 200 to Meta, even on internal errors.
Never block the webhook thread — all processing in BackgroundTasks.
"""

import logging
from datetime import datetime, timezone
from typing import Dict

from fastapi import APIRouter, BackgroundTasks, Request, Response

from core.constants import Intent, SessionState, MESSAGES, get_message, get_image_type_buttons
from core.security import verify_webhook_signature, hash_phone_number
from core.config import get_settings
from core.database import get_db
from flows.consent_flow import (
    check_consent,
    handle_consent_response,
    request_consent,
)
from flows.intent_router import route_message
from flows.tryon_flow import handle_product_image, handle_selfie
from flows.occasion_agent import handle_occasion_request
from flows.fit_verification_flow import handle_fit_check
from flows.catalog_flow import handle_catalog_browse
from flows.deletion_flow import handle_deletion
from flows.help_flow import handle_help
from middleware.idempotency import is_duplicate
from middleware.tenant_resolver import resolve_tenant, TenantNotFoundError
from models.customer import CustomerSession
from services.voice_transcription import transcribe_audio
from services.whatsapp import (
    download_media,
    extract_message_data,
    mark_as_read,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory session store (per customer phone_hash)
# In production, consider Redis for multi-worker deployments
_sessions: Dict[str, CustomerSession] = {}


def _get_session(phone_hash: str, tenant_id: str) -> CustomerSession:
    """Get or create a customer session."""
    key = f"{tenant_id}:{phone_hash}"
    if key not in _sessions:
        _sessions[key] = CustomerSession(
            phone_hash=phone_hash,
            tenant_id=tenant_id,
        )
    return _sessions[key]


@router.get("/webhook")
async def verify_webhook(request: Request) -> Response:
    """
    Handle Meta's webhook verification challenge.
    Meta sends a GET request with hub.mode, hub.verify_token, and hub.challenge.
    """
    settings = get_settings()
    params = request.query_params

    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        logger.info("Webhook verified successfully")
        return Response(content=challenge, media_type="text/plain")

    logger.warning("Webhook verification failed — invalid token")
    return Response(content="Forbidden", status_code=403)


@router.post("/webhook")
async def handle_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    """
    Handle incoming WhatsApp messages.

    Flow:
    1. HMAC signature verification
    2. Extract message data
    3. Idempotency check
    4. Tenant resolution
    5. Dispatch to background processing
    6. Return HTTP 200 immediately (Meta requires <5s)
    """
    # Always return 200 to Meta — even on errors
    try:
        # Read raw body for signature verification
        body = await request.body()

        # Verify HMAC signature
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not verify_webhook_signature(body, signature):
            logger.warning("Invalid webhook signature — processing anyway")
            # Still return 200 to prevent Meta retries
            # Log for security review

        # Parse JSON body
        import json
        webhook_data = json.loads(body)

        # Extract message data
        message_data = extract_message_data(webhook_data)
        if not message_data:
            # Not a message event (could be status update, etc.)
            return Response(content="OK", status_code=200)

        # Idempotency check
        message_id = message_data["message_id"]
        if await is_duplicate(message_id):
            return Response(content="OK", status_code=200)

        # Dispatch to background task (never block webhook)
        background_tasks.add_task(
            _process_message,
            message_data=message_data,
        )

    except Exception as e:
        # NEVER let errors prevent 200 response to Meta
        logger.error("Webhook handler error: %s", str(e))

    return Response(content="OK", status_code=200)


async def _process_message(message_data: dict) -> None:
    """
    Process an incoming message in the background.

    This runs as a BackgroundTask — never blocks the webhook response.
    All errors are caught and logged (never crash the handler).
    """
    phone_number_id = message_data["phone_number_id"]
    from_number = message_data["from_number"]
    message_type = message_data["message_type"]
    text = message_data.get("text", "")
    media_id = message_data.get("media_id")
    button_reply_id = message_data.get("button_reply_id")
    message_id = message_data["message_id"]

    try:
        # 1. Resolve tenant
        try:
            tenant = await resolve_tenant(phone_number_id)
        except TenantNotFoundError:
            logger.warning(
                "No tenant for phone_number_id: %s",
                phone_number_id,
            )
            return

        # 2. Mark message as read
        await mark_as_read(message_id, phone_number_id)

        # 3. Hash phone number (DPDP — never store raw)
        phone_hash = hash_phone_number(from_number)

        # 4. Get/create customer session
        session = _get_session(phone_hash, tenant.id)

        # 5. Get full customer data
        consent_info = await check_consent(phone_hash, tenant.id)
        customer_data = {
            "consent_given": consent_info["consent_given"],
            "id": consent_info.get("customer_id"),
        }

        # Get full customer data if exists
        if consent_info["customer_id"]:
            db = get_db()
            result = (
                db.table("customers")
                .select("*")
                .eq("id", consent_info["customer_id"])
                .execute()
            )
            if result.data:
                customer_data.update(result.data[0])

                # Update last_active
                db.table("customers").update({
                    "last_active": datetime.now(timezone.utc).isoformat(),
                }).eq("id", consent_info["customer_id"]).execute()

        # Determine customer language: customer preference > tenant default > en
        language = customer_data.get("language") or tenant.language or "en"

        # 6. Handle voice messages (transcribe first)
        if message_type == "audio" and media_id:
            if tenant.has_feature("voice_support"):
                audio_bytes = await download_media(media_id)
                transcription = await transcribe_audio(
                    audio_bytes,
                    language_hint=language,
                )
                if transcription["success"]:
                    text = transcription["text"]
                    message_type = "text"  # Treat as text after transcription

                    # Update customer language if detected
                    if (
                        consent_info["customer_id"]
                        and transcription["language"] != customer_data.get("language")
                    ):
                        db = get_db()
                        db.table("customers").update({
                            "language": transcription["language"],
                        }).eq("id", consent_info["customer_id"]).execute()
                        customer_data["language"] = transcription["language"]
                        language = transcription["language"]
                else:
                    await handle_help(from_number, tenant, "voice_not_understood", language)
                    return
            else:
                await handle_help(from_number, tenant, "feature_not_available", language)
                return

        # 7. Route message to correct flow
        route = await route_message(
            text=text,
            message_type=message_type,
            session=session,
            tenant=tenant,
            customer_data=customer_data,
            button_reply_id=button_reply_id,
            media_id=media_id,
        )

        # 8. Execute the routed flow
        # Use language override if router specified one (e.g. from language picker)
        flow_language = route.get("language_override", language)

        await _execute_flow(
            route=route,
            phone_number=from_number,
            phone_hash=phone_hash,
            session=session,
            tenant=tenant,
            customer_data=customer_data,
            media_id=media_id,
            text=text,
            language=flow_language,
        )

    except Exception as e:
        # Never crash — log and send friendly error
        logger.error(
            "Message processing failed: %s",
            str(e),
            exc_info=True,
        )
        try:
            await handle_help(from_number, tenant, "unknown", language)
        except Exception:
            pass


async def _execute_flow(
    route: dict,
    phone_number: str,
    phone_hash: str,
    session: CustomerSession,
    tenant,
    customer_data: dict,
    media_id: str = None,
    text: str = "",
    language: str = "en",
) -> None:
    """Execute the flow handler based on routing result."""

    flow = route["flow"]
    action = route.get("action", "handle")
    customer_id = customer_data.get("id", "")

    if flow == "language_flow":
        if action == "send_picker":
            from services.whatsapp import send_interactive_buttons
            from core.constants import LANGUAGE_PICKER_BUTTONS
            await send_interactive_buttons(
                phone_number=phone_number,
                interactive_payload=LANGUAGE_PICKER_BUTTONS,
                phone_number_id=tenant.phone_number_id,
            )

    elif flow == "image_type_flow":
        if action == "ask_type":
            from services.whatsapp import send_interactive_buttons
            await send_interactive_buttons(
                phone_number=phone_number,
                interactive_payload=get_image_type_buttons(language),
                phone_number_id=tenant.phone_number_id,
            )
        elif action == "handle_selection":
            button_id = route.get("button_id")
            if button_id == "type_selfie":
                # We have their selfie, now we need a product
                from flows.tryon_flow import handle_selfie_first
                await handle_selfie_first(
                    phone_number=phone_number,
                    session=session,
                    tenant=tenant,
                    customer_id=customer_id,
                    language=language,
                )
            elif button_id == "type_product":
                # We have a product, now we need a selfie
                from flows.tryon_flow import handle_product_image
                await handle_product_image(
                    phone_number=phone_number,
                    media_id=session.pending_media_id,
                    caption=session.pending_media_caption,
                    session=session,
                    tenant=tenant,
                    customer_id=customer_id,
                    language=language,
                )

    elif flow == "consent_flow":
        if action == "request_consent":
            await request_consent(
                phone_number=phone_number,
                tenant=tenant,
                session=session,
                language=language,
            )
        elif action == "check_response":
            await handle_consent_response(
                phone_number=phone_number,
                phone_hash=phone_hash,
                text=route.get("text", text),
                tenant=tenant,
                session=session,
                customer_id=customer_id,
                language=language,
            )
        elif action == "handle":
            # If already consented and LLM classified as consent_give
            from services.whatsapp import send_text_message
            from core.constants import get_message
            await send_text_message(
                phone_number=phone_number,
                message=get_message("consent_confirmed", language),
                phone_number_id=tenant.phone_number_id,
            )

    elif flow == "tryon_flow":
        if action == "receive_product":
            await handle_product_image(
                phone_number=phone_number,
                media_id=route.get("media_id", media_id),
                caption=route.get("caption", text),
                session=session,
                tenant=tenant,
                customer_id=customer_id,
                language=language,
            )
        elif action == "receive_selfie":
            await handle_selfie(
                phone_number=phone_number,
                media_id=route.get("media_id", media_id),
                session=session,
                tenant=tenant,
                customer_id=customer_id,
                language=language,
            )
        elif action == "remind_selfie":
            from services.whatsapp import send_text_message
            await send_text_message(
                phone_number=phone_number,
                message=get_message("awaiting_selfie", language),
                phone_number_id=tenant.phone_number_id,
            )
        elif action == "remind_product":
            from services.whatsapp import send_text_message
            await send_text_message(
                phone_number=phone_number,
                message=get_message("awaiting_product", language),
                phone_number_id=tenant.phone_number_id,
            )
        elif action == "start_new":
            session.reset()
            await handle_help(phone_number, tenant, "greeting", language)

    elif flow == "occasion_agent":
        await handle_occasion_request(
            phone_number=phone_number,
            text=route.get("text", text),
            session=session,
            tenant=tenant,
            customer_data=customer_data,
        )

    elif flow == "fit_verification_flow":
        await handle_fit_check(
            phone_number=phone_number,
            text=text,
            session=session,
            tenant=tenant,
            customer_data=customer_data,
            media_id=media_id,
        )

    elif flow == "catalog_flow":
        await handle_catalog_browse(
            phone_number=phone_number,
            text=route.get("text", text),
            session=session,
            tenant=tenant,
            customer_data=customer_data,
        )

    elif flow == "deletion_flow":
        await handle_deletion(
            phone_number=phone_number,
            phone_hash=phone_hash,
            session=session,
            tenant=tenant,
            customer_data=customer_data,
            language=language,
        )

    elif flow == "help_flow":
        intent = route.get("intent", Intent.HELP)
        if intent == Intent.GREETING:
            await handle_help(phone_number, tenant, "greeting", language)
        elif action in ("feature_not_available", "voice_not_understood", "empty_message"):
            await handle_help(phone_number, tenant, action, language)
        else:
            await handle_help(phone_number, tenant, "help", language)

    else:
        await handle_help(phone_number, tenant, "unknown", language)
