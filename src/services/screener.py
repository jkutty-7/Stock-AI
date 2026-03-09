"""Stock Screener Engine — Phase 3.

Runs daily at 9:30 AM IST (or on-demand) to discover NSE stocks
likely to gain value based on technical scoring criteria.

Scoring criteria (total 100 points):
    1. RSI < 35 (oversold)            → +25 pts
    2. MACD bullish crossover          → +25 pts
    3. Price > SMA20                   → +15 pts
    4. Volume > 1.5x 5-day avg         → +20 pts
    5. Near 52-week low (within 15%)   → +15 pts

Top candidates are passed to Claude for final ranking and reasoning.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from src.config import settings
from src.utils.indicators import (
    compute_macd,
    compute_rsi,
    compute_sma,
)

logger = logging.getLogger(__name__)

_BATCH_SIZE = 30          # symbols per batch API call
_BATCH_DELAY_SECONDS = 1  # pause between batches (rate limiting)
_MIN_CANDLES = 20         # minimum candles needed to score


@dataclass
class ScreenerCandidate:
    """A stock that passed initial technical screening."""

    symbol: str
    name: str
    sector: str
    score: float                       # 0–100 composite score
    signals: list[str] = field(default_factory=list)  # e.g. ["RSI_oversold"]
    current_price: float = 0.0
    week52_low: float = 0.0
    week52_high: float = 0.0
    rsi: float | None = None
    macd_crossover: str | None = None  # "bullish" / "bearish" / None
    volume_ratio: float = 0.0          # current vol / 5-day avg vol
    above_sma20: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "sector": self.sector,
            "score": round(self.score, 1),
            "signals": self.signals,
            "current_price": self.current_price,
            "week52_low": self.week52_low,
            "week52_high": self.week52_high,
            "rsi": self.rsi,
            "macd_crossover": self.macd_crossover,
            "volume_ratio": round(self.volume_ratio, 2),
            "above_sma20": self.above_sma20,
        }


class ScreenerEngine:
    """Technical screening engine for NSE stocks."""

    def __init__(self) -> None:
        self._universe: list[dict] = []

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    async def run_full_screen(
        self,
        universe: list[dict] | None = None,
    ) -> list[ScreenerCandidate]:
        """Run screening across the stock universe.

        Args:
            universe: Optional list of {symbol, name, sector} dicts.
                      If None, loads from nse_symbols.json or holdings.

        Returns:
            List of ScreenerCandidate sorted by score descending.
        """
        if universe is None:
            universe = await self._load_universe()

        if not universe:
            logger.warning("Screener: empty universe — nothing to screen")
            return []

        # Feature 5: Apply liquidity filter
        if settings.screener_min_liquidity > 0:
            universe = await self._filter_by_liquidity(universe)
            if not universe:
                logger.warning("Screener: no symbols passed liquidity filter")
                return []
            logger.info(f"Screener: {len(universe)} symbols after liquidity filter")

        logger.info(f"Screener: starting full screen of {len(universe)} symbols")
        candidates: list[ScreenerCandidate] = []

        # Process in batches to respect rate limits
        symbols = [u["symbol"] for u in universe]
        symbol_meta = {u["symbol"]: u for u in universe}

        for i in range(0, len(symbols), _BATCH_SIZE):
            batch = symbols[i : i + _BATCH_SIZE]
            batch_results = await self._screen_batch(batch, symbol_meta)
            candidates.extend(batch_results)
            if i + _BATCH_SIZE < len(symbols):
                await asyncio.sleep(_BATCH_DELAY_SECONDS)

        # Sort by score descending
        candidates.sort(key=lambda c: c.score, reverse=True)
        logger.info(
            f"Screener complete. {len(candidates)} candidates scored, "
            f"top score: {candidates[0].score if candidates else 0:.1f}"
        )
        return candidates

    def score_symbol(
        self,
        symbol: str,
        closes: list[float],
        volumes: list[int],
        week52_low: float = 0.0,
        week52_high: float = 0.0,
        current_price: float = 0.0,
    ) -> tuple[float, list[str]]:
        """Compute composite score (0-100) for a symbol.

        Returns:
            (score, signals) where signals is a list of triggered criteria names.
        """
        score = 0.0
        signals: list[str] = []

        if len(closes) < _MIN_CANDLES:
            return 0.0, []

        # 1. RSI oversold (<35) — max 25 pts
        rsi_val = compute_rsi(closes, period=14)
        if rsi_val is not None:
            if rsi_val < 30:
                score += 25
                signals.append("RSI_very_oversold")
            elif rsi_val < 35:
                score += 20
                signals.append("RSI_oversold")
            elif rsi_val < 40:
                score += 10
                signals.append("RSI_approaching_oversold")

        # 2. MACD bullish crossover — compare current vs 1 bar ago — max 25 pts
        macd_now = compute_macd(closes)
        macd_prev = compute_macd(closes[:-1]) if len(closes) > 1 else None
        hist_now = macd_now.get("histogram")
        hist_prev = macd_prev.get("histogram") if macd_prev else None
        if hist_now is not None:
            if hist_prev is not None and hist_prev <= 0 and hist_now > 0:
                score += 25
                signals.append("MACD_bullish_crossover")
            elif hist_now > 0:
                score += 10
                signals.append("MACD_bullish_momentum")

        # 3. Price > SMA20 — max 15 pts
        sma20 = compute_sma(closes, period=20)
        price = current_price or (closes[-1] if closes else 0)
        if sma20 is not None and price > 0 and price > sma20:
            score += 15
            signals.append("price_above_SMA20")

        # 4. Volume spike > 1.5x 5-day avg — max 20 pts
        if len(volumes) >= 6 and volumes[-1] > 0:
            avg_vol = sum(volumes[-6:-1]) / 5
            if avg_vol > 0:
                ratio = volumes[-1] / avg_vol
                if ratio >= 2.0:
                    score += 20
                    signals.append("volume_spike_2x")
                elif ratio >= 1.5:
                    score += 12
                    signals.append("volume_above_avg")

        # 5. Near 52-week low (within 15%) — max 15 pts
        if week52_low > 0 and price > 0:
            pct_above_low = (price - week52_low) / week52_low * 100
            if pct_above_low <= 5:
                score += 15
                signals.append("near_52w_low_5pct")
            elif pct_above_low <= 10:
                score += 10
                signals.append("near_52w_low_10pct")
            elif pct_above_low <= 15:
                score += 5
                signals.append("near_52w_low_15pct")

        return min(score, 100.0), signals

    # ----------------------------------------------------------------
    # Private helpers
    # ----------------------------------------------------------------

    async def _screen_batch(
        self,
        symbols: list[str],
        symbol_meta: dict[str, dict],
    ) -> list[ScreenerCandidate]:
        """Screen a batch of symbols — fetch data + score each."""
        from src.services.groww_service import groww_service

        candidates: list[ScreenerCandidate] = []

        # Fetch bulk LTP for price data
        try:
            prices = await groww_service.get_bulk_ltp(symbols)
        except Exception as e:
            logger.warning(f"Screener: bulk LTP failed for batch: {e}")
            prices = {}

        # Screen each symbol in batch
        for symbol in symbols:
            try:
                candidate = await self._screen_single(
                    symbol=symbol,
                    meta=symbol_meta.get(symbol, {"symbol": symbol, "name": symbol, "sector": "Unknown"}),
                    prices=prices,
                )
                if candidate and candidate.score > 0:
                    candidates.append(candidate)
            except Exception as e:
                logger.debug(f"Screener: error scoring {symbol}: {e}")

        return candidates

    async def _screen_single(
        self,
        symbol: str,
        meta: dict,
        prices: dict[str, float],
    ) -> ScreenerCandidate | None:
        """Screen a single symbol using historical candle data."""
        from src.services.groww_service import groww_service
        from datetime import datetime, timedelta

        # Get current price from bulk LTP
        current_price = groww_service.find_price(prices, symbol)
        if not current_price:
            return None

        # Fetch 90 days of daily candles for technical analysis
        try:
            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            start_time = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")
            candles = await groww_service.get_historical_candles(
                trading_symbol=symbol,
                exchange="NSE",
                segment="CASH",
                start_time=start_time,
                end_time=end_time,
                interval_minutes=1440,  # daily
            )
        except Exception as e:
            logger.debug(f"Screener: candle fetch failed for {symbol}: {e}")
            return None

        if not candles or len(candles) < _MIN_CANDLES:
            return None

        closes = [float(c.close) for c in candles if c.close]
        volumes = [int(c.volume or 0) for c in candles]

        # Compute 52-week range from candle data
        all_closes = closes
        week52_low = min(all_closes) if all_closes else 0.0
        week52_high = max(all_closes) if all_closes else 0.0

        score, signals = self.score_symbol(
            symbol=symbol,
            closes=closes,
            volumes=volumes,
            week52_low=week52_low,
            week52_high=week52_high,
            current_price=current_price,
        )

        # Compute derived fields for the candidate record
        rsi_val = compute_rsi(closes, period=14)
        sma20 = compute_sma(closes, period=20)
        above_sma20 = bool(sma20 and current_price > sma20)

        macd_crossover = None
        macd_data = compute_macd(closes)
        macd_prev_data = compute_macd(closes[:-1]) if len(closes) > 1 else None
        hist_now = macd_data.get("histogram")
        hist_prev = macd_prev_data.get("histogram") if macd_prev_data else None
        if hist_now is not None and hist_prev is not None:
            if hist_prev <= 0 and hist_now > 0:
                macd_crossover = "bullish"
            elif hist_prev >= 0 and hist_now < 0:
                macd_crossover = "bearish"

        vol_ratio = 0.0
        if len(volumes) >= 6 and sum(volumes[-6:-1]) > 0:
            avg5 = sum(volumes[-6:-1]) / 5
            vol_ratio = volumes[-1] / avg5 if avg5 > 0 else 0.0

        return ScreenerCandidate(
            symbol=symbol,
            name=meta.get("name", symbol),
            sector=meta.get("sector", "Unknown"),
            score=score,
            signals=signals,
            current_price=current_price,
            week52_low=round(week52_low, 2),
            week52_high=round(week52_high, 2),
            rsi=round(rsi_val, 1) if rsi_val is not None else None,
            macd_crossover=macd_crossover,
            volume_ratio=vol_ratio,
            above_sma20=above_sma20,
        )

    async def _load_universe(self) -> list[dict]:
        """Load the NSE symbol universe from file or fall back to holdings."""
        import json
        import os

        symbols_file = settings.screener_symbols_file
        if os.path.isfile(symbols_file):
            try:
                with open(symbols_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logger.info(f"Screener: loaded {len(data)} symbols from {symbols_file}")
                return data
            except Exception as e:
                logger.warning(f"Screener: could not load {symbols_file}: {e}")

        # Fallback: use current holdings only
        logger.info("Screener: falling back to holdings-only universe")
        try:
            from src.services.groww_service import groww_service
            holdings = await groww_service.get_holdings()
            return [
                {"symbol": h.trading_symbol, "name": h.trading_symbol, "sector": "Holdings"}
                for h in holdings
            ]
        except Exception as e:
            logger.warning(f"Screener: could not load holdings fallback: {e}")
            return []

    async def _filter_by_liquidity(self, universe: list[dict]) -> list[dict]:
        """Filter out illiquid stocks based on average daily volume (Feature 5).

        Args:
            universe: List of stock dicts with 'symbol' key

        Returns:
            Filtered universe with only liquid stocks (ADV >= min_liquidity)
        """
        from datetime import datetime, timedelta
        from src.services.groww_service import groww_service

        min_liquidity = settings.screener_min_liquidity
        lookback_days = settings.screener_liquidity_lookback_days

        logger.info(
            f"Filtering universe for liquidity: min ADV = {min_liquidity:,} shares "
            f"(lookback: {lookback_days} days)"
        )

        filtered_universe = []
        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_time = (datetime.now() - timedelta(days=lookback_days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        for stock_dict in universe:
            symbol = stock_dict["symbol"]
            try:
                # Fetch daily candles for volume data
                candles = await groww_service.get_historical_candles(
                    trading_symbol=symbol,
                    exchange="NSE",
                    segment="CASH",
                    start_time=start_time,
                    end_time=end_time,
                    interval_minutes=1440,  # Daily
                )

                if not candles or len(candles) < 5:
                    logger.debug(f"{symbol}: insufficient volume data — filtered out")
                    continue

                # Compute average daily volume
                volumes = [int(c.volume) for c in candles if c.volume]
                if not volumes:
                    logger.debug(f"{symbol}: no volume data — filtered out")
                    continue

                avg_volume = sum(volumes) / len(volumes)

                if avg_volume >= min_liquidity:
                    filtered_universe.append(stock_dict)
                    logger.debug(f"{symbol}: ADV {avg_volume:,.0f} — PASS")
                else:
                    logger.debug(f"{symbol}: ADV {avg_volume:,.0f} — FILTERED OUT")

            except Exception as e:
                logger.warning(f"{symbol}: liquidity check failed — {e}")
                continue

            # Small delay to avoid rate limiting (process ~1 symbol/sec)
            await asyncio.sleep(1)

        logger.info(
            f"Liquidity filter complete: {len(filtered_universe)}/{len(universe)} symbols passed"
        )
        return filtered_universe


# Singleton
screener_engine = ScreenerEngine()
