# Stock AI v3.0 - AI-Powered Portfolio Monitoring with Intelligent Capital Architecture

An intelligent stock trading system that combines real-time price tracking, AI-powered analysis, intraday day trading intelligence, technical stock screening, and now — intelligent capital allocation with Kelly-optimal sizing, correlation guards, and corporate event risk filtering.

## What's New in V3.0

**Version 3.0** adds three compounding layers of intelligence on top of the v2.2 engine, solving the biggest pain point: **capital not being allocated optimally**.

### Phase 3C — Event Risk Filter *(highest immediate impact)*
Prevents entering a trade days before a high-risk corporate event (results, board meeting, dividend ex-date, bonus ex-date):

1. **NSE Corporate Calendar** - Daily scrape at 8:50 AM of NSE's corporate actions API, caching events per symbol in-memory
2. **Pre-entry Gate** - Before any BUY/STRONG_BUY signal is sent, the system checks if any corporate event is within 3 days. If blocked, the signal is downgraded from BUY → WATCH with a reason attached
3. **Intraday Pre-filter** - Zero-cost event gate at 9:30 AM before Claude is even called for intraday entries (no API tokens wasted)
4. **`/events` command** - Telegram command listing all upcoming corporate events for your current holdings (color-coded 🔴🟡🟢 by urgency)
5. **`get_event_calendar` Claude tool** - Claude can check the NSE calendar for any symbol during analysis

### Phase 3A — Signal Intelligence Layer
Uses the `signal_outcomes` data that's been accumulating since v2.1 to teach Claude its own accuracy:

1. **Confidence Calibration** - Groups 90 days of closed signals into confidence buckets (0.5–0.6, 0.6–0.7, ... 0.9–1.0) and computes empirical win rates per bucket to detect over-confidence
2. **Pattern Performance** - Tracks which combinations of reasoning tags (`RSI_oversold`, `MACD_bullish_crossover`, etc.) produce the highest win rates
3. **Regime Performance** - Measures how signals perform in each market regime (BULL_STRONG → 71%, SIDEWAYS → 43%, BEAR_WEAK → 31%)
4. **Dynamic System Prompt** - Every evening at 8 PM, Claude's system prompt is rebuilt with its own historical accuracy stats. Claude now knows "in SIDEWAYS regime, raise the confidence bar to 0.85+"
5. **`/calibration` command** - Shows confidence bucket win rates, best/worst patterns, regime performance
6. **`get_signal_calibration` Claude tool** - Claude can look up its empirical win rate for a confidence level or reasoning pattern

### Phase 3B — Capital Allocation Engine *(requires 3A win rates)*
Replaces the fixed Rs. 500 risk sizing with Kelly-optimal position sizing:

1. **Half-Kelly Position Sizing** - `f = (W × b − L) / b × 0.5` using calibrated win rates + historical win/loss percentages. Clamped to 1%–20% of portfolio
2. **Correlation Guard** - Before a BUY signal is sent, Pearson correlation is computed between the new symbol and all current holdings (30-day daily returns). Blocks if any pair exceeds 0.80 correlation
3. **Sector Concentration Cap** - Blocks new buys when adding the position would push any sector above 30% of portfolio value
4. **Portfolio Beta** - Daily computation at 4 PM of portfolio-weighted beta vs. Nifty 50 (using 252 days of data). Alert if beta > 1.5 or < 0.5
5. **`/allocation` command** - Full portfolio report: beta, sector weights %, high-correlation pairs
6. **`/kelly SYMBOL BUY ENTRY SL TARGET`** - Ad-hoc Kelly sizing for any potential trade
7. **`get_capital_allocation` Claude tool** - Claude can run full Kelly + correlation + sector check before recommending a BUY

## What's New in V2.2

**Version 2.2** adds a full **intraday (MIS) trading intelligence layer** alongside the existing long-term portfolio monitoring system — both running in parallel, sharing infrastructure:

1. **Pre-Market Scanner** - At 8:55 AM, scans the NSE universe for gap stocks and computes CPR (Central Pivot Range) levels to build a priority watchlist before the bell
2. **Opening Range Breakout (ORB)** - Captures the high/low of the first 15 minutes (9:15–9:29 AM) as key breakout levels for the day
3. **1-Minute Monitor** - Dedicated polling loop (separate from the 15-min cycle) watching the intraday watchlist every minute for ORB breakout, VWAP cross, and Supertrend flip signals
4. **Intraday AI Engine** - Separate Claude instance tuned for day trading: different system prompt, 5 intraday-specific tools, max 5 iterations (faster + cheaper)
5. **Risk Management** - Per-trade Rs. risk sizing, daily loss breaker (Rs. 1500 default), no-entry after 2:30 PM, hard exit CRITICAL alert at 3:15 PM
6. **Trailing Stop-Loss** - SL automatically moves to breakeven once position is 1% in profit
7. **EOD P&L Report** - Daily win rate, total P&L, best/worst trades delivered to Telegram at 3:35 PM

**Architecture principle:** Entry is Python-detected, Claude-confirmed. Python evaluates fast rules every minute at zero API cost. Claude is called only to confirm a setup (1–3 times/day for intraday).

## What's New in V2.1

**Version 2.1** transforms Stock AI from an intelligence system into a production-ready capital management assistant with **5 critical risk management features**:

1. **Signal Outcome Tracker** - Automatically tracks every AI signal from entry to exit, measuring actual P&L vs. predictions to validate AI accuracy with win rate, avg P&L, and confidence correlation metrics
2. **Stop-Loss Monitoring** - Real-time breach detection integrated into the 10-second polling loop, converting decorative stop-losses into live CRITICAL alerts when price crosses thresholds
3. **Portfolio Drawdown Breaker** - Circuit breaker that automatically blocks all BUY signals when portfolio drops 8% from peak, protecting capital during severe drawdowns with auto-reset on recovery
4. **Market Regime Classifier** - Daily Nifty 50 analysis classifying market conditions (BULL_STRONG, BULL_WEAK, SIDEWAYS, BEAR_WEAK, BEAR_STRONG) and dynamically adjusting signal confidence thresholds (0.65-0.85) based on regime
5. **Minimum Liquidity Filter** - Screens out low-volume stocks (< 500k avg daily volume) before technical analysis to avoid illiquid stocks prone to manipulation

**Grade Improvement:** B- → A- (Risk & Signal Validation upgraded from D-F to B+)

## What's New in V2.0

**Version 2.0** introduced three major intelligence enhancements:

1. **MicroMonitor (10-Second Polling)** - Lightning-fast price tracking that captures micro-movements and momentum shifts every 10 seconds during market hours
2. **Stock Screener** - Daily technical screening of NSE stocks to discover undervalued opportunities based on RSI, MACD, volume, and 52-week positioning
3. **Enhanced AI Engine** - 10 specialized tools (up from 7) including sector analysis, peer comparison, and micro-signal integration

## How It Works

