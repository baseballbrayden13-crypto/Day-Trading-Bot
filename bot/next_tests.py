"""Nov 10 2026 research for bot 1: trailing stops vs the fixed target, and adding big tech stocks.
Bot 1's own .env settings, 3 years of 5-min bars, fees and slippage in, limit entries as live. Read-only.

    python -m bot.next_tests --days 1095
"""
from __future__ import annotations

import argparse
import dataclasses
import logging
from pathlib import Path

from . import research as rs
from .config import Settings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1095)
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    base = dataclasses.replace(Settings(), strategy="orb")
    extra = ["TSLA", "GOOGL", "AMZN", "META", "AVGO", "AMD", "NFLX", "ORCL", "CRM", "ADBE", "QCOM"]
    frames = rs.load_cached(sorted(set(base.symbols) | set(extra) | {"SPY"}), a.days, base, "alpaca", Path("data_cache"))
    market = frames["SPY"]
    start, end = min(df.index[0] for df in frames.values()), max(df.index[-1] for df in frames.values())
    split = start + (end - start) * 2 / 3
    out = [f"# Bot 1 next tests ({start:%Y-%m-%d} to {end:%Y-%m-%d}, unseen from {split:%Y-%m-%d})", "",
           f"Current: target {base.orb_target_r}R, trail {base.stop_trail_r}, breakeven {base.stop_breakeven_r}, "
           f"symbols {','.join(base.symbols)}, {base.slippage_bps:g} bps slippage, limit entries {base.entry_limit_bps:g} bps.", ""]

    def run(label, cfg, syms):
        rs._init({s: frames[s] for s in syms if s in frames}, market, split, 5_000)
        out.append(rs.row(label, rs.evaluate(cfg)))
        print(out[-1], flush=True)

    out += ["## Exits (current symbols)", "", rs.HEADER]
    run("As running", base, base.symbols)
    for tgt in (base.orb_target_r, 2.0, 3.0, 50.0):
        for trail in (0.0, 0.5, 1.0, 1.5):
            if tgt == base.orb_target_r and trail == base.stop_trail_r:
                continue
            name = f"target {'none' if tgt >= 50 else f'{tgt:g}R'}, trail {trail:g}R" if trail else f"target {'none' if tgt >= 50 else f'{tgt:g}R'}, no trail"
            run(name, dataclasses.replace(base, orb_target_r=tgt, stop_trail_r=trail), base.symbols)
    out += ["", "## Adding big tech stocks (current exits)", "", rs.HEADER]
    run("Current 5", base, base.symbols)
    for s in extra:
        run(f"+ {s}", base, base.symbols + [s])
    run("+ TSLA, GOOGL", base, base.symbols + ["TSLA", "GOOGL"])
    run("+ all 11 big tech", base, base.symbols + extra)
    Path("reports").mkdir(exist_ok=True)
    Path("reports/bot1_next_tests.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
