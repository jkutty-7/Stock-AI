"""Intraday-specific technical indicators.

Implements Supertrend, Opening Range Breakout (ORB), Central Pivot Range (CPR),
and intraday VWAP with standard-deviation bands.

All functions are pure — they accept lists/dicts and return computed values.
Returns None or empty dicts when insufficient data is available.
"""

from datetime import date, datetime, time
from typing import Optional

import numpy as np

from src.models.intraday import IntradayORBData
from src.models.market import Candle


# ---------------------------------------------------------------------------
# Supertrend
# ---------------------------------------------------------------------------

def compute_supertrend(
    candles: list[Candle],
    period: int = 10,
    multiplier: float = 3.0,
) -> list[dict]:
    """Compute Supertrend indicator on a candle series.

    Supertrend = ATR-based trend-following indicator.
    Direction "UP"  → price is above the band → bullish.
    Direction "DOWN" → price is below the band → bearish.

    Args:
        candles: OHLCV candles, oldest first.
        period: ATR period (default 10).
        multiplier: ATR multiplier for band width (default 3.0).

    Returns:
        List of dicts [{timestamp, close, direction, value, flipped}] aligned
        to input candles from index `period` onward.
        Returns [] if insufficient data (need > period candles).
    """
    if len(candles) < period + 1:
        return []

    highs = np.array([c.high for c in candles], dtype=float)
    lows = np.array([c.low for c in candles], dtype=float)
    closes = np.array([c.close for c in candles], dtype=float)

    # True Range
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])),
    )

    # ATR via Wilder smoothing (same as existing calculate_atr)
    atr = np.empty(len(tr))
    atr[0] = np.mean(tr[:period])
    for i in range(1, len(tr)):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    # Align candles to atr (atr starts at index period of original candles)
    # candles[period:] aligns with atr[period-1:]
    aligned_start = period  # first candle index that has an ATR value
    aligned_candles = candles[aligned_start:]
    aligned_atr = atr[period - 1:]  # atr[period-1] corresponds to candles[period]

    n = len(aligned_candles)
    hl2 = np.array(
        [(c.high + c.low) / 2 for c in aligned_candles], dtype=float
    )
    upper_band = hl2 + multiplier * aligned_atr
    lower_band = hl2 - multiplier * aligned_atr
    aligned_closes = np.array([c.close for c in aligned_candles], dtype=float)

    # Compute final bands with lookback continuity
    final_upper = upper_band.copy()
    final_lower = lower_band.copy()
    for i in range(1, n):
        # Upper band: only tighten (don't let it widen when price is rising)
        if upper_band[i] < final_upper[i - 1] or aligned_closes[i - 1] > final_upper[i - 1]:
            final_upper[i] = upper_band[i]
        else:
            final_upper[i] = final_upper[i - 1]
        # Lower band: only tighten (don't let it drop when price is falling)
        if lower_band[i] > final_lower[i - 1] or aligned_closes[i - 1] < final_lower[i - 1]:
            final_lower[i] = lower_band[i]
        else:
            final_lower[i] = final_lower[i - 1]

    # Direction: starts UP (assume bullish by default)
    directions = ["UP"] * n
    values = np.where(directions[0] == "UP", final_lower, final_upper)
    supertrend_values = np.empty(n)
    supertrend_dirs = ["UP"] * n
    supertrend_values[0] = final_lower[0]

    for i in range(1, n):
        prev_dir = supertrend_dirs[i - 1]
        if prev_dir == "UP":
            if aligned_closes[i] < supertrend_values[i - 1]:
                supertrend_dirs[i] = "DOWN"
                supertrend_values[i] = final_upper[i]
            else:
                supertrend_dirs[i] = "UP"
                supertrend_values[i] = final_lower[i]
        else:  # prev_dir == "DOWN"
            if aligned_closes[i] > supertrend_values[i - 1]:
                supertrend_dirs[i] = "UP"
                supertrend_values[i] = final_lower[i]
            else:
                supertrend_dirs[i] = "DOWN"
                supertrend_values[i] = final_upper[i]

    result = []
    for i, candle in enumerate(aligned_candles):
        flipped = i > 0 and supertrend_dirs[i] != supertrend_dirs[i - 1]
        result.append({
            "timestamp": candle.timestamp,
            "close": float(aligned_closes[i]),
            "direction": supertrend_dirs[i],
            "value": float(round(supertrend_values[i], 2)),
            "flipped": flipped,
        })

    return result


