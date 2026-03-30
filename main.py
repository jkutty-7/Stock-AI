"""FastAPI application entry point with lifespan management.

V3 startup order:
    1. Configure logging
    2. Connect to MongoDB
    3. Authenticate with Groww
    4. Initialize Telegram bot
    5. V3: Load event risk cache from MongoDB (Phase 3C)
    6. Start scheduler
    7. Start MicroMonitor (10-second polling loop) — Phase 2
    8. Start IntradayMonitor (1-minute polling loop) — v2.2
    9. Send startup notification

Shutdown: reverse order.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from src.api.router import router as api_router
from src.config import settings
from src.scheduler.setup import create_scheduler, register_jobs
from src.services.database import db
from src.services.groww_service import groww_service
from src.services.event_risk_filter import event_risk_filter
from src.services.micro_monitor import micro_monitor
from src.services.intraday_monitor import intraday_monitor
from src.services.intraday_scanner import intraday_scanner
from src.services.telegram_bot import telegram_service
from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""

    # --- STARTUP ---
    setup_logging()
    logger.info("Starting Stock AI Portfolio Monitor v2")

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

    # 4. V3.0: Load event risk cache from MongoDB (Phase 3C)
    if settings.event_risk_enabled:
        try:
            await event_risk_filter._reload_cache()
            logger.info(
                f"EventRiskFilter cache loaded: {event_risk_filter.cache_size} symbols"
            )
        except Exception as e:
            logger.warning(f"Could not pre-load event risk cache: {e}")

    # 5. Setup and start scheduler
    scheduler = create_scheduler()
    register_jobs(scheduler)
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("Scheduler started with market-hours jobs")

    # 6. Start MicroMonitor (10-second price polling) — Phase 2
    micro_monitor.start()
    logger.info("MicroMonitor started (10-second price polling)")

    # 7. Start IntradayMonitor (1-minute cycle) — v2.2
    if settings.intraday_enabled:
        await intraday_monitor.start()
        logger.info("IntradayMonitor started (1-minute intraday cycle)")

    # 8. Send startup notification
    try:
        await telegram_service.send_message(
            "<b>Stock AI Monitor v3 Started</b>\n\n"
            "All systems online.\n"
            "• 10-second live price tracking active\n"
            "• AI analysis every 15 minutes during market hours\n"
            "• Event risk filter active — BUY signals guarded before corporate events\n"
            "• Daily screener at 9:30 AM IST\n"
            "Use /help to see all commands."
        )
    except Exception as e:
        logger.warning(f"Could not send startup notification: {e}")

    logger.info("All services initialized successfully")

    yield  # --- APPLICATION RUNNING ---

    # --- SHUTDOWN ---
    logger.info("Shutting down Stock AI Portfolio Monitor v2")

    micro_monitor.stop()
    logger.info("MicroMonitor stopped")

    if settings.intraday_enabled:
        await intraday_monitor.stop()
        logger.info("IntradayMonitor stopped")

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
    description="AI-powered stock portfolio monitoring with Groww Trading API — v2",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api/v1", tags=["API"])


@app.get("/health", tags=["System"])
async def health():
    """Basic health check endpoint."""
    return {
        "status": "ok",
        "service": "stock-ai",
        "version": "3.0.0",
        "micro_monitor": "running" if micro_monitor._running else "stopped",
        "event_risk_cache_size": event_risk_filter.cache_size,
    }


@app.post("/webhook", tags=["System"])
async def telegram_webhook(request: Request):
    """Receive Telegram updates via webhook."""
    body = await request.body()
    if not body:
        return {"ok": True}
    data = await request.json()
    await telegram_service.process_update(data)
    return {"ok": True}



if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
