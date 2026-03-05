# Stock AI - Portfolio Monitoring & AI Advisory Backend

An AI-powered backend that monitors your Groww trading portfolio in real-time, runs Claude-based analysis every 15 minutes during NSE market hours, and delivers actionable buy/sell/hold signals straight to your Telegram.

## How It Works

```
Groww Holdings ──> Live Prices ──> Enrich P&L ──> Claude AI Analysis ──> Telegram Alerts
       |                                |                  |
       |          Technical Indicators  |        7 tools   |
       |          (RSI, MACD, SMA, BB) -+     (agentic    |
       |                                       loop)      |
       +-- MongoDB snapshots, signals, alert history -----+
```

**Every 15 minutes** during market hours (Mon-Fri, 9:15 AM - 3:30 PM IST), the system:

1. Fetches your holdings from Groww
2. Gets live prices and computes P&L for every stock
3. Checks threshold alerts (stocks moving > 5% in a day)
4. Runs Claude AI with tool-use to analyze your portfolio
5. Sends high-confidence signals and alerts to Telegram
6. Saves everything to MongoDB for historical tracking

## Features

- **Groww Trading API** integration - holdings, positions, live quotes, historical OHLCV candles
- **Claude AI agentic analysis** - the AI decides what data to fetch via 7 tools, then returns structured JSON recommendations
- **Telegram bot** - interactive commands + push notifications
- **Technical indicators** - RSI(14), MACD(12,26,9), SMA(20/50/200), EMA(12/26), Bollinger Bands
- **Scheduled monitoring** - 5 cron jobs covering market open, close, and periodic checks
- **REST API** - FastAPI endpoints for future web dashboard
- **MongoDB persistence** - portfolio snapshots, analysis logs, trade signals, alert history

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Framework | FastAPI + Uvicorn |
| Trading API | Groww Python SDK (`growwapi`) |
| AI Engine | Anthropic Claude API (tool-use) |
| Notifications | python-telegram-bot |
| Database | MongoDB (PyMongo async) |
| Scheduler | APScheduler (AsyncIOScheduler) |
| Indicators | NumPy (pure implementations) |
| Config | Pydantic Settings |

## Project Structure

```
Stock AI/
├── main.py                        # FastAPI entry point + lifespan
├── pyproject.toml                 # Project metadata & dependencies
├── requirements.txt               # pip dependencies
├── requirements-dev.txt           # dev/test dependencies
├── .env.template                  # Environment variable template
│
├── src/
│   ├── config.py                  # Pydantic Settings from .env
│   ├── models/
│   │   ├── holdings.py            # Holding, EnrichedHolding, PortfolioSnapshot
│   │   ├── market.py              # Quote, Candle, TechnicalIndicators
│   │   └── analysis.py            # TradeSignal, AnalysisResult, AlertMessage
│   ├── services/
│   │   ├── groww_service.py       # Groww SDK wrapper (TOTP auth, async)
│   │   ├── market_data.py         # Live data + indicator computation
│   │   ├── ai_engine.py           # Claude agentic loop with tool-use
│   │   ├── portfolio_monitor.py   # Orchestrator: fetch -> analyze -> alert
│   │   ├── telegram_bot.py        # Bot commands + push notifications
│   │   └── database.py            # PyMongo AsyncMongoClient
│   ├── tools/
│   │   ├── definitions.py         # Claude tool JSON schemas (7 tools)
│   │   └── executor.py            # Tool dispatch: name -> implementation
│   ├── scheduler/
│   │   ├── setup.py               # APScheduler cron configuration
│   │   └── jobs.py                # Scheduled job functions
│   ├── api/
│   │   └── router.py              # REST API routes
│   └── utils/
│       ├── market_hours.py        # IST market hours, NSE holidays
│       ├── indicators.py          # RSI, MACD, SMA, EMA, Bollinger Bands
│       ├── formatters.py          # Telegram HTML message formatters
│       ├── logger.py              # Structured logging
│       └── exceptions.py          # Custom exception hierarchy
│
└── tests/
    ├── conftest.py                # Shared fixtures
    ├── test_indicators.py         # Technical indicator tests
    └── test_market_hours.py       # Market hours/holiday tests
```

## Prerequisites

