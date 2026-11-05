"""Which stocks does bot 1's ORB actually work on? Runs bot 1's own settings (.env) on each symbol by itself,
then on the set that did well in-sample only, checked on the out-of-sample part it never saw.

    python -m bot.symbol_scan --symbols AAPL,MSFT,... --days 1095

Read-only (market data only). Writes reports/symbol_scan_<date>.md.
"""
from __future__ import annotations

import argparse
import dataclasses
import logging
from datetime import datetime
from pathlib import Path

from . import research as rs
from .config import Settings


def main() -> None:
    ap = argparse.ArgumentParser(description="Bot 1's ORB on each symbol")
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--days", type=int, default=1095)
    ap.add_argument("--cash", type=float, default=5_000)
    ap.add_argument("--oos", type=float, default=1 / 3)
    ap.add_argument("--min-pf", type=float, default=1.15, help="in-sample PF a symbol needs to make the picked set")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    cfg = dataclasses.replace(Settings(), strategy="orb")
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    frames = rs.load_cached(sorted(set(symbols) | {"SPY"}), args.days, cfg, "alpaca", Path("data_cache"))
    market = frames["SPY"]
    start = min(df.index[0] for df in frames.values())
    end = max(df.index[-1] for df in frames.values())
    split = start + (end - start) * (1 - args.oos)
    out = [f"# Bot 1 ORB, symbol by symbol, {datetime.now():%Y-%m-%d}", "",
           f"Bot 1's current settings (strategy orb, {cfg.bar_minutes}-min bars, {cfg.slippage_bps:g} bps slippage, fees in). "
           f"In-sample {start:%Y-%m-%d} to {split:%Y-%m-%d}, out-of-sample {split:%Y-%m-%d} to {end:%Y-%m-%d}.", "",
           rs.HEADER]
    res = {}
    for s in symbols:
        if s not in frames:
            out.append(f"| {s} | no data | | | | | | |")
            continue
        rs._init({s: frames[s]}, market, split, args.cash)
        res[s] = rs.evaluate(cfg)
        out.append(rs.row(s, res[s]))
        print(out[-1], flush=True)
    picked = [s for s, r in res.items() if r["is"]["trades"] >= 10 and r["is"]["pf"] >= args.min_pf]
    current = [s for s in cfg.symbols if s in frames]
    out += ["", f"## Picked on in-sample only (PF >= {args.min_pf}, 10+ trades): {', '.join(picked) or 'none'}", "", rs.HEADER]
    for label, syms in (("Bot 1's current list (" + ",".join(current) + ")", current), ("Picked set", picked),
                        ("All scanned", list(res))):
        if syms:
            rs._init({s: frames[s] for s in syms}, market, split, args.cash)
            out.append(rs.row(label, rs.evaluate(cfg)))
    out += ["", "The out-of-sample columns are the honest test: the picked set was chosen without them."]
    Path("reports").mkdir(exist_ok=True)
    path = Path("reports") / f"symbol_scan_{datetime.now():%Y-%m-%d}.md"
    path.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
