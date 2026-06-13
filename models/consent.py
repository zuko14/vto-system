"""
ZukoLabs VTO — Consent Record Pydantic Models

DPDP Act audit trail for consent management.
Consent log records are retained for 7 years (legal requirement).
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from core.constants import ConsentAction


class ConsentRecord(BaseModel):
    """Consent log entry matching the consent_log DB schema."""

    id: str
    tenant_id: str
    phone_hash: str
    action: ConsentAction
    purpose: str = "virtual_tryon"
    ip_hash: Optional[str] = None
    timestamp: Optional[datetime] = None

    class Config:
        from_attributes = True


class ConsentRecordCreate(BaseModel):
    """Schema for creating a new consent log entry."""

    tenant_id: str
    phone_hash: str
    action: ConsentAction
    purpose: str = "virtual_tryon"
    ip_hash: Optional[str] = None
