"""FastAPI application entry point with lifespan management.

Startup order:
    1. Configure logging
    2. Connect to MongoDB
    3. Authenticate with Groww
    4. Initialize Telegram bot
    5. Start scheduler
    6. Send startup notification

Shutdown: reverse order.

Run with: uvicorn src.main:app --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from src.api.router import router as api_router
from src.config import settings
from src.scheduler.setup import create_scheduler, register_jobs
from src.services.database import db
from src.services.groww_service import groww_service
from src.services.telegram_bot import telegram_service
from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""

    # --- STARTUP ---
    setup_logging()
    logger.info("Starting Stock AI Portfolio Monitor")

    # 1. Connect to MongoDB
    await db.connect()
    logger.info("MongoDB connected")

    # 2. Authenticate with Groww
    await groww_service.authenticate()
    logger.info("Groww API authenticated")

    # 3. Initialize and start Telegram bot
    await telegram_service.initialize()
    await telegram_service.start()
    logger.info("Telegram bot started")

    # 4. Setup and start scheduler
    scheduler = create_scheduler()
    register_jobs(scheduler)
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("Scheduler started with market-hours jobs")

    # 5. Send startup notification
    try:
        await telegram_service.send_message(
            "<b>Stock AI Monitor Started</b>\n\n"
            "All systems online. Monitoring will run during market hours.\n"
            "Use /help to see available commands."
        )
    except Exception as e:
        logger.warning(f"Could not send startup notification: {e}")

    logger.info("All services initialized successfully")

    yield  # --- APPLICATION RUNNING ---

    # --- SHUTDOWN ---
    logger.info("Shutting down Stock AI Portfolio Monitor")

    scheduler.shutdown(wait=True)
    logger.info("Scheduler stopped")

    await telegram_service.stop()
    logger.info("Telegram bot stopped")

    await db.disconnect()
    logger.info("MongoDB disconnected")

    logger.info("Shutdown complete")


# Create the FastAPI application
app = FastAPI(
    title="Stock AI Portfolio Monitor",
    description="AI-powered stock portfolio monitoring with Groww Trading API",
    version="0.1.0",
    lifespan=lifespan,
)

# Include API routes
app.include_router(api_router, prefix="/api/v1", tags=["API"])


# Health check endpoint
@app.get("/health", tags=["System"])
async def health():
    """Basic health check endpoint."""
    return {"status": "ok", "service": "stock-ai", "version": "0.1.0"}


# Telegram webhook endpoint
@app.post("/webhook", tags=["System"])
async def telegram_webhook(request: Request):
    """Receive Telegram updates via webhook."""
    data = await request.json()
    await telegram_service.process_update(data)
    return {"ok": True}





