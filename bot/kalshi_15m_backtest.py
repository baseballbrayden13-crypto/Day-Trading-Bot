"""Would betting Kalshi's 15-minute markets have made money? Settled events, real past prices, fees included.

    python -m bot.kalshi_15m_backtest --list                  # which 15-minute series Kalshi has
    python -m bot.kalshi_15m_backtest --days 14 --minutes-before 5
    python -m bot.kalshi_15m_backtest --series KXBTC15M,KXETH15M --days 7

Two rules, each tested on its own:
  model     crypto series only: the coin's 1-minute Coinbase price and the past 2 hours' moves give the
            chance it ends above/below the strike (same lognormal math as bot.kalshi_bets). Bet the side
            the model says is underpriced by --min-edge, if it expects $0.10+ after fees.
  favorite  any series (commodities, indexes, crypto): buy whichever side costs --fav-min or more,
            --minutes-before the close. Shows whether near-certain 15-minute outcomes are priced right.

Kalshi's 1-minute candles give the bid/ask at the bet time (sizes assumed available). Results are split
into an earlier and a later half: worth paper money only if both halves made money and t-stat is 2+.
Public data only, no keys.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import math
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .kalshi import D, fee
from . import kalshi_bets as kb
from .kalshi_backtest import candles, settled_events
from .kalshi_bets_backtest import bet_on, report
from .kalshi_calibration import quote_before
from .kalshi_live import Kalshi, multiplier

COIN_OF = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD", "XRP": "XRP-USD", "DOGE": "DOGE-USD"}


def fifteen_minute_series(api: Kalshi) -> list[dict]:
    """Series whose ticker says 15-minute (e.g. KXBTC15M), with their category and title."""
    page = api.request("GET", "/series", {})
    return [s for s in page.get("series", []) if "15M" in s.get("ticker", "").upper()]


def coin_for(series: str) -> str | None:
    s = series.upper().removeprefix("KX")
    return next((p for c, p in COIN_OF.items() if s.startswith(c)), None)


def minute_history(product: str, start: datetime, end: datetime) -> dict[int, float]:
    """1-minute (start time -> close) from Coinbase, 300 candles a call."""
    out, t = {}, start
    while t < end:
        stop = min(t + timedelta(minutes=300), end)
        for attempt in range(5):
            try:
                r = kb._http.get(f"https://api.exchange.coinbase.com/products/{product}/candles", timeout=30,
                                 params={"granularity": 60, "start": t.isoformat(), "end": stop.isoformat()})
                r.raise_for_status()
                break
            except Exception:  # noqa: BLE001 - requests raises several kinds
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        out.update({int(c[0]): float(c[4]) for c in r.json()})
        t = stop
        time.sleep(0.35)
    return out


def minute_sigma(closes: list[float]) -> float:
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    if len(rets) < 30:
        return 0.0
    m = sum(rets) / len(rets)
    return math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))


def favorite_bet(e: dict, m: dict, q: tuple[Decimal, Decimal], fav_min: Decimal, stake: Decimal) -> dict | None:
    bid, ask = q
    for side, price in (("yes", ask), ("no", 1 - bid)):
        if price >= fav_min and price < 1:
            count = int(stake / price)
            if count < 1:
                return None
            f = fee(count, price, multiplier(e))
            paid = D(count) if m.get("result") == side else D(0)
            return {"event": e["event_ticker"], "series": e.get("series_ticker", ""), "ticker": m["ticker"], "side": side,
                    "count": count, "price": price, "fee": f, "prob": float(price), "expected": -f,
                    "pnl": paid - price * count - f, "close": m.get("close_time", ""), "note": "favorite"}
    return None


def run(api: Kalshi, args) -> tuple[list[dict], list[dict], list[str]]:
    series = [s.strip() for s in args.series.split(",") if s.strip()] or [s["ticker"] for s in fifteen_minute_series(api)]
    cfg = {"stake": args.stake, "min_edge": args.min_edge, "min_profit": args.min_profit}
    model, fav, notes, prices = [], [], [], {}
    now = datetime.now(timezone.utc)
    for s in series:
        events = settled_events(api, args.days, args.max_events, s)
        product = coin_for(s)
        if product and product not in prices:
            try:
                prices[product] = minute_history(product, now - timedelta(days=args.days, hours=3), now)
            except Exception as err:  # noqa: BLE001
                notes.append(f"{product}: no Coinbase history ({err})")
                prices[product] = {}
        px = prices.get(product, {}) if product else {}
        stamps = sorted(px)
        n_model, n_fav = len(model), len(fav)
        for e in events:
            markets = [m for m in e.get("markets", []) if m.get("result") in ("yes", "no") and m.get("close_time")]
            if not markets:
                continue
            close = max(datetime.fromisoformat(m["close_time"].replace("Z", "+00:00")) for m in markets)
            ts = int((close - timedelta(minutes=args.minutes_before)).timestamp())
            try:
                hist = candles(api, [m["ticker"] for m in markets], ts - 20 * 60, ts, 1)
            except RuntimeError:
                continue
            quotes = {t: quote_before(cs, ts) for t, cs in hist.items()}
            for m in markets:
                q = quotes.get(m["ticker"])
                if q and (b := favorite_bet(e, m, q, args.fav_min, args.stake)):
                    fav.append(b)
            if not stamps:
                continue
            i = bisect.bisect_right(stamps, ts - 60)  # minute candles finished by then
            done = stamps[max(0, i - 121):i]
            if len(done) < 60 or ts - done[-1] > 300:
                continue
            spot, sig = px[done[-1]], minute_sigma([px[x] for x in done])
            if sig <= 0:
                continue
            sigma = sig * kb.CRYPTO_VOL_BOOST * math.sqrt(args.minutes_before)
            b = bet_on(e, markets, quotes, lambda m: (lambda r: kb.prob_lognormal(r, spot, sigma) if r else None)(
                kb.strike_range(m)), cfg)
            if b:
                model.append({**b, "note": f"spot {spot:,.2f}"})
        notes.append(f"{s}: {len(events)} settled events, {len(model) - n_model} model bets, {len(fav) - n_fav} favorite bets"
                     + ("" if product else " (no price feed: favorite rule only)"))
    return model, fav, notes


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest Kalshi 15-minute markets, after fees")
    ap.add_argument("--list", action="store_true", help="just list the 15-minute series")
    ap.add_argument("--series", default="", help="comma list; default every 15-minute series")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--max-events", type=int, default=2000, help="per series")
    ap.add_argument("--minutes-before", type=int, default=5, help="bet this many minutes before the close")
    ap.add_argument("--stake", type=D, default=D("2"))
    ap.add_argument("--min-edge", type=float, default=0.05)
    ap.add_argument("--min-profit", type=D, default=D("0.10"))
    ap.add_argument("--fav-min", type=D, default=D("0.85"), help="favorite rule: buy the side priced this or more")
    args = ap.parse_args()
    api = Kalshi("prod")
    if args.list:
        for s in fifteen_minute_series(api):
            print(f"{s['ticker']:<16} {s.get('category', ''):<14} {s.get('title', '')}")
        return
    model, fav, notes = run(api, args)
    print("\n".join(notes))
    print()
    for label, bets in (("model (crypto)", model), (f"favorite {args.fav_min}+", fav)):
        report(bets, label)
        for s in sorted({b["series"] for b in bets}):
            report([b for b in bets if b["series"] == s], f"  {s}")
    out = Path("reports")
    out.mkdir(exist_ok=True)
    stamp = f"{datetime.now():%Y-%m-%d_%H%M}"
    for name, bets in (("model", model), ("favorite", fav)):
        if bets:
            path = out / f"kalshi_15m_{name}_{stamp}.csv"
            with path.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(bets[0]))
                w.writeheader()
                w.writerows(bets)
            print(f"Saved {path}")
    print("Worth paper money only if both halves made money and t-stat is 2+.")


if __name__ == "__main__":
    main()
