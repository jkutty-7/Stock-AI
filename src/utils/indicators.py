"""Technical indicator calculations using numpy.

All functions are pure — they take a list of closing prices and return
computed indicator values. Returns None if insufficient data.
"""

from typing import Optional

import numpy as np


def compute_rsi(closes: list[float], period: int = 14) -> Optional[float]:
    """Compute Relative Strength Index (RSI).

    Uses the smoothed/Wilder's method for averaging gains and losses.

    Args:
        closes: List of closing prices (oldest first).
        period: RSI lookback period (default: 14).

    Returns:
        RSI value (0-100) or None if insufficient data.
    """
    if len(closes) < period + 1:
        return None

    prices = np.array(closes, dtype=float)
    deltas = np.diff(prices)

    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # Initial average using simple mean
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    # Smoothed (Wilder's) moving average for remaining
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return float(round(100.0 - (100.0 / (1.0 + rs)), 2))


def compute_sma(closes: list[float], period: int) -> Optional[float]:
    """Compute Simple Moving Average (latest value).

    Args:
        closes: List of closing prices (oldest first).
        period: SMA lookback period.

    Returns:
        SMA value or None if insufficient data.
    """
    if len(closes) < period:
        return None
    return float(round(np.mean(closes[-period:]), 2))


def compute_ema(closes: list[float], period: int) -> Optional[float]:
    """Compute Exponential Moving Average (latest value).

    Args:
        closes: List of closing prices (oldest first).
        period: EMA lookback period.

    Returns:
        EMA value or None if insufficient data.
    """
    if len(closes) < period:
        return None

    prices = np.array(closes, dtype=float)
    multiplier = 2.0 / (period + 1)

    # Start with SMA for the first 'period' values
    ema = np.mean(prices[:period])

    # Apply EMA formula for remaining values
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema

    return float(round(ema, 2))


def compute_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict[str, Optional[float]]:
    """Compute MACD (Moving Average Convergence Divergence).

    Args:
        closes: List of closing prices (oldest first).
        fast: Fast EMA period (default: 12).
        slow: Slow EMA period (default: 26).
        signal: Signal line EMA period (default: 9).

    Returns:
        Dict with 'macd_line', 'signal_line', and 'histogram'.
    """
    result: dict[str, Optional[float]] = {
        "macd_line": None,
        "signal_line": None,
        "histogram": None,
    }

    if len(closes) < slow + signal:
        return result

    prices = np.array(closes, dtype=float)

    # Compute full EMA series for fast and slow
    fast_ema = _ema_series(prices, fast)
    slow_ema = _ema_series(prices, slow)

    if fast_ema is None or slow_ema is None:
        return result

    # MACD line = Fast EMA - Slow EMA (aligned to slow EMA length)
    min_len = min(len(fast_ema), len(slow_ema))
    macd_line = fast_ema[-min_len:] - slow_ema[-min_len:]

    # Signal line = EMA of MACD line
    if len(macd_line) < signal:
        return result

    signal_ema = _ema_series(macd_line, signal)
    if signal_ema is None:
        return result

    result["macd_line"] = float(round(macd_line[-1], 4))
    result["signal_line"] = float(round(signal_ema[-1], 4))
    result["histogram"] = float(round(macd_line[-1] - signal_ema[-1], 4))

    return result


def compute_bollinger_bands(
    closes: list[float],
    period: int = 20,
    std_dev: float = 2.0,
) -> dict[str, Optional[float]]:
    """Compute Bollinger Bands.

    Args:
        closes: List of closing prices (oldest first).
        period: SMA lookback period (default: 20).
        std_dev: Standard deviation multiplier (default: 2.0).

    Returns:
        Dict with 'upper', 'middle', 'lower', and 'width'.
    """
    result: dict[str, Optional[float]] = {
        "upper": None,
        "middle": None,
        "lower": None,
        "width": None,
    }

    if len(closes) < period:
        return result

    recent = np.array(closes[-period:], dtype=float)
    middle = float(np.mean(recent))
    std = float(np.std(recent, ddof=1))  # sample std dev

    upper = middle + std_dev * std
    lower = middle - std_dev * std
    width = (upper - lower) / middle * 100 if middle > 0 else 0.0

    result["upper"] = round(upper, 2)
    result["middle"] = round(middle, 2)
    result["lower"] = round(lower, 2)
    result["width"] = round(width, 2)

    return result


