"""Intraday Scanner — pre-market gap/CPR scan and end-of-day report.

Runs at 8:55 AM to identify today's intraday candidates:
  1. Fetches today's open vs yesterday's close to compute gap%.
  2. Computes Central Pivot Range from yesterday's H/L/C.
  3. Ranks candidates by gap magnitude + volume.
  4. Sends a morning setup Telegram report.

Also generates the end-of-day intraday P&L summary at 3:35 PM.
"""

import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from src.models.intraday import IntradayDailyReport, IntradaySetup
from src.services.database import db
from src.services.groww_service import groww_service
from src.utils.intraday_indicators import compute_cpr
from src.utils.market_hours import now_ist

logger = logging.getLogger(__name__)


class IntradayScanner:
    """Pre-market scanner and daily report generator."""

    def __init__(self) -> None:
        self._nse_symbols: list[str] = []

    # ----------------------------------------------------------------
    # Pre-market scan
    # ----------------------------------------------------------------

    async def run_premarket_scan(self) -> list[IntradaySetup]:
        """Scan for intraday candidates based on gap and CPR.

        Returns:
            List of IntradaySetup ranked by score (best first).
        """
        from src.config import settings

        symbols = await self._load_symbols()
        if not symbols:
            logger.warning("No symbols loaded for pre-market scan")
            return []

        logger.info(f"Pre-market scan starting for {len(symbols)} symbols")

        # Fetch today's OHLC (open reflects today's open price after pre-open)
        try:
            today_ohlc = await groww_service.get_bulk_ohlc(symbols)
        except Exception as e:
            logger.error(f"Pre-market scan: bulk OHLC failed: {e}")
            return []

        # Fetch yesterday's candles for CPR (daily candles, 2 days back)
        prev_candles: dict[str, dict] = {}
        for sym in symbols:
            try:
                end_dt = now_ist()
                start_dt = end_dt - timedelta(days=5)  # 5 days back to skip weekends
                candles = await groww_service.get_historical_candles(
                    trading_symbol=sym,
                    exchange="NSE",
                    segment="CASH",
                    start_time=start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    end_time=end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    interval_minutes=1440,
                )
                if candles and len(candles) >= 2:
                    # Use second-to-last candle as "yesterday" (last may be today)
                    yesterday = candles[-2]
                    prev_candles[sym] = {
                        "high": yesterday.high,
                        "low": yesterday.low,
                        "close": yesterday.close,
                    }
            except Exception as e:
                logger.debug(f"Pre-market scan: candle fetch failed for {sym}: {e}")

        setups: list[IntradaySetup] = []
        today = now_ist().date()

        for sym in symbols:
            try:
                ohlc = groww_service.find_ohlc(today_ohlc, sym)
                if not ohlc:
                    continue

                today_open = float(ohlc.get("open", 0) or 0)
                prev = prev_candles.get(sym)
                if not today_open or not prev:
                    continue

                prev_close = float(prev["close"])
                if prev_close <= 0:
                    continue

                gap_pct = (today_open - prev_close) / prev_close * 100
                gap_type = (
                    "GAP_UP" if gap_pct >= settings.intraday_min_gap_pct
                    else "GAP_DOWN" if gap_pct <= -settings.intraday_min_gap_pct
                    else "FLAT"
                )

                cpr = compute_cpr(
                    prev_high=float(prev["high"]),
                    prev_low=float(prev["low"]),
                    prev_close=prev_close,
                )

                # Rank score: |gap%| weighted (50%) + CPR width penalty (50%)
                # Narrow CPR (< 0.3%) → trending day → higher score
                gap_score = min(abs(gap_pct) * 10, 50)  # cap at 50
                cpr_score = max(0, 50 - cpr["cpr_width_pct"] * 50)
                rank_score = gap_score + cpr_score

                reason_parts = []
                if abs(gap_pct) >= settings.intraday_min_gap_pct:
                    reason_parts.append(f"GAP_{'UP' if gap_pct > 0 else 'DOWN'}_{abs(gap_pct):.1f}%")
                if cpr["cpr_width_pct"] < 0.3:
                    reason_parts.append("NARROW_CPR")

                setup = IntradaySetup(
                    symbol=sym,
                    scan_date=today,
                    gap_pct=round(gap_pct, 3),
                    gap_type=gap_type,
                    prev_close=round(prev_close, 2),
                    today_open=round(today_open, 2),
                    cpr_pivot=cpr["pivot"],
                    cpr_bc=cpr["bc"],
                    cpr_tc=cpr["tc"],
                    cpr_r1=cpr["r1"],
                    cpr_r2=cpr["r2"],
                    cpr_s1=cpr["s1"],
                    cpr_s2=cpr["s2"],
                    rank_score=round(rank_score, 2),
                    watchlist_reason=", ".join(reason_parts) if reason_parts else "FLAT",
                )
                setups.append(setup)

            except Exception as e:
                logger.debug(f"Pre-market scan: setup failed for {sym}: {e}")

        # Sort by rank score, take top N
        setups.sort(key=lambda s: s.rank_score, reverse=True)
        top = setups[:settings.intraday_watchlist_size]

        # Save to DB (TTL 1 day handled by collection TTL index)
        if top:
            await db.intraday_watchlist.delete_many(
                {"scan_date": today.isoformat()}
            )
            docs = [
                {**s.model_dump(), "scan_date": s.scan_date.isoformat()}
                for s in top
            ]
            await db.intraday_watchlist.insert_many(docs)
            logger.info(f"Pre-market scan complete: {len(top)} candidates saved")

        return top

    async def get_today_watchlist(self) -> list[IntradaySetup]:
        """Load today's watchlist from DB (cached scan results)."""
        today = now_ist().date()
        docs = await db.intraday_watchlist.find(
            {"scan_date": today.isoformat()}
        ).sort("rank_score", -1).to_list(length=50)

        setups = []
        for doc in docs:
            try:
                doc.pop("_id", None)
                doc["scan_date"] = date.fromisoformat(doc["scan_date"])
                setups.append(IntradaySetup(**doc))
            except Exception:
                pass
        return setups

    # ----------------------------------------------------------------
    # Daily EOD report
    # ----------------------------------------------------------------

    async def generate_daily_report(self) -> IntradayDailyReport:
        """Compute and save today's intraday P&L summary."""
        today = now_ist().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())

        docs = await db.intraday_positions.find({
            "entry_time": {"$gte": today_start, "$lte": today_end},
            "status": {"$in": ["CLOSED", "TARGET_HIT", "STOP_HIT", "HARD_EXITED"]},
        }).to_list(length=200)

        report = IntradayDailyReport(date=today)

        pnls: list[float] = []
        capital = 0.0

        for doc in docs:
            doc.pop("_id", None)
            pnl = float(doc.get("current_pnl", 0))
            entry = float(doc.get("entry_price", 0))
            qty = int(doc.get("quantity", 0))
            report.total_trades += 1
            capital += entry * qty

            if pnl > 0:
                report.wins += 1
            elif pnl < 0:
                report.losses += 1
            else:
                report.breakevens += 1

            pnls.append(pnl)

        if pnls:
            report.total_pnl = round(sum(pnls), 2)
            report.max_win = round(max(pnls), 2)
            report.max_loss = round(min(pnls), 2)
            report.win_rate = round(report.wins / report.total_trades * 100, 1)
            report.capital_deployed = round(capital, 2)
            if capital > 0:
                report.total_pnl_pct = round(report.total_pnl / capital * 100, 2)

            best_idx = pnls.index(max(pnls))
            worst_idx = pnls.index(min(pnls))
            best_doc = docs[best_idx]
            worst_doc = docs[worst_idx]
            report.best_trade = f"{best_doc.get('symbol')} +Rs.{max(pnls):.0f}"
            report.worst_trade = f"{worst_doc.get('symbol')} Rs.{min(pnls):.0f}"

        # Check if daily loss breaker was triggered today
        breaker_doc = await db.intraday_breaker_state.find_one(
            {"date": today.isoformat()}
        )
        report.daily_loss_breaker_triggered = bool(
            breaker_doc and breaker_doc.get("triggered")
        )

        # Save report
        await db.intraday_daily_pnl.replace_one(
            {"date": today.isoformat()},
            {**report.model_dump(), "date": today.isoformat()},
            upsert=True,
        )

        return report

    # ----------------------------------------------------------------
    # Telegram formatting
    # ----------------------------------------------------------------

    def format_morning_report(self, setups: list[IntradaySetup]) -> str:
        """Format pre-market watchlist for Telegram."""
        if not setups:
            return "No strong intraday candidates found today.\nMarket may be flat or data unavailable."

        lines = [
            "<b>Intraday Watchlist</b>\n",
            f"Scanned at {now_ist().strftime('%H:%M IST')} | {len(setups)} candidates\n",
        ]

        for s in setups[:10]:
            gap_arrow = "+" if s.gap_pct >= 0 else ""
            bias_icon = {"BULLISH": "G", "BEARISH": "R", "NEUTRAL": "N"}.get(
                "BULLISH" if s.gap_pct > 0 else "BEARISH" if s.gap_pct < 0 else "NEUTRAL", "N"
            )
            lines.append(
                f"<b>{s.symbol}</b> [{bias_icon}] "
                f"Gap: {gap_arrow}{s.gap_pct:.2f}% | "
                f"CPR: {s.cpr_bc:.1f}-{s.cpr_tc:.1f} | "
                f"Pivot: {s.cpr_pivot:.1f}\n"
                f"  R1: {s.cpr_r1:.1f} | S1: {s.cpr_s1:.1f} | "
                f"Reason: {s.watchlist_reason}"
            )
            lines.append("")

        lines.append("\nORB setup pending (computed at 9:31 AM)")
        lines.append("Use /isetup SYMBOL for detailed levels")
        return "\n".join(lines)

    def format_daily_report(self, report: IntradayDailyReport) -> str:
        """Format EOD intraday report for Telegram."""
        pnl_sign = "+" if report.total_pnl >= 0 else ""
        pct_sign = "+" if report.total_pnl_pct >= 0 else ""
        lines = [
            "<b>Intraday EOD Report</b>",
            f"Date: {report.date.strftime('%d %b %Y')}",
            "",
            f"Trades: {report.total_trades} | Wins: {report.wins} | Losses: {report.losses}",
            f"Win Rate: {report.win_rate:.1f}%",
            f"P&L: {pnl_sign}Rs.{report.total_pnl:.0f} ({pct_sign}{report.total_pnl_pct:.2f}%)",
        ]
        if report.best_trade:
            lines.append(f"Best: {report.best_trade}")
        if report.worst_trade:
            lines.append(f"Worst: {report.worst_trade}")
        if report.daily_loss_breaker_triggered:
            lines.append("\n[WARN] Daily loss limit was triggered today")
        return "\n".join(lines)

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------

    async def _load_symbols(self) -> list[str]:
        """Load NSE symbols from file (NIFTY 50 focus) for intraday scanning."""
        from src.config import settings

        symbols: list[str] = []
        try:
            with open(settings.screener_symbols_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            symbols = [d["symbol"] for d in data if "symbol" in d]
        except Exception:
            pass

        # Also add user watchlist from DB
        try:
            user_settings = await db.user_settings.find_one({})
            if user_settings:
                symbols.extend(user_settings.get("watchlist", []))
        except Exception:
            pass

        # Deduplicate, cap at 50 for API rate limits
        seen: set[str] = set()
        unique: list[str] = []
        for s in symbols:
            if s not in seen:
                seen.add(s)
                unique.append(s)
        return unique[:50]


# Singleton
intraday_scanner = IntradayScanner()
