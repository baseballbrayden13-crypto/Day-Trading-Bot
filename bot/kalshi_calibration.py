"""Are some Kalshi prices reliably wrong? Price vs. how often YES actually won, after fees.

    python -m bot.kalshi_calibration --days 60 --hours-before 24 --series KXBTCD,KXHIGHNY,KXNBAGAME

For every settled binary market in the chosen series (or everything, if --series is empty), it reads
the YES bid and ask --hours-before the close (hourly candles), then groups markets by price in 5c
buckets and compares the price with how often YES really won. For each bucket it shows what buying
YES at the ask, or NO at 1 - the YES bid, would have made per contract after Kalshi's taker fee.

It splits the markets into an earlier and a later half by close time. A bucket is only worth a
paper test if it pays in both halves, on enough markets from enough different events (markets in
one event move together, so 50 rungs of one ladder count as about one bet). Public data only.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .kalshi import D, fee
from .kalshi_backtest import candles, settled_events
from .kalshi_live import Kalshi

BUCKET = D("0.05")


def quote_before(cs: list[dict], ts: int) -> tuple[Decimal, Decimal] | None:
    """Last (bid, ask) at or before ts, both strictly between 0 and 1."""
    best = None
    for c in cs:
        if c.get("end_period_ts", 0) > ts:
            break
        bid = (c.get("yes_bid") or {}).get("close_dollars")
        ask = (c.get("yes_ask") or {}).get("close_dollars")
        if bid and ask and 0 < D(bid) < 1 and 0 < D(ask) < 1:
            best = (D(bid), D(ask))
    return best


def bucket_of(price: Decimal) -> Decimal:
    return (price / BUCKET).to_integral_value(rounding="ROUND_FLOOR") * BUCKET


def summarize(rows: list[dict]) -> list[dict]:
    """Per price bucket: markets, events, YES win rate, and per-contract profit after fees of buying
    YES at the ask or NO at 1 - bid, overall and in the earlier/later half."""
    if not rows:
        return []
    cut = sorted(r["close"] for r in rows)[len(rows) // 2]
    groups = defaultdict(list)
    for r in rows:
        groups[bucket_of(r["ask"])].append(r)
    out = []
    for b in sorted(groups):
        g = groups[b]

        def ev(sub, side):
            if not sub:
                return None
            if side == "yes":
                return sum((int(r["won"]) - r["ask"] - fee(1, r["ask"]) for r in sub), D(0)) / len(sub)
            return sum((int(not r["won"]) - (1 - r["bid"]) - fee(1, 1 - r["bid"]) for r in sub), D(0)) / len(sub)

        early, late = [r for r in g if r["close"] < cut], [r for r in g if r["close"] >= cut]
        out.append({
            "bucket": f"{b:.2f}-{b + BUCKET:.2f}", "markets": len(g), "events": len({r["event"] for r in g}),
            "avg_ask": f"{sum((r['ask'] for r in g), D(0)) / len(g):.3f}",
            "yes_won": f"{sum(r['won'] for r in g) / len(g):.3f}",
            **{f"{side}_ev{tag}": (f"{v:+.3f}" if v is not None else "")
               for side in ("yes", "no") for tag, sub in (("", g), ("_early", early), ("_late", late))
               for v in [ev(sub, side)]},
        })
    return out


def promising(row: dict, side: str, min_ev: Decimal, min_events: int) -> bool:
    vals = [row.get(f"{side}_ev{t}") for t in ("", "_early", "_late")]
    return row["events"] >= min_events and all(v not in (None, "") and D(v) >= min_ev for v in vals)


def main() -> None:
    ap = argparse.ArgumentParser(description="Kalshi price vs. outcome, after fees")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--hours-before", type=int, default=24, help="read prices this long before the close")
    ap.add_argument("--series", default="", help="comma list; empty = everything (capped by --max-events)")
    ap.add_argument("--max-events", type=int, default=400, help="per series")
    ap.add_argument("--min-ev", type=D, default=D("0.02"), help="per-contract profit after fees to flag a bucket")
    ap.add_argument("--min-events", type=int, default=30)
    args = ap.parse_args()
    api = Kalshi("prod")
    names = [s.strip() for s in args.series.split(",") if s.strip()] or [""]
    events = [e for n in names for e in settled_events(api, args.days, args.max_events, n)]
    print(f"{len(events)} settled events")

    rows = []
    for e in events:
        markets = [m for m in e.get("markets", []) if m.get("result") in ("yes", "no") and m.get("close_time")]
        if not markets:
            continue
        close = max(datetime.fromisoformat(m["close_time"].replace("Z", "+00:00")) for m in markets)
        at = int((close - timedelta(hours=args.hours_before)).timestamp())
        try:
            hist = candles(api, [m["ticker"] for m in markets], at - 6 * 3600, at, 60)
        except RuntimeError as err:
            print(f"skip {e['event_ticker']}: {err}")
            continue
        for m in markets:
            q = quote_before(hist.get(m["ticker"], []), at)
            if q:
                rows.append({"event": e["event_ticker"], "series": e.get("series_ticker", ""), "ticker": m["ticker"],
                             "bid": q[0], "ask": q[1], "won": m["result"] == "yes", "close": close.isoformat()})
    print(f"{len(rows)} markets with a quote {args.hours_before}h before close")

    table = summarize(rows)
    out = Path("reports")
    out.mkdir(exist_ok=True)
    path = out / f"kalshi_calibration_{datetime.now():%Y-%m-%d_%H%M}.csv"
    if table:
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(table[0]))
            w.writeheader()
            w.writerows(table)
    print(f"\n{'bucket':12} {'mkts':>5} {'evts':>5} {'ask':>6} {'won':>6} {'YES ev':>7} {'NO ev':>7}  (per contract, after fees)")
    for r in table:
        flag = " <- YES" if promising(r, "yes", args.min_ev, args.min_events) else \
               " <- NO" if promising(r, "no", args.min_ev, args.min_events) else ""
        print(f"{r['bucket']:12} {r['markets']:5} {r['events']:5} {r['avg_ask']:>6} {r['yes_won']:>6} "
              f"{r['yes_ev']:>7} {r['no_ev']:>7}{flag}")
    print(f"\nFlagged = at least +${args.min_ev} a contract overall AND in both halves, over {args.min_events}+ events.")
    print(f"Saved to {path}")


if __name__ == "__main__":
    main()
