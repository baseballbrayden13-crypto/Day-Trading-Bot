"""Monthly ETF rotation (momentum) research: trades about once a month, so costs barely matter.

    python -m bot.rotation --years 20

At each month's last close, rank the ETFs by their return over the last LOOKBACK months
and hold the top N in equal parts from the next open. An ETF only qualifies if it is
above its 200-day average; empty slots sit in cash (or in SAFE, e.g. TLT or SHY, if set).
This is the classic "relative + absolute momentum" idea. Scored on the first 2/3 of the
history and the last 1/3, against buy-and-hold SPY. Research only; nothing places orders.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from .backtest import sell_fees
from .config import Settings
from .swing import daily_bars

DEFAULT = "SPY,QQQ,IWM,EFA,EEM,XLK,XLF,XLE,XLV,XLI,XLY,XLP,XLU,GLD,TLT"


def targets(close: pd.DataFrame, top: int = 3, lookback: int = 3, safe: str = "") -> dict[str, float]:
    """Share of the account for each ETF, from daily closes up to the decision day (last row)."""
    if len(close) < 21 * lookback + 1 or len(close) < 200:
        return {}
    last = close.iloc[-1]
    mom = last / close.iloc[-1 - 21 * lookback] - 1
    window = close.iloc[-200:]
    sma200 = window.mean().where(window.count() == 200)  # an ETF needs a full 200 days of history
    ok = [s for s in close.columns if s != safe and pd.notna(mom[s]) and pd.notna(sma200[s]) and last[s] > sma200[s]]
    picks = sorted(ok, key=lambda s: -mom[s])[:top]
    want = {s: 1 / top for s in picks}  # each pick gets one slot; empty slots stay in cash...
    if safe in close.columns and len(picks) < top:  # ...or go to the safe asset
        want[safe] = want.get(safe, 0) + (top - len(picks)) / top
    return want


def run_rotation(frames: dict[str, pd.DataFrame], cfg: Settings, top: int = 3, lookback: int = 6,
                 safe: str = "", cash: float = 5_000, guard: bool = False) -> pd.Series:
    """Daily equity curve. Decisions on month-end closes, fills at the next open with slippage and sell fees.
    guard: also sell a holding mid-month (next open) once it closes below its 200-day average."""
    close = pd.DataFrame({s: df["close"] for s, df in frames.items()}).dropna(how="all").ffill()
    open_ = pd.DataFrame({s: df["open"] for s, df in frames.items()}).reindex(close.index).ffill()
    ym = close.index.year * 12 + close.index.month
    month_end = pd.Series(ym, index=close.index) != pd.Series(ym, index=close.index).shift(-1)  # last day of each month
    below = close < close.rolling(200).mean()
    slip = cfg.slippage_bps / 10_000
    shares: dict[str, int] = {}
    want: dict[str, float] | None = None  # symbol -> share of the account
    curve = []
    for i, d in enumerate(close.index):
        if want is not None:  # rebalance at today's open
            value = cash + sum(q * open_.at[d, s] for s, q in shares.items())
            for s in [s for s in shares if s not in want]:
                px = open_.at[d, s] * (1 - slip)
                cash += shares[s] * px - sell_fees(shares[s], px, cfg)
                del shares[s]
            for s in want:
                if s in shares or pd.isna(open_.at[d, s]):
                    continue
                px = open_.at[d, s] * (1 + slip)
                q = int(min(value * want[s], cash) // px)
                if q > 0:
                    shares[s] = q
                    cash -= q * px
            want = None
        if month_end.iloc[i] and i >= 200:
            want = targets(close.iloc[: i + 1], top, lookback, safe)
        elif guard and i >= 200 and any(below.at[d, s] for s in shares if s != safe):
            want = {s: 1 / top for s in shares if s == safe or not below.at[d, s]}  # drop the broken ones, keep the rest
        curve.append((d, cash + sum(q * close.at[d, s] for s, q in shares.items())))
    return pd.Series(dict(curve))


def describe(eq: pd.Series) -> str:
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    return f"{cagr:+.1%}/yr, max drop {dd:.0%}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest monthly ETF momentum rotation")
    ap.add_argument("--years", type=int, default=20)
    ap.add_argument("--symbols", default=DEFAULT)
    ap.add_argument("--slippage", type=float, default=5.0)
    ap.add_argument("--guard", action="store_true", help="also try selling mid-month below the 200-day average")
    args = ap.parse_args()
    cfg = Settings(slippage_bps=args.slippage)
    frames = {s: daily_bars(s, args.years, cfg, source="yfinance").dropna() for s in args.symbols.split(",")}
    frames = {s: df for s, df in frames.items() if len(df) > 300}
    # SPY is the yardstick even when it isn't one of the ETFs being rotated
    spy = (frames["SPY"] if "SPY" in frames else daily_bars("SPY", args.years, cfg, source="yfinance").dropna())["close"]
    split = spy.index[int(len(spy) * 2 / 3)]
    out = [f"# Monthly ETF rotation, {datetime.now():%Y-%m-%d}", "",
           f"{', '.join(frames)} | $5,000 | {args.slippage:g} bps per fill + sell fees | out-of-sample from {split:%Y-%m-%d}", "",
           "| Version | Whole period | In-sample | Out-of-sample |", "|---|---|---|---|"]
    start = spy.index[200]
    bh = spy[start:]
    out.append(f"| Buy and hold SPY | {describe(bh)} | {describe(bh[:split])} | {describe(bh[split:])} |")
    for top in (1, 2, 3):
        for lookback in (3, 6, 12):
            for safe in ("", "TLT"):
                for guard in ((False, True) if args.guard else (False,)):
                    eq = run_rotation(frames, cfg, top, lookback, safe, guard=guard)[start:]
                    label = (f"top {top}, {lookback}-month lookback" + (f", else {safe}" if safe else ", else cash")
                             + (", mid-month 200-day exit" if guard else ""))
                    out.append(f"| {label} | {describe(eq)} | {describe(eq[:split])} | {describe(eq[split:])} |")
    text = "\n".join(out)
    print(text)
    Path("reports").mkdir(exist_ok=True)
    path = Path("reports") / f"rotation_{datetime.now():%Y-%m-%d}.md"
    path.write_text(text, encoding="utf-8")
    print(f"\nSaved to {path.resolve()}")


if __name__ == "__main__":
    main()