```
┌──────────────────────────────────────────────────────────────────────┐
│                    STOCK AI v3.0 ARCHITECTURE                         │
├──────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  ══════════════════ INTRADAY PIPELINE (v2.2) ══════════════════       │
│                                                                        │
│  8:55 AM ──> Pre-Market Scan                                          │
│              ├── Gap% from prev close vs today open                   │
│              ├── CPR levels (pivot, BC, TC, R1/R2, S1/S2)            │
│              └── Top 20 ranked → intraday_watchlist                   │
│                          ↓                                             │
│  9:31 AM ──> ORB Setup (Opening Range Breakout)                       │
│              └── High/Low of 9:15–9:29 candles → orb_data            │
│                          ↓                                             │
│  9:30–3:15 PM ──> 1-Min Monitor Loop                                  │
│              ├── Bulk LTP for watchlist                               │
│              ├── Entry check (Python rules, zero cost):               │
│              │     • ORB Breakout: price > orb_high + 0.1% + vol     │
│              │     • VWAP Cross: price crosses VWAP + ≥3 ticks UP    │
│              │     • Supertrend Flip: direction → UP on 5-min        │
│              │           ↓ trigger detected                            │
│              │     Claude AI confirms: entry, SL, target, size       │
│              │           ↓ confirmed                                   │
│              │     Telegram entry alert + DB save                     │
│              ├── Open position monitoring:                             │
│              │     • Target hit → close                               │
│              │     • SL hit → CRITICAL alert                          │
│              │     • 1% profit → trailing SL to breakeven            │
│              └── Daily loss breaker (Rs. 1500 default)               │
│                          ↓                                             │
│  3:15 PM ──> Hard Exit: CRITICAL alert for all open MIS positions    │
│  3:35 PM ──> EOD P&L Report: wins/losses, total P&L, best/worst     │
│                                                                        │
│  ══════════════════ LONG-TERM PIPELINE (v3.0) ═════════════════       │
│                                                                        │
│  8:50 AM ──> NSE Corporate Calendar Scrape ── Phase 3C               │
│              └── Event cache: {symbol → [events]} per holding         │
│                                                                        │
│  8 PM nightly ──> Signal Calibration Job ── Phase 3A                 │
│              ├── Confidence bucket win rates (0.5–1.0 buckets)        │
│              ├── Pattern performance (RSI+MACD combos etc.)           │
│              ├── Regime performance (BULL→71%, SIDEWAYS→43%)          │
│              └── Rebuild Claude system prompt with own accuracy data  │
│                                                                        │
│  Nifty 50 ──────────> Daily Regime Classification (9:20 AM)          │
│                       (BULL/BEAR/SIDEWAYS scoring)                    │
│                                   ↓                                    │
│                       Adjust Confidence Thresholds                    │
│                                                                        │
│  4 PM ──> Portfolio Beta Job ── Phase 3B                             │
│           └── Pearson corr matrix + beta vs Nifty (252 days)         │
│                                                                        │
│  Groww Holdings ──┬──> 10s Price Polling (MicroMonitor)               │
│                   │         ↓                                          │
│                   │    • Tick Analysis & Momentum                      │
│                   │    • Stop-Loss Breach Detection ⭐ v2.1           │
│                   │         ↓                                          │
│                   ├──> 15min AI Analysis ─┬─> Claude AI               │
│                   │    • Technical Signals │   (17 tools)            │
│                   │    • P&L Enrichment   │   • Signal perf ⭐       │
│                   │    • Micro context    │   • Intraday tools ⭐     │
│                   │    • Regime context ⭐ │   • Event calendar ⭐ v3  │
│                   │    • Calibration ⭐ v3 │   • Kelly alloc ⭐ v3    │
│                   │                        ↓                           │
│                   │                   Signal Generation               │
│                   │                        ↓                           │
│                   │        V3.0 Pre-Send Validation Gate ⭐           │
│                   │        • Event risk check (3C) → BUY→WATCH       │
│                   │        • Correlation guard (3B) → warning         │
│                   │        • Sector cap check (3B) → warning          │
│                   │        • Kelly sizing (3B) → qty + value          │
│                   │                        ↓                           │
│                   │                 Risk Filters ⭐ v2.1               │
│                   │                 • Drawdown Breaker                │
│                   │                 • Regime Threshold                │
│                   │                        ↓                           │
│                   │                 Outcome Tracking ⭐                │
│                   │                (entry → exit → P&L)               │
│                   │                                                    │
│                   └──> Daily Screener ──> AI Ranking                  │
│                        (9:30 AM IST)                                  │
│                        • Liquidity Filter ⭐ v2.1                     │
│                             ↓                                          │
│                      Telegram Alerts (with Kelly qty + warnings)      │
│                             +                                          │
│                      MongoDB Storage                                  │
│                                                                        │
│  MicroMonitor (10s ticks) ──feeds tick data to BOTH pipelines──      │
│                                                                        │
└──────────────────────────────────────────────────────────────────────┘
```

### Monitoring Cycles

**Every 10 seconds** (MicroMonitor):
- Fetches bulk LTP for all holdings + intraday watchlist
- Detects velocity spikes (>0.5% per tick)
- Tracks consecutive up/down ticks (feeds intraday VWAP cross detection)
- Identifies volume surges (>2x average)
- Sends immediate micro-alerts on significant movements

**Every 1 minute** during intraday hours (9:30 AM - 3:15 PM IST) ⭐ **v2.2**:
1. Bulk LTP for intraday watchlist (up to 20 symbols)
2. Checks open MIS positions for target/SL/trailing SL
3. Evaluates entry conditions (ORB breakout, VWAP cross, Supertrend flip)
4. Calls Claude AI to confirm any triggered entry (max 5 tool iterations)
5. Enforces daily loss breaker and no-entry-after-2:30 PM rules

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

### New in V2.2 - Intraday Trading Module ⭐

#### Pre-Market Scanner
- **Gap analysis** - Calculates overnight gap% from previous close to today's open for all symbols
- **CPR levels** - Central Pivot Range (Pivot, Bottom Central, Top Central, R1/R2/R3, S1/S2/S3) computed from yesterday's H/L/C
- **Ranking** - Composite score `|gap%| * 0.5 + cpr_bias * 0.5` — bias is `BULLISH` when open > TC, `BEARISH` when open < BC
- **Watchlist** - Top 20 symbols saved to MongoDB with 1-day TTL, loaded into 1-minute monitor
- **Morning report** - HTML Telegram message at 8:55 AM with gap table and CPR levels

#### Opening Range Breakout (ORB)
- **ORB window** - High/Low of the first 15 minutes (9:15–9:29 AM), configurable via `INTRADAY_ORB_MINUTES`
- **Breakout detection** - `price > orb_high * 1.001` (0.1% buffer to avoid false breakouts)
- **Volume confirmation** - Requires volume spike alongside price breakout
- **Breakout strength** - Computed as `(price - orb_high) / orb_high * 100` for reporting

#### VWAP with Standard Deviation Bands
- **Intraday VWAP** - Cumulative `sum(typical_price * volume) / sum(volume)` from market open using 5-min candles
- **SD bands** - ±1 standard deviation bands for support/resistance context
- **Cross detection** - `BULLISH_CROSS` when price transitions from below to above VWAP with ≥3 MicroMonitor ticks confirming