def calculate_atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> Optional[float]:
    """Average True Range — measures volatility, useful for stop-loss sizing.

    Args:
        highs: Daily high prices (oldest first).
        lows: Daily low prices (oldest first).
        closes: Daily close prices (oldest first).
        period: ATR lookback period (default: 14).

    Returns:
        ATR value or None if insufficient data.
    """
    if len(closes) < period + 1 or len(highs) < period + 1 or len(lows) < period + 1:
        return None

    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    c = np.array(closes, dtype=float)

    # True Range = max(H-L, |H-prev_C|, |L-prev_C|)
    tr = np.maximum(
        h[1:] - l[1:],
        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])),
    )

    if len(tr) < period:
        return None

    # Wilder's smoothed ATR
    atr = np.mean(tr[:period])
    for i in range(period, len(tr)):
        atr = (atr * (period - 1) + tr[i]) / period

    return float(round(atr, 4))


def calculate_adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> Optional[float]:
    """Average Directional Index — measures trend strength (0-100).

    > 25 = strong trend, < 20 = weak/sideways.

    Args:
        highs: Daily high prices (oldest first).
        lows: Daily low prices (oldest first).
        closes: Daily close prices (oldest first).
        period: ADX period (default: 14).

    Returns:
        ADX value (0-100) or None if insufficient data.
    """
    min_len = period * 2 + 1
    if len(closes) < min_len or len(highs) < min_len or len(lows) < min_len:
        return None

    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    c = np.array(closes, dtype=float)

    # True Range
    tr = np.maximum(
        h[1:] - l[1:],
        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])),
    )

    # Directional Movement
    up_move = h[1:] - h[:-1]
    down_move = l[:-1] - l[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # Wilder smoothing
    def _wilder_smooth(arr: np.ndarray) -> np.ndarray:
        out = np.empty_like(arr)
        out[0] = np.mean(arr[:period])
        for i in range(1, len(arr)):
            out[i] = (out[i - 1] * (period - 1) + arr[i]) / period
        return out

    n = len(tr) - period + 1
    if n < period:
        return None

    smooth_tr = _wilder_smooth(tr[period - 1 :])
    smooth_plus = _wilder_smooth(plus_dm[period - 1 :])
    smooth_minus = _wilder_smooth(minus_dm[period - 1 :])

    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = np.where(smooth_tr > 0, 100 * smooth_plus / smooth_tr, 0.0)
        minus_di = np.where(smooth_tr > 0, 100 * smooth_minus / smooth_tr, 0.0)
        dx = np.where(
            (plus_di + minus_di) > 0,
            100 * np.abs(plus_di - minus_di) / (plus_di + minus_di),
            0.0,
        )

    # ADX = smoothed DX
    if len(dx) < period:
        return None

    adx = np.mean(dx[:period])
    for i in range(period, len(dx)):
        adx = (adx * (period - 1) + dx[i]) / period

    return float(round(adx, 2))


def calculate_vwap(prices: list[float], volumes: list[int]) -> Optional[float]:
    """Volume Weighted Average Price.

    Args:
        prices: Typical prices or close prices (oldest first).
        volumes: Corresponding volumes.

    Returns:
        VWAP value or None if data is missing/volumes are all zero.
    """
    if not prices or not volumes or len(prices) != len(volumes):
        return None

    p = np.array(prices, dtype=float)
    v = np.array(volumes, dtype=float)
    total_volume = np.sum(v)
    if total_volume == 0:
        return None

    return float(round(np.sum(p * v) / total_volume, 4))


def detect_crossover(
    series_a: list[float],
    series_b: list[float],
) -> Optional[str]:
    """Detect if series_a crossed series_b in the most recent candle.

    Used for: MACD line vs signal line, price vs SMA, EMA crossovers.

    Args:
        series_a: First series (e.g. MACD line) — at least 2 values, oldest first.
        series_b: Second series (e.g. signal line) — same length.

    Returns:
        'bullish'  — series_a crossed above series_b (last candle)
        'bearish'  — series_a crossed below series_b (last candle)
        None       — no crossover or insufficient data
    """
    if len(series_a) < 2 or len(series_b) < 2:
        return None

    prev_diff = series_a[-2] - series_b[-2]
    curr_diff = series_a[-1] - series_b[-1]

    if prev_diff <= 0 and curr_diff > 0:
        return "bullish"
    if prev_diff >= 0 and curr_diff < 0:
        return "bearish"
    return None


def _ema_series(prices: np.ndarray, period: int) -> Optional[np.ndarray]:
    """Compute a full EMA series (internal helper).

    Args:
        prices: NumPy array of prices.
        period: EMA lookback period.

    Returns:
        NumPy array of EMA values starting from index (period-1).
    """
    if len(prices) < period:
        return None

    multiplier = 2.0 / (period + 1)
    ema_values = np.empty(len(prices) - period + 1)
    ema_values[0] = np.mean(prices[:period])

    for i in range(1, len(ema_values)):
        ema_values[i] = (prices[period - 1 + i] - ema_values[i - 1]) * multiplier + ema_values[i - 1]

    return ema_values
