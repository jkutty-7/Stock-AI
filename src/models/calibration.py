"""Pydantic models for V3.0 — Signal Calibration, Capital Allocation, and Event Risk."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


# ─── Phase 3C: Event Risk ─────────────────────────────────────────────────────


class CorporateEvent(BaseModel):
    """A corporate event from the NSE calendar that may affect trading decisions."""

    symbol: str
    event_type: str  # BOARD_MEETING_RESULTS | DIVIDEND_EX | BONUS_EX | SPLIT | AGM | BUYBACK | RIGHTS | OTHER
    event_date: date
    description: str
    source: str = "NSE"
    scraped_at: datetime = Field(default_factory=datetime.now)


class EventRisk(BaseModel):
    """Result of checking event risk before a trade entry."""

    symbol: str
    blocked: bool
    reason: Optional[str] = None
    event_date: Optional[date] = None
    event_type: Optional[str] = None
    days_until_event: Optional[int] = None


# ─── Phase 3A: Signal Calibration ────────────────────────────────────────────


class CalibrationBucket(BaseModel):
    """Win rate statistics for a specific confidence range bucket."""

    bucket: str              # e.g., "0.7-0.8"
    count: int               # Total signals in this bucket
    wins: int
    losses: int
    win_rate: float          # Empirical win rate (wins / count)
    calibration_error: float # |bucket_midpoint - actual_win_rate|


class PatternStats(BaseModel):
    """Win rate for a specific combination of reasoning tags."""

    pattern_key: str         # e.g., "MACD_bullish_crossover+RSI_oversold"
    tags: list[str]
    count: int
    wins: int
    win_rate: float
    avg_pnl_pct: float
    computed_at: datetime = Field(default_factory=datetime.now)


class RegimeStats(BaseModel):
    """Win rate per market regime."""

    regime: str              # BULL_STRONG | BULL_WEAK | SIDEWAYS | BEAR_WEAK | BEAR_STRONG
    count: int
    wins: int
    win_rate: float
    avg_pnl_pct: float
    avg_hold_hours: Optional[float] = None
    computed_at: datetime = Field(default_factory=datetime.now)


class CalibrationData(BaseModel):
    """Complete signal calibration snapshot for a given lookback period."""

    computed_at: datetime = Field(default_factory=datetime.now)
    lookback_days: int
    overall_win_rate: float
    total_signals_analyzed: int
    buckets: list[CalibrationBucket]
    best_bucket: Optional[str] = None      # Bucket string with highest win rate
    worst_bucket: Optional[str] = None     # Bucket string with lowest win rate
    is_current: bool = True


# ─── Phase 3B: Capital Allocation ────────────────────────────────────────────


class KellyResult(BaseModel):
    """Kelly Criterion position sizing recommendation."""

    symbol: str
    kelly_fraction: float           # e.g., 0.08 = 8% of portfolio
    recommended_value_rs: float     # Rs. to allocate
    recommended_qty: int            # Share quantity
    max_risk_rs: float              # Max Rs. at risk for this trade
    win_rate_used: float            # Calibrated win rate used
    avg_win_pct_used: float
    avg_loss_pct_used: float
    note: Optional[str] = None      # e.g., "Default win rate used — insufficient data"


class CorrelationCheck(BaseModel):
    """Result of checking correlation with existing holdings."""

    symbol: str
    blocked: bool
    correlated_with: Optional[str] = None
    correlation: Optional[float] = None
    message: Optional[str] = None


class SectorCheck(BaseModel):
    """Result of checking sector concentration limits."""

    symbol: str
    sector: Optional[str]
    blocked: bool
    current_sector_pct: float
    after_sector_pct: float
    message: Optional[str] = None


class BetaEntry(BaseModel):
    """Beta of a single holding vs the market index."""

    symbol: str
    beta: float
    weight: float   # Portfolio weight (0.0 to 1.0)


class BetaReport(BaseModel):
    """Portfolio beta snapshot."""

    computed_at: datetime = Field(default_factory=datetime.now)
    index_symbol: str = "NIFTY 50"
    lookback_days: int
    portfolio_beta: float
    holdings: list[BetaEntry]
    interpretation: str  # "Aggressive (beta > 1.2)" | "Market-like" | "Defensive (beta < 0.8)"


class AllocationReport(BaseModel):
    """Full portfolio capital allocation snapshot."""

    computed_at: datetime = Field(default_factory=datetime.now)
    portfolio_value: float
    portfolio_beta: Optional[float] = None
    sector_weights: dict[str, float]    # {"IT": 0.28, "Financial Services": 0.35}
    concentrated_sectors: list[str]     # Sectors above SECTOR_MAX_PCT
    high_correlation_pairs: list[dict]  # [{"a": "TCS", "b": "INFY", "corr": 0.91}]
    total_holdings: int
