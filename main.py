"""
ZukoLabs VTO — FastAPI Application Entry Point

Multi-tenant, WhatsApp-native virtual try-on platform.
Built by ZukoLabs · zukolabs14@gmail.com · Visakhapatnam, India
"""

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings

# ── Configure Logging ─────────────────────────────────────────
settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

logger = logging.getLogger("zukolabs-vto")

# ── Create FastAPI App ────────────────────────────────────────
app = FastAPI(
    title="ZukoLabs VTO",
    description=(
        "WhatsApp-native AI Virtual Try-On SaaS for Indian D2C fashion, "
        "jewelry, and lifestyle sellers."
    ),
    version="1.0.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

# ── CORS Middleware ───────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.is_production else [settings.base_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register Routers ─────────────────────────────────────────
from api.webhook import router as webhook_router
from api.health import router as health_router
from api.admin import router as admin_router
from api.privacy import router as privacy_router

app.include_router(webhook_router)
app.include_router(health_router)
app.include_router(admin_router)
app.include_router(privacy_router)


# ── Startup Event ─────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    """Initialize services on application startup."""
    logger.info("=" * 60)
    logger.info("ZukoLabs VTO starting up...")
    logger.info("Environment: %s", settings.app_env)
    logger.info("Log level: %s", settings.log_level)
    logger.info("Base URL: %s", settings.base_url or "(not set)")
    logger.info("=" * 60)

    # Initialize Supabase client (will log warning if not configured)
    try:
        from core.database import get_db
        get_db()
        logger.info("Database client initialized")
    except Exception as e:
        logger.warning("Database initialization failed: %s", str(e))


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown."""
    logger.info("ZukoLabs VTO shutting down...")


# ── Root Endpoint ─────────────────────────────────────────────
@app.get("/")
async def root():
    """Root endpoint — basic service info."""
    return {
        "service": "ZukoLabs VTO",
        "version": "1.0.0",
        "description": "WhatsApp-native AI Virtual Try-On Platform",
        "health": "/health",
        "docs": "/docs" if not settings.is_production else None,
    }
