"""
ZukoLabs VTO — DPDP Compliance Tests

Tests verifying compliance with India's Digital Personal Data
Protection (DPDP) Act 2023. These are mandatory before every
production deployment.
"""

import hashlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from core.constants import ConsentAction, SessionState
from core.security import hash_phone_number
from models.customer import Customer, CustomerSession
from models.tenant import Tenant, TenantSettings


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def mock_tenant():
    return Tenant(
        id="test-tenant-id",
        phone_number_id="123456789",
        business_name="Test Boutique",
        plan="essential",
        whatsapp_number="+919876543210",
        language="en",
        settings=TenantSettings(),
    )


@pytest.fixture
def mock_session():
    return CustomerSession(
        phone_hash="hashed_phone",
        tenant_id="test-tenant-id",
    )


# ═══════════════════════════════════════════════════════════════
# CONSENT TESTS
# ═══════════════════════════════════════════════════════════════


class TestConsentBeforeProcessing:
    """DPDP Rule: No selfie processed without explicit AGREE."""

    @pytest.mark.asyncio
    @patch("flows.intent_router.classify_intent")
    async def test_tryon_blocked_without_consent(
        self, mock_classify, mock_tenant, mock_session
    ):
        """Try-on should be blocked when consent is not given."""
        from core.constants import Intent
        mock_classify.return_value = Intent.TRYON_SINGLE

        from flows.intent_router import route_message

        customer_data = {"consent_given": False, "id": "cust-1"}

        result = await route_message(
            text="try this on",
            message_type="text",
            session=mock_session,
            tenant=mock_tenant,
            customer_data=customer_data,
        )

        assert result["flow"] == "consent_flow"
        assert result["action"] == "request_consent"

    @pytest.mark.asyncio
    async def test_image_blocked_without_consent(
        self, mock_tenant, mock_session
    ):
        """Image processing should be blocked without consent."""
        from flows.intent_router import route_message

        customer_data = {"consent_given": False, "id": "cust-1"}

        result = await route_message(
            text="",
            message_type="image",
            session=mock_session,
            tenant=mock_tenant,
            customer_data=customer_data,
            media_id="test-media-id",
        )

        assert result["flow"] == "consent_flow"

    @pytest.mark.asyncio
    @patch("flows.intent_router.classify_intent")
    async def test_tryon_allowed_with_consent(
        self, mock_classify, mock_tenant, mock_session
    ):
        """Try-on should proceed when consent is given."""
        from core.constants import Intent
        mock_classify.return_value = Intent.TRYON_SINGLE

        from flows.intent_router import route_message

        customer_data = {"consent_given": True, "id": "cust-1"}

        result = await route_message(
            text="try this on",
            message_type="text",
            session=mock_session,
            tenant=mock_tenant,
            customer_data=customer_data,
        )

        assert result["flow"] == "tryon_flow"


# ═══════════════════════════════════════════════════════════════
# PHONE NUMBER HASHING TESTS
# ═══════════════════════════════════════════════════════════════


class TestNoRawPhoneStorage:
    """DPDP Rule: Never store raw phone numbers — always SHA-256."""

    def test_phone_hash_is_sha256(self):
        """hash_phone_number should return SHA-256 hex digest."""
        phone = "+919876543210"
        result = hash_phone_number(phone)

        expected = hashlib.sha256(phone.encode("utf-8")).hexdigest()
        assert result == expected

    def test_phone_hash_is_deterministic(self):
        """Same phone number should always produce same hash."""
        phone = "+919876543210"
        hash1 = hash_phone_number(phone)
        hash2 = hash_phone_number(phone)
        assert hash1 == hash2

    def test_different_phones_different_hashes(self):
        """Different phone numbers should produce different hashes."""
        hash1 = hash_phone_number("+919876543210")
        hash2 = hash_phone_number("+919876543211")
        assert hash1 != hash2

    def test_phone_hash_length(self):
        """SHA-256 hex digest should be 64 characters."""
        result = hash_phone_number("+919876543210")
        assert len(result) == 64

    def test_phone_hash_no_raw_number(self):
        """Hash should not contain the raw phone number."""
        phone = "+919876543210"
        result = hash_phone_number(phone)
        assert phone not in result
        assert "9876543210" not in result


# ═══════════════════════════════════════════════════════════════
# CROSS-TENANT ISOLATION TESTS
# ═══════════════════════════════════════════════════════════════


