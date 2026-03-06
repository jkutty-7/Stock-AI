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

        await self._create_indexes()
        logger.info(f"Connected to MongoDB: {settings.mongodb_database}")

    async def _create_indexes(self) -> None:
        """Create indexes (idempotent). TTL indexes handle automatic expiration."""
        await self.portfolio_snapshots.create_index([("timestamp", DESCENDING)])
        await self.analysis_logs.create_index([("timestamp", DESCENDING)])
        await self.analysis_logs.create_index([("analysis_type", ASCENDING)])

        # Alerts — TTL 90 days
        await self.alerts_history.create_index([("timestamp", DESCENDING)])
        await self.alerts_history.create_index(
            [("timestamp", ASCENDING)], expireAfterSeconds=90 * 86400, name="alerts_ttl"
        )

        # Trade signals — TTL 30 days
        await self.trade_signals.create_index(
            [("trading_symbol", ASCENDING), ("timestamp", DESCENDING)]
        )
        await self.trade_signals.create_index([("status", ASCENDING)])
        await self.trade_signals.create_index(
            [("timestamp", ASCENDING)], expireAfterSeconds=30 * 86400, name="signals_ttl"
        )

        # Micro signals — TTL 24 hours
        await self.micro_signals.create_index([("symbol", ASCENDING), ("timestamp", DESCENDING)])
        await self.micro_signals.create_index(
            [("timestamp", ASCENDING)], expireAfterSeconds=86400, name="micro_ttl"
        )

        # Screener results — TTL 30 days
        await self.screener_results.create_index([("timestamp", DESCENDING)])
        await self.screener_results.create_index(
            [("timestamp", ASCENDING)], expireAfterSeconds=30 * 86400, name="screener_ttl"
        )

        # AI usage logs — TTL 90 days
        await self.ai_usage_logs.create_index([("timestamp", DESCENDING)])
        await self.ai_usage_logs.create_index(
            [("timestamp", ASCENDING)], expireAfterSeconds=90 * 86400, name="ai_usage_ttl"
        )

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
