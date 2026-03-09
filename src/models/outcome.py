"""Signal outcome tracking models for validating AI prediction accuracy."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from src.models.analysis import ActionType


class SignalOutcome(BaseModel):
    """Tracks the actual outcome of a trade signal from entry to exit.

    This model stores the real-world results of AI-generated signals,
    enabling win rate calculation, confidence score calibration, and
    signal quality validation over time.
    """

    # Signal reference
    signal_id: str = Field(description="Reference to trade_signals._id")
    trading_symbol: str
    action: ActionType
    signal_timestamp: datetime

    # Entry tracking
    entry_price: float = Field(description="Actual entry price if filled, or signal price")
    entry_timestamp: datetime
    entry_method: str = Field(
        default="AUTO_TRACKED",
        description="AUTO_TRACKED | MANUAL | ESTIMATED",
    )

    # Exit tracking
    exit_price: Optional[float] = None
    exit_timestamp: Optional[datetime] = None
    exit_reason: Optional[str] = Field(
        default=None,
        description="TARGET_HIT | STOP_LOSS | TIMEOUT | MANUAL",
    )

    # Outcome metrics
    status: str = Field(default="OPEN", description="OPEN | CLOSED | EXPIRED | CANCELLED")
    pnl_points: Optional[float] = None
    pnl_pct: Optional[float] = None
    win_loss: Optional[str] = Field(default=None, description="WIN | LOSS | BREAKEVEN | None")
    hold_duration_hours: Optional[float] = None

    # Signal quality metrics
    original_confidence: float = Field(ge=0.0, le=1.0)
    original_target: Optional[float] = None
    original_stop_loss: Optional[float] = None
    target_achieved: Optional[bool] = None
    stop_loss_hit: Optional[bool] = None

    timestamp: datetime = Field(default_factory=datetime.now)
    notes: Optional[str] = None

    def compute_metrics(self) -> None:
        """Compute P&L metrics and win/loss classification when exit occurs."""
        if self.exit_price is None or self.entry_price == 0:
            return

        # Compute P&L based on action
        if self.action in [ActionType.BUY, ActionType.STRONG_BUY]:
            self.pnl_points = self.exit_price - self.entry_price
        elif self.action in [ActionType.SELL, ActionType.STRONG_SELL]:
            self.pnl_points = self.entry_price - self.exit_price
        else:
            self.pnl_points = 0.0

        self.pnl_pct = (self.pnl_points / self.entry_price) * 100

        # Classify win/loss
        if self.pnl_pct > 0.5:
            self.win_loss = "WIN"
        elif self.pnl_pct < -0.5:
            self.win_loss = "LOSS"
        else:
            self.win_loss = "BREAKEVEN"

        # Check target/stop-loss achievement
        if self.original_target and self.action in [ActionType.BUY, ActionType.STRONG_BUY]:
            self.target_achieved = self.exit_price >= self.original_target
        elif self.original_target and self.action in [ActionType.SELL, ActionType.STRONG_SELL]:
            self.target_achieved = self.exit_price <= self.original_target

        if self.original_stop_loss and self.action in [ActionType.BUY, ActionType.STRONG_BUY]:
            self.stop_loss_hit = self.exit_price <= self.original_stop_loss
        elif self.original_stop_loss and self.action in [ActionType.SELL, ActionType.STRONG_SELL]:
            self.stop_loss_hit = self.exit_price >= self.original_stop_loss

        # Compute hold duration
        if self.exit_timestamp:
            duration = self.exit_timestamp - self.entry_timestamp
            self.hold_duration_hours = duration.total_seconds() / 3600

        self.status = "CLOSED"
        self.timestamp = datetime.now()


class SignalStatistics(BaseModel):
    """Aggregated signal performance statistics for a time period."""

    period_days: int
    total_signals: int
    open_signals: int
    closed_signals: int

    # Win/Loss metrics
    wins: int
    losses: int
    breakevens: int
    win_rate: float = Field(description="Percentage of winning trades")

    # P&L metrics
    avg_pnl_pct: float
    total_pnl_pct: float
    max_win_pct: float
    max_loss_pct: float

    # Confidence correlation
    avg_confidence_wins: float
    avg_confidence_losses: float
    confidence_correlation: float = Field(
        description="Correlation between confidence and actual outcomes"
    )

    # Target/Stop-loss hit rates
    target_hit_rate: Optional[float] = None
    stop_loss_hit_rate: Optional[float] = None

    # Duration metrics
    avg_hold_hours: Optional[float] = None
