"""
ZukoLabs VTO — Supabase Database Client

Singleton Supabase client initialization.
Uses service role key for server-side operations.
"""

import logging
from functools import lru_cache

from supabase import create_client, Client

from core.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache()
def get_supabase_client() -> Client:
    """
    Returns a cached singleton Supabase client using the service role key.
    This key has full access — NEVER expose to client-side code.
    """
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_key:
        logger.warning(
            "Supabase credentials not configured. "
            "Database operations will fail."
        )
    client = create_client(
        settings.supabase_url,
        settings.supabase_service_key,
    )
    logger.info("Supabase client initialized for %s", settings.supabase_url)
    return client


async def set_tenant_context(client: Client, tenant_id: str) -> None:
    """
    Set the tenant context for Row Level Security (RLS) policies.
    Must be called before every tenant-scoped query.
    """
    client.postgrest.auth(
        token=get_settings().supabase_service_key,
        headers={"x-tenant-id": tenant_id},
    )


def get_db() -> Client:
    """Alias for get_supabase_client() — shorter import."""
    return get_supabase_client()
