"""MongoDB database layer using PyMongo's native async client.

Provides repository methods for all collections: portfolio snapshots,
analysis logs, alerts, trade signals, and user settings.
"""

import logging
from datetime import datetime
from typing import Any, Optional

from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

from src.config import settings
from src.models.analysis import AlertMessage, AnalysisResult, TradeSignal
from src.models.holdings import PortfolioSnapshot

logger = logging.getLogger(__name__)


class Database:
    """Async MongoDB database wrapper with repository methods."""

    client: AsyncMongoClient
    db: AsyncDatabase

    # Collections
    portfolio_snapshots: AsyncCollection
    analysis_logs: AsyncCollection
    alerts_history: AsyncCollection
    trade_signals: AsyncCollection
    user_settings: AsyncCollection

    async def connect(self) -> None:
        """Initialize MongoDB connection and create indexes."""
        self.client = AsyncMongoClient(settings.mongodb_uri)
        self.db = self.client[settings.mongodb_database]

        # Bind collections
        self.portfolio_snapshots = self.db["portfolio_snapshots"]
        self.analysis_logs = self.db["analysis_logs"]
        self.alerts_history = self.db["alerts_history"]
        self.trade_signals = self.db["trade_signals"]
        self.user_settings = self.db["user_settings"]

        # Create indexes for efficient queries
        await self._create_indexes()
        logger.info(f"Connected to MongoDB: {settings.mongodb_database}")

    async def _create_indexes(self) -> None:
        """Create indexes on all collections."""
        await self.portfolio_snapshots.create_index("timestamp")
        await self.analysis_logs.create_index("timestamp")
        await self.analysis_logs.create_index("analysis_type")
        await self.alerts_history.create_index("timestamp")
        await self.trade_signals.create_index([("trading_symbol", 1), ("timestamp", -1)])
        await self.trade_signals.create_index("status")

    async def disconnect(self) -> None:
        """Close the MongoDB connection."""
        self.client.close()
        logger.info("MongoDB disconnected")

    # ----------------------------------------------------------------
    # Portfolio Snapshots
    # ----------------------------------------------------------------

    async def save_snapshot(self, snapshot: PortfolioSnapshot) -> str:
        """Save a portfolio snapshot. Returns the inserted ID."""
        doc = snapshot.model_dump(mode="json")
        result = await self.portfolio_snapshots.insert_one(doc)
        logger.debug(f"Saved portfolio snapshot: {result.inserted_id}")
        return str(result.inserted_id)

    async def get_latest_snapshot(self) -> Optional[dict[str, Any]]:
        """Get the most recent portfolio snapshot."""
        cursor = self.portfolio_snapshots.find().sort("timestamp", -1).limit(1)
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            return doc
        return None

    async def get_snapshots(
        self, start: datetime, end: datetime, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get portfolio snapshots within a time range."""
        cursor = (
            self.portfolio_snapshots.find({"timestamp": {"$gte": start.isoformat(), "$lte": end.isoformat()}})
            .sort("timestamp", -1)
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
        """Save an AI analysis result. Returns the inserted ID."""
        doc = result.model_dump(mode="json")
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
        cursor = self.analysis_logs.find(query).sort("timestamp", -1).limit(1)
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            return doc
        return None

    async def get_analysis_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent analysis logs."""
        cursor = self.analysis_logs.find().sort("timestamp", -1).limit(limit)
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    # ----------------------------------------------------------------
    # Alerts
    # ----------------------------------------------------------------

    async def save_alert(self, alert: AlertMessage) -> str:
        """Save an alert record. Returns the inserted ID."""
        doc = alert.model_dump(mode="json")
        res = await self.alerts_history.insert_one(doc)
        return str(res.inserted_id)

    async def get_recent_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent alerts, newest first."""
        cursor = self.alerts_history.find().sort("timestamp", -1).limit(limit)
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    # ----------------------------------------------------------------
    # Trade Signals
    # ----------------------------------------------------------------

    async def save_signal(self, signal: dict[str, Any]) -> str:
        """Save a trade signal. Returns the inserted ID."""
        signal.setdefault("status", "ACTIVE")
        signal.setdefault("timestamp", datetime.now().isoformat())
        res = await self.trade_signals.insert_one(signal)
        return str(res.inserted_id)

    async def get_signals_for_symbol(
        self, symbol: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get recent signals for a specific trading symbol."""
        cursor = (
            self.trade_signals.find({"trading_symbol": symbol})
            .sort("timestamp", -1)
            .limit(limit)
        )
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    async def get_active_signals(self) -> list[dict[str, Any]]:
        """Get all active (non-expired) trade signals."""
        cursor = self.trade_signals.find({"status": "ACTIVE"}).sort("timestamp", -1)
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    # ----------------------------------------------------------------
    # User Settings
    # ----------------------------------------------------------------

    async def get_user_settings(self) -> dict[str, Any]:
        """Get user settings, creating defaults if not exists."""
        doc = await self.user_settings.find_one({"_id": "default"})
        if doc:
            return doc

        # Create default settings
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
            {"_id": "default"},
            {"$set": updates},
            upsert=True,
        )
        logger.info(f"Updated user settings: {list(updates.keys())}")


# Singleton instance
db = Database()
