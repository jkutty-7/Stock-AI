"""Telegram bot service for interactive commands and push notifications.

V2 improvements:
- Bug fix #7: /analyze help text uses proper HTML escape (&lt;SYMBOL&gt;)
- Per-user rate limiting: max 10 free-text messages per 5 minutes
- Alert cooldown: suppress duplicate symbol alerts within ALERT_COOLDOWN_SECONDS
- New commands: /live, /signals, /watchlist, /screen, /opportunity
- format_micro_alert used for Phase 2 micro-alerts

Commands:
    /start      - Welcome message
    /status     - Quick portfolio P&L summary
    /portfolio  - Detailed per-stock breakdown
    /analyze    - AI analysis for a specific stock
    /alerts     - Recent alert history
    /signals    - Active trade signals
    /live       - Current 10-sec tick state (Phase 2)
    /screen     - On-demand screener (Phase 3)
    /opportunity- Latest screener results (Phase 3)
    /watchlist  - View/manage personal watchlist
    /settings   - View current settings
    /help       - List all commands
"""

import logging
import time
from collections import defaultdict
from datetime import datetime
from typing import Optional

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.config import settings
from src.models.analysis import AlertMessage
from src.services.ai_engine import ai_engine
from src.services.database import db
from src.utils.formatters import (
    format_alert_message,
    format_analysis_result,
    format_holding_detail,
    format_micro_alert,
    format_portfolio_summary,
    format_screener_results,
    format_signal_list,
)

logger = logging.getLogger(__name__)


