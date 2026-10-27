"""Would the weather and crypto bets (bot.kalshi_bets) have made money? Settled Kalshi events, real
past prices, the same betting rule, fees included.

    python -m bot.kalshi_bets_backtest weather --days 60 --lead 1
    python -m bot.kalshi_bets_backtest crypto --days 30 --hours-before 3 --max-events 400

weather: for each settled daily-high event, the Open-Meteo forecast made --lead days before (its
"previous runs" archive), and Kalshi's hourly bid/ask at 8pm local the evening before the day
(--lead 1) or two evenings before (--lead 2). It also measures how far the forecast missed per city
(from the bucket that won), so WEATHER_SD in bot.kalshi_bets can be set from data. The bias it
finds is printed but NOT used in the same test (that would be fitting to the answers).

crypto: for each settled BTC/ETH price event, Coinbase's hourly price and the past week's moves
as of --hours-before the close, and Kalshi's bid/ask at that moment.

One bet per event (the best expected profit), up to --stake dollars, sizes assumed available
(hourly candles don't show depth). Splits results into an earlier and a later half: a strategy is
only worth paper money if both halves made money. Public data only.
"""
from __future__ import annotations

import argparse
import csv
import math
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from .kalshi import D
from . import kalshi_bets as kb
from .kalshi_backtest import candles, settled_events
from .kalshi_calibration import quote_before, t_stat
from .kalshi_live import Kalshi, multiplier


def past_forecast_highs(lat: float, lon: float, tz: str, start: date, end: date, lead: int) -> dict[date, float]:
    """Daily high (F) of the forecast made `lead` days earlier, from Open-Meteo's previous-runs archive."""
    var = f"temperature_2m_previous_day{lead}"
    r = kb._http.get("https://previous-runs-api.open-meteo.com/v1/forecast", timeout=60, params={
        "latitude": lat, "longitude": lon, "hourly": var, "temperature_unit": "fahrenheit", "timezone": tz,
        "start_date": start.isoformat(), "end_date": end.isoformat()})
    r.raise_for_status()
    h = r.json()["hourly"]
    highs = defaultdict(lambda: -math.inf)
    for t, v in zip(h["time"], h[var]):
        if v is not None:
            d = date.fromisoformat(t[:10])
            highs[d] = max(highs[d], v)
    return {d: v for d, v in highs.items() if v > -math.inf}


def coin_history(product: str, start: datetime, end: datetime) -> list[tuple[int, float]]:
    """Hourly (start time, close) from Coinbase, 300 candles a call."""
    out, t = {}, start
    while t < end:
        stop = min(t + timedelta(hours=300), end)
        r = kb._http.get(f"https://api.exchange.coinbase.com/products/{product}/candles", timeout=30,
                         params={"granularity": 3600, "start": t.isoformat(), "end": stop.isoformat()})
        r.raise_for_status()
        out.update({int(c[0]): float(c[4]) for c in r.json()})
        t = stop
        time.sleep(0.2)
    return sorted(out.items())


def market_view(m: dict, bid: Decimal, ask: Decimal) -> dict:
    """The fields best_side reads, from a past quote (depth unknown: assume plenty)."""
    return {**m, "yes_bid_dollars": str(bid), "yes_ask_dollars": str(ask), "yes_bid_size_fp": "1000", "yes_ask_size_fp": "1000"}


def bet_on(e: dict, markets: list[dict], quotes: dict, prob, cfg: dict) -> dict | None:
    """Best bet in the event at the past quotes, with what it really paid."""
    best = None
    for m in markets:
        q = quotes.get(m["ticker"])
        p = prob(m)
        if not q or p is None:
            continue
        pick = kb.best_side(market_view(m, *q), min(max(p, 0.0), 1.0), cfg["stake"], cfg["min_edge"], cfg["min_profit"], multiplier(e))
        if not pick:
            continue
        side, count, price, f, prob_side = pick
        ev = D(str(round(prob_side, 4))) * count - price * count - f
        if best is None or ev > best["expected"]:
            paid = D(count) if m.get("result") == side else D(0)
            best = {"event": e["event_ticker"], "series": e.get("series_ticker", ""), "ticker": m["ticker"], "side": side,
                    "count": count, "price": price, "fee": f, "prob": prob_side, "expected": ev,
                    "pnl": paid - price * count - f, "close": m.get("close_time", "")}
    return best


def run_weather(api: Kalshi, args, cfg: dict) -> tuple[list[dict], list[str]]:
    bets, notes = [], []
    for series, (station, lat, lon, tz) in kb.CITIES.items():
        events = [e for e in settled_events(api, args.days, args.max_events, series) if kb.event_date(e["event_ticker"])]
        if not events:
            notes.append(f"{series}: no settled events")
            continue
        days = [kb.event_date(e["event_ticker"]) for e in events]
        try:
            fc = past_forecast_highs(lat, lon, tz, min(days), max(days), args.lead)
        except Exception as err:  # noqa: BLE001 - report and move on to the next city
            notes.append(f"{series}: no past forecasts ({err})")
            continue
        errors = []
        for e in events:
            day = kb.event_date(e["event_ticker"])
            high = fc.get(day)
            markets = [m for m in e.get("markets", []) if m.get("result") in ("yes", "no")]
            if high is None or not markets:
                continue
            won = [kb.strike_range(m, integer=True) for m in markets if m["result"] == "yes"]
            if won and won[0] and all(map(math.isfinite, won[0])):
                errors.append((won[0][0] + won[0][1]) / 2 - high)
            at = datetime.combine(day - timedelta(days=args.lead), datetime.min.time(), ZoneInfo(tz)) + timedelta(hours=20)
            ts = int(at.timestamp())
            try:
                hist = candles(api, [m["ticker"] for m in markets], ts - 6 * 3600, ts, 60)
            except RuntimeError:
                continue
            quotes = {t: quote_before(cs, ts) for t, cs in hist.items()}
            sd = kb.weather_sd(args.lead - 1 + 16 / 24 + 4 / 24)  # 8pm the evening before -> ~0.8 days to the afternoon
            b = bet_on(e, markets, quotes, lambda m: (lambda r: kb.prob_normal(r, high, sd) if r else None)(
                kb.strike_range(m, integer=True)), cfg)
            if b:
                bets.append({**b, "note": f"forecast {high:.1f}"})
        if errors:
            mean = sum(errors) / len(errors)
            sd = math.sqrt(sum((x - mean) ** 2 for x in errors) / max(len(errors) - 1, 1))
            notes.append(f"{series} ({station}): {len(errors)} days, forecast missed by {mean:+.1f}F on average, "
                         f"spread {sd:.1f}F (model assumes {kb.weather_sd(args.lead - 1 + 20 / 24):.1f})")
    return bets, notes


