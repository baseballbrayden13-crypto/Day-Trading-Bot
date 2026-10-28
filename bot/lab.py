"""Lab, the research helper: once a week, re-tests every bot's strategy on the newest data and asks
"is the edge fading?", then runs one queued experiment.

    python -m bot.lab                 # all of it (the Saturday task)
    python -m bot.lab --no-queue      # skip the queued experiment

For each bot, with fresh data (cached per week in data_cache/lab_<year-week>/), after fees:

    Bot 1 (ORB)       your current .env settings over 3 years of 5-minute bars, scored on the last
                      90 days, the last year, and the two years before. "Fading" when the last year's
                      profit factor is under 1.0 or under 70% of the earlier years'.
    Bot 2 (rotation)  top 3 / 3 months over 20 years of daily bars: the last year vs holding SPY.
    Bot 3 (crypto)    50-day trend on BTC and ETH: the last year vs holding them.

Queued experiments live in fleet_data/lab_queue.txt, one bot.sweep command line per line, e.g.
    --set ORB_TARGET_R=1.25,1.5 --label target
Lab runs the first one that isn't marked done, then marks it "# done <date>". Results land in
reports/ like any sweep. Nothing is ever applied: a winner becomes a Proposed row.

Writes fleet_data/lab.md and lab.csv.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

OUT = Path("fleet_data")


def pf(pnl: pd.Series) -> float:
    won, lost = pnl[pnl > 0].sum(), -pnl[pnl <= 0].sum()
    return float(won / lost) if lost else (float("inf") if won else 0.0)


def windows(log: pd.DataFrame, end: pd.Timestamp) -> list[dict]:
    """Profit factor and P&L of the trade log in the last 90 days, the last year, and before that."""
    out = []
    if not len(log):
        return out
    t = pd.to_datetime(log["entry_time"], utc=True)
    for name, lo, hi in (("last 90 days", end - pd.Timedelta(days=90), end), ("last year", end - pd.Timedelta(days=365), end),
                         ("before that", t.min(), end - pd.Timedelta(days=365))):
        part = log[(t >= lo) & (t < hi)] if name != "before that" else log[t < hi]
        out.append({"window": name, "trades": len(part), "pf": round(pf(part["pnl"]), 2) if len(part) else 0.0,
                    "pnl": round(float(part["pnl"].sum()), 2)})
    return out


def orb_verdict(rows: list[dict]) -> str:
    by = {r["window"]: r for r in rows}
    last, before = by.get("last year"), by.get("before that")
    if not last or last["trades"] < 30:
        return "too few trades to judge"
    if last["pf"] < 1.0:
        return "FADING: lost money over the last year"
    if before and before["trades"] >= 30 and last["pf"] < 0.7 * before["pf"]:
        return "FADING: last year's profit factor is well under the earlier years'"
    return "holding up"


def bot1(cache: Path, loader=None, cash: float = 5_000) -> tuple[list[dict], str]:
    from .backtest import run_backtest
    from .config import Settings
    from .research import load_cached

    cfg = Settings()
    syms = list(dict.fromkeys(cfg.symbols + ([cfg.market_filter] if cfg.market_filter else [])))
    frames = loader(syms) if loader else load_cached(syms, 1095, cfg, "alpaca", cache)
    market = frames.get(cfg.market_filter) if cfg.market_filter else None
    res = run_backtest({s: frames[s] for s in cfg.symbols if s in frames}, cfg, cash, market=market)
    end = max(df.index[-1] for df in frames.values())
    rows = windows(res["trade_log"], end)
    return rows, orb_verdict(rows)


def yearly(eq: pd.Series) -> float:
    eq = eq.dropna()
    start = eq.index[-1] - pd.Timedelta(days=365)
    base = eq[eq.index <= start]
    return float(eq.iloc[-1] / (base.iloc[-1] if len(base) else eq.iloc[0]) - 1) * 100


def bot2(cache: Path, loader=None) -> tuple[list[dict], str]:
    from .config import Settings
    from .rotation import DEFAULT, run_rotation
    from .swing import daily_bars

    cfg = Settings(slippage_bps=5.0)
    syms = DEFAULT.split(",")
    frames = loader(syms) if loader else {s: daily_bars(s, 20, cfg, cache=cache, source="yfinance").dropna() for s in syms}
    frames = {s: df for s, df in frames.items() if len(df) > 300}
    eq = run_rotation(frames, cfg, top=3, lookback=3)
    mine, spy = yearly(eq), yearly(frames["SPY"]["close"])
    rows = [{"window": "last year", "trades": "", "pf": "", "pnl": round(mine, 1)},
            {"window": "last year, holding SPY", "trades": "", "pf": "", "pnl": round(spy, 1)}]
    verdict = ("behind SPY by more than 15 points this year (expected in strong markets: it trades return for smaller crashes)"
               if mine < spy - 15 else "in line with its design")
    return rows, verdict


def bot3(cache: Path, loader=None) -> tuple[list[dict], str]:
    from .config import Settings
    from .daily_rules import strategy_returns
    from .swing import daily_bars

    cfg = Settings()
    frames = loader(["BTC-USD", "ETH-USD"]) if loader else {s: daily_bars(s, 12, cfg, cache=cache, source="yfinance").dropna()
                                                            for s in ("BTC-USD", "ETH-USD")}
    rows, worse = [], 0
    for sym, df in frames.items():
        r = strategy_returns(df, "trend50", 0.0025)
        mine, hold = yearly((1 + r).cumprod()), yearly(df["close"])
        rows += [{"window": f"{sym} last year", "trades": "", "pf": "", "pnl": round(mine, 1)},
                 {"window": f"{sym} last year, holding", "trades": "", "pf": "", "pnl": round(hold, 1)}]
        worse += mine < hold - 25
    return rows, ("behind just holding on both coins by 25+ points" if worse == len(frames) else "in line with its design")


def next_experiment(queue: Path) -> tuple[int, str] | None:
    if not queue.exists():
        return None
    for i, line in enumerate(queue.read_text().splitlines()):
        if line.strip() and not line.lstrip().startswith("#"):
            return i, line.strip()
    return None


def mark_done(queue: Path, i: int, when: str) -> None:
    lines = queue.read_text().splitlines()
    lines[i] = f"# done {when}: {lines[i]}"
    queue.write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Lab: weekly re-test of every bot (read-only)")
    ap.add_argument("--no-queue", action="store_true")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    week = now.strftime("%G-%V")
    cache = Path("data_cache") / f"lab_{week}"
    cache.mkdir(parents=True, exist_ok=True)
    report = [f"# Lab, week {week} ({now:%Y-%m-%d})", "", "Fresh data, after fees. Nothing was changed.", ""]
    table = []
    for num, name, fn in ((1, "ORB day trader", bot1), (2, "ETF rotation", bot2), (3, "Crypto trend", bot3)):
        try:
            rows, verdict = fn(cache)
        except Exception as e:
            rows, verdict = [], f"couldn't test: {type(e).__name__}: {e}"[:200]
        report += [f"## Bot {num}: {name}: {verdict}", "", "| Window | Trades | Profit factor | P&L ($ for bot 1, % for 2-3) |", "|---|---|---|---|"]
        report += [f"| {r['window']} | {r['trades']} | {r['pf']} | {r['pnl']} |" for r in rows] + [""]
        table += [{"week": week, "bot": num, **r, "verdict": verdict} for r in rows] or [{"week": week, "bot": num, "verdict": verdict}]
    queue = OUT / "lab_queue.txt"
    nxt = None if args.no_queue else next_experiment(queue)
    if nxt:
        i, cmd = nxt
        report += [f"## Experiment: `{cmd}`", ""]
        done = subprocess.run([sys.executable, "-m", "bot.sweep", *cmd.split()], capture_output=True, text=True, timeout=6 * 3600)
        report += ["```", done.stdout[-3000:] or done.stderr[-2000:], "```", ""]
        mark_done(queue, i, f"{now:%Y-%m-%d}")
    else:
        report += ["No experiment queued. Add one line to fleet_data/lab_queue.txt, e.g. `--set ORB_TARGET_R=1.25,1.5 --label target`.", ""]
    OUT.mkdir(exist_ok=True)
    (OUT / "lab.md").write_text("\n".join(report), encoding="utf-8")
    with (OUT / "lab.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["week", "bot", "window", "trades", "pf", "pnl", "verdict"], extrasaction="ignore")
        w.writeheader()
        w.writerows(table)
    print("\n".join(report))
    fading = [r for r in table if str(r.get("verdict", "")).startswith(("FADING", "behind", "couldn't"))]
    if fading:
        from .alerts import notify

        notify("lab", "Lab: a strategy needs a look", "; ".join(sorted({f"Bot {r['bot']}: {r['verdict']}" for r in fading}))[:600], "watch")


if __name__ == "__main__":
    main()