def get_supertrend_signal(
    candles: list[Candle],
    period: int = 10,
    multiplier: float = 3.0,
) -> dict:
    """Convenience wrapper — returns only the latest Supertrend state.

    Returns:
        {direction, value, flipped_at, flipped} or {direction: "UNKNOWN"} if insufficient data.
    """
    series = compute_supertrend(candles, period, multiplier)
    if not series:
        return {"direction": "UNKNOWN", "value": None, "flipped": False, "flipped_at": None}

    latest = series[-1]
    flipped_at = latest["timestamp"] if latest["flipped"] else None

    # Find when last flip happened if not in latest candle
    if not latest["flipped"]:
        for entry in reversed(series[:-1]):
            if entry["flipped"]:
                flipped_at = entry["timestamp"]
                break

    return {
        "direction": latest["direction"],
        "value": latest["value"],
        "flipped": latest["flipped"],
        "flipped_at": flipped_at.isoformat() if flipped_at else None,
    }


# ---------------------------------------------------------------------------
# Opening Range Breakout (ORB)
# ---------------------------------------------------------------------------

_MARKET_OPEN_TIME = time(9, 15)
_ORB_END_TIME = time(9, 30)  # exclusive — first 15 minutes = 9:15 to 9:29


def compute_opening_range(
    candles_today: list[Candle],
    symbol: str,
    trading_date: Optional[date] = None,
    orb_minutes: int = 15,
) -> Optional[IntradayORBData]:
    """Compute Opening Range Breakout from today's 1-minute candles.

    Args:
        candles_today: 1-minute candles for today (any window — will filter).
        symbol: Trading symbol.
        trading_date: Date for the ORB (defaults to today).
        orb_minutes: Duration of opening range in minutes (default 15).

    Returns:
        IntradayORBData or None if fewer than orb_minutes candles found.
    """
    if trading_date is None:
        trading_date = datetime.now().date()

    # Filter to opening range window: 9:15 AM → 9:15 + orb_minutes
    orb_end = time(
        _MARKET_OPEN_TIME.hour,
        _MARKET_OPEN_TIME.minute + orb_minutes,
    )
    orb_candles = [
        c for c in candles_today
        if _MARKET_OPEN_TIME <= c.timestamp.time() < orb_end
    ]

    if len(orb_candles) < 1:
        return None

    orb_high = max(c.high for c in orb_candles)
    orb_low = min(c.low for c in orb_candles)
    volume_first15 = sum(c.volume for c in orb_candles)
    orb_range_pct = (orb_high - orb_low) / orb_low * 100 if orb_low > 0 else 0.0

    return IntradayORBData(
        symbol=symbol,
        date=trading_date,
        orb_high=round(orb_high, 2),
        orb_low=round(orb_low, 2),
        orb_range_pct=round(orb_range_pct, 3),
        volume_first15=volume_first15,
    )


def check_orb_breakout(
    current_price: float,
    orb: IntradayORBData,
    breakout_buffer_pct: float = 0.1,
) -> dict:
    """Check whether price has broken above ORB high or below ORB low.

    Args:
        current_price: Latest LTP.
        orb: Opening range data.
        breakout_buffer_pct: Require price to exceed ORB by this % to confirm (default 0.1%).

    Returns:
        {breakout: bool, direction: "UP"|"DOWN"|"NONE", strength_pct: float}
    """
    buffer_up = orb.orb_high * (1 + breakout_buffer_pct / 100)
    buffer_down = orb.orb_low * (1 - breakout_buffer_pct / 100)

    if current_price >= buffer_up:
        strength = (current_price - orb.orb_high) / orb.orb_high * 100
        return {"breakout": True, "direction": "UP", "strength_pct": round(strength, 3)}
    elif current_price <= buffer_down:
        strength = (orb.orb_low - current_price) / orb.orb_low * 100
        return {"breakout": True, "direction": "DOWN", "strength_pct": round(strength, 3)}
    else:
        return {"breakout": False, "direction": "NONE", "strength_pct": 0.0}


