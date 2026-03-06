"""Scheduled job functions.

V2 improvements:
- _timed_job() wrapper logs execution duration and success/failure
- Market holiday check at TOP of each job (before any work)
- Failures send Telegram error notification (not just logger.error)
- daily_screener_job added (Phase 3)
"""

import logging
import time
from datetime import datetime

from src.services.database import db
from src.services.groww_service import groww_service
from src.services.portfolio_monitor import portfolio_monitor
from src.services.telegram_bot import telegram_service
from src.utils.formatters import format_analysis_result, format_portfolio_summary, format_screener_results
from src.utils.market_hours import is_market_holiday, now_ist

logger = logging.getLogger(__name__)


async def _timed_job(name: str, coro) -> None:
    """Wrapper that logs job duration and sends Telegram alert on failure."""
    start = time.monotonic()
    try:
        await coro
        elapsed = time.monotonic() - start
        logger.info(f"[Job:{name}] completed in {elapsed:.1f}s")
    except Exception as e:
        elapsed = time.monotonic() - start
        logger.error(f"[Job:{name}] FAILED after {elapsed:.1f}s: {e}", exc_info=True)
        try:
            await telegram_service.send_error_notification(
                f"Scheduled job '{name}' failed: {str(e)[:400]}"
            )
        except Exception:
            logger.error(f"[Job:{name}] Could not send failure notification")


async def monitoring_job() -> None:
    """15-minute portfolio monitoring cycle."""
    # Holiday check first — before any API calls
    if is_market_holiday(now_ist()):
        logger.info("[Job:monitoring] Market holiday — skipping")
        return
    await _timed_job("monitoring", portfolio_monitor.run_monitoring_cycle())


async def market_open_job() -> None:
    """Send market open notification and re-authenticate Groww."""
    if is_market_holiday(now_ist()):
        return

    async def _open():
        logger.info("Market opening — re-authenticating and sending status")
        await groww_service.authenticate()
        await telegram_service.send_message(
            "<b>Market Open</b>\n\n"
            f"NSE/BSE markets are now open.\n"
            f"Monitoring started at {now_ist().strftime('%H:%M IST')}.\n"
            f"10-second price tracking active. Next AI check in 15 minutes."
        )

    await _timed_job("market_open", _open())


async def market_close_job() -> None:
    """Send end-of-day summary after market close."""
    if is_market_holiday(now_ist()):
        return

    async def _close():
        logger.info("Market closed — sending daily summary")
        await portfolio_monitor.run_monitoring_cycle()
        snapshot = await db.get_latest_snapshot()
        if snapshot:
            summary = format_portfolio_summary(snapshot)
            await telegram_service.send_message(f"<b>Market Close Summary</b>\n\n{summary}")
        else:
            await telegram_service.send_message(
                "<b>Market Close</b>\n\nNo portfolio data available for today's summary."
            )

    await _timed_job("market_close", _close())


async def daily_full_analysis_job() -> None:
    """Run comprehensive AI portfolio analysis after market close."""
    if is_market_holiday(now_ist()):
        return

    async def _analysis():
        logger.info("Running daily full AI analysis")
        analysis = await portfolio_monitor.run_full_analysis()
        text = format_analysis_result(analysis)
        await telegram_service.send_message(f"<b>Daily AI Analysis</b>\n\n{text}")

    await _timed_job("daily_analysis", _analysis())


async def health_check_job() -> None:
    """Verify all systems are operational."""
    async def _check():
        await groww_service.get_user_profile()
        await db.portfolio_snapshots.find_one()
        logger.info("[Job:health_check] all systems OK")

    await _timed_job("health_check", _check())


async def daily_screener_job() -> None:
    """Run daily stock screener at 9:30 AM (Phase 3)."""
    if is_market_holiday(now_ist()):
        return

    async def _screen():
        from src.services.screener import screener_engine
        from src.services.ai_engine import ai_engine
        from src.config import settings

        logger.info("Running daily stock screener")
        candidates = await screener_engine.run_full_screen()
        top = candidates[:settings.screener_top_n]
        if not top:
            logger.info("Screener found no candidates today")
            return

        analysis = await ai_engine.analyze_screener_candidates([c.to_dict() for c in top])
        result_doc = {
            "timestamp": datetime.now(),
            "candidates": [c.to_dict() for c in top],
            "claude_analysis": analysis.model_dump(mode="json"),
        }
        await db.save_screener_result(result_doc)

        text = format_screener_results(result_doc)
        await telegram_service.send_message(f"<b>Daily Screener Results</b>\n\n{text}")

    try:
        await _timed_job("daily_screener", _screen())
    except ImportError:
        logger.info("Screener module not yet active — skipping daily_screener_job")