class TestCrossTenantIsolation:
    """DPDP Rule: No cross-tenant data leakage."""

    def test_tenant_id_required_in_customer_model(self):
        """Customer model should always require tenant_id."""
        # This should work
        customer = Customer(
            id="cust-1",
            tenant_id="tenant-1",
            phone_hash="hash123",
        )
        assert customer.tenant_id == "tenant-1"

    def test_session_scoped_to_tenant(self):
        """Session should be scoped to a specific tenant."""
        session = CustomerSession(
            phone_hash="hash123",
            tenant_id="tenant-1",
        )
        assert session.tenant_id == "tenant-1"


# ═══════════════════════════════════════════════════════════════
# RE-CONSENT TESTS
# ═══════════════════════════════════════════════════════════════


class TestReConsent:
    """DPDP Rule: Re-consent required after 12 months inactivity."""

    def test_needs_consent_when_never_given(self):
        """Customer without consent should need consent."""
        customer = Customer(
            id="cust-1",
            tenant_id="tenant-1",
            phone_hash="hash123",
            consent_given=False,
        )
        assert customer.needs_consent is True

    def test_no_consent_needed_when_recently_active(self):
        """Recently active customer with consent should not need re-consent."""
        customer = Customer(
            id="cust-1",
            tenant_id="tenant-1",
            phone_hash="hash123",
            consent_given=True,
            last_active=datetime.now(timezone.utc),
        )
        assert customer.needs_consent is False

    def test_needs_reconsent_after_12_months(self):
        """Customer inactive for >12 months should need re-consent."""
        old_date = datetime.now(timezone.utc) - timedelta(days=400)
        customer = Customer(
            id="cust-1",
            tenant_id="tenant-1",
            phone_hash="hash123",
            consent_given=True,
            last_active=old_date,
        )
        assert customer.needs_consent is True


# ═══════════════════════════════════════════════════════════════
# PLAN LIMIT ENFORCEMENT TESTS
# ═══════════════════════════════════════════════════════════════


class TestPlanLimits:
    """Tests for plan feature and limit enforcement."""

    def test_starter_plan_limited_categories(self):
        """Starter plan should only support apparel and jewelry."""
        from core.constants import get_plan_features

        features = get_plan_features("starter")
        assert features["categories"] == ["apparel", "jewelry"]

    def test_starter_plan_no_occasion_agent(self):
        """Starter plan should not have occasion agent."""
        from core.constants import is_feature_enabled

        assert is_feature_enabled("starter", "occasion_agent") is False

    def test_essential_plan_has_occasion_agent(self):
        """Essential plan should have occasion agent."""
        from core.constants import is_feature_enabled

        assert is_feature_enabled("essential", "occasion_agent") is True

    def test_enterprise_unlimited_tryons(self):
        """Enterprise plan should have unlimited try-ons."""
        from core.constants import get_monthly_limit

        assert get_monthly_limit("enterprise") is None

    def test_starter_1000_monthly_limit(self):
        """Starter plan should have 1000 monthly try-on limit."""
        from core.constants import get_monthly_limit

        assert get_monthly_limit("starter") == 1000


# ═══════════════════════════════════════════════════════════════
# WEBHOOK SECURITY TESTS
# ═══════════════════════════════════════════════════════════════


class TestWebhookSecurity:
    """Tests for webhook HMAC signature verification."""

    def test_valid_signature_passes(self):
        """Valid HMAC signature should pass verification."""
        import hmac
        import hashlib

        with patch("core.security.get_settings") as mock_settings:
            mock_settings.return_value.whatsapp_app_secret = "test_secret"

            from core.security import verify_webhook_signature

            payload = b'{"test": "data"}'
            signature = "sha256=" + hmac.new(
                b"test_secret",
                payload,
                hashlib.sha256,
            ).hexdigest()

            assert verify_webhook_signature(payload, signature) is True

    def test_invalid_signature_fails(self):
        """Invalid HMAC signature should fail verification."""
        with patch("core.security.get_settings") as mock_settings:
            mock_settings.return_value.whatsapp_app_secret = "test_secret"

            from core.security import verify_webhook_signature

            payload = b'{"test": "data"}'
            assert verify_webhook_signature(payload, "sha256=invalid") is False

    def test_missing_signature_fails(self):
        """Missing signature header should fail verification."""
        from core.security import verify_webhook_signature

        assert verify_webhook_signature(b"data", "") is False
