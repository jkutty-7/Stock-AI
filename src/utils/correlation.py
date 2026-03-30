"""Pearson correlation utilities for portfolio analysis (Phase 3B).

Used by CapitalAllocator to detect over-correlated positions before entry.

Usage:
    from src.utils.correlation import pearson_correlation, build_correlation_matrix

    corr = pearson_correlation(prices_a, prices_b)  # returns float in [-1, 1]
    matrix = build_correlation_matrix({"TCS": [...], "INFY": [...]})
"""

from math import sqrt
from typing import Optional


def pearson_correlation(x: list[float], y: list[float]) -> Optional[float]:
    """Compute Pearson correlation coefficient between two price series.

    Args:
        x: List of closing prices for series A.
        y: List of closing prices for series B (same length as x).

    Returns:
        Pearson r in [-1.0, 1.0], or None if calculation fails (e.g., zero variance).
    """
    n = min(len(x), len(y))
    if n < 5:
        return None

    # Use returns instead of raw prices to remove level-effect bias
    rx = [(x[i] - x[i - 1]) / x[i - 1] for i in range(1, n) if x[i - 1] != 0]
    ry = [(y[i] - y[i - 1]) / y[i - 1] for i in range(1, n) if y[i - 1] != 0]

    m = min(len(rx), len(ry))
    if m < 4:
        return None

    rx = rx[:m]
    ry = ry[:m]

    mean_x = sum(rx) / m
    mean_y = sum(ry) / m

    cov_xy = sum((rx[i] - mean_x) * (ry[i] - mean_y) for i in range(m))
    var_x = sum((v - mean_x) ** 2 for v in rx)
    var_y = sum((v - mean_y) ** 2 for v in ry)

    denom = sqrt(var_x * var_y)
    if denom == 0:
        return None

    return max(-1.0, min(1.0, cov_xy / denom))


def build_correlation_matrix(
    prices: dict[str, list[float]],
) -> dict[str, dict[str, Optional[float]]]:
    """Build a pairwise Pearson correlation matrix from multiple price series.

    Args:
        prices: Dict mapping symbol → list of closing prices (same length recommended).

    Returns:
        Nested dict: matrix[symbol_a][symbol_b] = correlation float or None.
    """
    symbols = list(prices.keys())
    matrix: dict[str, dict[str, Optional[float]]] = {}

    for i, sym_a in enumerate(symbols):
        matrix[sym_a] = {}
        for j, sym_b in enumerate(symbols):
            if sym_a == sym_b:
                matrix[sym_a][sym_b] = 1.0
            elif j < i:
                # Mirror the already-computed value
                matrix[sym_a][sym_b] = matrix.get(sym_b, {}).get(sym_a)
            else:
                matrix[sym_a][sym_b] = pearson_correlation(prices[sym_a], prices[sym_b])

    return matrix


def find_high_correlation_pairs(
    matrix: dict[str, dict[str, Optional[float]]],
    threshold: float = 0.80,
) -> list[dict]:
    """Extract pairs above the correlation threshold.

    Args:
        matrix: Output of build_correlation_matrix().
        threshold: Minimum absolute correlation to flag (default 0.80).

    Returns:
        List of {"a": sym_a, "b": sym_b, "corr": float} dicts, sorted by corr desc.
    """
    pairs = []
    symbols = list(matrix.keys())
    seen: set[frozenset] = set()

    for sym_a in symbols:
        for sym_b, corr in matrix.get(sym_a, {}).items():
            if sym_a == sym_b or corr is None:
                continue
            pair_key = frozenset([sym_a, sym_b])
            if pair_key in seen:
                continue
            seen.add(pair_key)
            if abs(corr) >= threshold:
                pairs.append({"a": sym_a, "b": sym_b, "corr": round(corr, 4)})

    pairs.sort(key=lambda p: abs(p["corr"]), reverse=True)
    return pairs
