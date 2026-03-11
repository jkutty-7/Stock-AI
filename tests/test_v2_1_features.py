"""
End-to-end tests for Stock AI v2.1 features.

Run with: pytest tests/test_v2_1_features.py -v
Or from project root: python -m pytest tests/test_v2_1_features.py -v
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from src.config import settings
from src.models.outcome import SignalOutcome
from src.services.database import db
from src.services.drawdown_breaker import drawdown_breaker
from src.services.outcome_tracker import outcome_tracker
from src.services.regime_classifier import regime_classifier


@pytest.fixture
async def mongodb_connection():
    """Fixture to ensure MongoDB connection."""
    client = AsyncIOMotorClient(settings.mongodb_uri)
    await client.admin.command("ping")
    yield client
    client.close()


@pytest.mark.asyncio
class TestDatabaseSetup:
    """Test MongoDB collections and indexes are properly set up."""

    async def test_signal_outcomes_collection_exists(self, mongodb_connection):
        """Verify signal_outcomes collection exists."""
        collection_names = await db.db.list_collection_names()
        assert "signal_outcomes" in collection_names

    async def test_signal_outcomes_indexes(self, mongodb_connection):
        """Verify signal_outcomes has correct indexes."""
        indexes = await db.signal_outcomes.index_information()

        # Check for compound index on (trading_symbol, signal_timestamp)
        assert any(
            "trading_symbol" in idx.get("key", {})
            for idx in indexes.values()
        ), "Missing trading_symbol index"

        # Check for status index
        assert any(
            "status" in idx.get("key", {})
            for idx in indexes.values()
        ), "Missing status index"

    async def test_portfolio_peaks_collection_exists(self, mongodb_connection):
        """Verify portfolio_peaks collection exists."""
        collection_names = await db.db.list_collection_names()
        assert "portfolio_peaks" in collection_names

    async def test_circuit_breaker_state_collection_exists(self, mongodb_connection):
        """Verify circuit_breaker_state collection exists."""
        collection_names = await db.db.list_collection_names()
        assert "circuit_breaker_state" in collection_names

    async def test_market_regime_collection_exists(self, mongodb_connection):
        """Verify market_regime collection exists."""
        collection_names = await db.db.list_collection_names()
        assert "market_regime" in collection_names

    async def test_trade_signals_ttl_updated(self, mongodb_connection):
        """Verify trade_signals TTL increased to 90 days."""
        indexes = await db.trade_signals.index_information()

        ttl_index = None
        for idx_name, idx_info in indexes.items():
            if idx_info.get("expireAfterSeconds") is not None:
                ttl_index = idx_info
                break

        assert ttl_index is not None, "No TTL index found on trade_signals"
        # 90 days = 7,776,000 seconds
        assert ttl_index["expireAfterSeconds"] == 7776000, \
            f"Expected 90 days TTL, got {ttl_index['expireAfterSeconds']} seconds"


@pytest.mark.asyncio
class TestSignalOutcomeTracker:
    """Test signal outcome tracking functionality."""

    async def test_outcome_model_pnl_calculation_buy(self):
        """Test P&L calculation for BUY signal."""
        outcome = SignalOutcome(
            signal_id="test_id",
            trading_symbol="RELIANCE",
            action="BUY",
            signal_timestamp=datetime.now(),
            entry_price=2450.0,
            entry_timestamp=datetime.now(),
            entry_method="AUTO_TRACKED",
            original_confidence=0.85,
        )

        # Simulate exit at profit
        outcome.exit_price = 2520.0
        outcome.compute_metrics()

        assert outcome.pnl_points == 70.0
        assert abs(outcome.pnl_pct - 2.857) < 0.01  # ~2.857%
        assert outcome.win_loss == "WIN"

    async def test_outcome_model_pnl_calculation_sell(self):
        """Test P&L calculation for SELL signal."""
        outcome = SignalOutcome(
            signal_id="test_id",
            trading_symbol="RELIANCE",
            action="SELL",
            signal_timestamp=datetime.now(),
            entry_price=2450.0,
            entry_timestamp=datetime.now(),
            entry_method="AUTO_TRACKED",
            original_confidence=0.85,
        )

        # SELL profits when price drops
        outcome.exit_price = 2400.0
        outcome.compute_metrics()

        assert outcome.pnl_points == 50.0  # entry - exit for SELL
        assert abs(outcome.pnl_pct - 2.041) < 0.01  # ~2.041%
        assert outcome.win_loss == "WIN"

    async def test_outcome_win_loss_classification(self):
        """Test win/loss classification with 0.5% threshold."""
        outcome = SignalOutcome(
            signal_id="test_id",
            trading_symbol="TEST",
            action="BUY",
            signal_timestamp=datetime.now(),
            entry_price=1000.0,
            entry_timestamp=datetime.now(),
            entry_method="AUTO_TRACKED",
            original_confidence=0.75,
        )

        # Test WIN (> 0.5%)
        outcome.exit_price = 1010.0
        outcome.compute_metrics()
        assert outcome.win_loss == "WIN"

        # Test LOSS (< -0.5%)
        outcome.exit_price = 990.0
        outcome.compute_metrics()
        assert outcome.win_loss == "LOSS"

        # Test BREAKEVEN (-0.5% to +0.5%)
        outcome.exit_price = 1002.0  # +0.2%
        outcome.compute_metrics()
        assert outcome.win_loss == "BREAKEVEN"


@pytest.mark.asyncio
class TestDrawdownBreaker:
    """Test portfolio drawdown circuit breaker."""

    async def test_drawdown_calculation(self):
        """Test drawdown percentage calculation."""
        # Set up peak
        await db.portfolio_peaks.delete_many({})
        await db.portfolio_peaks.insert_one({
            "timestamp": datetime.now(),
            "portfolio_value": 1000000.0,
            "is_current_peak": True,
        })

        # Check drawdown at different levels
        result = await drawdown_breaker.check_drawdown(920000.0)

        assert result["in_drawdown"] is True
        assert abs(result["drawdown_pct"] - 8.0) < 0.01  # 8% drawdown
        assert result["peak_value"] == 1000000.0

    async def test_peak_update(self):
        """Test portfolio peak updates when portfolio increases."""
        # Set initial peak
        await db.portfolio_peaks.delete_many({})
        await db.portfolio_peaks.insert_one({
            "timestamp": datetime.now(),
            "portfolio_value": 1000000.0,
            "is_current_peak": True,
        })

        # Update with higher value
        updated = await drawdown_breaker.update_peak(1100000.0, 950000.0)

        assert updated is True

        # Verify new peak
        new_peak = await db.portfolio_peaks.find_one({"is_current_peak": True})
        assert new_peak["portfolio_value"] == 1100000.0

    async def test_breaker_not_triggered_below_threshold(self):
        """Test breaker doesn't trigger below threshold."""
        # Set up peak
        await db.portfolio_peaks.delete_many({})
        await db.portfolio_peaks.insert_one({
            "timestamp": datetime.now(),
            "portfolio_value": 1000000.0,
            "is_current_peak": True,
        })

        # Clear breaker state
        await db.circuit_breaker_state.delete_one({"_id": "drawdown_breaker"})

        # 5% drawdown (below 8% threshold)
        result = await drawdown_breaker.check_drawdown(950000.0)

        assert result["breaker_triggered"] is False
        assert result["drawdown_pct"] == 5.0


