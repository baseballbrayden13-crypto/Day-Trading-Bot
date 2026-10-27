"""Kalshi maker quotes: wait at our own price on one leg of a NO basket instead of paying the ask.

    python -m bot.kalshi_maker                  # demo: taker sweep + new quotes every 5 min, quotes checked every 5 s
    python -m bot.kalshi_maker --minutes 10     # same, but cancel everything and stop after 10 minutes
    python -m bot.kalshi_maker --paper          # REAL prices, pretend quotes filled only by real trades (no keys, no orders)

A NO basket on n markets of a mutually exclusive event pays at least k x (n - 1) (see bot.kalshi). Paying
the ask on every leg rarely beats that by $0.10. Here the bot instead rests a post-only NO bid on one leg,
at a price where, if it fills, buying the other legs at their current asks still locks in KALSHI_MIN_PROFIT
after fees. The maker fee is modeled at Kalshi's 0.0175 maker rate on every market, rounded up, although most
markets charge none. When a quote fills, the other legs are bought fill-or-kill at once.

Quotes are cancelled when the other legs move so the hedge no longer pays, after KALSHI_QUOTE_MIN minutes
(they also expire on Kalshi by themselves then, in case this program dies), and on exit. If a hedge misses,
the filled contracts are sold back the same way execute() does, and the loss is booked. Their full cost is
reserved from the budget while they rest, so taker trades can't spend the same money.

--paper answers the question demo can't (demo has almost no other traders): would real quotes fill? See
PaperMakerApi for the fill rule. It keeps its own state (kalshi_maker_paper_state.json), data
(kalshi_data_maker_paper/) and log (kalshi_maker_paper.log).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path

from .kalshi import CENT, FEE_RATE, ONE, Basket, D, Leg, asks_from_bids, buy, fee
from . import kalshi_live as kl

MAKER_RATE = D("0.0175")
log = logging.getLogger("kalshi")


def maker_fee(count: int, price: Decimal, multiplier: Decimal = ONE) -> Decimal:
    return fee(count, price, multiplier * MAKER_RATE / FEE_RATE)


@dataclass
class Quote:
    event_ticker: str
    series_ticker: str
    title: str
    ticker: str  # the leg we rest a NO bid on
    price: Decimal  # NO price we bid
    sets: int
    hedge: list[Leg]  # the other legs, `sets` each, at prices on the book now (limit = worst level)
    payout_min: Decimal
    close_time: str = ""
    multiplier: Decimal = ONE

    @property
    def reserve(self) -> Decimal:
        """Everything it costs if it fills and the hedge fills at its limits."""
        return self.sets * self.price + maker_fee(self.sets, self.price, self.multiplier) + sum((l.cost + l.fee for l in self.hedge), D(0))

    @property
    def profit(self) -> Decimal:
        return self.payout_min - self.reserve

    def score(self) -> float:
        days = Basket(self.event_ticker, "", "", "", 0, [], D(0), self.close_time).days_to_close()
        return float(self.profit / self.reserve) / max(days, 1.0) if self.reserve > 0 else 0.0


def best_quote(event: dict, no_asks: dict[str, list[tuple[Decimal, int]]], no_bids: dict[str, Decimal], budget: Decimal,
               min_profit: Decimal, max_sets: int = 50, multiplier: Decimal = ONE) -> Quote | None:
    """Most profitable quote for this event that fits the budget, or None. `no_asks` maps ticker -> NO asks
    (cheapest first), `no_bids` ticker -> best NO bid now. The quote joins or improves the best NO bid by a
    cent (never crossing the ask) and only if that price still locks in `min_profit`; a quote stuck behind
    other bids would almost never fill."""
    best = None
    for j in no_asks:
        top_bid = no_bids.get(j, D(0))
        ask = no_asks[j][0][0] if no_asks[j] else ONE
        for k in range(1, max_sets + 1):
            hedge = []
            for t, asks in no_asks.items():
                f = buy(asks, k, multiplier) if t != j else None
                if f and k - f.cost - f.fee > 0:
                    hedge.append(Leg(t, "no", k, f.cost, f.fee, f.worst))
            if not hedge:
                break  # deeper levels only cost more
            payout = D(k * len(hedge))  # n = len(hedge) + 1 markets, at most one loses
            room = payout - sum((l.cost + l.fee for l in hedge), D(0)) - min_profit
            q = min((room / k).quantize(CENT, rounding=ROUND_FLOOR), top_bid + CENT, ask - CENT)
            while q >= CENT and k * q + maker_fee(k, q, multiplier) > room:
                q -= CENT
            if q < CENT or q < top_bid:
                continue
            quote = Quote(event["event_ticker"], event.get("series_ticker", ""), event.get("title", ""), j, q, k, hedge,
                          payout, event.get("close_time", ""), multiplier)
            if quote.reserve > budget:
                break
            if best is None or quote.profit > best.profit:
                best = quote
    return best


def _top_no_bid(m: dict) -> Decimal:
    ask = m.get("yes_ask_dollars")
    return ONE - D(ask) if ask and 0 < D(ask) < 1 else D(0)


def find_quotes(events: list[dict], cfg: dict, budget: Decimal, skip: set[str], api=None) -> list[Quote]:
    """Screen every candidate event on the listing's top of book, then re-price the best few on the full book."""
    rough = []
    for e, markets in kl.candidates(events, cfg):
        if e["event_ticker"] in skip or not e.get("mutually_exclusive"):
            continue  # a NO basket only locks in when at most one market can win ("above $104" and "above $107" can both)
        mult = kl.multiplier(e)
        q = best_quote(e, {m["ticker"]: kl._top_no_asks(m) for m in markets}, {m["ticker"]: _top_no_bid(m) for m in markets},
                       budget, cfg["min_profit"], cfg["max_sets"], mult)
        if q:
            rough.append((q, e, markets, mult))
    rough.sort(key=lambda r: -r[0].score())
    out = []
    for q, e, markets, mult in rough[: cfg["max_quotes"] * 3]:
        if api is None:
            out.append(q)
            continue
        books = api.orderbooks([m["ticker"] for m in markets])
        full = best_quote(e, {t: asks_from_bids(b.get("yes_dollars") or []) for t, b in books.items()},
                          {t: (D(str(b["no_dollars"][-1][0])) if b.get("no_dollars") else D(0)) for t, b in books.items()},
                          budget, cfg["min_profit"], cfg["max_sets"], mult)
        if full:
            out.append(full)
    return sorted(out, key=lambda q: -q.score())


