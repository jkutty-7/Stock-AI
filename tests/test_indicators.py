"""Tests for technical indicator calculations."""

import pytest

from src.utils.indicators import (
    compute_bollinger_bands,
    compute_ema,
    compute_macd,
    compute_rsi,
    compute_sma,
)


class TestRSI:
    def test_rsi_returns_none_for_insufficient_data(self):
        assert compute_rsi([100, 101], period=14) is None

    def test_rsi_returns_100_for_all_gains(self):
        # Monotonically increasing prices
        prices = list(range(100, 120))
        result = compute_rsi(prices, period=14)
        assert result == 100.0

    def test_rsi_returns_value_in_range(self):
        prices = [44, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10, 45.42,
                  45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00]
        result = compute_rsi(prices, period=14)
        assert result is not None
        assert 0 <= result <= 100

    def test_rsi_detects_overbought(self):
        # Strong uptrend should give high RSI
        prices = [100 + i * 2 for i in range(20)]
        result = compute_rsi(prices, period=14)
        assert result is not None
        assert result > 70  # Overbought territory


class TestSMA:
    def test_sma_returns_none_for_insufficient_data(self):
        assert compute_sma([100, 101, 102], period=5) is None

    def test_sma_simple_case(self):
        prices = [10, 20, 30, 40, 50]
        assert compute_sma(prices, period=5) == 30.0

    def test_sma_uses_latest_n_values(self):
        prices = [1, 2, 3, 100, 200, 300]
        result = compute_sma(prices, period=3)
        assert result == 200.0  # avg of [100, 200, 300]


class TestEMA:
    def test_ema_returns_none_for_insufficient_data(self):
        assert compute_ema([100, 101], period=5) is None

    def test_ema_gives_more_weight_to_recent(self):
        prices = [10, 10, 10, 10, 10, 10, 10, 10, 10, 100]
        sma = compute_sma(prices, period=10)
        ema = compute_ema(prices, period=10)
        # EMA should be higher than SMA due to recent spike
        assert ema is not None
        assert sma is not None
        assert ema > sma


class TestMACD:
    def test_macd_returns_nones_for_insufficient_data(self):
        result = compute_macd([100] * 10)
        assert result["macd_line"] is None
        assert result["signal_line"] is None
        assert result["histogram"] is None

    def test_macd_returns_valid_values(self):
        # 50 data points should be enough
        prices = [100 + i * 0.5 for i in range(50)]
        result = compute_macd(prices)
        assert result["macd_line"] is not None
        assert result["signal_line"] is not None
        assert result["histogram"] is not None

    def test_macd_histogram_is_difference(self):
        prices = [100 + i * 0.5 for i in range(50)]
        result = compute_macd(prices)
        if result["macd_line"] is not None and result["signal_line"] is not None:
            expected = round(result["macd_line"] - result["signal_line"], 4)
            assert result["histogram"] == expected


class TestBollingerBands:
    def test_bb_returns_nones_for_insufficient_data(self):
        result = compute_bollinger_bands([100] * 5, period=20)
        assert result["upper"] is None

    def test_bb_middle_equals_sma(self):
        prices = list(range(100, 121))  # 21 prices
        bb = compute_bollinger_bands(prices, period=20)
        sma = compute_sma(prices, period=20)
        assert bb["middle"] == sma

    def test_bb_upper_greater_than_lower(self):
        prices = [100 + (i % 5) for i in range(25)]
        result = compute_bollinger_bands(prices, period=20)
        assert result["upper"] is not None
        assert result["lower"] is not None
        assert result["upper"] > result["lower"]

    def test_bb_width_is_positive(self):
        prices = [100 + (i % 5) for i in range(25)]
        result = compute_bollinger_bands(prices, period=20)
        assert result["width"] is not None
        assert result["width"] > 0