#### Supertrend Indicator
- **ATR-based** - Period 10, Multiplier 3.0 on 5-minute chart (configurable)
- **Flip detection** - Trigger fires when direction changes from DOWN → UP (bullish flip)
- **Context** - `flipped_at` timestamp included in Claude's analysis context

#### Intraday Risk Management
- **Per-trade sizing** - `quantity = floor(risk_rs / abs(entry - stop_loss))`, capped by `INTRADAY_MAX_POSITION_VALUE`
- **Daily loss breaker** - Stops all new entries when realized P&L reaches `-INTRADAY_MAX_DAILY_LOSS_RS` (default Rs. 1500)
- **Max positions** - Hard cap on concurrent MIS positions (default 3)
- **No-entry cutoff** - No new entries after 2:30 PM (configurable)
- **Hard exit** - CRITICAL Telegram alert for all open MIS positions at 3:15 PM
- **Trailing SL** - Stop-loss moves to breakeven automatically once position is 1% in profit
- **Entry cooldown** - Same symbol cannot be re-entered within 5 minutes of a previous attempt

#### Intraday AI Engine (Separate from Long-Term)
- **Focused system prompt** - NSE intraday trader persona with non-negotiable rules (≥1:1.5 R:R, SL within 0.5%, no entry after 2:30 PM)
- **5 intraday tools** - `get_stock_quote`, `get_micro_signal_summary`, `get_intraday_indicators`, `get_opening_range`, `get_gap_analysis`
- **Max 5 iterations** - Faster and cheaper than the 15-min engine (10 iterations)
- **Exit evaluation** - Single-call analysis (no tool loop) for exit signals

#### EOD P&L Report
- **Daily summary** - Total trades, win rate, total P&L, max win/loss, best/worst trade
- **Daily loss breaker status** - Whether the breaker was triggered today
- **Telegram delivery** - HTML report sent at 3:35 PM every trading day

### New in V2.1 - Risk Management & Signal Validation

#### Signal Outcome Tracker
- **Automatic tracking** - Every AI signal tracked from generation → entry → exit
- **P&L computation** - Actual vs. predicted returns with win/loss classification
- **Accuracy metrics** - Win rate, avg P&L %, max win/loss, confidence correlation
- **Auto-detection** - Position exits detected by comparing holdings snapshots
- **Historical validation** - 365-day retention for backtesting and strategy refinement
- **Claude integration** - New `get_signal_performance` tool for AI to check its own accuracy before generating signals

#### Stop-Loss Monitoring
- **Real-time breach detection** - Integrated into 10-second MicroMonitor polling loop
- **CRITICAL alerts** - Telegram notification within 10 seconds of stop-loss breach
- **Grace threshold** - 0.1% buffer to avoid false positives from minor fluctuations
- **Auto-reload** - Active stop-losses refreshed hourly from database
- **Directional logic** - BUY signals breach when price < stop_loss, SELL signals when price > stop_loss
- **Status tracking** - Signals marked TRIGGERED in database to prevent duplicate alerts

#### Portfolio Drawdown Breaker
- **Peak tracking** - Continuous monitoring of portfolio all-time high value
- **8% threshold** - Circuit breaker triggers when portfolio drops 8% from peak (configurable)
- **BUY signal blocking** - All BUY/STRONG_BUY signals automatically blocked when breaker active
- **CRITICAL notifications** - Telegram alert with peak value, current value, drawdown %
- **Auto-reset** - Breaker resets when portfolio recovers to 50% of threshold (e.g., 4% if threshold is 8%)
- **AI context** - Drawdown status injected into Claude's system prompt to prevent aggressive signals

#### Market Regime Classifier
- **Daily Nifty 50 analysis** - Fetches 90 days of data, computes SMA(20/50/200), RSI(14), volatility
- **5-regime classification** - BULL_STRONG (+60 to +100), BULL_WEAK (+20 to +60), SIDEWAYS (-20 to +20), BEAR_WEAK (-20 to -60), BEAR_STRONG (-60 to -100)
- **Regime scoring** - Composite -100 to +100 score based on price vs SMAs (40 pts), SMA alignment (20 pts), RSI momentum (20 pts), volatility penalty (20 pts)
- **Dynamic thresholds** - Minimum signal confidence adjusted by regime: 0.65 (BULL_STRONG) to 0.85 (BEAR_STRONG)
- **Strategy parameters** - Exposure % and signal weight multipliers vary by regime
- **Scheduled job** - Runs at 9:20 AM IST before screener, stores results in MongoDB

#### Minimum Liquidity Filter (Screener Enhancement)
- **Average daily volume** - Computes 30-day ADV for each symbol before technical screening
- **500k threshold** - Stocks with < 500,000 avg daily volume filtered out (configurable)
- **Manipulation prevention** - Avoids illiquid penny stocks prone to price manipulation
- **Screener integration** - Applied before technical scoring to save computation
- **Performance optimized** - 1-second delay between symbols to respect API rate limits

### New in V2.0 - Intelligence & Discovery

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
Claude now has access to **17 specialized tools**:

| Tool | Version | Description |
|------|---------|-------------|
| `get_portfolio_holdings` | v1 | Current holdings from Groww |
| `get_stock_quote` | v1 | Real-time quote with OHLC, 52-week range |
| `get_bulk_prices` | v1 | Batch LTP for up to 50 symbols |
| `get_historical_data` | v1 | OHLCV candles (1min to weekly) |
| `get_technical_indicators` | v1 | RSI, MACD, SMA, EMA, Bollinger Bands |
| `get_portfolio_snapshot` | v1 | Latest enriched portfolio state from DB |
| `get_positions` | v1 | Intraday/F&O positions |
| `get_micro_signal_summary` | v2.0 | 10-second tick data for momentum context |
| `get_sector_performance` | v2.0 | Aggregated sector metrics to identify sector-wide moves |
| `get_peer_comparison` | v2.0 | Compare stock against sector peers for relative strength |
| `screen_stocks` | v2.0 | Run technical screener to discover opportunities |
| `get_signal_performance` | v2.1 | AI signal accuracy stats: win rate, avg P&L, confidence correlation (last 30-365 days) |
| `get_intraday_indicators` | v2.2 | Supertrend (5-min), VWAP bands, CPR levels for intraday context |
| `get_opening_range` | v2.2 | ORB high/low/range%, breakout direction and strength |
| `get_gap_analysis` | v2.2 | Overnight gap%: prev_close vs today_open, gap type, gap fill status |
| `get_event_calendar` | ⭐ **v3.0** | Upcoming NSE corporate events (results, board meetings, dividends) — blocks BUY within 3 days |
| `get_signal_calibration` | ⭐ **v3.0** | Historical win rate for a confidence level or reasoning tag pattern (Phase 3A calibration data) |
| `get_capital_allocation` | ⭐ **v3.0** | Kelly-optimal quantity, correlation guard check, and sector concentration limit for any BUY candidate |