# ---------------------------------------------------------------- orders

def rest(api, q: Quote, minutes: int) -> str:
    """Post-only NO bid at q.price (a YES ask at 1 - price), expiring by itself after `minutes`."""
    res = api.request("POST", "/portfolio/events/orders", body={
        "ticker": q.ticker, "side": "ask", "count": str(q.sets), "price": f"{ONE - q.price:.4f}",
        "time_in_force": "good_till_canceled", "post_only": True, "cancel_order_on_pause": True,
        "expiration_time": int(time.time()) + minutes * 60, "self_trade_prevention_type": "maker",
        "client_order_id": f"mk-{q.event_ticker[:30]}-{int(time.time())}"})
    return res["order_id"]


def cancel(api, order_id: str, ticker: str) -> None:
    try:
        api.request("DELETE", f"/portfolio/events/orders/{order_id}", params={"market_ticker": ticker})
    except RuntimeError as err:  # already filled, expired or cancelled
        log.info("Cancel %s: %s", order_id, err)


def filled(api, order_id: str, ticker: str) -> tuple[int, str]:
    """Contracts filled so far and the order's status. Orders placed through /portfolio/events/orders
    404 on GET /portfolio/orders/{id}, but they do show up in the per-market order list."""
    for o in api.request("GET", "/portfolio/orders", params={"ticker": ticker}).get("orders", []):
        if o.get("order_id") == order_id:
            return int(D(o.get("fill_count_fp") or "0")), o.get("status", "")
    raise RuntimeError(f"order {order_id} not in the {ticker} order list")


