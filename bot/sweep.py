"""Try a grid of settings on top of your current .env, scored in- and out-of-sample.

    python -m bot.sweep --set ORB_TARGET_R=1.25,1.5,1.75 --set ORB_GAP_MIN_PCT=0,0.5
    python -m bot.sweep --symbols AMZN,GOOGL,META --label new-stocks

Every combination of the --set values runs once (in parallel) over the same
history as bot.research, using the same data cache. With no --set it runs
your current settings only, which is how you test them on new symbols.
Writes reports/sweep_<date>_<label>.md and .csv. Never touches .env.
"""
from __future__ import annotations

import argparse
import dataclasses
import itertools
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import Settings
from .research import HEADER, _init, describe, evaluate, load_cached, row


def parse_sets(sets: list[str], base: Settings) -> list[dict]:
    """--set NAME=a,b,c → every combination as {field: typed value}."""
    axes = []
    for item in sets:
        name, _, values = item.partition("=")
        field = name.strip().lower()
        if not hasattr(base, field):
            raise SystemExit(f"Unknown setting {name}. It must match a setting in .env.example.")
        kind = type(getattr(base, field))
        conv = (lambda v: v.strip().lower() in {"1", "true", "yes", "on"}) if kind is bool else kind
        axes.append([(field, conv(v)) for v in values.split(",")])
    return [dict(combo) for combo in itertools.product(*axes)] if axes else [{}]


def main() -> None:
    ap = argparse.ArgumentParser(description="Grid-test settings in- and out-of-sample")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=a,b,c")
    ap.add_argument("--days", type=int, default=1095)
    ap.add_argument("--source", default="alpaca")
    ap.add_argument("--cash", type=float, default=5_000)
    ap.add_argument("--symbols", default=None, help="comma list; defaults to SYMBOLS from .env")
    ap.add_argument("--oos", type=float, default=1 / 3)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--cache", default="data_cache")
    ap.add_argument("--label", default="sweep")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)

    base = Settings()
    combos = parse_sets(args.set, base)
    symbols = args.symbols.split(",") if args.symbols else base.symbols
    print(f"Loading bars for {', '.join(symbols)}...")
    frames = load_cached(symbols, args.days, base, args.source, Path(args.cache))
    market = frames.get("SPY")
    if market is None:
        market = load_cached(["SPY"], args.days, base, args.source, Path(args.cache)).get("SPY")
    start = min(df.index[0] for df in frames.values())
    end = max(df.index[-1] for df in frames.values())
    split = start + (end - start) * (1 - args.oos)
    print(f"Running {len(combos)} backtest(s)...")
    with ProcessPoolExecutor(args.workers, initializer=_init, initargs=(frames, market, split, args.cash)) as pool:
        results = list(pool.map(evaluate, [dataclasses.replace(base, **c) for c in combos]))

    order = sorted(range(len(combos)), key=lambda i: -results[i]["oos"]["pnl"])
    out = [
        f"# Sweep: {args.label}, {datetime.now():%Y-%m-%d}",
        "",
        f"{', '.join(frames)} | ${args.cash:,.0f} | in-sample {start:%Y-%m-%d} to {split:%Y-%m-%d}, "
        f"out-of-sample {split:%Y-%m-%d} to {end:%Y-%m-%d} | strategy {base.strategy}, on top of your .env",
        "",
        HEADER,
    ] + [row(describe(combos[i]) if combos[i] else "Your current settings", results[i]) for i in order]
    text = "\n".join(out)
    print("\n" + text)
    Path("reports").mkdir(exist_ok=True)
    stem = Path("reports") / f"sweep_{datetime.now():%Y-%m-%d}_{args.label}"
    stem.with_suffix(".md").write_text(text, encoding="utf-8")
    pd.DataFrame([
        {**{k.upper(): v for k, v in combos[i].items()},
         **{f"is_{k}": v for k, v in results[i]["is"].items()},
         **{f"oos_{k}": v for k, v in results[i]["oos"].items()}, "max_dd": results[i]["max_dd"]}
        for i in order
    ]).to_csv(stem.with_suffix(".csv"), index=False)
    print(f"\nSaved to {stem.with_suffix('.md').resolve()}")


if __name__ == "__main__":
    main()
