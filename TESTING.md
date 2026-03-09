# Stock AI v2.1 - End-to-End Testing Guide

This guide provides comprehensive test procedures to verify all v2.1 features against acceptance criteria from the implementation plan.

## Prerequisites

Before starting tests:

1. **Environment Setup**
   - MongoDB running and accessible
   - `.env` file configured with all required credentials
   - Application started: `uvicorn main:app --host 0.0.0.0 --port 8000`
   - Telegram bot connected and responsive

2. **Initial State**
   - At least 1-2 active holdings in Groww account
   - Clean MongoDB collections (or known baseline state)
   - Market hours (Mon-Fri 9:15 AM - 3:30 PM IST) for live testing

3. **Verification Tools**
   - MongoDB Compass or `mongosh` for database inspection
   - Telegram app for receiving alerts
   - Application logs: `tail -f stock_ai.log`

---

## Feature 1: Signal Outcome Tracker

### Test 1.1: Automatic Outcome Record Creation

**Objective:** Verify that new signals automatically create outcome records

**Steps:**
1. Trigger AI analysis (wait for 15-min cycle or use `/analyze RELIANCE`)
2. Wait for AI to generate at least 1 BUY/SELL signal
3. Check MongoDB `trade_signals` collection for new signal
4. Check MongoDB `signal_outcomes` collection for matching outcome record

**Expected Results:**
```javascript
// signal_outcomes document should exist with:
{
  signal_id: ObjectId("..."),  // matches trade_signals._id
  trading_symbol: "RELIANCE",
  action: "BUY",
  signal_timestamp: ISODate("..."),
  entry_price: 2450.50,
  entry_method: "AUTO_TRACKED",
  status: "OPEN",
  original_confidence: 0.85,
  exit_price: null,
  pnl_pct: null,
  win_loss: null
}
```

**Acceptance Criteria:**
- [ ] Outcome record created within 10 seconds of signal generation
- [ ] signal_id correctly references trade_signals._id
- [ ] entry_price populated from current market price
- [ ] status = "OPEN"
- [ ] original_confidence matches signal confidence

---

### Test 1.2: Auto-Detection of Position Exits

**Objective:** Verify auto-tracking job detects when positions are closed

**Steps:**
1. Ensure you have an open outcome record (from Test 1.1)
2. Close the position in your Groww account (sell the stock)
3. Wait for outcome tracking job to run (every 6 hours by default)
   - OR trigger manually: run `outcome_tracking_job()` from Python shell
4. Check `signal_outcomes` collection for updated record

**Expected Results:**
```javascript
{
  status: "CLOSED",
  exit_price: 2520.00,  // Current market price at detection
  exit_timestamp: ISODate("..."),
  exit_reason: "POSITION_EXITED",
  pnl_points: 69.50,  // exit_price - entry_price
  pnl_pct: 2.84,      // (pnl_points / entry_price) * 100
  win_loss: "WIN"     // "WIN" if pnl_pct > 0.5%, "LOSS" if < -0.5%
}
```

**Acceptance Criteria:**
- [ ] Status changed from "OPEN" to "CLOSED"
- [ ] exit_price populated with current market price
- [ ] pnl_points calculated correctly (considers BUY vs SELL action)
- [ ] pnl_pct calculated correctly
- [ ] win_loss classified correctly (WIN/LOSS/BREAKEVEN)
- [ ] Telegram notification sent if result["closed"] > 0

---

### Test 1.3: Signal Performance Statistics

**Objective:** Verify win rate and performance metrics calculation

**Steps:**
1. Ensure you have at least 5-10 closed outcomes (mix of wins and losses)
2. Use Telegram command: `/signal_stats`
   - OR call REST API: `GET /api/v1/signals/performance?days=30`
   - OR use Claude tool: Ask "What's my AI signal win rate?"
3. Verify statistics returned

**Expected Results:**
```json
{
  "period_days": 30,
  "total_signals": 15,
  "closed_signals": 10,
  "open_signals": 5,
  "wins": 6,
  "losses": 3,
  "breakeven": 1,
  "win_rate": 60.0,
  "avg_pnl_pct": 1.85,
  "max_win_pct": 5.2,
  "max_loss_pct": -2.8,
  "confidence_correlation": 0.42
}
```

