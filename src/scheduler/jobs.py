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
from src.services.outcome_tracker import outcome_tracker
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


async def outcome_tracking_job() -> None:
    """Auto-track signal outcomes by detecting position exits (Feature 1)."""
    async def _track():
        logger.info("Running outcome auto-tracking job")
        result = await outcome_tracker.auto_track_from_holdings()
        logger.info(
            f"Outcome tracking complete: {result['closed']} closed, "
            f"{result['still_open']} still open, {result['errors']} errors"
        )

        # Send notification if outcomes were closed
        if result["closed"] > 0:
            await telegram_service.send_message(
                f"<b>Outcome Tracker</b>\n\n"
                f"Detected {result['closed']} position exit(s).\n"
                f"Open positions: {result['still_open']}"
            )

    await _timed_job("outcome_tracking", _track())


async def reload_stop_losses_job() -> None:
    """Reload active stop-losses from database into MicroMonitor (Feature 2)."""
    async def _reload():
        from src.services.micro_monitor import micro_monitor
        logger.info("Reloading active stop-losses into MicroMonitor")
        await micro_monitor.load_active_stop_losses()

    await _timed_job("reload_stop_losses", _reload())


async def daily_regime_classification_job() -> None:
    """Classify market regime daily at 9:20 AM (Feature 4)."""
    if is_market_holiday(now_ist()):
        return

    async def _classify():
        from src.services.regime_classifier import regime_classifier
        logger.info("Running daily market regime classification")
        result = await regime_classifier.classify_daily_regime()

        if result["success"]:
            regime = result["regime"]
            score = result["regime_score"]
            message = (
                f"<b>Market Regime Classified</b>\n\n"
                f"Regime: {regime}\n"
                f"Score: {score:.1f}/100\n"
                f"Nifty 50: ₹{result['indicators']['price']:.2f}\n"
                f"RSI(14): {result['indicators']['rsi']:.1f}\n"
                f"Volatility: {result['indicators']['volatility']:.2f}%"
            )
            await telegram_service.send_message(message, parse_mode="HTML")
        else:
            logger.warning(f"Regime classification failed: {result.get('message')}")

    await _timed_job("regime_classification", _classify())


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


async def intraday_premarket_scan_job() -> None:
    """Pre-market intraday scan at 8:55 AM — gap analysis and CPR levels."""
    if is_market_holiday(now_ist()):
        return

    async def _scan():
        from src.config import settings
        if not settings.intraday_enabled:
            return
        from src.services.intraday_scanner import intraday_scanner
        from src.services.intraday_monitor import intraday_monitor
        logger.info("Running intraday pre-market scan")
        setups = await intraday_scanner.run_premarket_scan()
        # Pre-load the watchlist into the monitor
        await intraday_monitor.load_watchlist()
        # Send morning report
        text = intraday_scanner.format_morning_report(setups)
        await telegram_service.send_message(text, parse_mode="HTML")

    try:
        await _timed_job("intraday_premarket_scan", _scan())
    except ImportError:
        logger.info("Intraday module not yet active — skipping premarket scan")


async def intraday_orb_setup_job() -> None:
    """Compute Opening Range Breakout data at 9:31 AM."""
    if is_market_holiday(now_ist()):
        return

    async def _setup():
        from src.config import settings
        if not settings.intraday_enabled:
            return
        from src.services.intraday_monitor import intraday_monitor
        logger.info("Setting up ORB data for intraday watchlist")
        await intraday_monitor.setup_orb()

    try:
        await _timed_job("intraday_orb_setup", _setup())
    except ImportError:
        pass


async def intraday_hard_exit_job() -> None:
    """Send CRITICAL alert at 3:15 PM to exit all open MIS positions."""
    if is_market_holiday(now_ist()):
        return

    async def _exit():
        from src.config import settings
        if not settings.intraday_enabled:
            return
        from src.services.intraday_monitor import intraday_monitor
        logger.info("Intraday hard exit alert — sending to all open positions")
        await intraday_monitor.hard_exit_alert()

    try:
        await _timed_job("intraday_hard_exit", _exit())
    except ImportError:
        pass


