"""MicroMonitor — 10-second price polling engine for fast signal detection.

This module runs an async infinite loop during market hours, fetching bulk LTP
every 10 seconds for all holdings and generating lightweight signals WITHOUT
calling Claude (to avoid unnecessary API costs).

Key concepts:
- RingBuffer: stores last 90 ticks per symbol (= 15 minutes of history)
- velocity_pct: % change from last tick
- momentum_1m: cumulative % change over last 6 ticks (1 minute)
- Alert conditions (no Claude):
    1. |velocity| > MICRO_VELOCITY_THRESHOLD_PCT (default 0.5%)
    2. consecutive same-direction ticks >= MICRO_CONSECUTIVE_TICKS (default 3)
    3. volume > 2x 5-tick avg
- Accumulated tick data is fed to Claude's 15-min analysis as context

Phase 2 of V2 upgrade plan.
"""

import asyncio
import logging
from collections import deque
from datetime import datetime
from typing import Any

from src.config import settings
from src.models.market import MicroSignal
from src.utils.market_hours import is_market_open

logger = logging.getLogger(__name__)

_RING_SIZE = 90  # 90 ticks × 10s = 15 minutes of history


class _SymbolBuffer:
    """Per-symbol ring buffer of price ticks."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._prices: deque[float] = deque(maxlen=_RING_SIZE)
        self._volumes: deque[int] = deque(maxlen=_RING_SIZE)
        self._times: deque[datetime] = deque(maxlen=_RING_SIZE)
        self.consecutive_ticks: int = 0
        self.last_direction: str = "FLAT"

    def push(self, price: float, volume: int = 0) -> None:
        self._prices.append(price)
        self._volumes.append(volume)
        self._times.append(datetime.now())

    @property
    def latest_price(self) -> float:
        return self._prices[-1] if self._prices else 0.0

    @property
    def prev_price(self) -> float:
        return self._prices[-2] if len(self._prices) >= 2 else self._prices[-1] if self._prices else 0.0

    def velocity(self) -> float:
        """% change from previous tick."""
        prev = self.prev_price
        if prev <= 0:
            return 0.0
        return (self.latest_price - prev) / prev * 100

    def momentum_1m(self) -> float:
        """Cumulative % change over last 6 ticks (≈1 minute)."""
        ticks = list(self._prices)
        if len(ticks) < 2:
            return 0.0
        window = ticks[-min(6, len(ticks)):]
        if window[0] <= 0:
            return 0.0
        return (window[-1] - window[0]) / window[0] * 100

    def volume_spike(self, multiplier: float = 2.0) -> bool:
        """True if current volume > multiplier × 5-tick average volume."""
        vols = list(self._volumes)
        if len(vols) < 6 or vols[-1] == 0:
            return False
        avg_5 = sum(vols[-6:-1]) / 5
        return avg_5 > 0 and vols[-1] > avg_5 * multiplier

    def direction(self) -> str:
        v = self.velocity()
        if v > 0.01:
            return "UP"
        if v < -0.01:
            return "DOWN"
        return "FLAT"

    def to_summary(self) -> str:
        """One-line summary string for injecting into Claude's 15-min prompt."""
        d = self.direction()
        m = self.momentum_1m()
        v = self.volume_spike()
        ticks = list(self._prices)
        up_ticks = sum(1 for i in range(1, min(10, len(ticks))) if ticks[-i] > ticks[-i - 1])
        down_ticks = min(10, len(ticks) - 1) - up_ticks
        return (
            f"{self.symbol}: {up_ticks} UP / {down_ticks} DOWN ticks (last 10), "
            f"momentum {m:+.2f}%"
            + (", VOLUME SPIKE" if v else "")
        )


