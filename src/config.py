"""Centralized application configuration loaded from environment variables."""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    # --- Groww Trading API ---
    groww_api_key: str = Field(description="Groww API key or TOTP token")
    groww_totp_secret: str = Field(description="TOTP secret for generating auth codes")

    # --- Anthropic / Claude ---
    anthropic_api_key: str = Field(description="Anthropic API key")
    claude_model: str = Field(default="claude-sonnet-4-20250514", description="Claude model ID")
    claude_max_tokens: int = Field(default=4096, description="Max tokens for Claude responses")

    # --- Telegram ---
    telegram_bot_token: str = Field(description="Telegram bot token from BotFather")
    telegram_chat_id: str = Field(description="Primary user chat ID for push notifications")
    telegram_webhook_url: str = Field(default="", description="Public HTTPS URL for webhook (e.g. https://your-app.onrender.com). Leave empty to use polling.")

    # --- MongoDB ---
    mongodb_uri: str = Field(default="mongodb://localhost:27017", description="MongoDB connection URI")
    mongodb_database: str = Field(default="stock_ai", description="MongoDB database name")

    # --- Scheduler ---
    monitor_interval_minutes: int = Field(default=15, description="Monitoring cycle interval")
    market_open_hour: int = Field(default=9, description="Market open hour (IST)")
    market_open_minute: int = Field(default=15, description="Market open minute (IST)")
    market_close_hour: int = Field(default=15, description="Market close hour (IST)")
    market_close_minute: int = Field(default=30, description="Market close minute (IST)")

    # --- Alert Thresholds ---
    pnl_alert_threshold_pct: float = Field(
        default=5.0, description="Alert if any stock moves more than this % in a day"
    )
    portfolio_alert_threshold_pct: float = Field(
        default=3.0, description="Alert if overall portfolio moves more than this %"
    )

    # --- Logging ---
    log_level: str = Field(default="INFO", description="Logging level")
    log_json: bool = Field(default=False, description="Emit logs as JSON (for log aggregators)")
    log_file: str = Field(default="stock_ai.log", description="Log file path")

    # --- Caching & Resilience ---
    cache_ttl_seconds: int = Field(default=8, description="In-memory quote cache TTL in seconds")
    max_retry_attempts: int = Field(default=3, description="Max Groww API retry attempts")
    circuit_breaker_threshold: int = Field(default=5, description="Consecutive failures before circuit opens")
    circuit_breaker_reset_seconds: int = Field(default=60, description="Seconds before circuit half-opens")

    # --- Alert Cooldown ---
    alert_cooldown_seconds: int = Field(default=300, description="Suppress duplicate symbol alerts within this window")

    # --- REST API ---
    api_key: str = Field(default="", description="Optional X-API-Key header auth (empty = disabled)")

    # --- Micro Monitor ---
    micro_poll_interval_seconds: int = Field(default=10, description="Price polling interval for fast signals")
    micro_velocity_threshold_pct: float = Field(default=0.5, description="% change per tick to fire micro-alert")
    micro_consecutive_ticks: int = Field(default=3, description="Consecutive same-direction ticks to fire micro-alert")

    # --- Screener ---
    screener_symbols_file: str = Field(default="nse_symbols.json", description="NSE universe file for screener")
    screener_top_n: int = Field(default=10, description="Top N candidates to send to Claude for ranking")
    screener_min_liquidity: int = Field(default=500000, description="Minimum average daily volume (shares) to screen stocks")
    screener_liquidity_lookback_days: int = Field(default=30, description="Days to compute average volume for liquidity filter")

    # --- Signal Outcome Tracking ---
    outcome_auto_track_enabled: bool = Field(default=True, description="Enable automatic outcome tracking from holdings")
    outcome_auto_track_interval_hours: int = Field(default=6, description="Hours between auto-tracking job runs")
    outcome_min_confidence_track: float = Field(default=0.6, description="Minimum signal confidence to track outcomes")

    # --- Stop-Loss Monitoring ---
    stop_loss_enabled: bool = Field(default=True, description="Enable real-time stop-loss breach monitoring")
    stop_loss_grace_pct: float = Field(default=0.1, description="Grace % below stop-loss to avoid noise (0.1 = 0.1%)")

    # --- Portfolio Drawdown Breaker ---
    drawdown_breaker_enabled: bool = Field(default=True, description="Enable portfolio drawdown circuit breaker")
    drawdown_breaker_threshold_pct: float = Field(default=8.0, description="Drawdown % threshold to trigger breaker (default 8%)")
    drawdown_breaker_auto_reset: bool = Field(default=True, description="Auto-reset breaker when drawdown recovers to 50% of threshold")

    # --- Market Regime Classification ---
    regime_classification_enabled: bool = Field(default=True, description="Enable daily market regime classification")
    regime_index_symbol: str = Field(default="NIFTY 50", description="Index symbol for regime classification")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# Singleton instance — import this throughout the app
settings = Settings()