async def intraday_daily_report_job() -> None:
    """Generate and send intraday EOD P&L report at 3:35 PM."""
    if is_market_holiday(now_ist()):
        return

    async def _report():
        from src.config import settings
        if not settings.intraday_enabled:
            return
        from src.services.intraday_scanner import intraday_scanner
        logger.info("Generating intraday daily P&L report")
        report = await intraday_scanner.generate_daily_report()
        text = intraday_scanner.format_daily_report(report)
        await telegram_service.send_message(
            f"<b>Intraday EOD</b>\n\n{text}", parse_mode="HTML"
        )

    try:
        await _timed_job("intraday_daily_report", _report())
    except ImportError:
        pass


# ── V3.0 Scheduled Jobs ───────────────────────────────────────────────────────

async def refresh_events_job() -> None:
    """Fetch NSE corporate calendar for the next 30 days (Phase 3C).

    Runs at 8:50 AM before market open and pre-market scan.
    Stores events in MongoDB; in-memory cache rebuilt automatically.
    """
    if is_market_holiday(now_ist()):
        return

    async def _refresh():
        from src.config import settings
        if not settings.event_risk_enabled:
            logger.info("[Job:refresh_events] Event risk filter disabled — skipping")
            return

        from src.services.event_risk_filter import event_risk_filter
        logger.info("Refreshing NSE corporate event calendar")
        saved = await event_risk_filter.refresh_calendar()
        logger.info(f"refresh_events_job: {saved} events saved/updated")

        if saved > 0:
            await telegram_service.send_message(
                f"📅 <b>Event Calendar Refreshed</b>\n\n"
                f"{saved} upcoming corporate events loaded (next 30 days).\n"
                f"Entry risk filter is active.",
                parse_mode="HTML",
            )

    await _timed_job("refresh_events", _refresh())


async def nightly_calibration_job() -> None:
    """Compute signal calibration from closed outcomes (Phase 3A).

    Runs at 8 PM after market close and outcome tracking have completed.
    """
    async def _calibrate():
        from src.config import settings
        if not settings.calibration_enabled:
            logger.info("[Job:nightly_calibration] Calibration disabled — skipping")
            return

        from src.services.signal_calibrator import signal_calibrator
        logger.info("Running nightly signal calibration")
        cal = await signal_calibrator.compute_calibration()
        if cal:
            await signal_calibrator.compute_pattern_performance()
            await signal_calibrator.compute_regime_performance()
            logger.info(
                f"Calibration complete: {cal.total_signals_analyzed} signals analyzed, "
                f"overall win rate {cal.overall_win_rate:.1%}"
            )
        else:
            logger.info("Insufficient data for calibration this run")

    try:
        await _timed_job("nightly_calibration", _calibrate())
    except ImportError:
        logger.info("signal_calibrator not yet active — skipping nightly_calibration_job")


async def portfolio_beta_job() -> None:
    """Compute portfolio beta and correlation matrix after market close (Phase 3B).

    Runs at 4 PM after the market closes.
    """
    if is_market_holiday(now_ist()):
        return

    async def _beta():
        from src.config import settings
        if not settings.capital_allocation_enabled:
            return

        from src.services.capital_allocator import capital_allocator
        logger.info("Computing portfolio beta and correlation matrix")
        report = await capital_allocator.compute_portfolio_beta()
        logger.info(
            f"Portfolio beta: {report.portfolio_beta:.2f} ({report.interpretation})"
        )

        if report.portfolio_beta > 1.5:
            await telegram_service.send_message(
                f" <b>High Portfolio Beta Alert</b>\n\n"
                f"Portfolio β = {report.portfolio_beta:.2f}\n"
                f"{report.interpretation}\n\n"
                f"Consider reducing aggressive positions.",
                parse_mode="HTML",
            )

    try:
        await _timed_job("portfolio_beta", _beta())
    except ImportError:
        logger.info("capital_allocator not yet active — skipping portfolio_beta_job")
