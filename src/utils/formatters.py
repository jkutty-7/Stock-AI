"""Telegram message formatters.

V2 improvements:
- Bug fix #2: format_inr handles negative amounts correctly
- Bug fix #3: &amp; used only where HTML entity is needed (P&L displayed correctly)
- format_micro_alert() — new formatter for 10-second tick alerts
- format_screener_results() — new formatter for stock discovery results
- format_signal_list() — /signals command formatter
- Action icons use Unicode arrows for clarity
"""

from datetime import datetime
from typing import Any, Optional

from src.models.analysis import AlertMessage, AnalysisResult, TradeSignal


def format_portfolio_summary(snapshot: dict) -> str:
    """Format a portfolio snapshot into a concise Telegram summary."""
    total_pnl = snapshot.get("total_pnl", 0)
    total_pnl_pct = snapshot.get("total_pnl_pct", 0)
    day_pnl = snapshot.get("day_pnl", 0)
    pnl_sign = "+" if total_pnl >= 0 else ""
    day_sign = "+" if day_pnl >= 0 else ""
    holdings_count = len(snapshot.get("holdings", []))

    # Bug fix #3: P&L is written as P&amp;L so Telegram HTML renders it as P&L
    return (
        f"<b>Portfolio Status</b>\n"
        f"{'=' * 28}\n"
        f"Invested:  {format_inr(snapshot.get('total_invested', 0))}\n"
        f"Current:   {format_inr(snapshot.get('current_value', 0))}\n"
        f"P&amp;L:      {pnl_sign}{format_inr(total_pnl)} ({pnl_sign}{total_pnl_pct:.2f}%)\n"
        f"Day P&amp;L:   {day_sign}{format_inr(day_pnl)}\n"
        f"Holdings:  {holdings_count}\n"
        f"\nUpdated: {snapshot.get('timestamp', 'N/A')}"
    )


def format_holding_detail(snapshot: dict) -> list[str]:
    """Format per-stock detail into one or more Telegram messages."""
    messages: list[str] = []
    current_msg = "<b>Portfolio Details</b>\n\n"

    for h in snapshot.get("holdings", []):
        symbol = h.get("trading_symbol", "???")
        qty = h.get("quantity", 0)
        avg = h.get("average_price", 0)
        curr = h.get("current_price", 0)
        pnl = h.get("pnl", 0)
        pnl_pct = h.get("pnl_pct", 0)
        day_pct = h.get("day_change_pct", 0)
        pnl_sign = "+" if pnl >= 0 else ""
        day_sign = "+" if day_pct >= 0 else ""
        day_icon = "↗" if day_pct >= 0 else "↘"

        entry = (
            f"<b>{symbol}</b> {day_icon} ({qty} shares)\n"
            f"  Avg: {avg:,.2f} | CMP: {curr:,.2f}\n"
            f"  P&amp;L: {pnl_sign}{pnl:,.0f} ({pnl_sign}{pnl_pct:.1f}%)"
            f"  Day: {day_sign}{day_pct:.1f}%\n\n"
        )

        if len(current_msg) + len(entry) > 3900:
            messages.append(current_msg)
            current_msg = ""

        current_msg += entry

    if current_msg:
        messages.append(current_msg)

    return messages if messages else ["No holdings data available."]


def format_analysis_result(result: AnalysisResult) -> str:
    """Format an AI analysis result into a readable Telegram message."""
    parts: list[str] = []

    sentiment = result.market_sentiment or "N/A"
    sentiment_icon = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(sentiment, "⚪")
    parts.append(f"<b>AI Analysis — {result.analysis_type.value}</b>")
    parts.append(f"Sentiment: <b>{sentiment_icon} {sentiment}</b>\n")
    parts.append(f"{result.summary}\n")

    if result.signals:
        parts.append("<b>Signals:</b>")
        for s in result.signals:
            confidence_pct = s.confidence * 100
            action_icon = _action_icon(s.action.value)
            line = f"  {action_icon} <b>{s.trading_symbol}</b>: {s.action.value}"
            line += f" ({confidence_pct:.0f}% confidence, {s.risk_level} risk)"
            if s.target_price:
                line += f"\n    Target: {s.target_price:,.2f}"
            if s.stop_loss:
                line += f" | SL: {s.stop_loss:,.2f}"
            # Show more reasoning (up to 400 chars instead of 200)
            line += f"\n    {s.reasoning[:400]}"
            parts.append(line)
        parts.append("")

    if result.key_observations:
        parts.append("<b>Key Observations:</b>")
        for obs in result.key_observations[:5]:
            parts.append(f"  • {obs}")
        parts.append("")

    if result.risks:
        parts.append("<b>Risks:</b>")
        for risk in result.risks[:5]:
            parts.append(f"  ⚠ {risk}")

    return "\n".join(parts)


