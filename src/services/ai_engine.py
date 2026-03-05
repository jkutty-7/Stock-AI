"""Claude AI analysis engine with tool-use for intelligent stock analysis.

This is the core "brain" of the system. It uses an agentic loop where Claude
can call tools to fetch market data, then produces structured analysis results.
"""

import json
import logging
from datetime import datetime
from typing import Any

import anthropic

from src.config import settings
from src.models.analysis import AnalysisResult, AnalysisType, TradeSignal
from src.tools.definitions import TOOL_DEFINITIONS
from src.tools.executor import execute_tool
from src.utils.exceptions import AIAnalysisError

logger = logging.getLogger(__name__)

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

When providing your final analysis, structure your response as a valid JSON object:
{
    "summary": "Brief overall assessment (2-3 sentences)",
    "market_sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
    "signals": [
        {
            "trading_symbol": "SYMBOL",
            "action": "BUY" | "SELL" | "HOLD" | "STRONG_BUY" | "STRONG_SELL",
            "confidence": 0.0 to 1.0,
            "target_price": number or null,
            "stop_loss": number or null,
            "reasoning": "Detailed reasoning for this recommendation",
            "risk_level": "LOW" | "MEDIUM" | "HIGH"
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

    async def analyze_portfolio(self, context: dict[str, Any]) -> AnalysisResult:
        """Run comprehensive portfolio health analysis.

        Args:
            context: Dict with portfolio metrics (total_invested, current_value, etc.)
        """
        user_prompt = self._build_portfolio_prompt(context)
        return await self._run_analysis(
            user_prompt=user_prompt,
            analysis_type=AnalysisType.PORTFOLIO_HEALTH,
        )

    async def analyze_stock(self, trading_symbol: str) -> AnalysisResult:
        """Deep analysis of a specific stock with recommendations.

        Args:
            trading_symbol: Stock symbol to analyze (e.g., 'RELIANCE').
        """
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

    async def check_alerts(self, snapshot: dict[str, Any]) -> AnalysisResult:
        """Quick check for urgent alerts or signals based on current portfolio state.

        Args:
            snapshot: Current portfolio snapshot dict.
        """
        user_prompt = self._build_alert_check_prompt(snapshot)
        return await self._run_analysis(
            user_prompt=user_prompt,
            analysis_type=AnalysisType.ALERT_CHECK,
            max_tokens=2048,
        )

    async def answer_question(self, question: str) -> AnalysisResult:
        """Answer a free-form user question about their portfolio or the market.

        Args:
            question: User's question text.
        """
        user_prompt = (
            f"The user asks: {question}\n\n"
            f"Use the available tools to fetch relevant data and provide a helpful, "
            f"data-backed answer. Include any relevant recommendations."
        )
        return await self._run_analysis(
            user_prompt=user_prompt,
            analysis_type=AnalysisType.MARKET_OVERVIEW,
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
        """Core agentic loop: prompt → tool calls → response → parse.

        Iterates up to 10 times, allowing Claude to call multiple tools
        before producing its final structured analysis.
        """
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]

        max_iterations = 10
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            logger.info(f"AI analysis iteration {iteration}/{max_iterations}")

            try:
                response = await self.client.messages.create(
                    model=settings.claude_model,
                    max_tokens=max_tokens or settings.claude_max_tokens,
                    system=SYSTEM_PROMPT,
                    tools=TOOL_DEFINITIONS,
                    messages=messages,
                )
            except anthropic.APIError as e:
                logger.error(f"Claude API error: {e}")
                raise AIAnalysisError(f"Claude API error: {e}") from e

            # If Claude is done (no more tool use), parse the final response
            if response.stop_reason != "tool_use":
                return self._parse_final_response(response, analysis_type)

            # Handle tool calls
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    logger.info(f"AI calling tool: {block.name}({block.input})")
                    try:
                        result = await execute_tool(block.name, block.input)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": (
                                    json.dumps(result, default=str)
                                    if isinstance(result, dict)
                                    else str(result)
                                ),
                            }
                        )
                    except Exception as e:
                        logger.error(f"Tool execution error ({block.name}): {e}")
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": f"Error executing tool: {str(e)}",
                                "is_error": True,
                            }
                        )

            messages.append({"role": "user", "content": tool_results})

        # Max iterations reached without a final response
        logger.warning("AI analysis reached max iterations without completing")
        return AnalysisResult(
            analysis_type=analysis_type,
            timestamp=datetime.now(),
            summary="Analysis incomplete — reached maximum tool call iterations.",
            signals=[],
        )

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

        # Try to extract JSON from the response
        json_text = self._extract_json(text)

        try:
            data = json.loads(json_text)
            signals = [TradeSignal(**s) for s in data.get("signals", [])]
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
            # Fall back to using raw text as summary
            return AnalysisResult(
                analysis_type=analysis_type,
                timestamp=datetime.now(),
                summary=text[:1000] if text else "No analysis generated.",
                signals=[],
                raw_response=text,
            )

    def _extract_json(self, text: str) -> str:
        """Extract JSON from text that may contain markdown code fences."""
        text = text.strip()

        # Remove markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first line (```json or ```)
            lines = lines[1:]
            # Remove last line (```)
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        # Try to find JSON object boundaries
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]

        return text

    # ----------------------------------------------------------------
    # Prompt Builders
    # ----------------------------------------------------------------

    def _build_portfolio_prompt(self, context: dict[str, Any]) -> str:
        """Build a detailed prompt with current portfolio snapshot for full analysis."""
        holdings_summary = json.dumps(context.get("holdings_summary", []), indent=2)

        return f"""\
Analyze my current stock portfolio and provide comprehensive recommendations.

Current portfolio metrics:
- Total invested: INR {context.get('total_invested', 0):,.2f}
- Current value: INR {context.get('current_value', 0):,.2f}
- Overall P&L: INR {context.get('total_pnl', 0):,.2f} ({context.get('total_pnl_pct', 0):.2f}%)
- Today's P&L: INR {context.get('day_pnl', 0):,.2f}

Holdings summary:
{holdings_summary}

Use the tools to fetch detailed technical data for stocks that need deeper analysis.
Focus on:
1. Are any positions at risk (significant losses, breaking key support levels)?
2. Are there opportunities to book profits (overbought, near resistance)?
3. Overall portfolio diversification assessment
4. Any stocks that need immediate attention (buy more, sell, or set stop-loss)?
5. Market sentiment and how it affects this portfolio"""

    def _build_alert_check_prompt(self, snapshot: dict[str, Any]) -> str:
        """Build a prompt for quick alert checking (used every 15 min)."""
        # Truncate raw snapshot to essential data
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

        return f"""\
Quick portfolio check for urgent alerts. Review the current state and flag ONLY items \
that require immediate attention.

Portfolio state:
{json.dumps(essential, indent=2, default=str)}

Flag these situations:
- Stocks with day change > 5% (up or down)
- RSI extreme values (< 30 oversold or > 70 overbought) — use the technical indicators tool
- Stop-loss levels that may be breached
- Any significant developments

If nothing urgent, return a brief summary with empty signals array. Be concise."""


# Singleton
ai_engine = AIAnalysisEngine()
