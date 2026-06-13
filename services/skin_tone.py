"""
ZukoLabs VTO — Skin Tone Detection Service

Detects skin tone from selfie using MediaPipe face detection.
Maps to Monk Skin Tone Scale (MST-1 to MST-10).
Result is cached in customer record after first detection.
"""

import io
import logging
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image

from core.constants import SKIN_TONE_COLORS

logger = logging.getLogger(__name__)

# Monk Skin Tone Scale RGB reference values (approximate)
# MST-1 (lightest) → MST-10 (darkest)
MONK_SCALE_RGB = {
    "MST-1": (246, 237, 228),
    "MST-2": (236, 212, 185),
    "MST-3": (215, 185, 153),
    "MST-4": (196, 161, 124),
    "MST-5": (174, 137, 100),
    "MST-6": (150, 114, 81),
    "MST-7": (123, 90, 62),
    "MST-8": (96, 67, 46),
    "MST-9": (72, 49, 34),
    "MST-10": (46, 30, 21),
}


async def detect_skin_tone(selfie_bytes: bytes) -> Optional[str]:
    """
    Detect skin tone from a selfie image.

    Process:
    1. Load image into memory
    2. Detect face region using simple heuristics (center crop)
    3. Sample skin pixels from cheek/forehead area
    4. Map average color to Monk Skin Tone Scale
    5. Delete local data after detection (DPDP)

    Args:
        selfie_bytes: Raw bytes of the selfie image.

    Returns:
        Skin tone code (e.g., "MST-3", "MST-7") or None if detection fails.
    """
    try:
        img = Image.open(io.BytesIO(selfie_bytes))
        img = img.convert("RGB")
        img_array = np.array(img)

        # Simple face region estimation (center of image)
        h, w = img_array.shape[:2]

        # Sample from typical face region (center upper portion)
        face_top = int(h * 0.15)
        face_bottom = int(h * 0.65)
        face_left = int(w * 0.25)
        face_right = int(w * 0.75)

        face_region = img_array[face_top:face_bottom, face_left:face_right]

        if face_region.size == 0:
            logger.warning("Empty face region — cannot detect skin tone")
            return None

        # Sample skin pixels (cheek area — middle section of face)
        cheek_top = int(face_region.shape[0] * 0.4)
        cheek_bottom = int(face_region.shape[0] * 0.7)
        cheek_left = int(face_region.shape[1] * 0.2)
        cheek_right = int(face_region.shape[1] * 0.8)

        skin_sample = face_region[
            cheek_top:cheek_bottom, cheek_left:cheek_right
        ]

        if skin_sample.size == 0:
            logger.warning("Empty skin sample — cannot detect skin tone")
            return None

        # Calculate average skin color
        avg_color = skin_sample.mean(axis=(0, 1))
        avg_rgb = tuple(int(c) for c in avg_color[:3])

        # Map to closest Monk Scale tone
        tone = _map_to_monk_scale(avg_rgb)

        logger.info(
            "Skin tone detected: %s (avg RGB: %s)",
            tone,
            avg_rgb,
        )

        # Clean up — process in memory only (DPDP compliance)
        del img_array, face_region, skin_sample

        return tone

    except Exception as e:
        logger.error("Skin tone detection failed: %s", str(e))
        return None


def _map_to_monk_scale(rgb: Tuple[int, int, int]) -> str:
    """
    Map an RGB color to the closest Monk Skin Tone Scale value.

    Uses Euclidean distance in RGB space for matching.

    Args:
        rgb: Tuple of (R, G, B) values.

    Returns:
        Monk scale code (e.g., "MST-5").
    """
    min_distance = float("inf")
    closest_tone = "MST-5"  # Default to medium

    for tone, ref_rgb in MONK_SCALE_RGB.items():
        distance = sum((a - b) ** 2 for a, b in zip(rgb, ref_rgb)) ** 0.5
        if distance < min_distance:
            min_distance = distance
            closest_tone = tone

    return closest_tone


def check_color_compatibility(
    skin_tone_code: str,
    garment_colors: List[str],
) -> dict:
    """
    Check color compatibility between skin tone and garment colors.

    Args:
        skin_tone_code: Monk scale code (e.g., "MST-3").
        garment_colors: List of color names for the garment.

    Returns:
        Dict with 'score' (0-100), 'recommendation' (text),
        'flattering' (list), 'avoid' (list).
    """
    tone_data = SKIN_TONE_COLORS.get(skin_tone_code, {})
    flattering = tone_data.get("flattering", [])
    avoid = tone_data.get("avoid", [])

    # Simple scoring: check how many garment colors match flattering/avoid lists
    good_matches = 0
    bad_matches = 0

    for color in garment_colors:
        color_lower = color.lower()
        for f in flattering:
            if f.lower() in color_lower or color_lower in f.lower():
                good_matches += 1
                break
        for a in avoid:
            if a.lower() in color_lower or color_lower in a.lower():
                bad_matches += 1
                break

    total = len(garment_colors) or 1
    score = max(0, min(100, int(
        ((good_matches - bad_matches) / total) * 50 + 50
    )))

    if score >= 70:
        recommendation = "Yeh colors aapke skin tone ke saath bahut achha lagega! 🌟"
    elif score >= 40:
        recommendation = "Yeh colors theek hai, but better options bhi hain."
    else:
        recommendation = "Yeh colors aapke skin tone ke saath itna suit nahi karega."

    return {
        "score": score,
        "recommendation": recommendation,
        "flattering": flattering,
        "avoid": avoid,
        "skin_tone": skin_tone_code,
    }
