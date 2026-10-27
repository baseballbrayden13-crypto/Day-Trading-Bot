"""More bot ideas on daily bars, each holding one asset or cash:

    python -m bot.daily_rules --years 20

  turn_of_month  Hold from the close of the 4th-last trading day of each month to the
                 close of the 3rd trading day of the next. Month-end pension and payroll
                 money has historically lifted stocks around then.
  trend200       Hold while the close is above the 200-day average, otherwise cash.
                 Checked at each close and traded at that close (a market-on-close order).
  trend50        The same with a 50-day average: faster, but more trades.
  tom_trend      turn_of_month, but only while above the 200-day average.

Stocks use SLIPPAGE_BPS per fill plus sell fees. Crypto (symbols ending -USD, e.g.
BTC-USD) uses --crypto-fee instead, about Alpaca's 0.25% taker fee, and trades every day
of the week. Scored on the first 2/3 of the history and the last 1/3, against buy and
hold. Yahoo daily bars through bot.swing.daily_bars. Research only.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import Settings
from .swing import daily_bars


def turn_of_month(df: pd.DataFrame) -> pd.Series:
    """True on days whose close-to-close return the strategy holds."""
    ym = pd.Series(df.index.year * 12 + df.index.month, index=df.index)
    nth = ym.groupby(ym).cumcount() + 1  # trading day number within the month
    from_end = ym.groupby(ym).cumcount(ascending=False) + 1
    # we hold over day d's return if bought at the close before it: last 3 days of a month and first 3 of the next
    return (from_end <= 3) | (nth <= 3)


def _above(df: pd.DataFrame, n: int) -> pd.Series:
    """Decided on yesterday's close, so it applies to today's move."""
    return (df["close"] > df["close"].rolling(n).mean()).shift(1, fill_value=False)


RULES = {
    "turn_of_month": turn_of_month,
    "trend200": lambda df: _above(df, 200),
    "trend50": lambda df: _above(df, 50),
    "tom_trend": lambda df: turn_of_month(df) & _above(df, 200),
}


def strategy_returns(df: pd.DataFrame, rule: str, cost: float) -> pd.Series:
    """Daily returns of holding the asset on the rule's days (close to close), cash otherwise.
    `cost` (a fraction, per side) is charged on every day the position is opened or closed."""
    hold = RULES[rule](df).astype(bool)
    ret = df["close"].pct_change().fillna(0)
    switches = hold.astype(int).diff().abs().fillna(hold.astype(int))
    return ret.where(hold, 0.0) - switches * cost


def stats(r: pd.Series, per_year: float) -> dict:
    eq = (1 + r).cumprod()
    yrs = len(r) / per_year
    return {"cagr": eq.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else 0.0, "dd": float((eq / eq.cummax() - 1).min())}


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest simple daily hold-or-cash bots")
    ap.add_argument("--years", type=int, default=20)
    ap.add_argument("--symbols", default="SPY,QQQ,BTC-USD,ETH-USD")
    ap.add_argument("--crypto-fee", type=float, default=25.0, help="bps per side for crypto")
    ap.add_argument("--ma", default="", help="extra trend rules to try, e.g. 20,30,75,100 (adds trend20 ...)")
    args = ap.parse_args()
    for n in [int(x) for x in args.ma.split(",") if x.strip()]:
        RULES.setdefault(f"trend{n}", lambda df, n=n: _above(df, n))
    cfg = Settings()
    out = [f"# Daily hold-or-cash bots, {datetime.now():%Y-%m-%d}", "",
           f"Stocks: {cfg.slippage_bps:g} bps per side + sell fees. Crypto: {args.crypto_fee:g} bps per side. "
           "CAGR = yearly growth, DD = worst drop, In = share of days invested.", ""]
    for sym in args.symbols.split(","):
        df = daily_bars(sym, args.years, cfg, source="yfinance").dropna()
        if len(df) < 400:
            continue
        crypto = sym.endswith("-USD")
        cost = args.crypto_fee / 10_000 if crypto else cfg.slippage_bps / 10_000 + cfg.sec_fee_rate / 2
        per_year = 365 if crypto else 252
        split = df.index[int(len(df) * 2 / 3)]
        out += [f"## {sym}: {df.index[0]:%Y-%m-%d} to {df.index[-1]:%Y-%m-%d}, out-of-sample from {split:%Y-%m-%d}", "",
                "| Rule | In | Whole CAGR | DD | In-sample CAGR | DD | Out-of-sample CAGR | DD |", "|---|---|---|---|---|---|---|---|"]
        bh = df["close"].pct_change().fillna(0)
        rows = [("buy and hold", bh, 1.0)]
        for rule in RULES:
            rows.append((rule, strategy_returns(df, rule, cost), RULES[rule](df).mean()))
        for name, r, inm in rows:
            w, i, o = stats(r, per_year), stats(r[r.index < split], per_year), stats(r[r.index >= split], per_year)
            out.append(f"| {name} | {inm:.0%} | {w['cagr']:+.1%} | {w['dd']:.0%} | {i['cagr']:+.1%} | {i['dd']:.0%} | "
                       f"{o['cagr']:+.1%} | {o['dd']:.0%} |")
        out.append("")
    text = "\n".join(out)
    print(text)
    Path("reports").mkdir(exist_ok=True)
    path = Path("reports") / f"daily_rules_{datetime.now():%Y-%m-%d}.md"
    path.write_text(text, encoding="utf-8")
    print(f"\nSaved to {path.resolve()}")


if __name__ == "__main__":
    main()
