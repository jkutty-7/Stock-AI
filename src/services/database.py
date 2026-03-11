"""MongoDB database layer using PyMongo's native async client.

V2 improvements:
- Bug fix #8: All timestamps stored/queried as BSON datetime (not ISO strings)
- TTL indexes on alerts_history (90 days) and trade_signals (30 days)
- Pagination support (offset parameter)
- New collections: system_config, micro_signals, screener_results, ai_usage_logs
- update_signal_status() method
- get_snapshots_range() with proper datetime queries
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

from src.config import settings
from src.models.analysis import AlertMessage, AnalysisResult
from src.models.holdings import PortfolioSnapshot

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


def _ensure_tz(dt: datetime) -> datetime:
    """Ensure a datetime has UTC timezone info."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class Database:
    """Async MongoDB database wrapper with repository methods."""

    client: AsyncMongoClient
    db: AsyncDatabase

    portfolio_snapshots: AsyncCollection
    analysis_logs: AsyncCollection
    alerts_history: AsyncCollection
    trade_signals: AsyncCollection
    user_settings: AsyncCollection
    system_config: AsyncCollection
    micro_signals: AsyncCollection
    screener_results: AsyncCollection
    ai_usage_logs: AsyncCollection
    signal_outcomes: AsyncCollection  # v2.1: Signal outcome tracking
    portfolio_peaks: AsyncCollection  # v2.1: Portfolio peak tracking for drawdown breaker
    circuit_breaker_state: AsyncCollection  # v2.1: Circuit breaker state
    market_regime: AsyncCollection  # v2.1: Market regime classification

    async def connect(self) -> None:
        """Initialize MongoDB connection and create indexes."""
        self.client = AsyncMongoClient(settings.mongodb_uri)
        self.db = self.client[settings.mongodb_database]

        self.portfolio_snapshots = self.db["portfolio_snapshots"]
        self.analysis_logs = self.db["analysis_logs"]
        self.alerts_history = self.db["alerts_history"]
        self.trade_signals = self.db["trade_signals"]
        self.user_settings = self.db["user_settings"]
        self.system_config = self.db["system_config"]
        self.micro_signals = self.db["micro_signals"]
        self.screener_results = self.db["screener_results"]
        self.ai_usage_logs = self.db["ai_usage_logs"]
        self.signal_outcomes = self.db["signal_outcomes"]  # v2.1
        self.portfolio_peaks = self.db["portfolio_peaks"]  # v2.1
        self.circuit_breaker_state = self.db["circuit_breaker_state"]  # v2.1
        self.market_regime = self.db["market_regime"]  # v2.1

        await self._create_indexes()
        logger.info(f"Connected to MongoDB: {settings.mongodb_database}")

    async def _create_indexes(self) -> None:
        """Create indexes (idempotent). TTL indexes handle automatic expiration.

        v2.1 improvements: Added compound indexes for query performance,
        increased trade_signals TTL to 90 days for outcome tracking.
        """
        # Portfolio snapshots
        await self.portfolio_snapshots.create_index([("timestamp", DESCENDING)])
        await self.portfolio_snapshots.create_index([("total_pnl_pct", DESCENDING)])

        # Analysis logs
        await self.analysis_logs.create_index([("timestamp", DESCENDING)])
        await self.analysis_logs.create_index([("analysis_type", ASCENDING)])
        await self.analysis_logs.create_index(
            [("analysis_type", ASCENDING), ("timestamp", DESCENDING)]
        )

        # Alerts — TTL 90 days
        await self.alerts_history.create_index(
            [("trading_symbol", ASCENDING), ("timestamp", DESCENDING)]
        )
        await self.alerts_history.create_index([("alert_type", ASCENDING)])
        await self._create_ttl_index(
            self.alerts_history, "timestamp", 90 * 86400, "alerts_ttl"
        )

        # Trade signals — TTL increased to 90 days (was 30) for outcome tracking
        await self.trade_signals.create_index(
            [("trading_symbol", ASCENDING), ("timestamp", DESCENDING)]
        )
        await self.trade_signals.create_index([("status", ASCENDING)])
        await self.trade_signals.create_index([("confidence", DESCENDING)])
        await self.trade_signals.create_index([("expires_at", ASCENDING)])
        await self._create_ttl_index(
            self.trade_signals, "timestamp", 90 * 86400, "signals_ttl"
        )

        # Micro signals — TTL 24 hours
        await self.micro_signals.create_index([("symbol", ASCENDING), ("timestamp", DESCENDING)])
        await self._create_ttl_index(
            self.micro_signals, "timestamp", 86400, "micro_ttl"
        )

        # Screener results — TTL 30 days
        await self._create_ttl_index(
            self.screener_results, "timestamp", 30 * 86400, "screener_ttl"
        )

        # AI usage logs — TTL 90 days
        await self._create_ttl_index(
            self.ai_usage_logs, "timestamp", 90 * 86400, "ai_usage_ttl"
        )

        # Signal outcomes — TTL 365 days (1 year for backtesting)
        await self.signal_outcomes.create_index(
            [("trading_symbol", ASCENDING), ("signal_timestamp", DESCENDING)]
        )
        await self.signal_outcomes.create_index([("status", ASCENDING)])
        await self.signal_outcomes.create_index([("win_loss", ASCENDING)])
        await self._create_ttl_index(
            self.signal_outcomes, "timestamp", 365 * 86400, "outcomes_ttl"
        )

        # Portfolio peaks — TTL 90 days (Feature 3: Drawdown Breaker)
        await self.portfolio_peaks.create_index([("timestamp", DESCENDING)])
        await self.portfolio_peaks.create_index([("is_current_peak", ASCENDING)])
        await self._create_ttl_index(
            self.portfolio_peaks, "timestamp", 90 * 86400, "peaks_ttl"
        )

        # Circuit breaker state — no TTL (persistent state, small collection)
        # Note: _id field already has a unique index by default, no additional index needed

        # Market regime — TTL 365 days (Feature 4: Regime Classifier)
        await self.market_regime.create_index([("date", DESCENDING)], unique=True)
        await self.market_regime.create_index([("is_current", ASCENDING)])
        await self._create_ttl_index(
            self.market_regime, "timestamp", 365 * 86400, "regime_ttl"
        )

    async def _create_ttl_index(
        self,
        collection: AsyncCollection,
        field: str,
        expire_seconds: int,
        index_name: str,
    ) -> None:
        """Create a TTL index, handling conflicts by dropping old indexes first."""
        from pymongo.errors import OperationFailure

        try:
            await collection.create_index(
                [(field, ASCENDING)],
                expireAfterSeconds=expire_seconds,
                name=index_name,
            )
        except OperationFailure as e:
            if e.code == 85:  # IndexOptionsConflict
                logger.info(
                    f"Dropping conflicting index on {collection.name}.{field} to recreate with TTL"
                )
                # Drop all indexes on this field and recreate
                indexes = await collection.index_information()
                for idx_name, idx_info in indexes.items():
                    # Check if this index uses our field
                    if idx_name != "_id_" and any(
                        key == field for key, _ in idx_info.get("key", [])
                    ):
                        await collection.drop_index(idx_name)
                        logger.debug(f"Dropped index {idx_name}")
                # Now create the TTL index
                await collection.create_index(
                    [(field, ASCENDING)],
                    expireAfterSeconds=expire_seconds,
                    name=index_name,
                )
                logger.info(f"Created TTL index {index_name} on {collection.name}.{field}")
            else:
                raise

    async def disconnect(self) -> None:
        """Close the MongoDB connection."""
        await self.client.aclose()
        logger.info("MongoDB disconnected")

    # ----------------------------------------------------------------
    # Portfolio Snapshots
    # ----------------------------------------------------------------

    async def save_snapshot(self, snapshot: PortfolioSnapshot) -> str:
        """Save a portfolio snapshot with BSON datetime timestamps."""
        doc = snapshot.model_dump(mode="python")
        if isinstance(doc.get("timestamp"), datetime):
            doc["timestamp"] = _ensure_tz(doc["timestamp"])
        result = await self.portfolio_snapshots.insert_one(doc)
        logger.debug(f"Saved portfolio snapshot: {result.inserted_id}")
        return str(result.inserted_id)

    async def get_latest_snapshot(self) -> Optional[dict[str, Any]]:
        """Get the most recent portfolio snapshot."""
        cursor = self.portfolio_snapshots.find().sort("timestamp", DESCENDING).limit(1)
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            return doc
        return None

    async def get_snapshots_range(
        self, start: datetime, end: datetime, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Get snapshots in a time range. Bug fix #8: uses datetime objects, not strings."""
        cursor = (
            self.portfolio_snapshots
            .find({"timestamp": {"$gte": _ensure_tz(start), "$lte": _ensure_tz(end)}})
            .sort("timestamp", DESCENDING)
            .skip(offset)
            .limit(limit)
        )
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    # ----------------------------------------------------------------
    # Analysis Logs
    # ----------------------------------------------------------------

    async def save_analysis(self, result: AnalysisResult) -> str:
        """Save an AI analysis result."""
        doc = result.model_dump(mode="python")
        if isinstance(doc.get("timestamp"), datetime):
            doc["timestamp"] = _ensure_tz(doc["timestamp"])
        res = await self.analysis_logs.insert_one(doc)
        logger.debug(f"Saved analysis log: {res.inserted_id}")
        return str(res.inserted_id)

    async def get_latest_analysis(
        self, analysis_type: str | None = None
    ) -> Optional[dict[str, Any]]:
        """Get the most recent analysis, optionally filtered by type."""
        query: dict[str, Any] = {}
        if analysis_type:
            query["analysis_type"] = analysis_type
        cursor = self.analysis_logs.find(query).sort("timestamp", DESCENDING).limit(1)
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            return doc
        return None

    async def get_analysis_history(
        self, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Get recent analysis logs with pagination."""
        cursor = (
            self.analysis_logs.find()
            .sort("timestamp", DESCENDING)
            .skip(offset)
            .limit(limit)
        )
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    # ----------------------------------------------------------------
    # Alerts
    # ----------------------------------------------------------------

    async def save_alert(self, alert: AlertMessage) -> str:
        """Save an alert record."""
        doc = alert.model_dump(mode="python")
        if isinstance(doc.get("timestamp"), datetime):
            doc["timestamp"] = _ensure_tz(doc["timestamp"])
        res = await self.alerts_history.insert_one(doc)
        return str(res.inserted_id)

    async def get_recent_alerts(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Get recent alerts, newest first, with pagination."""
        cursor = (
            self.alerts_history.find()
            .sort("timestamp", DESCENDING)
            .skip(offset)
            .limit(limit)
        )
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    # ----------------------------------------------------------------
    # Trade Signals
    # ----------------------------------------------------------------

    async def save_signal(self, signal: dict[str, Any]) -> str:
        """Save a trade signal with BSON datetime."""
        signal = dict(signal)
        signal.setdefault("status", "ACTIVE")
        ts = signal.get("timestamp")
        if ts is None or isinstance(ts, str):
            signal["timestamp"] = _utcnow()
        elif isinstance(ts, datetime):
            signal["timestamp"] = _ensure_tz(ts)
        res = await self.trade_signals.insert_one(signal)
        return str(res.inserted_id)

    async def update_signal_status(self, signal_id: str, status: str) -> None:
        """Update trade signal status (ACTIVE → TRIGGERED / EXPIRED / CANCELLED)."""
        from bson import ObjectId
        await self.trade_signals.update_one(
            {"_id": ObjectId(signal_id)},
            {"$set": {"status": status, "updated_at": _utcnow()}},
        )

    async def get_signals_for_symbol(
        self, symbol: str, limit: int = 10, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Get recent signals for a specific trading symbol."""
        cursor = (
            self.trade_signals.find({"trading_symbol": symbol})
            .sort("timestamp", DESCENDING)
            .skip(offset)
            .limit(limit)
        )
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    async def get_active_signals(self) -> list[dict[str, Any]]:
        """Get all active (non-expired) trade signals."""
        cursor = self.trade_signals.find({"status": "ACTIVE"}).sort("timestamp", DESCENDING)
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    # ----------------------------------------------------------------
    # Signal Outcomes (v2.1)
    # ----------------------------------------------------------------

    async def save_signal_outcome(self, outcome: dict[str, Any]) -> str:
        """Save a signal outcome record."""
        outcome = dict(outcome)
        # Ensure timestamps are BSON datetime
        for ts_field in ["signal_timestamp", "entry_timestamp", "exit_timestamp", "timestamp"]:
            if ts_field in outcome and outcome[ts_field]:
                if isinstance(outcome[ts_field], str):
                    outcome[ts_field] = datetime.fromisoformat(outcome[ts_field])
                if isinstance(outcome[ts_field], datetime):
                    outcome[ts_field] = _ensure_tz(outcome[ts_field])

        res = await self.signal_outcomes.insert_one(outcome)
        return str(res.inserted_id)

    async def update_signal_outcome(self, outcome_id: str, updates: dict[str, Any]) -> None:
        """Update a signal outcome (e.g., when position exits)."""
        from bson import ObjectId

        # Ensure timestamp updates are BSON datetime
        if "exit_timestamp" in updates and isinstance(updates["exit_timestamp"], datetime):
            updates["exit_timestamp"] = _ensure_tz(updates["exit_timestamp"])
        if "timestamp" in updates and isinstance(updates["timestamp"], datetime):
            updates["timestamp"] = _ensure_tz(updates["timestamp"])
        else:
            updates["timestamp"] = _utcnow()

        await self.signal_outcomes.update_one(
            {"_id": ObjectId(outcome_id)},
            {"$set": updates},
        )

    async def get_outcomes_by_status(self, status: str, limit: int = 100) -> list[dict[str, Any]]:
        """Get outcomes filtered by status (OPEN, CLOSED, EXPIRED, CANCELLED)."""
        cursor = (
            self.signal_outcomes.find({"status": status})
            .sort("signal_timestamp", DESCENDING)
            .limit(limit)
        )
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    async def get_outcomes_by_symbol(
        self, symbol: str, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Get signal outcomes for a specific trading symbol."""
        cursor = (
            self.signal_outcomes.find({"trading_symbol": symbol})
            .sort("signal_timestamp", DESCENDING)
            .skip(offset)
            .limit(limit)
        )
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    async def get_signal_statistics(self, days: int = 30) -> dict[str, Any]:
        """Aggregate signal outcome statistics for the last N days."""
        from datetime import timedelta

        cutoff = _utcnow() - timedelta(days=days)

        pipeline = [
            {"$match": {"signal_timestamp": {"$gte": cutoff}}},
            {
                "$group": {
                    "_id": None,
                    "total_signals": {"$sum": 1},
                    "open_signals": {
                        "$sum": {"$cond": [{"$eq": ["$status", "OPEN"]}, 1, 0]}
                    },
                    "closed_signals": {
                        "$sum": {"$cond": [{"$eq": ["$status", "CLOSED"]}, 1, 0]}
                    },
                    "wins": {
                        "$sum": {"$cond": [{"$eq": ["$win_loss", "WIN"]}, 1, 0]}
                    },
                    "losses": {
                        "$sum": {"$cond": [{"$eq": ["$win_loss", "LOSS"]}, 1, 0]}
                    },
                    "breakevens": {
                        "$sum": {"$cond": [{"$eq": ["$win_loss", "BREAKEVEN"]}, 1, 0]}
                    },
                    "avg_pnl_pct": {"$avg": "$pnl_pct"},
                    "total_pnl_pct": {"$sum": "$pnl_pct"},
                    "max_win_pct": {"$max": "$pnl_pct"},
                    "max_loss_pct": {"$min": "$pnl_pct"},
                    "avg_confidence": {"$avg": "$original_confidence"},
                }
            },
        ]

        async for doc in self.signal_outcomes.aggregate(pipeline):
            doc.pop("_id", None)
            # Calculate win rate
            closed = doc.get("closed_signals", 0)
            wins = doc.get("wins", 0)
            doc["win_rate"] = (wins / closed * 100) if closed > 0 else 0.0
            return doc

        # Return empty stats if no outcomes
        return {
            "total_signals": 0,
            "open_signals": 0,
            "closed_signals": 0,
            "wins": 0,
            "losses": 0,
            "breakevens": 0,
            "win_rate": 0.0,
            "avg_pnl_pct": 0.0,
            "total_pnl_pct": 0.0,
            "max_win_pct": 0.0,
            "max_loss_pct": 0.0,
            "avg_confidence": 0.0,
        }

    # ----------------------------------------------------------------
    # Micro Signals
    # ----------------------------------------------------------------

    async def save_micro_signal(self, signal: dict[str, Any]) -> str:
        """Save a micro-signal alert. Auto-deleted after 24h via TTL index."""
        signal = dict(signal)
        ts = signal.get("timestamp")
        if ts is None or isinstance(ts, str):
            signal["timestamp"] = _utcnow()
        elif isinstance(ts, datetime):
            signal["timestamp"] = _ensure_tz(ts)
        res = await self.micro_signals.insert_one(signal)
        return str(res.inserted_id)

    async def get_recent_micro_signals(
        self, limit: int = 50, symbol: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Get recent micro-signals, optionally filtered by symbol."""
        query: dict[str, Any] = {}
        if symbol:
            query["symbol"] = symbol
        cursor = self.micro_signals.find(query).sort("timestamp", DESCENDING).limit(limit)
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    # ----------------------------------------------------------------
    # Screener Results
    # ----------------------------------------------------------------

    async def save_screener_result(self, result: dict[str, Any]) -> str:
        """Save a screener run result."""
        result = dict(result)
        ts = result.get("timestamp")
        if ts is None or isinstance(ts, str):
            result["timestamp"] = _utcnow()
        elif isinstance(ts, datetime):
            result["timestamp"] = _ensure_tz(ts)
        res = await self.screener_results.insert_one(result)
        return str(res.inserted_id)

    async def get_latest_screener_result(self) -> Optional[dict[str, Any]]:
        """Get the most recent screener result."""
        cursor = self.screener_results.find().sort("timestamp", DESCENDING).limit(1)
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            return doc
        return None

    # ----------------------------------------------------------------
    # AI Usage Logs
    # ----------------------------------------------------------------

    async def save_ai_usage(self, usage: dict[str, Any]) -> str:
        """Log Claude API token/cost usage."""
        usage = dict(usage)
        ts = usage.get("timestamp")
        if ts is None or isinstance(ts, str):
            usage["timestamp"] = _utcnow()
        elif isinstance(ts, datetime):
            usage["timestamp"] = _ensure_tz(ts)
        res = await self.ai_usage_logs.insert_one(usage)
        return str(res.inserted_id)

    async def get_ai_usage_summary(self, days: int = 7) -> dict[str, Any]:
        """Aggregate AI usage for the last N days."""
        from datetime import timedelta
        cutoff = _utcnow() - timedelta(days=days)
        pipeline = [
            {"$match": {"timestamp": {"$gte": cutoff}}},
            {
                "$group": {
                    "_id": None,
                    "total_calls": {"$sum": 1},
                    "total_input_tokens": {"$sum": "$input_tokens"},
                    "total_output_tokens": {"$sum": "$output_tokens"},
                    "total_cost_usd": {"$sum": "$cost_usd"},
                    "avg_duration_ms": {"$avg": "$duration_ms"},
                }
            },
        ]
        async for doc in self.ai_usage_logs.aggregate(pipeline):
            doc.pop("_id", None)
            return doc
        return {
            "total_calls": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": 0.0,
            "avg_duration_ms": 0.0,
        }

    # ----------------------------------------------------------------
    # User Settings
    # ----------------------------------------------------------------

    async def get_user_settings(self) -> dict[str, Any]:
        """Get user settings, creating defaults if not exists."""
        doc = await self.user_settings.find_one({"_id": "default"})
        if doc:
            return doc
        defaults = {
            "_id": "default",
            "pnl_alert_threshold_pct": settings.pnl_alert_threshold_pct,
            "portfolio_alert_threshold_pct": settings.portfolio_alert_threshold_pct,
            "monitoring_enabled": True,
            "analysis_frequency_minutes": settings.monitor_interval_minutes,
            "preferred_analysis_depth": "detailed",
            "watchlist": [],
            "telegram_notifications_enabled": True,
        }
        await self.user_settings.insert_one(defaults)
        return defaults

    async def update_user_settings(self, updates: dict[str, Any]) -> None:
        """Update user settings."""
        await self.user_settings.update_one(
            {"_id": "default"}, {"$set": updates}, upsert=True
        )
        logger.info(f"Updated user settings: {list(updates.keys())}")

    # ----------------------------------------------------------------
    # System Config
    # ----------------------------------------------------------------

    async def get_system_config(self, key: str) -> Optional[Any]:
        """Get a system configuration value."""
        doc = await self.system_config.find_one({"_id": key})
        return doc.get("value") if doc else None

    async def set_system_config(self, key: str, value: Any) -> None:
        """Set a system configuration value."""
        await self.system_config.update_one(
            {"_id": key},
            {"$set": {"value": value, "updated_at": _utcnow()}},
            upsert=True,
        )


# Singleton instance
db = Database()
