"""
ZukoLabs VTO — Try-On Job Pydantic Models

Represents a virtual try-on generation job.
Tracks status from pending → processing → completed/failed.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from core.constants import TryOnStatus


class TryOnJob(BaseModel):
    """Try-on job model matching the tryon_jobs DB schema."""

    id: str
    tenant_id: str
    customer_id: str
    status: TryOnStatus = TryOnStatus.PENDING
    category: str
    product_ref: Optional[str] = None
    selfie_path: Optional[str] = None
    output_path: Optional[str] = None
    output_url: Optional[str] = None
    error_message: Optional[str] = None
    replicate_id: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @property
    def is_terminal(self) -> bool:
        """Check if the job is in a terminal state (completed or failed)."""
        return self.status in (TryOnStatus.COMPLETED, TryOnStatus.FAILED)


class TryOnJobCreate(BaseModel):
    """Schema for creating a new try-on job."""

    tenant_id: str
    customer_id: str
    category: str
    product_ref: Optional[str] = None
    selfie_path: Optional[str] = None


class TryOnResult(BaseModel):
    """Result returned after try-on generation completes."""

    job_id: str
    status: TryOnStatus
    output_url: Optional[str] = None
    error_message: Optional[str] = None
