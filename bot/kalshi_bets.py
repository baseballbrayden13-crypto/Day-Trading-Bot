"""Kalshi bot, expected-profit bets, on paper only (bot "4d").

    python -m bot.kalshi_bets --loop 15                      # every 15 minutes, all strategies
    python -m bot.kalshi_bets --once --strategies weather    # one pass, one strategy

Locked-in trades don't show up on real Kalshi (see bot.kalshi_backtest), so this tests bets that
are only expected to make money. Each strategy gives every market it understands a probability,
and the bot pretends to buy the side whose probability beats its price by enough to clear Kalshi's
fee and still expect $0.10+ profit:

  weather    Daily high-temperature markets (KXHIGHNY, KXHIGHCHI, ...) against the free Open-Meteo
             forecast for the station Kalshi settles on: normal spread around the forecast.
  crypto     Bitcoin and Ether price markets (KXBTCD, KXETHD, KXBTC, KXETH) against the live
             Coinbase price and how much the coin has been moving: log-normal spread.
  favorites  NO on 80-90c favorites about a day before the close. A test brayden asked for: the
             60-day study hinted favorites lose a bit more than priced, but it didn't hold 2h
             before the close, so it's probably luck. No model: it assumes a 5c edge.

Pretend money on real prices: it buys at the real top-of-book ask, no more contracts than are
showing there, pays the taker fee, and books what the market really pays when it settles. Each
strategy has its own pretend $20 pot so they can be compared. Never signs or sends an order.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from .kalshi import D, fee
from . import kalshi_live as kl

log = logging.getLogger("kalshi")
STATE = Path("kalshi_bets_state.json")
DATA = Path("kalshi_data_bets")

# Weather: series -> (station Kalshi settles on, lat, lon, time zone). Check the series' rules
# before trusting a new city: Kalshi uses the NWS daily climate report for that one station.
CITIES = {
    "KXHIGHNY": ("Central Park", 40.7789, -73.9692, "America/New_York"),
    "KXHIGHCHI": ("Chicago Midway", 41.7868, -87.7522, "America/Chicago"),
    "KXHIGHMIA": ("Miami Intl", 25.7906, -80.3164, "America/New_York"),
    "KXHIGHLAX": ("Los Angeles Intl", 33.9382, -118.3886, "America/Los_Angeles"),
    "KXHIGHAUS": ("Austin Bergstrom", 30.1945, -97.6699, "America/Chicago"),
    "KXHIGHDEN": ("Denver Intl", 39.8466, -104.6562, "America/Denver"),
    "KXHIGHPHIL": ("Philadelphia Intl", 39.8733, -75.2268, "America/New_York"),
}
COINS = {"KXBTCD": "BTC-USD", "KXBTC": "BTC-USD", "KXETHD": "ETH-USD", "KXETH": "ETH-USD"}
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


# ---------------------------------------------------------------- the math (no network)

def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def strike_range(m: dict, integer: bool = False) -> tuple[float, float] | None:
    """The values of the underlying for which the market resolves YES, as [lo, hi). Kalshi's
    "greater" means above floor_strike, "less" below cap_strike, "between" floor..cap. Integer
    readings (temperatures) widen by half a degree: "between 85 and 86" is [84.5, 86.5)."""
    t, lo, hi = m.get("strike_type"), m.get("floor_strike"), m.get("cap_strike")
    h = 0.5 if integer else 0.0
    if t in ("greater", "greater_or_equal") and lo is not None:
        return (float(lo) + (h if t == "greater" else -h), math.inf)
    if t in ("less", "less_or_equal") and hi is not None:
        return (-math.inf, float(hi) - (h if t == "less" else -h))
    if t == "between" and lo is not None and hi is not None:
        return (float(lo) - h, float(hi) + h)
    return None


def prob_normal(rng: tuple[float, float], mean: float, sd: float) -> float:
    lo, hi = rng
    return norm_cdf((hi - mean) / sd) - norm_cdf((lo - mean) / sd)


def prob_lognormal(rng: tuple[float, float], spot: float, sigma: float) -> float:
    """P(price at the close in rng) for a driftless log-normal price; sigma = stdev of the log
    return between now and the close."""
    def cdf(x):
        if x <= 0:
            return 0.0
        if math.isinf(x):
            return 1.0
        return norm_cdf((math.log(x / spot) + sigma * sigma / 2) / sigma)
    return cdf(rng[1]) - cdf(rng[0])


@dataclass
class Bet:
    strategy: str
    ticker: str
    event: str
    series: str
    side: str  # "yes" or "no"
    count: int
    price: str  # paid per contract
    fee: str
    prob: float  # the strategy's chance this side wins
    close_time: str
    placed: str
    note: str = ""

    @property
    def cost(self) -> Decimal:
        return D(self.price) * self.count + D(self.fee)

    @property
    def expected(self) -> Decimal:
        return D(str(round(self.prob, 4))) * self.count - self.cost


def best_side(m: dict, p_yes: float, stake: Decimal, min_edge: float, min_profit: Decimal,
              multiplier: Decimal = D(1)) -> tuple[str, int, Decimal, Decimal, float] | None:
    """Side to buy at the top of book, if the model's edge clears min_edge a contract and the bet
    expects min_profit after fees. Returns (side, count, price, fee, prob) or None."""
    yes_ask, yes_bid = m.get("yes_ask_dollars"), m.get("yes_bid_dollars")
    options = []
    if yes_ask and 0 < D(yes_ask) < 1:
        options.append(("yes", D(yes_ask), p_yes, m.get("yes_ask_size_fp")))
    if yes_bid and 0 < D(yes_bid) < 1:
        options.append(("no", 1 - D(yes_bid), 1 - p_yes, m.get("yes_bid_size_fp")))
    best = None
    for side, price, p, size in options:
        if p - float(price) < min_edge:
            continue
        shown = int(D(str(size))) if size not in (None, "") else 0
        count = min(shown, int(stake / price))
        if count < 1:
            continue
        f = fee(count, price, multiplier)
        ev = D(str(round(p, 4))) * count - price * count - f
        if ev >= min_profit and (best is None or ev > best[0]):
            best = (ev, (side, count, price, f, p))
    return best[1] if best else None


def event_date(event_ticker: str) -> date | None:
    """KXHIGHNY-26OCT27 -> 2026-10-27."""
    try:
        code = event_ticker.split("-")[1]
        return date(2000 + int(code[:2]), MONTHS[code[2:5]], int(code[5:7]))
    except (IndexError, KeyError, ValueError):
        return None


def weather_sd(days_ahead: float) -> float:
    """Typical miss of a point forecast of the daily high, in F: ~2 same day, ~3 a day out. The
    backtest (bot.kalshi_bets_backtest) measures the real number per city; set WEATHER_SD there."""
    return WEATHER_SD + 1.0 * max(days_ahead, 0)


WEATHER_SD = 2.0
CRYPTO_VOL_BOOST = 1.25  # coins jump more than a bell curve says: widen the spread


def hourly_sigma(closes: list[float]) -> float:
    """Stdev of hourly log returns."""
    r = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    if len(r) < 10:
        return 0.0
    m = sum(r) / len(r)
    return math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1))


# ---------------------------------------------------------------- outside data (PC only)

_http = requests.Session()


def forecast_highs(lat: float, lon: float, tz: str) -> dict[date, float]:
    """Open-Meteo's forecast daily high (F) for today and the next two days. Free, no key."""
    r = _http.get("https://api.open-meteo.com/v1/forecast", timeout=20, params={
        "latitude": lat, "longitude": lon, "daily": "temperature_2m_max", "temperature_unit": "fahrenheit",
        "timezone": tz, "forecast_days": 3})
    r.raise_for_status()
    d = r.json()["daily"]
    return {date.fromisoformat(t): v for t, v in zip(d["time"], d["temperature_2m_max"]) if v is not None}