**Acceptance Criteria:**
- [ ] win_rate = (wins / closed_signals) * 100
- [ ] avg_pnl_pct is average of all pnl_pct for closed signals
- [ ] max_win_pct and max_loss_pct correctly identified
- [ ] confidence_correlation shows if higher confidence → better results
- [ ] Claude can call `get_signal_performance` tool successfully

---

## Feature 2: Stop-Loss Monitoring

### Test 2.1: Stop-Loss Loading on Startup

**Objective:** Verify MicroMonitor loads active stop-losses into memory

**Steps:**
1. Create a test signal with stop-loss:
   ```python
   await db.trade_signals.insert_one({
       "trading_symbol": "RELIANCE",
       "action": "BUY",
       "confidence": 0.85,
       "stop_loss": 2450.0,
       "status": "ACTIVE",
       "timestamp": datetime.now()
   })
   ```
2. Restart MicroMonitor or trigger reload:
   ```python
   from src.services.micro_monitor import micro_monitor
   await micro_monitor.load_active_stop_losses()
   ```
3. Check logs: `grep "Loading active stop-losses" stock_ai.log`

**Expected Results:**
```
Loading active stop-losses into MicroMonitor memory
Loaded 1 stop-loss(es) for 1 symbol(s)
```

**Acceptance Criteria:**
- [ ] All signals with status "ACTIVE" and stop_loss != null loaded
- [ ] Stop-losses organized by trading_symbol
- [ ] Logs confirm count of loaded stop-losses

---

### Test 2.2: Real-Time Breach Detection

**Objective:** Verify stop-loss breach detected within 10 seconds

**Steps:**
1. Create a signal with stop_loss close to current price:
   - Current RELIANCE price: 2460.0
   - Set stop_loss: 2458.0 (BUY signal)
2. Wait for MicroMonitor 10-second poll cycle
3. Simulate price drop below stop-loss (or wait for actual price movement)
4. Check for CRITICAL Telegram alert
5. Verify signal status updated in database

**Expected Results:**
- **Telegram Alert:**
  ```
  🚨 STOP-LOSS HIT 🚨

  Symbol: RELIANCE
  Action: BUY
  Stop-Loss: ₹2,458.00
  Current Price: ₹2,445.00
  Breach: -0.53%

  Immediate action recommended.
  ```

- **Database Update:**
  ```javascript
  {
    status: "TRIGGERED",
    trigger_timestamp: ISODate("..."),
    trigger_price: 2445.00
  }
  ```

**Acceptance Criteria:**
- [ ] Breach detected within 10 seconds of price crossing stop-loss
- [ ] CRITICAL Telegram alert sent immediately
- [ ] Alert includes symbol, stop-loss price, current price, breach %
- [ ] Signal status updated to "TRIGGERED" in database
- [ ] No duplicate alerts on subsequent ticks (cooldown works)

---

### Test 2.3: Grace Threshold

**Objective:** Verify grace threshold prevents false positives

**Steps:**
1. Create signal with stop_loss: 2450.0
2. Set `STOP_LOSS_GRACE_PCT=0.1` in .env (0.1%)
3. Effective threshold: 2450.0 * (1 - 0.001) = 2447.55
4. Simulate price at 2449.0 (below stop-loss but within grace)
5. Verify NO alert sent

**Expected Results:**
- No Telegram alert
- Signal status remains "ACTIVE"
- Logs show: "Price 2449.0 within grace threshold (2447.55)"

**Acceptance Criteria:**
- [ ] Breach only triggered when price < (stop_loss * (1 - grace_pct))
- [ ] Grace threshold configurable via STOP_LOSS_GRACE_PCT
- [ ] No false positives from minor price fluctuations

---

### Test 2.4: Hourly Reload

**Objective:** Verify stop-losses reloaded hourly during market hours

**Steps:**
1. Note current loaded stop-losses count
2. Add new signal with stop-loss while MicroMonitor running
3. Wait for hourly reload job (top of the hour during market hours)
4. Check logs for reload confirmation
5. Verify new stop-loss now monitored

**Expected Results:**
```
[reload_stop_losses_job] Reloading active stop-losses
Loaded 2 stop-loss(es) for 2 symbol(s)
```

**Acceptance Criteria:**
- [ ] Reload job runs every hour during market hours (9 AM - 3 PM IST)
- [ ] New signals picked up without restart
- [ ] Triggered signals removed from monitoring

---

## Feature 3: Portfolio Drawdown Breaker

### Test 3.1: Peak Tracking

