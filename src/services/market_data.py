"""Market data service combining Groww data with technical indicator computation."""

import logging
from datetime import datetime, timedelta

from src.models.holdings import Holding
from src.models.market import Candle, Quote, TechnicalIndicators
from src.services.groww_service import groww_service
from src.utils.indicators import (
    compute_bollinger_bands,
    compute_ema,
    compute_macd,
    compute_rsi,
    compute_sma,
)

logger = logging.getLogger(__name__)


class MarketDataService:
    """Combines live market data from Groww with technical analysis."""

    async def get_enriched_quote(self, trading_symbol: str) -> dict:
        """Get real-time quote + technical indicators for a symbol.

        Fetches 90 days of daily candles to compute indicators.

        Returns:
            Dict with 'quote' (Quote), 'indicators' (TechnicalIndicators),
            and 'candles_count' (int).
        """
        # Fetch live quote
        quote = await groww_service.get_quote(trading_symbol)

        # Fetch historical candles for indicator computation
        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_time = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")

        candles = await groww_service.get_historical_candles(
            trading_symbol=trading_symbol,
            exchange="NSE",
            segment="CASH",
            start_time=start_time,
            end_time=end_time,
            interval_minutes=1440,  # daily candles
        )

        indicators = self._compute_indicators(trading_symbol, candles)

        return {
            "quote": quote,
            "indicators": indicators,
            "candles_count": len(candles),
        }

    async def get_portfolio_prices(self, holdings: list[Holding]) -> dict[str, float]:
        """Bulk fetch LTP for all holdings.

        Returns: dict mapping symbol key to price.
        """
        symbols = [h.trading_symbol for h in holdings]
        return await groww_service.get_bulk_ltp(symbols)

    async def get_historical_with_indicators(
        self,
        trading_symbol: str,
        days_back: int = 90,
        interval_minutes: int = 1440,
    ) -> dict:
        """Fetch historical data and compute indicators.

        Returns:
            Dict with 'candles', 'indicators', 'candles_count'.
        """
        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_time = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M:%S")

        candles = await groww_service.get_historical_candles(
            trading_symbol=trading_symbol,
            exchange="NSE",
            segment="CASH",
            start_time=start_time,
            end_time=end_time,
            interval_minutes=interval_minutes,
        )

        indicators = self._compute_indicators(trading_symbol, candles)

        return {
            "candles": candles,
            "indicators": indicators,
            "candles_count": len(candles),
        }

    def _compute_indicators(
        self, symbol: str, candles: list[Candle]
    ) -> TechnicalIndicators:
        """Compute all technical indicators from candle data."""
        closes = [c.close for c in candles]

        if len(closes) < 2:
            return TechnicalIndicators(trading_symbol=symbol)

        macd = compute_macd(closes)
        bb = compute_bollinger_bands(closes)

        return TechnicalIndicators(
            trading_symbol=symbol,
            rsi_14=compute_rsi(closes, period=14),
            macd_line=macd["macd_line"],
            macd_signal=macd["signal_line"],
            macd_histogram=macd["histogram"],
            sma_20=compute_sma(closes, period=20),
            sma_50=compute_sma(closes, period=50),
            sma_200=compute_sma(closes, period=200),
            ema_12=compute_ema(closes, period=12),
            ema_26=compute_ema(closes, period=26),
            bb_upper=bb["upper"],
            bb_middle=bb["middle"],
            bb_lower=bb["lower"],
            bb_width=bb["width"],
        )


# Singleton
market_data_service = MarketDataService()
