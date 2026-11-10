"""Event days bot 1 sits out (SKIP_EVENT_DAYS=true, off by default).

  * A stock's earnings reaction day: the report day if it came out before the open, otherwise the next
    trading day. The opening range on those days is the earnings gap, not a normal breakout.
  * Jobs-report Fridays (the monthly payrolls report at 8:30am ET), approximated as the first Friday of
    the month. That's right in most months; BLS occasionally moves it a week.

Nov 10 2026 test on bot 1's 3-year trade log (/mnt/project-files/reports/free-data-filters.md): skipping both
kept profit factor up in both halves (first 2 years 1.37 -> 1.46, last year 1.24 -> 1.29), but only ~25
trades were affected, so it's a small, uncertain gain.

Earnings dates come from bot/earnings.csv (symbol,when in ET, from Yahoo), which refresh() tops up.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd

log = logging.getLogger("events")
EARNINGS_FILE = Path(os.getenv("EARNINGS_FILE", Path(__file__).with_name("earnings.csv")))
ETF_SYMBOLS = {"SPY", "QQQ", "IWM", "DIA"}


def jobs_friday(day: date) -> bool:
    return day.weekday() == 4 and day.day <= 7


def _next_weekday(d: date) -> date:
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


@lru_cache(maxsize=1)
def _reaction_days(path: str, mtime: float) -> dict[str, set[date]]:
    out: dict[str, set[date]] = {}
    try:
        df = pd.read_csv(path)
    except (OSError, ValueError):
        return out
    for sym, when in zip(df["symbol"], df["when"]):
        try:
            ts = datetime.strptime(str(when)[:16], "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        day = ts.date() if ts.hour < 12 else _next_weekday(ts.date())  # after the close: next session reacts
        out.setdefault(sym, set()).add(day)
    return out


def earnings_days(symbol: str) -> set[date]:
    p = EARNINGS_FILE
    mtime = p.stat().st_mtime if p.exists() else 0.0
    return _reaction_days(str(p), mtime).get(symbol.upper(), set())


def skip_reason(symbol: str, day: date) -> str:
    """Why bot 1 sits this symbol out today, or "" to trade normally."""
    if jobs_friday(day):
        return "jobs-report Friday"
    if symbol.upper() not in ETF_SYMBOLS and day in earnings_days(symbol):
        return f"{symbol} earnings day"
    return ""


def refresh(symbols: list[str]) -> int:
    """Add upcoming earnings dates from Yahoo to EARNINGS_FILE. Returns how many dates were new. Never raises."""
    try:
        import yfinance as yf

        old = pd.read_csv(EARNINGS_FILE) if EARNINGS_FILE.exists() else pd.DataFrame(columns=["symbol", "when"])
        rows = []
        for s in symbols:
            if s.upper() in ETF_SYMBOLS:
                continue
            df = yf.Ticker(s).get_earnings_dates(limit=8)
            for ts in (df.index if df is not None else []):
                rows.append((s.upper(), pd.Timestamp(ts).tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M")))
        new = pd.concat([old, pd.DataFrame(rows, columns=["symbol", "when"])]).drop_duplicates()
        added = len(new) - len(old)
        if added:
            new.sort_values(["symbol", "when"]).to_csv(EARNINGS_FILE, index=False)
        return added
    except Exception as e:  # noqa: BLE001 - a data hiccup must never stop the bot
        log.warning("Couldn't refresh earnings dates: %s", e)
        return 0
