"""Scheduled job functions.

Each function is invoked by APScheduler at the configured schedule.
All jobs are wrapped in try/except to prevent scheduler crashes.
"""

import logging
from datetime import datetime

from src.services.database import db
from src.services.groww_service import groww_service
from src.services.portfolio_monitor import portfolio_monitor
from src.services.telegram_bot import telegram_service
from src.utils.formatters import format_analysis_result, format_portfolio_summary
from src.utils.market_hours import is_market_holiday, now_ist

logger = logging.getLogger(__name__)


async def monitoring_job() -> None:
    """15-minute portfolio monitoring cycle.

    Skips execution on market holidays.
    """
    if is_market_holiday(now_ist()):
        logger.info("Market holiday — skipping monitoring cycle")
        return

    try:
        await portfolio_monitor.run_monitoring_cycle()
    except Exception as e:
        logger.error(f"Monitoring job failed: {e}", exc_info=True)


async def market_open_job() -> None:
    """Send market open notification and re-authenticate Groww."""
    if is_market_holiday(now_ist()):
        return

    try:
        logger.info("Market opening — re-authenticating and sending status")

        # Re-authenticate (TOTP token may have changed overnight)
        await groww_service.authenticate()

        # Send opening notification
        await telegram_service.send_message(
            "<b>Market Open</b>\n\n"
            f"NSE/BSE markets are now open.\n"
            f"Monitoring started at {now_ist().strftime('%H:%M IST')}.\n"
            f"Next check in {15} minutes."
        )
    except Exception as e:
        logger.error(f"Market open job failed: {e}", exc_info=True)


async def market_close_job() -> None:
    """Send end-of-day summary after market close."""
    if is_market_holiday(now_ist()):
        return

    try:
        logger.info("Market closed — sending daily summary")

        # Run one final monitoring cycle to capture closing data
        await portfolio_monitor.run_monitoring_cycle()

        # Send summary
        snapshot = await db.get_latest_snapshot()
        if snapshot:
            summary = format_portfolio_summary(snapshot)
            await telegram_service.send_message(
                f"<b>Market Close Summary</b>\n\n{summary}"
            )
        else:
            await telegram_service.send_message(
                "<b>Market Close</b>\n\nNo portfolio data available for today's summary."
            )
    except Exception as e:
        logger.error(f"Market close job failed: {e}", exc_info=True)


async def daily_full_analysis_job() -> None:
    """Run comprehensive AI portfolio analysis after market close."""
    if is_market_holiday(now_ist()):
        return

    try:
        logger.info("Running daily full AI analysis")

        analysis = await portfolio_monitor.run_full_analysis()
        text = format_analysis_result(analysis)
        await telegram_service.send_message(
            f"<b>Daily AI Analysis</b>\n\n{text}"
        )
    except Exception as e:
        logger.error(f"Daily analysis job failed: {e}", exc_info=True)
        await telegram_service.send_error_notification(
            f"Daily analysis failed: {str(e)[:500]}"
        )


async def health_check_job() -> None:
    """Verify all systems are operational.

    Checks: Groww API connectivity, MongoDB connectivity.
    Sends a Telegram error notification if anything is down.
    """
    try:
        # Check Groww API
        await groww_service.get_user_profile()

        # Check MongoDB
        await db.portfolio_snapshots.find_one()

        logger.info("Health check: all systems OK")
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        try:
            await telegram_service.send_error_notification(
                f"Health check failed: {str(e)[:500]}"
            )
        except Exception:
            logger.error("Could not send health check failure notification")