@pytest.mark.asyncio
class TestRegimeClassifier:
    """Test market regime classification."""

    def test_regime_score_calculation(self):
        """Test regime score calculation logic."""
        classifier = regime_classifier

        # Test strong bull scenario
        score = classifier._compute_regime_score(
            price=22500,
            sma_20=22200,
            sma_50=21800,
            sma_200=21000,
            rsi=65,
            volatility=0.8,
        )
        assert score > 60, "Expected BULL_STRONG score"

        # Test strong bear scenario
        score = classifier._compute_regime_score(
            price=21000,
            sma_20=21500,
            sma_50=22000,
            sma_200=22500,
            rsi=32,
            volatility=3.5,
        )
        assert score < -60, "Expected BEAR_STRONG score"

    def test_regime_mapping(self):
        """Test regime score to regime type mapping."""
        classifier = regime_classifier

        # Test BULL_STRONG
        regime_info = classifier._map_score_to_regime(75.0)
        assert regime_info["regime"] == "BULL_STRONG"
        assert regime_info["min_confidence"] == 0.65
        assert regime_info["exposure_pct"] == 90

        # Test BEAR_WEAK
        regime_info = classifier._map_score_to_regime(-40.0)
        assert regime_info["regime"] == "BEAR_WEAK"
        assert regime_info["min_confidence"] == 0.80
        assert regime_info["exposure_pct"] == 40

        # Test SIDEWAYS
        regime_info = classifier._map_score_to_regime(0.0)
        assert regime_info["regime"] == "SIDEWAYS"
        assert regime_info["min_confidence"] == 0.75
        assert regime_info["exposure_pct"] == 60

    def test_regime_score_clamping(self):
        """Test regime score clamped to -100 to +100."""
        classifier = regime_classifier

        # Extreme bull (should clamp to +100)
        score = classifier._compute_regime_score(
            price=25000,
            sma_20=22000,
            sma_50=21000,
            sma_200=20000,
            rsi=80,
            volatility=0.5,
        )
        assert score <= 100

        # Extreme bear (should clamp to -100)
        score = classifier._compute_regime_score(
            price=19000,
            sma_20=22000,
            sma_50=23000,
            sma_200=24000,
            rsi=20,
            volatility=5.0,
        )
        assert score >= -100


