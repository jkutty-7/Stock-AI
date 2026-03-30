"""Signal Calibrator — Phase 3A of V3.0 Intelligent Capital Architecture.

Analyses closed signal_outcomes to compute:
  1. Confidence bucket calibration  — empirical win rate per 0.1-wide confidence bucket
  2. Reasoning-tag pattern performance — win rate per combination of reasoning_tags
  3. Market-regime performance       — win rate per BULL/BEAR/SIDEWAYS regime

Results are stored in MongoDB and injected into the Claude system prompt nightly.

Usage:
    from src.services.signal_calibrator import signal_calibrator

    cal = await signal_calibrator.compute_calibration()
    context = await signal_calibrator.get_calibration_context_for_claude()
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.config import settings
from src.models.calibration import (
    CalibrationBucket,
    CalibrationData,
    PatternStats,
    RegimeStats,
)

logger = logging.getLogger(__name__)

# Confidence bucket boundaries — right-inclusive
_BUCKET_EDGES = [0.5, 0.6, 0.7, 0.8, 0.9, 1.01]  # 1.01 so 1.0 falls in last bucket
_BUCKET_LABELS = ["0.5-0.6", "0.6-0.7", "0.7-0.8", "0.8-0.9", "0.9-1.0"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SignalCalibrator:
    """Nightly calibration engine — reads signal_outcomes, writes calibration collections."""

    def __init__(self) -> None:
        self._cached_context: Optional[str] = None
        self._context_built_at: Optional[datetime] = None

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    async def compute_calibration(
        self,
        lookback_days: Optional[int] = None,
    ) -> Optional[CalibrationData]:
        """Compute confidence calibration from closed signal outcomes.

        Args:
            lookback_days: Days of history to analyse. Defaults to settings value.

        Returns:
            CalibrationData if enough data is available, None otherwise.
        """
        from src.services.database import db

        lookback = lookback_days or settings.calibration_lookback_days
        cutoff = _utcnow() - timedelta(days=lookback)

        # Fetch all CLOSED outcomes in window
        cursor = db.signal_outcomes.find(
            {
                "status": "CLOSED",
                "win_loss": {"$in": ["WIN", "LOSS", "BREAKEVEN"]},
                "signal_timestamp": {"$gte": cutoff},
                "original_confidence": {"$exists": True},
            },
        )

        # Bucket tallies: {label: {count, wins, losses}}
        buckets: dict[str, dict] = {
            label: {"count": 0, "wins": 0, "losses": 0}
            for label in _BUCKET_LABELS
        }
        total_count = 0
        total_wins = 0

        async for doc in cursor:
            conf = doc.get("original_confidence") or doc.get("confidence", 0.0)
            wl = doc.get("win_loss", "LOSS")
            label = self._bucket_label(conf)
            if label:
                buckets[label]["count"] += 1
                if wl == "WIN":
                    buckets[label]["wins"] += 1
                elif wl == "LOSS":
                    buckets[label]["losses"] += 1
            total_count += 1
            if wl == "WIN":
                total_wins += 1

        if total_count < settings.calibration_min_samples:
            logger.info(
                f"SignalCalibrator: Only {total_count} closed signals — "
                f"minimum {settings.calibration_min_samples} needed, skipping"
            )
            return None

        overall_win_rate = total_wins / total_count if total_count > 0 else 0.0

        calibration_buckets: list[CalibrationBucket] = []
        best_bucket: Optional[str] = None
        worst_bucket: Optional[str] = None
        best_wr = -1.0
        worst_wr = 2.0

        for label, stats in buckets.items():
            count = stats["count"]
            wins = stats["wins"]
            losses = stats["losses"]
            win_rate = wins / count if count > 0 else 0.0
            # Bucket midpoint for calibration error
            lo, hi = label.split("-")
            midpoint = (float(lo) + float(hi)) / 2
            cal_error = abs(midpoint - win_rate)

            calibration_buckets.append(
                CalibrationBucket(
                    bucket=label,
                    count=count,
                    wins=wins,
                    losses=losses,
                    win_rate=win_rate,
                    calibration_error=cal_error,
                )
            )

            if count >= settings.calibration_min_samples:
                if win_rate > best_wr:
                    best_wr = win_rate
                    best_bucket = label
                if win_rate < worst_wr:
                    worst_wr = win_rate
                    worst_bucket = label

        calibration = CalibrationData(
            computed_at=_utcnow(),
            lookback_days=lookback,
            overall_win_rate=overall_win_rate,
            total_signals_analyzed=total_count,
            buckets=calibration_buckets,
            best_bucket=best_bucket,
            worst_bucket=worst_bucket,
            is_current=True,
        )

        # Mark previous calibrations as not current
        await db.confidence_calibration.update_many(
            {"is_current": True}, {"$set": {"is_current": False}}
        )
        # Insert new calibration
        await db.confidence_calibration.insert_one(calibration.model_dump(mode="python"))
        logger.info(
            f"SignalCalibrator: Calibration saved — {total_count} signals, "
            f"overall win rate {overall_win_rate:.1%}"
        )

        # Invalidate cached context so it's rebuilt on next call
        self._cached_context = None
        return calibration

    async def compute_pattern_performance(self) -> list[PatternStats]:
        """Compute win rates per reasoning_tags combination.

        Returns:
            List of PatternStats sorted by win_rate descending.
        """
        from src.services.database import db

        lookback = settings.calibration_lookback_days
        cutoff = _utcnow() - timedelta(days=lookback)

        cursor = db.signal_outcomes.find(
            {
                "status": "CLOSED",
                "win_loss": {"$in": ["WIN", "LOSS"]},
                "signal_timestamp": {"$gte": cutoff},
                "reasoning_tags": {"$exists": True, "$ne": []},
            },
        )

        pattern_stats: dict[str, dict] = {}

        async for doc in cursor:
            tags = doc.get("reasoning_tags", [])
            if not tags:
                continue
            key = "+".join(sorted(tags))
            wl = doc.get("win_loss", "LOSS")
            pnl = doc.get("pnl_pct", 0.0) or 0.0

            if key not in pattern_stats:
                pattern_stats[key] = {
                    "tags": sorted(tags),
                    "count": 0,
                    "wins": 0,
                    "pnl_sum": 0.0,
                }
            pattern_stats[key]["count"] += 1
            if wl == "WIN":
                pattern_stats[key]["wins"] += 1
            pattern_stats[key]["pnl_sum"] += pnl

        results: list[PatternStats] = []
        for key, stats in pattern_stats.items():
            count = stats["count"]
            if count < settings.calibration_min_samples:
                continue
            wins = stats["wins"]
            win_rate = wins / count
            avg_pnl = stats["pnl_sum"] / count

            ps = PatternStats(
                pattern_key=key,
                tags=stats["tags"],
                count=count,
                wins=wins,
                win_rate=win_rate,
                avg_pnl_pct=avg_pnl,
            )
            results.append(ps)

            # Upsert into pattern_performance collection
            await db.pattern_performance.update_one(
                {"pattern_key": key},
                {"$set": ps.model_dump(mode="python")},
                upsert=True,
            )

        results.sort(key=lambda x: x.win_rate, reverse=True)
        logger.info(f"SignalCalibrator: {len(results)} patterns computed")
        return results

    async def compute_regime_performance(self) -> list[RegimeStats]:
        """Compute win rates per market regime.

        Joins signal_outcomes with market_regime by date overlap.

        Returns:
            List of RegimeStats.
        """
        from src.services.database import db

        lookback = settings.calibration_lookback_days
        cutoff = _utcnow() - timedelta(days=lookback)

        # Build a date → regime map from market_regime collection
        regime_map: dict[str, str] = {}
        regime_cursor = db.market_regime.find(
            {"timestamp": {"$gte": cutoff}},
            {"date": 1, "regime": 1},
        )
        async for doc in regime_cursor:
            raw_date = doc.get("date")
            if isinstance(raw_date, datetime):
                date_str = raw_date.date().isoformat()
            elif isinstance(raw_date, str):
                date_str = raw_date[:10]
            else:
                continue
            regime_map[date_str] = doc.get("regime", "UNKNOWN")

        if not regime_map:
            logger.info("SignalCalibrator: No regime data available — skipping regime performance")
            return []

        cursor = db.signal_outcomes.find(
            {
                "status": "CLOSED",
                "win_loss": {"$in": ["WIN", "LOSS"]},
                "signal_timestamp": {"$gte": cutoff},
            },
        )

        regime_stats: dict[str, dict] = {}

        async for doc in cursor:
            ts = doc.get("signal_timestamp")
            if isinstance(ts, datetime):
                date_str = ts.date().isoformat()
            elif isinstance(ts, str):
                date_str = ts[:10]
            else:
                continue

            regime = regime_map.get(date_str)
            if not regime:
                continue

            wl = doc.get("win_loss", "LOSS")
            pnl = doc.get("pnl_pct", 0.0) or 0.0
            hold_hours = doc.get("hold_hours")

            if regime not in regime_stats:
                regime_stats[regime] = {
                    "count": 0, "wins": 0, "pnl_sum": 0.0, "hold_hours_sum": 0.0, "hold_count": 0
                }
            regime_stats[regime]["count"] += 1
            if wl == "WIN":
                regime_stats[regime]["wins"] += 1
            regime_stats[regime]["pnl_sum"] += pnl
            if hold_hours is not None:
                regime_stats[regime]["hold_hours_sum"] += hold_hours
                regime_stats[regime]["hold_count"] += 1

        results: list[RegimeStats] = []
        for regime, stats in regime_stats.items():
            count = stats["count"]
            if count < settings.calibration_min_samples:
                continue
            wins = stats["wins"]
            win_rate = wins / count
            avg_pnl = stats["pnl_sum"] / count
            avg_hold = (
                stats["hold_hours_sum"] / stats["hold_count"]
                if stats["hold_count"] > 0
                else None
            )

            rs = RegimeStats(
                regime=regime,
                count=count,
                wins=wins,
                win_rate=win_rate,
                avg_pnl_pct=avg_pnl,
                avg_hold_hours=avg_hold,
            )
            results.append(rs)

            await db.regime_signal_performance.update_one(
                {"regime": regime},
                {"$set": rs.model_dump(mode="python")},
                upsert=True,
            )

        logger.info(f"SignalCalibrator: {len(results)} regime performance records computed")
        return results

    async def get_current_calibration(self) -> Optional[CalibrationData]:
        """Return the latest calibration snapshot from MongoDB."""
        from src.services.database import db
        doc = await db.confidence_calibration.find_one(
            {"is_current": True},
            sort=[("computed_at", -1)],
        )
        if not doc:
            return None
        doc.pop("_id", None)
        return CalibrationData(**doc)

    async def get_top_patterns(self, limit: int = 20) -> list[PatternStats]:
        """Return top-performing reasoning tag patterns, sorted by win rate."""
        from src.services.database import db
        cursor = (
            db.pattern_performance.find()
            .sort([("win_rate", -1), ("count", -1)])
            .limit(limit)
        )
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            try:
                results.append(PatternStats(**doc))
            except Exception:
                continue
        return results

    async def get_calibration_for_tool(
        self,
        confidence_level: Optional[float] = None,
        reasoning_tags: Optional[list[str]] = None,
    ) -> dict:
        """Tool executor helper — returns calibration data formatted for Claude.

        Args:
            confidence_level: If provided, look up the confidence bucket.
            reasoning_tags: If provided, look up the matching pattern.

        Returns:
            Dict suitable for returning from the tool executor.
        """
        from src.services.database import db
        result: dict = {}

        # Confidence bucket lookup
        if confidence_level is not None:
            label = self._bucket_label(confidence_level)
            if label:
                cal = await self.get_current_calibration()
                if cal:
                    for bucket in cal.buckets:
                        if bucket.bucket == label:
                            result["confidence_bucket"] = label
                            result["empirical_win_rate"] = bucket.win_rate
                            result["sample_count"] = bucket.count
                            result["calibration_error"] = bucket.calibration_error
                            over_under = "over-confident" if bucket.calibration_error > 0.05 else "well-calibrated"
                            result["interpretation"] = (
                                f"Your {label} confidence signals win {bucket.win_rate:.1%} of the time "
                                f"({bucket.count} samples). You appear {over_under}."
                            )
                            break
                else:
                    result["confidence_bucket"] = label
                    result["error"] = "No calibration data yet — insufficient closed signals."

        # Pattern lookup
        if reasoning_tags:
            key = "+".join(sorted(reasoning_tags))
            doc = await db.pattern_performance.find_one({"pattern_key": key})
            if doc:
                doc.pop("_id", None)
                result["pattern_stats"] = {
                    "pattern_key": doc.get("pattern_key"),
                    "count": doc.get("count"),
                    "win_rate": doc.get("win_rate"),
                    "avg_pnl_pct": doc.get("avg_pnl_pct"),
                    "interpretation": (
                        f"The pattern {'+'.join(reasoning_tags)} has won "
                        f"{doc.get('win_rate', 0):.1%} of {doc.get('count', 0)} signals."
                    ),
                }
            else:
                result["pattern_stats"] = {
                    "error": f"No data for pattern: {'+'.join(reasoning_tags)}"
                }

        # Regime context
        cal = await self.get_current_calibration()
        if cal:
            result["overall_win_rate"] = cal.overall_win_rate
            result["total_signals_analyzed"] = cal.total_signals_analyzed
            result["best_bucket"] = cal.best_bucket
            result["worst_bucket"] = cal.worst_bucket

        return result or {"error": "No parameters provided. Pass confidence_level or reasoning_tags."}

    async def get_calibration_context_for_claude(self) -> str:
        """Build a formatted string to inject into the AI engine system prompt.

        Cached for 1 hour to avoid repeated DB reads.
        """
        # Return cached version if fresh (< 1 hour old)
        if (
            self._cached_context
            and self._context_built_at
            and (_utcnow() - self._context_built_at).total_seconds() < 3600
        ):
            return self._cached_context

        try:
            cal = await self.get_current_calibration()
            if not cal:
                return ""

            lines = [
                "=== YOUR SIGNAL PERFORMANCE ===",
                f"Overall win rate: {cal.overall_win_rate:.1%} ({cal.total_signals_analyzed} closed signals, last {cal.lookback_days} days)",
                "",
                "Confidence calibration (your score → actual win rate):",
            ]
            for bucket in cal.buckets:
                if bucket.count >= settings.calibration_min_samples:
                    err_note = " ← you over-estimate" if bucket.calibration_error > 0.10 else ""
                    lines.append(
                        f"  {bucket.bucket} → {bucket.win_rate:.1%} actual "
                        f"({bucket.count} signals){err_note}"
                    )

            if cal.best_bucket:
                lines.append(f"\nYour most reliable confidence range: {cal.best_bucket}")
            if cal.worst_bucket:
                lines.append(f"Your least reliable range: {cal.worst_bucket} — raise bar here")

            # Top 3 patterns
            top_patterns = await self.get_top_patterns(limit=5)
            if top_patterns:
                lines.append("\nBest performing reasoning patterns (by win rate):")
                for p in top_patterns[:3]:
                    lines.append(
                        f"  {p.pattern_key}: {p.win_rate:.1%} win rate ({p.count} signals)"
                    )

            # Regime context from DB
            from src.services.database import db
            regime_docs = await db.regime_signal_performance.find().to_list(None)
            if regime_docs:
                lines.append("\nWin rate by market regime:")
                for doc in sorted(regime_docs, key=lambda x: x.get("win_rate", 0), reverse=True):
                    regime = doc.get("regime", "UNKNOWN")
                    wr = doc.get("win_rate", 0)
                    count = doc.get("count", 0)
                    if count >= settings.calibration_min_samples:
                        lines.append(f"  {regime}: {wr:.1%} ({count} signals)")

            lines.append("=== END SIGNAL PERFORMANCE ===")
            context = "\n".join(lines)

            self._cached_context = context
            self._context_built_at = _utcnow()
            return context

        except Exception as e:
            logger.warning(f"SignalCalibrator: Could not build context string: {e}")
            return ""

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _bucket_label(confidence: float) -> Optional[str]:
        """Map a confidence value to its bucket label."""
        for i in range(len(_BUCKET_EDGES) - 1):
            if _BUCKET_EDGES[i] <= confidence < _BUCKET_EDGES[i + 1]:
                return _BUCKET_LABELS[i]
        return None


# ─── Singleton ────────────────────────────────────────────────────────────────
signal_calibrator = SignalCalibrator()
