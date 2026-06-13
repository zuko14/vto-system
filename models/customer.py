"""
ZukoLabs VTO — Customer Pydantic Models

Represents a customer interacting with a tenant's WhatsApp bot.
Phone numbers are always stored as SHA-256 hashes (DPDP compliance).
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from core.constants import SessionState


class Customer(BaseModel):
    """Customer model matching the customers DB schema."""

    id: str
    tenant_id: str
    phone_hash: str
    consent_given: bool = False
    consent_at: Optional[datetime] = None
    language: str = "en"
    skin_tone_code: Optional[str] = None
    last_active: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @property
    def needs_consent(self) -> bool:
        """Check if customer needs to provide consent before processing."""
        if not self.consent_given:
            return True
        # Re-consent required if inactive for 12 months
        if self.last_active:
            months_inactive = (
                datetime.now(timezone.utc) - self.last_active
            ).days / 30
            if months_inactive > 12:
                return True
        return False


class CustomerSession(BaseModel):
    """
    In-memory session state for a customer interaction.
    Tracks the current flow state, pending product/selfie info.
    """

    phone_hash: str
    tenant_id: str
    state: SessionState = SessionState.IDLE
    pending_product_url: Optional[str] = None
    pending_product_id: Optional[str] = None
    pending_selfie_url: Optional[str] = None
    pending_category: Optional[str] = None
    current_job_id: Optional[str] = None
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    message_count: int = 0

    def reset(self) -> None:
        """Reset session to IDLE state, clearing all pending data."""
        self.state = SessionState.IDLE
        self.pending_product_url = None
        self.pending_product_id = None
        self.pending_selfie_url = None
        self.pending_category = None
        self.current_job_id = None
        self.last_updated = datetime.now(timezone.utc)


class CustomerCreate(BaseModel):
    """Schema for creating a new customer record."""

    tenant_id: str
    phone_hash: str
    language: str = "en"
