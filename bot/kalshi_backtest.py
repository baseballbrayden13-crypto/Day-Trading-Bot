"""Replay recently settled Kalshi events to see how often locked-in trades showed up.

    python -m bot.kalshi_backtest --days 14 --hours 48 --period 5

For every event that settled in the last --days, it pulls the --period-minute price history of each
market over its last --hours, and at each step checks for a NO basket and a backwards ladder worth
KALSHI_MIN_PROFIT after fees, the same way the live bot does. Each event counts once, at its first
qualifying moment, sized to the $20 budget. Since the event has settled, it also checks what the
trade really paid.

Rough guide only. The history has the best bid and ask each period but not how many contracts were
there, so it assumes --depth contracts at each price, which overstates what $20 could get. Gaps
shorter than --period minutes don't show up at all. Public data only: no keys, no orders.
"""
from __future__ import annotations

import argparse
import csv
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .kalshi import D, Basket, best_ladder, ladder_pairs, no_basket
from .kalshi_live import Kalshi, load_settings, multiplier


def settled_events(api: Kalshi, days: int, limit: int, series: str = "") -> list[dict]:
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    events, cursor = [], ""
    while len(events) < limit:
        params = {"status": "settled", "with_nested_markets": "true", "limit": 200, "cursor": cursor, "min_close_ts": since}
        if series:
            params["series_ticker"] = series
        page = api.request("GET", "/events", params)
        events += page.get("events", [])
        cursor = page.get("cursor") or ""
        if not cursor:
            break
        time.sleep(0.06)
    return events[:limit]


