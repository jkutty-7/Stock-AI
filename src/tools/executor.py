"""Tool executor — dispatches Claude tool calls to actual implementations.

Maps tool names to service methods and handles parameter extraction.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from src.services.database import db
from src.services.groww_service import groww_service
from src.services.market_data import market_data_service

logger = logging.getLogger(__name__)


async def execute_tool(tool_name: str, tool_input: dict[str, Any]) -> dict | str:
    """Dispatch a tool call from Claude to the appropriate service method.

    Args:
        tool_name: Name of the tool to execute.
        tool_input: Tool input parameters from Claude.

    Returns:
        Tool result as a dict or string.
    """
    match tool_name:
        case "get_portfolio_holdings":
            holdings = await groww_service.get_holdings()
            return {"holdings": [h.model_dump() for h in holdings]}

        case "get_stock_quote":
            quote = await groww_service.get_quote(
                trading_symbol=tool_input["trading_symbol"],
                exchange=tool_input.get("exchange", "NSE"),
            )
            return quote.model_dump()

        case "get_bulk_prices":
            prices = await groww_service.get_bulk_ltp(tool_input["trading_symbols"])
            return {"prices": prices}

        case "get_historical_data":
            days = tool_input["days_back"]
            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            start_time = (datetime.now() - timedelta(days=days)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            candles = await groww_service.get_historical_candles(
                trading_symbol=tool_input["trading_symbol"],
                exchange="NSE",
                segment="CASH",
                start_time=start_time,
                end_time=end_time,
                interval_minutes=tool_input["interval_minutes"],
            )
            return {
                "symbol": tool_input["trading_symbol"],
                "interval_minutes": tool_input["interval_minutes"],
                "candles": [c.model_dump(mode="json") for c in candles],
                "count": len(candles),
            }

        case "get_technical_indicators":
            result = await market_data_service.get_enriched_quote(
                tool_input["trading_symbol"]
            )
            return {
                "quote": result["quote"].model_dump(),
                "indicators": result["indicators"].model_dump(),
                "candles_analyzed": result["candles_count"],
            }

        case "get_portfolio_snapshot":
            snapshot = await db.get_latest_snapshot()
            if snapshot:
                return snapshot
            return {"error": "No portfolio snapshot available yet. Run a monitoring cycle first."}

        case "get_positions":
            positions = await groww_service.get_positions(
                segment=tool_input.get("segment")
            )
            return {"positions": [p.model_dump() for p in positions]}

        case _:
            logger.warning(f"Unknown tool called: {tool_name}")
            return f"Unknown tool: {tool_name}"
