"""
ZukoLabs VTO — Flow Tests

Tests for all chat flows: consent, try-on state machine,
greeting, help, intent routing, and plan limit enforcement.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.constants import Intent, SessionState, MESSAGES
from models.customer import CustomerSession
from models.tenant import Tenant, TenantSettings


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def mock_tenant():
    """Create a mock tenant for testing."""
    return Tenant(
        id="test-tenant-id",
        phone_number_id="123456789",
        business_name="Test Boutique",
        plan="essential",
        whatsapp_number="+919876543210",
        language="en",
        catalog_enabled=True,
        active=True,
        settings=TenantSettings(),
    )


@pytest.fixture
def mock_starter_tenant():
    """Create a mock starter plan tenant."""
    return Tenant(
        id="starter-tenant-id",
        phone_number_id="987654321",
        business_name="Starter Shop",
        plan="starter",
        whatsapp_number="+919876543211",
        language="en",
        catalog_enabled=True,
        active=True,
        settings=TenantSettings(),
    )


@pytest.fixture
def mock_session():
    """Create a mock customer session."""
    return CustomerSession(
        phone_hash="test_phone_hash",
        tenant_id="test-tenant-id",
    )


@pytest.fixture
def mock_customer_data():
    """Create mock customer data."""
    return {
        "id": "test-customer-id",
        "consent_given": True,
        "language": "en",
        "skin_tone_code": None,
    }


@pytest.fixture
def mock_customer_no_consent():
    """Create mock customer data without consent."""
    return {
        "id": "test-customer-id",
        "consent_given": False,
        "language": "en",
    }


# ═══════════════════════════════════════════════════════════════
# INTENT ROUTER TESTS
# ═══════════════════════════════════════════════════════════════


class TestIntentRouter:
    """Tests for the intent router."""

    @pytest.mark.asyncio
    @patch("flows.intent_router.classify_intent")
    async def test_routes_greeting_to_help_flow(
        self, mock_classify, mock_tenant, mock_session, mock_customer_data
    ):
        """Greeting intent should route to help flow."""
        mock_classify.return_value = Intent.GREETING

        from flows.intent_router import route_message

        result = await route_message(
            text="hello",
            message_type="text",
            session=mock_session,
            tenant=mock_tenant,
            customer_data=mock_customer_data,
        )

        assert result["flow"] == "help_flow"
        assert result["intent"] == Intent.GREETING

    @pytest.mark.asyncio
    @patch("flows.intent_router.classify_intent")
    async def test_routes_tryon_to_tryon_flow(
        self, mock_classify, mock_tenant, mock_session, mock_customer_data
    ):
        """Try-on intent should route to tryon_flow."""
        mock_classify.return_value = Intent.TRYON_SINGLE

        from flows.intent_router import route_message

        result = await route_message(
            text="try this on",
            message_type="text",
            session=mock_session,
            tenant=mock_tenant,
            customer_data=mock_customer_data,
        )

        assert result["flow"] == "tryon_flow"

    @pytest.mark.asyncio
    @patch("flows.intent_router.classify_intent")
    async def test_consent_required_before_tryon(
        self, mock_classify, mock_tenant, mock_session, mock_customer_no_consent
    ):
        """Try-on should be blocked when consent is not given."""
        mock_classify.return_value = Intent.TRYON_SINGLE

        from flows.intent_router import route_message

        result = await route_message(
            text="try this on",
            message_type="text",
            session=mock_session,
            tenant=mock_tenant,
            customer_data=mock_customer_no_consent,
        )

        assert result["flow"] == "consent_flow"
        assert result["action"] == "request_consent"

    @pytest.mark.asyncio
    async def test_image_routes_to_tryon_flow(
        self, mock_tenant, mock_session, mock_customer_data
    ):
        """Image message should route to tryon_flow receive_product."""
        from flows.intent_router import route_message

        result = await route_message(
            text="",
            message_type="image",
            session=mock_session,
            tenant=mock_tenant,
            customer_data=mock_customer_data,
            media_id="test-media-id",
        )

        assert result["flow"] == "tryon_flow"
        assert result["action"] == "receive_product"

    @pytest.mark.asyncio
    async def test_awaiting_selfie_state_routes_image_to_selfie(
        self, mock_tenant, mock_session, mock_customer_data
    ):
        """When awaiting selfie, image should route to receive_selfie."""
        mock_session.state = SessionState.AWAITING_SELFIE

        from flows.intent_router import route_message

        result = await route_message(
            text="",
            message_type="image",
            session=mock_session,
            tenant=mock_tenant,
            customer_data=mock_customer_data,
            media_id="selfie-media-id",
        )

        assert result["flow"] == "tryon_flow"
        assert result["action"] == "receive_selfie"

    @pytest.mark.asyncio
    async def test_button_reply_routes_correctly(
        self, mock_tenant, mock_session, mock_customer_data
    ):
        """Button replies should route to correct flows."""
        from flows.intent_router import route_message

        result = await route_message(
            text="",
            message_type="interactive",
            session=mock_session,
            tenant=mock_tenant,
            customer_data=mock_customer_data,
            button_reply_id="try_another",
        )

        assert result["flow"] == "tryon_flow"
        assert result["action"] == "start_new"

    @pytest.mark.asyncio
    @patch("flows.intent_router.classify_intent")
    async def test_occasion_blocked_on_starter_plan(
        self, mock_classify, mock_starter_tenant, mock_session, mock_customer_data
    ):
        """Occasion agent should be blocked for starter plan."""
        mock_classify.return_value = Intent.TRYON_OCCASION

        from flows.intent_router import route_message

        result = await route_message(
            text="wedding outfit",
            message_type="text",
            session=mock_session,
            tenant=mock_starter_tenant,
            customer_data=mock_customer_data,
        )

        assert result["flow"] == "help_flow"
        assert result["action"] == "feature_not_available"


# ═══════════════════════════════════════════════════════════════
# SESSION STATE TESTS
# ═══════════════════════════════════════════════════════════════


class TestSessionState:
    """Tests for customer session state management."""

    def test_session_starts_idle(self, mock_session):
        """New sessions should start in IDLE state."""
        assert mock_session.state == SessionState.IDLE

    def test_session_reset_clears_state(self, mock_session):
        """Reset should clear all pending data."""
        mock_session.state = SessionState.PROCESSING
        mock_session.pending_product_url = "http://example.com/product.jpg"
        mock_session.pending_selfie_url = "http://example.com/selfie.jpg"
        mock_session.current_job_id = "job-123"

        mock_session.reset()

        assert mock_session.state == SessionState.IDLE
        assert mock_session.pending_product_url is None
        assert mock_session.pending_selfie_url is None
        assert mock_session.current_job_id is None


# ═══════════════════════════════════════════════════════════════
# WEBHOOK TESTS
# ═══════════════════════════════════════════════════════════════


class TestWebhookVerification:
    """Tests for webhook verification endpoint."""

    @pytest.mark.asyncio
    async def test_webhook_verification_succeeds(self):
        """Valid verification token should return challenge."""
        from fastapi.testclient import TestClient
        from main import app

        with patch("api.webhook.get_settings") as mock_settings:
            mock_settings.return_value.whatsapp_verify_token = "test_token"

            client = TestClient(app)
            response = client.get(
                "/webhook",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "test_token",
                    "hub.challenge": "test_challenge_123",
                },
            )

            assert response.status_code == 200
            assert response.text == "test_challenge_123"

    @pytest.mark.asyncio
    async def test_webhook_always_returns_200(self):
        """POST webhook should always return 200."""
        from fastapi.testclient import TestClient
        from main import app

        client = TestClient(app)
        response = client.post(
            "/webhook",
            json={"entry": []},
        )

        assert response.status_code == 200
