"""Intraday AI Engine — Claude analysis tuned for day trading.

Key differences from the long-term AIAnalysisEngine:
- System prompt focused on 1-min/5-min charts, VWAP, Supertrend, ORB, CPR
- Max 5 tool iterations (faster, cheaper — Claude confirms, doesn't discover)
- Uses 3 new intraday-specific tools: get_intraday_indicators, get_opening_range,
  get_gap_analysis  (plus existing get_stock_quote, get_micro_signal_summary)
- Returns TradeSignal with time_horizon="intraday"

Entry flow:
  Python rules detect a potential trigger (fast, no API cost)
      → IntradayEngine.analyze_entry() is called ONLY to confirm the setup
            → Claude fetches VWAP/Supertrend/ORB, validates the setup
                  → Returns TradeSignal with entry, SL, target, quantity
"""

import json
import logging
import time
from datetime import datetime
from math import floor
from typing import Any, Optional

import anthropic

from src.config import settings
from src.models.analysis import ActionType, AnalysisResult, AnalysisType, TradeSignal
from src.models.intraday import IntradayORBData
from src.utils.exceptions import AIAnalysisError

logger = logging.getLogger(__name__)

# Tools available to the intraday AI (subset + 3 new intraday-specific tools)
INTRADAY_TOOL_DEFINITIONS = [
    {
        "name": "get_stock_quote",
        "description": "Get real-time quote for a stock: LTP, OHLC, volume, day change, circuit limits.",
        "input_schema": {
            "type": "object",
            "properties": {
                "trading_symbol": {"type": "string"},
                "exchange": {"type": "string", "enum": ["NSE", "BSE"]},
            },
            "required": ["trading_symbol"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_micro_signal_summary",
        "description": (
            "Get the last 15 minutes of 10-second tick data for a stock. "
            "Shows direction (UP/DOWN/FLAT), 1-min momentum, volume spike, consecutive ticks. "
            "Use to confirm entry momentum BEFORE deciding."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"trading_symbol": {"type": "string"}},
            "required": ["trading_symbol"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_intraday_indicators",
        "description": (
            "Get intraday-specific technical indicators for a symbol: "
            "Supertrend (5-min chart, period=10, multiplier=3), "
            "VWAP with +/-1 SD bands (from today's 5-min candles), "
            "and CPR levels (pivot, BC, TC, R1, R2, S1, S2). "
            "Use this as your primary tool to assess intraday bias."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"trading_symbol": {"type": "string"}},
            "required": ["trading_symbol"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_opening_range",
        "description": (
            "Get Opening Range Breakout (ORB) data: high/low of first 15 minutes (9:15–9:29), "
            "current breakout status (UP/DOWN/NONE), and breakout strength %. "
            "A confirmed ORB breakout with volume is one of the most reliable intraday setups."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"trading_symbol": {"type": "string"}},
            "required": ["trading_symbol"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_gap_analysis",
        "description": (
            "Get gap analysis: overnight gap% from prev close to today's open, "
            "gap type (GAP_UP/GAP_DOWN/FLAT), gap fill price, and whether gap has been filled. "
            "Gap direction often sets the intraday bias for the first half of the session."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"trading_symbol": {"type": "string"}},
            "required": ["trading_symbol"],
            "additionalProperties": False,
        },
    },
]

INTRADAY_SYSTEM_PROMPT = """\
You are an expert NSE intraday trader with deep expertise in price action and momentum.
You analyze 1-minute and 5-minute charts using: VWAP, Supertrend, ORB breakout, CPR levels.

Your trading rules (non-negotiable):
1. NEVER enter after 2:30 PM IST (market closes at 3:30 PM — too risky)
2. Stop-loss MUST be within 0.5% of entry price for most setups (max 1%)
3. Minimum risk-reward: 1:1.5 (target must be 1.5x the risk distance)
4. Volume confirmation required: entry should happen with volume above VWAP average
5. Market regime context is provided — be aggressive in BULL_STRONG, cautious in BEAR

Entry confirmation checklist (ALL must be true for a BUY):
- Supertrend direction is UP (or just flipped to UP)
- Price is above VWAP
- ORB breakout direction is UP (or VWAP/Supertrend combo without ORB)
- Micro-signal shows at least 2-3 consecutive UP ticks
- Not within 1% of a CPR resistance level (R1/R2)

For SELL/SHORT setups, reverse all conditions.

Position sizing formula (provided as context):
  quantity = floor(risk_per_trade_rs / abs(entry - stop_loss))
  Capped by max_position_value

Output ONLY valid JSON:
{
    "summary": "1-2 sentence setup description",
    "market_sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
    "signals": [
        {
            "trading_symbol": "SYMBOL",
            "action": "BUY" | "SELL" | "HOLD" | "SKIP",
            "confidence": 0.0 to 1.0,
            "target_price": number,
            "stop_loss": number,
            "reasoning": "Specific reasoning referencing VWAP/Supertrend/ORB data",
            "risk_level": "LOW" | "MEDIUM" | "HIGH",
            "risk_reward_ratio": number,
            "reasoning_tags": ["ORB_BREAKOUT", "VWAP_ABOVE", "SUPERTREND_UP"],
            "time_horizon": "intraday"
        }
    ],
    "key_observations": ["observation1"],
    "risks": ["risk1"]
}

If the setup is weak or rules are violated, use action "SKIP" with reasoning.
IMPORTANT: Your final response MUST be ONLY valid JSON — no markdown, no code fences."""


class IntradayAIEngine:
    """Claude AI engine tuned for intraday trading decisions."""

    def __init__(self) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def analyze_entry(
        self,
        symbol: str,
        trigger: str,
        context: dict[str, Any],
        regime: Optional[dict[str, Any]] = None,
    ) -> AnalysisResult:
        """Confirm an entry setup identified by Python rules.

        Args:
            symbol: Trading symbol.
            trigger: What triggered the check (ORB_BREAKOUT | VWAP_CROSS | SUPERTREND_FLIP).
            context: Dict with current_price, orb data, micro data, time info.
            regime: Current market regime (BULL/BEAR/SIDEWAYS) for context.

        Returns:
            AnalysisResult with a signal (BUY/SKIP) for the symbol.
        """
        # V3.0: Event risk gate — zero API cost pre-filter before Claude call
        if settings.event_risk_enabled:
            try:
                from src.services.event_risk_filter import event_risk_filter
                evt_risk = await event_risk_filter.check_entry_risk(symbol, days_ahead=1)
                if evt_risk.blocked:
                    logger.warning(
                        f"IntradayEngine: Entry BLOCKED for {symbol} — {evt_risk.reason}"
                    )
                    # Return a synthetic SKIP result (no Claude API call wasted)
                    skip_signal = TradeSignal(
                        trading_symbol=symbol,
                        action=ActionType.WATCH,
                        confidence=0.0,
                        reasoning=f" INTRADAY ENTRY BLOCKED — Event Risk: {evt_risk.reason}",
                        risk_level="HIGH",
                        event_risk=evt_risk.reason,
                    )
                    return AnalysisResult(
                        analysis_type=AnalysisType.ALERT_CHECK,
                        timestamp=datetime.now(),
                        summary=f"Entry blocked for {symbol}: {evt_risk.reason}",
                        signals=[skip_signal],
                    )
            except Exception as _ev_err:
                logger.debug(f"Event risk pre-filter skipped for {symbol}: {_ev_err}")

        now_str = context.get("time_ist", datetime.now().strftime("%H:%M IST"))
        regime_str = ""
        if regime:
            regime_str = (
                f"\nMarket Regime: {regime.get('regime', 'UNKNOWN')} "
                f"(score: {regime.get('regime_score', 0):.0f})"
            )

        risk_per_trade = settings.intraday_risk_per_trade_rs
        max_pos_value = settings.intraday_max_position_value

        prompt = (
            f"Entry trigger detected for {symbol} at {now_str}\n"
            f"Trigger type: {trigger}\n"
            f"Current price: Rs.{context.get('current_price', 0):.2f}\n"
            f"Risk per trade: Rs.{risk_per_trade}\n"
            f"Max position value: Rs.{max_pos_value}{regime_str}\n\n"
            f"Validate this intraday setup using the available tools. "
            f"Call get_intraday_indicators first, then get_opening_range and "
            f"get_micro_signal_summary. "
            f"If all entry checklist conditions are met, provide a BUY signal with "
            f"specific entry price, stop-loss (within 0.5% of entry), and target "
            f"(minimum 1.5x risk distance). "
            f"If conditions are NOT fully met, use action SKIP with clear reasoning."
        )

        return await self._run_intraday_analysis(
            user_prompt=prompt,
            analysis_type=AnalysisType.ALERT_CHECK,
        )

    async def analyze_exit(
        self,
        symbol: str,
        position_summary: str,
        exit_trigger: str,
    ) -> str:
        """Quick exit assessment — returns a plain-text recommendation.

        Not a full agentic loop — just a single Claude call for speed.
        Used when an unusual exit condition is detected (not clean SL/target).
        """
        prompt = (
            f"EXIT ASSESSMENT for active intraday position:\n{position_summary}\n\n"
            f"Exit trigger detected: {exit_trigger}\n\n"
            f"Should I exit immediately or hold? Current time: "
            f"{datetime.now().strftime('%H:%M IST')}. "
            f"Reply in 1-2 sentences only."
        )
        try:
            response = await self.client.messages.create(
                model=settings.claude_model,
                max_tokens=200,
                system=INTRADAY_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text.strip()
        except Exception as e:
            logger.error(f"IntradayAIEngine.analyze_exit error: {e}")
        return "Unable to assess — consider exiting to protect capital."

    # ----------------------------------------------------------------
    # Entry condition evaluator (pure Python, NO Claude call)
    # ----------------------------------------------------------------

    @staticmethod
    def evaluate_entry_conditions(
        symbol: str,
        current_price: float,
        prev_price: float,
        orb: Optional[IntradayORBData],
        micro: dict[str, Any],
        vwap: float,
        supertrend_direction: str,
    ) -> Optional[str]:
        """Fast pre-filter: detect potential entry trigger without Claude.

        This runs in the 1-minute monitor cycle. Claude is only called
        when this returns a non-None trigger string.

        Returns:
            Trigger name string or None.
        """
        from src.config import settings

        consecutive = micro.get("consecutive_ticks", 0)
        volume_spike = micro.get("volume_spike", False)
        min_ticks = settings.intraday_min_breakout_confirm_ticks

        # Rule 1: ORB Breakout
        if orb is not None:
            from src.utils.intraday_indicators import check_orb_breakout
            orb_result = check_orb_breakout(current_price, orb)
            if orb_result["breakout"] and orb_result["direction"] == "UP":
                if volume_spike or consecutive >= min_ticks:
                    return "ORB_BREAKOUT"

        # Rule 2: VWAP Cross (price just crossed above VWAP)
        if vwap > 0:
            from src.utils.intraday_indicators import check_vwap_cross
            cross = check_vwap_cross(prev_price, current_price, vwap)
            if cross == "BULLISH_CROSS" and consecutive >= min_ticks:
                return "VWAP_CROSS"

        # Rule 3: Supertrend just flipped to UP (detected by monitor)
        if supertrend_direction == "FLIPPED_UP" and consecutive >= 2:
            return "SUPERTREND_FLIP"

        return None

    @staticmethod
    def calculate_position_size(
        entry_price: float,
        stop_loss: float,
        risk_rs: float,
        max_position_value: float,
    ) -> int:
        """Compute number of shares to buy given risk parameters.

        Args:
            entry_price: Planned entry price.
            stop_loss: Stop-loss price.
            risk_rs: Rs. amount to risk on this trade.
            max_position_value: Hard cap on total position value.

        Returns:
            Number of shares (minimum 1, 0 if stop-loss is invalid).
        """
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance <= 0:
            return 0
        qty = floor(risk_rs / sl_distance)
        if entry_price > 0:
            max_qty_by_value = floor(max_position_value / entry_price)
            qty = min(qty, max_qty_by_value)
        return max(qty, 0)

    # ----------------------------------------------------------------
    # Core agentic loop (intraday variant — max 5 iterations)
    # ----------------------------------------------------------------

    async def _run_intraday_analysis(
        self,
        user_prompt: str,
        analysis_type: AnalysisType,
    ) -> AnalysisResult:
        """Intraday agentic loop — max 5 iterations, intraday tools only."""
        from src.tools.executor import execute_tool

        messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]
        max_iterations = 5
        iteration = 0
        start_time = time.monotonic()

        while iteration < max_iterations:
            iteration += 1
            logger.info(f"Intraday AI iteration {iteration}/{max_iterations}")

            try:
                response = await self._claude_call(messages)
            except AIAnalysisError:
                raise
            except Exception as e:
                raise AIAnalysisError(f"Intraday Claude API error: {e}") from e

            if response.stop_reason != "tool_use":
                result = self._parse_response(response, analysis_type)
                elapsed = time.monotonic() - start_time
                logger.info(f"Intraday AI done in {elapsed:.1f}s, {iteration} iterations")
                return result

            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    logger.info(f"Intraday AI tool: {block.name}({block.input})")
                    try:
                        result = await execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": (
                                json.dumps(result, default=str)
                                if isinstance(result, dict)
                                else str(result)
                            ),
                        })
                    except Exception as e:
                        logger.error(f"Intraday tool error ({block.name}): {e}")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Error: {str(e)}",
                            "is_error": True,
                        })

            messages.append({"role": "user", "content": tool_results})

        logger.warning("Intraday AI reached max iterations")
        return AnalysisResult(
            analysis_type=analysis_type,
            timestamp=datetime.now(),
            summary="Intraday analysis incomplete — max iterations reached.",
            signals=[],
        )

    async def _claude_call(self, messages: list):
        """Call Claude with intraday-specific tools and system prompt."""
        try:
            return await self.client.messages.create(
                model=settings.claude_model,
                max_tokens=1024,
                system=INTRADAY_SYSTEM_PROMPT,
                tools=INTRADAY_TOOL_DEFINITIONS,
                messages=messages,
            )
        except anthropic.APITimeoutError:
            logger.warning("Intraday Claude timeout — retrying once")
            return await self.client.messages.create(
                model=settings.claude_model,
                max_tokens=1024,
                system=INTRADAY_SYSTEM_PROMPT,
                tools=INTRADAY_TOOL_DEFINITIONS,
                messages=messages,
            )
        except anthropic.APIError as e:
            raise AIAnalysisError(f"Claude API error: {e}") from e

    def _parse_response(
        self, response: Any, analysis_type: AnalysisType
    ) -> AnalysisResult:
        """Parse Claude's JSON response into AnalysisResult."""
        import re

        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        # Extract JSON (handles code fences or extra text)
        json_match = re.search(r"\{[\s\S]*\}", text)
        if not json_match:
            return AnalysisResult(
                analysis_type=analysis_type,
                timestamp=datetime.now(),
                summary=text[:200] if text else "No response",
                signals=[],
            )

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            return AnalysisResult(
                analysis_type=analysis_type,
                timestamp=datetime.now(),
                summary="JSON parse error in intraday response",
                signals=[],
            )

        signals: list[TradeSignal] = []
        for s in data.get("signals", []):
            try:
                action_str = s.get("action", "HOLD").upper()
                if action_str == "SKIP":
                    action_str = "HOLD"  # SKIP maps to HOLD in TradeSignal model
                action = ActionType(action_str) if action_str in ActionType.__members__ else ActionType.HOLD
                confidence = max(0.0, min(1.0, float(s.get("confidence", 0.5))))

                # Compute risk/reward if not provided
                rr = s.get("risk_reward_ratio")
                if rr is None:
                    entry = s.get("target_price", 0) or 0
                    target = s.get("target_price", 0) or 0
                    sl = s.get("stop_loss", 0) or 0
                    current = 0
                    if sl and target and entry:
                        risk = abs(entry - sl)
                        reward = abs(target - entry)
                        rr = round(reward / risk, 2) if risk > 0 else None

                signals.append(TradeSignal(
                    trading_symbol=s.get("trading_symbol", ""),
                    action=action,
                    confidence=confidence,
                    target_price=s.get("target_price"),
                    stop_loss=s.get("stop_loss"),
                    reasoning=s.get("reasoning", ""),
                    risk_level=s.get("risk_level", "MEDIUM"),
                    risk_reward_ratio=rr,
                    reasoning_tags=s.get("reasoning_tags", []),
                    time_horizon="intraday",
                ))
            except Exception as e:
                logger.warning(f"Intraday signal parse error: {e}")

        return AnalysisResult(
            analysis_type=analysis_type,
            timestamp=datetime.now(),
            summary=data.get("summary", ""),
            signals=signals,
            market_sentiment=data.get("market_sentiment"),
            key_observations=data.get("key_observations", []),
            risks=data.get("risks", []),
            raw_response=text,
        )


# Singleton
intraday_ai_engine = IntradayAIEngine()
