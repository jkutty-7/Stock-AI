"""Tests for market hours and holiday utilities."""

import pytest
from datetime import date, datetime, time

import pytz

from src.utils.market_hours import (
    IST,
    is_market_holiday,
    is_market_open,
    is_pre_market,
    is_trading_day,
    is_weekend,
    next_market_open,
    time_to_market_close,
)


class TestIsWeekend:
    def test_monday_is_not_weekend(self):
        # 2026-03-02 is a Monday
        assert is_weekend(date(2026, 3, 2)) is False

    def test_saturday_is_weekend(self):
        # 2026-03-07 is a Saturday
        assert is_weekend(date(2026, 3, 7)) is True

    def test_sunday_is_weekend(self):
        # 2026-03-08 is a Sunday
        assert is_weekend(date(2026, 3, 8)) is True


class TestIsMarketHoliday:
    def test_republic_day(self):
        assert is_market_holiday(date(2026, 1, 26)) is True

    def test_christmas(self):
        assert is_market_holiday(date(2026, 12, 25)) is True

    def test_regular_day_is_not_holiday(self):
        assert is_market_holiday(date(2026, 3, 5)) is False

    def test_accepts_datetime(self):
        dt = datetime(2026, 1, 26, 10, 0, 0, tzinfo=IST)
        assert is_market_holiday(dt) is True


class TestIsTradingDay:
    def test_weekday_non_holiday(self):
        # 2026-03-05 is a Thursday
        assert is_trading_day(date(2026, 3, 5)) is True

    def test_weekend_is_not_trading_day(self):
        assert is_trading_day(date(2026, 3, 7)) is False

    def test_holiday_is_not_trading_day(self):
        assert is_trading_day(date(2026, 1, 26)) is False


class TestIsMarketOpen:
    def test_open_during_market_hours(self):
        dt = datetime(2026, 3, 5, 10, 30, 0, tzinfo=IST)  # Thursday 10:30 AM
        assert is_market_open(dt) is True

    def test_closed_before_market(self):
        dt = datetime(2026, 3, 5, 9, 0, 0, tzinfo=IST)  # 9:00 AM
        assert is_market_open(dt) is False

    def test_open_at_exact_opening(self):
        dt = datetime(2026, 3, 5, 9, 15, 0, tzinfo=IST)  # 9:15 AM
        assert is_market_open(dt) is True

    def test_open_at_exact_closing(self):
        dt = datetime(2026, 3, 5, 15, 30, 0, tzinfo=IST)  # 3:30 PM
        assert is_market_open(dt) is True

    def test_closed_after_market(self):
        dt = datetime(2026, 3, 5, 15, 31, 0, tzinfo=IST)  # 3:31 PM
        assert is_market_open(dt) is False

    def test_closed_on_weekend(self):
        dt = datetime(2026, 3, 7, 11, 0, 0, tzinfo=IST)  # Saturday 11 AM
        assert is_market_open(dt) is False

    def test_closed_on_holiday(self):
        dt = datetime(2026, 1, 26, 11, 0, 0, tzinfo=IST)  # Republic Day 11 AM
        assert is_market_open(dt) is False


class TestIsPreMarket:
    def test_pre_market_window(self):
        dt = datetime(2026, 3, 5, 9, 10, 0, tzinfo=IST)  # 9:10 AM
        assert is_pre_market(dt) is True

    def test_not_pre_market_during_session(self):
        dt = datetime(2026, 3, 5, 10, 0, 0, tzinfo=IST)
        assert is_pre_market(dt) is False


class TestTimeToMarketClose:
    def test_returns_positive_during_market(self):
        dt = datetime(2026, 3, 5, 14, 30, 0, tzinfo=IST)  # 2:30 PM
        minutes = time_to_market_close(dt)
        assert minutes == 60.0  # 60 minutes to 3:30 PM

    def test_returns_zero_when_closed(self):
        dt = datetime(2026, 3, 5, 16, 0, 0, tzinfo=IST)
        assert time_to_market_close(dt) == 0.0


class TestNextMarketOpen:
    def test_next_open_same_day_before_market(self):
        dt = datetime(2026, 3, 5, 8, 0, 0, tzinfo=IST)  # Thursday 8 AM
        result = next_market_open(dt)
        assert result.hour == 9
        assert result.minute == 15
        assert result.day == 5

    def test_next_open_from_friday_evening(self):
        dt = datetime(2026, 3, 6, 16, 0, 0, tzinfo=IST)  # Friday 4 PM
        result = next_market_open(dt)
        assert result.weekday() == 0  # Monday
        assert result.day == 9
