"""Pydantic models for AI analysis results, trade signals, and alerts."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    """Recommended trade action."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    STRONG_BUY = "STRONG_BUY"
    STRONG_SELL = "STRONG_SELL"
    WATCH = "WATCH"


class AnalysisType(str, Enum):
    """Type of analysis performed."""

    PORTFOLIO_HEALTH = "portfolio_health"
    STOCK_ANALYSIS = "stock_analysis"
    MARKET_OVERVIEW = "market_overview"
    ALERT_CHECK = "alert_check"
    SCREENER = "screener"


class TradeSignal(BaseModel):
    """A specific buy/sell/hold recommendation for a stock."""

    trading_symbol: str
    action: ActionType
    confidence: float = Field(ge=0.0, le=1.0)
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    reasoning: str
    risk_level: str = "MEDIUM"  # LOW, MEDIUM, HIGH
    # V2 additions
    risk_reward_ratio: Optional[float] = None
    reasoning_tags: list[str] = Field(default_factory=list)
    time_horizon: Optional[str] = None  # intraday | swing_3-5d | positional_2-4w
    micro_signal_context: Optional[str] = None
    expires_at: Optional[datetime] = None


class AnalysisResult(BaseModel):
    """Complete AI analysis output."""

    analysis_type: AnalysisType
    timestamp: datetime
    summary: str
    signals: list[TradeSignal] = []
    market_sentiment: Optional[str] = None  # BULLISH, BEARISH, NEUTRAL
    key_observations: list[str] = []
    risks: list[str] = []
    raw_response: Optional[str] = None  # Full Claude response for debugging


class AlertMessage(BaseModel):
    """Alert to be sent via Telegram."""

    timestamp: datetime
    alert_type: str  # PNL_THRESHOLD, AI_SIGNAL, MARKET_OPEN, MARKET_CLOSE, SYSTEM_ERROR
    severity: str  # INFO, WARNING, CRITICAL
    title: str
    body: str
    trading_symbol: Optional[str] = None
    signal: Optional[TradeSignal] = None