**Objective:** Verify portfolio peak updated correctly

**Steps:**
1. Check current portfolio value: `/status`
2. Record current peak:
   ```javascript
   db.portfolio_peaks.findOne({is_current_peak: true})
   ```
3. Simulate portfolio increase (add holdings or wait for price increase)
4. Wait for next monitoring cycle (15 min)
5. Verify peak updated

**Expected Results:**
```javascript
// Old peak
{
  portfolio_value: 1000000.0,
  is_current_peak: false  // Changed to false
}

// New peak
{
  timestamp: ISODate("..."),
  portfolio_value: 1050000.0,
  total_invested: 950000.0,
  is_current_peak: true
}
```

**Acceptance Criteria:**
- [ ] Peak updated when current_value > stored peak
- [ ] Old peak's is_current_peak set to false
- [ ] New peak document inserted with is_current_peak: true
- [ ] Logs show: "New portfolio peak: ₹1,050,000 (was ₹1,000,000)"

---

### Test 3.2: Drawdown Calculation & Trigger

**Objective:** Verify breaker triggers at 8% drawdown threshold

**Steps:**
1. Set portfolio peak: 1,000,000 INR
2. Simulate portfolio drop to 915,000 INR (8.5% drawdown)
   - Can be simulated by manually updating holdings prices in MongoDB
   - OR wait for actual market movement
3. Wait for next monitoring cycle
4. Verify CRITICAL Telegram alert
5. Check circuit_breaker_state collection

**Expected Results:**
- **Telegram Alert:**
  ```
  🚨 CIRCUIT BREAKER TRIGGERED 🚨

  Portfolio drawdown exceeded 8.0% threshold.

  Peak Value: ₹10,00,000
  Current Value: ₹9,15,000
  Drawdown: 8.5%

  ALL BUY SIGNALS ARE NOW BLOCKED.
  Focus on capital preservation and risk reduction.

  Use /reset_breaker to manually override (not recommended).
  ```

- **Database:**
  ```javascript
  {
    _id: "drawdown_breaker",
    triggered: true,
    trigger_timestamp: ISODate("..."),
    trigger_drawdown_pct: 8.5,
    peak_value_at_trigger: 1000000.0,
    trigger_portfolio_value: 915000.0
  }
  ```

**Acceptance Criteria:**
- [ ] Drawdown calculated: ((peak - current) / peak) * 100
- [ ] Breaker triggers when drawdown >= threshold (8.0%)
- [ ] CRITICAL Telegram alert sent immediately
- [ ] circuit_breaker_state.triggered = true
- [ ] Logs show: "DRAWDOWN BREAKER TRIGGERED: 8.5% drawdown"

---

### Test 3.3: BUY Signal Blocking

**Objective:** Verify all BUY signals blocked when breaker active

**Steps:**
1. Ensure drawdown breaker triggered (from Test 3.2)
2. Trigger AI analysis
3. Verify BUY signals not sent to Telegram
4. Check logs for blocked signals

**Expected Results:**
```
AI generated BUY signal for RELIANCE (confidence: 0.85)
Drawdown breaker BLOCKED BUY signal for RELIANCE
```

**Acceptance Criteria:**
- [ ] BUY and STRONG_BUY signals filtered out
- [ ] SELL, STRONG_SELL, HOLD signals allowed
- [ ] Claude's prompt includes drawdown warning:
  ```
  CRITICAL: DRAWDOWN BREAKER IS ACTIVE
  DO NOT generate any BUY or STRONG_BUY signals.
  Focus ONLY on risk reduction.
  ```
- [ ] User notified why BUY signals blocked

---

### Test 3.4: Auto-Reset

**Objective:** Verify breaker resets when portfolio recovers

**Steps:**
1. Start with breaker triggered at 8.5% drawdown
2. Simulate portfolio recovery to 960,000 INR (4% drawdown)
3. Threshold * 0.5 = 8% * 0.5 = 4% (recovery threshold)
4. Wait for next monitoring cycle
5. Verify breaker reset

**Expected Results:**
```
Drawdown recovered to 4.0% (below reset threshold 4.0%)
Circuit breaker auto-reset
```

**Database:**
```javascript
{
  _id: "drawdown_breaker",
  triggered: false,
  reset_timestamp: ISODate("..."),
  last_trigger_timestamp: ISODate("..."),
  last_trigger_drawdown_pct: 8.5
}
```

