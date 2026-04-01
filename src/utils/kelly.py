"""Kelly Criterion position sizing utilities (Phase 3B).

Implements half-Kelly for conservative position sizing in non-professional
trading contexts. Kelly fraction is clamped to [min_pct, max_pct] to prevent
extreme allocations from low-data situations.

Usage:
    from src.utils.kelly import compute_half_kelly, compute_position_size

    fraction = compute_half_kelly(win_rate=0.60, avg_win_pct=0.08, avg_loss_pct=0.04)
    qty = compute_position_size(fraction, portfolio_value=500_000, price=2450.0)
"""

from math import floor


def compute_half_kelly(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    kelly_multiplier: float = 0.5,
    min_fraction: float = 0.01,
    max_fraction: float = 0.20,
) -> float:
    """Compute the half-Kelly optimal fraction of portfolio to allocate.

    Kelly formula: f = (W * b - L) / b
    where:
        W = win_rate
        L = loss_rate (1 - win_rate)
        b = avg_win_pct / avg_loss_pct  (win/loss ratio)

    Args:
        win_rate:         Calibrated win probability (0.0-1.0).
        avg_win_pct:      Average winning trade gain as a fraction (e.g., 0.08 = 8%).
        avg_loss_pct:     Average losing trade loss as a fraction (e.g., 0.04 = 4%).
        kelly_multiplier: Fraction of full Kelly to use (default 0.5 = half-Kelly).
        min_fraction:     Floor on returned fraction (default 1%).
        max_fraction:     Cap on returned fraction (default 20%).

    Returns:
        Portfolio fraction to allocate (e.g., 0.08 = 8%).
    """
    if avg_loss_pct <= 0 or avg_win_pct <= 0:
        return min_fraction

    loss_rate = 1.0 - win_rate
    b = avg_win_pct / avg_loss_pct  # win/loss ratio

    full_kelly = (win_rate * b - loss_rate) / b

    # Full Kelly can be negative (edge is against us) — return minimum
    if full_kelly <= 0:
        return min_fraction

    half_kelly = full_kelly * kelly_multiplier
    return max(min_fraction, min(max_fraction, half_kelly))


def compute_position_size(
    kelly_fraction: float,
    portfolio_value: float,
    price: float,
    lot_size: int = 1,
) -> int:
    """Compute share quantity from Kelly fraction.

    Args:
        kelly_fraction:  Output of compute_half_kelly() (e.g., 0.08).
        portfolio_value: Total portfolio value in Rs.
        price:           Current share price in Rs.
        lot_size:        Minimum lot size (default 1 share for equities).

    Returns:
        Number of shares to buy (floored to lot_size boundary, minimum 0).
    """
    if price <= 0 or portfolio_value <= 0:
        return 0

    position_value = portfolio_value * kelly_fraction
    raw_qty = floor(position_value / price)
    # Align to lot_size
    qty = max(0, (raw_qty // lot_size) * lot_size)
    return qty
