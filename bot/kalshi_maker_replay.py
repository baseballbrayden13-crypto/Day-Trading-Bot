"""Replay the maker quotes (bot.kalshi_maker) on recently settled Kalshi events, using real trades for fills.

    python -m bot.kalshi_maker_replay --days 14 --hours 12 --series KXHIGHNY,KXNBAGAME,KXNHLGAME

For every mutually exclusive event that settled in the last --days, every --step minutes over its last
--hours, it prices a quote from the 1-minute candles the way the live maker does (best_quote). The quote
then rests for up to --quote-min minutes:
- each minute it re-checks the other legs; if buying them no longer locks in KALSHI_MIN_PROFIT it is
  cancelled (the live bot does the same every few seconds);
- it fills only from real prints strictly THROUGH its price (a taker bought YES at a NO price below ours).
  The history has no queue, so prints exactly at our price never count. That's conservative;
- each fill is hedged at that minute's asks. If any other leg's ask is above its limit the hedge fails
  and the filled contracts are sold at that minute's NO bid (5c under our price at worst), else held.
Since the events have settled, every hedged basket and every stray position is valued at what it paid.

Rough guide: candles have the best bid and ask but not their size (--depth contracts are assumed), and
quiet minutes carry the last quote forward for --stale minutes. Public data only: no keys, no orders.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .kalshi import CENT, D, fee
from .kalshi_backtest import books_at, candles, settled_events
from .kalshi_live import Kalshi, load_settings, multiplier
from .kalshi_maker import best_quote, maker_fee


def prints(api: Kalshi, ticker: str, start: int, end: int) -> list[tuple[int, Decimal, int]]:
    """Real trades where a taker bought YES: (time, NO price, contracts), oldest first."""
    out, cursor = [], ""
    while True:
        params = {"ticker": ticker, "min_ts": start, "max_ts": end, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        page = api.request("GET", "/markets/trades", params)
        for t in page.get("trades", []):
            if t.get("taker_outcome_side", t.get("taker_side")) == "yes":
                ts = int(datetime.fromisoformat(t["created_time"].replace("Z", "+00:00")).timestamp())
                out.append((ts, D(t["no_price_dollars"]), int(D(t["count_fp"]))))
        cursor = page.get("cursor") or ""
        if not cursor or not page.get("trades"):
            break
        time.sleep(0.06)
    return sorted(out)


def hedge_cost(hedge: list[dict], no: dict, n: int, mult: Decimal, raise_limits: bool) -> Decimal | None:
    """Cost of buying n of every hedge leg at the asks in `no`, or None if a leg is missing or (unless
    raise_limits) above its limit."""
    total = D(0)
    for leg in hedge:
        book = no.get(leg["ticker"])
        if not book:
            return None
        ask = book[0][0]
        if ask > leg["limit"]:
            if not raise_limits:
                return None
            leg["limit"] = ask
        total += n * ask + fee(n, ask, mult)
    return total


def replay_event(api: Kalshi, e: dict, cfg: dict, args) -> tuple[list[list], dict]:
    markets = [m for m in e.get("markets", []) if m.get("market_type", "binary") == "binary" and m.get("close_time")]
    stats = defaultdict(int)
    if not e.get("mutually_exclusive") or len(markets) < 2:
        return [], stats
    close = max(datetime.fromisoformat(m["close_time"].replace("Z", "+00:00")) for m in markets)
    end, start = int(close.timestamp()), int((close - timedelta(hours=args.hours)).timestamp())
    hist = candles(api, [m["ticker"] for m in markets], start, end, 1)
    series = {t: {c["end_period_ts"]: c for c in cs} for t, cs in hist.items() if cs}
    if not series:
        return [], stats
    stats["events"] += 1
    results = {m["ticker"]: m.get("result", "") for m in markets}
    ev, mult = {**e, "close_time": close.isoformat()}, multiplier(e)
    tape: dict[str, list] = {}
    rows, t = [], start
    while t < end - args.quote_min * 60:
        no, yes = books_at(series, t, args.depth, args.stale * 60)
        q = best_quote(ev, no, {k: 1 - v[0][0] for k, v in yes.items()}, cfg["budget"], cfg["min_profit"], cfg["max_sets"], mult)
        if not q:
            t += args.step * 60
            continue
        stats["quotes"] += 1
        if q.ticker not in tape:
            tape[q.ticker] = prints(api, q.ticker, start, end)
        times = [p[0] for p in tape[q.ticker]]
        hedge = [{"ticker": l.ticker, "limit": l.limit} for l in q.hedge]
        left, stop, filled_any = q.sets, t + args.quote_min * 60, False
        i = bisect.bisect_right(times, t)
        minute = t
        while left > 0 and minute < stop:
            minute += 60
            book_no, book_yes = books_at(series, minute, args.depth, args.stale * 60)
            cost = hedge_cost(hedge, book_no, left, mult, raise_limits=True)
            if cost is None or left * len(hedge) - left * q.price - maker_fee(left, q.price, mult) - cost < cfg["min_profit"]:
                stats["cancelled_stale"] += 1
                break  # the live bot would cancel here: the hedge no longer pays
            while i < len(times) and times[i] <= minute and left > 0:
                ts, price, size = tape[q.ticker][i]
                i += 1
                if price >= q.price:
                    continue  # at our price we might still be behind the queue; never counted
                n = min(left, size)
                left -= n
                filled_any = True
                stats["contracts"] += n
                mine = n * q.price + maker_fee(n, q.price, mult)
                cost = hedge_cost(hedge, book_no, n, mult, raise_limits=False)
                when = datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="minutes")
                if cost is not None:
                    stats["hedged"] += 1
                    locked = D(n * len(hedge)) - mine - cost
                    paid = sum((D(n) for l in [q.ticker] + [h["ticker"] for h in hedge] if results.get(l) == "no"), D(0))
                    real = paid - mine - cost
                    rows.append([when, e.get("series_ticker", ""), e["event_ticker"], q.ticker, f"{q.price}", n, "hedged",
                                 f"{locked:.2f}", f"{real:.2f}"])
                else:
                    stats["hedge_failed"] += 1
                    bid_quote = (book_yes.get(q.ticker) or [(None, 0)])[0][0]
                    bid = 1 - bid_quote if bid_quote is not None else None
                    if bid is not None and bid >= q.price - D("0.05") and bid >= CENT:
                        real = n * bid - fee(n, bid, mult) - mine
                        how = "sold back"
                    else:
                        real = (D(n) if results.get(q.ticker) == "no" else D(0)) - mine
                        how = "held to settlement"
                    rows.append([when, e.get("series_ticker", ""), e["event_ticker"], q.ticker, f"{q.price}", n, how, "0.00", f"{real:.2f}"])
                    left = 0  # stop quoting after a miss, like the live bot's check() does
        stats["quotes_filled"] += filled_any
        t = max(minute, t + args.step * 60)
    return rows, stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Replay maker quotes on settled Kalshi events, filled by real trades")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--hours", type=int, default=12, help="price history before each event's close")
    ap.add_argument("--step", type=int, default=30, help="minutes between quote attempts per event")
    ap.add_argument("--quote-min", type=int, default=30, help="minutes a quote rests (KALSHI_QUOTE_MIN)")
    ap.add_argument("--stale", type=int, default=30, help="minutes a market's last quote stays valid with no new candle")
    ap.add_argument("--depth", type=int, default=10, help="contracts assumed at each price")
    ap.add_argument("--max-events", type=int, default=100, help="per series")
    ap.add_argument("--series", required=True, help="comma list, e.g. KXHIGHNY,KXNBAGAME")
    args = ap.parse_args()
    cfg = load_settings()
    api = Kalshi("prod")  # real past prices and trades; public data, never signs or trades
    rows, totals, by_series = [], defaultdict(int), defaultdict(lambda: defaultdict(int))
    for name in [s.strip() for s in args.series.split(",") if s.strip()]:
        events = settled_events(api, args.days, args.max_events, name)
        for e in events:
            try:
                r, st = replay_event(api, e, cfg, args)
            except RuntimeError as err:
                print(f"skip {e['event_ticker']}: {err}")
                continue
            rows += r
            for k, v in st.items():
                totals[k] += v
                by_series[name][k] += v
        print(f"{name}: {len(events)} settled events")

    out = Path("reports")
    out.mkdir(exist_ok=True)
    path = out / f"kalshi_maker_replay_{datetime.now():%Y-%m-%d_%H%M}.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "series", "event", "quoted_market", "no_price", "contracts", "outcome", "locked_profit", "real_profit"])
        w.writerows(rows)
    locked = sum((D(r[7]) for r in rows), D(0))
    real = sum((D(r[8]) for r in rows), D(0))
    hedges = totals["hedged"] + totals["hedge_failed"]
    print(f"\nEvents replayed: {totals['events']}. Quotes: {totals['quotes']}, filled at least once: {totals['quotes_filled']} "
          f"({totals['contracts']} contracts), cancelled because the hedge stopped paying: {totals['cancelled_stale']}.")
    print(f"Hedges: {totals['hedged']} of {hedges} fills ({100 * totals['hedged'] / hedges if hedges else 0:.0f}%). "
          f"Locked profit ${locked:.2f}; real result after settlement ${real:.2f} "
          f"(${real / max(args.days, 1):.2f} a day, assuming {args.depth} contracts at each price).")
    print("\nBy series (events, quotes, filled, contracts, hedged, failed hedges):")
    for name, st in by_series.items():
        print(f"  {name:16} {st['events']:5} {st['quotes']:6} {st['quotes_filled']:5} {st['contracts']:6} {st['hedged']:5} {st['hedge_failed']:5}")
    print(f"\nFills saved to {path}")


if __name__ == "__main__":
    main()
