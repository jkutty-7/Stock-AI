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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# Singleton instance — import this throughout the app
settings = Settings()