# ---------------------------------------------------------------------------
# Central Pivot Range (CPR)
# ---------------------------------------------------------------------------

def compute_cpr(
    prev_high: float,
    prev_low: float,
    prev_close: float,
) -> dict:
    """Compute Central Pivot Range from previous day's H/L/C.

    CPR is used as a daily bias indicator:
    - Wide CPR (tc far from bc) → range-bound day expected
    - Narrow CPR → trending day expected
    - Price above tc → bullish bias; below bc → bearish bias

    Returns:
        {pivot, bc, tc, r1, r2, r3, s1, s2, s3, cpr_width_pct}
    """
    pivot = (prev_high + prev_low + prev_close) / 3
    bc = (prev_high + prev_low) / 2       # Bottom Central
    tc = 2 * pivot - bc                   # Top Central (tc > bc always)

    r1 = 2 * pivot - prev_low
    r2 = pivot + (prev_high - prev_low)
    r3 = prev_high + 2 * (pivot - prev_low)

    s1 = 2 * pivot - prev_high
    s2 = pivot - (prev_high - prev_low)
    s3 = prev_low - 2 * (prev_high - pivot)

    cpr_width_pct = abs(tc - bc) / pivot * 100 if pivot > 0 else 0.0

    return {
        "pivot": round(pivot, 2),
        "bc": round(bc, 2),
        "tc": round(tc, 2),
        "r1": round(r1, 2),
        "r2": round(r2, 2),
        "r3": round(r3, 2),
        "s1": round(s1, 2),
        "s2": round(s2, 2),
        "s3": round(s3, 2),
        "cpr_width_pct": round(cpr_width_pct, 3),
        "bias": (
            "BULLISH" if prev_close > tc
            else "BEARISH" if prev_close < bc
            else "NEUTRAL"
        ),
    }


# ---------------------------------------------------------------------------
# Intraday VWAP with Standard-Deviation Bands
# ---------------------------------------------------------------------------

def compute_vwap_bands(
    candles_today: list[Candle],
    std_multiplier: float = 1.0,
) -> dict:
    """Compute intraday VWAP and ±1 standard-deviation bands.

    VWAP resets at market open each day (9:15 AM IST).
    Uses typical price = (H + L + C) / 3 for each candle.

    Args:
        candles_today: Intraday candles from 9:15 AM (1-min or 5-min), oldest first.
        std_multiplier: SD multiplier for bands (default 1.0).

    Returns:
        {vwap, upper_band, lower_band, std_dev, candles_used} or zeros dict if no data.
    """
    empty = {"vwap": 0.0, "upper_band": 0.0, "lower_band": 0.0, "std_dev": 0.0, "candles_used": 0}

    if not candles_today:
        return empty

    typical_prices = np.array(
        [(c.high + c.low + c.close) / 3 for c in candles_today], dtype=float
    )
    volumes = np.array([c.volume for c in candles_today], dtype=float)
    total_volume = np.sum(volumes)

    if total_volume == 0:
        return empty

    vwap = float(np.sum(typical_prices * volumes) / total_volume)

    # VWAP standard deviation (volume-weighted)
    variance = np.sum(volumes * (typical_prices - vwap) ** 2) / total_volume
    std_dev = float(np.sqrt(variance))

    return {
        "vwap": round(vwap, 2),
        "upper_band": round(vwap + std_multiplier * std_dev, 2),
        "lower_band": round(vwap - std_multiplier * std_dev, 2),
        "std_dev": round(std_dev, 2),
        "candles_used": len(candles_today),
    }


def check_vwap_cross(
    prev_price: float,
    current_price: float,
    vwap: float,
) -> Optional[str]:
    """Detect if price just crossed VWAP.

    Returns:
        "BULLISH_CROSS" — price crossed above VWAP
        "BEARISH_CROSS" — price crossed below VWAP
        None — no cross
    """
    if vwap <= 0:
        return None
    if prev_price < vwap and current_price >= vwap:
        return "BULLISH_CROSS"
    if prev_price > vwap and current_price <= vwap:
        return "BEARISH_CROSS"
    return None
