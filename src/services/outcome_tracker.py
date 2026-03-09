"""Signal outcome tracking service for validating AI prediction accuracy.

This service tracks the lifecycle of trade signals from generation through entry
and exit, computing actual P&L and win/loss rates to validate AI confidence scores.
"""

import logging
from datetime import datetime
from typing import Any, Optional

from src.config import settings
from src.models.analysis import ActionType, TradeSignal
from src.models.outcome import SignalOutcome, SignalStatistics
from src.services.database import db
from src.services.groww_service import groww_service

logger = logging.getLogger(__name__)


class OutcomeTracker:
    """Tracks signal outcomes from entry to exit for win rate calculation."""

    async def track_new_signal(
        self,
        signal_id: str,
        signal: TradeSignal,
        entry_price: Optional[float] = None,
    ) -> str:
        """Create a new outcome record when a signal is generated.

        Args:
            signal_id: MongoDB _id of the trade_signals document
            signal: The TradeSignal model instance
            entry_price: Optional actual entry price (defaults to signal price)

        Returns:
            outcome_id: MongoDB _id of the created outcome record
        """
        # Only track signals above minimum confidence threshold
        if signal.confidence < settings.outcome_min_confidence_track:
            logger.debug(
                f"Signal {signal.trading_symbol} confidence {signal.confidence:.2f} "
                f"below threshold {settings.outcome_min_confidence_track} - not tracking"
            )
            return ""

        # Create outcome record
        outcome = SignalOutcome(
            signal_id=signal_id,
            trading_symbol=signal.trading_symbol,
            action=signal.action,
            signal_timestamp=signal.timestamp,
            entry_price=entry_price or signal.current_price,
            entry_timestamp=datetime.now(),
            entry_method="AUTO_TRACKED" if entry_price else "ESTIMATED",
            original_confidence=signal.confidence,
            original_target=signal.target_price,
            original_stop_loss=signal.stop_loss,
            status="OPEN",
        )

        outcome_id = await db.save_signal_outcome(outcome.model_dump())
        logger.info(
            f"Tracking outcome for {signal.trading_symbol} {signal.action.value} "
            f"signal (confidence: {signal.confidence:.2f}, outcome_id: {outcome_id})"
        )

        return outcome_id

    async def update_entry(
        self,
        outcome_id: str,
        entry_price: float,
        entry_method: str = "MANUAL",
    ) -> None:
        """Update entry information for an outcome.

        Args:
            outcome_id: MongoDB _id of the outcome record
            entry_price: Actual entry price
            entry_method: Entry method (MANUAL | AUTO_TRACKED | ESTIMATED)
        """
        update_data = {
            "entry_price": entry_price,
            "entry_method": entry_method,
            "entry_timestamp": datetime.now(),
        }

        await db.update_signal_outcome(outcome_id, update_data)
        logger.info(f"Updated entry for outcome {outcome_id}: {entry_price} ({entry_method})")

    async def update_exit(
        self,
        outcome_id: str,
        exit_price: float,
        exit_reason: str = "MANUAL",
    ) -> None:
        """Update exit information and compute final P&L metrics.

        Args:
            outcome_id: MongoDB _id of the outcome record
            exit_price: Actual exit price
            exit_reason: Exit reason (TARGET_HIT | STOP_LOSS | TIMEOUT | MANUAL)
        """
        # Fetch the outcome to compute metrics
        outcome_doc = await db.signal_outcomes.find_one({"_id": outcome_id})
        if not outcome_doc:
            logger.warning(f"Outcome {outcome_id} not found for exit update")
            return

        # Convert to model and compute metrics
        outcome = SignalOutcome(**outcome_doc)
        outcome.exit_price = exit_price
        outcome.exit_timestamp = datetime.now()
        outcome.exit_reason = exit_reason
        outcome.compute_metrics()  # Calculates P&L, win/loss, duration

        # Update in database
        update_data = {
            "exit_price": outcome.exit_price,
            "exit_timestamp": outcome.exit_timestamp,
            "exit_reason": outcome.exit_reason,
            "status": outcome.status,
            "pnl_points": outcome.pnl_points,
            "pnl_pct": outcome.pnl_pct,
            "win_loss": outcome.win_loss,
            "hold_duration_hours": outcome.hold_duration_hours,
            "target_achieved": outcome.target_achieved,
            "stop_loss_hit": outcome.stop_loss_hit,
        }

        await db.update_signal_outcome(outcome_id, update_data)
        logger.info(
            f"Updated exit for outcome {outcome_id}: {exit_price} "
            f"(P&L: {outcome.pnl_pct:.2f}%, {outcome.win_loss})"
        )

    async def auto_track_from_holdings(self) -> dict[str, int]:
        """Auto-detect position exits by comparing open outcomes with current holdings.

        This method checks all OPEN outcomes and verifies if the positions still exist
        in the user's holdings. If a position is no longer held, it attempts to
        determine the exit price and updates the outcome accordingly.

        Returns:
            dict with counts: {closed: int, still_open: int, errors: int}
        """
        if not settings.outcome_auto_track_enabled:
            logger.debug("Auto-tracking disabled")
            return {"closed": 0, "still_open": 0, "errors": 0}

        logger.info("Running auto-tracking job to detect position exits")

        # Fetch all OPEN outcomes
        open_outcomes = await db.get_outcomes_by_status("OPEN")
        if not open_outcomes:
            logger.info("No open outcomes to track")
            return {"closed": 0, "still_open": 0, "errors": 0}

        # Fetch current holdings
        try:
            holdings = await groww_service.get_holdings()
            held_symbols = {h.trading_symbol for h in holdings}
        except Exception as e:
            logger.error(f"Failed to fetch holdings for auto-tracking: {e}")
            return {"closed": 0, "still_open": len(open_outcomes), "errors": 1}

        closed_count = 0
        still_open_count = 0
        error_count = 0

        for outcome_doc in open_outcomes:
            symbol = outcome_doc["trading_symbol"]

            # If position still held, skip
            if symbol in held_symbols:
                still_open_count += 1
                continue

            # Position exited — try to determine exit price
            try:
                # Get latest price as approximate exit price
                ltp = await groww_service.get_ltp(symbol)
                if ltp is None:
                    logger.warning(f"Could not fetch LTP for {symbol} - skipping")
                    error_count += 1
                    continue

                # Update outcome with exit
                await self.update_exit(
                    outcome_id=str(outcome_doc["_id"]),
                    exit_price=ltp,
                    exit_reason="AUTO_DETECTED",
                )
                closed_count += 1

            except Exception as e:
                logger.error(f"Error auto-tracking {symbol}: {e}")
                error_count += 1

        logger.info(
            f"Auto-tracking complete: {closed_count} closed, "
            f"{still_open_count} still open, {error_count} errors"
        )

        return {
            "closed": closed_count,
            "still_open": still_open_count,
            "errors": error_count,
        }

    async def get_signal_statistics(self, days: int = 30) -> Optional[SignalStatistics]:
        """Get aggregated signal performance statistics.

        Args:
            days: Number of days to include in statistics (default: 30)

        Returns:
            SignalStatistics model or None if no data
        """
        stats_doc = await db.get_signal_statistics(days)
        if not stats_doc:
            logger.info(f"No signal statistics available for last {days} days")
            return None

        # Compute confidence correlation
        # This requires fetching closed outcomes to correlate confidence with win/loss
        closed_outcomes = await db.get_outcomes_by_status("CLOSED")

        wins = [o for o in closed_outcomes if o.get("win_loss") == "WIN"]
        losses = [o for o in closed_outcomes if o.get("win_loss") == "LOSS"]

        avg_confidence_wins = (
            sum(o["original_confidence"] for o in wins) / len(wins) if wins else 0.0
        )
        avg_confidence_losses = (
            sum(o["original_confidence"] for o in losses) / len(losses) if losses else 0.0
        )

        # Simple correlation: positive if avg win confidence > avg loss confidence
        confidence_correlation = avg_confidence_wins - avg_confidence_losses

        # Build statistics model
        statistics = SignalStatistics(
            period_days=days,
            total_signals=stats_doc["total_signals"],
            open_signals=stats_doc["open_signals"],
            closed_signals=stats_doc["closed_signals"],
            wins=stats_doc["wins"],
            losses=stats_doc["losses"],
            breakevens=stats_doc["breakevens"],
            win_rate=stats_doc["win_rate"],
            avg_pnl_pct=stats_doc["avg_pnl_pct"],
            total_pnl_pct=stats_doc.get("total_pnl_pct", 0.0),
            max_win_pct=stats_doc["max_win_pct"],
            max_loss_pct=stats_doc["max_loss_pct"],
            avg_confidence_wins=avg_confidence_wins,
            avg_confidence_losses=avg_confidence_losses,
            confidence_correlation=confidence_correlation,
            target_hit_rate=stats_doc.get("target_hit_rate"),
            stop_loss_hit_rate=stats_doc.get("stop_loss_hit_rate"),
            avg_hold_hours=stats_doc.get("avg_hold_hours"),
        )

        return statistics

    async def manual_close_outcome(
        self,
        outcome_id: str,
        exit_price: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> None:
        """Manually close an outcome (for user-initiated exits).

        Args:
            outcome_id: MongoDB _id of the outcome
            exit_price: Exit price (fetches current LTP if not provided)
            notes: Optional notes about the manual closure
        """
        outcome_doc = await db.signal_outcomes.find_one({"_id": outcome_id})
        if not outcome_doc:
            logger.warning(f"Outcome {outcome_id} not found")
            return

        # Get exit price
        if exit_price is None:
            symbol = outcome_doc["trading_symbol"]
            exit_price = await groww_service.get_ltp(symbol)
            if exit_price is None:
                logger.error(f"Could not fetch LTP for {symbol} - cannot close outcome")
                return

        # Update exit
        await self.update_exit(outcome_id, exit_price, exit_reason="MANUAL")

        # Add notes if provided
        if notes:
            await db.update_signal_outcome(outcome_id, {"notes": notes})

        logger.info(f"Manually closed outcome {outcome_id}")


# Global singleton
outcome_tracker = OutcomeTracker()
