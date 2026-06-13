"""
ZukoLabs VTO — Core Try-On Flow

State machine for the main try-on interaction:
IDLE → AWAITING_SELFIE → PROCESSING → POST_TRYON → IDLE

Handles 80% of all customer interactions.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from core.constants import (
    SessionState,
    TryOnStatus,
    MESSAGES,
    POST_TRYON_BUTTONS,
    FRIEND_SHARE_BUTTONS,
)
from core.database import get_db
from middleware.rate_limiter import check_rate_limit, increment_usage
from models.customer import CustomerSession
from models.tenant import Tenant
from services.image_store import (
    upload_selfie,
    get_signed_url,
    SELFIE_BUCKET,
    OUTPUT_BUCKET,
)
from services.tryon_engine import generate, preprocess_image, TryOnError
from services.whatsapp import (
    send_text_message,
    send_image_message,
    send_interactive_buttons,
    download_media,
)

logger = logging.getLogger(__name__)


async def handle_product_image(
    phone_number: str,
    media_id: str,
    caption: Optional[str],
    session: CustomerSession,
    tenant: Tenant,
    customer_id: str,
) -> None:
    """
    Handle a product image sent by the customer.
    Transitions to AWAITING_SELFIE state.

    Args:
        phone_number: Customer's phone number.
        media_id: WhatsApp media ID for the product image.
        caption: Optional image caption text.
        session: Customer session.
        tenant: Tenant object.
        customer_id: Customer UUID.
    """
    # Check rate limit first
    rate = await check_rate_limit(tenant.id, tenant.plan)
    if not rate["allowed"]:
        await send_text_message(
            phone_number=phone_number,
            message=MESSAGES["plan_limit_reached"].format(
                seller_name=tenant.business_name
            ),
            phone_number_id=tenant.phone_number_id,
        )
        return

    try:
        # Download product image from WhatsApp
        product_bytes = await download_media(media_id)

        # Preprocess and store temporarily
        processed = await preprocess_image(product_bytes)
        product_path = await upload_selfie(
            tenant_id=tenant.id,
            customer_id=customer_id,
            image_bytes=processed,
        )

        # Get signed URL for the product image
        product_url = await get_signed_url(SELFIE_BUCKET, product_path)

        # Update session state
        session.pending_product_url = product_url
        session.pending_category = _detect_category(caption)

        if session.pending_selfie_url:
            # We already have the selfie, start processing
            session.state = SessionState.PROCESSING
            session.last_updated = datetime.now(timezone.utc)

            await send_text_message(
                phone_number=phone_number,
                message=MESSAGES["processing"],
                phone_number_id=tenant.phone_number_id,
            )

            job_id = await _create_tryon_job(
                tenant_id=tenant.id,
                customer_id=customer_id,
                category=session.pending_category or "apparel",
                selfie_path=session.pending_selfie_url.split("?")[0].split("/")[-1], # Hacky way to get path from URL, or we can just pass None since it's just for DB tracking
            )
            session.current_job_id = job_id

            await _run_tryon_generation(
                phone_number=phone_number,
                selfie_url=session.pending_selfie_url,
                product_url=product_url,
                category=session.pending_category or "apparel",
                job_id=job_id,
                tenant=tenant,
                session=session,
                customer_id=customer_id,
            )
        else:
            # We don't have the selfie yet, ask for it
            session.state = SessionState.AWAITING_SELFIE
            session.last_updated = datetime.now(timezone.utc)

            await send_text_message(
                phone_number=phone_number,
                message=MESSAGES["awaiting_selfie"],
                phone_number_id=tenant.phone_number_id,
            )

            logger.info(
                "Product received — awaiting selfie (tenant: %s, category: %s)",
                tenant.business_name,
                session.pending_category,
            )

    except Exception as e:
        logger.error("Failed to handle product image: %s", str(e))
        await send_text_message(
            phone_number=phone_number,
            message=MESSAGES["unknown_error"],
            phone_number_id=tenant.phone_number_id,
        )
        session.reset()


async def handle_selfie_first(
    phone_number: str,
    session: CustomerSession,
    tenant: Tenant,
    customer_id: str,
    language: str = "en",
) -> None:
    """
    Handle a selfie sent by the customer when they send their selfie FIRST.
    Transitions to AWAITING_PRODUCT state.
    """
    media_id = session.pending_media_id
    if not media_id:
        return

    try:
        selfie_bytes = await download_media(media_id)
        if len(selfie_bytes) < 5000:
            await send_text_message(
                phone_number=phone_number,
                message=MESSAGES["invalid_selfie"],
                phone_number_id=tenant.phone_number_id,
            )
            return

        processed = await preprocess_image(selfie_bytes)
        selfie_path = await upload_selfie(
            tenant_id=tenant.id,
            customer_id=customer_id,
            image_bytes=processed,
        )

        selfie_url = await get_signed_url(SELFIE_BUCKET, selfie_path)

        session.pending_selfie_url = selfie_url
        session.state = SessionState.AWAITING_PRODUCT
        session.last_updated = datetime.now(timezone.utc)

        # Fetch translated message
        from core.constants import get_message

        await send_text_message(
            phone_number=phone_number,
            message=get_message("awaiting_product", language),
            phone_number_id=tenant.phone_number_id,
        )

        logger.info(
            "Selfie received first — awaiting product (tenant: %s)",
            tenant.business_name,
        )

    except Exception as e:
        logger.error("Failed to handle selfie first: %s", str(e))
        await send_text_message(
            phone_number=phone_number,
            message=MESSAGES["unknown_error"],
            phone_number_id=tenant.phone_number_id,
        )
        session.reset()


async def handle_selfie(
    phone_number: str,
    media_id: str,
    session: CustomerSession,
    tenant: Tenant,
    customer_id: str,
) -> None:
    """
    Handle a selfie sent by the customer.
    Validates the image, starts try-on generation.

    Args:
        phone_number: Customer's phone number.
        media_id: WhatsApp media ID for the selfie.
        session: Customer session.
        tenant: Tenant object.
        customer_id: Customer UUID.
    """
    if session.state != SessionState.AWAITING_SELFIE:
        await send_text_message(
            phone_number=phone_number,
            message="Pehle product photo bhejo, phir selfie! 😊",
            phone_number_id=tenant.phone_number_id,
        )
        return

    try:
        # Download selfie
        selfie_bytes = await download_media(media_id)

        # Basic validation (size check)
        if len(selfie_bytes) < 5000:  # Less than 5KB is too small
            await send_text_message(
                phone_number=phone_number,
                message=MESSAGES["invalid_selfie"],
                phone_number_id=tenant.phone_number_id,
            )
            return

        # Preprocess selfie
        processed_selfie = await preprocess_image(selfie_bytes)

        # Upload temporarily
        selfie_path = await upload_selfie(
            tenant_id=tenant.id,
            customer_id=customer_id,
            image_bytes=processed_selfie,
        )

        selfie_url = await get_signed_url(SELFIE_BUCKET, selfie_path)

        # Transition to PROCESSING
        session.pending_selfie_url = selfie_url
        session.state = SessionState.PROCESSING

        # Notify customer
        await send_text_message(
            phone_number=phone_number,
            message=MESSAGES["processing"],
            phone_number_id=tenant.phone_number_id,
        )

        # Create try-on job in DB
        job_id = await _create_tryon_job(
            tenant_id=tenant.id,
            customer_id=customer_id,
            category=session.pending_category or "apparel",
            selfie_path=selfie_path,
        )

        session.current_job_id = job_id

        # Generate try-on
        await _run_tryon_generation(
            phone_number=phone_number,
            selfie_url=selfie_url,
            product_url=session.pending_product_url,
            category=session.pending_category or "apparel",
            job_id=job_id,
            tenant=tenant,
            session=session,
            customer_id=customer_id,
        )

    except Exception as e:
        logger.error("Failed to handle selfie: %s", str(e))
        await send_text_message(
            phone_number=phone_number,
            message=MESSAGES["unknown_error"],
            phone_number_id=tenant.phone_number_id,
        )
        session.reset()


async def _run_tryon_generation(
    phone_number: str,
    selfie_url: str,
    product_url: str,
    category: str,
    job_id: str,
    tenant: Tenant,
    session: CustomerSession,
    customer_id: str,
) -> None:
    """
    Run the actual try-on generation and deliver the result.

    Args:
        phone_number: Customer's phone number.
        selfie_url: URL of the preprocessed selfie.
        product_url: URL of the product image.
        category: Try-on category.
        job_id: Try-on job UUID.
        tenant: Tenant object.
        session: Customer session.
        customer_id: Customer UUID.
    """
    db = get_db()

    try:
        # Update job status to processing
        db.table("tryon_jobs").update({
            "status": TryOnStatus.PROCESSING.value,
        }).eq("id", job_id).eq("tenant_id", tenant.id).execute()

        # Generate try-on
        output_url = await generate(
            selfie_url=selfie_url,
            product_url=product_url,
            category=category,
        )

        # Update job as completed
        db.table("tryon_jobs").update({
            "status": TryOnStatus.COMPLETED.value,
            "output_url": output_url,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", job_id).eq("tenant_id", tenant.id).execute()

        # Increment usage counter
        await increment_usage(tenant.id)

        # Send result image to customer
        await send_image_message(
            phone_number=phone_number,
            image_url=output_url,
            caption=MESSAGES["tryon_complete"],
            phone_number_id=tenant.phone_number_id,
        )

        # Send post-try-on buttons
        if tenant.has_feature("friend_share_loop"):
            buttons = FRIEND_SHARE_BUTTONS
        else:
            buttons = POST_TRYON_BUTTONS

        await send_interactive_buttons(
            phone_number=phone_number,
            interactive_payload=buttons,
            phone_number_id=tenant.phone_number_id,
        )

        # Transition to POST_TRYON then IDLE
        session.state = SessionState.POST_TRYON
        session.last_updated = datetime.now(timezone.utc)

        logger.info(
            "Try-on delivered — job: %s, tenant: %s",
            job_id,
            tenant.business_name,
        )

        # Reset session after a short delay conceptually
        session.reset()

    except TryOnError as e:
        logger.error("Try-on generation failed: %s", str(e))

        # Update job as failed
        db.table("tryon_jobs").update({
            "status": TryOnStatus.FAILED.value,
            "error_message": str(e),
        }).eq("id", job_id).eq("tenant_id", tenant.id).execute()

        await send_text_message(
            phone_number=phone_number,
            message=MESSAGES["tryon_failed"],
            phone_number_id=tenant.phone_number_id,
        )

        session.reset()

    except Exception as e:
        logger.error("Unexpected error in try-on generation: %s", str(e))

        await send_text_message(
            phone_number=phone_number,
            message=MESSAGES["unknown_error"],
            phone_number_id=tenant.phone_number_id,
        )

        session.reset()


async def _create_tryon_job(
    tenant_id: str,
    customer_id: str,
    category: str,
    selfie_path: str,
    product_ref: Optional[str] = None,
) -> str:
    """Create a try-on job record in the database."""
    db = get_db()

    result = db.table("tryon_jobs").insert({
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "category": category,
        "selfie_path": selfie_path,
        "product_ref": product_ref,
        "status": TryOnStatus.PENDING.value,
    }).execute()

    if result.data:
        return result.data[0]["id"]

    raise Exception("Failed to create try-on job")


def _detect_category(caption: Optional[str]) -> str:
    """
    Simple category detection from image caption.
    Defaults to 'apparel' if no category hints found.

    Args:
        caption: Image caption text.

    Returns:
        Category string.
    """
    if not caption:
        return "apparel"

    caption_lower = caption.lower()

    category_keywords = {
        "jewelry": ["jewelry", "jewellery", "necklace", "earring", "ring", "bracelet", "bangle"],
        "eyewear": ["eyewear", "glasses", "sunglasses", "spectacles", "chasma"],
        "watch": ["watch", "ghadi"],
        "footwear": ["footwear", "shoe", "shoes", "sandal", "heels", "chappal"],
        "makeup": ["makeup", "lipstick", "foundation", "eyeshadow"],
        "kids_wear": ["kids", "children", "baby", "bacche"],
        "hair_color": ["hair color", "hair colour", "baal color"],
    }

    for category, keywords in category_keywords.items():
        if any(kw in caption_lower for kw in keywords):
            return category

    return "apparel"
