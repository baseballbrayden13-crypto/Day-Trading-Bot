"""Research data for the free-data filters (Nov 10 2026). Read-only: market data and public pages, no orders.

    python -m bot.filter_data --out out

Writes to --out:
  bot1_trades.csv     bot 1's ORB trade log, 3 years, its .env settings (5-min Alpaca bars)
  earnings.csv        symbol,date of past earnings reports (Yahoo)
  fomc.csv            FOMC decision days (federalreserve.gov)
  cpi.csv, jobs.csv   CPI and jobs-report release days (BLS schedule pages, when reachable)
  fear_greed.csv      crypto fear & greed index, daily (alternative.me)
  funding.csv         BTC and ETH perpetual funding rates, 8-hourly (first exchange that answers)
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import time
import urllib.request
from pathlib import Path

import pandas as pd

UA = {"User-Agent": "Mozilla/5.0 (research script)"}


def get(url: str, tries: int = 3) -> bytes:
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            print("  fail", url, e)
            time.sleep(2 * (i + 1))
    return b""


def bot1_trades(out: Path, days: int) -> None:
    from . import research as rs
    from .backtest import run_backtest
    from .config import Settings

    cfg = dataclasses.replace(Settings(), strategy="orb")
    frames = rs.load_cached(sorted(set(cfg.symbols) | {"SPY"}), days, cfg, "alpaca", Path("data_cache"))
    res = run_backtest({s: frames[s] for s in cfg.symbols if s in frames}, cfg, 5_000,
                       market=frames["SPY"] if cfg.market_filter == "SPY" else None)
    res["trade_log"].to_csv(out / "bot1_trades.csv", index=False)
    print("bot 1 trades", len(res["trade_log"]), cfg.symbols)


def earnings(out: Path, symbols: list[str]) -> None:
    import yfinance as yf

    rows = []
    for s in symbols:
        try:
            df = yf.Ticker(s).get_earnings_dates(limit=60)
            for ts in (df.index if df is not None else []):
                rows.append((s, pd.Timestamp(ts).tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M")))
            print("earnings", s, len(df) if df is not None else 0)
        except Exception as e:  # noqa: BLE001
            print("earnings fail", s, e)
        time.sleep(1)
    pd.DataFrame(rows, columns=["symbol", "when"]).to_csv(out / "earnings.csv", index=False)


def fomc(out: Path) -> None:
    days = set()
    pages = ["https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"] + [
        f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{y}.htm" for y in range(2015, 2021)]
    months = "January|February|March|April|May|June|July|August|September|October|November|December"
    for url in pages:
        html = get(url).decode("utf-8", "ignore")
        year = None
        # calendar page: "<h4>2024 FOMC Meetings</h4>" then panels "January" "30-31"
        for m in re.finditer(rf"(20\d\d) FOMC Meetings|fomc-meeting__month[^>]*>\s*<strong>({months})[^<]*</strong>.*?fomc-meeting__date[^>]*>\s*(\d+)(?:-(\d+))?", html, re.S):
            if m.group(1):
                year = m.group(1)
            elif year:
                day = m.group(4) or m.group(3)
                days.add(pd.Timestamp(f"{m.group(2)} {day} {year}").strftime("%Y-%m-%d"))
        # historical pages: "FOMC Meeting ... January 28-29, 2020" headings
        for m in re.finditer(rf"({months})\s+(\d+)(?:-(\d+))?,?\s+(20\d\d)\s*(?:FOMC )?Meeting", html):
            day = m.group(3) or m.group(2)
            days.add(pd.Timestamp(f"{m.group(1)} {day} {m.group(4)}").strftime("%Y-%m-%d"))
    pd.Series(sorted(days), name="date").to_csv(out / "fomc.csv", index=False)
    print("fomc days", len(days))


def bls(out: Path) -> None:
    """Release days from the BLS schedule and archive pages (BLS sometimes refuses scripts; then the file is empty)."""
    for name, code in (("cpi", "cpi"), ("jobs", "empsit")):
        days = set()
        html = "".join(get(u).decode("utf-8", "ignore") for u in (
            f"https://www.bls.gov/schedule/news_release/{code}.htm", f"https://www.bls.gov/bls/news-release/{code}.htm"))
        for m in re.finditer(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? (\d{1,2}), (20[12]\d)", html):
            try:
                days.add(pd.Timestamp(f"{m.group(1)} {m.group(2)} {m.group(3)}").strftime("%Y-%m-%d"))
            except ValueError:
                pass
        pd.Series(sorted(days), name="date").to_csv(out / f"{name}.csv", index=False)
        print(name, "days", len(days), "page bytes", len(html))


def fear_greed(out: Path) -> None:
    raw = get("https://api.alternative.me/fng/?limit=0&format=json")
    data = json.loads(raw or b"{}").get("data", [])
    df = pd.DataFrame([(pd.Timestamp(int(d["timestamp"]), unit="s").strftime("%Y-%m-%d"), int(d["value"])) for d in data],
                      columns=["date", "value"]).sort_values("date")
    df.to_csv(out / "fear_greed.csv", index=False)
    print("fear greed", len(df))


def funding(out: Path) -> None:
    rows = []
    for coin in ("BTC", "ETH"):
        got = False
        # Binance (may refuse US runners), then Bybit, then OKX (OKX keeps only ~3 months)
        start = int(pd.Timestamp("2019-09-01").timestamp() * 1000)
        while not got:
            raw = get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={coin}USDT&startTime={start}&limit=1000", tries=1)
            try:
                page = json.loads(raw)
            except ValueError:
                page = None
            if not isinstance(page, list) or not page:
                break
            rows += [(coin, pd.Timestamp(p["fundingTime"], unit="ms").strftime("%Y-%m-%d %H:%M"), float(p["fundingRate"]), "binance") for p in page]
            start = page[-1]["fundingTime"] + 1
            if len(page) < 1000:
                got = True
        if got:
            continue
        # BitMEX keeps funding back to 2016 (XBTUSD) and 2018 (ETHUSD)
        sym = {"BTC": "XBTUSD", "ETH": "ETHUSD"}[coin]
        start_i = 0
        while True:
            raw = get(f"https://www.bitmex.com/api/v1/funding?symbol={sym}&count=500&start={start_i}", tries=2)
            try:
                page = json.loads(raw)
            except ValueError:
                page = None
            if not isinstance(page, list) or not page:
                break
            rows += [(coin, p["timestamp"][:16].replace("T", " "), float(p["fundingRate"]), "bitmex") for p in page]
            got = True
            start_i += len(page)
            if len(page) < 500:
                break
            time.sleep(1.2)
        if got:
            continue
        end = int(time.time() * 1000)
        for _ in range(40):
            raw = get(f"https://api.bybit.com/v5/market/funding/history?category=linear&symbol={coin}USDT&limit=200&endTime={end}", tries=1)
            try:
                lst = json.loads(raw)["result"]["list"]
            except (ValueError, KeyError, TypeError):
                lst = []
            if not lst:
                break
            rows += [(coin, pd.Timestamp(int(p["fundingRateTimestamp"]), unit="ms").strftime("%Y-%m-%d %H:%M"), float(p["fundingRate"]), "bybit") for p in lst]
            end = int(lst[-1]["fundingRateTimestamp"]) - 1
            got = True
        print("funding", coin, "rows so far", len(rows))
    pd.DataFrame(rows, columns=["coin", "time", "rate", "source"]).drop_duplicates().sort_values(["coin", "time"]).to_csv(out / "funding.csv", index=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--days", type=int, default=1095)
    ap.add_argument("--skip-bot1", action="store_true")
    ap.add_argument("--only", default="", help="run just these steps, e.g. funding")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    from .fleet import DIP_SYMBOLS
    steps = {"fomc": lambda: fomc(out), "bls": lambda: bls(out), "fear_greed": lambda: fear_greed(out),
             "funding": lambda: funding(out),
             "earnings": lambda: earnings(out, sorted(set(DIP_SYMBOLS.split(",")) | {"AAPL", "MSFT", "NVDA"}))}
    only = [x for x in a.only.split(",") if x]
    for name, step in steps.items():
        if only and name not in only:
            continue
        try:
            step()
        except Exception as e:  # noqa: BLE001
            print("step failed", e)
    if not a.skip_bot1 and not only:
        bot1_trades(out, a.days)


if __name__ == "__main__":
    main()
