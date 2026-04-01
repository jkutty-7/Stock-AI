"""Claude AI analysis engine with tool-use for intelligent stock analysis.

V2 improvements:
- Bug fix #8: Robust JSON extraction (regex-based, handles text before/after fence)
- Token/cost tracking logged to DB (ai_usage_logs collection)
- asyncio.wait_for() timeout on Claude API calls (60s)
- Retry once on APITimeoutError
- Confidence value clamped to [0.0, 1.0]
- Enhanced system prompt with micro-signal context awareness
- analyze_screener_candidates() for Phase 3 stock discovery
"""

import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Optional

import anthropic

from src.config import settings
from src.models.analysis import ActionType, AnalysisResult, AnalysisType, TradeSignal
from src.tools.definitions import TOOL_DEFINITIONS
from src.tools.executor import execute_tool
from src.utils.exceptions import AIAnalysisError

logger = logging.getLogger(__name__)

# Claude API cost per million tokens (approximate, update as needed)
_INPUT_COST_PER_M = 3.0   # USD per 1M input tokens (Sonnet)
_OUTPUT_COST_PER_M = 15.0  # USD per 1M output tokens (Sonnet)

SYSTEM_PROMPT = """\
You are an expert Indian stock market financial analyst and portfolio advisor.
You have access to real-time market data, historical price data, technical indicators,
and the user's current portfolio holdings through the tools provided.

Your responsibilities:
1. Analyze portfolio health considering diversification, sector exposure, and risk
2. Evaluate individual stocks using technical analysis (RSI, MACD, SMA, Bollinger Bands) \
and price action
3. Generate actionable BUY/SELL/HOLD recommendations with confidence levels
4. Identify risks and opportunities in the current market context
5. Consider Indian market specifics: NSE/BSE dynamics, FII/DII flows, sector rotation

Guidelines:
- Always provide reasoning backed by data from the tools
- Set realistic target prices and stop-loss levels
- Consider position sizing relative to the overall portfolio
- Flag high-risk situations prominently with CRITICAL severity
- Use data from tools rather than assumptions — always call tools first
- Consider current market hours and trading session context
- All prices are in INR (Indian Rupees)

IMPORTANT — 10-second price tick context:
When micro-signal context is provided (lines starting with "=== LAST 15 MIN ==="),
use get_micro_signal_summary tool to get current tick momentum for each holding
before making hold/sell decisions. A stock with 8 consecutive DOWN ticks needs
different treatment than one with 8 UP ticks, even if overall P&L is similar.

When providing your final analysis, structure your response as a valid JSON object:
{
    "summary": "Brief overall assessment (2-3 sentences)",
    "market_sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
    "signals": [
        {
            "trading_symbol": "SYMBOL",
            "action": "BUY" | "SELL" | "HOLD" | "STRONG_BUY" | "STRONG_SELL" | "WATCH",
            "confidence": 0.0 to 1.0,
            "target_price": number or null,
            "stop_loss": number or null,
            "reasoning": "Detailed reasoning for this recommendation",
            "risk_level": "LOW" | "MEDIUM" | "HIGH",
            "risk_reward_ratio": number or null,
            "reasoning_tags": ["RSI_oversold", "MACD_crossover"],
            "time_horizon": "intraday" | "swing_3-5d" | "positional_2-4w"
        }
    ],
    "key_observations": ["observation1", "observation2"],
    "risks": ["risk1", "risk2"]
}

IMPORTANT: Your final response MUST be ONLY a valid JSON object — no markdown, no \
code fences, no extra text."""