**Acceptance Criteria:**
- [ ] Auto-reset when drawdown < (threshold * 0.5)
- [ ] circuit_breaker_state.triggered = false
- [ ] Last trigger info preserved for history
- [ ] BUY signals allowed again after reset
- [ ] Only works if DRAWDOWN_BREAKER_AUTO_RESET=true

---

### Test 3.5: Manual Reset

**Objective:** Verify manual reset via Telegram command

**Steps:**
1. Ensure breaker triggered
2. Send Telegram command: `/reset_breaker`
3. Verify confirmation message
4. Check database state

**Expected Results:**
```
Circuit Breaker Reset

Previous drawdown: 8.5%
Previous trigger: 2026-03-09 14:30:00 IST

The circuit breaker has been manually reset.
BUY signals are now allowed.

Use with caution - consider current market conditions.
```

**Acceptance Criteria:**
- [ ] `/reset_breaker` command works
- [ ] Confirmation message shows previous trigger details
- [ ] circuit_breaker_state.triggered = false
- [ ] Warning about using with caution displayed

---

## Feature 4: Market Regime Classifier

### Test 4.1: Daily Classification Job

**Objective:** Verify regime classification runs at 9:20 AM IST

**Steps:**
1. Set system time to 9:19 AM IST on a weekday
2. Wait for 9:20 AM
3. Check logs for classification job execution
4. Verify Telegram notification received

**Expected Results:**
```
[daily_regime_classification_job] Running daily market regime classification
Fetching NIFTY 50 data for regime classification
Regime classified: BULL_WEAK (score: 45.0, confidence: 0.72)
```

**Telegram Notification:**
```
📊 Market Regime Classified

Regime: BULL_WEAK
Score: 45.0/100
Nifty 50: ₹22,450.00
RSI(14): 58.5
Volatility: 1.8%
```

**Acceptance Criteria:**
- [ ] Job runs Mon-Fri at 9:20 AM IST
- [ ] Skipped on NSE holidays
- [ ] Nifty 50 data fetched (90 days)
- [ ] Indicators computed: SMA20, SMA50, SMA200, RSI14, volatility
- [ ] Regime score calculated (-100 to +100)
- [ ] Telegram notification sent with regime details

---

### Test 4.2: Regime Scoring Logic

**Objective:** Verify regime score calculation is correct

**Steps:**
1. Manually trigger classification or inspect latest result
2. Verify score calculation:
   ```python
   from src.services.regime_classifier import regime_classifier
   result = await regime_classifier.classify_daily_regime()
   ```
3. Check indicators vs score

**Test Cases:**

| Scenario | Price | SMA20 | SMA50 | SMA200 | RSI | Vol | Expected Score | Expected Regime |
|----------|-------|-------|-------|--------|-----|-----|----------------|-----------------|
| Strong Bull | 22500 | 22200 | 21800 | 21000 | 65 | 0.8 | +85 | BULL_STRONG |
| Weak Bull | 22200 | 22000 | 21900 | 21800 | 55 | 1.5 | +35 | BULL_WEAK |
| Sideways | 22000 | 22050 | 22000 | 21900 | 50 | 1.2 | 0 | SIDEWAYS |
| Weak Bear | 21500 | 21800 | 22000 | 22200 | 42 | 2.0 | -35 | BEAR_WEAK |
| Strong Bear | 21000 | 21500 | 22000 | 22500 | 32 | 3.5 | -85 | BEAR_STRONG |

**Acceptance Criteria:**
- [ ] Score clamped to -100 to +100 range
- [ ] Price vs SMAs: +40 pts max (15+15+10)
- [ ] SMA alignment: ±20 pts
- [ ] RSI momentum: ±15 pts
- [ ] Volatility penalty: -20 pts max

---

### Test 4.3: Regime-Based Threshold Adjustment

**Objective:** Verify signal confidence thresholds adjusted by regime

**Steps:**
1. Set regime to BEAR_WEAK (min_confidence: 0.80)
2. Generate AI signal with confidence: 0.75
3. Verify signal filtered out (below threshold)
4. Generate signal with confidence: 0.82
5. Verify signal passes

**Expected Results:**
```
Current regime: BEAR_WEAK
Minimum confidence threshold: 0.80

Signal: BUY RELIANCE (confidence: 0.75)
→ FILTERED: Below regime threshold (0.75 < 0.80)

Signal: BUY TCS (confidence: 0.82)
→ ACCEPTED: Meets regime threshold (0.82 >= 0.80)
```

