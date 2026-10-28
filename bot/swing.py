"""Daily swing bot research: holds for days, not minutes, so it makes and loses money
at different times than ORB.

    python -m bot.swing --source alpaca --years 8 --cash 5000

Uses split-adjusted daily bars (cached in data_cache/). Signals are computed on a day's
close and filled at the next day's open plus slippage, with sell fees, like the intraday
backtest. Up to SWING_SLOTS positions at once, each sized at equity / slots.

  rsi2       Buy when RSI(2) closes under 10 while above the 200-day average.
             Sell when the close gets back above the 5-day average, or after 10 days.
  breakout   Buy a close at a new 50-day high while above the 200-day average.
             Sell on a close under the 20-day low (a trailing exit).
  pullback   In an uptrend (50-day average above the 200-day), buy 3 down closes in a row.
             Sell after 5 days, or on a close above the previous day's high.

Each is scored on the first 2/3 of the history (in-sample) and the last 1/3 (out-of-sample).
Writes reports/swing_<date>.md. Research only; nothing here places orders.
"""
from __future__ import annotations

import argparse
import dataclasses
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import sell_fees
from .config import Settings
from .strategy import rsi

DEFAULT_SYMBOLS = "SPY,QQQ,IWM,DIA,AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,XLF,XLE,XLV,GLD,TLT"


def daily_bars(symbol: str, years: int, cfg: Settings, cache: Path = Path("data_cache"),
               source: str = "alpaca") -> pd.DataFrame:
    """Split- and dividend-adjusted daily bars, cached. Alpaca's free daily history starts in
    mid-2020; Yahoo (source="yfinance") goes back decades, so it can test 2008 and 2022."""
    cache.mkdir(exist_ok=True)
    path = cache / f"{symbol}_1d_{years}y{'_yf' if source == 'yfinance' else ''}.pkl"
    if path.exists():
        return pd.read_pickle(path)
    if source == "yfinance":
        import yfinance as yf

        df = yf.download(symbol, period=f"{years}y", interval="1d", progress=False, auto_adjust=True,
                         multi_level_index=False)
        if df.empty:
            return df
        df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna()  # today's bar is NaN
        df.index = pd.to_datetime(df.index).tz_localize("UTC")
        df.to_pickle(path)
        return df
    from alpaca.data.enums import Adjustment
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = StockHistoricalDataClient(cfg.alpaca_key, cfg.alpaca_secret)
    req = StockBarsRequest(
        symbol_or_symbols=symbol, timeframe=TimeFrame.Day, adjustment=Adjustment.ALL, feed="iex",
        start=datetime.now(timezone.utc) - timedelta(days=365 * years),
        end=datetime.now(timezone.utc) - timedelta(days=1),
    )
    df = client.get_stock_bars(req).df
    if df.empty:
        return df
    df = df.xs(symbol, level="symbol")[["open", "high", "low", "close", "volume"]]
    df.to_pickle(path)
    return df


def add_daily_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    c = out["close"]
    out["sma5"], out["sma50"], out["sma200"] = c.rolling(5).mean(), c.rolling(50).mean(), c.rolling(200).mean()
    out["rsi2"] = rsi(c, 2)
    out["high50"] = c.rolling(50).max()
    out["low20"] = out["low"].rolling(20).min().shift(1)  # the 20 days before today
    down = c < c.shift(1)
    out["down3"] = down & down.shift(1, fill_value=False) & down.shift(2, fill_value=False)
    return out


# Each rule: (entry(row) -> bool, exit(row, prev_row, days_held) -> bool)
def _rsi2_entry(r):
    return r["rsi2"] < 10 and r["close"] > r["sma200"]


def _rsi2_exit(r, prev, held):
    return r["close"] > r["sma5"] or held >= 10


def _breakout_entry(r):
    return r["close"] >= r["high50"] and r["close"] > r["sma200"]


def _breakout_exit(r, prev, held):
    return r["close"] < r["low20"]


def _pullback_entry(r):
    return bool(r["down3"]) and r["sma50"] > r["sma200"]


def _pullback_exit(r, prev, held):
    return held >= 5 or r["close"] > prev["high"]


RULES = {
    "rsi2": (_rsi2_entry, _rsi2_exit),
    "breakout": (_breakout_entry, _breakout_exit),
    "pullback": (_pullback_entry, _pullback_exit),
}


@dataclass
class Holding:
    qty: int
    entry: float
    entry_date: pd.Timestamp
    held: int = 0