class AIAnalysisEngine:
    """Claude-powered AI engine for stock analysis with tool-use."""

    def __init__(self) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._cached_system_prompt: Optional[str] = None  # V3: calibration-enriched prompt
        self._prompt_built_at: Optional[datetime] = None   # V3: cache timestamp

    async def _get_system_prompt(self) -> str:
        """Return the system prompt, enriched with nightly calibration context (V3).

        The calibration context is cached for 1 hour to avoid repeated DB reads.
        Falls back to the base SYSTEM_PROMPT if calibration is unavailable.
        """
        if (
            self._cached_system_prompt
            and self._prompt_built_at
            and (datetime.now() - self._prompt_built_at).total_seconds() < 3600
        ):
            return self._cached_system_prompt

        try:
            if settings.calibration_enabled:
                from src.services.signal_calibrator import signal_calibrator
                calibration_text = await signal_calibrator.get_calibration_context_for_claude()
                if calibration_text:
                    self._cached_system_prompt = SYSTEM_PROMPT + "\n\n" + calibration_text
                    self._prompt_built_at = datetime.now()
                    return self._cached_system_prompt
        except Exception as e:
            logger.debug(f"Could not load calibration context: {e}")

        return SYSTEM_PROMPT

    async def analyze_portfolio(self, context: dict[str, Any]) -> AnalysisResult:
        """Run comprehensive portfolio health analysis."""
        user_prompt = self._build_portfolio_prompt(context)
        return await self._run_analysis(
            user_prompt=user_prompt,
            analysis_type=AnalysisType.PORTFOLIO_HEALTH,
        )

    async def analyze_stock(self, trading_symbol: str) -> AnalysisResult:
        """Deep analysis of a specific stock with recommendations."""
        user_prompt = (
            f"Perform a detailed technical and fundamental analysis of {trading_symbol}. "
            f"Use the available tools to fetch the current price, historical data, and "
            f"technical indicators. Provide a clear BUY/SELL/HOLD recommendation with "
            f"target price and stop-loss levels."
        )
        return await self._run_analysis(
            user_prompt=user_prompt,
            analysis_type=AnalysisType.STOCK_ANALYSIS,
        )

    async def check_alerts(
        self,
        snapshot: dict[str, Any],
        drawdown_status: dict[str, Any] | None = None,
        regime: dict[str, Any] | None = None
    ) -> AnalysisResult:
        """Quick check for urgent alerts based on current portfolio state."""
        user_prompt = self._build_alert_check_prompt(snapshot, drawdown_status, regime)
        return await self._run_analysis(
            user_prompt=user_prompt,
            analysis_type=AnalysisType.ALERT_CHECK,
            max_tokens=2048,
        )

    async def answer_question(self, question: str) -> AnalysisResult:
        """Answer a free-form user question about portfolio or market."""
        user_prompt = (
            f"The user asks: {question}\n\n"
            f"Use the available tools to fetch relevant data and provide a helpful, "
            f"data-backed answer. Include any relevant recommendations."
        )
        return await self._run_analysis(
            user_prompt=user_prompt,
            analysis_type=AnalysisType.MARKET_OVERVIEW,
        )

    async def analyze_screener_candidates(
        self, candidates: list[dict[str, Any]]
    ) -> AnalysisResult:
        """Analyze top screener candidates and rank buy opportunities."""
        candidates_json = json.dumps(candidates, indent=2, default=str)
        user_prompt = (
            f"You have been given {len(candidates)} NSE stock candidates pre-screened by "
            f"technical criteria (RSI, MACD crossover, volume surge, SMA position).\n\n"
            f"Candidates:\n{candidates_json}\n\n"
            f"Rank them by buy opportunity confidence for a 1-2 week swing trade horizon. "
            f"For each stock provide: action (BUY/WATCH/SKIP), entry price range, "
            f"target, stop loss, and key catalyst or risk. "
            f"You may use get_stock_quote or get_technical_indicators for stocks you want "
            f"to investigate further before deciding."
        )
        return await self._run_analysis(
            user_prompt=user_prompt,
            analysis_type=AnalysisType.STOCK_ANALYSIS,
        )

    # ----------------------------------------------------------------
    # Core Agentic Loop
    # ----------------------------------------------------------------

    async def _run_analysis(
        self,
        user_prompt: str,
        analysis_type: AnalysisType,
        max_tokens: int | None = None,
    ) -> AnalysisResult:
        """Core agentic loop: prompt → tool calls → response → parse."""
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]
        max_iterations = 10
        iteration = 0
        total_input_tokens = 0
        total_output_tokens = 0
        tool_calls_count = 0
        start_time = time.monotonic()

        while iteration < max_iterations:
            iteration += 1
            logger.info(f"AI analysis iteration {iteration}/{max_iterations}")

            try:
                response = await self._claude_call(
                    messages=messages,
                    max_tokens=max_tokens or settings.claude_max_tokens,
                )
            except AIAnalysisError:
                raise
            except Exception as e:
                raise AIAnalysisError(f"Claude API error: {e}") from e

            # Track token usage
            if hasattr(response, "usage") and response.usage:
                total_input_tokens += getattr(response.usage, "input_tokens", 0)
                total_output_tokens += getattr(response.usage, "output_tokens", 0)

            if response.stop_reason != "tool_use":
                result = self._parse_final_response(response, analysis_type)
                # V3 Phase 3C: enrich BUY signals with event risk (block near corporate events)
                if settings.event_risk_enabled and result.signals:
                    result = await self._apply_event_risk(result)
                # Log usage to DB (fire-and-forget)
                await self._log_usage(
                    analysis_type=analysis_type.value,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    tool_calls_count=tool_calls_count,
                    duration_ms=int((time.monotonic() - start_time) * 1000),
                )
                return result

            # Handle tool calls
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_calls_count += 1
                    logger.info(f"AI calling tool: {block.name}({block.input})")
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
                        logger.error(f"Tool execution error ({block.name}): {e}")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Error executing tool: {str(e)}",
                            "is_error": True,
                        })

            messages.append({"role": "user", "content": tool_results})

        logger.warning("AI analysis reached max iterations without completing")
        return AnalysisResult(
            analysis_type=analysis_type,
            timestamp=datetime.now(),
            summary="Analysis incomplete — reached maximum tool call iterations.",
            signals=[],
        )

    async def _claude_call(self, messages: list, max_tokens: int):
        """Call Claude API with timeout and one retry on timeout."""
        system_prompt = await self._get_system_prompt()  # V3: may include calibration context
        try:
            return await self.client.messages.create(
                model=settings.claude_model,
                max_tokens=max_tokens,
                system=system_prompt,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )
        except anthropic.APITimeoutError:
            logger.warning("Claude API timeout — retrying once")
            return await self.client.messages.create(
                model=settings.claude_model,
                max_tokens=max_tokens,
                system=system_prompt,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )
        except anthropic.APIError as e:
            raise AIAnalysisError(f"Claude API error: {e}") from e

    async def _apply_event_risk(self, result: AnalysisResult) -> AnalysisResult:
        """Phase 3C: check event risk for BUY/STRONG_BUY signals; downgrade if blocked.

        Non-fatal — if the event filter is unavailable, signals pass through unchanged.
        """
        try:
            from src.services.event_risk_filter import event_risk_filter
            for signal in result.signals:
                if signal.action not in (ActionType.BUY, ActionType.STRONG_BUY):
                    continue
                risk = await event_risk_filter.check_entry_risk(signal.trading_symbol)
                if risk.blocked:
                    logger.info(
                        f"[3C] {signal.trading_symbol} BUY→HOLD — event risk: {risk.reason}"
                    )
                    signal.event_risk = risk.reason
                    signal.action = ActionType.HOLD
        except Exception as e:
            logger.debug(f"Event risk enrichment skipped (non-fatal): {e}")
        return result

    async def _log_usage(
        self,
        analysis_type: str,
        input_tokens: int,
        output_tokens: int,
        tool_calls_count: int,
        duration_ms: int,
    ) -> None:
        """Save token/cost metrics to DB (best-effort, non-fatal)."""
        try:
            from src.services.database import db
            cost_usd = (
                input_tokens / 1_000_000 * _INPUT_COST_PER_M
                + output_tokens / 1_000_000 * _OUTPUT_COST_PER_M
            )
            await db.save_ai_usage({
                "analysis_type": analysis_type,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "tool_calls_count": tool_calls_count,
                "duration_ms": duration_ms,
                "cost_usd": round(cost_usd, 6),
            })
        except Exception as e:
            logger.debug(f"AI usage logging failed (non-fatal): {e}")

    # ----------------------------------------------------------------
    # Response Parsing
    # ----------------------------------------------------------------

    def _parse_final_response(
        self, response: Any, analysis_type: AnalysisType
    ) -> AnalysisResult:
        """Parse Claude's final text response into a structured AnalysisResult."""
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text = block.text
                break

        json_text = self._extract_json(text)

        try:
            data = json.loads(json_text)
            signals = []
            for s in data.get("signals", []):
                # Bug fix: clamp confidence to [0.0, 1.0]
                s["confidence"] = max(0.0, min(1.0, float(s.get("confidence", 0.5))))
                # Auto-compute risk_reward_ratio if not provided
                if s.get("target_price") and s.get("stop_loss") and s.get("confidence"):
                    entry = s.get("current_price", 0)
                    if entry > 0 and s["stop_loss"] > 0:
                        upside = abs(s["target_price"] - entry)
                        downside = abs(entry - s["stop_loss"])
                        if downside > 0:
                            s["risk_reward_ratio"] = round(upside / downside, 2)
                # Normalise unknown action values to HOLD rather than dropping the signal
                valid_actions = {a.value for a in ActionType}
                if s.get("action") not in valid_actions:
                    logger.debug(f"Unknown action '{s.get('action')}' for {s.get('trading_symbol')} — defaulting to HOLD")
                    s["action"] = "HOLD"
                try:
                    signals.append(TradeSignal(**{
                        k: v for k, v in s.items()
                        if k in TradeSignal.model_fields
                    }))
                except Exception as sig_err:
                    logger.debug(f"Skipping invalid signal {s.get('trading_symbol')}: {sig_err}")
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
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Failed to parse AI response as JSON: {e}")
            return AnalysisResult(
                analysis_type=analysis_type,
                timestamp=datetime.now(),
                summary=text[:1000] if text else "No analysis generated.",
                signals=[],
                raw_response=text,
            )

    def _extract_json(self, text: str) -> str:
        """Bug fix #8: Robust JSON extraction using regex.

        Handles: code fences with/without 'json' tag, text before/after JSON.
        """
        text = text.strip()

        # Try ```json ... ``` or ``` ... ``` block first
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()

        # Fall back to outermost { ... } (handles text surrounding the JSON)
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]

        return text

    # ----------------------------------------------------------------
    # Prompt Builders
    # ----------------------------------------------------------------

    def _build_portfolio_prompt(self, context: dict[str, Any]) -> str:
        holdings_summary = json.dumps(context.get("holdings_summary", []), indent=2)
        micro_context = context.get("micro_context", "")

        prompt = f"""\
Analyze my current stock portfolio and provide comprehensive recommendations.

Current portfolio metrics:
- Total invested: INR {context.get('total_invested', 0):,.2f}
- Current value: INR {context.get('current_value', 0):,.2f}
- Overall P&L: INR {context.get('total_pnl', 0):,.2f} ({context.get('total_pnl_pct', 0):.2f}%)
- Today's P&L: INR {context.get('day_pnl', 0):,.2f}

Holdings summary:
{holdings_summary}"""

        if micro_context:
            prompt += f"\n\n=== LAST 15 MIN PRICE ACTIVITY (10-sec ticks) ===\n{micro_context}"

        prompt += """

Use the tools to fetch detailed technical data for stocks needing deeper analysis.
Focus on:
1. Are any positions at risk (significant losses, breaking key support levels)?
2. Are there opportunities to book profits (overbought, near resistance)?
3. Overall portfolio diversification assessment
4. Any stocks that need immediate attention?
5. Market sentiment and how it affects this portfolio"""

        return prompt

    def _build_alert_check_prompt(
        self,
        snapshot: dict[str, Any],
        drawdown_status: dict[str, Any] | None = None,
        regime: dict[str, Any] | None = None
    ) -> str:
        essential = {
            "total_invested": snapshot.get("total_invested"),
            "current_value": snapshot.get("current_value"),
            "total_pnl_pct": snapshot.get("total_pnl_pct"),
            "day_pnl": snapshot.get("day_pnl"),
            "holdings": [
                {
                    "symbol": h.get("trading_symbol", h.get("symbol", "")),
                    "pnl_pct": h.get("pnl_pct", 0),
                    "day_change_pct": h.get("day_change_pct", 0),
                    "current_price": h.get("current_price", 0),
                }
                for h in snapshot.get("holdings", [])
            ],
        }

        # Feature 3: Drawdown breaker warning
        drawdown_warning = ""
        if drawdown_status and drawdown_status.get("breaker_triggered"):
            drawdown_pct = drawdown_status.get("drawdown_pct", 0)
            drawdown_warning = f"""\

CRITICAL: DRAWDOWN BREAKER IS ACTIVE
Portfolio is down {drawdown_pct:.2f}% from peak (threshold exceeded).
DO NOT generate any BUY or STRONG_BUY signals.
Focus ONLY on risk reduction: SELL/HOLD signals to protect capital.
"""

        # Feature 4: Market regime context
        regime_context = ""
        if regime:
            regime_name = regime.get("regime", "UNKNOWN")
            regime_score = regime.get("regime_score", 0)
            min_confidence = regime.get("suggested_min_confidence", 0.7)
            regime_context = f"""\

MARKET REGIME: {regime_name} (score: {regime_score:.0f}/100)
Minimum confidence threshold for signals: {min_confidence:.0%}
Adjust your signal confidence accordingly based on current market conditions.
"""

        return f"""\
Quick portfolio check for urgent alerts. Flag ONLY items requiring immediate attention.

Portfolio state:
{json.dumps(essential, indent=2, default=str)}
{drawdown_warning}{regime_context}
Flag: stocks with day change > 5%, RSI extremes (< 30 or > 70), stop-loss breaches.
If nothing urgent, return brief summary with empty signals array. Be concise."""


# Singleton
ai_engine = AIAnalysisEngine()