**Acceptance Criteria:**
- [ ] BULL_STRONG: min_confidence = 0.65
- [ ] BULL_WEAK: min_confidence = 0.70
- [ ] SIDEWAYS: min_confidence = 0.75
- [ ] BEAR_WEAK: min_confidence = 0.80
- [ ] BEAR_STRONG: min_confidence = 0.85
- [ ] Signals below threshold not sent to Telegram
- [ ] Claude's prompt includes regime context

---

### Test 4.4: Regime Context in AI Prompt

**Objective:** Verify Claude receives regime context in system prompt

**Steps:**
1. Set regime to BEAR_STRONG
2. Trigger AI analysis
3. Check Claude's system prompt includes:
   ```
   MARKET REGIME: BEAR_STRONG (score: -75/100)
   Minimum confidence threshold for signals: 85.0%
   Current market conditions require defensive positioning.
   ```
4. Verify Claude's signals reflect regime awareness

**Expected Results:**
- Claude avoids aggressive BUY recommendations in BEAR regime
- Higher confidence scores in bear markets
- More SELL/HOLD recommendations

**Acceptance Criteria:**
- [ ] Regime info injected into every AI analysis
- [ ] Min confidence threshold communicated
- [ ] Suggested exposure % included
- [ ] Claude's behavior adapts to regime

---

## Feature 5: Minimum Liquidity Filter

### Test 5.1: Universe Filtering

**Objective:** Verify illiquid stocks filtered before technical screening

**Steps:**
1. Create test universe with mix of liquid and illiquid stocks:
   ```json
   [
     {"symbol": "RELIANCE", "avg_volume": 5000000},  // Liquid
     {"symbol": "SMALLCAP", "avg_volume": 100000}    // Illiquid
   ]
   ```
2. Set `SCREENER_MIN_LIQUIDITY=500000`
3. Run screener: `/screen`
4. Check logs for filtering

**Expected Results:**
```
Screener starting with 500 symbols
Applying liquidity filter (min: 500,000 shares)
SMALLCAP: avg volume 100,000 - filtered out
RELIANCE: avg volume 5,000,000 - passed
Screener: 450 symbols after liquidity filter
```

**Acceptance Criteria:**
- [ ] Volume data fetched for all symbols (30-day lookback)
- [ ] Average daily volume calculated correctly
- [ ] Stocks with ADV < threshold filtered out
- [ ] Remaining stocks pass to technical screening
- [ ] Logs show count of filtered symbols

---

### Test 5.2: Volume Calculation Accuracy

**Objective:** Verify average daily volume calculation

**Steps:**
1. Pick test symbol (e.g., "RELIANCE")
2. Fetch 30 days of daily candles
3. Calculate ADV manually:
   ```python
   volumes = [c.volume for c in candles]
   avg_volume = sum(volumes) / len(volumes)
   ```
4. Compare with screener's calculation

**Expected Results:**
```python
# Example candles (simplified)
Day 1: volume = 4,800,000
Day 2: volume = 5,200,000
Day 3: volume = 4,900,000
...
Day 30: volume = 5,100,000

Average = sum(all volumes) / 30 = 5,000,000
```

**Acceptance Criteria:**
- [ ] Uses 30-day lookback (configurable via SCREENER_LIQUIDITY_LOOKBACK_DAYS)
- [ ] Handles missing data gracefully
- [ ] Calculation matches manual verification
- [ ] Zero-volume days excluded or handled properly

---

### Test 5.3: Performance & Rate Limiting

**Objective:** Verify screener respects API rate limits during liquidity filter

**Steps:**
1. Run screener with large universe (500+ symbols)
2. Monitor API call frequency
3. Check for rate limit errors

**Expected Results:**
```
Fetching volume data for 500 symbols
Rate limit: 1 request per second
Estimated time: ~8 minutes
[Progress: 50/500 symbols processed]
```

**Acceptance Criteria:**
- [ ] 1-second delay between symbols
- [ ] No "429 Too Many Requests" errors
- [ ] Progress logged periodically
- [ ] Screener completes without errors

---

### Test 5.4: Filter Bypass

**Objective:** Verify filter can be disabled

**Steps:**
1. Set `SCREENER_MIN_LIQUIDITY=0` in .env
2. Run screener
3. Verify no liquidity filtering

