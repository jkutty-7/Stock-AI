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

    # --- Event Risk Filter (Phase 3C) ---
    event_risk_enabled: bool = Field(default=True, description="Block trade entries near corporate events (results, dividends, etc.)")
    event_risk_lookback_days: int = Field(default=3, description="Block entries this many days before an event")

    # --- Signal Calibration (Phase 3A) ---
    calibration_enabled: bool = Field(default=True, description="Enable nightly confidence calibration from signal outcomes")
    calibration_lookback_days: int = Field(default=90, description="Days of closed signal outcomes to analyze")
    calibration_min_samples: int = Field(default=5, description="Minimum signals per bucket to trust empirical win rate")
    calibration_refresh_hour: int = Field(default=20, description="Hour (IST) to run nightly calibration job (default 8 PM)")

    # --- Capital Allocation / Kelly Criterion (Phase 3B) ---
    capital_allocation_enabled: bool = Field(default=True, description="Enable Kelly-optimal position sizing")
    kelly_fraction: float = Field(default=0.5, description="Kelly multiplier: 0.5 = half-Kelly (conservative), 1.0 = full Kelly")
    kelly_max_position_pct: float = Field(default=20.0, description="Never allocate more than this % of portfolio to one stock")
    kelly_min_position_pct: float = Field(default=1.0, description="Minimum meaningful position size as % of portfolio")
    correlation_guard_enabled: bool = Field(default=True, description="Block new positions highly correlated with existing holdings")
    correlation_threshold: float = Field(default=0.80, description="Pearson correlation above this blocks new entry (0.0–1.0)")
    sector_cap_enabled: bool = Field(default=True, description="Limit maximum allocation to any single sector")
    sector_max_pct: float = Field(default=30.0, description="Maximum % allocation to any single GICS sector")

    # --- Intraday Trading ---
    intraday_enabled: bool = Field(default=True, description="Enable intraday trading module")
    intraday_poll_interval_seconds: int = Field(default=60, description="Intraday monitor polling interval (seconds)")
    intraday_max_positions: int = Field(default=3, description="Max concurrent intraday (MIS) positions")
    intraday_risk_per_trade_rs: float = Field(default=500.0, description="Rs. to risk per intraday trade")
    intraday_max_daily_loss_rs: float = Field(default=1500.0, description="Daily intraday loss limit (triggers breaker)")
    intraday_max_position_value: float = Field(default=50000.0, description="Hard cap on total value per intraday position")
    intraday_no_entry_after_hour: int = Field(default=14, description="No new entries after this hour (14 = 2 PM)")
    intraday_no_entry_after_minute: int = Field(default=30, description="No new entries after this minute")
    intraday_hard_exit_hour: int = Field(default=15, description="Hard exit alert hour")
    intraday_hard_exit_minute: int = Field(default=15, description="Hard exit alert minute (15 = 3:15 PM)")
    intraday_orb_minutes: int = Field(default=15, description="Opening range duration in minutes")
    intraday_supertrend_period: int = Field(default=10, description="Supertrend ATR period")
    intraday_supertrend_multiplier: float = Field(default=3.0, description="Supertrend ATR multiplier")
    intraday_min_gap_pct: float = Field(default=0.5, description="Minimum gap% to include in pre-market watchlist")
    intraday_watchlist_size: int = Field(default=20, description="Max symbols in daily intraday watchlist")
    intraday_min_breakout_confirm_ticks: int = Field(default=3, description="Min MicroMonitor consecutive ticks to confirm intraday breakout")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# Singleton instance — import this throughout the app
settings = Settings()