def candles(api: Kalshi, tickers: list[str], start: int, end: int, period: int) -> dict[str, list[dict]]:
    per = max(1, (end - start) // (period * 60) + 1)
    step = max(1, min(100, 10000 // per))  # Kalshi: 100 markets and 10,000 candles a call
    out = {}
    for i in range(0, len(tickers), step):
        page = api.request("GET", "/markets/candlesticks", {"market_tickers": ",".join(tickers[i:i + step]),
                                                            "start_ts": start, "end_ts": end, "period_interval": period})
        out.update({m["market_ticker"]: m.get("candlesticks", []) for m in page.get("markets", [])})
        time.sleep(0.06)
    return out


def _px(c: dict, side: str) -> Decimal | None:
    v = (c.get(side) or {}).get("close_dollars")
    return D(v) if v not in (None, "") and 0 < D(v) < 1 else None


def books_at(series: dict[str, dict[int, dict]], ts: int, depth: int):
    """NO asks and YES asks per market at time ts, from the bid/ask closes (depth is assumed)."""
    no, yes = {}, {}
    for t, by_ts in series.items():
        c = by_ts.get(ts)
        if not c:
            continue
        bid, ask = _px(c, "yes_bid"), _px(c, "yes_ask")
        if bid is not None:
            no[t] = [(1 - bid, depth)]
        if ask is not None:
            yes[t] = [(ask, depth)]
    return no, yes


def raw_edge(no: dict, yes: dict, pairs: list, me: bool) -> Decimal | None:
    """Best price gap before fees and depth: YES bids over $1 for a who-wins basket, or the higher
    rung's YES bid over the lower rung's YES ask for a ladder. Positive = a trade before fees."""
    best = None
    if me and len(no) >= 2:
        best = sum((1 - a[0][0] for a in no.values()), D(0)) - 1
    for narrow, wide in pairs:
        n, w = no.get(narrow["ticker"]), yes.get(wide["ticker"])
        if n and w:
            gap = (1 - n[0][0]) - w[0][0]
            best = gap if best is None else max(best, gap)
    return best


def paid(b: Basket, results: dict[str, str]) -> Decimal:
    return sum((D(l.count) for l in b.legs if results.get(l.ticker) == l.side), D(0))


def main() -> None:
    ap = argparse.ArgumentParser(description="Replay settled Kalshi events for locked-in trades")
    ap.add_argument("--days", type=int, default=14, help="events that settled in the last N days")
    ap.add_argument("--hours", type=int, default=48, help="price history before each event's close")
    ap.add_argument("--period", type=int, default=5, help="candle length in minutes")
    ap.add_argument("--depth", type=int, default=10, help="contracts assumed at each price")
    ap.add_argument("--max-events", type=int, default=3000, help="per series when --series is given")
    ap.add_argument("--series", default="", help="comma list, e.g. KXBTCD,KXNHLTOTAL,KXNBASPREAD (default: everything)")
    args = ap.parse_args()
    cfg = load_settings()
    api = Kalshi("prod")  # real past prices; public data, never signs or trades
    names = [s.strip() for s in args.series.split(",") if s.strip()] or [""]
    events = [e for name in names for e in settled_events(api, args.days, args.max_events, name)]
    print(f"{len(events)} settled events in the last {args.days} days")

    rows, by_series, checked, edges = [], defaultdict(lambda: [0, 0, D(0)]), 0, []
    for e in events:
        markets = [m for m in e.get("markets", []) if m.get("market_type", "binary") == "binary" and m.get("close_time")]
        me = bool(e.get("mutually_exclusive"))
        if len(markets) < 2 or not (me or ladder_pairs(markets)):
            continue
        checked += 1
        close = max(datetime.fromisoformat(m["close_time"].replace("Z", "+00:00")) for m in markets)
        end, start = int(close.timestamp()), int((close - timedelta(hours=args.hours)).timestamp())
        try:
            hist = candles(api, [m["ticker"] for m in markets], start, end, args.period)
        except RuntimeError as err:
            print(f"skip {e['event_ticker']}: {err}")
            continue
        series = {t: {c["end_period_ts"]: c for c in cs} for t, cs in hist.items()}
        stamps = sorted({ts for s in series.values() for ts in s})
        ev = {**e, "close_time": close.isoformat()}
        mult = multiplier(e)
        by_series[e.get("series_ticker", "")][0] += 1
        pairs = ladder_pairs(markets)
        best_edge = None
        for ts in stamps:
            no, yes = books_at(series, ts, args.depth)
            edge = raw_edge(no, yes, pairs, me)
            if edge is not None and (best_edge is None or edge > best_edge):
                best_edge = edge
            found = []
            if me:
                found.append(no_basket(ev, no, cfg["budget"], cfg["max_sets"], mult))
            found.append(best_ladder(ev, markets, no, yes, cfg["budget"], cfg["max_sets"], mult))
            found = [f for f in found if f and f.profit >= cfg["min_profit"]]
            if not found:
                continue
            b = max(found, key=lambda f: f.profit)
            results = {m["ticker"]: m.get("result", "") for m in markets}
            real = paid(b, results) - b.outlay
            when = datetime.fromtimestamp(ts, timezone.utc)
            rows.append([when.isoformat(timespec="minutes"), e.get("series_ticker", ""), e["event_ticker"], e.get("title", ""),
                         b.kind, b.sets, len(b.legs), f"{b.outlay:.2f}", f"{b.fees:.2f}", f"{b.profit:.2f}", f"{real:.2f}",
                         f"{(close - when).total_seconds() / 3600:.1f}"])
            s = by_series[e.get("series_ticker", "")]
            s[1] += 1
            s[2] += real
            break  # one trade per event
        if best_edge is not None:
            edges.append(best_edge)

    out = Path("reports")
    out.mkdir(exist_ok=True)
    path = out / f"kalshi_backtest_{datetime.now():%Y-%m-%d_%H%M}.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "series", "event", "title", "kind", "sets", "markets", "cost", "fees", "locked_profit",
                    "real_profit", "hours_before_close"])
        w.writerows(rows)
    total = sum((D(r[10]) for r in rows), D(0))
    print(f"\nChecked {checked} events (only-one-wins or ladders). Trades worth ${cfg['min_profit']}+ after fees: {len(rows)}, "
          f"real profit ${total:.2f} (assuming {args.depth} contracts at each price).")
    if edges:  # near misses, before fees: shows the data is flowing and how far off the trades were
        edges.sort()
        print(f"Best edge per event before fees (1.00 = a dollar per set): median {edges[len(edges) // 2]:+.3f}, "
              f"best {edges[-1]:+.3f}; events above 0: {sum(e > 0 for e in edges)}, above +0.02: {sum(e > D('0.02') for e in edges)}, "
              f"above +0.05: {sum(e > D('0.05') for e in edges)} of {len(edges)}")
    print(f"Per day: {len(rows) / max(args.days, 1):.1f} trades, ${total / max(args.days, 1):.2f}")
    print("\nTop series (events checked, trades, real profit):")
    for s, (n, k, p) in sorted(by_series.items(), key=lambda x: (-x[1][1], -x[1][2]))[:15]:
        print(f"  {s:30} {n:5} {k:4}  ${p:.2f}")
    print(f"\nTrades saved to {path}")


if __name__ == "__main__":
    main()
