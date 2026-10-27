"""Kalshi bot: scans every open Kalshi market for locked-in trades worth $0.10+ after fees.

    python -m bot.kalshi_live --scan        # read-only sweep of real Kalshi prices, no keys, no orders
    python -m bot.kalshi_live --scorecard   # which series have produced trades so far
    python -m bot.kalshi_live --paper       # sweep real prices and paper-trade a pretend $20 (no keys, no orders)
    python -m bot.kalshi_live --trade       # sweep, then buy the best baskets on the DEMO account

Each sweep reads every open event (sports, politics, weather, economics, ...), checks every mutually
exclusive one for a NO basket and every strike ladder for backwards-priced rungs (see bot.kalshi), double-checks the full order book, and logs:

    kalshi_data/opportunities.csv   every basket found, locked in or not, traded or not
    kalshi_data/scorecard.csv       per series: sweeps seen, opportunities, best profit (decides focus)
    kalshi_data/prices/<day>.csv.gz top of book for every market, for testing expected-profit ideas later

With --trade it spends at most KALSHI_BUDGET (default $20) of the account, raised 25% each time
settled profits grow the pot 25% (after 5 paid-out baskets), only on baskets that lock
in KALSHI_MIN_PROFIT (default $0.10) after fees, best profit per day of waiting first. Legs are
fill-or-kill orders; if one fails, the legs already bought are sold back.

Keys: python set_kalshi_key.py (writes .env.kalshi). DEMO only: real money needs KALSHI_ENV=prod AND
KALSHI_LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY in .env.kalshi, which only brayden sets.
"""
from __future__ import annotations

import argparse
import base64
import csv
import gzip
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import requests

from .kalshi import ONE, Basket, D, asks_from_bids, best_ladder, fee, ladder_pairs, no_basket, pick, stake, yes_basket

ENV_FILE = Path(".env.kalshi")
DATA = Path("kalshi_data")
STATE = Path("kalshi_state.json")
URLS = {"demo": "https://external-api.demo.kalshi.co/trade-api/v2",
        "prod": "https://external-api.kalshi.com/trade-api/v2"}
log = logging.getLogger("kalshi")


def _main_env(name: str) -> str:
    """A value from the ORB bot's .env (only used for the shared phone-alert topic)."""
    from dotenv import dotenv_values

    return (dotenv_values(".env").get(name) or "").strip() if Path(".env").exists() else ""


MODE = "scan"  # "demo" or "paper" once main() picks, for alert titles
NTFY = ""


def alert(title: str, message: str, priority: str = "default") -> None:
    """Phone push through ntfy, if NTFY_TOPIC is set. Never stops the bot."""
    if not NTFY:
        return
    from types import SimpleNamespace

    from .notify import send

    send(SimpleNamespace(ntfy_topic=NTFY), f"Kalshi bot ({MODE}): {title}", message, priority)


def load_settings() -> dict:
    from dotenv import load_dotenv

    if ENV_FILE.exists():
        load_dotenv(ENV_FILE, override=True)
    env = os.getenv("KALSHI_ENV", "demo").strip().lower()
    if env not in URLS:
        raise SystemExit(f"KALSHI_ENV must be demo or prod, not {env!r}")
    if env == "prod" and os.getenv("KALSHI_LIVE_CONFIRM", "") != "I_UNDERSTAND_REAL_MONEY":
        raise SystemExit("KALSHI_ENV=prod trades real money and also needs KALSHI_LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY.")
    return {
        "env": env,
        "key_id": os.getenv("KALSHI_KEY_ID", "").strip(),
        "key_file": os.getenv("KALSHI_KEY_FILE", "kalshi_key.pem").strip(),
        "budget": D(os.getenv("KALSHI_BUDGET", "20")),
        "min_profit": D(os.getenv("KALSHI_MIN_PROFIT", "0.10")),
        "max_days": float(os.getenv("KALSHI_MAX_DAYS", "60")),  # skip baskets that tie money up longer
        "max_sets": int(os.getenv("KALSHI_MAX_SETS", "50")),
        "step": D(os.getenv("KALSHI_STEP", "0.25")),  # raise the budget 25% each time profits grow it 25%
        "min_settled": int(os.getenv("KALSHI_MIN_SETTLED", "5")),  # ...but only after 5 baskets have paid out
        "max_found": int(os.getenv("KALSHI_MAX_FOUND", "10")),  # more than this per sweep = something's wrong, trade nothing
        "ntfy_topic": os.getenv("NTFY_TOPIC") or _main_env("NTFY_TOPIC"),  # phone alerts, same topic as the other bots
    }


