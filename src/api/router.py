"""FastAPI REST API routes for future web dashboard integration."""

from fastapi import APIRouter

from src.services.database import db

router = APIRouter()


@router.get("/portfolio")
async def get_portfolio():
    """Get the latest portfolio snapshot."""
    snapshot = await db.get_latest_snapshot()
    return snapshot or {"error": "No portfolio data available"}


@router.get("/analysis/latest")
async def get_latest_analysis(analysis_type: str | None = None):
    """Get the most recent analysis, optionally filtered by type."""
    result = await db.get_latest_analysis(analysis_type=analysis_type)
    return result or {"error": "No analysis available"}


@router.get("/analysis/history")
async def get_analysis_history(limit: int = 20):
    """Get analysis history."""
    return await db.get_analysis_history(limit=limit)


@router.get("/alerts")
async def get_alerts(limit: int = 50):
    """Get recent alerts."""
    return await db.get_recent_alerts(limit=limit)


@router.get("/signals")
async def get_signals():
    """Get active trade signals."""
    return await db.get_active_signals()


@router.get("/signals/{symbol}")
async def get_signals_for_symbol(symbol: str, limit: int = 10):
    """Get signals for a specific trading symbol."""
    return await db.get_signals_for_symbol(symbol.upper(), limit=limit)


@router.post("/analyze/{symbol}")
async def trigger_analysis(symbol: str):
    """Trigger an on-demand AI analysis for a specific stock."""
    from src.services.ai_engine import ai_engine

    result = await ai_engine.analyze_stock(symbol.upper())
    await db.save_analysis(result)
    return result.model_dump(mode="json")


@router.get("/settings")
async def get_settings():
    """Get current user settings."""
    return await db.get_user_settings()


@router.put("/settings")
async def update_settings(updates: dict):
    """Update user settings."""
    await db.update_user_settings(updates)
    return {"status": "ok", "updated": list(updates.keys())}
