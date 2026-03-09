"""Tool executor — dispatches Claude tool calls to actual implementations.

Maps tool names to service methods and handles parameter extraction.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from src.services.database import db
from src.services.groww_service import groww_service
from src.services.market_data import market_data_service
from src.services.outcome_tracker import outcome_tracker

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

        case "get_micro_signal_summary":
            try:
                from src.services.micro_monitor import micro_monitor
                symbol = tool_input["trading_symbol"]
                summary = micro_monitor.get_context_for_claude(symbol)
                live = micro_monitor.get_live_status()
                detail = live.get(symbol, {})
                return {
                    "symbol": symbol,
                    "summary": summary,
                    "direction": detail.get("direction", "FLAT"),
                    "velocity_pct": detail.get("velocity", 0),
                    "momentum_1m": detail.get("momentum_1m", 0),
                    "consecutive_ticks": detail.get("consecutive", 0),
                    "volume_spike": detail.get("volume_spike", False),
                }
            except Exception as e:
                return {"error": f"Micro signal data unavailable: {e}"}

        case "get_sector_performance":
            sector = tool_input["sector"]
            days = min(tool_input.get("days", 5), 30)
            try:
                import json as _json
                nse_file = "nse_symbols.json"
                sector_symbols: list[str] = []
                try:
                    with open(nse_file, "r", encoding="utf-8") as _f:
                        universe = _json.load(_f)
                    sector_symbols = [
                        u["symbol"] for u in universe if u.get("sector") == sector
                    ][:10]  # cap at 10 for performance
                except Exception:
                    pass

                if not sector_symbols:
                    return {"error": f"No symbols found for sector: {sector}"}

                prices = await groww_service.get_bulk_ltp(sector_symbols)
                results = []
                for sym in sector_symbols:
                    price = groww_service.find_price(prices, sym)
                    if price:
                        results.append({"symbol": sym, "current_price": price})

                return {
                    "sector": sector,
                    "days_analyzed": days,
                    "stocks": results,
                    "count": len(results),
                }
            except Exception as e:
                return {"error": f"Sector performance unavailable: {e}"}

        case "get_peer_comparison":
            symbol = tool_input["trading_symbol"]
            sector = tool_input.get("sector", "")
            try:
                import json as _json
                peers: list[str] = []
                try:
                    with open("nse_symbols.json", "r", encoding="utf-8") as _f:
                        universe = _json.load(_f)
                    peers = [
                        u["symbol"]
                        for u in universe
                        if u.get("sector") == sector and u["symbol"] != symbol
                    ][:5]
                except Exception:
                    pass

                compare_symbols = [symbol] + peers
                prices = await groww_service.get_bulk_ltp(compare_symbols)

                comparison = []
                for sym in compare_symbols:
                    price = groww_service.find_price(prices, sym)
                    if not price:
                        continue
                    try:
                        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        start_time = (datetime.now() - timedelta(days=90)).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                        candles = await groww_service.get_historical_candles(
                            trading_symbol=sym,
                            exchange="NSE",
                            segment="CASH",
                            start_time=start_time,
                            end_time=end_time,
                            interval_minutes=1440,
                        )
                        if candles and len(candles) >= 6:
                            from src.utils.indicators import compute_rsi
                            closes = [float(c.close) for c in candles if c.close]
                            rsi = compute_rsi(closes, 14)
                            five_day_return = (
                                (closes[-1] - closes[-6]) / closes[-6] * 100
                                if closes[-6] > 0
                                else 0
                            )
                            comparison.append({
                                "symbol": sym,
                                "is_target": sym == symbol,
                                "current_price": price,
                                "rsi": round(rsi, 1) if rsi else None,
                                "five_day_return_pct": round(five_day_return, 2),
                            })
                    except Exception:
                        comparison.append({"symbol": sym, "is_target": sym == symbol, "current_price": price})

                return {
                    "target_symbol": symbol,
                    "sector": sector,
                    "comparison": comparison,
                }
            except Exception as e:
                return {"error": f"Peer comparison unavailable: {e}"}

        case "screen_stocks":
            try:
                from src.services.screener import screener_engine
                top_n = min(tool_input.get("top_n", 10), 20)
                candidates = await screener_engine.run_full_screen()
                top = candidates[:top_n]
                return {
                    "candidates": [c.to_dict() for c in top],
                    "total_screened": len(candidates),
                    "top_n": top_n,
                }
            except Exception as e:
                return {"error": f"Screener unavailable: {e}"}

        case "get_signal_performance":
            days = min(tool_input.get("days", 30), 365)
            try:
                statistics = await outcome_tracker.get_signal_statistics(days)
                if statistics is None:
                    return {
                        "error": f"No signal outcome data available for the last {days} days. "
                        "Outcome tracking may be newly enabled or no signals have been closed yet."
                    }
                return {
                    "period_days": statistics.period_days,
                    "total_signals": statistics.total_signals,
                    "open_signals": statistics.open_signals,
                    "closed_signals": statistics.closed_signals,
                    "wins": statistics.wins,
                    "losses": statistics.losses,
                    "breakevens": statistics.breakevens,
                    "win_rate_pct": round(statistics.win_rate, 2),
                    "avg_pnl_pct": round(statistics.avg_pnl_pct, 2),
                    "total_pnl_pct": round(statistics.total_pnl_pct, 2),
                    "max_win_pct": round(statistics.max_win_pct, 2),
                    "max_loss_pct": round(statistics.max_loss_pct, 2),
                    "avg_confidence_wins": round(statistics.avg_confidence_wins, 3),
                    "avg_confidence_losses": round(statistics.avg_confidence_losses, 3),
                    "confidence_correlation": round(statistics.confidence_correlation, 3),
                    "target_hit_rate_pct": round(statistics.target_hit_rate * 100, 2) if statistics.target_hit_rate else None,
                    "stop_loss_hit_rate_pct": round(statistics.stop_loss_hit_rate * 100, 2) if statistics.stop_loss_hit_rate else None,
                    "avg_hold_hours": round(statistics.avg_hold_hours, 1) if statistics.avg_hold_hours else None,
                    "interpretation": (
                        f"Over the last {days} days: {statistics.win_rate:.1f}% win rate, "
                        f"avg P&L {statistics.avg_pnl_pct:+.2f}%. "
                        f"Confidence correlation: {statistics.confidence_correlation:+.3f} "
                        f"({'positive - higher confidence signals perform better' if statistics.confidence_correlation > 0.05 else 'negative or neutral - confidence scores may need recalibration'})."
                    )
                }
            except Exception as e:
                logger.error(f"Error fetching signal performance: {e}", exc_info=True)
                return {"error": f"Signal performance data unavailable: {e}"}

        case _:
            logger.warning(f"Unknown tool called: {tool_name}")
            return f"Unknown tool: {tool_name}"
