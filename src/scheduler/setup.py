"""APScheduler configuration with market-hours aware cron triggers.

V2 improvements:
- max_instances=1 on all jobs (prevent overlapping runs)
- Screener job added at 9:30 AM IST (Phase 3)
"""

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.config import settings

IST = pytz.timezone("Asia/Kolkata")


def create_scheduler() -> AsyncIOScheduler:
    """Create an AsyncIO scheduler configured for IST timezone."""
    return AsyncIOScheduler(timezone=IST)


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    """Register all scheduled jobs.

    Jobs:
        1. Portfolio monitor: every 15 min during market hours (Mon-Fri)
        2. Market open notification: 9:15 AM IST
        3. Market close summary: 3:35 PM IST
        4. Daily full AI analysis: 3:40 PM IST
        5. Health check: every 30 min during market hours
        6. Daily screener: 9:30 AM IST (Phase 3)
    """
    from src.scheduler.jobs import (
        daily_full_analysis_job,
        daily_regime_classification_job,
        daily_screener_job,
        health_check_job,
        intraday_daily_report_job,
        intraday_hard_exit_job,
        intraday_orb_setup_job,
        intraday_premarket_scan_job,
        market_close_job,
        market_open_job,
        monitoring_job,
        outcome_tracking_job,
        reload_stop_losses_job,
    )

    # 1. Main monitoring cycle
    scheduler.add_job(
        monitoring_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=f"{settings.market_open_hour}-{settings.market_close_hour}",
            minute=f"*/{settings.monitor_interval_minutes}",
            timezone=IST,
        ),
        id="portfolio_monitor",
        name="Portfolio Monitor (15-min cycle)",
        replace_existing=True,
        misfire_grace_time=120,
        max_instances=1,
    )

    # 2. Market open
    scheduler.add_job(
        market_open_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=settings.market_open_hour,
            minute=settings.market_open_minute,
            timezone=IST,
        ),
        id="market_open",
        name="Market Open Alert",
        replace_existing=True,
        max_instances=1,
    )

    # 3. Market close summary (5 min after close)
    scheduler.add_job(
        market_close_job,
        trigger=CronTrigger(
            day_of_week="mon-fri", hour=15, minute=35, timezone=IST
        ),
        id="market_close",
        name="Market Close Summary",
        replace_existing=True,
        max_instances=1,
    )

    # 4. Full AI analysis (10 min after close)
    scheduler.add_job(
        daily_full_analysis_job,
        trigger=CronTrigger(
            day_of_week="mon-fri", hour=15, minute=40, timezone=IST
        ),
        id="daily_analysis",
        name="Daily Full AI Analysis",
        replace_existing=True,
        max_instances=1,
    )

    # 5. Health check every 30 min
    scheduler.add_job(
        health_check_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=f"{settings.market_open_hour}-{settings.market_close_hour}",
            minute="0,30",
            timezone=IST,
        ),
        id="health_check",
        name="System Health Check",
        replace_existing=True,
        max_instances=1,
    )

    # 6. Daily screener at 9:30 AM (Phase 3)
    scheduler.add_job(
        daily_screener_job,
        trigger=CronTrigger(
            day_of_week="mon-fri", hour=9, minute=30, timezone=IST
        ),
        id="daily_screener",
        name="Daily Stock Screener",
        replace_existing=True,
        max_instances=1,
    )

    # 7. Outcome tracking job - runs every N hours to detect position exits (Feature 1)
    scheduler.add_job(
        outcome_tracking_job,
        trigger=IntervalTrigger(hours=settings.outcome_auto_track_interval_hours),
        id="outcome_tracking",
        name="Signal Outcome Auto-Tracking",
        replace_existing=True,
        max_instances=1,
    )

    # 8. Reload stop-losses hourly during market hours (Feature 2)
    scheduler.add_job(
        reload_stop_losses_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=f"{settings.market_open_hour}-{settings.market_close_hour}",
            minute="0",  # Every hour on the hour
            timezone=IST,
        ),
        id="reload_stop_losses",
        name="Reload Active Stop-Losses",
        replace_existing=True,
        max_instances=1,
    )

    # 9. Daily regime classification at 9:20 AM (Feature 4)
    scheduler.add_job(
        daily_regime_classification_job,
        trigger=CronTrigger(
            day_of_week="mon-fri", hour=9, minute=20, timezone=IST
        ),
        id="regime_classification",
        name="Daily Market Regime Classification",
        replace_existing=True,
        max_instances=1,
    )

    # 10. Intraday pre-market scan at 8:55 AM
    if settings.intraday_enabled:
        scheduler.add_job(
            intraday_premarket_scan_job,
            trigger=CronTrigger(
                day_of_week="mon-fri", hour=8, minute=55, timezone=IST
            ),
            id="intraday_premarket_scan",
            name="Intraday Pre-Market Scan",
            replace_existing=True,
            max_instances=1,
        )

        # 11. ORB setup at 9:31 AM (after first 15-min candle)
        scheduler.add_job(
            intraday_orb_setup_job,
            trigger=CronTrigger(
                day_of_week="mon-fri", hour=9, minute=31, timezone=IST
            ),
            id="intraday_orb_setup",
            name="Intraday ORB Setup",
            replace_existing=True,
            max_instances=1,
        )

        # 12. Hard exit alert at 3:15 PM
        scheduler.add_job(
            intraday_hard_exit_job,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=settings.intraday_hard_exit_hour,
                minute=settings.intraday_hard_exit_minute,
                timezone=IST,
            ),
            id="intraday_hard_exit",
            name="Intraday Hard Exit Alert",
            replace_existing=True,
            max_instances=1,
        )

        # 13. Daily intraday P&L report at 3:35 PM
        scheduler.add_job(
            intraday_daily_report_job,
            trigger=CronTrigger(
                day_of_week="mon-fri", hour=15, minute=35, timezone=IST
            ),
            id="intraday_daily_report",
            name="Intraday Daily P&L Report",
            replace_existing=True,
            max_instances=1,
        )

