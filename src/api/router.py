"""FastAPI REST API routes.

V2 improvements:
- Optional X-API-Key authentication (set API_KEY in .env to enable)
- Pagination (offset + limit on all list endpoints)
- New endpoints: /micro-signals, /screener/results, /screener/run, /ai/usage
- CORS configured in main.py
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from src.config import settings
from src.services.database import db

router = APIRouter()


# ----------------------------------------------------------------
# Optional API Key auth dependency
# ----------------------------------------------------------------

async def verify_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    """Validate X-API-Key header if API_KEY is configured in settings."""
    if not settings.api_key:
        return  # Auth disabled
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")


# ----------------------------------------------------------------
# Portfolio & Analysis
# ----------------------------------------------------------------

@router.get("/portfolio")
async def get_portfolio(_: None = Depends(verify_api_key)):
    """Get the latest portfolio snapshot."""
    snapshot = await db.get_latest_snapshot()
    return snapshot or {"error": "No portfolio data available"}


@router.get("/analysis/latest")
async def get_latest_analysis(
    analysis_type: Optional[str] = None,
    _: None = Depends(verify_api_key),
):
    """Get the most recent analysis, optionally filtered by type."""
    result = await db.get_latest_analysis(analysis_type=analysis_type)
    return result or {"error": "No analysis available"}


@router.get("/analysis/history")
async def get_analysis_history(
    limit: int = 20,
    offset: int = 0,
    _: None = Depends(verify_api_key),
):
    """Get analysis history with pagination."""
    return await db.get_analysis_history(limit=limit, offset=offset)


# ----------------------------------------------------------------
# Alerts
# ----------------------------------------------------------------

@router.get("/alerts")
async def get_alerts(
    limit: int = 50,
    offset: int = 0,
    _: None = Depends(verify_api_key),
):
    """Get recent alerts with pagination."""
    return await db.get_recent_alerts(limit=limit, offset=offset)


# ----------------------------------------------------------------
# Trade Signals
# ----------------------------------------------------------------

@router.get("/signals")
async def get_signals(_: None = Depends(verify_api_key)):
    """Get all active trade signals."""
    return await db.get_active_signals()


@router.get("/signals/{symbol}")
async def get_signals_for_symbol(
    symbol: str,
    limit: int = 10,
    offset: int = 0,
    _: None = Depends(verify_api_key),
):
    """Get signals for a specific trading symbol."""
    return await db.get_signals_for_symbol(symbol.upper(), limit=limit, offset=offset)


@router.post("/analyze/{symbol}")
async def trigger_analysis(
    symbol: str,
    _: None = Depends(verify_api_key),
):
    """Trigger an on-demand AI analysis for a specific stock."""
    from src.services.ai_engine import ai_engine
    result = await ai_engine.analyze_stock(symbol.upper())
    await db.save_analysis(result)
    return result.model_dump(mode="json")


# ----------------------------------------------------------------
# Settings
# ----------------------------------------------------------------

@router.get("/settings")
async def get_settings(_: None = Depends(verify_api_key)):
    """Get current user settings."""
    return await db.get_user_settings()


@router.put("/settings")
async def update_settings(
    updates: dict,
    _: None = Depends(verify_api_key),
):
    """Update user settings."""
    await db.update_user_settings(updates)
    return {"status": "ok", "updated": list(updates.keys())}


# ----------------------------------------------------------------
# Micro Signals (Phase 2)
# ----------------------------------------------------------------

@router.get("/micro-signals")
async def get_micro_signals(
    limit: int = 50,
    symbol: Optional[str] = None,
    _: None = Depends(verify_api_key),
):
    """Get recent micro-signals (10-sec polling alerts)."""
    return await db.get_recent_micro_signals(
        limit=limit,
        symbol=symbol.upper() if symbol else None,
    )


# ----------------------------------------------------------------
# Screener (Phase 3)
# ----------------------------------------------------------------

@router.get("/screener/results")
async def get_screener_results(_: None = Depends(verify_api_key)):
    """Get the latest stock screener results."""
    result = await db.get_latest_screener_result()
    return result or {"error": "No screener results yet. POST /screener/run to trigger one."}


@router.post("/screener/run")
async def run_screener(_: None = Depends(verify_api_key)):
    """Trigger an on-demand stock screener run."""
    try:
        from src.services.screener import screener_engine
        from src.services.ai_engine import ai_engine
        from datetime import datetime

        candidates = await screener_engine.run_full_screen()
        top = candidates[:settings.screener_top_n]
        if not top:
            return {"status": "no_candidates", "message": "Screener found no qualifying stocks"}

        analysis = await ai_engine.analyze_screener_candidates([c.to_dict() for c in top])
        result_doc = {
            "timestamp": datetime.now(),
            "candidates": [c.to_dict() for c in top],
            "claude_analysis": analysis.model_dump(mode="json"),
        }
        await db.save_screener_result(result_doc)
        return {"status": "ok", "candidates_found": len(top)}
    except ImportError:
        return {"status": "unavailable", "message": "Screener module not yet active"}


# ----------------------------------------------------------------
# AI Usage (Phase 4)
# ----------------------------------------------------------------

@router.get("/ai/usage")
async def get_ai_usage(
    days: int = 7,
    _: None = Depends(verify_api_key),
):
    """Get Claude API token usage and cost summary for the last N days."""
    return await db.get_ai_usage_summary(days=days)


# ----------------------------------------------------------------
# Intraday Trading (v2.2)
# ----------------------------------------------------------------

@router.get("/intraday/watchlist")
async def get_intraday_watchlist(
    _=None,
):
    """Get today intraday watchlist from pre-market scan."""
    try:
        from src.services.intraday_scanner import intraday_scanner
        setups = await intraday_scanner.get_today_watchlist()
        return {"watchlist": [s.model_dump() for s in setups], "count": len(setups)}
    except Exception as e:
        return {"error": str(e)}


@router.get("/intraday/positions")
async def get_intraday_positions(
    _=None,
):
    """Get active intraday positions with live P&L."""
    try:
        from src.services.intraday_monitor import intraday_monitor
        return {"positions": intraday_monitor.get_active_positions()}
    except Exception as e:
        return {"error": str(e)}


@router.get("/intraday/pnl")
async def get_intraday_pnl(
    _=None,
):
    """Get today intraday P&L report."""
    try:
        from src.services.intraday_scanner import intraday_scanner
        report = await intraday_scanner.generate_daily_report()
        return report.model_dump()
    except Exception as e:
        return {"error": str(e)}


@router.get("/intraday/risk")
async def get_intraday_risk(
    _=None,
):
    """Get intraday risk status."""
    try:
        from src.services.intraday_monitor import intraday_monitor
        return intraday_monitor.get_risk_status()
    except Exception as e:
        return {"error": str(e)}


@router.post("/intraday/scan")
async def trigger_intraday_scan(
    _=None,
):
    """Trigger on-demand intraday pre-market scan."""
    try:
        from src.services.intraday_scanner import intraday_scanner
        from src.services.intraday_monitor import intraday_monitor
        setups = await intraday_scanner.run_premarket_scan()
        await intraday_monitor.load_watchlist()
        return {"status": "ok", "candidates_found": len(setups)}
    except Exception as e:
        return {"error": str(e)}


# ----------------------------------------------------------------
# V3.0 Endpoints — Event Risk (Phase 3C)
# ----------------------------------------------------------------

@router.get("/events")
async def get_events_for_holdings(_: None = Depends(verify_api_key)):
    """Get upcoming corporate events for all current holdings."""
    try:
        from src.services.event_risk_filter import event_risk_filter
        from src.services.groww_service import groww_service
        holdings = await groww_service.get_holdings()
        symbols = [h.trading_symbol for h in holdings]
        events = await event_risk_filter.get_events_for_holdings(symbols, days_ahead=14)
        return {
            "symbols_checked": len(symbols),
            "symbols_with_events": len(events),
            "events": {
                sym: [
                    {
                        "event_type": e.event_type,
                        "event_date": e.event_date.isoformat(),
                        "description": e.description,
                        "days_until": (__import__("datetime").date.today() - e.event_date).days * -1,
                    }
                    for e in evts
                ]
                for sym, evts in events.items()
            },
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/events/{symbol}")
async def get_events_for_symbol(
    symbol: str,
    days_ahead: int = 30,
    _: None = Depends(verify_api_key),
):
    """Get upcoming corporate events for a specific symbol."""
    try:
        from src.services.event_risk_filter import event_risk_filter
        sym = symbol.upper()
        events = await event_risk_filter.get_events_for_holdings([sym], days_ahead=days_ahead)
        risk = await event_risk_filter.check_entry_risk(sym, days_ahead=days_ahead)
        return {
            "symbol": sym,
            "days_ahead": days_ahead,
            "entry_blocked": risk.blocked,
            "block_reason": risk.reason,
            "events": [
                {
                    "event_type": e.event_type,
                    "event_date": e.event_date.isoformat(),
                    "description": e.description,
                }
                for e in events.get(sym, [])
            ],
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/events/refresh")
async def refresh_event_calendar(_: None = Depends(verify_api_key)):
    """Trigger an on-demand refresh of the NSE corporate event calendar."""
    try:
        from src.services.event_risk_filter import event_risk_filter
        saved = await event_risk_filter.refresh_calendar()
        return {
            "status": "ok",
            "events_saved": saved,
            "cache_size": event_risk_filter.cache_size,
            "last_refresh": event_risk_filter.last_refresh.isoformat() if event_risk_filter.last_refresh else None,
        }
    except Exception as e:
        return {"error": str(e)}


# ----------------------------------------------------------------
# V3.0 Endpoints — Signal Calibration (Phase 3A)
# ----------------------------------------------------------------

@router.get("/calibration")
async def get_calibration(_: None = Depends(verify_api_key)):
    """Get the latest confidence calibration statistics."""
    try:
        from src.services.signal_calibrator import signal_calibrator
        cal = await signal_calibrator.get_current_calibration()
        if not cal:
            return {"error": "No calibration data yet. Run nightly_calibration_job first."}
        return cal.model_dump(mode="json")
    except ImportError:
        return {"error": "Signal calibrator not yet available"}
    except Exception as e:
        return {"error": str(e)}


@router.get("/calibration/patterns")
async def get_calibration_patterns(
    limit: int = 20,
    _: None = Depends(verify_api_key),
):
    """Get top-performing reasoning tag patterns by win rate."""
    try:
        from src.services.signal_calibrator import signal_calibrator
        patterns = await signal_calibrator.get_top_patterns(limit=limit)
        return {"patterns": [p.model_dump(mode="json") for p in patterns]}
    except ImportError:
        return {"error": "Signal calibrator not yet available"}
    except Exception as e:
        return {"error": str(e)}


# ----------------------------------------------------------------
# V3.0 Endpoints — Capital Allocation (Phase 3B)
# ----------------------------------------------------------------

@router.get("/allocation")
async def get_allocation_report(_: None = Depends(verify_api_key)):
    """Get full portfolio allocation report: beta, sectors, correlation pairs."""
    try:
        from src.services.capital_allocator import capital_allocator
        report = await capital_allocator.get_full_allocation_report()
        return report.model_dump(mode="json")
    except ImportError:
        return {"error": "Capital allocator not yet available"}
    except Exception as e:
        return {"error": str(e)}


@router.post("/allocation/kelly")
async def compute_kelly(
    body: dict,
    _: None = Depends(verify_api_key),
):
    """Compute Kelly-optimal position size for a given trade.

    Body: { trading_symbol, action, confidence, entry_price, stop_loss, target_price }
    """
    try:
        from src.services.capital_allocator import capital_allocator
        result = await capital_allocator.get_kelly_recommendation(
            symbol=body["trading_symbol"],
            action=body["action"],
            confidence=float(body["confidence"]),
            entry_price=float(body["entry_price"]),
            stop_loss=float(body["stop_loss"]),
            target_price=float(body["target_price"]),
        )
        return result.model_dump(mode="json")
    except ImportError:
        return {"error": "Capital allocator not yet available"}
    except Exception as e:
        return {"error": str(e)}