class Kalshi:
    """Small Kalshi REST client. Public market data works without keys; orders need a signed key."""

    def __init__(self, env: str = "demo", key_id: str = "", key_file: str = "", base_url: str = ""):
        self.base = base_url or URLS[env]
        self.key_id, self.key = key_id, None
        if key_id and key_file and Path(key_file).exists():
            from cryptography.hazmat.primitives import serialization

            self.key = serialization.load_pem_private_key(Path(key_file).read_bytes(), password=None)
        self.http = requests.Session()

    def _headers(self, method: str, path: str) -> dict:
        if not self.key:
            return {}
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from urllib.parse import urlparse

        ts = str(int(time.time() * 1000))
        msg = f"{ts}{method}{urlparse(self.base + path).path}".encode()  # path from /trade-api, no query
        if isinstance(self.key, Ed25519PrivateKey):
            sig = self.key.sign(msg)
        else:
            sig = self.key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                                                 salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
        return {"KALSHI-ACCESS-KEY": self.key_id, "KALSHI-ACCESS-TIMESTAMP": ts,
                "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode()}

    def request(self, method: str, path: str, params=None, body=None) -> dict:
        for attempt in range(5):
            r = self.http.request(method, self.base + path, params=params, json=body,
                                  headers=self._headers(method, path), timeout=20)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(0.5 * 2 ** attempt)  # rate limit (about 20 reads a second) or a hiccup
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"Kalshi {method} {path} -> {r.status_code}: {r.text[:300]}")
            return r.json()
        raise RuntimeError(f"Kalshi {method} {path} kept failing")

    def open_events(self) -> list[dict]:
        events, cursor = [], ""
        while True:
            page = self.request("GET", "/events", {"status": "open", "with_nested_markets": "true",
                                                   "limit": 200, "cursor": cursor})
            events += page.get("events", [])
            cursor = page.get("cursor") or ""
            if not cursor:
                return events
            time.sleep(0.06)

    def orderbooks(self, tickers: list[str]) -> dict[str, dict]:
        out = {}
        for i in range(0, len(tickers), 100):
            try:
                page = self.request("GET", "/markets/orderbooks", {"tickers": tickers[i:i + 100]})
                out.update({b["ticker"]: b.get("orderbook_fp", {}) for b in page.get("orderbooks", [])})
            except RuntimeError:  # the batch call may need keys; one book at a time is public
                for t in tickers[i:i + 100]:
                    out[t] = self.request("GET", f"/markets/{t}/orderbook").get("orderbook_fp", {})
        return out

    def market(self, ticker: str) -> dict:
        return self.request("GET", f"/markets/{ticker}").get("market", {})

    def balance(self) -> Decimal:
        return D(self.request("GET", "/portfolio/balance")["balance"]) / 100

    def order(self, ticker: str, outcome: str, count: int, limit: Decimal, tif: str = "fill_or_kill",
              reduce_only: bool = False) -> int:
        """Buy `count` contracts of `outcome` ("yes"/"no") paying at most `limit`. Returns contracts filled.
        Kalshi's order book is on the YES scale: side bid = long YES, side ask = long NO, so a NO buy
        at up to `limit` is a YES sell at no less than 1 - limit."""
        price = limit if outcome == "yes" else ONE - limit
        body = {"ticker": ticker, "side": "bid" if outcome == "yes" else "ask", "count": str(count),
                "price": f"{price:.4f}", "time_in_force": tif, "self_trade_prevention_type": "taker_at_cross",
                "client_order_id": str(uuid.uuid4())}
        if reduce_only:
            body["reduce_only"] = True
        res = self.request("POST", "/portfolio/events/orders", body=body)
        return int(D(res.get("fill_count", "0")))