def run_swing(frames: dict[str, pd.DataFrame], rule: str, cfg: Settings, cash: float = 5_000,
              slots: int = 5) -> dict:
    entry_rule, exit_rule = RULES[rule]
    data = {s: add_daily_indicators(df) for s, df in frames.items() if len(df) > 200}
    days = sorted(set().union(*[df.index for df in data.values()])) if data else []
    slip = cfg.slippage_bps / 10_000
    start_cash = cash
    held: dict[str, Holding] = {}
    to_buy: list[str] = []
    to_sell: set[str] = set()
    trades, curve = [], []

    def equity(d) -> float:
        return cash + sum(h.qty * data[s].loc[:d, "close"].iloc[-1] for s, h in held.items())

    for d in days:
        # 1. fill yesterday's decisions at today's open: sells first, then buys
        for s in list(to_sell):
            if s in held and d in data[s].index:
                h = held.pop(s)
                fill = data[s].loc[d, "open"] * (1 - slip)
                fees = sell_fees(h.qty, fill, cfg)
                cash += h.qty * fill - fees
                trades.append({"symbol": s, "entry_time": h.entry_date, "exit_time": d, "qty": h.qty,
                               "entry": h.entry, "exit": fill, "pnl": h.qty * (fill - h.entry) - fees,
                               "fees": fees, "days": h.held})
        to_sell.clear()
        budget = (curve[-1][1] if curve else cash) / slots  # yesterday's closing equity: no peeking
        for s in to_buy:
            if len(held) >= slots or s in held or d not in data[s].index:
                continue
            fill = data[s].loc[d, "open"] * (1 + slip)
            qty = int(min(budget, cash) // fill)
            if qty > 0:
                cash -= qty * fill
                held[s] = Holding(qty, fill, d)
        to_buy = []

        # 2. decide on today's close
        candidates = []
        for s, df in data.items():
            if d not in df.index:
                continue
            i = df.index.get_loc(d)
            if i < 200:
                continue
            r, prev = df.iloc[i], df.iloc[i - 1]
            if s in held:
                held[s].held += 1
                if exit_rule(r, prev, held[s].held):
                    to_sell.add(s)
            elif entry_rule(r):
                candidates.append((r["rsi2"], s))  # most oversold first when slots are short
        to_buy = [s for _, s in sorted(candidates)]
        curve.append((d, equity(d)))

    for s, h in list(held.items()):  # close what's left at the last close
        px = data[s]["close"].iloc[-1] * (1 - slip)
        fees = sell_fees(h.qty, px, cfg)
        cash += h.qty * px - fees
        trades.append({"symbol": s, "entry_time": h.entry_date, "exit_time": days[-1], "qty": h.qty,
                       "entry": h.entry, "exit": px, "pnl": h.qty * (px - h.entry) - fees, "fees": fees,
                       "days": h.held})
    eq = pd.Series([v for _, v in curve], index=[t for t, _ in curve], dtype=float)
    return {"trades": pd.DataFrame(trades), "equity_curve": eq, "final": cash, "start": start_cash,
            "max_drawdown": float(((eq / eq.cummax()) - 1).min()) if len(eq) else 0.0}


def score(trades: pd.DataFrame, cash: float) -> dict:
    if not len(trades):
        return {"trades": 0, "win_rate": 0.0, "pf": 0.0, "pnl": 0.0, "return": 0.0}
    w, l = trades[trades["pnl"] > 0]["pnl"].sum(), -trades[trades["pnl"] <= 0]["pnl"].sum()
    return {"trades": len(trades), "win_rate": (trades["pnl"] > 0).mean(), "pf": w / l if l else float("inf"),
            "pnl": trades["pnl"].sum(), "return": trades["pnl"].sum() / cash}


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest daily swing strategies")
    ap.add_argument("--years", type=int, default=8)
    ap.add_argument("--cash", type=float, default=5_000)
    ap.add_argument("--slots", type=int, default=5, help="max positions at once")
    ap.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    ap.add_argument("--oos", type=float, default=1 / 3)
    ap.add_argument("--source", default="alpaca", help="alpaca (from mid-2020) or yfinance (decades)")
    ap.add_argument("--slippage", type=float, default=None, help="bps per fill; default SLIPPAGE_BPS")
    args = ap.parse_args()
    cfg = Settings()
    if args.slippage is not None:
        cfg = dataclasses.replace(cfg, slippage_bps=args.slippage)
    frames = {}
    for s in args.symbols.split(","):
        frames[s] = daily_bars(s, args.years, cfg, source=args.source)
        print(f"  {s}: {len(frames[s]):,} days")
    frames = {s: df for s, df in frames.items() if not df.empty}
    start = min(df.index[0] for df in frames.values()) + timedelta(days=300)  # after the 200-day warm-up
    end = max(df.index[-1] for df in frames.values())
    split = start + (end - start) * (1 - args.oos)
    out = [f"# Swing strategies, {datetime.now():%Y-%m-%d}", "",
           f"{', '.join(frames)} | daily bars | ${args.cash:,.0f} | {args.slots} slots | "
           f"in-sample to {split:%Y-%m-%d}, out-of-sample after. After sell fees and {cfg.slippage_bps:g} bps per fill.",
           "", "| Strategy | In-sample trades | PF | P&L | Out-of-sample trades | PF | P&L | Avg days held | Max drawdown |",
           "|---|---|---|---|---|---|---|---|---|"]
    for rule in RULES:
        res = run_swing(frames, rule, cfg, args.cash, args.slots)
        t = res["trades"]
        i = score(t[t["entry_time"] < split] if len(t) else t, args.cash)
        o = score(t[t["entry_time"] >= split] if len(t) else t, args.cash)
        avg_days = t["days"].mean() if len(t) else np.nan
        out.append(f"| {rule} | {i['trades']} | {i['pf']:.2f} | ${i['pnl']:,.0f} | {o['trades']} | {o['pf']:.2f} | "
                   f"${o['pnl']:,.0f} | {avg_days:.1f} | {res['max_drawdown']:.1%} |")
    spy = frames.get("SPY")
    if spy is not None:
        s = spy[spy.index >= split]["close"]
        out += ["", f"For comparison, buying and holding SPY out-of-sample returned {s.iloc[-1] / s.iloc[0] - 1:+.1%}."]
    text = "\n".join(out)
    print(text)
    Path("reports").mkdir(exist_ok=True)
    path = Path("reports") / f"swing_{datetime.now():%Y-%m-%d}.md"
    path.write_text(text, encoding="utf-8")
    print(f"\nSaved to {path.resolve()}")


if __name__ == "__main__":
    main()
