"""Groww Trading API wrapper with TOTP authentication and async support.

The Groww SDK (growwapi) is synchronous. All blocking calls are wrapped
in asyncio.to_thread() to avoid blocking the async event loop.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import pyotp
from growwapi import GrowwAPI

from src.config import settings
from src.models.holdings import Holding, Position
from src.models.market import Candle, Quote
from src.utils.exceptions import GrowwAPIError, GrowwAuthError

logger = logging.getLogger(__name__)


class GrowwService:
    """Async wrapper around the Groww Trading API SDK."""

    _groww: GrowwAPI | None = None
    _totp_gen: pyotp.TOTP

    def __init__(self) -> None:
        self._totp_gen = pyotp.TOTP(settings.groww_totp_secret)

    async def authenticate(self) -> None:
        """Authenticate with Groww using TOTP flow. Call on startup and on auth errors."""
        try:
            totp = self._totp_gen.now()
            access_token = await asyncio.to_thread(
                GrowwAPI.get_access_token,
                api_key=settings.groww_api_key,
                totp=totp,
            )
            self._groww = GrowwAPI(access_token)
            logger.info("Groww API authenticated successfully")
        except Exception as e:
            logger.error(f"Groww authentication failed: {e}")
            raise GrowwAuthError(f"Authentication failed: {e}") from e

    @property
    def client(self) -> GrowwAPI:
        """Get the authenticated GrowwAPI client."""
        if self._groww is None:
            raise GrowwAuthError("GrowwService not authenticated. Call authenticate() first.")
        return self._groww

    async def _call_with_retry(self, func, *args, **kwargs) -> Any:
        """Execute a Groww SDK call with auto-retry on auth failure."""
        try:
            return await asyncio.to_thread(func, *args, **kwargs)
        except Exception as e:
            error_msg = str(e).lower()
            if "auth" in error_msg or "token" in error_msg or "401" in error_msg:
                logger.warning("Groww auth error detected, re-authenticating...")
                await self.authenticate()
                return await asyncio.to_thread(func, *args, **kwargs)
            raise GrowwAPIError(f"Groww API call failed: {e}") from e

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
    ) -> dict[str, float]:
        """Get LTP for multiple symbols (chunked into groups of 50).

        Returns: dict mapping 'EXCHANGE_SYMBOL' to price.
        """
        result: dict[str, float] = {}
        exchange_symbols = [f"NSE_{s}" for s in symbols]

        for i in range(0, len(exchange_symbols), 50):
            chunk = tuple(exchange_symbols[i : i + 50])
            raw = await self._call_with_retry(
                self.client.get_ltp,
                segment=segment,
                exchange_trading_symbols=chunk,
            )
            if isinstance(raw, dict):
                result.update(raw)

            # Brief delay between chunks to respect rate limits
            if i + 50 < len(exchange_symbols):
                await asyncio.sleep(0.15)

        return result

    async def get_bulk_ohlc(
        self,
        symbols: list[str],
        segment: str = "CASH",
    ) -> dict[str, dict]:
        """Get OHLC data for multiple symbols (chunked into groups of 50)."""
        result: dict[str, dict] = {}
        exchange_symbols = [f"NSE_{s}" for s in symbols]

        for i in range(0, len(exchange_symbols), 50):
            chunk = tuple(exchange_symbols[i : i + 50])
            raw = await self._call_with_retry(
                self.client.get_ohlc,
                segment=segment,
                exchange_trading_symbols=chunk,
            )
            if isinstance(raw, dict):
                result.update(raw)

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
        """Fetch historical OHLCV candle data.

        Args:
            trading_symbol: Stock symbol (e.g., 'RELIANCE').
            exchange: Exchange code (default: 'NSE').
            segment: Segment (default: 'CASH').
            start_time: Start time as 'YYYY-MM-DD HH:mm:ss'.
            end_time: End time as 'YYYY-MM-DD HH:mm:ss'.
            interval_minutes: Candle interval in minutes.
                1=1min, 5=5min, 60=1hour, 1440=1day, 10080=1week.
        """
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
        """Parse raw Groww quote response into a Quote model."""
        ohlc = raw.get("ohlc") or {}
        last_price = float(raw.get("last_price") or 0)
        close = float(ohlc.get("close") or raw.get("close") or 0)
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


# Singleton
groww_service = GrowwService()