def coin_closes(product: str, hours: int = 168, end: datetime | None = None) -> list[tuple[int, float]]:
    """Hourly (time, close) from Coinbase's public candles, oldest first."""
    params = {"granularity": 3600}
    if end:
        params |= {"start": (end - timedelta(hours=min(hours, 300))).isoformat(), "end": end.isoformat()}
    r = _http.get(f"https://api.exchange.coinbase.com/products/{product}/candles", params=params, timeout=20)
    r.raise_for_status()
    return sorted((int(c[0]), float(c[4])) for c in r.json())[-hours:]


def coin_spot(product: str) -> float:
    r = _http.get(f"https://api.exchange.coinbase.com/products/{product}/ticker", timeout=20)
    r.raise_for_status()
    return float(r.json()["price"])


# ---------------------------------------------------------------- strategies

def _hours_left(m: dict, now: datetime) -> float:
    ct = m.get("close_time")
    return (datetime.fromisoformat(ct.replace("Z", "+00:00")) - now).total_seconds() / 3600 if ct else -1


def weather(events: list[dict], now: datetime, cfg: dict, data=None) -> list[Bet]:
    """data: {series: {date: forecast high}} for tests; fetched from Open-Meteo otherwise."""
    out, cache = [], data or {}
    for e in events:
        s = e.get("series_ticker", "")
        if s not in CITIES:
            continue
        day = event_date(e.get("event_ticker", ""))
        if day is None:
            continue
        _, lat, lon, tz = CITIES[s]
        if s not in cache:
            try:
                cache[s] = forecast_highs(lat, lon, tz)
            except (requests.RequestException, KeyError, ValueError) as err:
                log.warning("No forecast for %s: %s", s, err)
                cache[s] = {}
        high = cache[s].get(day)
        if high is None:
            continue
        local_now = now.astimezone(ZoneInfo(tz))
        days_ahead = (datetime.combine(day, datetime.min.time(), ZoneInfo(tz)) + timedelta(hours=16) - local_now).total_seconds() / 86400
        if days_ahead < -0.1:  # past mid-afternoon of the day: the high is mostly known, the forecast isn't
            continue
        sd = weather_sd(days_ahead)
        out += _bets_for(e, now, cfg, "weather", lambda m: (lambda r: prob_normal(r, high, sd) if r else None)(
            strike_range(m, integer=True)), f"forecast {high:.1f}F sd {sd:.1f}")
    return out


