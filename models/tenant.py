"""
ZukoLabs VTO — Tenant / Seller Pydantic Models

Represents a seller/client who subscribes to the VTO platform.
Each tenant gets a dedicated WhatsApp-powered try-on bot.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TenantSettings(BaseModel):
    """Per-tenant configuration stored in tenants.settings JSONB column."""

    llm_prompt: Optional[str] = None
    privacy_url: str = "https://zukolabs.com/privacy"
    language_templates: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    custom_greeting: Optional[str] = None
    buy_now_url: Optional[str] = None


class Tenant(BaseModel):
    """Tenant (seller/client) model matching the tenants DB schema."""

    id: str
    phone_number_id: str
    business_name: str
    plan: str = "starter"
    whatsapp_number: str
    language: str = "en"
    catalog_enabled: bool = True
    active: bool = True
    created_at: Optional[datetime] = None
    settings: TenantSettings = Field(default_factory=TenantSettings)

    class Config:
        from_attributes = True

    @property
    def supported_categories(self) -> List[str]:
        """Get categories supported by this tenant's plan."""
        from core.constants import get_plan_features
        return get_plan_features(self.plan).get("categories", ["apparel"])

    @property
    def monthly_limit(self) -> Optional[int]:
        """Get monthly try-on limit for this tenant's plan."""
        from core.constants import get_monthly_limit
        return get_monthly_limit(self.plan)

    def has_feature(self, feature: str) -> bool:
        """Check if a feature is enabled for this tenant's plan."""
        from core.constants import is_feature_enabled
        return is_feature_enabled(self.plan, feature)


class TenantCreate(BaseModel):
    """Schema for creating a new tenant via admin API."""

    phone_number_id: str
    business_name: str
    plan: str = "starter"
    whatsapp_number: str
    language: str = "en"
    catalog_enabled: bool = True
    settings: TenantSettings = Field(default_factory=TenantSettings)


class TenantStats(BaseModel):
    """Tenant usage statistics for the admin dashboard."""

    tenant_id: str
    business_name: str
    plan: str
    tryons_this_month: int = 0
    monthly_limit: Optional[int] = None
    total_customers: int = 0
    active_customers_30d: int = 0
    catalog_items_count: int = 0