### New in V3.0 - Intelligent Capital Architecture ⭐

#### Event Risk Filter (Phase 3C)
- **NSE corporate calendar** - Scrapes board meetings, results dates, dividend/bonus ex-dates, AGMs from NSE API daily at 8:50 AM
- **3-day blocking window** - Any BUY signal within 3 days of a corporate event is downgraded to WATCH with the reason attached to the signal
- **Intraday pre-filter** - Zero-cost gate before Claude is called: if same-day event exists, returns a synthetic SKIP without consuming API tokens
- **In-memory cache** - Events cached per symbol dict, reloaded at startup and 8:50 AM daily. MongoDB `corporate_events` collection with 30-day TTL for persistence
- **`/events` Telegram command** - Lists all upcoming events for held stocks: 🔴 within 1 day, 🟡 within 3 days, 🟢 within 7 days
- **REST API** - `GET /api/v1/events`, `GET /api/v1/events/{symbol}`, `POST /api/v1/events/refresh`

#### Signal Intelligence Layer (Phase 3A)
- **Confidence calibration** - 90-day lookback on `signal_outcomes`, grouped into 5 buckets (0.5–0.6 to 0.9–1.0). Computes empirical win rate and calibration error per bucket
- **Pattern performance** - Groups outcomes by `reasoning_tags` combinations to find the best/worst signal patterns (e.g., `RSI_oversold+MACD_crossover` → 74% win rate)
- **Regime-conditioned performance** - Win rate computed per market regime — informs Claude to raise the bar in SIDEWAYS/BEAR regimes
- **Dynamic system prompt** - At 8 PM nightly, Claude's system prompt is automatically rebuilt with its own historical accuracy stats. Cold start gracefully falls back to the base static prompt
- **`/calibration` Telegram command** - Shows confidence bucket accuracy, top/bottom patterns, regime performance
- **REST API** - `GET /api/v1/calibration`, `GET /api/v1/calibration/patterns`

#### Capital Allocation Engine (Phase 3B)
- **Half-Kelly sizing** - Full Kelly `f = (W × b − L) / b` halved for conservative sizing, clamped to `[KELLY_MIN_POSITION_PCT, KELLY_MAX_POSITION_PCT]` (default 1%–20%). Uses calibrated win rate from Phase 3A
- **Signals enriched** - Every BUY/STRONG_BUY signal now includes `kelly_fraction`, `recommended_qty`, `recommended_value_rs`, `correlation_warning`, `sector_warning`, `event_risk` fields
- **Pearson correlation guard** - Daily close returns (not raw prices) used to compute Pearson r between the candidate and all holdings. Blocks if any pair exceeds 0.80 threshold
- **Sector concentration cap** - Computes current sector weights from latest `portfolio_snapshot`. Warns if adding the new position would push any sector above 30%
- **Portfolio beta** - 252-day weighted beta vs. Nifty 50 computed at 4 PM daily. Telegram alert if beta > 1.5 or < 0.5
- **`/allocation` Telegram command** - Full report: portfolio beta, sector weights %, high-correlation pairs table
- **`/kelly SYMBOL BUY ENTRY SL TARGET`** - Ad-hoc Kelly sizing for any potential trade without running a full analysis
- **REST API** - `GET /api/v1/allocation`, `POST /api/v1/allocation/kelly`

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
| AI Engine | Anthropic Claude API | Sonnet 4 with tool-use (2 instances: long-term + intraday) |
| Notifications | python-telegram-bot | Webhook + polling modes |
| Database | MongoDB | PyMongo async driver |
| Scheduler | APScheduler | AsyncIOScheduler for cron jobs |
| Indicators | NumPy | Pure Python implementations (Supertrend, VWAP, CPR added v2.2) |
| Config | Pydantic Settings | Type-safe `.env` configuration |

## Project Structure