def sell_back(api, state: dict, q: dict, ticker: str, n: int, price: Decimal, paid: Decimal) -> None:
    """Sell `n` NO contracts of `ticker` bought for `paid`, accepting 5c under `price`; book the worst-case loss
    and track anything that won't sell (same rules as kalshi_live.execute)."""
    floor = max(price - D("0.05"), CENT)
    mult = D(q["multiplier"])
    try:
        sold = api.order(ticker, "yes", n, ONE - floor, "immediate_or_cancel", reduce_only=True)
    except RuntimeError as err:
        log.error("Could not sell back %s: %s", ticker, err)
        sold = 0
    loss = paid * sold / n - (floor * sold - fee(sold, floor, mult))
    state["realized"] = str(D(state["realized"]) - loss)
    if sold < n:
        log.error("STRAY POSITION: %d NO contracts of %s still held. Check it on Kalshi.", n - sold, ticker)
        state["open"].append({"event": f"{q['event']} (stray)", "series": q["series"], "title": q["title"], "sets": 0,
                              "outlay": str(paid * (n - sold) / n), "locked_profit": "0", "opened": _now(),
                              "legs": [{"ticker": ticker, "side": "no", "count": n - sold, "limit": str(price)}]})


def hedge(api, state: dict, q: dict, n: int) -> bool:
    """`n` more contracts of the quote filled: buy `n` of every other leg fill-or-kill at its limit. On a miss,
    sell back the quote's `n` and whatever hedge legs filled."""
    mult, price = D(q["multiplier"]), D(q["price"])
    legs = [Leg(l["ticker"], "no", n, D(l["limit"]) * n, fee(n, D(l["limit"]), mult), D(l["limit"])) for l in q["hedge"]]
    got = []
    for leg in legs:
        try:
            ok = api.order(leg.ticker, "no", n, leg.limit) >= n
        except RuntimeError as err:
            log.warning("Hedge leg %s failed: %s", leg.ticker, err)
            ok = False
        if not ok:
            log.warning("Quote %s: hedge missed on %s. Selling back %d contracts on %d legs.", q["event"], leg.ticker, n, len(got) + 1)
            sell_back(api, state, q, q["ticker"], n, price, n * price + maker_fee(n, price, mult))
            for g in got:
                sell_back(api, state, q, g.ticker, n, g.limit, g.cost + g.fee)
            return False
        got.append(leg)
    outlay = n * price + maker_fee(n, price, mult) + sum((l.cost + l.fee for l in legs), D(0))
    state["open"].append({"event": q["event"], "series": q["series"], "title": q["title"], "sets": n, "outlay": str(outlay),
                          "locked_profit": str(D(n * len(legs)) - outlay), "opened": _now(), "maker": True,
                          "legs": [{"ticker": q["ticker"], "side": "no", "count": n, "limit": str(price)}]
                          + [{"ticker": l.ticker, "side": "no", "count": n, "limit": str(l.limit)} for l in legs]})
    log.info("Quote %s filled %d: hedged, locks in $%.2f", q["event"], n, D(n * len(legs)) - outlay)
    return True


