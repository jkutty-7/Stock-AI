"""Pydantic models for portfolio holdings and positions."""

from datetime import datetime

from pydantic import BaseModel


class Holding(BaseModel):
    """Raw holding from Groww API."""

    isin: str
    trading_symbol: str
    quantity: int
    average_price: float
    pledge_quantity: int = 0
    demat_locked_quantity: int = 0
    groww_locked_quantity: int = 0
    repledge_quantity: int = 0
    t1_quantity: int = 0
    demat_free_quantity: int = 0
    corporate_action_additional_quantity: int = 0
    active_demat_transfer_quantity: int = 0


class EnrichedHolding(BaseModel):
    """Holding enriched with live price data and P&L calculations."""

    isin: str
    trading_symbol: str
    quantity: int
    average_price: float
    current_price: float
    day_change_pct: float
    total_invested: float
    current_value: float
    pnl: float
    pnl_pct: float
    day_pnl: float


class Position(BaseModel):
    """Trading position from Groww API."""

    trading_symbol: str
    segment: str
    exchange: str
    product: str
    quantity: int = 0
    credit_quantity: int = 0
    debit_quantity: int = 0
    credit_price: float = 0.0
    debit_price: float = 0.0
    carry_forward_credit_quantity: int = 0
    carry_forward_credit_price: float = 0.0
    carry_forward_debit_quantity: int = 0
    carry_forward_debit_price: float = 0.0
    net_price: float = 0.0
    net_carry_forward_quantity: int = 0
    net_carry_forward_price: float = 0.0
    realised_pnl: float = 0.0
    symbol_isin: str = ""


class PortfolioSnapshot(BaseModel):
    """Complete portfolio state at a point in time."""

    timestamp: datetime
    total_invested: float
    current_value: float
    total_pnl: float
    total_pnl_pct: float
    day_pnl: float
    holdings: list[EnrichedHolding]
    positions: list[Position] = []