@pytest.mark.asyncio
class TestConfiguration:
    """Test v2.1 configuration variables are set."""

    def test_outcome_tracking_config(self):
        """Test outcome tracking configuration variables."""
        assert hasattr(settings, "outcome_auto_track_enabled")
        assert hasattr(settings, "outcome_auto_track_interval_hours")
        assert hasattr(settings, "outcome_min_confidence_track")

        assert isinstance(settings.outcome_auto_track_enabled, bool)
        assert settings.outcome_auto_track_interval_hours > 0

    def test_stop_loss_config(self):
        """Test stop-loss monitoring configuration."""
        assert hasattr(settings, "stop_loss_enabled")
        assert hasattr(settings, "stop_loss_grace_pct")

        assert isinstance(settings.stop_loss_enabled, bool)
        assert settings.stop_loss_grace_pct >= 0

    def test_drawdown_breaker_config(self):
        """Test drawdown breaker configuration."""
        assert hasattr(settings, "drawdown_breaker_enabled")
        assert hasattr(settings, "drawdown_breaker_threshold_pct")
        assert hasattr(settings, "drawdown_breaker_auto_reset")

        assert isinstance(settings.drawdown_breaker_enabled, bool)
        assert settings.drawdown_breaker_threshold_pct > 0
        assert isinstance(settings.drawdown_breaker_auto_reset, bool)

    def test_regime_classification_config(self):
        """Test regime classification configuration."""
        assert hasattr(settings, "regime_classification_enabled")
        assert hasattr(settings, "regime_index_symbol")

        assert isinstance(settings.regime_classification_enabled, bool)
        assert settings.regime_index_symbol == "NIFTY 50"

    def test_liquidity_filter_config(self):
        """Test liquidity filter configuration."""
        assert hasattr(settings, "screener_min_liquidity")
        assert hasattr(settings, "screener_liquidity_lookback_days")

        assert settings.screener_min_liquidity >= 0
        assert settings.screener_liquidity_lookback_days > 0


@pytest.mark.asyncio
class TestIntegration:
    """Integration tests for v2.1 features working together."""

    async def test_signal_to_outcome_flow(self):
        """Test complete flow: signal generation → outcome tracking."""
        # Create test signal
        signal_doc = {
            "trading_symbol": "TEST",
            "action": "BUY",
            "confidence": 0.85,
            "target_price": 2550.0,
            "stop_loss": 2400.0,
            "current_price": 2450.0,
            "timestamp": datetime.now(),
            "status": "ACTIVE",
        }

        # Insert signal
        result = await db.trade_signals.insert_one(signal_doc)
        signal_id = str(result.inserted_id)

        # Track outcome (simulating what portfolio_monitor does)
        outcome_id = await outcome_tracker.track_new_signal(signal_id, signal_doc)

        # Verify outcome created
        outcome_doc = await db.signal_outcomes.find_one({"_id": outcome_id})
        assert outcome_doc is not None
        assert outcome_doc["trading_symbol"] == "TEST"
        assert outcome_doc["status"] == "OPEN"
        assert outcome_doc["original_confidence"] == 0.85

        # Cleanup
        await db.trade_signals.delete_one({"_id": result.inserted_id})
        await db.signal_outcomes.delete_one({"_id": outcome_id})


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--asyncio-mode=auto"])