# ---------------------------------------------------------------- scanning

def _top_no_asks(m: dict) -> list[tuple[Decimal, int]]:
    """NO asks from the event listing's top of book (NO ask = 1 - YES bid; its size is the YES bid's)."""
    bid, size = m.get("yes_bid_dollars"), m.get("yes_bid_size_fp")
    return asks_from_bids([[bid, size]]) if bid and size and D(bid) > 0 else []


def _top_yes_asks(m: dict) -> list[tuple[Decimal, int]]:
    ask, size = m.get("yes_ask_dollars"), m.get("yes_ask_size_fp")
    return [(D(ask), int(D(size)))] if ask and size and 0 < D(ask) < 1 and D(size) >= 1 else []


def candidates(events: list[dict], cfg: dict) -> list[tuple[dict, list[dict]]]:
    """Events with 2+ active markets, closing within KALSHI_MAX_DAYS."""
    now = datetime.now(timezone.utc)
    out = []
    for e in events:
        markets = [m for m in e.get("markets", []) if m.get("status") in ("active", "open") and m.get("market_type", "binary") == "binary"]
        if len(markets) < 2:
            continue
        close = max(m.get("close_time", "") for m in markets)
        days = (datetime.fromisoformat(close.replace("Z", "+00:00")) - now).total_seconds() / 86400 if close else 9999
        if days > cfg["max_days"]:
            continue
        out.append(({**e, "close_time": close}, markets))
    return out


def multiplier(e: dict) -> Decimal:
    m = e.get("fee_multiplier_override")
    return D(str(m)) if m not in (None, "") else ONE


def ladder_check(api: Kalshi, e: dict, markets: list[dict], budget: Decimal, cfg: dict, mult: Decimal) -> Basket | None:
    """Best backwards-priced ladder pair in the event, confirmed on the full order books."""
    if not ladder_pairs(markets):
        return None
    no_top = {m["ticker"]: _top_no_asks(m) for m in markets}
    yes_top = {m["ticker"]: _top_yes_asks(m) for m in markets}
    quick = best_ladder(e, markets, no_top, yes_top, max(budget, D(1000)), cfg["max_sets"], mult)
    if not quick:
        return None
    tickers = [l.ticker for l in quick.legs]
    books = api.orderbooks(tickers)
    no_full = {t: asks_from_bids(books.get(t, {}).get("yes_dollars") or []) for t in tickers}
    yes_full = {t: asks_from_bids(books.get(t, {}).get("no_dollars") or []) for t in tickers}
    pair = [m for m in markets if m["ticker"] in tickers]
    b = best_ladder(e, pair, no_full, yes_full, budget, cfg["max_sets"], mult)
    if b:
        return b
    quick.extra["note"] = "gone or over budget on the full book"
    quick.locked = False
    return quick


def sweep(api: Kalshi, cfg: dict, budget: Decimal) -> tuple[list[dict], list[Basket]]:
    """One pass over every open event. Returns (events, baskets confirmed on the full order book)."""
    events = api.open_events()
    found = []
    for e, markets in candidates(events, cfg):
        mult = multiplier(e)
        lad = ladder_check(api, e, markets, budget, cfg, mult)
        if lad:
            found.append(lad)
        if not e.get("mutually_exclusive"):
            continue  # baskets need "only one can win"
        quick = no_basket(e, {m["ticker"]: _top_no_asks(m) for m in markets}, max(budget, D(1000)), cfg["max_sets"], mult)
        yb = yes_basket(e, {m["ticker"]: _top_yes_asks(m) for m in markets}, max(budget, D(1000)), cfg["max_sets"], mult)
        if yb:
            found.append(yb)
        if not quick:
            continue
        books = api.orderbooks([m["ticker"] for m in markets])  # top of book can be stale: confirm on the real book
        full = {t: asks_from_bids(b.get("yes_dollars") or []) for t, b in books.items()}
        b = no_basket(e, full, budget, cfg["max_sets"], mult)
        if b:
            found.append(b)
        elif quick.profit > 0:
            quick.extra["note"] = "gone or over budget on the full book"
            quick.locked = False
            found.append(quick)
    return events, found