class MicroMonitor:
    """10-second price polling engine."""

    def __init__(self) -> None:
        self._buffers: dict[str, _SymbolBuffer] = {}
        self._running = False
        self._task: asyncio.Task | None = None
        # Last alert time per symbol (for cooldown)
        self._last_alert: dict[str, float] = {}
        # Active stop-losses (Feature 2: Stop-Loss Monitoring)
        # Format: {"RELIANCE": [{"signal_id": "...", "stop_loss": 2450.0, "action": "BUY"}]}
        self._active_stop_losses: dict[str, list[dict[str, Any]]] = {}

    # ----------------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------------

    def start(self) -> None:
        """Launch the polling loop as a background asyncio task."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._polling_loop(), name="micro_monitor")
            # Load active stop-losses on startup (Feature 2)
            if settings.stop_loss_enabled:
                asyncio.create_task(self.load_active_stop_losses())
            logger.info("MicroMonitor started (10-second polling)")

    def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("MicroMonitor stopped")

    # ----------------------------------------------------------------
    # Core polling loop
    # ----------------------------------------------------------------

    async def _polling_loop(self) -> None:
        """Infinite async loop: sleep 10s → fetch LTP → process ticks."""
        import time as _time

        while self._running:
            await asyncio.sleep(settings.micro_poll_interval_seconds)

            if not is_market_open():
                continue

            try:
                await self._fetch_and_process()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"MicroMonitor tick error (non-fatal): {e}")

    async def _fetch_and_process(self) -> None:
        """Fetch LTP for all tracked symbols and process ticks."""
        from src.services.groww_service import groww_service
        from src.services.telegram_bot import telegram_service
        from src.services.database import db

        symbols = list(self._buffers.keys())
        if not symbols:
            # Lazy init: load holdings on first tick
            symbols = await self._load_holding_symbols()

        if not symbols:
            return

        prices = await groww_service.get_bulk_ltp(symbols)

        for symbol in symbols:
            key = groww_service.get_price_key(symbol)
            price = prices.get(key) or groww_service.find_price(prices, symbol)
            if not price:
                continue

            if symbol not in self._buffers:
                self._buffers[symbol] = _SymbolBuffer(symbol)

            buf = self._buffers[symbol]
            buf.push(price)

            # Check for stop-loss breaches (Feature 2)
            breaches = self._check_stop_loss_breach(symbol, price)
            for breach in breaches:
                try:
                    await self._send_stop_loss_alert(symbol, price, breach)
                except Exception as e:
                    logger.error(f"Stop-loss alert failed for {symbol}: {e}")

            sig = self._evaluate(buf)
            if sig and not sig.alert_sent:
                continue  # no alert condition met
            if sig and sig.alert_sent:
                # Send micro-alert
                try:
                    await telegram_service.send_micro_alert(sig.model_dump(mode="json"))
                    await db.save_micro_signal(sig.model_dump(mode="json"))
                except Exception as e:
                    logger.warning(f"Micro-alert send failed for {symbol}: {e}")

    async def _load_holding_symbols(self) -> list[str]:
        """Fetch holding symbols and pre-initialize buffers."""
        try:
            from src.services.groww_service import groww_service
            holdings = await groww_service.get_holdings()
            symbols = [h.trading_symbol for h in holdings]
            for s in symbols:
                if s not in self._buffers:
                    self._buffers[s] = _SymbolBuffer(s)
            logger.info(f"MicroMonitor tracking {len(symbols)} symbols: {symbols}")
            return symbols
        except Exception as e:
            logger.warning(f"MicroMonitor: could not load holdings: {e}")
            return []

    # ----------------------------------------------------------------
    # Stop-Loss Monitoring (Feature 2)
    # ----------------------------------------------------------------

    async def load_active_stop_losses(self) -> None:
        """Load active stop-losses from trade_signals collection into memory.

        Fetches all ACTIVE signals with stop_loss field set, groups by symbol.
        Should be called on startup and periodically (hourly) to refresh.
        """
        if not settings.stop_loss_enabled:
            return

        from src.services.database import db

        try:
            # Fetch all ACTIVE signals with stop_loss defined
            signals = await db.trade_signals.find(
                {
                    "status": {"$in": ["ACTIVE", None]},  # ACTIVE or unset
                    "stop_loss": {"$exists": True, "$ne": None},
                }
            ).to_list(length=None)

            # Group by symbol
            self._active_stop_losses.clear()
            for sig in signals:
                symbol = sig.get("trading_symbol")
                if not symbol:
                    continue

                if symbol not in self._active_stop_losses:
                    self._active_stop_losses[symbol] = []

                self._active_stop_losses[symbol].append({
                    "signal_id": str(sig["_id"]),
                    "action": sig.get("action", "BUY"),
                    "stop_loss": float(sig["stop_loss"]),
                    "confidence": float(sig.get("confidence", 0.0)),
                })

            total = sum(len(sls) for sls in self._active_stop_losses.values())
            logger.info(
                f"Loaded {total} active stop-losses across "
                f"{len(self._active_stop_losses)} symbols"
            )

        except Exception as e:
            logger.error(f"Failed to load active stop-losses: {e}")

    def _check_stop_loss_breach(
        self, symbol: str, current_price: float
    ) -> list[dict[str, Any]]:
        """Check if current price has breached any active stop-losses for a symbol.

        Args:
            symbol: Trading symbol
            current_price: Current market price

        Returns:
            List of breached stop-loss dicts (each with signal_id, action, stop_loss)
        """
        if not settings.stop_loss_enabled:
            return []

        sls = self._active_stop_losses.get(symbol, [])
        if not sls:
            return []

        breaches = []
        grace = settings.stop_loss_grace_pct / 100.0

        for sl in sls:
            stop_price = sl["stop_loss"]
            action = sl["action"]

            # BUY signal: breach if price drops below stop_loss
            if action in ["BUY", "STRONG_BUY"]:
                threshold = stop_price * (1 - grace)
                if current_price <= threshold:
                    breaches.append(sl)

            # SELL signal: breach if price rises above stop_loss
            elif action in ["SELL", "STRONG_SELL"]:
                threshold = stop_price * (1 + grace)
                if current_price >= threshold:
                    breaches.append(sl)

        return breaches

    async def _send_stop_loss_alert(
        self, symbol: str, current_price: float, breach: dict[str, Any]
    ) -> None:
        """Send CRITICAL Telegram alert for stop-loss breach.

        Args:
            symbol: Trading symbol
            current_price: Current price that breached stop-loss
            breach: Dict with signal_id, action, stop_loss, confidence
        """
        from src.services.telegram_bot import telegram_service
        from src.services.database import db

        signal_id = breach["signal_id"]
        stop_loss = breach["stop_loss"]
        action = breach["action"]
        confidence = breach.get("confidence", 0.0)

        breach_pct = abs((current_price - stop_loss) / stop_loss * 100)

        message = (
            f"<b>STOP-LOSS HIT: {symbol}</b>\n\n"
            f"Signal: {action}\n"
            f"Stop-Loss: ₹{stop_loss:.2f}\n"
            f"Current Price: ₹{current_price:.2f} ({breach_pct:.2f}% breach)\n"
            f"Original Confidence: {confidence:.0%}\n\n"
            f"RECOMMENDATION: Review position immediately and consider exiting."
        )

        try:
            await telegram_service.send_message(message, parse_mode="HTML")

            # Mark signal as TRIGGERED in database
            await db.trade_signals.update_one(
                {"_id": signal_id},
                {"$set": {"status": "TRIGGERED", "trigger_timestamp": datetime.now()}}
            )

            # Remove from active stop-losses to avoid duplicate alerts
            if symbol in self._active_stop_losses:
                self._active_stop_losses[symbol] = [
                    sl for sl in self._active_stop_losses[symbol] if sl["signal_id"] != signal_id
                ]

            logger.warning(
                f"Stop-loss BREACH: {symbol} @ ₹{current_price:.2f} "
                f"(stop: ₹{stop_loss:.2f}, signal: {signal_id})"
            )

        except Exception as e:
            logger.error(f"Failed to send stop-loss alert for {symbol}: {e}")

    # ----------------------------------------------------------------
    # Signal evaluation
    # ----------------------------------------------------------------

    def _evaluate(self, buf: _SymbolBuffer) -> MicroSignal | None:
        """Evaluate alert conditions for a symbol's buffer.

        Returns MicroSignal with alert_sent=True if an alert should fire,
        MicroSignal with alert_sent=False if conditions not met.
        """
        import time as _time

        if len(buf._prices) < 2:
            return None

        velocity = buf.velocity()
        momentum = buf.momentum_1m()
        vol_spike = buf.volume_spike()
        direction = buf.direction()

        # Update consecutive tick count
        if direction == buf.last_direction and direction != "FLAT":
            buf.consecutive_ticks += 1
        elif direction != "FLAT":
            buf.consecutive_ticks = 1
            buf.last_direction = direction
        else:
            buf.consecutive_ticks = 0

        # Alert conditions
        velocity_breach = abs(velocity) >= settings.micro_velocity_threshold_pct
        consecutive_breach = buf.consecutive_ticks >= settings.micro_consecutive_ticks
        should_alert = velocity_breach or consecutive_breach or vol_spike

        # Cooldown: don't spam alerts for same symbol
        if should_alert:
            last = self._last_alert.get(buf.symbol, 0)
            if _time.monotonic() - last < settings.alert_cooldown_seconds:
                should_alert = False
            else:
                self._last_alert[buf.symbol] = _time.monotonic()

        return MicroSignal(
            symbol=buf.symbol,
            timestamp=datetime.now(),
            direction=direction,  # type: ignore[arg-type]
            velocity_pct=round(velocity, 4),
            momentum_1m=round(momentum, 4),
            volume_spike=vol_spike,
            current_price=buf.latest_price,
            prev_price=buf.prev_price,
            consecutive_ticks=buf.consecutive_ticks,
            alert_sent=should_alert,
        )

    # ----------------------------------------------------------------
    # Public query methods
    # ----------------------------------------------------------------

    def get_context_for_claude(self, symbol: str) -> str:
        """Return a one-line micro-data summary for injection into Claude's prompt."""
        buf = self._buffers.get(symbol)
        if not buf or len(buf._prices) < 2:
            return f"{symbol}: no tick data yet"
        return buf.to_summary()

    def get_all_context(self, symbols: list[str]) -> str:
        """Multi-line context for all symbols to inject into Claude's 15-min prompt."""
        lines = [self.get_context_for_claude(s) for s in symbols]
        return "\n".join(lines)

    def get_live_status(self) -> dict[str, dict]:
        """Return current tick state for /live Telegram command."""
        result: dict[str, dict] = {}
        for symbol, buf in self._buffers.items():
            if not buf._prices:
                continue
            result[symbol] = {
                "price": buf.latest_price,
                "direction": buf.direction(),
                "velocity": round(buf.velocity(), 3),
                "momentum_1m": round(buf.momentum_1m(), 3),
                "consecutive": buf.consecutive_ticks,
                "volume_spike": buf.volume_spike(),
            }
        return result


# Singleton
micro_monitor = MicroMonitor()
