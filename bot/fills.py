"""Fill tracker:  python -m bot.fills [--days 30]

The backtest assumes each fill costs 2 bps (0.02%) of slippage, and the tuned ORB
breaks even at about 5 bps. This compares the price the bot wanted (the signal bar's
close, logged by bot.live to fills/signals.csv) with what Alpaca actually filled,
for every entry, and checks stop exits against the stop price. Read-only.
Writes reports/fills_<date>.csv.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Settings

ET = ZoneInfo("America/New_York")
SIGNALS = Path("fills") / "signals.csv"
FIELDS = ["time", "symbol", "qty", "wanted", "stop", "target", "order_id"]
BACKTEST_BPS, BREAK_EVEN_BPS = 2.0, 5.0


def log_order(symbol: str, qty: int, wanted: float, stop: float, target: float, order_id: str,
              path: Path = SIGNALS) -> None:
    """Called by bot.live right after it submits an order."""
    path.parent.mkdir(exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS)
        if new:
            w.writeheader()
        w.writerow({"time": datetime.now(ET).isoformat(timespec="seconds"), "symbol": symbol, "qty": qty,
                    "wanted": round(wanted, 4), "stop": round(stop, 4), "target": round(target, 4),
                    "order_id": order_id})


def slippage_bps(wanted: float, got: float, side: str) -> float:
    """Positive = cost. Buying above the wanted price or selling below it costs money."""
    diff = (got - wanted) if side == "buy" else (wanted - got)
    return diff / wanted * 10_000


def check(rows: list[dict], get_order) -> list[dict]:
    """get_order(order_id) -> Alpaca order with legs. Returns one row per filled entry."""
    out = []
    for r in rows:
        o = get_order(r["order_id"])
        if not o.filled_avg_price:
            continue
        entry = float(o.filled_avg_price)
        row = {"time": r["time"], "symbol": r["symbol"], "qty": r["qty"], "wanted": float(r["wanted"]),
               "entry_fill": entry, "entry_bps": round(slippage_bps(float(r["wanted"]), entry, "buy"), 2),
               "exit": "", "exit_fill": "", "exit_bps": ""}
        for leg in o.legs or []:
            if not leg.filled_avg_price:
                continue
            px = float(leg.filled_avg_price)
            row["exit_fill"] = px
            if "stop" in str(leg.order_type).lower():
                row["exit"] = "stop"
                row["exit_bps"] = round(slippage_bps(float(r["stop"]), px, "sell"), 2)
            else:
                row["exit"] = "target"  # limit orders can't fill worse than the target
                row["exit_bps"] = round(slippage_bps(float(r["target"]), px, "sell"), 2)
        out.append(row)
    return out


def summary(rows: list[dict]) -> str:
    if not rows:
        return "No filled entries yet."
    fills = [r["entry_bps"] for r in rows] + [r["exit_bps"] for r in rows if r["exit"] == "stop"]
    avg = sum(fills) / len(fills)
    lines = [f"{len(rows)} entries, {sum(r['exit'] == 'stop' for r in rows)} stop exits checked.",
             f"Average slippage: {avg:+.1f} bps per fill (backtest assumes {BACKTEST_BPS:g}, "
             f"break-even is about {BREAK_EVEN_BPS:g})."]
    if avg <= BACKTEST_BPS:
        lines.append("Fills are as good as the backtest assumed.")
    elif avg < BREAK_EVEN_BPS:
        lines.append("Fills are worse than the backtest assumed, but still under break-even.")
    else:
        lines.append("Fills are at or past break-even: the edge is likely gone at these costs.")
    if len(fills) < 20:
        lines.append("Under 20 fills, so this is still noisy.")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare wanted prices with actual fills")
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()
    if not SIGNALS.exists():
        print(f"No {SIGNALS} yet. bot.live writes it when it places its first order.")
        return
    from .broker import Broker

    broker = Broker(Settings())
    since = datetime.now(ET) - timedelta(days=args.days)
    with SIGNALS.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if datetime.fromisoformat(r["time"]) >= since]
    result = check(rows, lambda oid: broker.client.get_order_by_id(oid, nested=True))
    for r in result:
        print(f"{r['time'][:16]}  {r['symbol']:<5} wanted {r['wanted']:>9.2f}  got {r['entry_fill']:>9.2f}  "
              f"{r['entry_bps']:+6.1f} bps" + (f"  | {r['exit']} {r['exit_bps']:+.1f} bps" if r["exit"] else ""))
    print()
    print(summary(result))
    if result:
        Path("reports").mkdir(exist_ok=True)
        path = Path("reports") / f"fills_{datetime.now(ET):%Y-%m-%d}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, list(result[0]))
            w.writeheader()
            w.writerows(result)
        print(f"\nSaved to {path.resolve()}")


if __name__ == "__main__":
    main()