**Expected Results:**
```
Screener minimum liquidity: 0 (disabled)
Skipping liquidity filter
Proceeding with technical screening on all 500 symbols
```

**Acceptance Criteria:**
- [ ] Setting to 0 disables filter
- [ ] All symbols pass to technical screening
- [ ] No volume data fetched (performance optimization)

---

## Feature 6: MongoDB Indexing & TTL

### Test 6.1: Index Verification

**Objective:** Verify all new indexes created successfully

**Steps:**
1. Start application (triggers database setup)
2. Connect to MongoDB
3. Check indexes for each collection:
   ```javascript
   db.signal_outcomes.getIndexes()
   db.portfolio_peaks.getIndexes()
   db.circuit_breaker_state.getIndexes()
   db.market_regime.getIndexes()
   db.trade_signals.getIndexes()
   ```

**Expected Results:**
```javascript
// signal_outcomes
[
  {key: {_id: 1}},
  {key: {trading_symbol: 1, signal_timestamp: -1}},
  {key: {status: 1}},
  {key: {win_loss: 1}},
  {key: {timestamp: 1}, expireAfterSeconds: 31536000}  // 365 days
]

// portfolio_peaks
[
  {key: {_id: 1}},
  {key: {timestamp: -1}},
  {key: {is_current_peak: 1}},
  {key: {timestamp: 1}, expireAfterSeconds: 7776000}  // 90 days
]

// market_regime
[
  {key: {_id: 1}},
  {key: {date: -1}, unique: true},
  {key: {is_current: 1}},
  {key: {timestamp: 1}, expireAfterSeconds: 31536000}  // 365 days
]

// trade_signals (TTL updated)
[
  ...,
  {key: {timestamp: 1}, expireAfterSeconds: 7776000}  // 90 days (was 30)
]
```

**Acceptance Criteria:**
- [ ] All compound indexes created
- [ ] TTL indexes have correct expireAfterSeconds
- [ ] Unique indexes where specified
- [ ] No duplicate or conflicting indexes
- [ ] Index creation completes without errors

---

### Test 6.2: TTL Expiration

**Objective:** Verify documents expire after TTL period

**Steps:**
1. Insert test document with old timestamp:
   ```javascript
   db.signal_outcomes.insertOne({
     trading_symbol: "TEST",
     timestamp: new Date(Date.now() - 366 * 24 * 60 * 60 * 1000)  // 366 days ago
   })
   ```
2. Wait for MongoDB's TTL background thread (runs every 60 seconds)
3. Check if document deleted

**Expected Results:**
Document automatically deleted after ~60 seconds

**Acceptance Criteria:**
- [ ] Documents older than TTL deleted automatically
- [ ] Recent documents preserved
- [ ] TTL thread runs without errors

---

### Test 6.3: Query Performance

**Objective:** Verify indexes improve query performance

**Steps:**
1. Insert 10,000 test signal outcome records
2. Run query with explain:
   ```javascript
   db.signal_outcomes.find({
     trading_symbol: "RELIANCE",
     signal_timestamp: {$gte: ISODate("2026-01-01")}
   }).explain("executionStats")
   ```
3. Verify index used

**Expected Results:**
```javascript
{
  executionStats: {
    executionTimeMillis: 15,  // Should be < 100ms
    totalKeysExamined: 50,
    totalDocsExamined: 50,
    executionStages: {
      stage: "IXSCAN",  // Index scan (not COLLSCAN)
      indexName: "trading_symbol_1_signal_timestamp_-1"
    }
  }
}
```

**Acceptance Criteria:**
- [ ] Query uses index (IXSCAN, not COLLSCAN)
- [ ] Execution time < 100ms for common queries
- [ ] totalDocsExamined ≈ totalKeysExamined (efficient index)

---

## Integration Tests

### Integration Test 1: Full Monitoring Cycle

**Objective:** Verify all v2.1 features work together in monitoring cycle

**Steps:**
1. Ensure all features enabled in .env
2. Wait for 15-minute monitoring cycle
3. Monitor logs for:
   - Portfolio snapshot created
   - Drawdown check performed
   - Regime loaded
   - AI analysis with regime context
   - Signal filtering (regime + drawdown)
   - Outcome tracking for new signals

