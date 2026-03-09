# Stock AI v2 - AI-Powered Portfolio Monitoring & Stock Discovery

An intelligent stock portfolio monitoring system that combines real-time price tracking, AI-powered analysis, and technical stock screening to deliver actionable trading insights directly to your Telegram.

## What's New in V2

**Version 2.0** introduces three major enhancements:

1. **MicroMonitor (10-Second Polling)** - Lightning-fast price tracking that captures micro-movements and momentum shifts every 10 seconds during market hours
2. **Stock Screener** - Daily technical screening of NSE stocks to discover undervalued opportunities based on RSI, MACD, volume, and 52-week positioning
3. **Enhanced AI Engine** - 10 specialized tools (up from 7) including sector analysis, peer comparison, and micro-signal integration

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                     STOCK AI v2 ARCHITECTURE                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Groww Holdings ──┬──> 10s Price Polling (MicroMonitor)         │
│                   │         ↓                                    │
│                   │    Tick Analysis & Momentum                  │
│                   │         ↓                                    │
│                   ├──> 15min AI Analysis ─┬─> Claude AI         │
│                   │    • Technical Signals │   (10 tools)       │
│                   │    • P&L Enrichment   │   • Sector data    │
│                   │    • Micro context    │   • Peer comp      │
│                   │                        │   • Screener       │
│                   │                        ↓                    │
│                   └──> Daily Screener ──> AI Ranking            │
│                        (9:30 AM IST)                            │
│                             ↓                                    │
│                      Telegram Alerts                            │
│                             +                                    │
│                      MongoDB Storage                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Monitoring Cycles

**Every 10 seconds** (MicroMonitor):
- Fetches bulk LTP for all holdings
- Detects velocity spikes (>0.5% per tick)
- Tracks consecutive up/down ticks
- Identifies volume surges (>2x average)
- Sends immediate micro-alerts on significant movements

**Every 15 minutes** during market hours (9:15 AM - 3:30 PM IST):
1. Fetches current holdings from Groww
2. Enriches with live prices and P&L calculations
3. Runs Claude AI analysis with 10-second tick context
4. Generates BUY/SELL/HOLD signals with confidence scores
5. Sends actionable alerts to Telegram
6. Saves everything to MongoDB

**Daily at 9:30 AM IST** (Stock Screener):
1. Screens entire NSE universe for technical opportunities
2. Scores stocks on RSI, MACD, volume, SMA20, 52-week positioning
3. Sends top 10 candidates to Claude for AI ranking
4. Delivers morning watchlist to Telegram

## Features

### Core Features (v1)
- **Groww Trading API Integration** - Holdings, positions, live quotes, historical OHLCV
- **Claude AI Agentic Analysis** - Autonomous tool-use to fetch and analyze market data
- **Telegram Bot** - Interactive commands + push notifications
- **Technical Indicators** - RSI(14), MACD(12,26,9), SMA(20/50/200), EMA(12/26), Bollinger Bands
- **Scheduled Monitoring** - Cron jobs for market open, close, and periodic checks
- **REST API** - FastAPI endpoints for web integration
- **MongoDB Persistence** - Portfolio snapshots, analysis logs, trade signals, alerts

### New in V2

#### MicroMonitor (10-Second Polling)
- **Real-time tick data** - Ring buffer of 90 ticks (15 minutes) per symbol
- **Velocity tracking** - % change per tick
- **Momentum calculation** - Cumulative % change over 1-minute windows
- **Volume spike detection** - Alerts when volume exceeds 2x 5-tick average
- **Direction streaks** - Tracks consecutive up/down ticks
- **Context injection** - Feeds tick summaries into Claude's 15-minute analysis

#### Stock Screener
- **Technical scoring** - Composite 0-100 score based on 5 criteria:
  - RSI < 35 (oversold) → +25 pts
  - MACD bullish crossover → +25 pts
  - Price > SMA20 → +15 pts
  - Volume > 1.5x average → +20 pts
  - Near 52-week low (within 15%) → +15 pts
- **AI ranking** - Top candidates sent to Claude for final analysis and reasoning
- **Daily automation** - Runs at 9:30 AM IST, delivering opportunities before market heats up
- **On-demand screening** - Trigger via `/screen` Telegram command or REST API

#### Enhanced AI Tools
Claude now has access to **10 specialized tools**:

| Tool | Description |
|------|-------------|
| `get_portfolio_holdings` | Current holdings from Groww |
| `get_stock_quote` | Real-time quote with OHLC, 52-week range |
| `get_bulk_prices` | Batch LTP for up to 50 symbols |
| `get_historical_data` | OHLCV candles (1min to weekly) |
| `get_technical_indicators` | RSI, MACD, SMA, EMA, Bollinger Bands |
| `get_portfolio_snapshot` | Latest enriched portfolio state from DB |
| `get_positions` | Intraday/F&O positions |
| `get_micro_signal_summary` ⭐ **NEW** | 10-second tick data for momentum context |
| `get_sector_performance` ⭐ **NEW** | Aggregated sector metrics to identify sector-wide moves |
| `get_peer_comparison` ⭐ **NEW** | Compare stock against sector peers for relative strength |
| `screen_stocks` ⭐ **NEW** | Run technical screener to discover opportunities |

#### Additional Enhancements
- **Webhook support** for Telegram (lower latency vs polling on hosted environments)
- **Circuit breaker** - Protects against API cascading failures
- **In-memory caching** - 8-second quote cache to reduce API calls
- **Rate limiting** - User-level limits (10 messages per 5 minutes)
- **Alert cooldown** - Prevents duplicate symbol alerts within 5-minute window
- **Enhanced error handling** - Failed jobs send Telegram notifications
- **API authentication** - Optional X-API-Key header for REST endpoints

## Tech Stack

| Component | Technology | Notes |
|-----------|-----------|-------|
| Framework | FastAPI + Uvicorn | Async Python web framework |
| Trading API | Groww Python SDK | TOTP-based authentication |
| AI Engine | Anthropic Claude API | Sonnet 4 with tool-use |
| Notifications | python-telegram-bot | Webhook + polling modes |
| Database | MongoDB | PyMongo async driver |
| Scheduler | APScheduler | AsyncIOScheduler for cron jobs |
| Indicators | NumPy | Pure Python implementations |
| Config | Pydantic Settings | Type-safe `.env` configuration |

## Project Structure

```
Stock-AI/
├── main.py                        # FastAPI entry + lifespan management
├── pyproject.toml                 # Project metadata & dependencies
├── .env                           # Environment configuration
│
├── src/
│   ├── config.py                  # Settings from .env
│   │
│   ├── models/
│   │   ├── holdings.py            # Holding, EnrichedHolding, PortfolioSnapshot
│   │   ├── market.py              # Quote, Candle, TechnicalIndicators, MicroSignal
│   │   └── analysis.py            # TradeSignal, AnalysisResult, AlertMessage
│   │
│   ├── services/
│   │   ├── groww_service.py       # Groww SDK wrapper (TOTP auth)
│   │   ├── market_data.py         # Live data + indicator computation
│   │   ├── ai_engine.py           # Claude agentic loop
│   │   ├── portfolio_monitor.py   # Orchestrator: fetch → analyze → alert
│   │   ├── telegram_bot.py        # Bot commands + push notifications
│   │   ├── database.py            # MongoDB async client
│   │   ├── micro_monitor.py       # 10-second polling engine (v2)
│   │   └── screener.py            # Stock screener engine (v2)
│   │
│   ├── tools/
│   │   ├── definitions.py         # 10 Claude tool schemas
│   │   └── executor.py            # Tool dispatch logic
│   │
│   ├── scheduler/
│   │   ├── setup.py               # APScheduler config
│   │   └── jobs.py                # Scheduled job functions
│   │
│   ├── api/
│   │   ├── router.py              # REST API endpoints
│   │   └── dependencies.py        # API key verification
│   │
│   └── utils/
│       ├── market_hours.py        # IST market hours, NSE holidays
│       ├── indicators.py          # RSI, MACD, SMA, EMA, Bollinger
│       ├── formatters.py          # Telegram HTML formatters
│       ├── logger.py              # Structured logging
│       ├── cache.py               # In-memory quote cache
│       ├── circuit_breaker.py     # API failure protection
│       └── exceptions.py          # Custom exception hierarchy
│
└── tests/
    ├── conftest.py                # Shared pytest fixtures
    ├── test_indicators.py         # Technical indicator tests
    └── test_market_hours.py       # Market hours/holiday tests
```

## Prerequisites