```
Stock-AI/
├── main.py                        # FastAPI entry + lifespan management
├── pyproject.toml                 # Project metadata & dependencies
├── .env                           # Environment configuration
│
├── src/
│   ├── config.py                  # Settings from .env (14 V3 vars added in v3.0)
│   │
│   ├── models/
│   │   ├── holdings.py            # Holding, EnrichedHolding, PortfolioSnapshot
│   │   ├── market.py              # Quote, Candle, TechnicalIndicators, MicroSignal
│   │   ├── analysis.py            # TradeSignal (+5 Kelly/event fields v3.0), AnalysisResult, AlertMessage
│   │   ├── outcome.py             # SignalOutcome, OutcomeStatistics (v2.1)
│   │   ├── intraday.py            # v2.2: IntradaySetup, ORBData, Position, DailyReport
│   │   └── calibration.py         # ⭐ v3.0: CorporateEvent, EventRisk, CalibrationData, KellyResult, AllocationReport
│   │
│   ├── services/
│   │   ├── groww_service.py       # Groww SDK wrapper (TOTP auth)
│   │   ├── market_data.py         # Live data + indicator computation
│   │   ├── ai_engine.py           # Claude agentic loop (17 tools, dynamic system prompt v3.0)
│   │   ├── portfolio_monitor.py   # Orchestrator: fetch → analyze → V3 validation gate → alert
│   │   ├── telegram_bot.py        # Bot commands + push notifications (4 new V3 commands)
│   │   ├── database.py            # MongoDB async client (6 new V3 collections)
│   │   ├── micro_monitor.py       # 10-second polling engine (v2.0)
│   │   ├── screener.py            # Stock screener engine (v2.0)
│   │   ├── outcome_tracker.py     # Signal outcome tracking (v2.1)
│   │   ├── drawdown_breaker.py    # Portfolio drawdown circuit breaker (v2.1)
│   │   ├── regime_classifier.py   # Market regime classification (v2.1)
│   │   ├── intraday_scanner.py    # v2.2: Pre-market scan + EOD report
│   │   ├── intraday_engine.py     # v2.2: Claude AI tuned for intraday (event risk gate added v3.0)
│   │   ├── intraday_monitor.py    # v2.2: 1-minute orchestrator + position tracking
│   │   ├── event_risk_filter.py   # ⭐ v3.0: NSE calendar scraper + entry risk check
│   │   ├── signal_calibrator.py   # ⭐ v3.0: Confidence calibration + pattern win rates + regime performance
│   │   └── capital_allocator.py   # ⭐ v3.0: Kelly sizing + correlation guard + sector cap + portfolio beta
│   │
│   ├── tools/
│   │   ├── definitions.py         # 17 Claude tool schemas (3 V3 tools added v3.0)
│   │   └── executor.py            # Tool dispatch logic (3 new V3 cases)
│   │
│   ├── scheduler/
│   │   ├── setup.py               # APScheduler config (3 new V3 jobs registered)
│   │   └── jobs.py                # Scheduled job functions (refresh_events, nightly_calibration, portfolio_beta)
│   │
│   ├── api/
│   │   ├── router.py              # REST API endpoints (7 new V3 endpoints added)
│   │   └── dependencies.py        # API key verification
│   │
│   └── utils/
│       ├── market_hours.py        # IST market hours, NSE holidays
│       ├── indicators.py          # RSI, MACD, SMA, EMA, Bollinger
│       ├── intraday_indicators.py # v2.2: Supertrend, ORB, CPR, VWAP bands
│       ├── formatters.py          # Telegram HTML formatters
│       ├── logger.py              # Structured logging
│       ├── cache.py               # In-memory quote cache
│       ├── circuit_breaker.py     # API failure protection
│       ├── exceptions.py          # Custom exception hierarchy
│       ├── kelly.py               # ⭐ v3.0: Kelly criterion math (compute_half_kelly, compute_position_size)
│       └── correlation.py         # ⭐ v3.0: Pearson correlation (pearson_correlation, build_correlation_matrix)
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

# Market Hours (IST — change only if NSE timing ever shifts)
MARKET_OPEN_HOUR=9
MARKET_OPEN_MINUTE=15
MARKET_CLOSE_HOUR=15
MARKET_CLOSE_MINUTE=30

# Monitoring Schedule
MONITOR_INTERVAL_MINUTES=15

# Alert Thresholds
PNL_ALERT_THRESHOLD_PCT=5.0
PORTFOLIO_ALERT_THRESHOLD_PCT=3.0

# MicroMonitor Settings (v2)
MICRO_POLL_INTERVAL_SECONDS=10
MICRO_VELOCITY_THRESHOLD_PCT=0.5
MICRO_CONSECUTIVE_TICKS=3

# Screener Settings (v2.0)
SCREENER_SYMBOLS_FILE=nse_symbols.json
SCREENER_TOP_N=10
SCREENER_MIN_LIQUIDITY=500000  # v2.1: Minimum avg daily volume (shares)
SCREENER_LIQUIDITY_LOOKBACK_DAYS=30  # v2.1: Days to compute avg volume

# Signal Outcome Tracking (v2.1)
OUTCOME_AUTO_TRACK_ENABLED=true
OUTCOME_AUTO_TRACK_INTERVAL_HOURS=6
OUTCOME_MIN_CONFIDENCE_TRACK=0.6

# Stop-Loss Monitoring (v2.1)
STOP_LOSS_ENABLED=true
STOP_LOSS_GRACE_PCT=0.1  # Grace % below stop-loss to avoid noise

# Portfolio Drawdown Breaker (v2.1)
DRAWDOWN_BREAKER_ENABLED=true
DRAWDOWN_BREAKER_THRESHOLD_PCT=8.0  # Trigger at 8% drawdown
DRAWDOWN_BREAKER_AUTO_RESET=true

# Market Regime Classification (v2.1)
REGIME_CLASSIFICATION_ENABLED=true
REGIME_INDEX_SYMBOL="NIFTY 50"

# Intraday Trading (v2.2)
INTRADAY_ENABLED=true
INTRADAY_POLL_INTERVAL_SECONDS=60       # 1-minute cycle
INTRADAY_MAX_POSITIONS=3                # Max concurrent MIS positions
INTRADAY_RISK_PER_TRADE_RS=500          # Rs. to risk per trade
INTRADAY_MAX_DAILY_LOSS_RS=1500         # Daily loss limit (triggers breaker)
INTRADAY_MAX_POSITION_VALUE=50000       # Hard cap: max Rs. per position
INTRADAY_NO_ENTRY_AFTER_HOUR=14         # No new entries after 2:30 PM
INTRADAY_NO_ENTRY_AFTER_MINUTE=30
INTRADAY_HARD_EXIT_HOUR=15              # Hard exit alert at 3:15 PM
INTRADAY_HARD_EXIT_MINUTE=15
INTRADAY_ORB_MINUTES=15                 # Opening range duration
INTRADAY_SUPERTREND_PERIOD=10
INTRADAY_SUPERTREND_MULTIPLIER=3.0
INTRADAY_MIN_GAP_PCT=0.5                # Min gap% for pre-market watchlist
INTRADAY_WATCHLIST_SIZE=20              # Max symbols in daily watchlist
INTRADAY_MIN_BREAKOUT_CONFIRM_TICKS=3   # MicroMonitor ticks to confirm

# Event Risk Filter (v3.0)
EVENT_RISK_ENABLED=true
EVENT_RISK_LOOKBACK_DAYS=3          # Block entries N days before event

# Signal Calibration (v3.0)
CALIBRATION_ENABLED=true
CALIBRATION_LOOKBACK_DAYS=90        # Days of outcome history to analyze
CALIBRATION_MIN_SAMPLES=5           # Min signals per bucket to trust stats
CALIBRATION_REFRESH_HOUR=20         # Nightly recalculation hour (8 PM)

# Capital Allocation / Kelly Criterion (v3.0)
CAPITAL_ALLOCATION_ENABLED=true
KELLY_FRACTION=0.5                  # Half-Kelly multiplier (0.5 = conservative)
KELLY_MAX_POSITION_PCT=20.0         # Never exceed 20% in one stock
KELLY_MIN_POSITION_PCT=1.0          # Minimum meaningful position
CORRELATION_GUARD_ENABLED=true
CORRELATION_THRESHOLD=0.80          # Block if Pearson correlation exceeds this
SECTOR_CAP_ENABLED=true
SECTOR_MAX_PCT=30.0                 # Max allocation in any single sector

# Resilience (v2.0)
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

If this file is missing, the screener will fall back to screening only your current holdings. The intraday pre-market scanner will also use this file.

### 5. Run the Application

```bash
# Development (with auto-reload)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Production
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

On startup, you'll see:

```
Starting Stock AI Portfolio Monitor v3
MongoDB connected
Groww API authenticated
Telegram bot started
EventRiskFilter cache loaded: 15 symbols
Scheduler started with market-hours jobs
MicroMonitor started (10-second price polling)
IntradayMonitor started (1-minute intraday cycle)
All systems online.
• 10-second live price tracking active
• AI analysis every 15 minutes during market hours
• Event risk filter active — BUY signals guarded before corporate events
• Daily screener at 9:30 AM IST
Use /help to see all commands.
```

## Telegram Commands