def format_alert_message(alert: AlertMessage) -> str:
    """Format an alert for Telegram push notification."""
    severity_icon = {
        "INFO": "ℹ",
        "WARNING": "⚠",
        "CRITICAL": "🚨",
    }
    icon = severity_icon.get(alert.severity, "📢")

    parts = [f"<b>{icon} {alert.title}</b>\n"]
    parts.append(alert.body)

    if alert.signal:
        s = alert.signal
        parts.append(f"\nAction: {s.action.value} | Confidence: {s.confidence * 100:.0f}%")
        if s.target_price:
            parts.append(f"Target: {s.target_price:,.2f}")
        if s.stop_loss:
            parts.append(f"Stop-Loss: {s.stop_loss:,.2f}")

    parts.append(f"\n<i>{alert.timestamp.strftime('%H:%M:%S IST')}</i>")
    return "\n".join(parts)


def format_micro_alert(signal: dict) -> str:
    """Format a 10-second micro-signal alert for Telegram.

    Args:
        signal: MicroSignal dict with keys: symbol, direction, velocity_pct,
                momentum_1m, volume_spike, current_price, consecutive_ticks.
    """
    symbol = signal.get("symbol", "???")
    direction = signal.get("direction", "FLAT")
    velocity = signal.get("velocity_pct", 0.0)
    momentum = signal.get("momentum_1m", 0.0)
    volume_spike = signal.get("volume_spike", False)
    price = signal.get("current_price", 0.0)
    ticks = signal.get("consecutive_ticks", 0)

    dir_icon = "↗" if direction == "UP" else "↘" if direction == "DOWN" else "→"
    vel_sign = "+" if velocity >= 0 else ""
    mom_sign = "+" if momentum >= 0 else ""

    parts = [
        f"<b>⚡ MICRO ALERT — {symbol}</b>",
        f"Direction: {dir_icon} {direction} ({ticks} consecutive ticks)",
        f"Velocity:  {vel_sign}{velocity:.2f}% in 10s",
        f"Price:     ₹{price:,.2f}",
        f"Momentum (1m): {mom_sign}{momentum:.2f}%",
        f"Volume Spike: {'YES ⚠' if volume_spike else 'No'}",
        f"<i>{datetime.now().strftime('%H:%M:%S IST')}</i>",
    ]
    return "\n".join(parts)


def format_screener_results(result: dict) -> str:
    """Format stock screener/opportunity results for Telegram."""
    candidates = result.get("candidates", [])
    ts = result.get("timestamp", datetime.now())
    if isinstance(ts, datetime):
        ts_str = ts.strftime("%Y-%m-%d %H:%M IST")
    else:
        ts_str = str(ts)

    parts = [f"<b>📊 Stock Opportunities — {ts_str}</b>\n"]

    if not candidates:
        parts.append("No candidates found in this screening run.")
        return "\n".join(parts)

    for i, c in enumerate(candidates[:10], 1):
        symbol = c.get("symbol", "???")
        score = c.get("score", 0)
        signals_list = c.get("signals", [])
        rec = c.get("claude_recommendation", {})
        action = rec.get("action", "WATCH") if isinstance(rec, dict) else "WATCH"
        action_icon = _action_icon(action)
        signals_str = ", ".join(signals_list[:3]) if signals_list else "—"

        parts.append(
            f"{i}. {action_icon} <b>{symbol}</b> (Score: {score:.0f}/100)\n"
            f"   Signals: {signals_str}"
        )
        if isinstance(rec, dict) and rec.get("reasoning"):
            parts.append(f"   {rec['reasoning'][:120]}")
        parts.append("")

    return "\n".join(parts)


def format_signal_list(signals: list[dict]) -> str:
    """Format active trade signals for /signals command."""
    if not signals:
        return "No active signals."

    parts = ["<b>Active Trade Signals</b>\n"]
    for s in signals[:15]:
        symbol = s.get("trading_symbol", "???")
        action = s.get("action", "HOLD")
        confidence = s.get("confidence", 0) * 100
        target = s.get("target_price")
        sl = s.get("stop_loss")
        ts = s.get("timestamp", "")

        line = f"{_action_icon(action)} <b>{symbol}</b>: {action} ({confidence:.0f}%)"
        if target:
            line += f" | T: {target:,.2f}"
        if sl:
            line += f" | SL: {sl:,.2f}"
        parts.append(line)
        parts.append(f"  <i>{str(ts)[:16]}</i>\n")

    return "\n".join(parts)


def format_inr(amount: float) -> str:
    """Format amount in Indian Rupee style.

    Bug fix #2: Handles negative amounts correctly by preserving sign
    in the formatted string while using abs() for scale comparison.
    """
    sign = "-" if amount < 0 else ""
    abs_amount = abs(amount)

    if abs_amount >= 1_00_00_000:
        return f"{sign}INR {abs_amount / 1_00_00_000:,.2f} Cr"
    elif abs_amount >= 1_00_000:
        return f"{sign}INR {abs_amount / 1_00_000:,.2f} L"
    else:
        return f"{sign}INR {abs_amount:,.2f}"


def _action_icon(action: str) -> str:
    """Map action type to a Unicode arrow indicator."""
    icons = {
        "BUY": "↗",
        "SELL": "↘",
        "HOLD": "→",
        "STRONG_BUY": "⬆",
        "STRONG_SELL": "⬇",
        "WATCH": "👁",
        "SKIP": "✗",
    }
    return icons.get(action, f"[{action}]")
