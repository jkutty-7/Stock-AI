"""Shared test fixtures for Stock AI tests."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def sample_holdings_raw():
    """Raw holdings response as returned by Groww SDK."""
    return [
        {
            "isin": "INE002A01018",
            "trading_symbol": "RELIANCE",
            "quantity": 10,
            "average_price": 2500.0,
            "pledge_quantity": 0,
            "demat_locked_quantity": 0,
            "groww_locked_quantity": 0,
            "repledge_quantity": 0,
            "t1_quantity": 0,
            "demat_free_quantity": 10,
            "corporate_action_additional_quantity": 0,
            "active_demat_transfer_quantity": 0,
        },
        {
            "isin": "INE467B01029",
            "trading_symbol": "TCS",
            "quantity": 5,
            "average_price": 3800.0,
            "pledge_quantity": 0,
            "demat_locked_quantity": 0,
            "groww_locked_quantity": 0,
            "repledge_quantity": 0,
            "t1_quantity": 0,
            "demat_free_quantity": 5,
            "corporate_action_additional_quantity": 0,
            "active_demat_transfer_quantity": 0,
        },
        {
            "isin": "INE009A01021",
            "trading_symbol": "INFY",
            "quantity": 20,
            "average_price": 1500.0,
            "pledge_quantity": 0,
            "demat_locked_quantity": 0,
            "groww_locked_quantity": 0,
            "repledge_quantity": 0,
            "t1_quantity": 0,
            "demat_free_quantity": 20,
            "corporate_action_additional_quantity": 0,
            "active_demat_transfer_quantity": 0,
        },
    ]


@pytest.fixture
def sample_prices():
    """Bulk LTP response."""
    return {
        "NSE_RELIANCE": 2650.0,
        "NSE_TCS": 3900.0,
        "NSE_INFY": 1480.0,
    }


@pytest.fixture
def sample_ohlc():
    """Bulk OHLC response."""
    return {
        "NSE_RELIANCE": {"open": 2600.0, "high": 2660.0, "low": 2590.0, "close": 2620.0},
        "NSE_TCS": {"open": 3850.0, "high": 3910.0, "low": 3840.0, "close": 3870.0},
        "NSE_INFY": {"open": 1510.0, "high": 1520.0, "low": 1470.0, "close": 1500.0},
    }


@pytest.fixture
def sample_candles():
    """50 daily candles for indicator testing."""
    import random
    random.seed(42)

    candles = []
    price = 100.0
    for i in range(50):
        change = random.uniform(-3, 3)
        o = price
        h = price + abs(change) + random.uniform(0, 2)
        l = price - abs(change) - random.uniform(0, 2)
        c = price + change
        v = random.randint(100000, 500000)
        candles.append({
            "timestamp": datetime(2026, 1, 1 + i % 28, 15, 30),
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "volume": v,
        })
        price = c

    return candles


@pytest.fixture
def sample_snapshot():
    """Sample portfolio snapshot dict."""
    return {
        "timestamp": "2026-03-05T14:30:00",
        "total_invested": 68000.0,
        "current_value": 72300.0,
        "total_pnl": 4300.0,
        "total_pnl_pct": 6.32,
        "day_pnl": 450.0,
        "holdings": [
            {
                "isin": "INE002A01018",
                "trading_symbol": "RELIANCE",
                "quantity": 10,
                "average_price": 2500.0,
                "current_price": 2650.0,
                "day_change_pct": 1.15,
                "total_invested": 25000.0,
                "current_value": 26500.0,
                "pnl": 1500.0,
                "pnl_pct": 6.0,
                "day_pnl": 300.0,
            },
            {
                "isin": "INE467B01029",
                "trading_symbol": "TCS",
                "quantity": 5,
                "average_price": 3800.0,
                "current_price": 3900.0,
                "day_change_pct": 0.78,
                "total_invested": 19000.0,
                "current_value": 19500.0,
                "pnl": 500.0,
                "pnl_pct": 2.63,
                "day_pnl": 150.0,
            },
        ],
    }


@pytest.fixture
def mock_groww_api():
    """Mock GrowwAPI with realistic response data."""
    api = MagicMock()
    api.get_holdings_for_user.return_value = {
        "holdings": [
            {
                "isin": "INE002A01018",
                "trading_symbol": "RELIANCE",
                "quantity": 10,
                "average_price": 2500.0,
            },
        ]
    }
    api.get_ltp.return_value = {"NSE_RELIANCE": 2650.0}
    api.get_ohlc.return_value = {
        "NSE_RELIANCE": {"open": 2600, "high": 2660, "low": 2590, "close": 2620}
    }
    api.get_user_profile.return_value = {
        "vendor_user_id": "test-user",
        "ucc": "999999",
        "nse_enabled": True,
        "bse_enabled": True,
        "active_segments": ["CASH", "FNO"],
    }
    return api
