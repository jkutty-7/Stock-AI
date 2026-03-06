"""Groww Trading API wrapper with TOTP authentication and async support.

V2 improvements:
- Bug fix #4: OHLC close key fallback chain (close → ltp → current_price)
- Bug fix #6: BSE symbol prefix support in bulk calls
- Exponential backoff retry (1s, 2s, 4s)
- In-memory circuit breaker (5 failures → open for 60s)
- TTL cache for bulk LTP results (default 8s)
- asyncio.wait_for() timeouts on all SDK calls
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import pyotp
from growwapi import GrowwAPI

from src.config import settings
from src.models.holdings import Holding, Position
from src.models.market import Candle, Quote
from src.utils.cache import TTLCache
from src.utils.circuit_breaker import CircuitBreaker
from src.utils.exceptions import GrowwAPIError, GrowwAuthError, GrowwRateLimitError

logger = logging.getLogger(__name__)

# Supported exchange prefixes (Groww bulk API uses "EXCHANGE_SYMBOL" keys)
_EXCHANGE_PREFIXES = ("NSE_", "BSE_")


class GrowwService:
    """Async wrapper around the Groww Trading API SDK."""

    _groww: Optional[GrowwAPI] = None
    _totp_gen: pyotp.TOTP
    _ltp_cache: TTLCache
    _circuit_breaker: CircuitBreaker

    def __init__(self) -> None:
        self._totp_gen = pyotp.TOTP(settings.groww_totp_secret)
        self._ltp_cache = TTLCache(default_ttl=settings.cache_ttl_seconds)
        self._circuit_breaker = CircuitBreaker(
            threshold=settings.circuit_breaker_threshold,
            reset_seconds=settings.circuit_breaker_reset_seconds,
            name="groww",
        )

    async def authenticate(self) -> None:
        """Authenticate with Groww using TOTP flow."""
        try:
            totp = self._totp_gen.now()
            access_token = await asyncio.wait_for(
                asyncio.to_thread(
                    GrowwAPI.get_access_token,
                    api_key=settings.groww_api_key,
                    totp=totp,
                ),
                timeout=15.0,
            )
            self._groww = GrowwAPI(access_token)
            self._circuit_breaker.record_success()
            logger.info("Groww API authenticated successfully")
        except Exception as e:
            logger.error(f"Groww authentication failed: {e}")
            raise GrowwAuthError(f"Authentication failed: {e}") from e

    @property
    def client(self) -> GrowwAPI:
        if self._groww is None:
            raise GrowwAuthError("GrowwService not authenticated. Call authenticate() first.")
        return self._groww

    # ----------------------------------------------------------------
    # Core call wrapper: retry + circuit breaker + timeout
    # ----------------------------------------------------------------

    async def _call_with_retry(self, func, *args, **kwargs) -> Any:
        """Execute a Groww SDK call with circuit breaker, retry, and timeout."""
        if self._circuit_breaker.is_open():
            raise GrowwAPIError(
                "Groww API circuit open — too many recent failures. Will retry soon.",
                status_code=503,
            )

        last_exc: Exception = RuntimeError("No attempts made")
        for attempt in range(1, settings.max_retry_attempts + 1):
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(func, *args, **kwargs),
                    timeout=10.0,
                )
                self._circuit_breaker.record_success()
                return result

            except asyncio.TimeoutError as e:
                last_exc = e
                logger.warning(f"Groww API timeout (attempt {attempt}/{settings.max_retry_attempts})")

            except Exception as e:
                error_msg = str(e).lower()
                # Re-auth on token errors, then retry once
                if any(k in error_msg for k in ("auth", "token", "401", "unauthorized")):
                    logger.warning("Groww auth error detected, re-authenticating...")
                    try:
                        await self.authenticate()
                    except GrowwAuthError:
                        self._circuit_breaker.record_failure()
                        raise
                    last_exc = e
                    continue  # retry after re-auth

                if "429" in error_msg or "rate limit" in error_msg:
                    self._circuit_breaker.record_failure()
                    raise GrowwRateLimitError() from e

                last_exc = e
                logger.warning(f"Groww API error (attempt {attempt}): {e}")

            # Exponential backoff: 1s, 2s, 4s
            if attempt < settings.max_retry_attempts:
                await asyncio.sleep(2 ** (attempt - 1))

        self._circuit_breaker.record_failure()
        raise GrowwAPIError(f"Groww API call failed after {settings.max_retry_attempts} attempts: {last_exc}") from last_exc

    # ----------------------------------------------------------------
    # Holdings & Positions
    # ----------------------------------------------------------------

    async def get_holdings(self) -> list[Holding]:
        """Fetch all user holdings from Groww."""
        raw = await self._call_with_retry(self.client.get_holdings_for_user, timeout=10)
        holdings_data = raw if isinstance(raw, list) else raw.get("holdings", raw)
        if isinstance(holdings_data, dict):
            holdings_data = [holdings_data]
        return [Holding(**h) for h in holdings_data if isinstance(h, dict)]

    async def get_positions(self, segment: str | None = None) -> list[Position]:
        """Fetch positions, optionally filtered by segment."""
        if segment:
            raw = await self._call_with_retry(
                self.client.get_positions_for_user, segment=segment
            )
        else:
            raw = await self._call_with_retry(self.client.get_positions_for_user)
        positions_data = raw if isinstance(raw, list) else raw.get("positions", raw)
        if isinstance(positions_data, dict):
            positions_data = [positions_data]
        return [Position(**p) for p in positions_data if isinstance(p, dict)]

    # ----------------------------------------------------------------
    # Live Market Data
    # ----------------------------------------------------------------

    async def get_quote(
        self,
        trading_symbol: str,
        exchange: str = "NSE",
        segment: str = "CASH",
    ) -> Quote:
        """Get real-time quote for a single symbol."""
        raw = await self._call_with_retry(
            self.client.get_quote,
            exchange=exchange,
            segment=segment,
            trading_symbol=trading_symbol,
        )
        return self._parse_quote(raw, trading_symbol, exchange)

    async def get_bulk_ltp(
        self,
        symbols: list[str],
        segment: str = "CASH",
        exchange: str = "NSE",
    ) -> dict[str, float]:
        """Get LTP for multiple symbols (chunked into groups of 50).

        Checks cache first. Returns dict mapping 'EXCHANGE_SYMBOL' to price.
        Bug fix: supports both NSE_ and BSE_ prefixes.
        """
        result: dict[str, float] = {}
        uncached_symbols: list[str] = []

        prefix = f"{exchange}_"
        for s in symbols:
            key = f"{prefix}{s}"
            cached = self._ltp_cache.get(key)
            if cached is not None:
                result[key] = cached
            else:
                uncached_symbols.append(s)

        if not uncached_symbols:
            return result

        exchange_symbols = [f"{prefix}{s}" for s in uncached_symbols]
        for i in range(0, len(exchange_symbols), 50):
            chunk = tuple(exchange_symbols[i : i + 50])
            try:
                raw = await self._call_with_retry(
                    self.client.get_ltp,
                    segment=segment,
                    exchange_trading_symbols=chunk,
                )
                if isinstance(raw, dict):
                    result.update(raw)
                    self._ltp_cache.set_many(
                        {k: v for k, v in raw.items() if isinstance(v, (int, float))},
                        ttl=settings.cache_ttl_seconds,
                    )
            except GrowwAPIError as e:
                logger.warning(f"Bulk LTP chunk {i//50 + 1} failed (partial): {e}")

            if i + 50 < len(exchange_symbols):
                await asyncio.sleep(0.15)

        return result

    async def get_bulk_ohlc(
        self,
        symbols: list[str],
        segment: str = "CASH",
        exchange: str = "NSE",
    ) -> dict[str, dict]:
        """Get OHLC data for multiple symbols (chunked into groups of 50).

        Bug fix: supports configurable exchange prefix.
        """
        result: dict[str, dict] = {}
        prefix = f"{exchange}_"
        exchange_symbols = [f"{prefix}{s}" for s in symbols]

        for i in range(0, len(exchange_symbols), 50):
            chunk = tuple(exchange_symbols[i : i + 50])
            try:
                raw = await self._call_with_retry(
                    self.client.get_ohlc,
                    segment=segment,
                    exchange_trading_symbols=chunk,
                )
                if isinstance(raw, dict):
                    result.update(raw)
            except GrowwAPIError as e:
                logger.warning(f"Bulk OHLC chunk {i//50 + 1} failed (partial): {e}")

            if i + 50 < len(exchange_symbols):
                await asyncio.sleep(0.15)

        return result

    # ----------------------------------------------------------------
    # Historical Data
    # ----------------------------------------------------------------

    async def get_historical_candles(
        self,
        trading_symbol: str,
        exchange: str = "NSE",
        segment: str = "CASH",
        start_time: str = "",
        end_time: str = "",
        interval_minutes: int = 1440,
    ) -> list[Candle]:
        """Fetch historical OHLCV candle data."""
        if not start_time:
            start_time = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")
        if not end_time:
            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        raw = await self._call_with_retry(
            self.client.get_historical_candle_data,
            trading_symbol=trading_symbol,
            exchange=exchange,
            segment=segment,
            start_time=start_time,
            end_time=end_time,
            interval_in_minutes=str(interval_minutes),
        )

        candles = []
        candle_data = raw.get("candles", []) if isinstance(raw, dict) else []
        for c in candle_data:
            if len(c) >= 6:
                try:
                    candles.append(
                        Candle(
                            timestamp=datetime.fromtimestamp(c[0]) if isinstance(c[0], (int, float)) else c[0],
                            open=float(c[1]),
                            high=float(c[2]),
                            low=float(c[3]),
                            close=float(c[4]),
                            volume=int(c[5]),
                        )
                    )
                except (ValueError, TypeError) as e:
                    logger.debug(f"Skipping malformed candle for {trading_symbol}: {e}")
        return candles

    # ----------------------------------------------------------------
    # User
    # ----------------------------------------------------------------

    async def get_user_profile(self) -> dict:
        """Get the authenticated user's profile."""
        return await self._call_with_retry(self.client.get_user_profile)

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------

    def _parse_quote(self, raw: dict, symbol: str, exchange: str) -> Quote:
        """Parse raw Groww quote response into a Quote model.

        Bug fix #4: close key fallback — ohlc.close → raw.close → ltp → current_price → 0
        """
        ohlc = raw.get("ohlc") or {}

        # Bug fix: proper fallback chain for close price
        close = (
            ohlc.get("close")
            or raw.get("close")
            or raw.get("previous_close")
            or raw.get("ltp")
            or raw.get("current_price")
            or 0
        )
        close = float(close)

        last_price = float(raw.get("last_price") or raw.get("ltp") or raw.get("current_price") or 0)
        change = last_price - close if close > 0 else 0
        change_pct = (change / close * 100) if close > 0 else 0

        return Quote(
            trading_symbol=symbol,
            exchange=exchange,
            last_price=last_price,
            open=float(ohlc.get("open") or raw.get("open") or 0),
            high=float(ohlc.get("high") or raw.get("high") or 0),
            low=float(ohlc.get("low") or raw.get("low") or 0),
            close=close,
            volume=int(raw.get("volume") or 0),
            high_52w=raw.get("week_52_high"),
            low_52w=raw.get("week_52_low"),
            change=round(change, 2),
            change_pct=round(change_pct, 2),
            bid_price=float(raw.get("bid_price") or 0),
            bid_quantity=int(raw.get("bid_quantity") or 0),
            offer_price=float(raw.get("offer_price") or 0),
            offer_quantity=int(raw.get("offer_quantity") or 0),
            total_buy_quantity=int(raw.get("total_buy_quantity") or 0),
            total_sell_quantity=int(raw.get("total_sell_quantity") or 0),
            upper_circuit_limit=raw.get("upper_circuit_limit"),
            lower_circuit_limit=raw.get("lower_circuit_limit"),
            last_trade_time=raw.get("last_trade_time"),
        )

    def get_price_key(self, symbol: str, exchange: str = "NSE") -> str:
        """Return the exchange-prefixed key used in bulk LTP/OHLC responses."""
        return f"{exchange}_{symbol}"

    def find_price(
        self,
        prices: dict[str, float],
        symbol: str,
        preferred_exchange: str = "NSE",
    ) -> float:
        """Look up a symbol's price, trying NSE then BSE prefix.

        Bug fix #6: portfolio_monitor previously hardcoded 'NSE_' prefix.
        """
        for prefix in (f"{preferred_exchange}_",) + tuple(
            f"{ex}_" for ex in ("NSE", "BSE") if ex != preferred_exchange
        ):
            val = prices.get(f"{prefix}{symbol}")
            if val is not None:
                return float(val)
        return 0.0

    def find_ohlc(
        self,
        ohlc: dict[str, dict],
        symbol: str,
        preferred_exchange: str = "NSE",
    ) -> dict:
        """Look up OHLC data trying NSE then BSE prefix."""
        for prefix in (f"{preferred_exchange}_",) + tuple(
            f"{ex}_" for ex in ("NSE", "BSE") if ex != preferred_exchange
        ):
            val = ohlc.get(f"{prefix}{symbol}")
            if val is not None:
                return val
        return {}


# Singleton
groww_service = GrowwService()