- **Python 3.11+**
- **MongoDB** running locally (or a remote URI)
- **Groww Trading Account** with an active [Trade API subscription](https://groww.in/trade-api)
- **Anthropic API key** from [console.anthropic.com](https://console.anthropic.com/)
- **Telegram bot token** from [@BotFather](https://t.me/BotFather)

## Setup

### 1. Clone and install

```bash
cd "Stock AI"

# Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
.venv\Scripts\activate      # Windows

# Install dependencies
pip install -r requirements.txt

# Or with dev tools (pytest, ruff, mypy)
pip install -r requirements-dev.txt
```

### 2. Configure environment

```bash
# Copy the template
cp .env.template .env
```

Edit `.env` and fill in your credentials:

```env
# Groww Trading API
GROWW_API_KEY=your_groww_totp_token
GROWW_TOTP_SECRET=your_totp_secret

# Anthropic Claude API
ANTHROPIC_API_KEY=sk-ant-xxxxx

# Telegram Bot
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=your_numeric_chat_id

# MongoDB
MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=stock_ai
```

**Getting your Telegram chat ID:** Start a chat with your bot, send any message, then visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` to find your `chat.id`.

**Getting Groww API keys:** Go to [Groww Cloud API Keys](https://groww.in/trade-api/cloud/api-keys), generate a TOTP token, and copy the token + secret.

### 3. Start MongoDB

```bash
# Using Docker
docker run -d --name mongodb -p 27017:27017 mongo:7

# Or install locally: https://www.mongodb.com/docs/manual/installation/
```

### 4. Run the application

```bash
# Development (with auto-reload)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Production
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

On startup you will see:
```
Stock AI Monitor Started
All systems online. Monitoring will run during market hours.
Use /help to see available commands.
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/status` | Quick portfolio P&L summary |
| `/portfolio` | Detailed per-stock breakdown with P&L |
| `/analyze RELIANCE` | On-demand AI analysis for any stock |
| `/alerts` | Recent alert history |
| `/settings` | View current alert thresholds |
| `/help` | List all commands |

You can also **send any free-text message** to ask questions about your portfolio or the market (e.g., "Should I sell INFY?" or "How is my portfolio diversified?").

## REST API Endpoints

All endpoints are prefixed with `/api/v1`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/api/v1/portfolio` | Latest portfolio snapshot |
| `GET` | `/api/v1/analysis/latest` | Most recent AI analysis |
| `GET` | `/api/v1/analysis/history?limit=20` | Analysis history |
| `GET` | `/api/v1/alerts?limit=50` | Recent alerts |
| `GET` | `/api/v1/signals` | Active trade signals |
| `GET` | `/api/v1/signals/{symbol}` | Signals for a specific stock |
| `POST` | `/api/v1/analyze/{symbol}` | Trigger on-demand AI analysis |
| `GET` | `/api/v1/settings` | Current settings |
| `PUT` | `/api/v1/settings` | Update settings |

Interactive docs available at `http://localhost:8000/docs` (Swagger UI).

## Claude AI Engine

The AI engine uses an **agentic loop** where Claude autonomously decides what data to fetch:

**Available tools for Claude:**

| Tool | What it does |
|------|-------------|
| `get_portfolio_holdings` | Fetch current holdings from Groww |
| `get_stock_quote` | Real-time quote for any NSE/BSE stock |
| `get_bulk_prices` | LTP for up to 50 symbols at once |
| `get_historical_data` | OHLCV candles (1min to weekly) |
| `get_technical_indicators` | RSI, MACD, SMA, EMA, Bollinger Bands |
| `get_portfolio_snapshot` | Latest saved portfolio state from DB |
| `get_positions` | Current intraday/F&O positions |

Claude returns structured JSON with:
- **Action**: BUY / SELL / HOLD / STRONG_BUY / STRONG_SELL
- **Confidence**: 0.0 to 1.0
- **Target price** and **stop-loss**
- **Reasoning** backed by data
- **Risk level**: LOW / MEDIUM / HIGH
- **Market sentiment**: BULLISH / BEARISH / NEUTRAL

## Scheduled Jobs

All jobs respect NSE holidays and weekends:

| Job | Schedule | Description |
|-----|----------|-------------|
| Portfolio Monitor | Every 15 min, Mon-Fri 9:15-15:30 IST | Full monitoring cycle |
| Market Open | 9:15 AM IST | Re-authenticate Groww + opening notification |
| Market Close | 3:35 PM IST | End-of-day summary |
| Daily AI Analysis | 3:40 PM IST | Comprehensive portfolio analysis |
| Health Check | Every 30 min during market hours | Verify Groww + MongoDB connectivity |

## MongoDB Collections

| Collection | Purpose |
|------------|---------|
| `portfolio_snapshots` | Timestamped portfolio state (holdings + P&L) |
| `analysis_logs` | Claude AI analysis results |
| `alerts_history` | All sent alerts (threshold + AI-based) |
| `trade_signals` | BUY/SELL/HOLD signals with status tracking |
| `user_settings` | Configurable thresholds and watchlist |

## Configuration

All settings are configurable via `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `MONITOR_INTERVAL_MINUTES` | `15` | How often to run the monitoring cycle |
| `PNL_ALERT_THRESHOLD_PCT` | `5.0` | Alert when a stock moves > X% in a day |
| `PORTFOLIO_ALERT_THRESHOLD_PCT` | `3.0` | Alert when portfolio moves > X% overall |
| `CLAUDE_MODEL` | `claude-sonnet-4-20250514` | Claude model to use for analysis |
| `CLAUDE_MAX_TOKENS` | `4096` | Max tokens for Claude responses |
| `LOG_LEVEL` | `INFO` | Logging level |

## Running Tests

```bash
# Run all tests
pytest

# With coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_indicators.py -v
```

## Rate Limits

The Groww API enforces these limits (shared across all APIs of the same type):

| Type | Per Second | Per Minute |
|------|-----------|-----------|
| Orders (place/modify/cancel) | 10 | 250 |
| Live Data (quotes, LTP, OHLC) | 10 | 300 |
| Non-Trading (status, holdings, positions) | 20 | 500 |
| WebSocket subscriptions | - | 1000 max |

The SDK handles chunking (50 symbols per bulk request) and adds brief delays between chunks automatically.

## Disclaimer

This tool is for **informational and educational purposes only**. AI-generated trade signals are not financial advice. Always do your own research before making investment decisions. Past performance does not guarantee future results. Trading in the stock market involves risk, including the potential loss of principal.

## License

MIT
