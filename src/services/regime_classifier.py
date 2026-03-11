"""Market regime classification service for strategy adjustment.

This service analyzes Nifty 50 daily to classify the market regime (bull, bear,
sideways) and adjusts signal confidence thresholds accordingly. In bear markets,
higher confidence is required for BUY signals to reduce risk.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from src.config import settings
from src.services.database import db
from src.services.groww_service import groww_service
from src.utils.indicators import compute_rsi, compute_sma

logger = logging.getLogger(__name__)


class RegimeClassifier:
    """Classifies market regime based on Nifty 50 technical indicators."""

    async def classify_daily_regime(self) -> dict[str, Any]:
        """Run daily regime classification on Nifty 50.

        Fetches 90 days of Nifty 50 data, computes indicators (SMA20, SMA50,
        SMA200, RSI14, volatility), scores the regime, and stores the result.

        Returns:
            Dict with regime classification results
        """
        if not settings.regime_classification_enabled:
            logger.info("Regime classification disabled")
            return {"success": False, "message": "Disabled"}

        try:
            symbol = settings.regime_index_symbol
            logger.info(f"Fetching {symbol} data for regime classification")

            # Fetch 90 days of daily candles
            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            start_time = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")

            candles = await groww_service.get_historical_candles(
                trading_symbol=symbol,
                exchange="NSE",
                segment="CASH",
                start_time=start_time,
                end_time=end_time,
                interval_minutes=1440,  # Daily
            )

            if not candles or len(candles) < 50:
                logger.warning(f"Insufficient data for {symbol}: {len(candles)} candles")
                return {"success": False, "message": "Insufficient data"}

            # Extract prices and compute indicators
            closes = [float(c.close) for c in candles if c.close]
            current_price = closes[-1]

            sma_20 = compute_sma(closes, 20)
            sma_50 = compute_sma(closes, 50)
            sma_200 = compute_sma(closes, 200) if len(closes) >= 200 else sma_50
            rsi_14 = compute_rsi(closes, 14)

            # Compute 20-day volatility (std dev of daily returns)
            returns = [
                (closes[i] - closes[i-1]) / closes[i-1] * 100
                for i in range(1, min(21, len(closes)))
            ]
            volatility = self._std_dev(returns) if returns else 0.0

            # Compute regime score
            regime_score = self._compute_regime_score(
                price=current_price,
                sma_20=sma_20,
                sma_50=sma_50,
                sma_200=sma_200,
                rsi=rsi_14,
                volatility=volatility,
            )

            # Map score to regime
            regime_info = self._map_score_to_regime(regime_score)

            # Build regime document
            regime_doc = {
                "timestamp": datetime.now(),
                "date": datetime.now().strftime("%Y-%m-%d"),
                "index_symbol": symbol,
                # Raw indicators
                "close_price": current_price,
                "sma_20": sma_20,
                "sma_50": sma_50,
                "sma_200": sma_200,
                "rsi_14": rsi_14,
                "volatility_20d": volatility,
                # Classification
                "regime": regime_info["regime"],
                "regime_score": regime_score,
                "confidence": regime_info["confidence"],
                "trend": regime_info["trend"],
                "strength": regime_info["strength"],
                "volatility_regime": regime_info["volatility_regime"],
                # Strategy adjustments
                "signal_weight_multiplier": regime_info["weight_multiplier"],
                "suggested_min_confidence": regime_info["min_confidence"],
                "suggested_exposure_pct": regime_info["exposure_pct"],
                "is_current": True,
            }

            # Clear old "is_current" flag
            await db.market_regime.update_many(
                {"is_current": True},
                {"$set": {"is_current": False}}
            )

            # Insert new regime
            await db.market_regime.insert_one(regime_doc)

            logger.info(
                f"Regime classified: {regime_info['regime']} "
                f"(score: {regime_score:.1f}, confidence: {regime_info['confidence']:.2f})"
            )

            return {
                "success": True,
                "regime": regime_info["regime"],
                "regime_score": regime_score,
                "indicators": {
                    "price": current_price,
                    "sma_20": sma_20,
                    "sma_50": sma_50,
                    "sma_200": sma_200,
                    "rsi": rsi_14,
                    "volatility": volatility,
                },
            }

        except Exception as e:
            logger.error(f"Regime classification failed: {e}", exc_info=True)
            return {"success": False, "message": str(e)}

    def _compute_regime_score(
        self,
        price: float,
        sma_20: float,
        sma_50: float,
        sma_200: float,
        rsi: float,
        volatility: float,
    ) -> float:
        """Compute regime score from -100 (strong bear) to +100 (strong bull).

        Scoring breakdown:
        - Price vs SMAs: 40 points
        - SMA alignment: 20 points
        - RSI momentum: 20 points
        - Volatility penalty: -20 points
        """
        score = 0.0

        # Price vs SMAs (40 pts)
        if price > sma_20:
            score += 15
        else:
            score -= 15

        if price > sma_50:
            score += 15
        else:
            score -= 15

        if price > sma_200:
            score += 10
        else:
            score -= 10

        # SMA alignment (20 pts)
        if sma_20 > sma_50 > sma_200:
            score += 20  # Perfect bull alignment
        elif sma_200 > sma_50 > sma_20:
            score -= 20  # Perfect bear alignment
        elif sma_20 > sma_50 or sma_50 > sma_200:
            score += 10  # Partial bull alignment

        # RSI momentum (20 pts)
        if rsi > 60:
            score += 15
        elif rsi < 40:
            score -= 15
        elif rsi > 50:
            score += 5
        elif rsi < 50:
            score -= 5

        # Volatility penalty (20 pts)
        if volatility > 3.0:
            score -= 20  # High volatility penalizes
        elif volatility > 2.0:
            score -= 10
        elif volatility < 1.0:
            score += 5  # Low volatility slight bonus

        return max(-100, min(100, score))

    def _map_score_to_regime(self, score: float) -> dict[str, Any]:
        """Map regime score to regime type and strategy parameters."""
        if score >= 60:
            return {
                "regime": "BULL_STRONG",
                "confidence": 0.85 + (score - 60) / 400,  # 0.85-0.95
                "trend": "UP",
                "strength": "STRONG",
                "volatility_regime": "LOW" if score > 80 else "MEDIUM",
                "weight_multiplier": 1.3,
                "min_confidence": 0.65,
                "exposure_pct": 90,
            }
        elif score >= 20:
            return {
                "regime": "BULL_WEAK",
                "confidence": 0.65 + (score - 20) / 200,  # 0.65-0.85
                "trend": "UP",
                "strength": "WEAK",
                "volatility_regime": "MEDIUM",
                "weight_multiplier": 1.1,
                "min_confidence": 0.70,
                "exposure_pct": 75,
            }
        elif score >= -20:
            return {
                "regime": "SIDEWAYS",
                "confidence": 0.50 + abs(score) / 100,  # 0.50-0.70
                "trend": "FLAT",
                "strength": "NEUTRAL",
                "volatility_regime": "MEDIUM",
                "weight_multiplier": 0.9,
                "min_confidence": 0.75,
                "exposure_pct": 60,
            }
        elif score >= -60:
            return {
                "regime": "BEAR_WEAK",
                "confidence": 0.60 + (abs(score) - 20) / 200,  # 0.60-0.80
                "trend": "DOWN",
                "strength": "WEAK",
                "volatility_regime": "MEDIUM",
                "weight_multiplier": 0.7,
                "min_confidence": 0.80,
                "exposure_pct": 40,
            }
        else:  # score < -60
            return {
                "regime": "BEAR_STRONG",
                "confidence": 0.80 + (abs(score) - 60) / 400,  # 0.80-0.90
                "trend": "DOWN",
                "strength": "STRONG",
                "volatility_regime": "HIGH",
                "weight_multiplier": 0.5,
                "min_confidence": 0.85,
                "exposure_pct": 20,
            }

    def _std_dev(self, values: list[float]) -> float:
        """Compute standard deviation of a list of values."""
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5

    async def get_current_regime(self) -> Optional[dict[str, Any]]:
        """Get the current market regime classification.

        Returns:
            Dict with regime info, or None if no classification available
        """
        regime_doc = await db.market_regime.find_one({"is_current": True})
        return regime_doc if regime_doc else None


# Global singleton
regime_classifier = RegimeClassifier()
