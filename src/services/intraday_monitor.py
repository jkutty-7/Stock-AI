"""Intraday Monitor — 1-minute polling engine for day trading.

Responsibilities:
  - Polls bulk LTP every 60 seconds during 9:30–3:15 PM
  - Runs pure-Python entry condition checks (no Claude cost per tick)
  - Calls IntradayAIEngine ONLY when a trigger is detected (rare)
  - Monitors open positions for target/SL/trailing-SL exits
  - Enforces daily loss breaker (stops new entries if limit hit)
  - Sends CRITICAL alert at 3:15 PM to exit all open MIS positions
  - Saves all positions and signals to MongoDB
"""

import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta
from math import floor
from typing import Optional

from src.models.intraday import IntradayORBData, IntradayPosition
from src.models.analysis import ActionType
from src.services.database import db
from src.services.groww_service import groww_service
from src.services.telegram_bot import telegram_service
from src.utils.intraday_indicators import (
    check_orb_breakout,
    compute_supertrend,
    compute_vwap_bands,
)
from src.utils.market_hours import is_market_holiday, now_ist

logger = logging.getLogger(__name__)


class IntradayMonitor:
    """1-minute intraday trading monitor and position manager."""

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # State reset each day at startup
        self._active_positions: dict[str, IntradayPosition] = {}  # symbol → position
        self._watchlist: list[str] = []
        self._orb_data: dict[str, IntradayORBData] = {}            # symbol → ORB
        self._vwap_cache: dict[str, dict] = {}                     # symbol → vwap dict
        self._supertrend_dir: dict[str, str] = {}                  # symbol → "UP"/"DOWN"
        self._prev_prices: dict[str, float] = {}                   # for VWAP cross detection

        # Daily P&L tracking
        self._daily_realized_pnl: float = 0.0
        self._breaker_triggered: bool = False
        self._alert_cooldown: dict[str, float] = {}                # symbol → last alert ts

    # ----------------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------------

    async def start(self) -> None:
        """Launch the 1-minute polling loop as a background task."""
        from src.config import settings
        if not settings.intraday_enabled:
            logger.info("Intraday trading disabled (INTRADAY_ENABLED=false)")
            return
        self._running = True
        self._task = asyncio.create_task(self._polling_loop(), name="intraday_monitor")
        logger.info("IntradayMonitor started (1-minute polling)")

    async def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("IntradayMonitor stopped")

    async def load_watchlist(self) -> None:
        """Load today's watchlist from the intraday_watchlist DB collection."""
        from src.services.intraday_scanner import intraday_scanner
        setups = await intraday_scanner.get_today_watchlist()
        self._watchlist = [s.symbol for s in setups]
        # Also include any existing holdings (always monitor what you own)
        try:
            holdings = await groww_service.get_holdings()
            for h in holdings:
                if h.trading_symbol not in self._watchlist:
                    self._watchlist.append(h.trading_symbol)
        except Exception:
            pass
        logger.info(f"Intraday watchlist loaded: {len(self._watchlist)} symbols")

    # ----------------------------------------------------------------
    # ORB Setup (called at 9:31 AM by scheduler)
    # ----------------------------------------------------------------

    async def setup_orb(self) -> None:
        """Compute Opening Range Breakout data after first 15-minute candle."""
        from src.config import settings
        from src.utils.intraday_indicators import compute_opening_range

        if not self._watchlist:
            await self.load_watchlist()

        today = now_ist().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_start_str = today_start.strftime("%Y-%m-%d %H:%M:%S")
        now_str = now_ist().strftime("%Y-%m-%d %H:%M:%S")

        computed = 0
        for sym in self._watchlist[:20]:  # cap to 20 for rate limits
            try:
                candles = await groww_service.get_historical_candles(
                    trading_symbol=sym,
                    exchange="NSE",
                    segment="CASH",
                    start_time=today_start_str,
                    end_time=now_str,
                    interval_minutes=1,
                )
                orb = compute_opening_range(
                    candles_today=candles,
                    symbol=sym,
                    trading_date=today,
                    orb_minutes=settings.intraday_orb_minutes,
                )
                if orb:
                    self._orb_data[sym] = orb
                    # Persist to DB
                    await db.intraday_orb_data.replace_one(
                        {"symbol": sym, "date": today.isoformat()},
                        {**orb.model_dump(), "date": today.isoformat()},
                        upsert=True,
                    )
                    computed += 1
                await asyncio.sleep(0.5)  # respect rate limits
            except Exception as e:
                logger.debug(f"ORB setup failed for {sym}: {e}")

        logger.info(f"ORB setup complete: {computed}/{len(self._watchlist[:20])} symbols")

    # ----------------------------------------------------------------
    # Main polling loop
    # ----------------------------------------------------------------

    async def _polling_loop(self) -> None:
        """Infinite 60-second polling loop during intraday hours."""
        from src.config import settings

        logger.info("Intraday polling loop started")
        while self._running:
            await asyncio.sleep(settings.intraday_poll_interval_seconds)

            now = now_ist()
            if is_market_holiday(now):
                continue

            market_start = now.replace(
                hour=settings.market_open_hour,
                minute=settings.market_open_minute + 15,  # start after ORB window
                second=0, microsecond=0
            )
            hard_exit_time = now.replace(
                hour=settings.intraday_hard_exit_hour,
                minute=settings.intraday_hard_exit_minute,
                second=0, microsecond=0
            )

            if not (market_start <= now <= hard_exit_time):
                continue

            try:
                await self._monitor_cycle()
            except Exception as e:
                logger.error(f"Intraday monitor cycle error: {e}", exc_info=True)

    async def _monitor_cycle(self) -> None:
        """Single 1-minute monitoring cycle."""
        if not self._watchlist:
            return

        # 1. Fetch bulk LTP
        try:
            prices = await groww_service.get_bulk_ltp(self._watchlist)
        except Exception as e:
            logger.warning(f"Intraday bulk LTP failed: {e}")
            return

        # 2. Update open positions (P&L, target/SL checks)
        await self._check_open_positions(prices)

        # 3. Check daily loss breaker before scanning for entries
        if self._breaker_triggered:
            return

        # 4. Scan for new entries (only if below max positions limit)
        from src.config import settings
        if len(self._active_positions) >= settings.intraday_max_positions:
            return

        # 5. Update VWAP and Supertrend for watchlist symbols
        await self._refresh_indicators_for_watchlist()

        # 6. Check entry conditions for each watchlist symbol
        for sym in self._watchlist:
            if sym in self._active_positions:
                continue

            current_price = groww_service.find_price(prices, sym)
            if not current_price:
                continue

            prev_price = self._prev_prices.get(sym, current_price)

            # Get micro signal context (from MicroMonitor — already running)
            micro = await self._get_micro_context(sym)
            vwap = self._vwap_cache.get(sym, {}).get("vwap", 0.0)
            st_dir = self._supertrend_dir.get(sym, "UNKNOWN")

            trigger = self._intraday_engine_ref().evaluate_entry_conditions(
                symbol=sym,
                current_price=current_price,
                prev_price=prev_price,
                orb=self._orb_data.get(sym),
                micro=micro,
                vwap=vwap,
                supertrend_direction=st_dir,
            )

            if trigger:
                await self._handle_entry_trigger(sym, current_price, trigger, micro)

            self._prev_prices[sym] = current_price

    async def _check_open_positions(self, prices: dict[str, float]) -> None:
        """Update P&L and check exit conditions for all open positions."""
        closed = []
        for sym, pos in list(self._active_positions.items()):
            price = groww_service.find_price(prices, sym)
            if not price:
                continue

            pos.update_pnl(price)

            # Save updated P&L to DB (throttled — only every 5 minutes)
            should_save = (
                sym not in self._alert_cooldown
                or (datetime.now().timestamp() - self._alert_cooldown.get(f"db_{sym}", 0) > 300)
            )
            if should_save:
                await self._upsert_position(pos)
                self._alert_cooldown[f"db_{sym}"] = datetime.now().timestamp()

            exit_reason = None
            if pos.direction == "LONG":
                if price >= pos.target:
                    exit_reason = "TARGET_HIT"
                elif price <= (pos.trailing_sl or pos.stop_loss):
                    exit_reason = "STOP_HIT" if not pos.trailing_sl else "TRAILING_SL"
                elif pos.trailing_sl is None and (price - pos.entry_price) >= pos.entry_price * 0.01:
                    # Move SL to breakeven once 1% in profit
                    pos.trailing_sl = pos.entry_price
                    logger.info(f"Intraday trailing SL: {sym} SL moved to breakeven {pos.entry_price:.2f}")
            else:  # SHORT
                if price <= pos.target:
                    exit_reason = "TARGET_HIT"
                elif price >= (pos.trailing_sl or pos.stop_loss):
                    exit_reason = "STOP_HIT" if not pos.trailing_sl else "TRAILING_SL"

            if exit_reason:
                await self._close_position(pos, price, exit_reason)
                closed.append(sym)

        for sym in closed:
            self._active_positions.pop(sym, None)

    async def _handle_entry_trigger(
        self,
        symbol: str,
        current_price: float,
        trigger: str,
        micro: dict,
    ) -> None:
        """Python trigger detected → ask Claude to validate → open position."""
        from src.config import settings

        # Cooldown: don't re-trigger same symbol within 5 minutes
        last = self._alert_cooldown.get(f"entry_{symbol}", 0)
        if datetime.now().timestamp() - last < 300:
            return
        self._alert_cooldown[f"entry_{symbol}"] = datetime.now().timestamp()

        # Time check: no new entries after 2:30 PM
        now = now_ist()
        no_entry_after = now.replace(
            hour=settings.intraday_no_entry_after_hour,
            minute=settings.intraday_no_entry_after_minute,
            second=0,
        )
        if now >= no_entry_after:
            logger.info(f"Intraday: no entry after {no_entry_after.strftime('%H:%M')} — skipping {symbol}")
            return

        logger.info(f"Intraday entry trigger: {symbol} via {trigger} @ Rs.{current_price:.2f}")

        # Get regime for AI context
        regime = None
        try:
            from src.services.regime_classifier import regime_classifier
            regime = await regime_classifier.get_current_regime()
        except Exception:
            pass

        # Call Claude to validate
        try:
            result = await self._intraday_engine_ref().analyze_entry(
                symbol=symbol,
                trigger=trigger,
                context={
                    "current_price": current_price,
                    "time_ist": now.strftime("%H:%M IST"),
                    "micro": micro,
                },
                regime=regime,
            )
        except Exception as e:
            logger.error(f"Intraday AI entry analysis failed for {symbol}: {e}")
            return

        # Find the signal for this symbol
        signal = next(
            (s for s in result.signals if s.trading_symbol == symbol),
            None
        )
        if not signal:
            return

        if signal.action not in (ActionType.BUY, ActionType.STRONG_BUY):
            logger.info(f"Intraday: Claude declined entry for {symbol} ({signal.action}) — {signal.reasoning[:80]}")
            return

        if not signal.stop_loss or not signal.target_price:
            logger.warning(f"Intraday: no SL/target in signal for {symbol} — skipping")
            return

        # Compute position size
        qty = self._intraday_engine_ref().calculate_position_size(
            entry_price=current_price,
            stop_loss=signal.stop_loss,
            risk_rs=settings.intraday_risk_per_trade_rs,
            max_position_value=settings.intraday_max_position_value,
        )
        if qty <= 0:
            logger.warning(f"Intraday: zero quantity computed for {symbol} — SL too tight or price too high")
            return

        # Create position record
        position = IntradayPosition(
            id=str(uuid.uuid4()),
            symbol=symbol,
            entry_price=current_price,
            entry_time=now,
            quantity=qty,
            direction="LONG",
            stop_loss=signal.stop_loss,
            target=signal.target_price,
            entry_trigger=trigger,
            risk_amount=round(abs(current_price - signal.stop_loss) * qty, 2),
            current_price=current_price,
        )
        position.update_pnl(current_price)

        self._active_positions[symbol] = position
        await self._upsert_position(position)

        # Save signal to trade_signals
        signal_id = await db.save_signal(signal)
        position.signal_id = str(signal_id) if signal_id else None
        await self._upsert_position(position)

        # Send Telegram alert
        risk_rs = round(abs(current_price - signal.stop_loss) * qty, 0)
        await telegram_service.send_message(
            f"<b>Intraday Entry Signal</b>\n\n"
            f"Symbol: <b>{symbol}</b>\n"
            f"Trigger: {trigger}\n"
            f"Action: {signal.action.value}\n"
            f"Entry: Rs.{current_price:.2f}\n"
            f"Stop-Loss: Rs.{signal.stop_loss:.2f}\n"
            f"Target: Rs.{signal.target_price:.2f}\n"
            f"Qty: {qty} shares | Risk: Rs.{risk_rs:.0f}\n"
            f"R:R = 1:{signal.risk_reward_ratio or '?'}\n"
            f"Confidence: {signal.confidence:.0%}\n\n"
            f"<i>{signal.reasoning[:200]}</i>"
        )
        logger.info(f"Intraday position opened: {symbol} {qty} shares @ Rs.{current_price:.2f}")

    async def _close_position(
        self,
        pos: IntradayPosition,
        exit_price: float,
        reason: str,
    ) -> None:
        """Mark position closed, update P&L, send alert."""
        pos.exit_price = exit_price
        pos.exit_time = now_ist()
        pos.exit_reason = reason
        pos.status = {
            "TARGET_HIT": "TARGET_HIT",
            "STOP_HIT": "STOP_HIT",
            "TRAILING_SL": "CLOSED",
            "HARD_EXIT": "HARD_EXITED",
        }.get(reason, "CLOSED")
        pos.update_pnl(exit_price)

        self._daily_realized_pnl += pos.current_pnl
        await self._upsert_position(pos)

        # Check daily loss breaker
        from src.config import settings
        if self._daily_realized_pnl <= -abs(settings.intraday_max_daily_loss_rs):
            if not self._breaker_triggered:
                self._breaker_triggered = True
                await db.intraday_breaker_state.replace_one(
                    {"date": now_ist().date().isoformat()},
                    {"date": now_ist().date().isoformat(), "triggered": True, "timestamp": datetime.now()},
                    upsert=True,
                )
                await telegram_service.send_message(
                    f"<b>[CRITICAL] Intraday Daily Loss Limit Hit</b>\n\n"
                    f"Daily P&L: Rs.{self._daily_realized_pnl:.0f}\n"
                    f"Limit: Rs.{settings.intraday_max_daily_loss_rs:.0f}\n"
                    f"No new intraday entries will be taken today.",
                    parse_mode="HTML",
                )

        pnl_sign = "+" if pos.current_pnl >= 0 else ""
        icon = "✓" if pos.current_pnl >= 0 else "✗"
        await telegram_service.send_message(
            f"<b>Intraday Position Closed [{icon}]</b>\n\n"
            f"Symbol: <b>{pos.symbol}</b>\n"
            f"Exit: Rs.{exit_price:.2f} ({reason})\n"
            f"Entry: Rs.{pos.entry_price:.2f}\n"
            f"P&L: {pnl_sign}Rs.{pos.current_pnl:.0f} ({pnl_sign}{pos.current_pnl_pct:.2f}%)\n"
            f"Today's total P&L: {'+' if self._daily_realized_pnl >= 0 else ''}Rs.{self._daily_realized_pnl:.0f}"
        )
        logger.info(
            f"Intraday position closed: {pos.symbol} @ Rs.{exit_price:.2f} "
            f"({reason}) P&L: Rs.{pos.current_pnl:.0f}"
        )

    # ----------------------------------------------------------------
    # Hard exit at 3:15 PM
    # ----------------------------------------------------------------

    async def hard_exit_alert(self) -> None:
        """Send CRITICAL alert for all open MIS positions at 3:15 PM."""
        if not self._active_positions:
            return

        lines = ["<b>[CRITICAL] Hard Exit — Close All Intraday Positions</b>", ""]
        lines.append(f"Time: {now_ist().strftime('%H:%M IST')}")
        lines.append(f"Open positions: {len(self._active_positions)}")
        lines.append("")

        for sym, pos in self._active_positions.items():
            pnl_sign = "+" if pos.current_pnl >= 0 else ""
            lines.append(
                f"<b>{sym}</b> | Qty: {pos.quantity} | Entry: Rs.{pos.entry_price:.2f} "
                f"| Current: Rs.{pos.current_price:.2f} "
                f"| P&L: {pnl_sign}Rs.{pos.current_pnl:.0f}"
            )

        lines.append("")
        lines.append("MIS positions must be squared off before 3:30 PM to avoid auto-squareoff penalty.")

        await telegram_service.send_message("\n".join(lines))
        logger.warning(f"Hard exit alert sent for {len(self._active_positions)} positions")

        # Mark all open positions as HARD_EXITED in DB
        for sym, pos in self._active_positions.items():
            pos.status = "HARD_EXITED"
            pos.exit_reason = "HARD_EXIT"
            pos.exit_time = now_ist()
            await self._upsert_position(pos)

        self._active_positions.clear()

    # ----------------------------------------------------------------
    # Status helpers (for Telegram commands and API)
    # ----------------------------------------------------------------

    def get_active_positions(self) -> list[dict]:
        """Return current open positions for /itrades command."""
        return [
            {
                "symbol": pos.symbol,
                "direction": pos.direction,
                "entry_price": pos.entry_price,
                "current_price": pos.current_price,
                "quantity": pos.quantity,
                "stop_loss": pos.stop_loss,
                "target": pos.target,
                "trailing_sl": pos.trailing_sl,
                "current_pnl": pos.current_pnl,
                "current_pnl_pct": pos.current_pnl_pct,
                "entry_trigger": pos.entry_trigger,
                "entry_time": pos.entry_time.strftime("%H:%M"),
                "status": pos.status,
            }
            for pos in self._active_positions.values()
        ]

    def get_risk_status(self) -> dict:
        """Return risk status for /irisk command."""
        from src.config import settings
        open_risk = sum(
            abs(pos.entry_price - pos.stop_loss) * pos.quantity
            for pos in self._active_positions.values()
        )
        return {
            "open_positions": len(self._active_positions),
            "max_positions": settings.intraday_max_positions,
            "open_risk_rs": round(open_risk, 2),
            "daily_pnl_rs": round(self._daily_realized_pnl, 2),
            "daily_loss_limit_rs": settings.intraday_max_daily_loss_rs,
            "breaker_triggered": self._breaker_triggered,
            "remaining_loss_budget_rs": round(
                settings.intraday_max_daily_loss_rs + self._daily_realized_pnl, 2
            ),
        }

    # ----------------------------------------------------------------
    # Indicator refresh
    # ----------------------------------------------------------------

    async def _refresh_indicators_for_watchlist(self) -> None:
        """Update VWAP and Supertrend cache for watchlist (runs every cycle)."""
        from src.config import settings

        today = now_ist().date()
        today_start_str = datetime.combine(today, datetime.min.time()).strftime("%Y-%m-%d %H:%M:%S")
        now_str = now_ist().strftime("%Y-%m-%d %H:%M:%S")

        # Only refresh if not already done this minute (light throttling)
        # In practice this is called every 60s so it will re-run each cycle for top 5 symbols
        for sym in self._watchlist[:5]:  # limit to 5 per cycle to respect rate limits
            try:
                candles_5m = await groww_service.get_historical_candles(
                    trading_symbol=sym,
                    exchange="NSE",
                    segment="CASH",
                    start_time=today_start_str,
                    end_time=now_str,
                    interval_minutes=5,
                )
                if candles_5m:
                    # VWAP
                    vwap_data = compute_vwap_bands(candles_5m)
                    self._vwap_cache[sym] = vwap_data

                    # Supertrend (5-min chart)
                    st = compute_supertrend(candles_5m, period=settings.intraday_supertrend_period, multiplier=settings.intraday_supertrend_multiplier)
                    if st:
                        latest = st[-1]
                        prev_dir = self._supertrend_dir.get(sym, latest["direction"])
                        if latest["flipped"] and latest["direction"] == "UP" and prev_dir == "DOWN":
                            self._supertrend_dir[sym] = "FLIPPED_UP"
                        elif latest["flipped"] and latest["direction"] == "DOWN" and prev_dir == "UP":
                            self._supertrend_dir[sym] = "FLIPPED_DOWN"
                        else:
                            self._supertrend_dir[sym] = latest["direction"]
                await asyncio.sleep(0.3)  # rate limit
            except Exception as e:
                logger.debug(f"Indicator refresh failed for {sym}: {e}")

    async def _get_micro_context(self, symbol: str) -> dict:
        """Get MicroMonitor tick context for a symbol."""
        try:
            from src.services.micro_monitor import micro_monitor
            live = micro_monitor.get_live_status()
            return live.get(symbol, {})
        except Exception:
            return {}

    async def _upsert_position(self, pos: IntradayPosition) -> None:
        """Save or update position in MongoDB."""
        try:
            doc = {**pos.model_dump(), "entry_time": pos.entry_time}
            await db.intraday_positions.replace_one(
                {"id": pos.id},
                doc,
                upsert=True,
            )
        except Exception as e:
            logger.error(f"Failed to save intraday position {pos.symbol}: {e}")

    @staticmethod
    def _intraday_engine_ref():
        """Lazy import to avoid circular dependency."""
        from src.services.intraday_engine import intraday_ai_engine
        return intraday_ai_engine


# Singleton
intraday_monitor = IntradayMonitor()
