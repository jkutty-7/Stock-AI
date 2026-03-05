"""APScheduler configuration with market-hours aware cron triggers."""

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import settings

IST = pytz.timezone("Asia/Kolkata")


def create_scheduler() -> AsyncIOScheduler:
    """Create an AsyncIO scheduler configured for IST timezone."""
    return AsyncIOScheduler(timezone=IST)


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    """Register all scheduled jobs with market-hours awareness.

    Jobs:
        1. Portfolio monitor: every 15 min during market hours (Mon-Fri)
        2. Market open notification: 9:15 AM IST
        3. Market close summary: 3:35 PM IST (5 min after close)
        4. Daily full AI analysis: 3:40 PM IST
        5. Health check: every 30 min during market hours
    """
    from src.scheduler.jobs import (
        daily_full_analysis_job,
        health_check_job,
        market_close_job,
        market_open_job,
        monitoring_job,
    )

    # 1. Main monitoring cycle: every N minutes during market hours
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
    )

    # 2. Market open notification
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
    )

    # 3. Market close summary (5 min after close)
    scheduler.add_job(
        market_close_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=15,
            minute=35,
            timezone=IST,
        ),
        id="market_close",
        name="Market Close Summary",
        replace_existing=True,
    )

    # 4. Full AI analysis (10 min after close)
    scheduler.add_job(
        daily_full_analysis_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=15,
            minute=40,
            timezone=IST,
        ),
        id="daily_analysis",
        name="Daily Full AI Analysis",
        replace_existing=True,
    )

    # 5. Health check: every 30 min during market hours
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
    )
