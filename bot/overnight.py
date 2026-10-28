"""Overnight research: buy at the close, sell at the next open.

    python -m bot.overnight --years 20 --symbols SPY,QQQ,IWM

Much of the stock market's long-run gain has historically come overnight rather than
during the day. This checks whether capturing only that part pays after costs: each
trade pays slippage on both fills plus sell fees. Rules tried (on each symbol alone,
fully invested on the nights it trades):

  every       every night
  down_day    only after a day that closed down
  uptrend     only while the close is above the 200-day average
  both        down day and uptrend

Uses Yahoo daily bars through bot.swing.daily_bars (cached). Scored on the first 2/3
of the history and the last 1/3. Research only; nothing here places orders.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import Settings
from .swing import daily_bars

RULES = {
    "every": lambda d: pd.Series(True, index=d.index),
    "down_day": lambda d: d["close"] < d["close"].shift(1),
    "uptrend": lambda d: d["close"] > d["close"].rolling(200).mean(),
    "both": lambda d: (d["close"] < d["close"].shift(1)) & (d["close"] > d["close"].rolling(200).mean()),
}


def overnight_trades(df: pd.DataFrame, rule: str, cfg: Settings) -> pd.Series:
    """Net return of each overnight trade, indexed by the day it was bought (at that day's close)."""
    slip = cfg.slippage_bps / 10_000
    buy = df["close"] * (1 + slip)
    sell = df["open"].shift(-1) * (1 - slip)
    fee = cfg.sec_fee_rate + cfg.taf_per_share / sell  # sell fees as a share of the sale, per share
    ret = sell / buy * (1 - fee) - 1
    take = RULES[rule](df).fillna(False) & ret.notna()
    return ret[take]


def stats(r: pd.Series, years: float) -> dict:
    if not len(r):
        return {"trades": 0, "win": 0.0, "pf": 0.0, "cagr": 0.0, "dd": 0.0}
    eq = (1 + r).cumprod()
    w, l = r[r > 0].sum(), -r[r <= 0].sum()
    return {"trades": len(r), "win": (r > 0).mean(), "pf": w / l if l else float("inf"),
            "cagr": eq.iloc[-1] ** (1 / years) - 1 if years > 0 else 0.0,
            "dd": float((eq / eq.cummax() - 1).min())}


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest buy-at-close, sell-at-next-open")
    ap.add_argument("--years", type=int, default=20)
    ap.add_argument("--symbols", default="SPY,QQQ,IWM,DIA")
    ap.add_argument("--slippage", type=float, nargs="+", default=[2.0, 5.0])
    ap.add_argument("--source", default="yfinance")
    args = ap.parse_args()
    base = Settings()
    out = [f"# Overnight research, {datetime.now():%Y-%m-%d}", "",
           "Buy at the close, sell at the next open, fully invested on nights the rule trades. "
           "After sell fees and the slippage shown, on both fills. CAGR = yearly growth.", ""]
    for sym in args.symbols.split(","):
        df = daily_bars(sym, args.years, base, source=args.source).dropna()
        if len(df) < 300:
            continue
        split = df.index[int(len(df) * 2 / 3)]
        yrs_is = (split - df.index[0]).days / 365.25
        yrs_oos = (df.index[-1] - split).days / 365.25
        hold = df["close"]
        bh_is, bh_oos = hold[:split], hold[split:]
        out += [f"## {sym}: {df.index[0]:%Y-%m-%d} to {df.index[-1]:%Y-%m-%d}, out-of-sample from {split:%Y-%m-%d}", "",
                f"Buy and hold: in-sample CAGR {(bh_is.iloc[-1] / bh_is.iloc[0]) ** (1 / yrs_is) - 1:+.1%}, "
                f"out-of-sample CAGR {(bh_oos.iloc[-1] / bh_oos.iloc[0]) ** (1 / yrs_oos) - 1:+.1%}", "",
                "| Rule | Slippage | In-sample trades | Win | PF | CAGR | Max DD | Out-of-sample trades | Win | PF | CAGR | Max DD |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for bps in args.slippage:
            cfg = Settings(slippage_bps=bps)
            for rule in RULES:
                r = overnight_trades(df, rule, cfg)
                i, o = stats(r[r.index < split], yrs_is), stats(r[r.index >= split], yrs_oos)
                out.append(f"| {rule} | {bps:g} bps | {i['trades']} | {i['win']:.0%} | {i['pf']:.2f} | {i['cagr']:+.1%} | "
                           f"{i['dd']:.0%} | {o['trades']} | {o['win']:.0%} | {o['pf']:.2f} | {o['cagr']:+.1%} | {o['dd']:.0%} |")
        out.append("")
    text = "\n".join(out)
    print(text)
    Path("reports").mkdir(exist_ok=True)
    path = Path("reports") / f"overnight_{datetime.now():%Y-%m-%d}.md"
    path.write_text(text, encoding="utf-8")
    print(f"\nSaved to {path.resolve()}")


if __name__ == "__main__":
    main()
