"""Backtest every strategy on the same data and print them side by side.

    python -m bot.compare --source alpaca --days 180
    python -m bot.compare --strategies ema_cross,orb

Each strategy runs with the same symbols, risk limits and costs from .env,
so the only thing that differs between rows is the strategy.
"""
from __future__ import annotations

import argparse
import dataclasses
import logging

import pandas as pd

from .backtest import run_backtest
from .config import Settings
from .data import load_bars
from .strategy import STRATEGIES, get_strategy


def compare(
    frames: dict[str, pd.DataFrame], cfg: Settings, names: list[str], starting_cash: float = 25_000,
    market: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows = []
    for name in names:
        get_strategy(name)
        res = run_backtest(frames, dataclasses.replace(cfg, strategy=name), starting_cash, market)
        rows.append({
            "strategy": name,
            "trades": res["trades"],
            "win_rate": res["win_rate"],
            "profit_factor": res["profit_factor"],
            "total_return": res["total_return"],
            "max_drawdown": res["max_drawdown"],
            "avg_trade": res["avg_trade"],
            "fees": res["fees"],
        })
    return pd.DataFrame(rows).set_index("strategy").sort_values("profit_factor", ascending=False)


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest every strategy on the same data")
    ap.add_argument("--days", type=int, default=59)
    ap.add_argument("--source", default="yfinance", help="yfinance, alpaca, or a path to a .csv")
    ap.add_argument("--cash", type=float, default=25_000)
    ap.add_argument("--symbols", default=None, help="comma list; defaults to SYMBOLS from .env")
    ap.add_argument("--strategies", default=",".join(STRATEGIES), help="comma list; defaults to all")
    ap.add_argument("--out", default="compare_strategies.csv")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = Settings()
    symbols = args.symbols.split(",") if args.symbols else cfg.symbols
    frames = {s: load_bars(s, args.days, cfg, args.source) for s in symbols}
    frames = {s: df for s, df in frames.items() if not df.empty}
    if not frames:
        raise SystemExit("No price data loaded. Check your internet connection or try --source alpaca.")
    market = None
    if cfg.market_filter:
        market = frames.get(cfg.market_filter)
        if market is None:
            market = load_bars(cfg.market_filter, args.days, cfg, args.source)

    table = compare(frames, cfg, args.strategies.split(","), args.cash, market)
    print(f"\nSymbols: {', '.join(frames)} | {args.days} days of {cfg.bar_minutes}-min bars\n")
    print(table.to_string(formatters={
        "win_rate": "{:.1%}".format,
        "profit_factor": "{:.2f}".format,
        "total_return": "{:+.2%}".format,
        "max_drawdown": "{:.2%}".format,
        "avg_trade": "${:,.2f}".format,
        "fees": "${:,.2f}".format,
    }))
    print(f"\nAll P&L is after sell-side regulatory fees and {cfg.slippage_bps:g} bps slippage on every fill.")
    thin = table.index[table["trades"] < 30].tolist()
    if thin:
        print(f"\nFewer than 30 trades, so these rows are noise: {', '.join(thin)}")
    print("\nA profit factor under 1.3 is not an edge worth trading. Expect paper results to be worse.")
    table.to_csv(args.out)
    print(f"Table written to {args.out}")


if __name__ == "__main__":
    main()