def crypto(events: list[dict], now: datetime, cfg: dict, data=None) -> list[Bet]:
    """data: {product: (spot, hourly sigma)} for tests; fetched from Coinbase otherwise."""
    out, cache = [], data or {}
    for e in events:
        product = COINS.get(e.get("series_ticker", ""))
        if not product:
            continue
        if product not in cache:
            try:
                closes = [c for _, c in coin_closes(product)]
                cache[product] = (coin_spot(product), hourly_sigma(closes))
            except (requests.RequestException, KeyError, ValueError, IndexError) as err:
                log.warning("No %s price: %s", product, err)
                cache[product] = (0.0, 0.0)
        spot, sig_h = cache[product]
        if spot <= 0 or sig_h <= 0:
            continue

        def p(m):
            hours, r = _hours_left(m, now), strike_range(m)
            if r is None or hours < 0.25 or hours > cfg.get("crypto_max_hours", 36):
                return None
            return prob_lognormal(r, spot, sig_h * CRYPTO_VOL_BOOST * math.sqrt(hours))
        out += _bets_for(e, now, cfg, "crypto", p, f"spot {spot:,.0f} hourly vol {sig_h:.4f}")
    return out


def favorites(events: list[dict], now: datetime, cfg: dict, data=None) -> list[Bet]:
    """NO on markets whose YES bid is 80-90c, 20-28h before the close. Assumes a 5c edge."""
    def p(m):
        bid = m.get("yes_bid_dollars")
        if not bid or not (0.80 <= float(bid) < 0.90) or not (20 <= _hours_left(m, now) <= 28):
            return None
        return float(bid) - 0.05  # P(YES): NO's chance = its price + 5c
    return [b for e in events for b in _bets_for(e, now, cfg, "favorites", p, "80-90c favorite", sides=("no",))]


def _bets_for(e: dict, now: datetime, cfg: dict, name: str, p_yes, note: str, sides=("yes", "no")) -> list[Bet]:
    out = []
    mult = kl.multiplier(e)
    for m in e.get("markets", []):
        if m.get("status") not in ("active", "open"):
            continue
        p = p_yes(m)
        if p is None:
            continue
        p = min(max(p, 0.0), 1.0)
        pick = best_side(m, p, cfg["stake"], cfg["min_edge"], cfg["min_profit"], mult)
        if pick and pick[0] in sides:
            side, count, price, f, prob = pick
            out.append(Bet(name, m["ticker"], e.get("event_ticker", ""), e.get("series_ticker", ""), side, count,
                           f"{price:.4f}", f"{f:.2f}", round(prob, 4), m.get("close_time", ""),
                           now.isoformat(timespec="seconds"), note))
    return out


STRATEGIES = {"weather": weather, "crypto": crypto, "favorites": favorites}


# ---------------------------------------------------------------- paper book

def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"open": [], "closed": []}


def save_state(s: dict) -> None:
    STATE.write_text(json.dumps(s, indent=1))


def pot(state: dict, strategy: str, start: Decimal) -> tuple[Decimal, Decimal]:
    """(equity, free cash) of one strategy's pretend pot."""
    realized = sum((D(c["pnl"]) for c in state["closed"] if c["strategy"] == strategy), D(0))
    tied = sum((D(b["cost"]) for b in state["open"] if b["strategy"] == strategy), D(0))
    return start + realized, start + realized - tied


