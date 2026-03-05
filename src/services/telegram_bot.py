"""Telegram bot service for interactive commands and push notifications.

Commands:
    /start    - Welcome message
    /status   - Quick portfolio P&L summary
    /portfolio - Detailed per-stock breakdown
    /analyze <SYMBOL> - AI analysis for a specific stock
    /alerts   - Recent alert history
    /settings - View/modify alert settings
    /help     - List all commands

Free-text messages are forwarded to the AI engine for portfolio Q&A.
"""

import logging

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
    format_portfolio_summary,
)

logger = logging.getLogger(__name__)


class TelegramBotService:
    """Telegram bot with command handlers and push notification support."""

    app: Application | None = None

    async def initialize(self) -> None:
        """Build the Telegram bot application and register handlers."""
        self.app = ApplicationBuilder().token(settings.telegram_bot_token).build()

        # Register command handlers
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("status", self._cmd_status))
        self.app.add_handler(CommandHandler("portfolio", self._cmd_portfolio))
        self.app.add_handler(CommandHandler("analyze", self._cmd_analyze))
        self.app.add_handler(CommandHandler("alerts", self._cmd_alerts))
        self.app.add_handler(CommandHandler("settings", self._cmd_settings))
        self.app.add_handler(CommandHandler("help", self._cmd_help))

        # Free-text handler for AI Q&A
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        # Set bot command menu
        await self.app.bot.set_my_commands(
            [
                BotCommand("status", "Quick portfolio status"),
                BotCommand("portfolio", "Detailed portfolio view"),
                BotCommand("analyze", "AI analysis: /analyze RELIANCE"),
                BotCommand("alerts", "Recent alerts"),
                BotCommand("settings", "View/modify settings"),
                BotCommand("help", "Show available commands"),
            ]
        )

        logger.info("Telegram bot initialized with command handlers")

    async def start_polling(self) -> None:
        """Start the bot updater. Called during FastAPI lifespan startup."""
        if not self.app:
            raise RuntimeError("Bot not initialized. Call initialize() first.")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot polling started")

    async def stop(self) -> None:
        """Graceful shutdown of the bot."""
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
            logger.info("Telegram bot stopped")

    # ----------------------------------------------------------------
    # Push Notifications (called by portfolio_monitor)
    # ----------------------------------------------------------------

    async def send_alert(self, alert: AlertMessage) -> None:
        """Send an alert to the configured Telegram chat."""
        if not self.app:
            logger.warning("Telegram bot not initialized — cannot send alert")
            return
        text = format_alert_message(alert)
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
        """Send a generic message to the configured chat."""
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

    async def _cmd_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start command."""
        await update.message.reply_text(
            "<b>Stock AI Portfolio Monitor</b>\n\n"
            "I monitor your Groww portfolio and provide AI-powered analysis.\n\n"
            "Use /help to see all available commands.",
            parse_mode="HTML",
        )

    async def _cmd_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /status — quick portfolio P&L summary."""
        snapshot = await db.get_latest_snapshot()
        if not snapshot:
            await update.message.reply_text(
                "No portfolio data yet. Monitoring will start shortly."
            )
            return
        text = format_portfolio_summary(snapshot)
        await update.message.reply_text(text, parse_mode="HTML")

    async def _cmd_portfolio(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /portfolio — detailed per-stock breakdown."""
        snapshot = await db.get_latest_snapshot()
        if not snapshot:
            await update.message.reply_text("No portfolio data available.")
            return
        messages = format_holding_detail(snapshot)
        for msg in messages:
            await update.message.reply_text(msg, parse_mode="HTML")

    async def _cmd_analyze(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /analyze <SYMBOL> — AI analysis for a specific stock."""
        args = context.args
        if not args:
            await update.message.reply_text(
                "Usage: /analyze &lt;SYMBOL&gt;\nExample: /analyze RELIANCE",
                parse_mode="HTML",
            )
            return

        symbol = args[0].upper()
        await update.message.reply_text(f"Analyzing {symbol}... This may take a moment.")

        try:
            analysis = await ai_engine.analyze_stock(symbol)
            await db.save_analysis(analysis)
            text = format_analysis_result(analysis)
            for chunk in self._split_message(text):
                await update.message.reply_text(chunk, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Analysis failed for {symbol}: {e}")
            await update.message.reply_text(f"Analysis failed: {str(e)[:300]}")

    async def _cmd_alerts(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /alerts — show recent alerts."""
        alerts = await db.get_recent_alerts(limit=10)
        if not alerts:
            await update.message.reply_text("No recent alerts.")
            return

        parts = ["<b>Recent Alerts</b>\n"]
        for a in alerts:
            severity = a.get("severity", "INFO")
            title = a.get("title", "Unknown")
            timestamp = a.get("timestamp", "")
            parts.append(f"[{severity}] {title}")
            parts.append(f"  <i>{timestamp}</i>\n")

        text = "\n".join(parts)
        for chunk in self._split_message(text):
            await update.message.reply_text(chunk, parse_mode="HTML")

    async def _cmd_settings(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /settings — view current settings."""
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

    async def _cmd_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /help — list all commands."""
        await update.message.reply_text(
            "<b>Available Commands</b>\n\n"
            "/status - Quick portfolio P&amp;L summary\n"
            "/portfolio - Detailed holdings view\n"
            "/analyze &lt;SYMBOL&gt; - AI analysis for a stock\n"
            "/alerts - Recent alerts\n"
            "/settings - View/modify settings\n"
            "/help - Show this message\n\n"
            "You can also type any question about your portfolio\n"
            "or the market, and I'll analyze it using AI.",
            parse_mode="HTML",
        )

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle free-text messages as AI questions about the portfolio."""
        user_text = update.message.text
        await update.message.reply_text("Thinking...")

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
        """Split long messages to respect Telegram's character limit."""
        if len(text) <= max_length:
            return [text]

        chunks: list[str] = []
        while text:
            if len(text) <= max_length:
                chunks.append(text)
                break
            # Try to split at a newline
            split_point = text.rfind("\n", 0, max_length)
            if split_point == -1:
                split_point = max_length
            chunks.append(text[:split_point])
            text = text[split_point:].lstrip()

        return chunks


# Singleton
telegram_service = TelegramBotService()
