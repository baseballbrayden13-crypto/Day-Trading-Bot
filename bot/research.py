"""Find out which parts of ORB help, and how every strategy holds up on unseen data.

    python -m bot.research --source alpaca --days 1095 --cash 5000

It downloads the bars once (cached in data_cache/), then:

1. Parts:     tests each ORB option on its own against your current ORB settings.
2. Keep/drop: starting from your settings, walks through the options and keeps a
              change only if it improves the first part of the history (in-sample).
3. Check:     shows the kept settings on the most recent part (out-of-sample),
              which played no part in choosing them. That's the honest number.
4. Strategies: runs every strategy in STRATEGIES on the same split.

Everything is after fees and slippage. It never touches .env; it prints the
settings to copy in if you decide to use them. Writes reports/research_<date>.md.
"""
from __future__ import annotations

import argparse
import dataclasses
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

import pandas as pd

from .backtest import run_backtest
from .config import Settings
from .data import load_bars
from .strategy import STRATEGIES

# Each option of ORB, and the values to try. The first value in each list is "off"
# (or the usual setting), so the report reads as "what happens if I add this".
ORB_OPTIONS: dict[str, list[dict]] = {
    "range length": [{"orb_minutes": 15}, {"orb_minutes": 5, "no_entry_first_minutes": 5}, {"orb_minutes": 30}],
    "target": [{"orb_target_r": r} for r in (1.0, 1.5, 2.0, 3.0)],
    "last entry": [{"orb_last_entry": t} for t in ("", "10:30", "11:30", "13:00")],
    "breakouts per day": [{"orb_max_per_day": 1}, {"orb_max_per_day": 2}],
    "stop": [{"orb_stop": "low"}, {"orb_stop": "mid"}],
    "market filter (SPY above VWAP)": [{"market_filter": ""}, {"market_filter": "SPY"}],
    "VWAP filter": [{"orb_vwap_filter": False}, {"orb_vwap_filter": True}],
    "volume filter": [{"orb_volume_mult": m} for m in (0.0, 1.5, 2.0)],
    "max range width": [{"orb_max_range_pct": p} for p in (0.0, 1.0, 0.5)],
    "gap direction": [{"orb_gap": g} for g in ("any", "up", "down")],
}
MIN_TRADES = 100  # in-sample trades a setting needs before we believe it

_FRAMES: dict[str, pd.DataFrame] = {}
_MARKET: pd.DataFrame | None = None
_SPLIT: pd.Timestamp | None = None
_CASH = 5_000.0


def _init(frames, market, split, cash):
    global _FRAMES, _MARKET, _SPLIT, _CASH
    _FRAMES, _MARKET, _SPLIT, _CASH = frames, market, split, cash


def _stats(trades: pd.DataFrame, cash: float) -> dict:
    if not len(trades):
        return {"trades": 0, "win_rate": 0.0, "pf": 0.0, "pnl": 0.0, "return": 0.0}
    wins, losses = trades[trades["pnl"] > 0]["pnl"].sum(), -trades[trades["pnl"] <= 0]["pnl"].sum()
    return {
        "trades": len(trades),
        "win_rate": (trades["pnl"] > 0).mean(),
        "pf": wins / losses if losses else float("inf"),
        "pnl": trades["pnl"].sum(),
        "return": trades["pnl"].sum() / cash,
    }


def evaluate(cfg: Settings) -> dict:
    """One backtest over the whole history, scored separately before and after the split."""
    res = run_backtest(_FRAMES, cfg, _CASH, market=_MARKET if cfg.market_filter == "SPY" else None)
    log = res["trade_log"]
    is_log = log[log["entry_time"] < _SPLIT] if len(log) else log
    oos_log = log[log["entry_time"] >= _SPLIT] if len(log) else log
    return {"is": _stats(is_log, _CASH), "oos": _stats(oos_log, _CASH), "max_dd": res["max_drawdown"]}


def run_many(pool: ProcessPoolExecutor, cfgs: list[Settings]) -> list[dict]:
    return list(pool.map(evaluate, cfgs))


def better(new: dict, old: dict) -> bool:
    """Keep a change only if it makes more money in-sample without lowering the profit factor."""
    n, o = new["is"], old["is"]
    return n["trades"] >= MIN_TRADES and n["pnl"] > o["pnl"] and n["pf"] >= o["pf"] - 0.01


def describe(overrides: dict) -> str:
    return ", ".join(f"{k.upper()}={v}" for k, v in overrides.items()) or "(no change)"


def row(label: str, r: dict) -> str:
    i, o = r["is"], r["oos"]
    return (f"| {label} | {i['trades']} | {i['pf']:.2f} | ${i['pnl']:,.0f} | "
            f"{o['trades']} | {o['pf']:.2f} | ${o['pnl']:,.0f} | {r['max_dd']:.1%} |")


HEADER = ("| | In-sample trades | PF | P&L | Out-of-sample trades | PF | P&L | Max drawdown |\n"
          "|---|---|---|---|---|---|---|---|")


def load_cached(symbols: list[str], days: int, cfg: Settings, source: str, cache: Path) -> dict[str, pd.DataFrame]:
    cache.mkdir(exist_ok=True)
    frames = {}
    for s in symbols:
        path = cache / f"{s}_{cfg.bar_minutes}m_{days}d.pkl"
        if path.exists():
            frames[s] = pd.read_pickle(path)
        else:
            frames[s] = load_bars(s, days, cfg, source)
            if not frames[s].empty:
                frames[s].to_pickle(path)
        print(f"  {s}: {len(frames[s]):,} bars" + (" (cached)" if path.exists() else ""))
    return {s: df for s, df in frames.items() if not df.empty}