- **Python 3.11+**
- **MongoDB** (local or cloud - MongoDB Atlas supported)
- **Groww Trading Account** with [Trade API subscription](https://groww.in/trade-api)
- **Anthropic API key** from [console.anthropic.com](https://console.anthropic.com/)
- **Telegram bot token** from [@BotFather](https://t.me/BotFather)

## Setup

### 1. Clone and Install

```bash
cd Stock-AI

# Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
.venv\Scripts\activate      # Windows

# Install dependencies
pip install -e .

# Or with dev tools (pytest, ruff, mypy)
pip install -e ".[dev]"
```

### 2. Configure Environment

Create a `.env` file in the root directory:

```env
# Groww Trading API
GROWW_API_KEY=your_groww_totp_token
GROWW_TOTP_SECRET=your_totp_secret

# Anthropic Claude API
ANTHROPIC_API_KEY=sk-ant-xxxxx
CLAUDE_MODEL=claude-sonnet-4-20250514
CLAUDE_MAX_TOKENS=4096

# Telegram Bot
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=your_numeric_chat_id
TELEGRAM_WEBHOOK_URL=  # Optional: https://your-app.onrender.com (leave empty for polling)

# MongoDB
MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=stock_ai

# Monitoring Schedule
MONITOR_INTERVAL_MINUTES=15

# Alert Thresholds
PNL_ALERT_THRESHOLD_PCT=5.0
PORTFOLIO_ALERT_THRESHOLD_PCT=3.0

# MicroMonitor Settings (v2)
MICRO_POLL_INTERVAL_SECONDS=10
MICRO_VELOCITY_THRESHOLD_PCT=0.5
MICRO_CONSECUTIVE_TICKS=3

# Screener Settings (v2)
SCREENER_SYMBOLS_FILE=nse_symbols.json
SCREENER_TOP_N=10

# Resilience (v2)
CACHE_TTL_SECONDS=8
MAX_RETRY_ATTEMPTS=3
CIRCUIT_BREAKER_THRESHOLD=5
CIRCUIT_BREAKER_RESET_SECONDS=60
ALERT_COOLDOWN_SECONDS=300

# REST API
API_KEY=  # Optional: set to enable X-API-Key authentication

# Logging
LOG_LEVEL=INFO
LOG_JSON=false
LOG_FILE=stock_ai.log
```

**Getting your Telegram chat ID:**
1. Start a chat with your bot
2. Send any message
3. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
4. Find your `chat.id` in the response

**Getting Groww API keys:**
1. Go to [Groww Cloud API Keys](https://groww.in/trade-api/cloud/api-keys)
2. Generate a TOTP token
3. Copy the token and TOTP secret

### 3. Start MongoDB

```bash
# Using Docker
docker run -d --name mongodb -p 27017:27017 mongo:7

# Or MongoDB Atlas (cloud)
# Set MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/

# Or install locally
# https://www.mongodb.com/docs/manual/installation/
```

### 4. (Optional) Prepare NSE Symbols for Screener

Create `nse_symbols.json` in the root directory:

```json
[
  {"symbol": "RELIANCE", "name": "Reliance Industries", "sector": "Energy"},
  {"symbol": "TCS", "name": "Tata Consultancy Services", "sector": "IT"},
  {"symbol": "HDFCBANK", "name": "HDFC Bank", "sector": "Financial Services"},
  ...
]
```

If this file is missing, the screener will fall back to screening only your current holdings.

### 5. Run the Application

```bash
# Development (with auto-reload)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Production
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

On startup, you'll see:

```
Starting Stock AI Portfolio Monitor v2
MongoDB connected
Groww API authenticated
Telegram bot started
Scheduler started with market-hours jobs
MicroMonitor started (10-second price polling)
All systems online.
• 10-second live price tracking active
• AI analysis every 15 minutes during market hours
• Daily screener at 9:30 AM IST
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/status` | Quick portfolio P&L summary |
| `/portfolio` | Detailed per-stock breakdown with P&L |
| `/analyze RELIANCE` | On-demand AI analysis for any stock |
| `/alerts` | Recent alert history |
| `/signals` | Active trade signals (BUY/SELL/HOLD) |
| `/live` ⭐ **NEW** | Current 10-second tick state for all holdings |
| `/screen` ⭐ **NEW** | Run stock screener on-demand |
| `/opportunity` ⭐ **NEW** | View latest screener results |
| `/watchlist` ⭐ **NEW** | Manage personal watchlist |
| `/settings` | View current alert thresholds |
| `/help` | List all commands |

You can also **send free-text messages** to ask questions like:
- "Should I sell INFY?"
- "How is my portfolio diversified?"
- "Show me stocks with strong momentum right now"

## REST API Endpoints

All endpoints are prefixed with `/api/v1`:

### Portfolio & Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/portfolio` | Latest portfolio snapshot |
| `GET` | `/analysis/latest?analysis_type=stock` | Most recent AI analysis |
| `GET` | `/analysis/history?limit=20&offset=0` | Analysis history (paginated) |

### Alerts & Signals

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/alerts?limit=50&offset=0` | Recent alerts (paginated) |
| `GET` | `/signals` | Active trade signals |
| `GET` | `/signals/{symbol}?limit=10` | Signals for specific stock |
| `POST` | `/analyze/{symbol}` | Trigger on-demand AI analysis |

### MicroMonitor (v2)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/micro-signals?limit=50&symbol=RELIANCE` | Recent micro-signals (10-sec alerts) |

### Screener (v2)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/screener/results` | Latest screener results |
| `POST` | `/screener/run` | Trigger on-demand stock screen |

### System

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check (includes MicroMonitor status) |
| `GET` | `/settings` | Current user settings |
| `PUT` | `/settings` | Update settings |
| `GET` | `/ai/usage?days=7` | Claude API token usage summary |

**Interactive docs:** `http://localhost:8000/docs` (Swagger UI)

**Authentication:** Set `API_KEY` in `.env` to enable X-API-Key header authentication.

## Claude AI Engine

The AI engine uses an **agentic loop** where Claude autonomously decides what data to fetch via tool-use:

### Tool Execution Flow

```
User Request → Claude decides tools → Executor fetches data → Claude analyzes → Structured JSON response
```

### AI Output Format

Claude returns:
- **Action**: `BUY` / `SELL` / `HOLD` / `STRONG_BUY` / `STRONG_SELL`
- **Confidence**: 0.0 to 1.0
- **Target price** and **stop-loss**
- **Reasoning** backed by technical data
- **Risk level**: `LOW` / `MEDIUM` / `HIGH`
- **Market sentiment**: `BULLISH` / `BEARISH` / `NEUTRAL`
- **Timeframe**: Short-term, medium-term, or long-term holding

## Scheduled Jobs

All jobs respect NSE holidays and weekends:

| Job | Schedule | Description |
|-----|----------|-------------|
| **MicroMonitor Loop** | Every 10s, Mon-Fri 9:15-15:30 IST | Price polling + momentum tracking |
| **Portfolio Monitor** | Every 15 min, Mon-Fri 9:15-15:30 IST | Full AI analysis cycle |
| **Market Open** | 9:15 AM IST | Re-authenticate Groww + opening notification |
| **Daily Screener** ⭐ **NEW** | 9:30 AM IST | Technical stock screening + AI ranking |
| **Market Close** | 3:35 PM IST | End-of-day summary |
| **Daily AI Analysis** | 3:40 PM IST | Comprehensive portfolio analysis |
| **Health Check** | Every 30 min during market hours | Verify Groww + MongoDB connectivity |

## MongoDB Collections

| Collection | Purpose |
|------------|---------|
| `portfolio_snapshots` | Timestamped portfolio state (holdings + P&L) |
| `analysis_logs` | Claude AI analysis results |
| `alerts_history` | All sent alerts (threshold + AI-based) |
| `trade_signals` | BUY/SELL/HOLD signals with status tracking |
| `user_settings` | Configurable thresholds and watchlist |
| `micro_signals` ⭐ **NEW** | 10-second polling alerts |
| `screener_results` ⭐ **NEW** | Daily stock screener outputs |

## Configuration Reference

All settings are in `.env`:

### Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `GROWW_API_KEY` | required | Groww TOTP token |
| `GROWW_TOTP_SECRET` | required | TOTP secret for auth codes |
| `ANTHROPIC_API_KEY` | required | Anthropic API key |
| `TELEGRAM_BOT_TOKEN` | required | Telegram bot token |
| `TELEGRAM_CHAT_ID` | required | Your Telegram chat ID |
| `MONGODB_URI` | `mongodb://localhost:27017` | MongoDB connection string |

### Monitoring

| Variable | Default | Description |
|----------|---------|-------------|
| `MONITOR_INTERVAL_MINUTES` | `15` | AI analysis cycle interval |
| `PNL_ALERT_THRESHOLD_PCT` | `5.0` | Alert when stock moves > X% |
| `PORTFOLIO_ALERT_THRESHOLD_PCT` | `3.0` | Alert when portfolio moves > X% |

### MicroMonitor (v2)

| Variable | Default | Description |
|----------|---------|-------------|
| `MICRO_POLL_INTERVAL_SECONDS` | `10` | Price polling frequency |
| `MICRO_VELOCITY_THRESHOLD_PCT` | `0.5` | % change per tick to alert |
| `MICRO_CONSECUTIVE_TICKS` | `3` | Consecutive ticks threshold |

### Screener (v2)

| Variable | Default | Description |
|----------|---------|-------------|
| `SCREENER_SYMBOLS_FILE` | `nse_symbols.json` | NSE universe file |
| `SCREENER_TOP_N` | `10` | Top candidates for Claude |

### Resilience (v2)

| Variable | Default | Description |
|----------|---------|-------------|
| `CACHE_TTL_SECONDS` | `8` | Quote cache TTL |
| `MAX_RETRY_ATTEMPTS` | `3` | Groww API retries |
| `CIRCUIT_BREAKER_THRESHOLD` | `5` | Failures before circuit opens |
| `CIRCUIT_BREAKER_RESET_SECONDS` | `60` | Circuit recovery time |
| `ALERT_COOLDOWN_SECONDS` | `300` | Duplicate alert suppression window |

### Advanced

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_MODEL` | `claude-sonnet-4-20250514` | Claude model ID |
| `CLAUDE_MAX_TOKENS` | `4096` | Max response tokens |
| `TELEGRAM_WEBHOOK_URL` | `` | HTTPS webhook URL (empty = polling) |
| `API_KEY` | `` | X-API-Key auth (empty = disabled) |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_JSON` | `false` | JSON log format |

## Running Tests

```bash
# Run all tests
pytest

# With coverage report
pytest --cov=src --cov-report=html

# Specific test file
pytest tests/test_indicators.py -v

# Watch mode
pytest-watch
```

## Rate Limits

### Groww API Limits

| Type | Per Second | Per Minute |
|------|-----------|-----------|
| Orders (place/modify/cancel) | 10 | 250 |
| Live Data (quotes, LTP, OHLC) | 10 | 300 |
| Non-Trading (holdings, positions) | 20 | 500 |

The SDK automatically chunks requests (50 symbols per call) and adds delays to respect limits.

### Application Rate Limits (v2)

- **Telegram free-text messages**: 10 per user per 5 minutes
- **Alert cooldown**: 1 alert per symbol per 5 minutes
- **Quote cache**: 8-second TTL to reduce API calls

## Deployment

### Local Development

```bash
uvicorn main:app --reload
```

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -e .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Cloud Platforms

**Render.com / Railway.app:**
- Set environment variables in dashboard
- Use `TELEGRAM_WEBHOOK_URL` for better reliability
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

**Heroku:**
- Add `Procfile`: `web: uvicorn main:app --host 0.0.0.0 --port $PORT`
- Set all `.env` variables as config vars
- Use MongoDB Atlas for database

## Troubleshooting

### MicroMonitor not tracking symbols

**Symptom:** `/live` command shows "no tick data yet"

**Solution:**
- Ensure you have active holdings in your Groww account
- Check logs for "MicroMonitor tracking X symbols" message
- Verify market is open (9:15 AM - 3:30 PM IST, Mon-Fri)

### Screener returns no candidates

**Symptom:** Daily screener finds 0 stocks

**Solution:**
- Check if `nse_symbols.json` exists and is populated
- Verify NSE symbols have enough historical data (90 days)
- Adjust scoring thresholds in `screener.py` if criteria are too strict

### Telegram webhook not receiving updates

**Symptom:** Bot doesn't respond to commands

**Solution:**
- Verify `TELEGRAM_WEBHOOK_URL` is publicly accessible HTTPS URL
- Check webhook status: `https://api.telegram.org/bot<TOKEN>/getWebhookInfo`
- Try polling mode (clear `TELEGRAM_WEBHOOK_URL` in `.env`)

### MongoDB connection errors

**Symptom:** "MongoDB connection timeout"

**Solution:**
- Check `MONGODB_URI` format
- For MongoDB Atlas: Whitelist your IP in Network Access
- For local MongoDB: Ensure service is running on port 27017

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Run tests (`pytest`)
4. Lint code (`ruff check src/`)
5. Commit changes (`git commit -m 'Add amazing feature'`)
6. Push to branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## Roadmap

- [ ] **Phase 4**: AI cost tracking and usage analytics dashboard
- [ ] **Phase 5**: Multi-user support with per-user portfolios
- [ ] **Phase 6**: Options chain analysis and F&O strategy recommendations
- [ ] Web dashboard with real-time charts
- [ ] WhatsApp integration as alternative to Telegram
- [ ] Sentiment analysis from news and social media
- [ ] Backtesting engine for signal validation

## Disclaimer

This tool is for **informational and educational purposes only**. AI-generated trade signals are not financial advice. Always do your own research and consult with a qualified financial advisor before making investment decisions. Past performance does not guarantee future results. Trading in the stock market involves risk, including the potential loss of principal.

## License

MIT License - see [LICENSE](LICENSE) file for details

---

**Version:** 2.0.0
**Last Updated:** March 2026
**Author:** Built with Claude Code

For questions, issues, or feature requests, please open an issue on GitHub.
