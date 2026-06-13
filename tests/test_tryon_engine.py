"""
ZukoLabs VTO — Try-On Engine Tests

Tests for try-on engine: category routing, image preprocessing,
timeout handling, and error fallback behavior.
"""

import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image

from core.constants import CATEGORY_ENGINE
from services.tryon_engine import (
    preprocess_image,
    generate,
    TryOnError,
)


# ═══════════════════════════════════════════════════════════════
# IMAGE PREPROCESSING TESTS
# ═══════════════════════════════════════════════════════════════


class TestImagePreprocessing:
    """Tests for image preprocessing before Replicate submission."""

    @pytest.mark.asyncio
    async def test_resize_large_image(self):
        """Large images should be resized to max 768x1024."""
        # Create a large test image
        img = Image.new("RGB", (2000, 3000), color="red")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        large_bytes = buffer.getvalue()

        result = await preprocess_image(large_bytes)
        result_img = Image.open(io.BytesIO(result))

        assert result_img.width <= 768
        assert result_img.height <= 1024

    @pytest.mark.asyncio
    async def test_convert_rgba_to_rgb(self):
        """RGBA images should be converted to RGB."""
        img = Image.new("RGBA", (500, 500), color=(255, 0, 0, 128))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        rgba_bytes = buffer.getvalue()

        result = await preprocess_image(rgba_bytes)
        result_img = Image.open(io.BytesIO(result))

        assert result_img.mode == "RGB"

    @pytest.mark.asyncio
    async def test_small_image_not_upscaled(self):
        """Small images should not be upscaled (only downscaled)."""
        img = Image.new("RGB", (300, 400), color="blue")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        small_bytes = buffer.getvalue()

        result = await preprocess_image(small_bytes)
        result_img = Image.open(io.BytesIO(result))

        assert result_img.width <= 300
        assert result_img.height <= 400

    @pytest.mark.asyncio
    async def test_output_is_jpeg(self):
        """Output should always be JPEG format."""
        img = Image.new("RGB", (100, 100), color="green")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        png_bytes = buffer.getvalue()

        result = await preprocess_image(png_bytes)

        # JPEG files start with FF D8
        assert result[:2] == b"\xff\xd8"


# ═══════════════════════════════════════════════════════════════
# CATEGORY ROUTING TESTS
# ═══════════════════════════════════════════════════════════════


class TestCategoryRouting:
    """Tests for category-to-engine routing."""

    def test_all_categories_have_engines(self):
        """Every defined category should map to an engine."""
        expected_categories = [
            "apparel", "kids_wear", "makeup", "jewelry",
            "eyewear", "watch", "footwear", "hair_color", "home_decor",
        ]

        for category in expected_categories:
            assert category in CATEGORY_ENGINE, (
                f"Category '{category}' missing from CATEGORY_ENGINE"
            )

    def test_apparel_uses_viton(self):
        """Apparel should use replicate_viton engine."""
        assert CATEGORY_ENGINE["apparel"] == "replicate_viton"

    def test_jewelry_uses_mediapipe(self):
        """Jewelry should use mediapipe_ar engine."""
        assert CATEGORY_ENGINE["jewelry"] == "mediapipe_ar"

    def test_eyewear_uses_mediapipe(self):
        """Eyewear should use mediapipe_ar engine."""
        assert CATEGORY_ENGINE["eyewear"] == "mediapipe_ar"


# ═══════════════════════════════════════════════════════════════
# GENERATION TESTS
# ═══════════════════════════════════════════════════════════════


class TestGeneration:
    """Tests for try-on generation."""

    @pytest.mark.asyncio
    @patch("services.tryon_engine._generate_viton")
    async def test_generate_dispatches_to_viton_for_apparel(
        self, mock_viton
    ):
        """Generate should dispatch to VITON for apparel category."""
        mock_viton.return_value = "http://example.com/output.jpg"

        result = await generate(
            selfie_url="http://example.com/selfie.jpg",
            product_url="http://example.com/product.jpg",
            category="apparel",
        )

        mock_viton.assert_called_once()
        assert result == "http://example.com/output.jpg"

    @pytest.mark.asyncio
    async def test_generate_raises_for_unsupported_engine(self):
        """Generate should raise TryOnError for home_decor (not yet implemented)."""
        with pytest.raises(TryOnError, match="not yet available"):
            await generate(
                selfie_url="http://example.com/selfie.jpg",
                product_url="http://example.com/product.jpg",
                category="home_decor",
            )

    @pytest.mark.asyncio
    @patch("services.tryon_engine._generate_viton")
    async def test_generate_wraps_exceptions_as_tryon_error(
        self, mock_viton
    ):
        """Generate should wrap all exceptions as TryOnError."""
        mock_viton.side_effect = Exception("Network error")

        with pytest.raises(TryOnError, match="Generation failed"):
            await generate(
                selfie_url="http://example.com/selfie.jpg",
                product_url="http://example.com/product.jpg",
                category="apparel",
            )


# ═══════════════════════════════════════════════════════════════
# REPLICATE TIMEOUT TESTS
# ═══════════════════════════════════════════════════════════════


class TestReplicateTimeout:
    """Tests for Replicate timeout and fallback behavior."""

    @pytest.mark.asyncio
    @patch("services.tryon_engine._run_replicate")
    async def test_timeout_raises_tryon_error(self, mock_replicate):
        """Timeout should raise TryOnError with timeout message."""
        import asyncio
        mock_replicate.side_effect = asyncio.TimeoutError()

        with pytest.raises(TryOnError, match="timed out"):
            from services.tryon_engine import _generate_viton
            await _generate_viton(
                "http://example.com/selfie.jpg",
                "http://example.com/product.jpg",
            )

    @pytest.mark.asyncio
    @patch("services.tryon_engine._run_replicate")
    async def test_no_output_raises_tryon_error(self, mock_replicate):
        """Empty output from Replicate should raise TryOnError."""
        mock_replicate.return_value = None

        with pytest.raises(TryOnError, match="No output"):
            from services.tryon_engine import _generate_viton
            await _generate_viton(
                "http://example.com/selfie.jpg",
                "http://example.com/product.jpg",
            )