class TelegramBotService:
    """Telegram bot with command handlers and push notification support."""

    app: Optional[Application] = None

    def __init__(self) -> None:
        # Rate limiting: user_id -> list of message timestamps
        self._msg_timestamps: dict[int, list[float]] = defaultdict(list)
        self._rate_limit_window = 300  # 5 minutes
        self._rate_limit_max = 10  # max free-text messages per window

        # Alert cooldown: symbol -> last alert timestamp
        self._last_alert_time: dict[str, float] = {}

    async def initialize(self) -> None:
        """Build the Telegram bot application and register handlers."""
        self.app = ApplicationBuilder().token(settings.telegram_bot_token).build()

        # Register command handlers
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("status", self._cmd_status))
        self.app.add_handler(CommandHandler("portfolio", self._cmd_portfolio))
        self.app.add_handler(CommandHandler("analyze", self._cmd_analyze))
        self.app.add_handler(CommandHandler("alerts", self._cmd_alerts))
        self.app.add_handler(CommandHandler("signals", self._cmd_signals))
        self.app.add_handler(CommandHandler("live", self._cmd_live))
        self.app.add_handler(CommandHandler("screen", self._cmd_screen))
        self.app.add_handler(CommandHandler("opportunity", self._cmd_opportunity))
        self.app.add_handler(CommandHandler("watchlist", self._cmd_watchlist))
        self.app.add_handler(CommandHandler("settings", self._cmd_settings))
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        # Intraday commands
        self.app.add_handler(CommandHandler("intraday", self._cmd_intraday))
        self.app.add_handler(CommandHandler("itrades", self._cmd_itrades))
        self.app.add_handler(CommandHandler("isetup", self._cmd_isetup))
        self.app.add_handler(CommandHandler("ipnl", self._cmd_ipnl))
        self.app.add_handler(CommandHandler("iscan", self._cmd_iscan))
        self.app.add_handler(CommandHandler("irisk", self._cmd_irisk))

        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        await self.app.bot.set_my_commands([
            BotCommand("status", "Quick portfolio status"),
            BotCommand("portfolio", "Detailed portfolio view"),
            BotCommand("analyze", "AI analysis: /analyze RELIANCE"),
            BotCommand("alerts", "Recent alerts"),
            BotCommand("signals", "Active trade signals"),
            BotCommand("live", "Live 10-sec price ticks"),
            BotCommand("screen", "Run stock screener"),
            BotCommand("opportunity", "Latest screener results"),
            BotCommand("watchlist", "Manage watchlist"),
            BotCommand("settings", "View/modify settings"),
            BotCommand("help", "Show all commands"),
            BotCommand("intraday", "Today intraday watchlist with setups"),
            BotCommand("itrades", "Active intraday positions + P&L"),
            BotCommand("isetup", "Intraday setup: /isetup RELIANCE"),
            BotCommand("ipnl", "Today intraday P&L summary"),
            BotCommand("iscan", "Trigger on-demand intraday scan"),
            BotCommand("irisk", "Intraday risk status"),
        ])
        logger.info("Telegram bot initialized with command handlers")

    async def start(self) -> None:
        """Start the bot in webhook or polling mode."""
        if not self.app:
            raise RuntimeError("Bot not initialized. Call initialize() first.")
        await self.app.initialize()
        await self.app.start()

        if settings.telegram_webhook_url:
            webhook_url = settings.telegram_webhook_url.rstrip("/") + "/webhook"
            await self.app.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
            logger.info(f"Telegram bot webhook set: {webhook_url}")
        else:
            await self.app.bot.delete_webhook(drop_pending_updates=True)
            await self.app.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram bot polling started")

    async def process_update(self, data: dict) -> None:
        """Feed a raw webhook update into the bot dispatcher."""
        from telegram import Update
        update = Update.de_json(data, self.app.bot)
        await self.app.process_update(update)

    async def stop(self) -> None:
        """Graceful shutdown of the bot."""
        if self.app:
            if settings.telegram_webhook_url:
                await self.app.bot.delete_webhook()
            else:
                await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
            logger.info("Telegram bot stopped")

    # ----------------------------------------------------------------
    # Push Notifications
    # ----------------------------------------------------------------

    async def send_alert(self, alert: AlertMessage) -> None:
        """Send an alert with cooldown deduplication."""
        if not self.app:
            return

        # Cooldown check: suppress repeated alerts for the same symbol
        if alert.trading_symbol:
            last = self._last_alert_time.get(alert.trading_symbol, 0)
            if time.monotonic() - last < settings.alert_cooldown_seconds:
                logger.debug(f"Alert suppressed (cooldown): {alert.trading_symbol}")
                return
            self._last_alert_time[alert.trading_symbol] = time.monotonic()

        text = format_alert_message(alert)
        await self.app.bot.send_message(
            chat_id=settings.telegram_chat_id,
            text=text,
            parse_mode="HTML",
        )

    async def send_micro_alert(self, signal: dict) -> None:
        """Send a micro-signal (10-sec tick) alert."""
        if not self.app:
            return
        text = format_micro_alert(signal)
        await self.app.bot.send_message(
            chat_id=settings.telegram_chat_id,
            text=text,
            parse_mode="HTML",
        )

    async def send_error_notification(self, error: str) -> None:
        """Notify the user about system errors."""
        if not self.app:
            return
        await self.app.bot.send_message(
            chat_id=settings.telegram_chat_id,
            text=f"<b>[SYSTEM ERROR]</b>\n\n<code>{error[:800]}</code>",
            parse_mode="HTML",
        )

    async def send_message(self, text: str, parse_mode: str = "HTML") -> None:
        """Send a generic message, splitting if needed."""
        if not self.app:
            return
        for chunk in self._split_message(text):
            await self.app.bot.send_message(
                chat_id=settings.telegram_chat_id,
                text=chunk,
                parse_mode=parse_mode,
            )

    # ----------------------------------------------------------------
    # Command Handlers
    # ----------------------------------------------------------------

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "<b>Stock AI Portfolio Monitor v2</b>\n\n"
            "I monitor your Groww portfolio with 10-second live price tracking\n"
            "and Claude AI analysis every 15 minutes.\n\n"
            "Use /help to see all commands.",
            parse_mode="HTML",
        )

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        snapshot = await db.get_latest_snapshot()
        if not snapshot:
            await update.message.reply_text("No portfolio data yet. Monitoring starts shortly.")
            return
        text = format_portfolio_summary(snapshot)
        await update.message.reply_text(text, parse_mode="HTML")

    async def _cmd_portfolio(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        snapshot = await db.get_latest_snapshot()
        if not snapshot:
            await update.message.reply_text("No portfolio data available.")
            return
        for msg in format_holding_detail(snapshot):
            await update.message.reply_text(msg, parse_mode="HTML")

    async def _cmd_analyze(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        args = context.args
        if not args:
            # Bug fix #7: use HTML-escaped symbol placeholder correctly
            await update.message.reply_text(
                "Usage: /analyze &lt;SYMBOL&gt;\nExample: /analyze RELIANCE",
                parse_mode="HTML",
            )
            return

        symbol = args[0].upper()
        await update.message.reply_text(f"Analyzing {symbol}… This may take a moment.")
        try:
            analysis = await ai_engine.analyze_stock(symbol)
            await db.save_analysis(analysis)
            text = format_analysis_result(analysis)
            for chunk in self._split_message(text):
                await update.message.reply_text(chunk, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Analysis failed for {symbol}: {e}")
            await update.message.reply_text(f"Analysis failed: {str(e)[:300]}")

    async def _cmd_alerts(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        alerts = await db.get_recent_alerts(limit=10)
        if not alerts:
            await update.message.reply_text("No recent alerts.")
            return
        parts = ["<b>Recent Alerts</b>\n"]
        for a in alerts:
            severity = a.get("severity", "INFO")
            title = a.get("title", "Unknown")
            ts = str(a.get("timestamp", ""))[:16]
            parts.append(f"[{severity}] {title}\n  <i>{ts}</i>\n")
        for chunk in self._split_message("\n".join(parts)):
            await update.message.reply_text(chunk, parse_mode="HTML")

    async def _cmd_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show active trade signals."""
        signals = await db.get_active_signals()
        text = format_signal_list(signals)
        for chunk in self._split_message(text):
            await update.message.reply_text(chunk, parse_mode="HTML")

    async def _cmd_live(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show current 10-second tick state for all holdings (Phase 2)."""
        try:
            from src.services.micro_monitor import micro_monitor
            status = micro_monitor.get_live_status()
            if not status:
                await update.message.reply_text(
                    "No live tick data yet. Starts when market opens."
                )
                return
            parts = ["<b>⚡ Live Price Ticks</b>\n"]
            for symbol, info in status.items():
                dir_icon = "↗" if info["direction"] == "UP" else "↘" if info["direction"] == "DOWN" else "→"
                parts.append(
                    f"{dir_icon} <b>{symbol}</b>: ₹{info['price']:,.2f} "
                    f"({info['momentum_1m']:+.2f}% 1m | {info['consecutive']} ticks)"
                )
            await update.message.reply_text("\n".join(parts), parse_mode="HTML")
        except ImportError:
            await update.message.reply_text("Live monitoring (Phase 2) not yet active.")

    async def _cmd_screen(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Run on-demand stock screener (Phase 3)."""
        await update.message.reply_text("Running screener… This may take 1-2 minutes.")
        try:
            from src.services.screener import screener_engine
            from src.services.ai_engine import ai_engine as _ai
            candidates = await screener_engine.run_full_screen()
            top = candidates[:settings.screener_top_n]
            if not top:
                await update.message.reply_text("No candidates found in this screen.")
                return
            analysis = await _ai.analyze_screener_candidates([c.to_dict() for c in top])
            result_doc = {
                "timestamp": datetime.now(),
                "candidates": [c.to_dict() for c in top],
                "claude_analysis": analysis.model_dump(mode="json"),
            }
            await db.save_screener_result(result_doc)
            text = format_screener_results(result_doc)
            for chunk in self._split_message(text):
                await update.message.reply_text(chunk, parse_mode="HTML")
        except ImportError:
            await update.message.reply_text("Screener (Phase 3) not yet active.")
        except Exception as e:
            logger.error(f"Screener failed: {e}")
            await update.message.reply_text(f"Screener failed: {str(e)[:300]}")

    async def _cmd_opportunity(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show latest screener results from DB."""
        result = await db.get_latest_screener_result()
        if not result:
            await update.message.reply_text("No screener results yet. Use /screen to run one.")
            return
        text = format_screener_results(result)
        for chunk in self._split_message(text):
            await update.message.reply_text(chunk, parse_mode="HTML")

    async def _cmd_watchlist(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """View/add/remove symbols from the personal watchlist."""
        args = context.args
        user_settings = await db.get_user_settings()
        watchlist: list[str] = user_settings.get("watchlist", [])

        if not args:
            if watchlist:
                await update.message.reply_text(
                    f"<b>Watchlist:</b>\n{', '.join(watchlist)}\n\n"
                    f"Use /watchlist add SYMBOL or /watchlist remove SYMBOL",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(
                    "Watchlist is empty.\nUse /watchlist add SYMBOL to add stocks."
                )
            return

        action_arg = args[0].lower()
        if len(args) < 2:
            await update.message.reply_text("Usage: /watchlist add|remove SYMBOL")
            return

        symbol = args[1].upper()
        if action_arg == "add":
            if symbol not in watchlist:
                watchlist.append(symbol)
                await db.update_user_settings({"watchlist": watchlist})
                await update.message.reply_text(f"{symbol} added to watchlist.")
            else:
                await update.message.reply_text(f"{symbol} is already in watchlist.")
        elif action_arg == "remove":
            if symbol in watchlist:
                watchlist.remove(symbol)
                await db.update_user_settings({"watchlist": watchlist})
                await update.message.reply_text(f"{symbol} removed from watchlist.")
            else:
                await update.message.reply_text(f"{symbol} not found in watchlist.")
        else:
            await update.message.reply_text("Usage: /watchlist add|remove SYMBOL")

    async def _cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_settings = await db.get_user_settings()
        text = (
            "<b>Settings</b>\n\n"
            f"Monitoring: {'ON' if user_settings.get('monitoring_enabled') else 'OFF'}\n"
            f"Frequency: every {user_settings.get('analysis_frequency_minutes', 15)} min\n"
            f"P&amp;L Alert: {user_settings.get('pnl_alert_threshold_pct', 5)}%\n"
            f"Portfolio Alert: {user_settings.get('portfolio_alert_threshold_pct', 3)}%\n"
            f"Analysis Depth: {user_settings.get('preferred_analysis_depth', 'detailed')}\n"
            f"Watchlist: {', '.join(user_settings.get('watchlist', [])) or 'None'}\n"
            f"Notifications: {'ON' if user_settings.get('telegram_notifications_enabled') else 'OFF'}"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "<b>Available Commands</b>\n\n"
            "/status — Quick portfolio P&amp;L summary\n"
            "/portfolio — Detailed holdings view\n"
            "/analyze &lt;SYMBOL&gt; — AI analysis for a stock\n"
            "/alerts — Recent alerts\n"
            "/signals — Active trade signals\n"
            "/live — Real-time 10-sec tick prices\n"
            "/screen — Run stock screener (top opportunities)\n"
            "/opportunity — Latest screener results\n"
            "/watchlist — View/add/remove watchlist symbols\n"
            "/settings — View current settings\n"
            "/help — Show this message\n\n"
            "You can also type any question about your portfolio or the market.",
            parse_mode="HTML",
        )


    async def _cmd_intraday(self, update, context) -> None:
        """Show today intraday watchlist."""
        try:
            from src.services.intraday_scanner import intraday_scanner
            setups = await intraday_scanner.get_today_watchlist()
            text = intraday_scanner.format_morning_report(setups)
            await update.message.reply_text(text, parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"Intraday watchlist unavailable: {str(e)[:200]}")

    async def _cmd_itrades(self, update, context) -> None:
        """Show active intraday positions with live P&L."""
        try:
            from src.services.intraday_monitor import intraday_monitor
            positions = intraday_monitor.get_active_positions()
            if not positions:
                await update.message.reply_text("No active intraday positions.")
                return
            lines = ["<b>Active Intraday Positions</b>\n"]
            for p in positions:
                pnl_sign = "+" if p["current_pnl"] >= 0 else ""
                lines.append(
                    f"<b>{p['symbol']}</b> ({p['direction']})\n"
                    f"  Entry: Rs.{p['entry_price']:.2f} | Now: Rs.{p['current_price']:.2f}\n"
                    f"  Qty: {p['quantity']} | P&L: {pnl_sign}Rs.{p['current_pnl']:.0f} ({pnl_sign}{p['current_pnl_pct']:.2f}%)\n"
                    f"  SL: Rs.{p['stop_loss']:.2f} | Target: Rs.{p['target']:.2f}\n"
                    f"  Trigger: {p['entry_trigger']} @ {p['entry_time']}"
                )
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"Error: {str(e)[:200]}")

    async def _cmd_isetup(self, update, context) -> None:
        """Show detailed intraday setup for a specific stock."""
        args = context.args
        if not args:
            await update.message.reply_text(
                "Usage: /isetup &lt;SYMBOL&gt;\nExample: /isetup RELIANCE", parse_mode="HTML"
            )
            return
        symbol = args[0].upper()
        await update.message.reply_text(f"Fetching intraday setup for {symbol}...")
        try:
            from src.tools.executor import execute_tool
            indicators = await execute_tool("get_intraday_indicators", {"trading_symbol": symbol})
            orb = await execute_tool("get_opening_range", {"trading_symbol": symbol})
            gap = await execute_tool("get_gap_analysis", {"trading_symbol": symbol})
            lines = [f"<b>Intraday Setup: {symbol}</b>\n"]
            if isinstance(gap, dict) and not gap.get("error"):
                lines.append(f"Gap: {gap.get('gap_pct', 0):+.2f}% ({gap.get('gap_type', '')})")
                lines.append(f"Prev Close: Rs.{gap.get('prev_close', 0):.2f} | Open: Rs.{gap.get('today_open', 0):.2f}")
            if isinstance(indicators, dict) and not indicators.get("error"):
                cpr = indicators.get("cpr", {})
                st = indicators.get("supertrend", {})
                vwap_d = indicators.get("vwap", {})
                if cpr:
                    lines.append(f"\nCPR: {cpr.get('bc', 0):.1f}-{cpr.get('tc', 0):.1f} (Pivot: {cpr.get('pivot', 0):.1f})")
                    lines.append(f"R1: {cpr.get('r1', 0):.1f} | R2: {cpr.get('r2', 0):.1f}")
                    lines.append(f"S1: {cpr.get('s1', 0):.1f} | S2: {cpr.get('s2', 0):.1f}")
                if st:
                    lines.append(f"Supertrend: {st.get('direction', 'UNKNOWN')} @ Rs.{st.get('value', 0):.2f}")
                if vwap_d:
                    lines.append(f"VWAP: Rs.{vwap_d.get('vwap', 0):.2f} (+1SD: {vwap_d.get('upper_band', 0):.2f} | -1SD: {vwap_d.get('lower_band', 0):.2f})")
                lines.append(f"\nCurrent: Rs.{indicators.get('current_price', 0):.2f}")
            if isinstance(orb, dict) and not orb.get("error"):
                lines.append(f"\nORB High: Rs.{orb.get('orb_high', 0):.2f} | ORB Low: Rs.{orb.get('orb_low', 0):.2f}")
                lines.append(f"Breakout: {orb.get('breakout_direction', 'NONE')} ({orb.get('breakout_strength_pct', 0):.2f}%)")
            elif isinstance(orb, dict) and orb.get("error"):
                lines.append(f"\nORB: {orb['error']}")
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"Setup fetch failed: {str(e)[:300]}")

    async def _cmd_ipnl(self, update, context) -> None:
        """Show today intraday P&L summary."""
        try:
            from src.services.intraday_scanner import intraday_scanner
            report = await intraday_scanner.generate_daily_report()
            text = intraday_scanner.format_daily_report(report)
            await update.message.reply_text(text, parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"P&L data unavailable: {str(e)[:200]}")

    async def _cmd_iscan(self, update, context) -> None:
        """Trigger on-demand intraday scan."""
        await update.message.reply_text("Running intraday scan...")
        try:
            from src.services.intraday_scanner import intraday_scanner
            from src.services.intraday_monitor import intraday_monitor
            setups = await intraday_scanner.run_premarket_scan()
            await intraday_monitor.load_watchlist()
            text = intraday_scanner.format_morning_report(setups)
            await update.message.reply_text(text, parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"Scan failed: {str(e)[:200]}")

    async def _cmd_irisk(self, update, context) -> None:
        """Show intraday risk status."""
        try:
            from src.services.intraday_monitor import intraday_monitor
            risk = intraday_monitor.get_risk_status()
            breaker_icon = "[BLOCKED]" if risk["breaker_triggered"] else "[OK]"
            lines = [
                "<b>Intraday Risk Status</b>\n",
                f"Positions: {risk['open_positions']}/{risk['max_positions']}",
                f"Open Risk: Rs.{risk['open_risk_rs']:.0f}",
                f"Today P&L: Rs.{risk['daily_pnl_rs']:+.0f}",
                f"Daily Loss Limit: Rs.{risk['daily_loss_limit_rs']:.0f}",
                f"Remaining Budget: Rs.{risk['remaining_loss_budget_rs']:.0f}",
                f"Breaker: {breaker_icon}",
            ]
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"Risk status unavailable: {str(e)[:200]}")

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle free-text messages with per-user rate limiting."""
        user_id = update.effective_user.id if update.effective_user else 0
        now = time.monotonic()

        # Clean old timestamps outside the window
        self._msg_timestamps[user_id] = [
            t for t in self._msg_timestamps[user_id]
            if now - t < self._rate_limit_window
        ]

        if len(self._msg_timestamps[user_id]) >= self._rate_limit_max:
            await update.message.reply_text(
                f"Rate limit: max {self._rate_limit_max} questions per 5 minutes."
            )
            return

        self._msg_timestamps[user_id].append(now)
        user_text = update.message.text
        await update.message.reply_text("Thinking…")

        try:
            analysis = await ai_engine.answer_question(user_text)
            await db.save_analysis(analysis)
            text = format_analysis_result(analysis)
            for chunk in self._split_message(text):
                await update.message.reply_text(chunk, parse_mode="HTML")
        except Exception as e:
            logger.error(f"AI Q&A failed: {e}")
            await update.message.reply_text(f"Sorry, I couldn't process that: {str(e)[:300]}")

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------

    def _split_message(self, text: str, max_length: int = 4096) -> list[str]:
        """Split long messages to respect Telegram's 4096 char limit."""
        if len(text) <= max_length:
            return [text]
        chunks: list[str] = []
        while text:
            if len(text) <= max_length:
                chunks.append(text)
                break
            split_point = text.rfind("\n", 0, max_length)
            if split_point == -1:
                split_point = max_length
            chunks.append(text[:split_point])
            text = text[split_point:].lstrip()
        return chunks


# Singleton
telegram_service = TelegramBotService()
