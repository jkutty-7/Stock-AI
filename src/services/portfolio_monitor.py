"""Portfolio monitoring orchestrator.

This is the main workflow engine that runs every 15 minutes during market hours.
It fetches holdings, enriches them with live prices, computes P&L, runs AI
analysis, and sends alerts via Telegram.
"""

import logging
from datetime import datetime

from src.config import settings
from src.models.analysis import ActionType, AlertMessage, AnalysisResult
from src.models.holdings import EnrichedHolding, Holding, PortfolioSnapshot, Position
from src.services.ai_engine import ai_engine
from src.services.database import db
from src.services.drawdown_breaker import drawdown_breaker
from src.services.groww_service import groww_service
from src.services.outcome_tracker import outcome_tracker
from src.services.regime_classifier import regime_classifier
from src.services.telegram_bot import telegram_service

logger = logging.getLogger(__name__)


class PortfolioMonitor:
    """Orchestrates the full monitoring cycle."""

    async def run_monitoring_cycle(self) -> None:
        """Main 15-minute monitoring cycle.

        Flow: fetch holdings -> get prices -> enrich -> snapshot ->
              threshold alerts -> AI analysis -> send alerts
        """
        logger.info("Starting monitoring cycle")

        try:
            # Step 1: Fetch current holdings
            holdings = await groww_service.get_holdings()
            if not holdings:
                logger.warning("No holdings found — skipping monitoring cycle")
                return

            # Step 2: Fetch live prices for all holdings
            symbols = [h.trading_symbol for h in holdings]
            prices = await groww_service.get_bulk_ltp(symbols)
            ohlc = await groww_service.get_bulk_ohlc(symbols)

            # Step 3: Enrich holdings with P&L calculations
            enriched = self._enrich_holdings(holdings, prices, ohlc)

            # Step 4: Build and save portfolio snapshot
            snapshot = self._build_snapshot(enriched)
            await db.save_snapshot(snapshot)

            # Step 4a: Update peak & check drawdown breaker (Feature 3)
            await drawdown_breaker.update_peak(snapshot.current_value, snapshot.total_invested)
            drawdown_status = await drawdown_breaker.check_drawdown(snapshot.current_value)

            # Step 4b: Load current market regime (Feature 4)
            current_regime = await regime_classifier.get_current_regime()

            # Step 5: Check threshold-based alerts
            alerts = self._check_thresholds(enriched, snapshot)

            # Step 6: Run AI alert check (with drawdown status for Feature 3)
            try:
                analysis = await ai_engine.check_alerts(
                    snapshot.model_dump(mode="json"),
                    drawdown_status=drawdown_status,
                    regime=current_regime
                )
                await db.save_analysis(analysis)

                # Step 7: Generate alerts for high-confidence AI signals
                for signal in analysis.signals:
                    # Base threshold
                    min_confidence = 0.7

                    # Feature 4: Adjust threshold based on market regime
                    if current_regime and settings.regime_classification_enabled:
                        regime_min_conf = current_regime.get("suggested_min_confidence", 0.7)
                        min_confidence = max(min_confidence, regime_min_conf)

                    if signal.confidence >= min_confidence:
                        # Feature 3: Block BUY signals if drawdown breaker is triggered
                        if signal.action in [ActionType.BUY, ActionType.STRONG_BUY]:
                            if drawdown_status["breaker_triggered"]:
                                logger.warning(
                                    f"Drawdown breaker BLOCKED BUY signal for {signal.trading_symbol} "
                                    f"(confidence: {signal.confidence:.2f}, drawdown: {drawdown_status['drawdown_pct']:.2f}%)"
                                )
                                continue  # Skip this signal
                    else:
                        # Signal filtered by regime threshold
                        if current_regime:
                            logger.info(
                                f"Regime filter BLOCKED {signal.action.value} signal for {signal.trading_symbol} "
                                f"(confidence: {signal.confidence:.2f}, regime min: {min_confidence:.2f}, "
                                f"regime: {current_regime.get('regime', 'UNKNOWN')})"
                            )
                        continue  # Skip low-confidence signal

                        alert = AlertMessage(
                            timestamp=datetime.now(),
                            alert_type="AI_SIGNAL",
                            severity="CRITICAL" if signal.confidence >= 0.85 else "WARNING",
                            title=f"{signal.action.value}: {signal.trading_symbol}",
                            body=signal.reasoning[:500],
                            trading_symbol=signal.trading_symbol,
                            signal=signal,
                        )
                        alerts.append(alert)
                        signal_id = await db.save_signal(signal.model_dump(mode="json"))

                        # Track outcome for signal validation (Feature 1)
                        try:
                            await outcome_tracker.track_new_signal(
                                signal_id=signal_id,
                                signal=signal,
                                entry_price=signal.current_price,
                            )
                        except Exception as e:
                            logger.warning(f"Failed to track outcome for signal {signal_id}: {e}")

            except Exception as e:
                logger.error(f"AI analysis failed (non-fatal): {e}")
                # Continue — AI failure should not stop the monitoring cycle

            # Step 8: Send all alerts via Telegram
            for alert in alerts:
                try:
                    await telegram_service.send_alert(alert)
                    await db.save_alert(alert)
                except Exception as e:
                    logger.error(f"Failed to send alert '{alert.title}': {e}")

            logger.info(
                f"Monitoring cycle complete. Holdings: {len(holdings)}, "
                f"Alerts: {len(alerts)}, P&L: {snapshot.total_pnl_pct:.2f}%"
            )

        except Exception as e:
            logger.error(f"Monitoring cycle failed: {e}", exc_info=True)
            try:
                await telegram_service.send_error_notification(str(e))
            except Exception:
                logger.error("Failed to send error notification via Telegram")

    async def run_full_analysis(self) -> AnalysisResult:
        """Run comprehensive AI portfolio analysis (called daily or on-demand).

        Returns the complete analysis result.
        """
        logger.info("Running full portfolio analysis")

        # Fetch and enrich holdings
        holdings = await groww_service.get_holdings()
        symbols = [h.trading_symbol for h in holdings]
        prices = await groww_service.get_bulk_ltp(symbols)
        ohlc = await groww_service.get_bulk_ohlc(symbols)
        enriched = self._enrich_holdings(holdings, prices, ohlc)
        snapshot = self._build_snapshot(enriched)

        # Build micro-signal context for Claude (Phase 2)
        try:
            from src.services.micro_monitor import micro_monitor
            symbols_for_micro = [h.trading_symbol for h in enriched]
            micro_context = micro_monitor.get_all_context(symbols_for_micro)
        except Exception:
            micro_context = ""

        # Build context for AI
        context = {
            "total_invested": snapshot.total_invested,
            "current_value": snapshot.current_value,
            "total_pnl": snapshot.total_pnl,
            "total_pnl_pct": snapshot.total_pnl_pct,
            "day_pnl": snapshot.day_pnl,
            "micro_context": micro_context,
            "holdings_summary": [
                {
                    "symbol": h.trading_symbol,
                    "qty": h.quantity,
                    "avg_price": h.average_price,
                    "current_price": h.current_price,
                    "pnl_pct": h.pnl_pct,
                    "day_change_pct": h.day_change_pct,
                }
                for h in enriched
            ],
        }

        analysis = await ai_engine.analyze_portfolio(context)
        await db.save_analysis(analysis)
        await db.save_snapshot(snapshot)

        return analysis

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------

    def _enrich_holdings(
        self,
        holdings: list[Holding],
        prices: dict[str, float],
        ohlc: dict[str, dict],
    ) -> list[EnrichedHolding]:
        """Merge holdings with live price data to compute P&L."""
        enriched = []
        for h in holdings:
            # Bug fix #6: use helper that tries NSE_ then BSE_ prefix
            current_price = groww_service.find_price(prices, h.trading_symbol)
            ohlc_data = groww_service.find_ohlc(ohlc, h.trading_symbol)
            # Bug fix #4: proper fallback chain for prev_close
            prev_close = float(
                ohlc_data.get("close")
                or ohlc_data.get("previous_close")
                or current_price
                or 0
            )

            total_invested = h.quantity * h.average_price
            current_value = h.quantity * current_price
            pnl = current_value - total_invested
            pnl_pct = (pnl / total_invested * 100) if total_invested > 0 else 0
            day_change_pct = (
                ((current_price - prev_close) / prev_close * 100)
                if prev_close > 0
                else 0
            )
            day_pnl = h.quantity * (current_price - prev_close)

            enriched.append(
                EnrichedHolding(
                    isin=h.isin,
                    trading_symbol=h.trading_symbol,
                    quantity=h.quantity,
                    average_price=h.average_price,
                    current_price=current_price,
                    day_change_pct=round(day_change_pct, 2),
                    total_invested=round(total_invested, 2),
                    current_value=round(current_value, 2),
                    pnl=round(pnl, 2),
                    pnl_pct=round(pnl_pct, 2),
                    day_pnl=round(day_pnl, 2),
                )
            )
        return enriched

    def _build_snapshot(self, enriched: list[EnrichedHolding]) -> PortfolioSnapshot:
        """Build a complete portfolio snapshot from enriched holdings."""
        total_invested = sum(h.total_invested for h in enriched)
        current_value = sum(h.current_value for h in enriched)
        total_pnl = current_value - total_invested
        total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0
        day_pnl = sum(h.day_pnl for h in enriched)

        return PortfolioSnapshot(
            timestamp=datetime.now(),
            total_invested=round(total_invested, 2),
            current_value=round(current_value, 2),
            total_pnl=round(total_pnl, 2),
            total_pnl_pct=round(total_pnl_pct, 2),
            day_pnl=round(day_pnl, 2),
            holdings=enriched,
        )

    def _check_thresholds(
        self,
        enriched: list[EnrichedHolding],
        snapshot: PortfolioSnapshot,
    ) -> list[AlertMessage]:
        """Generate alerts based on configurable P&L thresholds."""
        alerts: list[AlertMessage] = []

        # Per-stock threshold alerts
        for h in enriched:
            if abs(h.day_change_pct) >= settings.pnl_alert_threshold_pct:
                direction = "up" if h.day_change_pct > 0 else "down"
                alerts.append(
                    AlertMessage(
                        timestamp=datetime.now(),
                        alert_type="PNL_THRESHOLD",
                        severity="WARNING",
                        title=f"{h.trading_symbol} {direction} {abs(h.day_change_pct):.1f}% today",
                        body=(
                            f"Current: INR {h.current_price:,.2f}\n"
                            f"Day P&L: INR {h.day_pnl:,.2f}\n"
                            f"Total P&L: {h.pnl_pct:.1f}%"
                        ),
                        trading_symbol=h.trading_symbol,
                    )
                )

        # Portfolio-level threshold alert
        if abs(snapshot.total_pnl_pct) >= settings.portfolio_alert_threshold_pct:
            direction = "up" if snapshot.total_pnl_pct > 0 else "down"
            alerts.append(
                AlertMessage(
                    timestamp=datetime.now(),
                    alert_type="PNL_THRESHOLD",
                    severity="WARNING",
                    title=f"Portfolio {direction} {abs(snapshot.total_pnl_pct):.1f}% overall",
                    body=(
                        f"Invested: INR {snapshot.total_invested:,.0f}\n"
                        f"Current: INR {snapshot.current_value:,.0f}\n"
                        f"Day P&L: INR {snapshot.day_pnl:,.0f}"
                    ),
                )
            )

        return alerts


# Singleton
portfolio_monitor = PortfolioMonitor()
