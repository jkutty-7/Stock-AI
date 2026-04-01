"""Event Risk Filter — NSE corporate calendar scraping and entry blocking (Phase 3C).

Prevents new entries before known corporate events such as board meetings (results),
dividend ex-dates, bonus ex-dates, splits, and AGMs.

Data is scraped daily from NSE India and cached in MongoDB with a 30-day TTL.
An in-memory cache (per-symbol dict) is rebuilt from DB on startup and after refresh.

Usage:
    from src.services.event_risk_filter import event_risk_filter

    risk = await event_risk_filter.check_entry_risk("RELIANCE")
    if risk.blocked:
        logger.warning(f"Entry blocked: {risk.reason}")
"""

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from src.config import settings
from src.models.calibration import CorporateEvent, EventRisk

logger = logging.getLogger(__name__)

# ─── NSE API details ──────────────────────────────────────────────────────────

_NSE_HOME_URL = "https://www.nseindia.com/"
_NSE_CORP_ACTIONS_URL = (
    "https://www.nseindia.com/api/corporates-corporateActions"
    "?index=equities&from_date={from_date}&to_date={to_date}"
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

# Event type normalization — keyword (lowercase) → canonical type
_EVENT_TYPE_MAP: list[tuple[str, str]] = [
    ("board meeting", "BOARD_MEETING_RESULTS"),
    ("quarterly results", "BOARD_MEETING_RESULTS"),
    ("annual results", "BOARD_MEETING_RESULTS"),
    ("half yearly results", "BOARD_MEETING_RESULTS"),
    ("ex-date", "DIVIDEND_EX"),
    ("dividend", "DIVIDEND_EX"),
    ("interim dividend", "DIVIDEND_EX"),
    ("final dividend", "DIVIDEND_EX"),
    ("bonus", "BONUS_EX"),
    ("split", "SPLIT"),
    ("stock split", "SPLIT"),
    ("agm", "AGM"),
    ("annual general", "AGM"),
    ("buyback", "BUYBACK"),
    ("buy-back", "BUYBACK"),
    ("rights", "RIGHTS"),
]

# Date formats used by NSE responses
_DATE_FORMATS = [
    "%d-%b-%Y",   # 15-Mar-2026 (most common)
    "%Y-%m-%d",   # 2026-03-15
    "%d/%m/%Y",   # 15/03/2026
    "%d-%m-%Y",   # 15-03-2026
    "%b %d, %Y",  # Mar 15, 2026
]


class EventRiskFilter:
    """Fetches NSE corporate calendar, caches events, and gates trade entries."""

    def __init__(self) -> None:
        # symbol (upper) → list of upcoming CorporateEvents
        self._cache: dict[str, list[CorporateEvent]] = {}
        self._last_refresh: Optional[datetime] = None
        self._refresh_lock = asyncio.Lock()

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    async def refresh_calendar(self) -> int:
        """Fetch the next 30 days of corporate actions from NSE and store in MongoDB.

        Returns:
            Number of events saved/updated.
        """
        async with self._refresh_lock:
            try:
                events = await self._fetch_nse_events()
                if not events:
                    logger.warning("EventRiskFilter: No events fetched from NSE — cache unchanged")
                    return 0

                from src.services.database import db

                saved = 0
                for evt in events:
                    # Store event_date as midnight UTC datetime for MongoDB TTL compatibility
                    event_dt = datetime.combine(evt.event_date, datetime.min.time())
                    doc = {
                        "symbol": evt.symbol,
                        "event_type": evt.event_type,
                        "event_date": event_dt,
                        "description": evt.description,
                        "source": evt.source,
                        "scraped_at": datetime.now(),
                    }
                    await db.corporate_events.update_one(
                        {
                            "symbol": evt.symbol,
                            "event_type": evt.event_type,
                            "event_date": event_dt,
                        },
                        {"$set": doc},
                        upsert=True,
                    )
                    saved += 1

                await self._reload_cache()
                self._last_refresh = datetime.now()
                logger.info(f"EventRiskFilter: Refreshed {saved} events from NSE")
                return saved

            except Exception as exc:
                logger.error(f"EventRiskFilter.refresh_calendar error: {exc}", exc_info=True)
                return 0

    async def check_entry_risk(
        self,
        symbol: str,
        days_ahead: Optional[int] = None,
    ) -> EventRisk:
        """Check whether a corporate event blocks entry for a given symbol.

        Args:
            symbol: NSE trading symbol (e.g., "RELIANCE").
            days_ahead: Look-ahead window in days. Defaults to settings.event_risk_lookback_days.

        Returns:
            EventRisk with blocked=True if an event falls within the window.
        """
        if not settings.event_risk_enabled:
            return EventRisk(symbol=symbol, blocked=False)

        # Lazy-load cache if empty
        if not self._cache:
            try:
                await self._reload_cache()
            except Exception as exc:
                logger.warning(f"EventRiskFilter: cache reload failed: {exc}")

        lookback = days_ahead if days_ahead is not None else settings.event_risk_lookback_days
        today = date.today()
        cutoff = today + timedelta(days=lookback)

        # Check symbol and common variants (e.g., RELIANCE-EQ → RELIANCE)
        sym_upper = symbol.upper()
        base_sym = sym_upper.replace("-EQ", "").replace("-BE", "").replace("-SM", "")
        candidates = list(self._cache.get(sym_upper, [])) + (
            self._cache.get(base_sym, []) if base_sym != sym_upper else []
        )

        for evt in candidates:
            if today <= evt.event_date <= cutoff:
                days_until = (evt.event_date - today).days
                friendly_type = evt.event_type.replace("_", " ").title()
                return EventRisk(
                    symbol=symbol,
                    blocked=True,
                    reason=f"{friendly_type} in {days_until} day(s): {evt.description[:120]}",
                    event_date=evt.event_date,
                    event_type=evt.event_type,
                    days_until_event=days_until,
                )

        return EventRisk(symbol=symbol, blocked=False)

    async def get_events_for_holdings(
        self,
        symbols: list[str],
        days_ahead: int = 14,
    ) -> dict[str, list[CorporateEvent]]:
        """Get all upcoming events for a list of holdings.

        Args:
            symbols: List of trading symbols.
            days_ahead: Look-ahead window in days.

        Returns:
            Dict mapping symbol → sorted list of upcoming events.
        """
        if not self._cache:
            try:
                await self._reload_cache()
            except Exception:
                pass

        today = date.today()
        cutoff = today + timedelta(days=days_ahead)
        result: dict[str, list[CorporateEvent]] = {}

        for sym in symbols:
            sym_upper = sym.upper()
            events = self._cache.get(sym_upper, [])
            upcoming = [e for e in events if today <= e.event_date <= cutoff]
            if upcoming:
                result[sym] = sorted(upcoming, key=lambda e: e.event_date)

        return result

    @property
    def last_refresh(self) -> Optional[datetime]:
        """Timestamp of the last successful calendar refresh."""
        return self._last_refresh

    @property
    def cache_size(self) -> int:
        """Number of symbols with cached events."""
        return len(self._cache)

    # ──────────────────────────────────────────────────────────────────────────
    # NSE Fetching
    # ──────────────────────────────────────────────────────────────────────────

    async def _fetch_nse_events(self) -> list[CorporateEvent]:
        """Try httpx first, fall back to urllib."""
        try:
            import httpx  # type: ignore
            return await self._fetch_via_httpx(httpx)
        except ImportError:
            logger.debug("httpx not installed — falling back to urllib for NSE events")
            return await self._fetch_via_urllib()
        except Exception as exc:
            logger.error(f"NSE fetch (httpx) failed: {exc}")
            # Try urllib as secondary fallback
            try:
                return await self._fetch_via_urllib()
            except Exception as exc2:
                logger.error(f"NSE fetch (urllib) also failed: {exc2}")
                return []

    async def _fetch_via_httpx(self, httpx) -> list[CorporateEvent]:
        today_str = date.today().strftime("%d-%m-%Y")
        end_str = (date.today() + timedelta(days=30)).strftime("%d-%m-%Y")
        url = _NSE_CORP_ACTIONS_URL.format(from_date=today_str, to_date=end_str)

        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, verify=False
        ) as client:
            # Prime session cookies with homepage hit
            try:
                await client.get(_NSE_HOME_URL, headers=_HEADERS)
                await asyncio.sleep(1.2)
            except Exception:
                pass

            resp = await client.get(url, headers=_HEADERS)
            resp.raise_for_status()
            return self._parse_response(resp.json())

    async def _fetch_via_urllib(self) -> list[CorporateEvent]:
        import ssl
        import urllib.request

        today_str = date.today().strftime("%d-%m-%Y")
        end_str = (date.today() + timedelta(days=30)).strftime("%d-%m-%Y")
        url = _NSE_CORP_ACTIONS_URL.format(from_date=today_str, to_date=end_str)

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(url, headers=_HEADERS)

        loop = asyncio.get_event_loop()

        def _do_fetch():
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))

        data = await loop.run_in_executor(None, _do_fetch)
        return self._parse_response(data)

    def _parse_response(self, data: list | dict) -> list[CorporateEvent]:
        """Convert raw NSE API response to CorporateEvent objects."""
        events: list[CorporateEvent] = []

        # NSE sometimes wraps in a dict
        if isinstance(data, dict):
            data = (
                data.get("data")
                or data.get("corporateActions")
                or data.get("table")
                or []
            )
        if not isinstance(data, list):
            return events

        for item in data:
            try:
                symbol = (
                    item.get("symbol")
                    or item.get("SYMBOL")
                    or item.get("nse_symbol", "")
                ).upper().strip()

                purpose = str(
                    item.get("purpose")
                    or item.get("PURPOSE")
                    or item.get("subject")
                    or item.get("action")
                    or ""
                )

                date_raw = str(
                    item.get("ex_date")
                    or item.get("EX_DATE")
                    or item.get("exDate")
                    or item.get("record_date")
                    or item.get("bcStartDate")
                    or ""
                ).strip()

                if not symbol or not date_raw or symbol == "-":
                    continue

                event_date = self._parse_date(date_raw)
                if not event_date:
                    continue

                # Skip past events
                if event_date < date.today():
                    continue

                event_type = self._classify_event(purpose)
                events.append(
                    CorporateEvent(
                        symbol=symbol,
                        event_type=event_type,
                        event_date=event_date,
                        description=purpose[:200],
                        source="NSE",
                    )
                )
            except Exception:
                continue

        return events

    # ──────────────────────────────────────────────────────────────────────────
    # Cache Management
    # ──────────────────────────────────────────────────────────────────────────

    async def _reload_cache(self) -> None:
        """Load all upcoming events from MongoDB into the in-memory dict."""
        from src.services.database import db

        self._cache = {}
        today_dt = datetime.combine(date.today(), datetime.min.time())

        cursor = db.corporate_events.find(
            {"event_date": {"$gte": today_dt}},
            sort=[("event_date", 1)],
        )
        async for doc in cursor:
            symbol = doc.get("symbol", "")
            if not symbol:
                continue

            raw_date = doc.get("event_date")
            if isinstance(raw_date, datetime):
                evt_date = raw_date.date()
            elif isinstance(raw_date, date):
                evt_date = raw_date
            else:
                continue

            if symbol not in self._cache:
                self._cache[symbol] = []

            self._cache[symbol].append(
                CorporateEvent(
                    symbol=symbol,
                    event_type=doc.get("event_type", "OTHER"),
                    event_date=evt_date,
                    description=doc.get("description", ""),
                    source=doc.get("source", "NSE"),
                )
            )

        logger.debug(f"EventRiskFilter cache: {self.cache_size} symbols loaded")

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_date(raw: str) -> Optional[date]:
        """Try multiple NSE date formats. Returns None if parsing fails."""
        raw = raw.strip()
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _classify_event(purpose: str) -> str:
        """Map a free-text purpose string to a canonical event type."""
        lower = purpose.lower()
        for keyword, event_type in _EVENT_TYPE_MAP:
            if keyword in lower:
                return event_type
        return "OTHER"


# ─── Singleton ────────────────────────────────────────────────────────────────
event_risk_filter = EventRiskFilter()
