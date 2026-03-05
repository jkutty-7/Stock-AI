"""Pydantic models for market data and technical indicators."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class Quote(BaseModel):
    """Real-time stock quote."""

    trading_symbol: str
    exchange: str
    last_price: float
    open: float
    high: float
    low: float
    close: float  # previous close
    volume: int = 0
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    change: float = 0.0  # last_price - close
    change_pct: float = 0.0
    bid_price: float = 0.0
    bid_quantity: int = 0
    offer_price: float = 0.0
    offer_quantity: int = 0
    total_buy_quantity: int = 0
    total_sell_quantity: int = 0
    upper_circuit_limit: Optional[float] = None
    lower_circuit_limit: Optional[float] = None
    last_trade_time: Optional[str] = None


class Candle(BaseModel):
    """OHLCV candle data point."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class TechnicalIndicators(BaseModel):
    """Computed technical indicators for a stock."""

    trading_symbol: str

    # RSI
    rsi_14: Optional[float] = None

    # MACD
    macd_line: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None

    # Simple Moving Averages
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None

    # Exponential Moving Averages
    ema_12: Optional[float] = None
    ema_26: Optional[float] = None

    # Bollinger Bands
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_width: Optional[float] = None