def place(state: dict, bets: list[Bet], start: Decimal, max_per_event: int = 1) -> list[Bet]:
    """Book the best bets per strategy (highest expected profit first) while each pot has cash.
    One bet per event per strategy, and never the same market twice."""
    held = {(b["strategy"], b["event"]) for b in state["open"]} | {(b["strategy"], b["ticker"]) for b in state["open"]}
    placed = []
    for b in sorted(bets, key=lambda b: -b.expected):
        if (b.strategy, b.event) in held or (b.strategy, b.ticker) in held:
            continue
        _, free = pot(state, b.strategy, start)
        if b.cost > free:
            continue
        state["open"].append({**asdict(b), "cost": f"{b.cost:.2f}", "expected": f"{b.expected:.2f}"})
        held |= {(b.strategy, b.event), (b.strategy, b.ticker)}
        placed.append(b)
        log.info("PAPER BET %s: %d %s %s at %s (fee %s), model %.0f%%, expects $%.2f. %s",
                 b.strategy, b.count, b.side.upper(), b.ticker, b.price, b.fee, b.prob * 100, b.expected, b.note)
    return placed


def settle(api, state: dict) -> int:
    still, n = [], 0
    for b in state["open"]:
        result = api.market(b["ticker"]).get("result", "")
        if result in ("yes", "no"):
            paid = D(b["count"]) if result == b["side"] else D(0)
            state["closed"].append({**b, "result": result, "paid": f"{paid:.2f}", "pnl": f"{paid - D(b['cost']):.2f}",
                                    "closed": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            log.info("Settled %s %s: %s, profit $%.2f", b["strategy"], b["ticker"], result.upper(), paid - D(b["cost"]))
            n += 1
        else:
            still.append(b)
    state["open"] = still
    return n


def summary(state: dict, start: Decimal, when: datetime) -> dict:
    s = {"updated": when.isoformat(timespec="seconds"), "mode": "paper-bets", "start_per_strategy": str(start), "strategies": {}}
    for name in STRATEGIES:
        closed = [c for c in state["closed"] if c["strategy"] == name]
        equity, free = pot(state, name, start)
        s["strategies"][name] = {
            "equity": f"{equity:.2f}", "free": f"{free:.2f}", "open_bets": sum(b["strategy"] == name for b in state["open"]),
            "settled_bets": len(closed), "won": sum(D(c["paid"]) > 0 for c in closed),
            "realized_profit": f"{sum((D(c['pnl']) for c in closed), D(0)):.2f}",
            "expected_profit_settled": f"{sum((D(c['expected']) for c in closed), D(0)):.2f}",
        }
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "summary.json").write_text(json.dumps(s, indent=1))
    return s


def run_once(api, cfg: dict, names: list[str]) -> dict:
    now = datetime.now(timezone.utc)
    state = load_state()
    settle(api, state)
    events = api.open_events()
    bets = [b for n in names for b in STRATEGIES[n](events, now, cfg)]
    placed = place(state, bets, cfg["budget"])
    save_state(state)
    s = summary(state, cfg["budget"], now)
    log.info("Bets: %d candidates, %d placed. %s", len(bets), len(placed),
             "; ".join(f"{k} ${v['equity']} ({v['open_bets']} open, {v['settled_bets']} settled)" for k, v in s["strategies"].items()))
    return s


def main() -> None:
    ap = argparse.ArgumentParser(description="Kalshi expected-profit bets, paper only")
    ap.add_argument("--strategies", default=",".join(STRATEGIES))
    ap.add_argument("--loop", type=int, default=15, help="minutes between passes")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--stake", type=D, default=D("2"), help="most a single bet may cost (pretend $)")
    ap.add_argument("--min-edge", type=float, default=0.05, help="model chance minus price, per contract")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("kalshi_bets.log")])
    names = [n.strip() for n in args.strategies.split(",") if n.strip()]
    if bad := [n for n in names if n not in STRATEGIES]:
        raise SystemExit(f"Unknown strategies: {bad}. Pick from {list(STRATEGIES)}")
    base = kl.load_settings()
    cfg = {"budget": base["budget"], "min_profit": base["min_profit"], "stake": args.stake, "min_edge": args.min_edge}
    if not args.once:
        kl.single_instance("kalshi-bets")
    api = kl.PaperKalshi()  # real prices, never signs or orders
    log.info("Paper bets on REAL Kalshi prices: %s, $%s pretend each, stake up to $%s, edge %.0fc+, expected $%s+",
             names, cfg["budget"], args.stake, args.min_edge * 100, cfg["min_profit"])
    while True:
        try:
            run_once(api, cfg, names)
        except Exception as err:
            log.exception("Bets loop failed: %s", err)
            if args.once:
                raise
        if args.once:
            return
        time.sleep(args.loop * 60)


if __name__ == "__main__":
    main()
