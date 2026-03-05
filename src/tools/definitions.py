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
]
