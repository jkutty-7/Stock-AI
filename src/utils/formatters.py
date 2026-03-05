"""Telegram message formatters.

All formatters produce HTML-formatted strings compatible with Telegram's
parse_mode="HTML". Handles Telegram's 4096 character limit by splitting.
"""

from src.models.analysis import AlertMessage, AnalysisResult, TradeSignal


def format_portfolio_summary(snapshot: dict) -> str:
    """Format a portfolio snapshot into a concise Telegram summary."""
    total_pnl = snapshot.get("total_pnl", 0)
    total_pnl_pct = snapshot.get("total_pnl_pct", 0)
    day_pnl = snapshot.get("day_pnl", 0)
    pnl_sign = "+" if total_pnl >= 0 else ""
    day_sign = "+" if day_pnl >= 0 else ""
    holdings_count = len(snapshot.get("holdings", []))

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
    """Format per-stock detail into one or more Telegram messages.

    Returns a list of HTML strings, each under 4096 chars.
    """
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

        entry = (
            f"<b>{symbol}</b>  ({qty} shares)\n"
            f"  Avg: {avg:,.2f} | CMP: {curr:,.2f}\n"
            f"  P&amp;L: {pnl_sign}{pnl:,.0f} ({pnl_sign}{pnl_pct:.1f}%)"
            f"  Day: {day_sign}{day_pct:.1f}%\n\n"
        )

        # Split if adding this entry would exceed Telegram limit
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

    # Header
    sentiment = result.market_sentiment or "N/A"
    parts.append(f"<b>AI Analysis — {result.analysis_type.value}</b>")
    parts.append(f"Sentiment: <b>{sentiment}</b>\n")

    # Summary
    parts.append(f"{result.summary}\n")

    # Signals
    if result.signals:
        parts.append("<b>Signals:</b>")
        for s in result.signals:
            confidence_pct = s.confidence * 100
            line = f"  {_action_icon(s.action.value)} <b>{s.trading_symbol}</b>: {s.action.value}"
            line += f" ({confidence_pct:.0f}% confidence, {s.risk_level} risk)"
            if s.target_price:
                line += f"\n    Target: {s.target_price:,.2f}"
            if s.stop_loss:
                line += f" | SL: {s.stop_loss:,.2f}"
            line += f"\n    {s.reasoning[:200]}"
            parts.append(line)
        parts.append("")

    # Key observations
    if result.key_observations:
        parts.append("<b>Key Observations:</b>")
        for obs in result.key_observations[:5]:
            parts.append(f"  - {obs}")
        parts.append("")

    # Risks
    if result.risks:
        parts.append("<b>Risks:</b>")
        for risk in result.risks[:5]:
            parts.append(f"  - {risk}")

    return "\n".join(parts)


def format_alert_message(alert: AlertMessage) -> str:
    """Format an alert for Telegram push notification."""
    severity_label = {
        "INFO": "[INFO]",
        "WARNING": "[WARN]",
        "CRITICAL": "[ALERT]",
    }
    label = severity_label.get(alert.severity, f"[{alert.severity}]")

    parts = [f"<b>{label} {alert.title}</b>\n"]
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


def format_inr(amount: float) -> str:
    """Format amount in Indian Rupee style with lakhs/crores notation."""
    if abs(amount) >= 1_00_00_000:
        return f"INR {amount / 1_00_00_000:,.2f} Cr"
    elif abs(amount) >= 1_00_000:
        return f"INR {amount / 1_00_000:,.2f} L"
    else:
        return f"INR {amount:,.2f}"


def _action_icon(action: str) -> str:
    """Map action type to a text indicator."""
    icons = {
        "BUY": "[BUY]",
        "SELL": "[SELL]",
        "HOLD": "[HOLD]",
        "STRONG_BUY": "[STRONG BUY]",
        "STRONG_SELL": "[STRONG SELL]",
    }
    return icons.get(action, f"[{action}]")