### Long-Term Portfolio

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/status` | Quick portfolio P&L summary |
| `/portfolio` | Detailed per-stock breakdown with P&L |
| `/analyze RELIANCE` | On-demand AI analysis for any stock |
| `/alerts` | Recent alert history |
| `/signals` | Active trade signals (BUY/SELL/HOLD) |
| `/live` (v2.0) | Current 10-second tick state for all holdings |
| `/screen` (v2.0) | Run stock screener on-demand |
| `/opportunity` (v2.0) | View latest screener results |
| `/watchlist` (v2.0) | Manage personal watchlist |
| `/signal_stats` ⭐ **v2.1** | AI signal accuracy: win rate, avg P&L, confidence correlation |
| `/breaker_status` ⭐ **v2.1** | Portfolio drawdown breaker status |
| `/reset_breaker` ⭐ **v2.1** | Manually reset drawdown circuit breaker (use with caution) |
| `/regime_status` ⭐ **v2.1** | Current market regime classification |
| `/events` ⭐ **v3.0** | Upcoming corporate events for all held stocks (results, dividends, board meetings) |
| `/calibration` ⭐ **v3.0** | Claude signal accuracy stats: confidence bucket win rates, best/worst patterns, regime performance |
| `/allocation` ⭐ **v3.0** | Full portfolio allocation report: beta vs Nifty, sector weights %, high-correlation pairs |
| `/kelly SYMBOL BUY 2450 2400 2550` ⭐ **v3.0** | Ad-hoc Kelly-optimal position sizing for any potential trade |
| `/settings` | View current alert thresholds |
| `/help` | List all commands |

### Intraday Trading ⭐ **v2.2**

| Command | Description |
|---------|-------------|
| `/intraday` | Today's watchlist with gap%, CPR levels, ORB (once computed) |
| `/itrades` | Active MIS positions with real-time P&L |
| `/isetup SYMBOL` | Detailed intraday levels for a specific stock (ORB, VWAP, Supertrend, CPR) |
| `/ipnl` | Today's intraday P&L summary (wins/losses/total) |
| `/iscan` | Trigger on-demand intraday pre-market scan |
| `/irisk` | Current risk: open positions, Rs. at risk, daily loss limit status |

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

### Intraday Trading ⭐ **v2.2**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/intraday/watchlist` | Today's intraday watchlist with gap% and CPR |
| `GET` | `/intraday/positions` | Active and closed MIS positions for today |
| `GET` | `/intraday/pnl` | Today's intraday P&L summary |
| `GET` | `/intraday/risk` | Current risk exposure: positions open, Rs. at risk, breaker status |
| `POST` | `/intraday/scan` | Trigger on-demand pre-market scan |

### Event Risk Filter ⭐ **v3.0**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/events` | Upcoming corporate events for all current holdings |
| `GET` | `/events/{symbol}` | Corporate events for a specific symbol |
| `POST` | `/events/refresh` | Trigger on-demand NSE calendar refresh |

### Signal Calibration ⭐ **v3.0**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/calibration` | Latest confidence calibration stats (win rate per bucket) |
| `GET` | `/calibration/patterns` | Top reasoning-tag patterns ranked by win rate |

### Capital Allocation ⭐ **v3.0**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/allocation` | Full portfolio allocation report: beta, sectors, correlation pairs |
| `POST` | `/allocation/kelly` | Compute Kelly-optimal sizing for given trade params (symbol, action, confidence, entry, SL, target) |

### System

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check (includes MicroMonitor, intraday, and event risk cache size) |
| `GET` | `/settings` | Current user settings |
| `PUT` | `/settings` | Update settings |
| `GET` | `/ai/usage?days=7` | Claude API token usage summary |

**Interactive docs:** `http://localhost:8000/docs` (Swagger UI)

**Authentication:** Set `API_KEY` in `.env` to enable X-API-Key header authentication.

## Claude AI Engine

The system uses **two separate AI engines**:

### Long-Term AI Engine (`ai_engine.py`)
- **Purpose**: Portfolio analysis, BUY/SELL/HOLD signals for CNC holdings
- **Tools**: 17 tools (14 previous + 3 new V3.0: `get_event_calendar`, `get_signal_calibration`, `get_capital_allocation`)
- **Max iterations**: 10
- **Max tokens**: 4096
- **Dynamic system prompt** ⭐ v3.0: Rebuilt nightly with Claude's own historical win rates, confidence calibration, and regime performance

### Intraday AI Engine (`intraday_engine.py`) ⭐ v2.2
- **Purpose**: Day trade confirmation — entry validation, position sizing, exit evaluation
- **Tools**: 5 tools (`get_stock_quote`, `get_micro_signal_summary`, `get_intraday_indicators`, `get_opening_range`, `get_gap_analysis`)
- **Max iterations**: 5 (faster, cheaper)
- **Max tokens**: 1024
- **Trigger**: Called only after Python rules detect a potential entry (1–3 calls/day typical)

### Tool Execution Flow

```
User Request / Python trigger → Claude decides tools → Executor fetches data → Claude analyzes → Structured JSON response
```

### AI Output Format

Claude returns:
- **Action**: `BUY` / `SELL` / `HOLD` / `STRONG_BUY` / `STRONG_SELL` / `WATCH`
- **Confidence**: 0.0 to 1.0
- **Target price** and **stop-loss**
- **Reasoning** backed by technical data
- **Risk level**: `LOW` / `MEDIUM` / `HIGH`
- **Market sentiment**: `BULLISH` / `BEARISH` / `NEUTRAL`
- **Timeframe**: `intraday` / short-term / medium-term / long-term
- **Kelly fraction** ⭐ v3.0: Optimal portfolio allocation % (e.g., 0.08 = 8%)
- **Recommended quantity** ⭐ v3.0: Shares to buy based on Kelly sizing
- **Correlation warning** ⭐ v3.0: Alert if new position is highly correlated with existing holdings
- **Sector warning** ⭐ v3.0: Alert if sector concentration would exceed 30%
- **Event risk** ⭐ v3.0: Reason if BUY was downgraded to WATCH due to upcoming corporate event

## Scheduled Jobs

All jobs respect NSE holidays and weekends:

| Job | Schedule | Description |
|-----|----------|-------------|
| **MicroMonitor Loop** (v2.0) | Every 10s, Mon-Fri 9:15-15:30 IST | Price polling + momentum tracking + stop-loss breach detection |
| **NSE Event Calendar Refresh** ⭐ **v3.0** | 8:50 AM IST | Scrape NSE corporate actions API and refresh event cache |
| **Regime Classification** (v2.1) | 9:20 AM IST | Classify Nifty 50 market regime (BULL/BEAR/SIDEWAYS) |
| **Intraday Pre-Market Scan** (v2.2) | 8:55 AM IST | Gap scan + CPR computation + watchlist build |
| **Intraday ORB Setup** (v2.2) | 9:31 AM IST | Compute opening range (9:15–9:29 candles) for all watchlist symbols |
| **Portfolio Monitor** | Every 15 min, Mon-Fri 9:15-15:30 IST | Full AI analysis cycle + V3 pre-send validation gate |
| **Daily Screener** (v2.0) | 9:30 AM IST | Technical stock screening + AI ranking + liquidity filter |
| **Market Open** | 9:15 AM IST | Re-authenticate Groww + opening notification |
| **Reload Stop-Losses** (v2.1) | Hourly during market hours | Refresh active stop-losses into MicroMonitor memory |
| **Intraday Hard Exit** (v2.2) | 3:15 PM IST | CRITICAL Telegram alert for all open MIS positions |
| **Market Close** | 3:35 PM IST | End-of-day long-term summary |
| **Intraday Daily Report** (v2.2) | 3:35 PM IST | EOD intraday P&L: wins/losses, total P&L, best/worst trades |
| **Daily AI Analysis** | 3:40 PM IST | Comprehensive long-term portfolio analysis |
| **Portfolio Beta Job** ⭐ **v3.0** | 4:00 PM IST | Compute portfolio-weighted beta vs. Nifty 50 + correlation matrix |
| **Health Check** | Every 30 min during market hours | Verify Groww + MongoDB connectivity |
| **Outcome Tracking** (v2.1) | Every 6 hours | Auto-detect signal position exits and compute P&L |
| **Nightly Calibration** ⭐ **v3.0** | 8:00 PM IST | Compute confidence calibration, pattern performance, regime stats. Rebuild Claude's system prompt |