**Expected Log Flow:**
```
[monitoring_job] Starting portfolio monitoring cycle
[portfolio_monitor] Fetching holdings from Groww
[portfolio_monitor] Enriching with live prices
[drawdown_breaker] Current drawdown: 2.3% (breaker: inactive)
[regime_classifier] Current regime: BULL_WEAK (min_conf: 0.70)
[ai_engine] Running AI analysis with regime context
[ai_engine] Generated 2 signals: BUY RELIANCE (0.85), SELL INFY (0.68)
[portfolio_monitor] Filtering signals by regime threshold
[portfolio_monitor] SELL INFY filtered: 0.68 < 0.70
[outcome_tracker] Tracking outcome for BUY RELIANCE signal
[telegram] Alert sent: BUY RELIANCE (₹2,450 → ₹2,550)
```

**Acceptance Criteria:**
- [ ] All v2.1 components execute in correct order
- [ ] Drawdown check before AI analysis
- [ ] Regime context passed to AI
- [ ] Signal filtering applies both regime + drawdown rules
- [ ] Outcome tracking for all generated signals
- [ ] No errors or exceptions

---

### Integration Test 2: Stop-Loss + Outcome Tracking

**Objective:** Verify stop-loss breach triggers outcome closure

**Steps:**
1. Create BUY signal with stop-loss
2. Outcome record created (entry_price = 2450)
3. Price drops below stop-loss (2440)
4. Stop-loss alert sent
5. Signal status = TRIGGERED
6. Later: outcome tracking detects position exited
7. Outcome updated with exit info

**Expected Flow:**
```
T=0:  Signal created (BUY RELIANCE, SL=2450)
T=0:  Outcome created (status=OPEN, entry_price=2450)
T=10s: Stop-loss breach detected (price=2440)
T=10s: CRITICAL alert sent
T=10s: Signal status → TRIGGERED
T=6h: Outcome tracking job runs
T=6h: Position not in holdings
T=6h: Outcome updated (status=CLOSED, exit_price=2440, win_loss=LOSS)
```

**Acceptance Criteria:**
- [ ] Stop-loss breach detected first
- [ ] Outcome remains OPEN during breach alert
- [ ] Auto-tracking later detects position exit
- [ ] Outcome closed with exit details
- [ ] Win/loss reflects stop-loss hit (LOSS)

---

### Integration Test 3: Regime Change Impact

**Objective:** Verify regime change affects signal generation

**Steps:**
1. Day 1: Regime = BULL_STRONG (min_conf: 0.65)
   - Generate signal with confidence 0.68
   - Verify signal accepted
2. Day 2: Regime = BEAR_WEAK (min_conf: 0.80)
   - Generate signal with confidence 0.68
   - Verify signal rejected
   - Generate signal with confidence 0.85
   - Verify signal accepted

**Expected Results:**
```
Day 1 (BULL_STRONG):
✓ BUY RELIANCE (0.68) → ACCEPTED (0.68 >= 0.65)

Day 2 (BEAR_WEAK):
✗ BUY TCS (0.68) → REJECTED (0.68 < 0.80)
✓ SELL INFY (0.85) → ACCEPTED (0.85 >= 0.80)
```

**Acceptance Criteria:**
- [ ] Regime changes reflected in next analysis
- [ ] Threshold adjustment immediate
- [ ] Lower-confidence signals filtered in bear market
- [ ] Higher-confidence signals required in bear market

---

## Troubleshooting Guide

### Issue: Outcome records not created

**Symptoms:** No signal_outcomes documents after signal generation

**Debug Steps:**
1. Check if outcome_tracker imported:
   ```python
   from src.services.outcome_tracker import outcome_tracker
   ```
2. Verify `track_new_signal()` called in portfolio_monitor.py
3. Check MongoDB connection
4. Look for errors in logs: `grep "outcome_tracker" stock_ai.log`

**Common Fixes:**
- Ensure OUTCOME_AUTO_TRACK_ENABLED=true
- Check MongoDB write permissions
- Verify signal has required fields (trading_symbol, action, confidence)

---

### Issue: Stop-loss alerts not sent

**Symptoms:** Price crosses stop-loss but no CRITICAL alert

**Debug Steps:**
1. Verify MicroMonitor running: `grep "MicroMonitor" stock_ai.log`
2. Check stop-losses loaded: `micro_monitor._active_stop_losses`
3. Verify signal status = ACTIVE (not TRIGGERED)
4. Check STOP_LOSS_ENABLED=true

