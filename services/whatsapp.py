"""
ZukoLabs VTO — WhatsApp Cloud API Service

Handles all communication with Meta's WhatsApp Cloud API:
sending text, images, interactive buttons, and downloading media.
"""

import logging
from typing import Any, Dict, Optional

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)

# WhatsApp message max length
MAX_MESSAGE_LENGTH = 1024


async def send_text_message(
    phone_number: str,
    message: str,
    phone_number_id: str,
) -> dict:
    """
    Send a text message via WhatsApp Cloud API.

    Args:
        phone_number: Recipient's phone number (with country code).
        message: Text message to send (max 1024 chars).
        phone_number_id: The sender's phone_number_id (tenant's number).

    Returns:
        API response dict.
    """
    settings = get_settings()

    # Truncate if too long
    if len(message) > MAX_MESSAGE_LENGTH:
        message = message[: MAX_MESSAGE_LENGTH - 3] + "..."
        logger.warning("Message truncated to %d chars", MAX_MESSAGE_LENGTH)

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone_number,
        "type": "text",
        "text": {"preview_url": False, "body": message},
    }

    return await _send_whatsapp_request(phone_number_id, payload)


async def send_image_message(
    phone_number: str,
    image_url: str,
    caption: str,
    phone_number_id: str,
) -> dict:
    """
    Send an image message via WhatsApp Cloud API.

    Args:
        phone_number: Recipient's phone number.
        image_url: Public URL of the image to send.
        caption: Caption text for the image.
        phone_number_id: Sender's phone_number_id.

    Returns:
        API response dict.
    """
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone_number,
        "type": "image",
        "image": {"link": image_url, "caption": caption},
    }

    return await _send_whatsapp_request(phone_number_id, payload)


async def send_interactive_buttons(
    phone_number: str,
    interactive_payload: dict,
    phone_number_id: str,
) -> dict:
    """
    Send an interactive button message via WhatsApp Cloud API.

    Args:
        phone_number: Recipient's phone number.
        interactive_payload: The interactive message structure
                            (from constants.POST_TRYON_BUTTONS etc.).
        phone_number_id: Sender's phone_number_id.

    Returns:
        API response dict.
    """
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone_number,
        **interactive_payload,
    }

    return await _send_whatsapp_request(phone_number_id, payload)


async def download_media(media_id: str) -> bytes:
    """
    Download media (image/audio) from WhatsApp Cloud API.

    Two-step process:
    1. GET media URL using media_id
    2. Download the actual file from the URL

    Args:
        media_id: The media ID from the incoming message payload.

    Returns:
        Raw bytes of the downloaded media.

    Raises:
        httpx.HTTPStatusError: If the download fails.
    """
    settings = get_settings()
    headers = {"Authorization": f"Bearer {settings.whatsapp_token}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Get media URL
        url_response = await client.get(
            f"{settings.whatsapp_api_url}/{media_id}",
            headers=headers,
        )
        url_response.raise_for_status()
        media_url = url_response.json().get("url")

        if not media_url:
            raise ValueError(f"No URL returned for media_id: {media_id}")

        # Step 2: Download the actual file
        media_response = await client.get(media_url, headers=headers)
        media_response.raise_for_status()

        logger.debug(
            "Downloaded media %s (%d bytes)",
            media_id,
            len(media_response.content),
        )
        return media_response.content


async def mark_as_read(
    message_id: str,
    phone_number_id: str,
) -> None:
    """
    Mark a message as read (sends blue ticks to the user).

    Args:
        message_id: The message ID to mark as read.
        phone_number_id: Sender's phone_number_id.
    """
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }

    try:
        await _send_whatsapp_request(phone_number_id, payload)
    except Exception as e:
        # Don't fail on read receipts — it's cosmetic
        logger.debug("Failed to mark message as read: %s", str(e))


async def _send_whatsapp_request(
    phone_number_id: str,
    payload: dict,
) -> dict:
    """
    Internal helper to send requests to WhatsApp Cloud API.

    Args:
        phone_number_id: The phone_number_id endpoint to use.
        payload: JSON payload to send.

    Returns:
        API response dict.

    Raises:
        httpx.HTTPStatusError: If the request fails.
    """
    settings = get_settings()
    url = f"{settings.whatsapp_api_url}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            logger.error(
                "WhatsApp API error: %d — %s",
                response.status_code,
                response.text,
            )
            response.raise_for_status()

        result = response.json()
        logger.debug("WhatsApp message sent: %s", result)
        return result


def extract_message_data(webhook_body: dict) -> Optional[Dict[str, Any]]:
    """
    Extract the relevant message data from a Meta webhook payload.

    Args:
        webhook_body: The full webhook JSON body.

    Returns:
        Dict with keys: phone_number_id, from_number, message_id,
        message_type, text, media_id, button_reply_id, timestamp.
        Returns None if payload is not a message event.
    """
    try:
        entry = webhook_body.get("entry", [])
        if not entry:
            return None

        changes = entry[0].get("changes", [])
        if not changes:
            return None

        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return None

        message = messages[0]
        metadata = value.get("metadata", {})
        contacts = value.get("contacts", [])

        phone_number_id = metadata.get("phone_number_id", "")
        from_number = message.get("from", "")
        message_id = message.get("id", "")
        message_type = message.get("type", "")
        timestamp = message.get("timestamp", "")

        # Extract content based on type
        text = None
        media_id = None
        button_reply_id = None
        contact_name = ""

        if contacts:
            profile = contacts[0].get("profile", {})
            contact_name = profile.get("name", "")

        if message_type == "text":
            text = message.get("text", {}).get("body", "")
        elif message_type == "image":
            media_id = message.get("image", {}).get("id", "")
            text = message.get("image", {}).get("caption", "")
        elif message_type == "audio":
            media_id = message.get("audio", {}).get("id", "")
        elif message_type == "interactive":
            interactive = message.get("interactive", {})
            if interactive.get("type") == "button_reply":
                button_reply_id = interactive.get("button_reply", {}).get("id", "")
                text = interactive.get("button_reply", {}).get("title", "")

        return {
            "phone_number_id": phone_number_id,
            "from_number": from_number,
            "message_id": message_id,
            "message_type": message_type,
            "text": text,
            "media_id": media_id,
            "button_reply_id": button_reply_id,
            "timestamp": timestamp,
            "contact_name": contact_name,
        }

    except (IndexError, KeyError) as e:
        logger.error("Failed to extract message data: %s", str(e))
        return None
