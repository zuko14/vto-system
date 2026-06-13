"""
ZukoLabs VTO — Voice Transcription Service

Transcribes voice notes from WhatsApp using OpenAI Whisper API.
Supports Hindi, Telugu, Tamil, Kannada, Marathi, and English.
"""

import io
import logging
import tempfile
from typing import Optional

import httpx
from groq import AsyncGroq

from core.config import get_settings

logger = logging.getLogger(__name__)

# Supported languages for transcription
SUPPORTED_LANGUAGES = {
    "en": "english",
    "hi": "hindi",
    "te": "telugu",
    "ta": "tamil",
    "kn": "kannada",
    "mr": "marathi",
}

# Module-level client
_client: Optional[AsyncGroq] = None


def _get_client() -> AsyncGroq:
    """Get or create the Groq async client."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncGroq(api_key=settings.groq_api_key)
    return _client


async def transcribe_audio(
    audio_bytes: bytes,
    language_hint: Optional[str] = None,
) -> dict:
    """
    Transcribe an audio message using OpenAI Whisper.

    Args:
        audio_bytes: Raw audio bytes from WhatsApp.
        language_hint: Optional ISO 639-1 language code
                      (e.g., "hi" for Hindi).

    Returns:
        Dict with:
          - text: Transcribed text.
          - language: Detected language code.
          - success: Whether transcription succeeded.
    """
    client = _get_client()

    try:
        # Groq Whisper expects a tuple (filename, bytes)
        params = {
            "model": "whisper-large-v3",
            "file": ("voice_message.ogg", audio_bytes),
            "response_format": "json",
        }

        # If we have a language hint, use it for better accuracy
        if language_hint and language_hint in SUPPORTED_LANGUAGES:
            params["language"] = language_hint

        response = await client.audio.transcriptions.create(**params)

        transcribed_text = response.text.strip()

        if not transcribed_text:
            logger.warning("Empty transcription result")
            return {
                "text": "",
                "language": language_hint or "en",
                "success": False,
            }

        # Detect language from response if not hinted
        detected_language = language_hint or detect_language(transcribed_text)

        logger.info(
            "Audio transcribed: '%s...' (language: %s)",
            transcribed_text[:50],
            detected_language,
        )

        return {
            "text": transcribed_text,
            "language": detected_language,
            "success": True,
        }

    except Exception as e:
        logger.error("Voice transcription failed: %s", str(e))
        return {
            "text": "",
            "language": language_hint or "en",
            "success": False,
        }


def detect_language(text: str) -> str:
    """
    Simple language detection based on character scripts.
    For more accurate detection, Whisper's detected language can be used.

    Args:
        text: The transcribed text.

    Returns:
        ISO 639-1 language code.
    """
    # Check for Devanagari script (Hindi, Marathi)
    devanagari_count = sum(
        1 for c in text if "\u0900" <= c <= "\u097F"
    )

    # Check for Telugu script
    telugu_count = sum(
        1 for c in text if "\u0C00" <= c <= "\u0C7F"
    )

    # Check for Tamil script
    tamil_count = sum(
        1 for c in text if "\u0B80" <= c <= "\u0BFF"
    )

    # Check for Kannada script
    kannada_count = sum(
        1 for c in text if "\u0C80" <= c <= "\u0CFF"
    )

    total = len(text)
    if total == 0:
        return "en"

    # If more than 20% of chars are in a script, detect that language
    if telugu_count / total > 0.2:
        return "te"
    elif tamil_count / total > 0.2:
        return "ta"
    elif kannada_count / total > 0.2:
        return "kn"
    elif devanagari_count / total > 0.2:
        return "hi"
    else:
        return "en"