def log_prices(events: list[dict], when: datetime) -> None:
    """Top of book for every open market, one gzip file a day, to test expected-profit ideas later."""
    path = DATA / "prices" / f"{when:%Y-%m-%d}.csv.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with gzip.open(path, "at", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "series", "event", "ticker", "yes_bid", "yes_ask", "last", "volume_24h", "open_interest", "close_time"])
        for e in events:
            for m in e.get("markets", []):
                w.writerow([when.isoformat(timespec="seconds"), e.get("series_ticker", ""), e.get("event_ticker", ""),
                            m.get("ticker", ""), m.get("yes_bid_dollars", ""), m.get("yes_ask_dollars", ""),
                            m.get("last_price_dollars", ""), m.get("volume_24h_fp", ""), m.get("open_interest_fp", ""),
                            m.get("close_time", "")])


def log_baskets(baskets: list[Basket], traded: set[str], when: datetime, min_profit: Decimal) -> None:
    path = DATA / "opportunities.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "series", "event", "title", "kind", "locked_in", "sets", "markets", "cost", "fees",
                        "pays_at_least", "profit", "meets_min", "days_to_close", "traded", "note"])
        for b in baskets:
            w.writerow([when.isoformat(timespec="seconds"), b.series_ticker, b.event_ticker, b.title, b.kind, b.locked,
                        b.sets, len(b.legs), f"{b.outlay - b.fees:.2f}", f"{b.fees:.2f}", f"{b.payout_min:.2f}",
                        f"{b.profit:.2f}", b.profit >= min_profit, f"{b.days_to_close(when):.1f}",
                        b.event_ticker in traded, b.extra.get("note", "")])