**Common Fixes:**
- Restart MicroMonitor to reload stop-losses
- Verify stop_loss field not null in signal
- Check Telegram bot connection
- Review grace threshold calculation

---

### Issue: Drawdown breaker not triggering

**Symptoms:** Portfolio down 10% but no circuit breaker

**Debug Steps:**
1. Check portfolio peak exists:
   ```javascript
   db.portfolio_peaks.findOne({is_current_peak: true})
   ```
2. Verify DRAWDOWN_BREAKER_ENABLED=true
3. Check drawdown calculation in logs
4. Verify monitoring cycle running

**Common Fixes:**
- Initialize peak manually if missing
- Check portfolio value calculation (current_value != 0)
- Verify threshold setting (default: 8.0%)

---

### Issue: Regime not affecting signals

**Symptoms:** Signals generated ignoring regime thresholds

**Debug Steps:**
1. Check regime document exists:
   ```javascript
   db.market_regime.findOne({is_current: true})
   ```
2. Verify regime loaded in portfolio_monitor.py
3. Check signal filtering logic
4. Review AI prompt includes regime context

**Common Fixes:**
- Run regime classification manually first
- Verify REGIME_CLASSIFICATION_ENABLED=true
- Check regime_classifier import
- Ensure get_current_regime() called before AI analysis

---

## Summary Checklist

### Feature 1: Signal Outcome Tracker ✓
- [ ] Outcome records created for all signals
- [ ] Auto-tracking detects position exits
- [ ] P&L calculated correctly (BUY vs SELL)
- [ ] Win/loss classification accurate
- [ ] Performance statistics available via /signal_stats
- [ ] Claude can use get_signal_performance tool
- [ ] 365-day TTL working

### Feature 2: Stop-Loss Monitoring ✓
- [ ] Active stop-losses loaded on startup
- [ ] Breaches detected within 10 seconds
- [ ] CRITICAL alerts sent to Telegram
- [ ] Signal status updated to TRIGGERED
- [ ] No duplicate alerts (cooldown works)
- [ ] Grace threshold prevents false positives
- [ ] Hourly reload picks up new signals

### Feature 3: Portfolio Drawdown Breaker ✓
- [ ] Portfolio peak tracked correctly
- [ ] Drawdown calculated: (peak - current) / peak × 100
- [ ] Breaker triggers at threshold (8%)
- [ ] CRITICAL alert sent on trigger
- [ ] All BUY signals blocked when active
- [ ] Auto-reset works (50% recovery)
- [ ] Manual reset via /reset_breaker
- [ ] AI prompt includes drawdown warning

### Feature 4: Market Regime Classifier ✓
- [ ] Daily job runs at 9:20 AM IST
- [ ] Nifty 50 data fetched (90 days)
- [ ] Indicators computed correctly
- [ ] Regime score -100 to +100
- [ ] 5 regimes classified correctly
- [ ] Confidence thresholds adjusted by regime
- [ ] Telegram notification sent
- [ ] AI prompt includes regime context

### Feature 5: Minimum Liquidity Filter ✓
- [ ] Universe filtered before screening
- [ ] 30-day average volume calculated
- [ ] Stocks < 500k ADV filtered out
- [ ] Logs show filtered count
- [ ] Can be disabled (min_liquidity=0)
- [ ] API rate limits respected (1s delay)

### Feature 6: MongoDB Indexing ✓
- [ ] All new indexes created
- [ ] TTL policies set correctly
- [ ] trade_signals TTL increased to 90 days
- [ ] Query performance < 100ms
- [ ] Index usage verified with explain()
- [ ] TTL expiration working

---

## Next Steps

After completing all tests:

1. **Document Results**
   - Create test report with pass/fail status
   - Note any deviations from expected behavior
   - Log performance metrics

2. **Production Readiness**
   - Review all error logs
   - Verify no memory leaks during extended run
   - Test with actual market data for 1-2 days

3. **User Training**
   - Document Telegram commands
   - Create user guide for interpreting alerts
   - Set up monitoring dashboards

4. **v2.2 Planning**
   - Implement missing Telegram commands
   - Add web dashboard
   - Consider additional features

---

**Testing Completion Date:** _____________

**Tester:** _____________

**Overall Status:** ☐ PASSED  ☐ FAILED  ☐ NEEDS REVISION

**Notes:**
_____________________________________________________________
_____________________________________________________________
_____________________________________________________________
