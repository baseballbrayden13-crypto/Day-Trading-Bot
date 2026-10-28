"""Are some Kalshi prices reliably wrong? Price vs. how often YES actually won, after fees.

    python -m bot.kalshi_calibration --days 60 --hours-before 24 --series KXBTCD,KXHIGHNY,KXNBAGAME

For every settled binary market in the chosen series (or everything, if --series is empty), it reads
the YES bid and ask --hours-before the close (hourly candles), then groups markets by price in 5c
buckets and compares the price with how often YES really won. For each bucket it shows what buying
YES at the ask, or NO at 1 - the YES bid, would have made per contract after Kalshi's taker fee.

It splits the markets into an earlier and a later half by close time. A bucket is only worth a
paper test if it pays in both halves, on enough markets from enough different events (markets in
one event move together, so 50 rungs of one ladder count as about one bet), and clearly more than
luck: its t-stat (average profit / its standard error) must be at least --min-t. With 20 buckets x 2
sides, a couple will look good by chance at t ~ 1.5. --by-series repeats the table per series so a
flag driven by one series shows up. Public data only.
"""
from __future__ import annotations

import argparse
import csv
import math
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

        def profits(sub, side):
            if side == "yes":
                return [int(r["won"]) - r["ask"] - fee(1, r["ask"]) for r in sub]
            return [int(not r["won"]) - (1 - r["bid"]) - fee(1, 1 - r["bid"]) for r in sub]

        def ev(sub, side):
            return sum(profits(sub, side), D(0)) / len(sub) if sub else None

        early, late = [r for r in g if r["close"] < cut], [r for r in g if r["close"] >= cut]
        out.append({
            "bucket": f"{b:.2f}-{b + BUCKET:.2f}", "markets": len(g), "events": len({r["event"] for r in g}),
            "avg_ask": f"{sum((r['ask'] for r in g), D(0)) / len(g):.3f}",
            "yes_won": f"{sum(r['won'] for r in g) / len(g):.3f}",
            **{f"{side}_ev{tag}": (f"{v:+.3f}" if v is not None else "")
               for side in ("yes", "no") for tag, sub in (("", g), ("_early", early), ("_late", late))
               for v in [ev(sub, side)]},
            **{f"{side}_t": f"{t_stat(profits(g, side), [r['ask'] if side == 'yes' else 1 - r['bid'] for r in g]):.1f}"
               for side in ("yes", "no")},
        })
    return out


def t_stat(xs: list, prices: list | None = None) -> float:
    """Average profit / its standard error, for bets that pay $1 or $0 at a given price. With `prices`
    (what each contract cost, fees aside) the error comes from the price: if the price were fair, a
    contract's profit has stdev sqrt(p(1-p)). That stays honest when every bet in a bucket lost or
    won (the sample stdev would be zero and the t-stat would blow up). Above ~2 is unlikely to be luck."""
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(float(x) for x in xs) / n
    if prices:
        p = min(max(sum(float(q) for q in prices) / len(prices), 0.02), 0.98)
        sd = math.sqrt(p * (1 - p))
    else:
        sd = math.sqrt(sum((float(x) - m) ** 2 for x in xs) / (n - 1))
    return m / (sd / math.sqrt(n)) if sd else 0.0


def promising(row: dict, side: str, min_ev: Decimal, min_events: int, min_t: float = 0.0) -> bool:
    vals = [row.get(f"{side}_ev{t}") for t in ("", "_early", "_late")]
    return (row["events"] >= min_events and float(row.get(f"{side}_t") or 0) >= min_t
            and all(v not in (None, "") and D(v) >= min_ev for v in vals))


def main() -> None:
    ap = argparse.ArgumentParser(description="Kalshi price vs. outcome, after fees")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--hours-before", type=int, default=24, help="read prices this long before the close")
    ap.add_argument("--series", default="", help="comma list; empty = everything (capped by --max-events)")
    ap.add_argument("--max-events", type=int, default=400, help="per series")
    ap.add_argument("--min-ev", type=D, default=D("0.02"), help="per-contract profit after fees to flag a bucket")
    ap.add_argument("--min-events", type=int, default=30)
    ap.add_argument("--min-t", type=float, default=2.0, help="t-stat needed to flag (2 ~ unlikely to be luck)")
    ap.add_argument("--by-series", action="store_true", help="also print each series' flagged buckets")
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
    def show(table, title):
        print(f"\n{title}\n{'bucket':12} {'mkts':>5} {'evts':>5} {'ask':>6} {'won':>6} {'YES ev':>7} {'t':>5} "
              f"{'NO ev':>7} {'t':>5}  (per contract, after fees)")
        for r in table:
            flag = " <- YES" if promising(r, "yes", args.min_ev, args.min_events, args.min_t) else \
                   " <- NO" if promising(r, "no", args.min_ev, args.min_events, args.min_t) else ""
            print(f"{r['bucket']:12} {r['markets']:5} {r['events']:5} {r['avg_ask']:>6} {r['yes_won']:>6} "
                  f"{r['yes_ev']:>7} {r['yes_t']:>5} {r['no_ev']:>7} {r['no_t']:>5}{flag}")

    show(table, "All series")
    if args.by_series:
        for name in sorted({r["series"] for r in rows}):
            show(summarize([r for r in rows if r["series"] == name]), name)
    print(f"\nFlagged = at least +${args.min_ev} a contract overall AND in both halves, over {args.min_events}+ events, "
          f"t-stat {args.min_t}+. Testing 40 bucket/side pairs, expect about one false flag at t 2.")
    print(f"Saved to {path}")


if __name__ == "__main__":
    main()