def update_scorecard(events: list[dict], baskets: list[Basket], min_profit: Decimal) -> list[dict]:
    """Per series: how often it was swept and how often it had a $0.10+ locked-in basket. The bot uses
    it to decide where to look first; series that never pay just stay at the bottom."""
    path = DATA / "scorecard.csv"
    rows = {}
    if path.exists():
        with path.open(newline="") as f:
            rows = {r["series"]: r for r in csv.DictReader(f)}
    for s in {e.get("series_ticker", "") for e in events}:
        r = rows.setdefault(s, {"series": s, "sweeps": 0, "opportunities": 0, "best_profit": "0.00", "total_profit_seen": "0.00"})
        r["sweeps"] = int(r["sweeps"]) + 1
    for b in baskets:
        if b.locked and b.profit >= min_profit:
            r = rows[b.series_ticker]
            r["opportunities"] = int(r["opportunities"]) + 1
            r["best_profit"] = f"{max(D(r['best_profit']), b.profit):.2f}"
            r["total_profit_seen"] = f"{D(r['total_profit_seen']) + b.profit:.2f}"
    ranked = sorted(rows.values(), key=lambda r: (-int(r["opportunities"]), -float(r["total_profit_seen"]), r["series"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["series", "sweeps", "opportunities", "best_profit", "total_profit_seen"])
        w.writeheader()
        w.writerows(ranked)
    return ranked


# ---------------------------------------------------------------- trading

def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"realized": "0", "open": [], "closed": []}


def save_state(s: dict) -> None:
    STATE.write_text(json.dumps(s, indent=1))


def settle(api: Kalshi, state: dict) -> None:
    """Close out baskets whose markets have all been decided, booking what they actually paid."""
    still = []
    for b in state["open"]:
        results = {l["ticker"]: api.market(l["ticker"]).get("result", "") for l in b["legs"]}
        if all(results.values()):
            paid = sum(D(l["count"]) for l in b["legs"] if results[l["ticker"]] == l["side"])
            pnl = paid - D(b["outlay"])
            state["realized"] = str(D(state["realized"]) + pnl)
            state["closed"].append({**b, "paid": str(paid), "pnl": str(pnl), "closed": datetime.now(timezone.utc).isoformat()})
            log.info("Settled %s: paid $%s, profit $%.2f", b["event"], paid, pnl)
            alert("trade settled", f"{b.get('title') or b['event']}: paid ${paid}, profit ${pnl:.2f}")
        else:
            still.append(b)
    state["open"] = still


def free_budget(cfg: dict, state: dict) -> Decimal:
    """The current bet level (see bot.kalshi.stake: KALSHI_BUDGET, stepping up 25% per 25% of settled
    growth) minus what's tied up in open baskets and reserved by resting maker quotes (bot.kalshi_maker)."""
    level = stake(cfg["budget"], D(state["realized"]), sum(1 for c in state["closed"] if c.get("sets", 1) > 0), cfg["step"], cfg["min_settled"])
    quotes = sum((D(q["reserve"]) * (q["sets"] - q["done"]) / q["sets"] for q in state.get("quotes", [])), D(0))
    return level - sum((D(b["outlay"]) for b in state["open"]), D(0)) - quotes


def execute(api: Kalshi, b: Basket, state: dict | None = None) -> bool:
    """Buy every leg fill-or-kill. On a miss, sell back what was bought (losing at most 5c a contract)
    and give up; anything that won't sell stays open and is logged for a person to check. The sell-back
    loss is booked in `state` (worst case) and unsold contracts are tracked until they settle, so the
    profit total that sets the bet size never counts money that isn't there."""
    state = state if state is not None else {"realized": "0", "open": []}
    done = []
    for leg in b.legs:
        try:
            filled = api.order(leg.ticker, leg.side, leg.count, leg.limit)
        except RuntimeError as err:
            log.warning("Leg %s failed: %s", leg.ticker, err)
            filled = 0
        if filled < leg.count:
            if filled:
                done.append((leg, filled))
            log.warning("Basket %s missed on %s (%d/%d). Selling back %d legs.", b.event_ticker, leg.ticker, filled, leg.count, len(done))
            for got, n in done:  # selling NO = buying YES; reduce-only so it can't open a new position
                floor = max(got.limit - D("0.05"), D("0.01"))
                try:
                    sold = api.order(got.ticker, "yes" if got.side == "no" else "no", n, ONE - floor, "immediate_or_cancel", reduce_only=True)
                except RuntimeError as err:
                    log.error("Could not sell back %s: %s", got.ticker, err)
                    sold = 0
                paid = (got.cost + got.fee) * n / got.count
                loss = paid * sold / n - (floor * sold - fee(sold, floor, b.fee_multiplier))  # sold at the floor or better
                state["realized"] = str(D(state["realized"]) - loss)
                if sold < n:
                    log.error("STRAY POSITION: %d %s contracts of %s still held. Check it on Kalshi.", n - sold, got.side.upper(), got.ticker)
                    alert("stray position", f"{n - sold} {got.side.upper()} of {got.ticker} still held after a half-filled trade.", "high")
                    state["open"].append({"event": f"{b.event_ticker} (stray)", "series": b.series_ticker, "title": b.title, "sets": 0,
                                          "outlay": str(paid * (n - sold) / n), "locked_profit": "0", "opened": datetime.now(timezone.utc).isoformat(),
                                          "legs": [{"ticker": got.ticker, "side": got.side, "count": n - sold, "limit": str(got.limit)}]})
            return False
        done.append((leg, filled))
    return True


def trade(api: Kalshi, cfg: dict, baskets: list[Basket]) -> set[str]:
    state = load_state()
    settle(api, state)
    budget = min(free_budget(cfg, state), api.balance())
    held = {b["event"] for b in state["open"]}
    locked = [b for b in baskets if b.locked and b.profit >= cfg["min_profit"]]
    if len(locked) > cfg["max_found"]:  # free money is rare; dozens at once means the bot misread markets
        log.error("%d locked-in trades in one sweep is too good to be true. Trading nothing; check the opportunities log.", len(locked))
        alert("paused: too good to be true", f"{len(locked)} 'locked-in' trades in one sweep. Nothing traded.", "high")
        save_state(state)
        return set()
    traded = set()
    for b in pick([b for b in baskets if b.event_ticker not in held], budget, cfg["min_profit"]):
        log.info("Buying %s (%s): %d sets on %d markets, cost $%.2f, locks in $%.2f", b.event_ticker, b.kind, b.sets, len(b.legs), b.outlay, b.profit)
        if execute(api, b, state):
            traded.add(b.event_ticker)
            alert("trade", f"{b.title or b.event_ticker} ({b.kind}): {b.sets} sets, cost ${b.outlay:.2f}, locks in ${b.profit:.2f}")
            state["open"].append({"event": b.event_ticker, "series": b.series_ticker, "title": b.title, "sets": b.sets,
                                  "outlay": str(b.outlay), "locked_profit": str(b.profit), "opened": datetime.now(timezone.utc).isoformat(),
                                  "legs": [{"ticker": l.ticker, "side": l.side, "count": l.count, "limit": str(l.limit)} for l in b.legs]})
            save_state(state)
    save_state(state)
    return traded


class _Problems(logging.Handler):
    """Counts warnings and errors (and keeps the last few) for summary.json."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.count, self.last = 0, []

    def emit(self, record):
        self.count += 1
        self.last = (self.last + [f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} {record.getMessage()}"])[-5:]


PROBLEMS = _Problems()
log.addHandler(PROBLEMS)


def write_summary(cfg: dict, mode: str, events: list[dict], good: list[Basket], traded: set[str],
                  ranked: list[dict], when: datetime) -> dict:
    """kalshi_data/summary.json (or kalshi_data_demo/) after every loop, for the website and the nightly review."""
    state = load_state()
    closed = [c for c in state["closed"] if c.get("sets", 1) > 0]
    realized = D(state["realized"])
    s = {
        "updated": when.isoformat(timespec="seconds"), "mode": mode, "env": cfg["env"] if mode == "demo" else "prod-prices",
        "start_budget": str(cfg["budget"]), "min_profit": str(cfg["min_profit"]),
        "equity": f"{cfg['budget'] + realized:.2f}", "realized_profit": f"{realized:.2f}",
        "bet_level": f"{stake(cfg['budget'], realized, len(closed), cfg['step'], cfg['min_settled']):.2f}",
        "open_trades": len(state["open"]), "open_locked_profit": f"{sum((D(b['locked_profit']) for b in state['open']), D(0)):.2f}",
        "in_play": f"{sum((D(b['outlay']) for b in state['open']), D(0)):.2f}",
        "stray_positions": sum(1 for b in state["open"] if b.get("sets", 1) == 0),
        "closed_trades": len(closed), "trades_this_loop": len(traded),
        "events_swept": len(events), "found_this_loop": len(good),
        "top_series": [r["series"] for r in ranked[:5] if int(r["opportunities"])],
        "problems": PROBLEMS.count, "last_problems": PROBLEMS.last,
    }
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "summary.json").write_text(json.dumps(s, indent=1))
    return s


class PaperKalshi(Kalshi):
    """Real Kalshi prices with pretend orders: every order fills in full at its limit, which the
    sweep has just checked against the full order book. Optimistic about speed (no one else grabs
    the trade first), honest about price, depth and fees. Never signs a request or sends an order."""

    def __init__(self):
        super().__init__("prod")

    def balance(self) -> Decimal:
        return D(10 ** 9)  # the pretend budget in kalshi_paper_state.json is the only limit

    def order(self, ticker, outcome, count, limit, tif="fill_or_kill", reduce_only=False) -> int:
        log.info("PAPER %s %d %s %s at %s", "sell" if reduce_only else "buy", count, outcome.upper(), ticker, limit)
        return count


def main() -> None:
    ap = argparse.ArgumentParser(description="Kalshi bot: locked-in baskets worth $0.10+ after fees")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--scan", action="store_true", help="read-only sweep of real Kalshi prices")
    g.add_argument("--trade", action="store_true", help="sweep and trade (demo unless .env.kalshi says otherwise)")
    g.add_argument("--paper", action="store_true", help="sweep real prices and paper-trade a pretend budget")
    g.add_argument("--scorecard", action="store_true", help="print the series ranking so far")
    ap.add_argument("--loop", type=int, default=0, help="repeat every N minutes instead of once")
    args = ap.parse_args()
    global DATA, STATE, MODE, NTFY
    if args.trade:  # demo books are fake, so keep their logs apart from the real-market ones
        DATA, STATE = Path("kalshi_data_demo"), Path("kalshi_state.json")
    elif args.paper:
        STATE = Path("kalshi_paper_state.json")
    logname = "kalshi_demo.log" if args.trade else "kalshi_paper.log" if args.paper else "kalshi.log"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(logname)])
    cfg = load_settings()
    MODE = "demo" if args.trade else "paper" if args.paper else "scan"
    NTFY = cfg["ntfy_topic"] if MODE != "scan" else ""
    if args.scorecard:
        path = DATA / "scorecard.csv"
        print(path.read_text() if path.exists() else "No sweeps yet. Run: python -m bot.kalshi_live --scan")
        return
    if args.trade:
        if not cfg["key_id"] or not Path(cfg["key_file"]).exists():
            raise SystemExit("No Kalshi key yet. Run: python set_kalshi_key.py")
        api = Kalshi(cfg["env"], cfg["key_id"], cfg["key_file"])
        log.info("Trading on Kalshi %s, budget $%s, min profit $%s", cfg["env"].upper(), cfg["budget"], cfg["min_profit"])
    elif args.paper:
        api = PaperKalshi()
        log.info("Paper trading on REAL Kalshi prices, pretend budget $%s, min profit $%s", cfg["budget"], cfg["min_profit"])
    else:
        api = Kalshi("prod")  # real prices, public data, never signs or places orders
    trading = args.trade or args.paper
    while True:
        try:
            loop_once(api, cfg, args, trading)
        except Exception as err:  # Kalshi down or a bug: log the traceback, alert, wait, try again
            log.exception("Loop failed: %s", err)
            alert("error", f"Loop failed: {err}"[:300], "high")
            if not args.loop:
                raise
        if not args.loop:
            return
        time.sleep(args.loop * 60)


def loop_once(api: Kalshi, cfg: dict, args, trading: bool) -> None:
    when = datetime.now(timezone.utc)
    budget = free_budget(cfg, load_state()) if trading else cfg["budget"]
    events, baskets = sweep(api, cfg, max(budget, D(0)))
    traded = trade(api, cfg, baskets) if trading else set()
    log_prices(events, when)
    log_baskets(baskets, traded, when, cfg["min_profit"])
    ranked = update_scorecard(events, baskets, cfg["min_profit"])
    good = [b for b in baskets if b.locked and b.profit >= cfg["min_profit"]]
    log.info("Swept %d events (%d markets): %d locked-in baskets worth $%s+, %d traded. Top series: %s",
             len(events), sum(len(e.get("markets", [])) for e in events), len(good), cfg["min_profit"], len(traded),
             ", ".join(r["series"] for r in ranked[:5] if int(r["opportunities"])) or "none yet")
    write_summary(cfg, "demo" if args.trade else "paper" if args.paper else "scan", events, good, traded, ranked, when)

if __name__ == "__main__":
    main()
