"""Portfolio drawdown circuit breaker for capital protection.

This service tracks the portfolio peak value and triggers a circuit breaker
when drawdown exceeds a threshold (default 8%), automatically blocking all
BUY signals until the portfolio recovers.
"""

import logging
from datetime import datetime
from typing import Any, Optional

from src.config import settings
from src.services.database import db

logger = logging.getLogger(__name__)


class DrawdownBreaker:
    """Circuit breaker that blocks BUY signals during severe portfolio drawdowns."""

    async def update_peak(
        self,
        portfolio_value: float,
        total_invested: float,
    ) -> bool:
        """Update portfolio peak if current value exceeds stored peak.

        Args:
            portfolio_value: Current portfolio value
            total_invested: Total capital invested

        Returns:
            True if peak was updated, False otherwise
        """
        if not settings.drawdown_breaker_enabled:
            return False

        if portfolio_value <= 0:
            logger.warning("Invalid portfolio value for peak update: {portfolio_value}")
            return False

        # Fetch current peak
        current_peak_doc = await db.portfolio_peaks.find_one({"is_current_peak": True})
        current_peak = current_peak_doc["portfolio_value"] if current_peak_doc else 0.0

        # Update if new peak
        if portfolio_value > current_peak:
            # Clear old peak flag
            if current_peak_doc:
                await db.portfolio_peaks.update_one(
                    {"_id": current_peak_doc["_id"]},
                    {"$set": {"is_current_peak": False}}
                )

            # Insert new peak
            await db.portfolio_peaks.insert_one({
                "timestamp": datetime.now(),
                "portfolio_value": portfolio_value,
                "total_invested": total_invested,
                "is_current_peak": True,
            })

            logger.info(f"New portfolio peak: ₹{portfolio_value:,.2f} (was ₹{current_peak:,.2f})")
            return True

        return False

    async def check_drawdown(self, current_value: float) -> dict[str, Any]:
        """Check current drawdown and trigger circuit breaker if threshold exceeded.

        Args:
            current_value: Current portfolio value

        Returns:
            Dict with: {
                "in_drawdown": bool,
                "drawdown_pct": float,
                "breaker_triggered": bool,
                "peak_value": float,
            }
        """
        if not settings.drawdown_breaker_enabled:
            return {
                "in_drawdown": False,
                "drawdown_pct": 0.0,
                "breaker_triggered": False,
                "peak_value": current_value,
            }

        # Get current peak
        peak_doc = await db.portfolio_peaks.find_one({"is_current_peak": True})
        if not peak_doc:
            # No peak yet — initialize with current value
            await db.portfolio_peaks.insert_one({
                "timestamp": datetime.now(),
                "portfolio_value": current_value,
                "is_current_peak": True,
            })
            return {
                "in_drawdown": False,
                "drawdown_pct": 0.0,
                "breaker_triggered": False,
                "peak_value": current_value,
            }

        peak_value = peak_doc["portfolio_value"]

        # Calculate drawdown
        drawdown_pct = ((peak_value - current_value) / peak_value) * 100 if peak_value > 0 else 0.0

        # Check if threshold exceeded
        threshold = settings.drawdown_breaker_threshold_pct
        breaker_should_trigger = drawdown_pct >= threshold

        # Get current breaker state
        breaker_state = await db.circuit_breaker_state.find_one({"_id": "drawdown_breaker"})
        is_triggered = breaker_state and breaker_state.get("triggered", False)

        # Trigger if not already triggered
        if breaker_should_trigger and not is_triggered:
            await self._trigger_breaker(peak_value, current_value, drawdown_pct)
            is_triggered = True

        # Auto-reset if enabled and drawdown recovered
        elif is_triggered and settings.drawdown_breaker_auto_reset:
            if drawdown_pct < threshold * 0.5:  # Reset at 50% recovery (e.g., 4% if threshold is 8%)
                await self.manual_reset()
                is_triggered = False

        return {
            "in_drawdown": drawdown_pct > 0.5,  # Consider >0.5% a drawdown
            "drawdown_pct": drawdown_pct,
            "breaker_triggered": is_triggered,
            "peak_value": peak_value,
        }

    async def is_triggered(self) -> bool:
        """Check if circuit breaker is currently triggered.

        Returns:
            True if breaker is active (BUY signals should be blocked)
        """
        if not settings.drawdown_breaker_enabled:
            return False

        breaker_state = await db.circuit_breaker_state.find_one({"_id": "drawdown_breaker"})
        return breaker_state and breaker_state.get("triggered", False)

    async def _trigger_breaker(
        self,
        peak_value: float,
        current_value: float,
        drawdown_pct: float,
    ) -> None:
        """Trigger the circuit breaker and send critical alert.

        Args:
            peak_value: Portfolio value at peak
            current_value: Current portfolio value
            drawdown_pct: Drawdown percentage
        """
        from src.services.telegram_bot import telegram_service

        # Save breaker state
        await db.circuit_breaker_state.update_one(
            {"_id": "drawdown_breaker"},
            {
                "$set": {
                    "triggered": True,
                    "trigger_timestamp": datetime.now(),
                    "trigger_drawdown_pct": drawdown_pct,
                    "peak_value_at_trigger": peak_value,
                    "trigger_portfolio_value": current_value,
                }
            },
            upsert=True,
        )

        # Send critical alert
        message = (
            f"<b>CIRCUIT BREAKER TRIGGERED</b>\n\n"
            f"Portfolio drawdown exceeded {settings.drawdown_breaker_threshold_pct:.1f}% threshold.\n\n"
            f"Peak Value: ₹{peak_value:,.2f}\n"
            f"Current Value: ₹{current_value:,.2f}\n"
            f"Drawdown: {drawdown_pct:.2f}%\n\n"
            f"ALL BUY SIGNALS ARE NOW BLOCKED.\n"
            f"Focus on capital preservation and risk reduction.\n\n"
            f"Use /reset_breaker to manually override (not recommended)."
        )

        try:
            await telegram_service.send_message(message, parse_mode="HTML")
            logger.critical(
                f"DRAWDOWN BREAKER TRIGGERED: {drawdown_pct:.2f}% drawdown "
                f"(peak: ₹{peak_value:,.2f}, current: ₹{current_value:,.2f})"
            )
        except Exception as e:
            logger.error(f"Failed to send drawdown breaker alert: {e}")

    async def manual_reset(self) -> dict[str, Any]:
        """Manually reset the circuit breaker.

        Returns:
            Dict with reset status and previous state info
        """
        breaker_state = await db.circuit_breaker_state.find_one({"_id": "drawdown_breaker"})

        if not breaker_state or not breaker_state.get("triggered"):
            return {"success": False, "message": "Circuit breaker was not triggered"}

        # Reset breaker
        await db.circuit_breaker_state.update_one(
            {"_id": "drawdown_breaker"},
            {
                "$set": {
                    "triggered": False,
                    "reset_timestamp": datetime.now(),
                    "last_trigger_timestamp": breaker_state.get("trigger_timestamp"),
                    "last_trigger_drawdown_pct": breaker_state.get("trigger_drawdown_pct"),
                }
            },
        )

        logger.warning("Circuit breaker manually reset")

        return {
            "success": True,
            "message": "Circuit breaker reset successfully",
            "previous_drawdown_pct": breaker_state.get("trigger_drawdown_pct", 0.0),
            "previous_trigger_time": breaker_state.get("trigger_timestamp"),
        }

    async def get_status(self) -> dict[str, Any]:
        """Get current circuit breaker status for display.

        Returns:
            Dict with triggered state, current drawdown, peak value, etc.
        """
        if not settings.drawdown_breaker_enabled:
            return {"enabled": False, "triggered": False}

        breaker_state = await db.circuit_breaker_state.find_one({"_id": "drawdown_breaker"})
        peak_doc = await db.portfolio_peaks.find_one({"is_current_peak": True})

        return {
            "enabled": True,
            "triggered": breaker_state.get("triggered", False) if breaker_state else False,
            "trigger_timestamp": breaker_state.get("trigger_timestamp") if breaker_state else None,
            "trigger_drawdown_pct": breaker_state.get("trigger_drawdown_pct", 0.0) if breaker_state else 0.0,
            "peak_value": peak_doc.get("portfolio_value", 0.0) if peak_doc else 0.0,
            "threshold_pct": settings.drawdown_breaker_threshold_pct,
            "auto_reset_enabled": settings.drawdown_breaker_auto_reset,
        }


# Global singleton
drawdown_breaker = DrawdownBreaker()
