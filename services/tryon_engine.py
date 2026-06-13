"""
ZukoLabs VTO — Try-On Engine Service

Wraps Replicate's IDM-VTON and other try-on models.
Handles image preprocessing, generation, status polling, and fallback.
"""

import asyncio
import io
import logging
from typing import Optional

import httpx
from PIL import Image

from core.config import get_settings
from core.constants import (
    CATEGORY_ENGINE,
    REPLICATE_CONFIG,
    FALLBACK_BEHAVIOR,
    TryOnStatus,
)

logger = logging.getLogger(__name__)


class TryOnError(Exception):
    """Raised when try-on generation fails."""
    pass


async def generate(
    selfie_url: str,
    product_url: str,
    category: str,
) -> str:
    """
    Generate a virtual try-on image.

    Dispatches to the correct engine based on category.
    Preprocesses images before sending to Replicate.

    Args:
        selfie_url: URL of the customer's selfie image.
        product_url: URL of the product/garment image.
        category: Try-on category (apparel, jewelry, etc.).

    Returns:
        URL of the generated try-on output image.

    Raises:
        TryOnError: If generation fails after retries.
    """
    engine = CATEGORY_ENGINE.get(category, "replicate_viton")

    logger.info(
        "Starting try-on generation — category: %s, engine: %s",
        category,
        engine,
    )

    try:
        if engine == "replicate_viton":
            return await _generate_viton(selfie_url, product_url)
        elif engine == "mediapipe_ar":
            return await _generate_ar_overlay(selfie_url, product_url, category)
        elif engine == "replicate_makeup":
            return await _generate_makeup(selfie_url, product_url)
        elif engine == "replicate_hair":
            return await _generate_hair_color(selfie_url, product_url)
        elif engine == "arcore_room":
            raise TryOnError("Home decor try-on is not yet available")
        else:
            raise TryOnError(f"Unknown engine: {engine}")

    except TryOnError:
        raise
    except Exception as e:
        logger.error("Try-on generation failed: %s", str(e))
        raise TryOnError(f"Generation failed: {str(e)}")


async def preprocess_image(image_bytes: bytes) -> bytes:
    """
    Preprocess an image before sending to Replicate.

    1. Resize to max 768x1024 (VITON optimal resolution)
    2. Convert to RGB (strip alpha channel)
    3. Compress to under 5MB
    4. Process entirely in memory — never save to disk (DPDP)

    Args:
        image_bytes: Raw image bytes.

    Returns:
        Preprocessed image bytes (JPEG).
    """
    img = Image.open(io.BytesIO(image_bytes))

    # Convert to RGB (strip alpha)
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Resize to fit within 768x1024 maintaining aspect ratio
    max_width, max_height = 768, 1024
    img.thumbnail((max_width, max_height), Image.LANCZOS)

    # Compress to JPEG
    output = io.BytesIO()
    quality = REPLICATE_CONFIG["output_quality"]

    img.save(output, format="JPEG", quality=quality, optimize=True)

    # Check if under size limit
    max_size = REPLICATE_CONFIG["max_image_size_mb"] * 1024 * 1024
    while output.tell() > max_size and quality > 30:
        output = io.BytesIO()
        quality -= 10
        img.save(output, format="JPEG", quality=quality, optimize=True)

    result = output.getvalue()
    logger.debug(
        "Image preprocessed: %dx%d, %d bytes, quality=%d",
        img.width,
        img.height,
        len(result),
        quality,
    )
    return result


async def _generate_viton(selfie_url: str, product_url: str) -> str:
    """
    Generate try-on using Replicate IDM-VTON model.

    Args:
        selfie_url: Customer selfie URL.
        product_url: Product/garment image URL.

    Returns:
        URL of the generated output image.
    """
    settings = get_settings()

    try:
        # Run the VITON model on Replicate
        output = await asyncio.wait_for(
            _run_replicate(
                model=settings.replicate_viton_model,
                input_data={
                    "human_img": selfie_url,
                    "garm_img": product_url,
                    "garment_des": "a garment",
                    "is_checked": True,
                    "is_checked_crop": False,
                    "denoise_steps": 30,
                    "seed": 42,
                },
            ),
            timeout=REPLICATE_CONFIG["timeout_poll"],
        )

        if not output:
            raise TryOnError("No output received from VITON model")

        # Output is typically a list of URLs or a single URL
        if isinstance(output, list):
            result_url = str(output[0])
        else:
            result_url = str(output)

        logger.info("VITON generation complete: %s", result_url[:80])
        return result_url

    except asyncio.TimeoutError:
        raise TryOnError(
            f"VITON generation timed out after {REPLICATE_CONFIG['timeout_poll']}s"
        )
    except Exception as e:
        raise TryOnError(f"VITON generation failed: {str(e)}")


async def _run_replicate(model: str, input_data: dict):
    """
    Run a Replicate model asynchronously with polling.

    Args:
        model: Replicate model identifier (e.g. "cuuupid/idm-vton").
        input_data: Input parameters for the model.

    Returns:
        Model output.
    """
    import replicate as replicate_lib

    # Run in a thread since replicate library is sync
    loop = asyncio.get_event_loop()
    output = await loop.run_in_executor(
        None,
        lambda: replicate_lib.run(model, input=input_data),
    )
    return output


async def _generate_ar_overlay(
    selfie_url: str,
    product_url: str,
    category: str,
) -> str:
    """
    Generate AR overlay for jewelry, eyewear, or watch try-on.
    Uses MediaPipe for face/hand/wrist landmark detection + asset overlay.

    NOTE: This is a placeholder — full implementation requires MediaPipe
    integration and 3D asset rendering pipeline.

    Args:
        selfie_url: Customer selfie URL.
        product_url: Product image URL.
        category: Specific category (jewelry, eyewear, watch).

    Returns:
        URL of the generated overlay image.
    """
    # For now, fall back to VITON-style processing
    # TODO: Implement full MediaPipe AR overlay pipeline
    logger.info("AR overlay for %s — using fallback processing", category)
    return await _generate_viton(selfie_url, product_url)


async def _generate_makeup(selfie_url: str, product_url: str) -> str:
    """
    Generate makeup try-on using color overlay model.

    NOTE: Placeholder — implement with specialized makeup model.
    """
    logger.info("Makeup generation — using fallback processing")
    return await _generate_viton(selfie_url, product_url)


async def _generate_hair_color(selfie_url: str, product_url: str) -> str:
    """
    Generate hair color try-on using hair segmentation + recolor.

    NOTE: Placeholder — implement with specialized hair model.
    """
    logger.info("Hair color generation — using fallback processing")
    return await _generate_viton(selfie_url, product_url)


async def get_prediction_status(prediction_id: str) -> dict:
    """
    Check the status of a Replicate prediction.

    Args:
        prediction_id: The Replicate prediction ID.

    Returns:
        Dict with 'status' and 'output' (if completed).
    """
    try:
        import replicate as replicate_lib

        loop = asyncio.get_event_loop()
        prediction = await loop.run_in_executor(
            None,
            lambda: replicate_lib.predictions.get(prediction_id),
        )

        return {
            "status": prediction.status,
            "output": prediction.output,
            "error": prediction.error,
        }
    except Exception as e:
        logger.error("Failed to get prediction status: %s", str(e))
        return {"status": "failed", "output": None, "error": str(e)}