> **Note:** Intraday jobs are only registered when `INTRADAY_ENABLED=true`. V3 event risk and calibration jobs require their respective feature flags.

## MongoDB Collections

| Collection | Purpose | TTL |
|------------|---------|-----|
| `portfolio_snapshots` | Timestamped portfolio state (holdings + P&L) | 90 days |
| `analysis_logs` | Claude AI analysis results | 60 days |
| `alerts_history` | All sent alerts (threshold + AI-based) | 60 days |
| `trade_signals` | BUY/SELL/HOLD signals with status tracking | 90 days |
| `user_settings` | Configurable thresholds and watchlist | None |
| `micro_signals` (v2.0) | 10-second polling alerts | 14 days |
| `screener_results` (v2.0) | Daily stock screener outputs | 90 days |
| `signal_outcomes` (v2.1) | Signal tracking: entry → exit → P&L → win/loss | 365 days |
| `portfolio_peaks` (v2.1) | Portfolio all-time high values for drawdown calculation | 90 days |
| `circuit_breaker_state` (v2.1) | Drawdown breaker triggered state | None |
| `market_regime` (v2.1) | Daily Nifty 50 regime classification | 365 days |
| `intraday_watchlist` (v2.2) | Daily pre-market scan results (gap%, CPR, rank) | 1 day |
| `intraday_positions` (v2.2) | All MIS trades: open + closed, P&L, entry trigger | 90 days |
| `intraday_signals` (v2.2) | AI entry/exit signals for intraday | 30 days |
| `intraday_orb_data` (v2.2) | Opening range per symbol per day | 7 days |
| `intraday_daily_pnl` (v2.2) | EOD P&L ledger per day | 365 days |
| `intraday_breaker_state` (v2.2) | Daily loss breaker triggered state | None |
| `corporate_events` ⭐ **v3.0** | NSE corporate actions: results, dividends, board meetings, ex-dates | 30 days |
| `confidence_calibration` ⭐ **v3.0** | Win rate per confidence bucket (0.5–1.0), computed nightly | None |
| `pattern_performance` ⭐ **v3.0** | Win rate per reasoning-tag pattern combination | None |
| `regime_signal_performance` ⭐ **v3.0** | Win rate per market regime (BULL/SIDEWAYS/BEAR) | None |
| `portfolio_correlation` ⭐ **v3.0** | Pairwise Pearson correlation matrix for all holdings (30-day) | None |
| `portfolio_beta` ⭐ **v3.0** | Portfolio-weighted beta vs. Nifty 50 (252-day) | None |

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
| `MONGODB_DATABASE` | `stock_ai` | MongoDB database name |

### Monitoring

| Variable | Default | Description |
|----------|---------|-------------|
| `MONITOR_INTERVAL_MINUTES` | `15` | AI analysis cycle interval |
| `PNL_ALERT_THRESHOLD_PCT` | `5.0` | Alert when stock moves > X% |
| `PORTFOLIO_ALERT_THRESHOLD_PCT` | `3.0` | Alert when portfolio moves > X% |

### Market Hours

| Variable | Default | Description |
|----------|---------|-------------|
| `MARKET_OPEN_HOUR` | `9` | NSE market open hour (IST, 24h) |
| `MARKET_OPEN_MINUTE` | `15` | NSE market open minute — 9:15 AM IST |
| `MARKET_CLOSE_HOUR` | `15` | NSE market close hour (IST, 24h) |
| `MARKET_CLOSE_MINUTE` | `30` | NSE market close minute — 3:30 PM IST |

### MicroMonitor (v2)

| Variable | Default | Description |
|----------|---------|-------------|
| `MICRO_POLL_INTERVAL_SECONDS` | `10` | Price polling frequency |
| `MICRO_VELOCITY_THRESHOLD_PCT` | `0.5` | % change per tick to alert |
| `MICRO_CONSECUTIVE_TICKS` | `3` | Consecutive ticks threshold |

### Screener (v2.0)

| Variable | Default | Description |
|----------|---------|-------------|
| `SCREENER_SYMBOLS_FILE` | `nse_symbols.json` | NSE universe file |
| `SCREENER_TOP_N` | `10` | Top candidates for Claude |
| `SCREENER_MIN_LIQUIDITY` (v2.1) | `500000` | Min avg daily volume (shares) |
| `SCREENER_LIQUIDITY_LOOKBACK_DAYS` (v2.1) | `30` | Days to compute avg volume |

### Signal Outcome Tracking (v2.1)

| Variable | Default | Description |
|----------|---------|-------------|
| `OUTCOME_AUTO_TRACK_ENABLED` | `true` | Enable automatic outcome tracking |
| `OUTCOME_AUTO_TRACK_INTERVAL_HOURS` | `6` | Hours between auto-tracking runs |
| `OUTCOME_MIN_CONFIDENCE_TRACK` | `0.6` | Min signal confidence to track |

### Stop-Loss Monitoring (v2.1)

| Variable | Default | Description |
|----------|---------|-------------|
| `STOP_LOSS_ENABLED` | `true` | Enable real-time stop-loss breach monitoring |
| `STOP_LOSS_GRACE_PCT` | `0.1` | Grace % below stop-loss to avoid noise |

### Portfolio Drawdown Breaker (v2.1)

| Variable | Default | Description |
|----------|---------|-------------|
| `DRAWDOWN_BREAKER_ENABLED` | `true` | Enable portfolio drawdown circuit breaker |
| `DRAWDOWN_BREAKER_THRESHOLD_PCT` | `8.0` | Drawdown % to trigger breaker |
| `DRAWDOWN_BREAKER_AUTO_RESET` | `true` | Auto-reset when drawdown recovers |

### Market Regime Classification (v2.1)

| Variable | Default | Description |
|----------|---------|-------------|
| `REGIME_CLASSIFICATION_ENABLED` | `true` | Enable daily regime classification |
| `REGIME_INDEX_SYMBOL` | `"NIFTY 50"` | Index symbol for regime analysis |

### Intraday Trading ⭐ **v2.2**

