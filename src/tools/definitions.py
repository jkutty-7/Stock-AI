"""Claude tool definitions for the AI analysis engine.

These JSON schemas define the tools that Claude can invoke during analysis
to fetch live market data, portfolio state, and historical information.
"""

TOOL_DEFINITIONS = [
    {
        "name": "get_portfolio_holdings",
        "description": (
            "Fetch the user's current stock holdings from their Groww trading account. "
            "Returns each holding with ISIN, trading symbol, quantity, and average "
            "purchase price. Use this to understand what the user currently owns."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_stock_quote",
        "description": (
            "Get real-time quote for a specific stock including last traded price, "
            "OHLC (open/high/low/close), volume, 52-week high/low, day change, "
            "bid/offer prices, and circuit limits. Works for any NSE or BSE listed stock."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trading_symbol": {
                    "type": "string",
                    "description": "NSE/BSE trading symbol (e.g., 'RELIANCE', 'TCS', 'INFY', 'NIFTY')",
                },
                "exchange": {
                    "type": "string",
                    "enum": ["NSE", "BSE"],
                    "description": "Stock exchange. Default: NSE.",
                },
            },
            "required": ["trading_symbol"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_bulk_prices",
        "description": (
            "Fetch last traded prices for multiple stocks at once (up to 50 symbols). "
            "Efficient for getting portfolio-wide price updates in a single call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trading_symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of trading symbols (e.g., ['RELIANCE', 'TCS', 'INFY'])",
                    "maxItems": 50,
                },
            },
            "required": ["trading_symbols"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_historical_data",
        "description": (
            "Fetch historical OHLCV (open/high/low/close/volume) candle data for a stock. "
            "Use this for technical analysis over time. Returns timestamp, open, high, low, "
            "close, and volume for each candle.\n\n"
            "Available intervals and their maximum request windows:\n"
            "- 1 min: max 7 days back\n"
            "- 5 min: max 15 days back\n"
            "- 60 min (1 hour): max 150 days back\n"
            "- 1440 min (1 day): max 1080 days (~3 years) back\n"
            "- 10080 min (1 week): unlimited history"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trading_symbol": {
                    "type": "string",
                    "description": "Trading symbol (e.g., 'RELIANCE')",
                },
                "interval_minutes": {
                    "type": "integer",
                    "enum": [1, 5, 60, 1440, 10080],
                    "description": "Candle interval in minutes",
                },
                "days_back": {
                    "type": "integer",
                    "description": "Number of days of historical data to fetch",
                    "minimum": 1,
                    "maximum": 1080,
                },
            },
            "required": ["trading_symbol", "interval_minutes", "days_back"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_technical_indicators",
        "description": (
            "Compute technical indicators for a stock: RSI(14), MACD(12,26,9), "
            "SMA(20,50,200), EMA(12,26), and Bollinger Bands(20,2). Also returns "
            "the current live quote. Historical data is fetched automatically "
            "(90 days of daily candles)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trading_symbol": {
                    "type": "string",
                    "description": "Trading symbol to analyze (e.g., 'RELIANCE')",
                },
            },
            "required": ["trading_symbol"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_portfolio_snapshot",
        "description": (
            "Get the latest stored portfolio snapshot with enriched data including "
            "current prices, P&L for each holding, day change, and overall portfolio "
            "metrics (total invested, current value, total P&L, day P&L)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_positions",
        "description": (
            "Fetch current intraday and derivative positions from the user's trading "
            "account. Includes credit/debit quantities, realised P&L, and segment "
            "information. Useful for checking F&O or intraday positions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "segment": {
                    "type": "string",
                    "enum": ["CASH", "FNO", "COMMODITY"],
                    "description": "Filter by segment. Omit for all segments.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_micro_signal_summary",
        "description": (
            "Get the last 15 minutes of 10-second price tick data for a specific stock. "
            "Returns: number of up/down ticks in the last 10 ticks, 1-minute momentum "
            "(cumulative % change), current direction, and whether a volume spike "
            "was detected. Use this BEFORE making hold/sell decisions — a stock with "
            "8/9 DOWN ticks needs different treatment than one with 8/9 UP ticks "
            "even if their current P&L looks similar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trading_symbol": {
                    "type": "string",
                    "description": "NSE trading symbol (e.g., 'RELIANCE', 'INFY')",
                },
            },
            "required": ["trading_symbol"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_sector_performance",
        "description": (
            "Get aggregated performance metrics for a market sector over the last N days. "
            "Returns the average day change %, average total P&L %, and a list of "
            "holdings in that sector with their individual performance. Useful for "
            "understanding if a stock's movement is sector-wide or stock-specific."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sector": {
                    "type": "string",
                    "description": (
                        "Sector name (e.g., 'IT', 'Financial Services', 'Pharma', "
                        "'Automobile', 'Energy', 'FMCG', 'Metals', 'Power')"
                    ),
                },
                "days": {
                    "type": "integer",
                    "description": "Look-back days for performance (default: 5, max: 30)",
                    "minimum": 1,
                    "maximum": 30,
                },
            },
            "required": ["sector"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_peer_comparison",
        "description": (
            "Compare a stock against its sector peers. Fetches RSI, 5-day return, "
            "and day volume ratio for 5 peer stocks and the target stock. "
            "Useful for understanding relative strength — is a stock lagging its peers "
            "(buy opportunity) or significantly outperforming (overvalued risk)?"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trading_symbol": {
                    "type": "string",
                    "description": "Target stock to compare (e.g., 'RELIANCE')",
                },
                "sector": {
                    "type": "string",
                    "description": (
                        "Sector of the target stock to find peers "
                        "(e.g., 'Energy', 'IT', 'Financial Services')"
                    ),
                },
            },
            "required": ["trading_symbol", "sector"],
            "additionalProperties": False,
        },
    },
    {
        "name": "screen_stocks",
        "description": (
            "Run the technical stock screener to find NSE stocks that may gain value. "
            "Screens using RSI (oversold < 35), MACD bullish crossover, price vs SMA20, "
            "volume spikes, and 52-week low proximity. Returns top candidates with "
            "composite scores (0-100). Use this when the user asks about stock discovery, "
            "investment opportunities, or undervalued stocks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "top_n": {
                    "type": "integer",
                    "description": "Number of top candidates to return (default: 10, max: 20)",
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_signal_performance",
        "description": (
            "Get AI signal accuracy statistics for the last N days. Returns win rate "
            "(percentage of winning trades), average P&L per trade, max win/loss, "
            "confidence correlation (whether higher confidence signals perform better), "
            "and target/stop-loss hit rates. Use this BEFORE generating BUY/SELL signals "
            "to understand if your confidence scores have been reliable. If win rate is "
            "below 50% or confidence correlation is negative, your signals may need "
            "recalibration."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to analyze (default: 30, max: 365)",
                    "minimum": 1,
                    "maximum": 365,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_intraday_indicators",
        "description": (
            "Get intraday-specific technical indicators for a symbol: "
            "Supertrend (5-min chart, period=10, multiplier=3) with current direction and flip status, "
            "VWAP with +/-1 standard-deviation bands (computed from today's 5-min candles), "
            "and CPR levels (pivot, Bottom Central, Top Central, R1, R2, S1, S2). "
            "Use this as the primary tool for intraday bias assessment."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trading_symbol": {
                    "type": "string",
                    "description": "NSE trading symbol (e.g., 'RELIANCE', 'TCS')",
                },
            },
            "required": ["trading_symbol"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_opening_range",
        "description": (
            "Get Opening Range Breakout (ORB) data for a symbol. "
            "Returns high and low of the first 15 minutes (9:15-9:29 AM IST), "
            "current breakout direction (UP/DOWN/NONE), and breakout strength %. "
            "An ORB breakout confirmed with volume is one of the strongest intraday setups."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trading_symbol": {
                    "type": "string",
                    "description": "NSE trading symbol",
                },
            },
            "required": ["trading_symbol"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_gap_analysis",
        "description": (
            "Get overnight gap analysis for a symbol: gap% from previous close to today's open, "
            "gap type (GAP_UP/GAP_DOWN/FLAT), gap fill price, and whether the gap has been filled. "
            "Gap direction often sets the intraday bias for the first half of the trading session."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trading_symbol": {
                    "type": "string",
                    "description": "NSE trading symbol",
                },
            },
            "required": ["trading_symbol"],
            "additionalProperties": False,
        },
    },
    # ── V3.0 Tools ──────────────────────────────────────────────────────────────
    {
        "name": "get_event_calendar",
        "description": (
            "Get upcoming NSE corporate events for a stock within the next N days. "
            "Events include: board meetings (quarterly/annual results), dividend ex-dates, "
            "bonus ex-dates, stock splits, AGMs, buybacks, and rights issues. "
            "ALWAYS call this before recommending a BUY or STRONG_BUY action — "
            "entering a position 1-3 days before results is extremely high risk. "
            "If an event is within 3 days, recommend WATCH instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trading_symbol": {
                    "type": "string",
                    "description": "NSE trading symbol (e.g., 'RELIANCE', 'TCS')",
                },
                "days_ahead": {
                    "type": "integer",
                    "description": "Look-ahead window in days (default: 14, max: 30)",
                    "minimum": 1,
                    "maximum": 30,
                },
            },
            "required": ["trading_symbol"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_signal_calibration",
        "description": (
            "Get your historical win rate for a specific confidence level or reasoning tag pattern. "
            "Use this to calibrate how confident you should be in this analysis. "
            "Returns: empirical win rate for the confidence bucket, pattern-specific stats "
            "(e.g., how often RSI_oversold + MACD_crossover signals have won), and "
            "regime-adjusted performance (your win rate in current market regime). "
            "If your 0.75 confidence signals have historically won only 45% of the time, "
            "you are over-confident and should lower confidence or raise your evidence bar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "confidence_level": {
                    "type": "number",
                    "description": (
                        "Your planned confidence score (0.0–1.0). "
                        "Returns empirical win rate for the containing bucket (e.g., 0.75 → 0.7–0.8 bucket)"
                    ),
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "reasoning_tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of reasoning tags you plan to use (e.g., ['RSI_oversold', 'MACD_bullish_crossover']). "
                        "Returns historical win rate for this tag combination."
                    ),
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_capital_allocation",
        "description": (
            "Get Kelly-optimal position size, correlation risk check, and sector concentration check "
            "before recommending a BUY or STRONG_BUY signal. "
            "Returns: recommended quantity (shares), recommended value (Rs.), Kelly fraction, "
            "correlation warning if the stock is highly correlated with an existing holding "
            "(Pearson > 0.80), and sector concentration warning if adding this stock would "
            "push a sector above the 30% cap. "
            "Use this for every BUY signal to tell the user exactly how many shares to buy "
            "instead of leaving sizing to guesswork."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trading_symbol": {
                    "type": "string",
                    "description": "NSE trading symbol (e.g., 'RELIANCE')",
                },
                "action": {
                    "type": "string",
                    "enum": ["BUY", "STRONG_BUY"],
                    "description": "Intended trade action",
                },
                "confidence": {
                    "type": "number",
                    "description": "Your planned confidence score (0.0–1.0)",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "entry_price": {
                    "type": "number",
                    "description": "Planned entry price in Rs.",
                },
                "stop_loss": {
                    "type": "number",
                    "description": "Stop-loss price in Rs.",
                },
                "target_price": {
                    "type": "number",
                    "description": "Target price in Rs.",
                },
            },
            "required": ["trading_symbol", "action", "confidence", "entry_price", "stop_loss", "target_price"],
            "additionalProperties": False,
        },
    },
]
