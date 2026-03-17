"""Pydantic models for intraday trading module."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class IntradaySetup(BaseModel):
    """Pre-market setup for a candidate intraday stock."""

    symbol: str
    scan_date: date
    gap_pct: float                  # % gap from prev close to today's open (+ve = gap up)
    gap_type: str                   # GAP_UP | GAP_DOWN | FLAT
    prev_close: float
    today_open: float
    # Central Pivot Range levels (computed from yesterday's H/L/C)
    cpr_pivot: float
    cpr_bc: float                   # Bottom Central = (H + L) / 2
    cpr_tc: float                   # Top Central = 2 * pivot - bc
    cpr_r1: float                   # Resistance 1
    cpr_r2: float                   # Resistance 2
    cpr_s1: float                   # Support 1
    cpr_s2: float                   # Support 2
    rank_score: float = 0.0         # 0–100, higher = stronger setup
    watchlist_reason: str = ""      # e.g. "GAP_UP_5.2%", "STRONG_VOLUME"


class IntradayORBData(BaseModel):
    """Opening Range Breakout data — computed after first 15 minutes."""

    symbol: str
    date: date
    orb_high: float                 # Highest high across 9:15–9:29 candles
    orb_low: float                  # Lowest low across 9:15–9:29 candles
    orb_range_pct: float            # (orb_high - orb_low) / orb_low * 100
    volume_first15: int             # Total volume in opening range window
    computed_at: datetime = Field(default_factory=datetime.now)


class IntradayPosition(BaseModel):
    """An active or closed intraday (MIS) position tracked by the system."""

    id: str                             # UUID
    symbol: str
    entry_price: float
    entry_time: datetime
    quantity: int
    direction: str                      # LONG | SHORT
    stop_loss: float
    target: float
    trailing_sl: Optional[float] = None # Moves to breakeven once 1% in profit
    current_price: float = 0.0
    current_pnl: float = 0.0            # (current - entry) * qty for LONG
    current_pnl_pct: float = 0.0
    status: str = "OPEN"                # OPEN | CLOSED | HARD_EXITED | STOP_HIT | TARGET_HIT
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_reason: Optional[str] = None   # TARGET_HIT | STOP_HIT | TRAILING_SL | HARD_EXIT | MANUAL
    entry_trigger: str = ""             # ORB_BREAKOUT | VWAP_CROSS | SUPERTREND_FLIP
    risk_amount: float = 0.0            # Rs. risked on this trade
    signal_id: Optional[str] = None    # Linked TradeSignal id for outcome tracking

    def update_pnl(self, current_price: float) -> None:
        """Recompute live P&L from current price."""
        self.current_price = current_price
        if self.direction == "LONG":
            self.current_pnl = (current_price - self.entry_price) * self.quantity
        else:
            self.current_pnl = (self.entry_price - current_price) * self.quantity
        if self.entry_price > 0:
            pnl_per_share = (
                current_price - self.entry_price
                if self.direction == "LONG"
                else self.entry_price - current_price
            )
            self.current_pnl_pct = (pnl_per_share / self.entry_price) * 100


class IntradayDailyReport(BaseModel):
    """End-of-day intraday P&L summary."""

    date: date
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    breakevens: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0          # As % of capital deployed today
    max_win: float = 0.0
    max_loss: float = 0.0
    best_trade: Optional[str] = None    # "RELIANCE +₹420 (1.8%)"
    worst_trade: Optional[str] = None
    daily_loss_breaker_triggered: bool = False
    capital_deployed: float = 0.0       # Total entry value of all trades today