def still_pays(api, q: dict, cfg: dict) -> bool:
    """Would the unfilled sets still lock in the minimum profit at today's asks on the other legs?"""
    left = q["sets"] - q["done"]
    if left <= 0:
        return False
    books = api.orderbooks([l["ticker"] for l in q["hedge"]])
    mult, price = D(q["multiplier"]), D(q["price"])
    cost = left * price + maker_fee(left, price, mult)
    for l in q["hedge"]:
        f = buy(asks_from_bids((books.get(l["ticker"]) or {}).get("yes_dollars") or []), left, mult)
        if not f:
            return False
        cost += f.cost + f.fee
        l["limit"] = str(max(f.worst, D(l["limit"])))  # hedge at what the book asks now
    return D(left * len(q["hedge"])) - cost >= cfg["min_profit"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def place(api, cfg: dict, events: list[dict]) -> int:
    """Rest new quotes (up to KALSHI_MAX_QUOTES at once) with whatever budget is free."""
    state = kl.load_state()
    quotes = state.setdefault("quotes", [])
    slots = cfg["max_quotes"] - len(quotes)
    budget = min(kl.free_budget(cfg, state), api.balance())
    skip = {b["event"] for b in state["open"]} | {q["event"] for q in quotes}
    placed = 0
    for q in find_quotes(events, cfg, max(budget, D(0)), skip, api) if slots > 0 and budget > 0 else []:
        if placed >= slots or q.reserve > budget:
            continue
        try:
            oid = rest(api, q, cfg["quote_min"])
        except RuntimeError as err:
            log.warning("Quote on %s refused: %s", q.ticker, err)
            continue
        quotes.append({"event": q.event_ticker, "series": q.series_ticker, "title": q.title, "ticker": q.ticker, "order_id": oid,
                       "price": str(q.price), "sets": q.sets, "done": 0, "reserve": str(q.reserve), "multiplier": str(q.multiplier),
                       "placed": time.time(), "hedge": [{"ticker": l.ticker, "limit": str(l.limit)} for l in q.hedge]})
        budget -= q.reserve
        placed += 1
        log.info("Resting NO bid on %s at $%s x%d (%s): locks in $%.2f if it fills; hedge NO %s", q.ticker, q.price, q.sets,
                 q.event_ticker, q.profit, ", ".join(f"{l.ticker.rsplit('-', 1)[-1]}@{l.limit}" for l in q.hedge))
        kl.save_state(state)
    kl.save_state(state)
    return placed


def check(api, cfg: dict) -> None:
    """Hedge new fills; cancel quotes that are done, stale or no longer pay."""
    state = kl.load_state()
    keep = []
    for q in state.get("quotes", []):
        try:
            n, status = filled(api, q["order_id"], q["ticker"])
        except RuntimeError as err:
            log.warning("Quote %s: can't read order: %s", q["event"], err)
            keep.append(q)
            continue
        if n > q["done"]:
            hedge(api, state, q, n - q["done"])
            q["done"] = n
        live = status == "resting" and q["done"] < q["sets"]
        if live and (time.time() - q["placed"] > cfg["quote_min"] * 60 or not still_pays(api, q, cfg)):
            cancel(api, q["order_id"], q["ticker"])
            n, _ = filled(api, q["order_id"], q["ticker"])  # a fill can land between the check and the cancel
            if n > q["done"]:
                hedge(api, state, q, n - q["done"])
                q["done"] = n
            log.info("Quote %s cancelled (%d/%d filled)", q["event"], q["done"], q["sets"])
            live = False
        if live:
            keep.append(q)
    state["quotes"] = keep
    kl.save_state(state)


def cancel_all(api) -> None:
    state = kl.load_state()
    for q in state.get("quotes", []):
        cancel(api, q["order_id"], q["ticker"])
    check(api, {"quote_min": -1, "min_profit": D(0)})  # hedge any last fills, drop the rest


class PaperMakerApi(kl.Kalshi):
    """Real Kalshi prices and trades, pretend orders. Never signs a request or sends an order.

    A pretend quote (a NO bid at q) fills only from real prints after it was placed, where a taker bought YES:
    - a print at a NO price below q went through our level, so it fills us up to the print's size;
    - prints exactly at q fill us only once their total size passes the NO bids that were already resting
      at q when we placed it (we're last in the queue).
    Taker orders (hedge legs, sell-backs) fill only if the real book has the size at or inside the limit."""

    def __init__(self, path: Path):
        super().__init__("prod")
        self.path = path
        self.orders = json.loads(path.read_text()) if path.exists() else {}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.orders, indent=1))

    def balance(self) -> Decimal:
        return D(10 ** 9)  # the pretend budget in the state file is the only limit

    def request(self, method: str, path: str, params=None, body=None) -> dict:
        if method == "POST" and path == "/portfolio/events/orders":
            return self._rest(body)
        if method == "DELETE" and path.startswith("/portfolio/events/orders/"):
            o = self.orders.get(path.rsplit("/", 1)[-1])
            if o:
                self._update(o)
                if o["status"] == "resting":
                    o["status"] = "canceled"
                self._save()
            return {}
        if method == "GET" and path == "/portfolio/orders":
            out = []
            for o in self.orders.values():
                if o["ticker"] == (params or {}).get("ticker"):
                    self._update(o)
                    out.append({"order_id": o["id"], "fill_count_fp": f"{o['filled']}.00", "status": o["status"]})
            self._save()
            return {"orders": out}
        if method != "GET":
            raise RuntimeError(f"paper mode never sends {method} {path}")
        return super().request(method, path, params, body)

    def _rest(self, body: dict) -> dict:
        ticker, q = body["ticker"], ONE - D(body["price"])
        book = self.orderbooks([ticker]).get(ticker, {})
        ahead = sum((int(D(str(n))) for p, n in book.get("no_dollars") or [] if D(str(p)) == q), 0)
        oid = f"paper-{len(self.orders) + 1}-{int(time.time())}"
        self.orders[oid] = {"id": oid, "ticker": ticker, "price": str(q), "count": int(D(body["count"])), "ahead": ahead,
                            "placed": time.time(), "checked": time.time(), "expires": body.get("expiration_time") or 0,
                            "through": 0, "at_price": 0, "filled": 0, "status": "resting"}
        self._save()
        log.info("PAPER rest NO bid %s at $%s x%s (%d already bid at that price)", ticker, q, body["count"], ahead)
        return {"order_id": oid, "fill_count": "0.00", "remaining_count": body["count"]}

    def _update(self, o: dict) -> None:
        """Count real prints since the last check against the pretend quote."""
        if o["status"] != "resting":
            return
        end = min(time.time(), o["expires"] or float("inf"))
        trades, cursor = [], ""
        while True:
            params = {"ticker": o["ticker"], "min_ts": int(o["checked"]), "max_ts": int(end) + 1, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            page = super().request("GET", "/markets/trades", params)
            trades += page.get("trades", [])
            cursor = page.get("cursor") or ""
            if not cursor or not page.get("trades"):
                break
        q = D(o["price"])
        for t in trades:
            ts = datetime.fromisoformat(t["created_time"].replace("Z", "+00:00")).timestamp()
            if ts <= o["placed"] or ts <= o["checked"] or ts > end or t.get("taker_outcome_side", t.get("taker_side")) != "yes":
                continue
            n, price = int(D(t["count_fp"])), D(t["no_price_dollars"])
            if price < q:
                o["through"] += n
            elif price == q:
                o["at_price"] += n
        o["checked"] = end
        o["filled"] = min(o["count"], o["through"] + max(0, o["at_price"] - o["ahead"]))
        if o["filled"] >= o["count"]:
            o["status"] = "executed"
        elif o["expires"] and time.time() >= o["expires"]:
            o["status"] = "canceled"
        if o["filled"]:
            log.info("PAPER %s NO bid at $%s: %d/%d filled by real trades", o["ticker"], q, o["filled"], o["count"])

    def order(self, ticker: str, outcome: str, count: int, limit: Decimal, tif: str = "fill_or_kill",
              reduce_only: bool = False) -> int:
        book = self.orderbooks([ticker]).get(ticker, {})
        asks = asks_from_bids(book.get("yes_dollars" if outcome == "no" else "no_dollars") or [])
        got = sum((n for p, n in asks if p <= limit), 0)
        filled = count if got >= count else (got if tif == "immediate_or_cancel" else 0)
        log.info("PAPER %s %d %s %s at up to $%s: %s", "sell" if reduce_only else "buy", count, outcome.upper(), ticker,
                 limit, f"filled {filled}" if filled else "not on the book")
        return filled


def main() -> None:
    ap = argparse.ArgumentParser(description="Kalshi bot with maker quotes (demo unless .env.kalshi says otherwise)")
    ap.add_argument("--sweep", type=int, default=5, help="minutes between sweeps")
    ap.add_argument("--poll", type=int, default=5, help="seconds between quote checks")
    ap.add_argument("--minutes", type=float, default=0, help="stop (cancelling all quotes) after this long; 0 = run until Ctrl+C")
    ap.add_argument("--paper", action="store_true", help="real prices, pretend quotes filled only by real trades; no keys, no orders")
    args = ap.parse_args()
    mode = "maker-paper" if args.paper else "maker"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler("kalshi_maker_paper.log" if args.paper else "kalshi.log")])
    kl.single_instance(f"kalshi-{mode}")  # never two makers on one state file
    cfg = kl.load_settings()
    cfg["max_quotes"] = int(os.getenv("KALSHI_MAX_QUOTES", "3"))
    cfg["quote_min"] = int(os.getenv("KALSHI_QUOTE_MIN", "30"))
    kl.MODE = mode
    if args.paper:
        kl.STATE, kl.DATA = Path("kalshi_maker_paper_state.json"), Path("kalshi_data_maker_paper")
        api = PaperMakerApi(Path("kalshi_maker_paper_orders.json"))
        log.info("Maker PAPER mode on REAL Kalshi prices, pretend budget $%s, min profit $%s, up to %d quotes",
                 cfg["budget"], cfg["min_profit"], cfg["max_quotes"])
    else:
        if not cfg["key_id"] or not Path(cfg["key_file"]).exists():
            raise SystemExit("No Kalshi key yet. Run: python set_kalshi_key.py")
        api = kl.Kalshi(cfg["env"], cfg["key_id"], cfg["key_file"])
        log.info("Maker mode on Kalshi %s, budget $%s, min profit $%s, up to %d quotes", cfg["env"].upper(), cfg["budget"],
                 cfg["min_profit"], cfg["max_quotes"])
    stop = time.time() + args.minutes * 60 if args.minutes else float("inf")
    next_sweep = 0.0
    try:
        while time.time() < stop:
            try:  # any error: log the traceback and keep going (a dead loop would leave quotes unwatched)
                if time.time() >= next_sweep:
                    next_sweep = time.time() + args.sweep * 60
                    when = datetime.now(timezone.utc)
                    events, baskets = kl.sweep(api, cfg, max(kl.free_budget(cfg, kl.load_state()), D(0)))
                    traded = kl.trade(api, cfg, baskets)
                    kl.log_prices(events, when)
                    kl.log_baskets(baskets, traded, when, cfg["min_profit"])
                    ranked = kl.update_scorecard(events, baskets, cfg["min_profit"])
                    good = [b for b in baskets if b.locked and b.profit >= cfg["min_profit"]]
                    kl.write_summary(cfg, mode, events, good, traded, ranked, when)
                    placed = place(api, cfg, events)
                    log.info("Swept %d events: %d taker trades, %d new quotes, %d resting", len(events), len(traded), placed,
                             len(kl.load_state().get("quotes", [])))
                check(api, cfg)
            except Exception:
                log.exception("Maker loop error; carrying on")
            time.sleep(args.poll)
    finally:
        cancel_all(api)
        log.info("Stopped; all quotes cancelled.")


if __name__ == "__main__":
    main()
