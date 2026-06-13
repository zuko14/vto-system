"""
ZukoLabs VTO — Groq LLM Client

Handles all Groq API calls: intent classification, occasion agent,
fit analysis, and general LLM calls. Includes retry with exponential
backoff and dead letter queue for persistent failures.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from groq import AsyncGroq, RateLimitError, APITimeoutError, APIError

from core.config import get_settings
from core.constants import (
    GROQ_CONFIG,
    RETRY_CONFIG,
    Intent,
    INTENT_CLASSIFIER_PROMPT,
    OCCASION_AGENT_SYSTEM_PROMPT,
)
from core.database import get_db

logger = logging.getLogger(__name__)

# Module-level client (lazy-initialized)
_client: Optional[AsyncGroq] = None


def _get_client() -> AsyncGroq:
    """Get or create the Groq async client."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncGroq(api_key=settings.groq_api_key)
    return _client


async def classify_intent(message: str, language: str = "en") -> Intent:
    """
    Classify a user message into one of the defined intents.
    Uses low temperature and minimal tokens for deterministic routing.

    Args:
        message: The user's text message.
        language: The user's detected language.

    Returns:
        Intent enum value.
    """
    try:
        response = await _call_groq(
            system_prompt=INTENT_CLASSIFIER_PROMPT,
            user_message=message,
            max_tokens=50,
            temperature=0.0,
        )

        # Parse the intent string
        intent_str = response.strip().lower().replace('"', "").replace("'", "")

        try:
            return Intent(intent_str)
        except ValueError:
            logger.warning(
                "Unknown intent from Groq: '%s' — defaulting to UNKNOWN",
                intent_str,
            )
            return Intent.UNKNOWN

    except Exception as e:
        logger.error("Intent classification failed: %s", str(e))
        return Intent.UNKNOWN


async def agent_call(
    system_prompt: str,
    user_message: str,
    tools: List[Dict[str, Any]],
    language: str = "en",
) -> dict:
    """
    Make a Groq tool-calling (agent) request.
    Used by the occasion agent with max 3 tool calls.

    Args:
        system_prompt: System prompt for the agent.
        user_message: The user's message.
        tools: List of tool definitions for Groq.
        language: The user's language for response.

    Returns:
        Dict with 'message' (text response) and 'tool_calls' (list).
    """
    prompt = system_prompt.replace("{language}", language)

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model=GROQ_CONFIG["model"],
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_message},
            ],
            tools=tools,
            tool_choice="auto",
            max_tokens=500,
            temperature=0.3,
        )

        choice = response.choices[0]
        result = {
            "message": choice.message.content or "",
            "tool_calls": [],
        }

        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                result["tool_calls"].append({
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments),
                })

        return result

    except Exception as e:
        logger.error("Agent call failed: %s", str(e))
        return {"message": "", "tool_calls": []}


async def analyze_fit(image_description: str, language: str = "en") -> dict:
    """
    Analyze a wearing photo for fit verification.

    Args:
        image_description: Description or context about the wearing photo.
        language: Response language.

    Returns:
        Dict with 'fit_status' (good_fit, size_issue, unclear)
        and 'message' (response text).
    """
    system_prompt = (
        "You are a fashion fit analysis assistant. Analyze the customer's "
        "wearing photo and determine if the garment fits well.\n"
        "Respond in JSON format with:\n"
        '- "fit_status": one of "good_fit", "size_issue", "unclear"\n'
        '- "issue": if size_issue, one of "too_tight", "too_loose", "wrong_length"\n'
        '- "message": a friendly response in Hinglish\n'
        '- "styling_tips": list of styling suggestions if good fit\n'
        f"Respond in the user's language: {language}"
    )

    try:
        response = await _call_groq(
            system_prompt=system_prompt,
            user_message=image_description,
            max_tokens=200,
            temperature=0.1,
        )

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {
                "fit_status": "unclear",
                "message": "Thoda better photo bhejo? Good lighting mein, full length",
            }

    except Exception as e:
        logger.error("Fit analysis failed: %s", str(e))
        return {
            "fit_status": "unclear",
            "message": "Analysis mein error aaya. Ek aur photo try karo? 📸",
        }


async def _call_groq(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 150,
    temperature: float = 0.1,
) -> str:
    """
    Internal helper: Make a Groq chat completion call with retry logic.

    Args:
        system_prompt: System prompt.
        user_message: User message.
        max_tokens: Maximum tokens in response.
        temperature: Sampling temperature.

    Returns:
        The text content of the LLM response.

    Raises:
        Exception: If all retries are exhausted.
    """
    client = _get_client()
    last_error = None

    for attempt in range(RETRY_CONFIG["max_retries"] + 1):
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=GROQ_CONFIG["model"],
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                ),
                timeout=GROQ_CONFIG["timeout"],
            )

            return response.choices[0].message.content or ""

        except RateLimitError as e:
            last_error = e
            delay = min(
                RETRY_CONFIG["base_delay"]
                * (RETRY_CONFIG["backoff_multiplier"] ** attempt),
                RETRY_CONFIG["max_delay"],
            )
            logger.warning(
                "Groq rate limited (attempt %d/%d) — retrying in %.1fs",
                attempt + 1,
                RETRY_CONFIG["max_retries"] + 1,
                delay,
            )
            await asyncio.sleep(delay)

        except (APITimeoutError, asyncio.TimeoutError) as e:
            last_error = e
            if attempt < RETRY_CONFIG["max_retries"]:
                delay = RETRY_CONFIG["base_delay"] * (attempt + 1)
                logger.warning(
                    "Groq timeout (attempt %d/%d) — retrying in %.1fs",
                    attempt + 1,
                    RETRY_CONFIG["max_retries"] + 1,
                    delay,
                )
                await asyncio.sleep(delay)

        except APIError as e:
            last_error = e
            if hasattr(e, "status_code") and e.status_code in RETRY_CONFIG["retry_on"]:
                delay = RETRY_CONFIG["base_delay"] * (attempt + 1)
                logger.warning(
                    "Groq API error %d (attempt %d/%d) — retrying",
                    e.status_code,
                    attempt + 1,
                    RETRY_CONFIG["max_retries"] + 1,
                )
                await asyncio.sleep(delay)
            else:
                # Non-retryable error
                break

        except Exception as e:
            last_error = e
            logger.error("Unexpected Groq error: %s", str(e))
            break

    # All retries exhausted — log to dead letter queue
    await _log_to_dlq("llm_call", {
        "system_prompt": system_prompt[:200],
        "user_message": user_message[:200],
        "error": str(last_error),
    })

    raise last_error or Exception("Groq call failed after all retries")


async def _log_to_dlq(
    job_type: str,
    payload: dict,
    tenant_id: str = None,
) -> None:
    """
    Log a failed operation to the dead letter queue for manual review.

    Args:
        job_type: Type of job that failed (llm_call, tryon, whatsapp_send).
        payload: Context about the failure.
        tenant_id: Optional tenant ID.
    """
    try:
        db = get_db()
        record = {
            "job_type": job_type,
            "payload": payload,
            "error": payload.get("error", "unknown"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if tenant_id:
            record["tenant_id"] = tenant_id

        db.table("dead_letter_queue").insert(record).execute()
        logger.info("Logged to DLQ: %s — %s", job_type, payload.get("error", ""))

    except Exception as e:
        logger.error("Failed to log to DLQ: %s", str(e))