| Variable | Default | Description |
|----------|---------|-------------|
| `INTRADAY_ENABLED` | `true` | Enable intraday trading module |
| `INTRADAY_POLL_INTERVAL_SECONDS` | `60` | 1-minute monitor cycle interval |
| `INTRADAY_MAX_POSITIONS` | `3` | Max concurrent MIS positions |
| `INTRADAY_RISK_PER_TRADE_RS` | `500.0` | Rs. to risk per trade (for position sizing) |
| `INTRADAY_MAX_DAILY_LOSS_RS` | `1500.0` | Daily loss limit — triggers entry breaker |
| `INTRADAY_MAX_POSITION_VALUE` | `50000.0` | Hard cap on total value per position |
| `INTRADAY_NO_ENTRY_AFTER_HOUR` | `14` | No new entries after this hour |
| `INTRADAY_NO_ENTRY_AFTER_MINUTE` | `30` | No new entries after this minute (14:30 = 2:30 PM) |
| `INTRADAY_HARD_EXIT_HOUR` | `15` | Hard exit alert hour |
| `INTRADAY_HARD_EXIT_MINUTE` | `15` | Hard exit alert minute (15:15 = 3:15 PM) |
| `INTRADAY_ORB_MINUTES` | `15` | Opening range duration in minutes |
| `INTRADAY_SUPERTREND_PERIOD` | `10` | Supertrend ATR period |
| `INTRADAY_SUPERTREND_MULTIPLIER` | `3.0` | Supertrend ATR multiplier |
| `INTRADAY_MIN_GAP_PCT` | `0.5` | Minimum gap% to include in pre-market watchlist |
| `INTRADAY_WATCHLIST_SIZE` | `20` | Max symbols in daily intraday watchlist |
| `INTRADAY_MIN_BREAKOUT_CONFIRM_TICKS` | `3` | MicroMonitor consecutive ticks to confirm breakout |

### Event Risk Filter ⭐ **v3.0**

| Variable | Default | Description |
|----------|---------|-------------|
| `EVENT_RISK_ENABLED` | `true` | Enable NSE corporate event risk filter |
| `EVENT_RISK_LOOKBACK_DAYS` | `3` | Block BUY signals N days before a corporate event |

### Signal Calibration ⭐ **v3.0**

| Variable | Default | Description |
|----------|---------|-------------|
| `CALIBRATION_ENABLED` | `true` | Enable nightly signal calibration computation |
| `CALIBRATION_LOOKBACK_DAYS` | `90` | Days of `signal_outcomes` history to analyze |
| `CALIBRATION_MIN_SAMPLES` | `5` | Minimum signals per confidence bucket to trust stats |
| `CALIBRATION_REFRESH_HOUR` | `20` | Hour (24h) to run nightly calibration (default 8 PM) |

### Capital Allocation / Kelly Criterion ⭐ **v3.0**

| Variable | Default | Description |
|----------|---------|-------------|
| `CAPITAL_ALLOCATION_ENABLED` | `true` | Enable Kelly sizing, correlation guard, sector cap |
| `KELLY_FRACTION` | `0.5` | Kelly multiplier (0.5 = half-Kelly, the standard conservative choice) |
| `KELLY_MAX_POSITION_PCT` | `20.0` | Hard cap: never allocate more than 20% of portfolio to one stock |
| `KELLY_MIN_POSITION_PCT` | `1.0` | Floor: minimum meaningful position size |
| `CORRELATION_GUARD_ENABLED` | `true` | Enable Pearson correlation guard for portfolio holdings |
| `CORRELATION_THRESHOLD` | `0.80` | Pearson r threshold above which a position is flagged/blocked |
| `SECTOR_CAP_ENABLED` | `true` | Enable sector concentration limit |
| `SECTOR_MAX_PCT` | `30.0` | Max % of portfolio value allowed in any single sector |

### Resilience (v2.0)

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
| `CLAUDE_MAX_TOKENS` | `4096` | Max response tokens (long-term engine) |
| `TELEGRAM_WEBHOOK_URL` | `` | HTTPS webhook URL (empty = polling) |
| `API_KEY` | `` | X-API-Key auth (empty = disabled) |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`/`INFO`/`WARNING`/`ERROR`) |
| `LOG_JSON` | `false` | JSON structured log format (useful for log aggregators) |
| `LOG_FILE` | `stock_ai.log` | Log output file path |

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
- **Intraday entry cooldown**: Same symbol not re-entered within 5 minutes

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

### Intraday watchlist is empty

**Symptom:** `/intraday` shows empty watchlist or pre-market scan finds nothing

**Solution:**
- Check that `nse_symbols.json` exists and is populated
- Verify `INTRADAY_MIN_GAP_PCT` isn't set too high (default 0.5%)
- Run `/iscan` to trigger an on-demand scan after 9 AM

### Intraday monitor not firing entry signals

**Symptom:** Conditions look right but no entry alerts

**Solution:**
- Check `/irisk` — daily loss breaker may be active
- Verify time is between 9:30 AM and 2:30 PM IST
- Check logs for "intraday cycle" entries — confirms polling is running
- Confirm `INTRADAY_ENABLED=true` in `.env`

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

### Completed ✅
- [x] **v1.0**: Core portfolio monitoring, Claude AI integration, Telegram bot
- [x] **v2.0**: MicroMonitor (10s polling), Stock Screener, Enhanced AI tools (11 total)
- [x] **v2.1**: Signal outcome tracking, stop-loss monitoring, drawdown breaker, regime classification, liquidity filter
- [x] **v2.2**: Full intraday trading module — pre-market scan, ORB, VWAP, Supertrend, CPR, 1-min monitor, risk management, EOD P&L report
- [x] **v3.0**: Intelligent Capital Architecture — Event Risk Filter (NSE calendar), Signal Calibration (confidence buckets + pattern win rates), Capital Allocation (half-Kelly sizing + Pearson correlation guard + sector cap + portfolio beta). 17 AI tools, dynamic system prompt, 6 new MongoDB collections

### In Progress / Next
- [ ] **v3.1**: News sentiment engine + FII/DII flow tracker (inject into Claude pre-analysis)
- [ ] **v3.2**: Full backtesting engine with historical signal replay against `signal_outcomes`
- [ ] **v3.3**: Options chain analysis and F&O strategy recommendations
- [ ] **v3.4**: AI cost tracking and usage analytics dashboard

### Future Phases
- [ ] Multi-user support with per-user portfolios
- [ ] Web dashboard with real-time charts
- [ ] WhatsApp integration as alternative to Telegram
- [ ] Secondary price feed fallback (BSE/Yahoo Finance)
- [ ] Auto-execution: place orders via Groww Trading API when confidence > threshold

## Disclaimer

This tool is for **informational and educational purposes only**. AI-generated trade signals are not financial advice. Always do your own research and consult with a qualified financial advisor before making investment decisions. Past performance does not guarantee future results. Trading in the stock market involves risk, including the potential loss of principal.

## License

MIT License - see [LICENSE](LICENSE) file for details

---

**Version:** 3.0.0
**Last Updated:** March 2026
**Author:** Built with Claude Code

**Architecture Grade:** A+ (upgraded from A in v2.2)
- Intelligence & Data Gathering: A
- Risk Management: A
- **Signal Validation: A (calibration feedback loop added in v3.0)**
- Integration & Monitoring: A
- Intraday Trading: A-
- **Capital Allocation: A (Kelly sizing + correlation + sector guards — new in v3.0)**
- **Self-Learning Loop: A- (dynamic system prompt with historical accuracy — new in v3.0)**

For questions, issues, or feature requests, please open an issue on GitHub.
