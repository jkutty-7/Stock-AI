"""NSE market hours, holidays, and trading session utilities."""

from datetime import date, datetime, time, timedelta

import pytz

IST = pytz.timezone("Asia/Kolkata")

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)

# NSE holidays for 2026 (update annually from NSE circular)
# Source: NSE Market Holidays 2026
# Note: Holidays falling on Saturday/Sunday are excluded (market already closed)
NSE_HOLIDAYS_2026: list[date] = [
    date(2026, 1, 15),   # Municipal Corporation Election in Maharashtra
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 3),    # Holi
    date(2026, 3, 26),   # Shri Ram Navami
    date(2026, 3, 31),   # Shri Mahavir Jayanti
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 5, 28),   # Bakri Id
    date(2026, 6, 26),   # Muharram
    date(2026, 9, 14),   # Ganesh Chaturthi
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 20),  # Dussehra
    date(2026, 11, 10),  # Diwali–Balipratipada
    date(2026, 11, 24),  # Prakash Gurpurb Sri Guru Nanak Dev
    date(2026, 12, 25),  # Christmas
]


def now_ist() -> datetime:
    """Get current time in IST."""
    return datetime.now(IST)


def is_market_holiday(dt: datetime | date | None = None) -> bool:
    """Check if a date is an NSE holiday."""
    if dt is None:
        dt = now_ist()
    check_date = dt.date() if isinstance(dt, datetime) else dt
    return check_date in NSE_HOLIDAYS_2026


def is_weekend(dt: datetime | date | None = None) -> bool:
    """Check if a date is Saturday or Sunday."""
    if dt is None:
        dt = now_ist()
    check_date = dt.date() if isinstance(dt, datetime) else dt
    return check_date.weekday() >= 5  # Saturday=5, Sunday=6


def is_trading_day(dt: datetime | date | None = None) -> bool:
    """Check if a date is a valid trading day (weekday and not a holiday)."""
    if dt is None:
        dt = now_ist()
    return not is_weekend(dt) and not is_market_holiday(dt)


def is_market_open(dt: datetime | None = None) -> bool:
    """Check if the market is currently open for trading."""
    now = dt or now_ist()

    if not is_trading_day(now):
        return False

    current_time = now.time()
    return MARKET_OPEN <= current_time <= MARKET_CLOSE


def is_pre_market(dt: datetime | None = None) -> bool:
    """Check if we're in the pre-market window (9:00 - 9:15 IST)."""
    now = dt or now_ist()
    if not is_trading_day(now):
        return False
    current_time = now.time()
    return time(9, 0) <= current_time < MARKET_OPEN


def time_to_market_close(dt: datetime | None = None) -> float:
    """Minutes remaining until market close. Returns 0 if market is closed."""
    now = dt or now_ist()
    if not is_market_open(now):
        return 0.0

    close_dt = now.replace(
        hour=MARKET_CLOSE.hour,
        minute=MARKET_CLOSE.minute,
        second=0,
        microsecond=0,
    )
    diff = (close_dt - now).total_seconds() / 60.0
    return max(0.0, diff)


def is_post_market(dt: datetime | None = None) -> bool:
    """Check if we're in the post-market window (15:30 - 16:00 IST)."""
    now = dt or now_ist()
    if not is_trading_day(now):
        return False
    current_time = now.time()
    return MARKET_CLOSE < current_time <= time(16, 0)


def get_session_type(dt: datetime | None = None) -> str:
    """Return the current trading session type.

    Returns:
        'pre'     — 09:00 - 09:15 IST (pre-market)
        'market'  — 09:15 - 15:30 IST (regular market hours)
        'post'    — 15:30 - 16:00 IST (post-market)
        'closed'  — all other times / holidays / weekends
    """
    now = dt or now_ist()
    if is_market_open(now):
        return "market"
    if is_pre_market(now):
        return "pre"
    if is_post_market(now):
        return "post"
    return "closed"


def next_market_open(dt: datetime | None = None) -> datetime:
    """Calculate the next market opening datetime in IST."""
    now = dt or now_ist()
    candidate = now.replace(
        hour=MARKET_OPEN.hour,
        minute=MARKET_OPEN.minute,
        second=0,
        microsecond=0,
    )

    # If market hasn't opened today yet and it's a trading day
    if is_trading_day(now) and now.time() < MARKET_OPEN:
        return candidate

    # Move to next day
    candidate += timedelta(days=1)
    while not is_trading_day(candidate):
        candidate += timedelta(days=1)

    return candidate
