"""Capital Allocator — Phase 3B of V3.0 Intelligent Capital Architecture.

Provides Kelly-optimal position sizing, correlation guard, sector concentration
check, and portfolio beta computation.

Usage:
    from src.services.capital_allocator import capital_allocator

    kelly = await capital_allocator.get_kelly_recommendation(
        symbol="RELIANCE", action="BUY", confidence=0.75,
        entry_price=2450, stop_loss=2400, target_price=2550,
    )
    corr  = await capital_allocator.check_correlation_guard("RELIANCE")
    check = await capital_allocator.check_sector_limits("RELIANCE")
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from math import floor
from typing import Optional

from src.config import settings
from src.models.calibration import (
    AllocationReport,
    BetaEntry,
    BetaReport,
    CorrelationCheck,
    KellyResult,
    SectorCheck,
)

logger = logging.getLogger(__name__)

# Sector data embedded from nse_symbols.json (loaded lazily)
_SECTOR_CACHE: Optional[dict[str, str]] = None  # symbol → sector


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_sector_map() -> dict[str, str]:
    """Load symbol → sector from nse_symbols.json (cached)."""
    global _SECTOR_CACHE
    if _SECTOR_CACHE is not None:
        return _SECTOR_CACHE
    try:
        with open("nse_symbols.json", encoding="utf-8") as f:
            universe = json.load(f)
        _SECTOR_CACHE = {u["symbol"]: u.get("sector", "Unknown") for u in universe}
    except Exception:
        _SECTOR_CACHE = {}
    return _SECTOR_CACHE


class CapitalAllocator:
    """Kelly-optimal position sizer + correlation/sector guard."""

    # 
    # Kelly Recommendation
    # 

    async def get_kelly_recommendation(
        self,
        symbol: str,
        action: str,
        confidence: float,
        entry_price: float,
        stop_loss: float,
        target_price: float,
    ) -> KellyResult:
        """Compute Kelly-optimal position sizing for a potential trade.

        Args:
            symbol:       Trading symbol.
            action:       "BUY" or "STRONG_BUY".
            confidence:   Signal confidence (0.0–1.0).
            entry_price:  Planned entry price (Rs.).
            stop_loss:    Stop-loss price (Rs.).
            target_price: Target price (Rs.).

        Returns:
            KellyResult with recommended quantity and value.
        """
        from src.utils.kelly import compute_half_kelly, compute_position_size

        # 1. Get calibrated win rate
        win_rate, note = await self._get_win_rate(confidence)

        # 2. Compute avg win/loss from trade parameters
        risk_per_share = abs(entry_price - stop_loss)
        reward_per_share = abs(target_price - entry_price)

        avg_win_pct = reward_per_share / entry_price if entry_price > 0 else 0.05
        avg_loss_pct = risk_per_share / entry_price if entry_price > 0 else 0.025

        # 3. Compute half-Kelly fraction
        kelly_fraction = compute_half_kelly(
            win_rate=win_rate,
            avg_win_pct=avg_win_pct,
            avg_loss_pct=avg_loss_pct,
            kelly_multiplier=settings.kelly_fraction,  # 0.5 = half-Kelly
            min_fraction=settings.kelly_min_position_pct / 100,
            max_fraction=settings.kelly_max_position_pct / 100,
        )

        # 4. Get portfolio value from latest snapshot
        portfolio_value = await self._get_portfolio_value()

        # 5. Compute quantity
        recommended_qty = compute_position_size(kelly_fraction, portfolio_value, entry_price)
        recommended_value = recommended_qty * entry_price
        max_risk = recommended_qty * risk_per_share

        return KellyResult(
            symbol=symbol,
            kelly_fraction=kelly_fraction,
            recommended_value_rs=recommended_value,
            recommended_qty=recommended_qty,
            max_risk_rs=max_risk,
            win_rate_used=win_rate,
            avg_win_pct_used=avg_win_pct,
            avg_loss_pct_used=avg_loss_pct,
            note=note,
        )

    # 
    # Correlation Guard
    # 

    async def check_correlation_guard(
        self,
        symbol: str,
        lookback_days: int = 30,
    ) -> CorrelationCheck:
        """Check if the symbol is highly correlated with any existing holding.

        Args:
            symbol:        Trading symbol to check.
            lookback_days: Days of daily price history to use.

        Returns:
            CorrelationCheck with blocked=True if Pearson correlation exceeds threshold.
        """
        if not settings.correlation_guard_enabled:
            return CorrelationCheck(symbol=symbol, blocked=False)

        try:
            from src.services.groww_service import groww_service
            from src.utils.correlation import pearson_correlation

            # Get current holdings
            holdings = await groww_service.get_holdings()
            if not holdings:
                return CorrelationCheck(symbol=symbol, blocked=False)

            holding_symbols = [h.trading_symbol for h in holdings if h.trading_symbol != symbol]
            if not holding_symbols:
                return CorrelationCheck(symbol=symbol, blocked=False)

            # Fetch price history for target symbol
            target_prices = await self._fetch_daily_closes(symbol, lookback_days)
            if len(target_prices) < 5:
                return CorrelationCheck(symbol=symbol, blocked=False)

            threshold = settings.correlation_threshold
            highest_corr: Optional[float] = None
            most_correlated_with: Optional[str] = None

            for holding_sym in holding_symbols:
                try:
                    holding_prices = await self._fetch_daily_closes(holding_sym, lookback_days)
                    if len(holding_prices) < 5:
                        continue
                    corr = pearson_correlation(target_prices, holding_prices)
                    if corr is None:
                        continue
                    if highest_corr is None or corr > highest_corr:
                        highest_corr = corr
                        most_correlated_with = holding_sym
                except Exception:
                    continue

            if highest_corr is not None and highest_corr >= threshold:
                return CorrelationCheck(
                    symbol=symbol,
                    blocked=True,
                    correlated_with=most_correlated_with,
                    correlation=highest_corr,
                    message=(
                        f"{symbol} has {highest_corr:.2f} Pearson correlation with "
                        f"{most_correlated_with}. Adding this increases concentration risk."
                    ),
                )

            return CorrelationCheck(
                symbol=symbol,
                blocked=False,
                correlated_with=most_correlated_with,
                correlation=highest_corr,
            )

        except Exception as e:
            logger.warning(f"CapitalAllocator.check_correlation_guard error: {e}")
            return CorrelationCheck(symbol=symbol, blocked=False)

    # 
    # Sector Concentration Check
    # 

    async def check_sector_limits(
        self,
        symbol: str,
        position_value: Optional[float] = None,
    ) -> SectorCheck:
        """Check if adding this stock would breach the sector concentration cap.

        Args:
            symbol:          Trading symbol.
            position_value:  Estimated new position value (Rs.). Uses Kelly default if None.

        Returns:
            SectorCheck with blocked=True if adding would exceed SECTOR_MAX_PCT.
        """
        if not settings.sector_cap_enabled:
            sector_map = _load_sector_map()
            return SectorCheck(
                symbol=symbol,
                sector=sector_map.get(symbol.upper()),
                blocked=False,
                current_sector_pct=0.0,
                after_sector_pct=0.0,
            )

        try:
            from src.services.database import db
            sector_map = _load_sector_map()
            target_sector = sector_map.get(symbol.upper(), "Unknown")

            # Get latest portfolio snapshot for sector weights
            snapshot = await db.get_latest_snapshot()
            if not snapshot:
                return SectorCheck(
                    symbol=symbol,
                    sector=target_sector,
                    blocked=False,
                    current_sector_pct=0.0,
                    after_sector_pct=0.0,
                )

            portfolio_value = snapshot.get("current_value", 1.0)
            if portfolio_value <= 0:
                portfolio_value = 1.0

            # Compute current sector weights from holdings
            holdings = snapshot.get("holdings", [])
            sector_values: dict[str, float] = {}
            for h in holdings:
                sym = h.get("trading_symbol", "")
                sector = sector_map.get(sym, "Unknown")
                current_val = h.get("current_value", 0.0) or 0.0
                sector_values[sector] = sector_values.get(sector, 0.0) + current_val

            current_sector_val = sector_values.get(target_sector, 0.0)
            current_sector_pct = (current_sector_val / portfolio_value) * 100

            # Estimate position value for new entry
            if position_value is None:
                position_value = portfolio_value * (settings.kelly_max_position_pct / 100 / 2)

            after_sector_val = current_sector_val + position_value
            after_sector_pct = (after_sector_val / portfolio_value) * 100

            blocked = after_sector_pct > settings.sector_max_pct

            return SectorCheck(
                symbol=symbol,
                sector=target_sector,
                blocked=blocked,
                current_sector_pct=current_sector_pct,
                after_sector_pct=after_sector_pct,
                message=(
                    f"{target_sector} sector would reach {after_sector_pct:.1f}% "
                    f"(limit: {settings.sector_max_pct}%). "
                    f"Currently: {current_sector_pct:.1f}%."
                )
                if blocked
                else None,
            )

        except Exception as e:
            logger.warning(f"CapitalAllocator.check_sector_limits error: {e}")
            sector_map = _load_sector_map()
            return SectorCheck(
                symbol=symbol,
                sector=sector_map.get(symbol.upper()),
                blocked=False,
                current_sector_pct=0.0,
                after_sector_pct=0.0,
            )

    # 
    # Portfolio Beta
    # 

    async def compute_portfolio_beta(self, lookback_days: int = 252) -> BetaReport:
        """Compute portfolio beta vs Nifty 50.

        Args:
            lookback_days: Trading days of history (default 252 = 1 year).

        Returns:
            BetaReport saved to MongoDB.
        """
        from src.services.database import db
        from src.utils.correlation import pearson_correlation

        try:
            from src.services.groww_service import groww_service
            holdings = await groww_service.get_holdings()
            snapshot = await db.get_latest_snapshot()

            if not holdings or not snapshot:
                return BetaReport(
                    lookback_days=lookback_days,
                    portfolio_beta=1.0,
                    holdings=[],
                    interpretation="Insufficient data",
                )

            portfolio_value = snapshot.get("current_value", 1.0)
            if portfolio_value <= 0:
                portfolio_value = 1.0

            # Fetch Nifty 50 reference prices
            nifty_prices = await self._fetch_daily_closes("NIFTY 50", lookback_days)

            beta_entries: list[BetaEntry] = []
            portfolio_beta = 0.0

            snapshot_holdings = {
                h.get("trading_symbol", ""): h
                for h in snapshot.get("holdings", [])
            }

            for holding in holdings:
                sym = holding.trading_symbol
                try:
                    stock_prices = await self._fetch_daily_closes(sym, lookback_days)
                    if len(stock_prices) < 10 or len(nifty_prices) < 10:
                        continue

                    # Beta = Cov(stock_returns, nifty_returns) / Var(nifty_returns)
                    n = min(len(stock_prices), len(nifty_prices))
                    stock_returns = [
                        (stock_prices[i] - stock_prices[i - 1]) / stock_prices[i - 1]
                        for i in range(1, n)
                        if stock_prices[i - 1] != 0
                    ]
                    nifty_returns = [
                        (nifty_prices[i] - nifty_prices[i - 1]) / nifty_prices[i - 1]
                        for i in range(1, n)
                        if nifty_prices[i - 1] != 0
                    ]

                    m = min(len(stock_returns), len(nifty_returns))
                    if m < 5:
                        continue

                    mean_s = sum(stock_returns[:m]) / m
                    mean_n = sum(nifty_returns[:m]) / m
                    cov = sum(
                        (stock_returns[i] - mean_s) * (nifty_returns[i] - mean_n)
                        for i in range(m)
                    )
                    var_n = sum((r - mean_n) ** 2 for r in nifty_returns[:m])
                    if var_n == 0:
                        continue
                    beta = cov / var_n

                    # Weight
                    h_snapshot = snapshot_holdings.get(sym, {})
                    holding_value = h_snapshot.get("current_value", 0.0) or 0.0
                    weight = holding_value / portfolio_value

                    beta_entries.append(BetaEntry(symbol=sym, beta=beta, weight=weight))
                    portfolio_beta += beta * weight

                except Exception as e:
                    logger.debug(f"Beta calc skipped for {sym}: {e}")
                    continue

            if portfolio_beta > 1.2:
                interpretation = f"Aggressive (β={portfolio_beta:.2f} > 1.2) — high market sensitivity"
            elif portfolio_beta < 0.8:
                interpretation = f"Defensive (β={portfolio_beta:.2f} < 0.8) — low market sensitivity"
            else:
                interpretation = f"Market-like (β={portfolio_beta:.2f}) — tracking Nifty 50 closely"

            report = BetaReport(
                lookback_days=lookback_days,
                portfolio_beta=portfolio_beta,
                holdings=beta_entries,
                interpretation=interpretation,
            )

            # Save to MongoDB
            await db.portfolio_beta.insert_one(report.model_dump(mode="python"))
            logger.info(f"CapitalAllocator: Portfolio beta = {portfolio_beta:.2f} ({interpretation})")
            return report

        except Exception as e:
            logger.error(f"CapitalAllocator.compute_portfolio_beta error: {e}", exc_info=True)
            return BetaReport(
                lookback_days=lookback_days,
                portfolio_beta=1.0,
                holdings=[],
                interpretation="Calculation failed — defaulting to market-like",
            )

    # 
    # Full Allocation Report
    # 

    async def get_full_allocation_report(self) -> AllocationReport:
        """Build a complete portfolio allocation report.

        Returns:
            AllocationReport with beta, sector weights, correlation pairs.
        """
        from src.services.database import db
        from src.utils.correlation import build_correlation_matrix, find_high_correlation_pairs

        try:
            from src.services.groww_service import groww_service
            holdings = await groww_service.get_holdings()
            snapshot = await db.get_latest_snapshot()

            portfolio_value = 0.0
            sector_weights: dict[str, float] = {}
            high_correlation_pairs: list[dict] = []
            concentrated_sectors: list[str] = []
            sector_map = _load_sector_map()

            if snapshot:
                portfolio_value = snapshot.get("current_value", 0.0)
                snapshot_holdings = snapshot.get("holdings", [])
                sector_values: dict[str, float] = {}
                for h in snapshot_holdings:
                    sym = h.get("trading_symbol", "")
                    sector = sector_map.get(sym, "Unknown")
                    val = h.get("current_value", 0.0) or 0.0
                    sector_values[sector] = sector_values.get(sector, 0.0) + val

                if portfolio_value > 0:
                    sector_weights = {
                        sector: val / portfolio_value
                        for sector, val in sector_values.items()
                    }
                    concentrated_sectors = [
                        s for s, w in sector_weights.items()
                        if w * 100 >= settings.sector_max_pct
                    ]

            # Get latest beta from DB
            latest_beta_doc = await db.portfolio_beta.find_one(sort=[("computed_at", -1)])
            portfolio_beta: Optional[float] = None
            if latest_beta_doc:
                portfolio_beta = latest_beta_doc.get("portfolio_beta")

            # Get correlation pairs (fetch 30-day prices for all holdings)
            if len(holdings) >= 2:
                try:
                    symbols = [h.trading_symbol for h in holdings[:15]]  # Cap at 15 for speed
                    prices: dict[str, list[float]] = {}
                    for sym in symbols:
                        closes = await self._fetch_daily_closes(sym, 30)
                        if len(closes) >= 5:
                            prices[sym] = closes
                    if len(prices) >= 2:
                        matrix = build_correlation_matrix(prices)
                        high_correlation_pairs = find_high_correlation_pairs(
                            matrix, threshold=settings.correlation_threshold
                        )

                        # Save matrix to DB
                        await db.portfolio_correlation.insert_one({
                            "computed_at": _utcnow(),
                            "lookback_days": 30,
                            "symbols": list(prices.keys()),
                            "high_pairs": high_correlation_pairs,
                        })
                except Exception as e:
                    logger.debug(f"Correlation matrix skipped: {e}")

            return AllocationReport(
                portfolio_value=portfolio_value,
                portfolio_beta=portfolio_beta,
                sector_weights=sector_weights,
                concentrated_sectors=concentrated_sectors,
                high_correlation_pairs=high_correlation_pairs,
                total_holdings=len(holdings),
            )

        except Exception as e:
            logger.error(f"CapitalAllocator.get_full_allocation_report error: {e}", exc_info=True)
            return AllocationReport(
                portfolio_value=0.0,
                sector_weights={},
                concentrated_sectors=[],
                high_correlation_pairs=[],
                total_holdings=0,
            )

    # 
    # Helpers
    # 

    async def _get_win_rate(self, confidence: float) -> tuple[float, Optional[str]]:
        """Look up calibrated win rate for a given confidence level.

        Returns:
            (win_rate, note_str) — note is set when default/fallback is used.
        """
        try:
            from src.services.signal_calibrator import signal_calibrator
            result = await signal_calibrator.get_calibration_for_tool(
                confidence_level=confidence
            )
            empirical = result.get("empirical_win_rate")
            if empirical is not None:
                return float(empirical), None
        except Exception:
            pass

        # Fallback: use the confidence score itself as a rough win rate estimate
        return confidence * 0.85, "Default win rate (confidence × 0.85) — insufficient calibration data"

    async def _get_portfolio_value(self) -> float:
        """Get the latest portfolio value from DB, fallback to 500_000 Rs."""
        try:
            from src.services.database import db
            snapshot = await db.get_latest_snapshot()
            if snapshot:
                return float(snapshot.get("current_value", 500_000))
        except Exception:
            pass
        return 500_000.0

    async def _fetch_daily_closes(self, symbol: str, days: int) -> list[float]:
        """Fetch daily closing prices for a symbol."""
        from src.services.groww_service import groww_service

        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Fetch extra days to ensure we have enough after weekends/holidays
        start_time = (datetime.now() - timedelta(days=days + 30)).strftime("%Y-%m-%d %H:%M:%S")

        candles = await groww_service.get_historical_candles(
            trading_symbol=symbol,
            exchange="NSE",
            segment="CASH",
            start_time=start_time,
            end_time=end_time,
            interval_minutes=1440,
        )
        # Take the last `days` closes
        closes = [float(c.close) for c in candles if c.close]
        return closes[-days:] if len(closes) > days else closes


# ─── Singleton ────────────────────────────────────────────────────────────────
capital_allocator = CapitalAllocator()