def main() -> None:
    ap = argparse.ArgumentParser(description="Test ORB's parts and every strategy on in- and out-of-sample data")
    ap.add_argument("--days", type=int, default=1095)
    ap.add_argument("--source", default="alpaca", help="alpaca, yfinance, or a path to a .csv")
    ap.add_argument("--cash", type=float, default=5_000)
    ap.add_argument("--symbols", default=None, help="comma list; defaults to SYMBOLS from .env")
    ap.add_argument("--oos", type=float, default=1 / 3, help="share of the history held back for the final check")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--cache", default="data_cache")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)

    base = dataclasses.replace(Settings(), strategy="orb")
    symbols = args.symbols.split(",") if args.symbols else base.symbols
    print("Loading bars...")
    frames = load_cached(symbols, args.days, base, args.source, Path(args.cache))
    market = frames.get("SPY")
    if market is None:  # the market filter option needs SPY even if you don't trade it
        market = load_cached(["SPY"], args.days, base, args.source, Path(args.cache)).get("SPY")
    start = min(df.index[0] for df in frames.values())
    end = max(df.index[-1] for df in frames.values())
    split = start + (end - start) * (1 - args.oos)
    out = [
        f"# Strategy research, {datetime.now():%Y-%m-%d}",
        "",
        f"{', '.join(frames)} | {base.bar_minutes}-min bars | ${args.cash:,.0f} starting cash | "
        f"in-sample {start:%Y-%m-%d} to {split:%Y-%m-%d}, out-of-sample {split:%Y-%m-%d} to {end:%Y-%m-%d}.",
        f"All P&L is after sell-side fees and {base.slippage_bps:g} bps slippage per fill. PF = profit factor.",
        "",
    ]

    def show(line: str = ""):
        print(line)
        out.append(line)

    with ProcessPoolExecutor(args.workers, initializer=_init, initargs=(frames, market, split, args.cash)) as pool:
        # 1. Each ORB option on its own
        show("## 1. ORB options one at a time (vs your current settings)")
        show()
        baseline = evaluate_in(pool, base)
        show(HEADER)
        show(row("**Your current ORB**", baseline))
        variants = [(name, ov) for name, values in ORB_OPTIONS.items() for ov in values
                    if any(getattr(base, k) != v for k, v in ov.items())]
        results = run_many(pool, [dataclasses.replace(base, **ov) for _, ov in variants])
        for (name, ov), r in zip(variants, results):
            show(row(f"{name}: {describe(ov)}", r))
        show()

        # 2. Greedy keep/drop on in-sample only
        show("## 2. Keep what helps, drop what hurts (chosen on in-sample only)")
        show()
        current, cur_res, kept = base, baseline, {}
        order = sorted(ORB_OPTIONS, key=lambda n: -max(
            (r["is"]["pnl"] for (nm, _), r in zip(variants, results) if nm == n), default=0))
        for name in order:
            values = [ov for ov in ORB_OPTIONS[name] if any(getattr(current, k) != v for k, v in ov.items())]
            if not values:
                continue
            trials = run_many(pool, [dataclasses.replace(current, **ov) for ov in values])
            best = max(zip(values, trials), key=lambda t: t[1]["is"]["pnl"])
            if better(best[1], cur_res):
                current, cur_res = dataclasses.replace(current, **best[0]), best[1]
                kept.update(best[0])
                show(f"- **Kept** {name}: {describe(best[0])} (in-sample P&L ${best[1]['is']['pnl']:,.0f}, PF {best[1]['is']['pf']:.2f})")
            else:
                show(f"- Dropped {name}: no value beat the current setup in-sample")
        show()
        show("## 3. The honest check: tuned ORB on data it never saw")
        show()
        show(HEADER)
        show(row("Your current ORB", baseline))
        show(row("Tuned ORB", cur_res))
        show()
        o_new, o_old = cur_res["oos"], baseline["oos"]
        if not kept:
            show("Nothing beat your current settings, so there is nothing to change.")
        elif o_new["pnl"] > o_old["pnl"] and o_new["pf"] >= o_old["pf"]:
            show("The tuned settings also did better out-of-sample, so the improvement looks real.")
        else:
            show("The tuned settings did NOT hold up out-of-sample. The gain was fitted to the past; don't use them.")
        if o_new["trades"] < 100:
            show(f"Only {o_new['trades']} out-of-sample trades, so treat this as preliminary.")
        show()
        if kept:
            show("Settings to put in .env if you use them:")
            show()
            show("```")
            for k, v in kept.items():
                show(f"{k.upper()}={v}")
            show("```")
            show()

        # 4. Every strategy
        show("## 4. Every strategy (default settings), same split")
        show()
        names = [n for n in STRATEGIES if n != "orb"]
        strat_res = run_many(pool, [dataclasses.replace(Settings(), strategy=n) for n in names])
        rows = [("orb (your current)", baseline)] + ([("orb (tuned)", cur_res)] if kept else []) + list(zip(names, strat_res))
        show(HEADER)
        for label, r in sorted(rows, key=lambda t: -t[1]["oos"]["pnl"]):
            show(row(label, r))
        show()
        show("A profit factor under 1.3 out-of-sample is not an edge worth trading with real money.")

    Path("reports").mkdir(exist_ok=True)
    path = Path("reports") / f"research_{datetime.now():%Y-%m-%d}.md"
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"\nSaved to {path.resolve()}")


def evaluate_in(pool: ProcessPoolExecutor, cfg: Settings) -> dict:
    return pool.submit(evaluate, cfg).result()


if __name__ == "__main__":
    main()