def run_crypto(api: Kalshi, args, cfg: dict) -> tuple[list[dict], list[str]]:
    bets, notes, prices = [], [], {}
    now = datetime.now(timezone.utc)
    for series, product in kb.COINS.items():
        events = settled_events(api, args.days, args.max_events, series)
        if not events:
            notes.append(f"{series}: no settled events")
            continue
        if product not in prices:
            try:
                prices[product] = dict(coin_history(product, now - timedelta(days=args.days + 9), now))
            except Exception as err:  # noqa: BLE001
                notes.append(f"{product}: no Coinbase history ({err})")
                prices[product] = {}
        hist_px = prices[product]
        if not hist_px:
            continue
        stamps = sorted(hist_px)
        n0 = len(bets)
        for e in events:
            markets = [m for m in e.get("markets", []) if m.get("result") in ("yes", "no") and m.get("close_time")]
            if not markets:
                continue
            close = max(datetime.fromisoformat(m["close_time"].replace("Z", "+00:00")) for m in markets)
            at = close - timedelta(hours=args.hours_before)
            ts = int(at.timestamp())
            done = [s for s in stamps if s + 3600 <= ts][-169:]  # hourly candles finished by then
            if len(done) < 50:
                continue
            spot, sig = hist_px[done[-1]], kb.hourly_sigma([hist_px[s] for s in done])
            if sig <= 0:
                continue
            try:
                hist = candles(api, [m["ticker"] for m in markets], ts - 6 * 3600, ts, 60)
            except RuntimeError:
                continue
            quotes = {t: quote_before(cs, ts) for t, cs in hist.items()}
            sigma = sig * kb.CRYPTO_VOL_BOOST * math.sqrt(args.hours_before)
            b = bet_on(e, markets, quotes, lambda m: (lambda r: kb.prob_lognormal(r, spot, sigma) if r else None)(
                kb.strike_range(m)), cfg)
            if b:
                bets.append({**b, "note": f"spot {spot:,.0f}"})
        notes.append(f"{series}: {len(events)} events, {len(bets) - n0} bets")
    return bets, notes


def report(bets: list[dict], label: str) -> None:
    if not bets:
        print(f"{label}: no bets")
        return
    pnl = [b["pnl"] for b in bets]
    cut = sorted(b["close"] for b in bets)[len(bets) // 2]
    early = sum((b["pnl"] for b in bets if b["close"] < cut), D(0))
    late = sum((b["pnl"] for b in bets if b["close"] >= cut), D(0))
    won = sum(b["pnl"] > 0 for b in bets)
    cost = sum((b["price"] * b["count"] + b["fee"] for b in bets), D(0))
    print(f"{label}: {len(bets)} bets, won {won}, profit ${sum(pnl, D(0)):.2f} on ${cost:.2f} bet "
          f"(expected ${sum((b['expected'] for b in bets), D(0)):.2f}); earlier half ${early:.2f}, later half ${late:.2f}; "
          f"t-stat {t_stat(pnl):.1f}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest Kalshi weather/crypto bets, after fees")
    ap.add_argument("strategy", choices=["weather", "crypto"])
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--max-events", type=int, default=400, help="per series")
    ap.add_argument("--lead", type=int, default=1, choices=[1, 2], help="weather: forecast/bet this many days ahead")
    ap.add_argument("--hours-before", type=float, default=3, help="crypto: bet this long before the close")
    ap.add_argument("--stake", type=D, default=D("2"))
    ap.add_argument("--min-edge", type=float, default=0.05)
    ap.add_argument("--min-profit", type=D, default=D("0.10"))
    args = ap.parse_args()
    cfg = {"stake": args.stake, "min_edge": args.min_edge, "min_profit": args.min_profit}
    api = Kalshi("prod")
    bets, notes = (run_weather if args.strategy == "weather" else run_crypto)(api, args, cfg)
    print("\n".join(notes))
    print()
    report(bets, f"{args.strategy} (all)")
    for s in sorted({b["series"] for b in bets}):
        report([b for b in bets if b["series"] == s], f"  {s}")
    for side in ("yes", "no"):
        report([b for b in bets if b["side"] == side], f"  {side.upper()} bets")
    out = Path("reports")
    out.mkdir(exist_ok=True)
    path = out / f"kalshi_bets_{args.strategy}_{datetime.now():%Y-%m-%d_%H%M}.csv"
    if bets:
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(bets[0]))
            w.writeheader()
            w.writerows(bets)
        print(f"\nSaved to {path}")
    print("Worth paper money only if both halves made money and t-stat is 2+.")


if __name__ == "__main__":
    main()
