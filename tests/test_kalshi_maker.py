import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

from bot import kalshi_live as kl
from bot import kalshi_maker as km

SOON = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
EVENT = {"event_ticker": "EV", "series_ticker": "SER", "title": "Who wins?", "close_time": SOON}
# Taking every ask costs 0.60 + 0.62 + 0.80 = 2.02 a set for a $2 payout: no taker trade. Resting at the best NO bid
# + 1c on one leg makes it pay.
ASKS = {"A": [(D("0.60"), 10)], "B": [(D("0.62"), 10)], "C": [(D("0.80"), 10)]}
BIDS = {"A": D("0.50"), "B": D("0.55"), "C": D("0.70")}
CFG = {"min_profit": D("0.10"), "quote_min": 30, "max_sets": 50, "max_quotes": 3}


def test_maker_fee_is_a_quarter_of_taker():
    assert km.maker_fee(100, D("0.50")) == D("0.44")  # 0.0175 x 100 x 0.25 = 0.4375, rounded up


def test_best_quote_rests_one_leg_and_locks_in_the_minimum():
    q = km.best_quote(EVENT, ASKS, BIDS, D(20), D("0.10"))
    assert q is not None
    assert BIDS[q.ticker] <= q.price < ASKS[q.ticker][0][0]  # joins or improves the bid, never crosses
    assert q.price <= BIDS[q.ticker] + D("0.01")
    assert q.profit >= D("0.10") and q.reserve <= 20
    assert q.payout_min == q.sets * len(q.hedge) and {l.ticker for l in q.hedge} | {q.ticker} == {"A", "B", "C"}


def test_no_quote_when_it_would_sit_behind_other_bids():
    tight = {"A": [(D("0.70"), 10)], "B": [(D("0.72"), 10)], "C": [(D("0.80"), 10)]}
    bids = {t: a[0][0] - D("0.01") for t, a in tight.items()}  # the price that would pay is far below these bids
    assert km.best_quote(EVENT, tight, bids, D(20), D("0.10")) is None


def test_budget_caps_the_quote():
    assert km.best_quote(EVENT, ASKS, BIDS, D("1.00"), D("0.10")) is None
    assert km.best_quote(EVENT, ASKS, BIDS, D(5), D("0.01")).reserve <= 5


class FakeApi:
    def __init__(self, fills=0, fail=None, books=None):
        self.fills, self.fail, self.orders, self.cancelled = fills, fail, [], []
        self.books = books or {t: {"yes_dollars": [[str(1 - a[0][0]), "10"]]} for t, a in ASKS.items()}

    def request(self, method, path, params=None, body=None):
        if method == "POST":
            self.orders.append(body)
            return {"order_id": "o1", "fill_count": "0", "remaining_count": body["count"]}
        if method == "DELETE":
            self.cancelled.append(path)
            return {}
        return {"order": {"fill_count_fp": f"{self.fills}.00", "status": "resting"}}

    def order(self, ticker, outcome, count, limit, tif="fill_or_kill", reduce_only=False):
        self.orders.append((ticker, outcome, count, limit, reduce_only))
        return 0 if ticker == self.fail and not reduce_only else count

    def orderbooks(self, tickers):
        return {t: self.books[t] for t in tickers}

    def balance(self):
        return D(100)


def _state(monkeypatch, tmp_path):
    monkeypatch.setattr(kl, "STATE", tmp_path / "state.json")
    q = km.best_quote(EVENT, ASKS, BIDS, D(20), D("0.10"))
    state = {"realized": "0", "open": [], "closed": [], "quotes": [{
        "event": "EV", "series": "SER", "title": "t", "ticker": q.ticker, "order_id": "o1", "price": str(q.price), "sets": q.sets,
        "done": 0, "reserve": str(q.reserve), "multiplier": "1", "placed": time.time(),
        "hedge": [{"ticker": l.ticker, "limit": str(l.limit)} for l in q.hedge]}]}
    kl.save_state(state)
    return q


def test_resting_quote_reserves_budget(monkeypatch, tmp_path):
    q = _state(monkeypatch, tmp_path)
    cfg = {"budget": D(20), "step": D(0), "min_settled": 5}
    assert kl.free_budget(cfg, kl.load_state()) == 20 - q.reserve


def test_fill_is_hedged_and_booked_as_an_open_basket(monkeypatch, tmp_path):
    q = _state(monkeypatch, tmp_path)
    api = FakeApi(fills=4)
    km.check(api, CFG)
    s = kl.load_state()
    assert [o[:3] for o in api.orders] == [(l.ticker, "no", 4) for l in q.hedge]
    assert s["quotes"][0]["done"] == 4 and len(s["open"]) == 1
    b = s["open"][0]
    assert b["sets"] == 4 and len(b["legs"]) == 3 and D(b["locked_profit"]) > 0


def test_missed_hedge_sells_everything_back_and_books_the_loss(monkeypatch, tmp_path):
    q = _state(monkeypatch, tmp_path)
    api = FakeApi(fills=2, fail=q.hedge[1].ticker)
    km.check(api, CFG)
    s = kl.load_state()
    sells = [o for o in api.orders if o[4]]
    assert {o[0] for o in sells} == {q.ticker, q.hedge[0].ticker} and all(o[1] == "yes" for o in sells)
    assert D(s["realized"]) < 0 and s["open"] == []


def test_quote_is_cancelled_when_the_hedge_stops_paying(monkeypatch, tmp_path):
    _state(monkeypatch, tmp_path)
    worse = {t: {"yes_dollars": [["0.05", "10"]]} for t in ASKS}  # NO asks jump to 0.95
    api = FakeApi(books=worse)
    km.check(api, CFG)
    assert api.cancelled and kl.load_state()["quotes"] == []


def test_quote_survives_while_it_still_pays(monkeypatch, tmp_path):
    _state(monkeypatch, tmp_path)
    api = FakeApi()
    km.check(api, CFG)
    assert not api.cancelled and len(kl.load_state()["quotes"]) == 1


def test_place_posts_a_post_only_no_bid(monkeypatch, tmp_path):
    monkeypatch.setattr(kl, "STATE", tmp_path / "state.json")
    mk = lambda t: {"ticker": t, "status": "active", "close_time": SOON, "yes_bid_dollars": str(1 - ASKS[t][0][0]),
                    "yes_bid_size_fp": "10", "yes_ask_dollars": str(1 - BIDS[t]), "yes_ask_size_fp": "10"}
    events = [{**EVENT, "mutually_exclusive": True, "markets": [mk(t) for t in ASKS]}]
    books = {t: {"yes_dollars": [[str(1 - ASKS[t][0][0]), "10"]], "no_dollars": [[str(BIDS[t]), "10"]]} for t in ASKS}
    api = FakeApi(books=books)
    cfg = {**CFG, "budget": D(20), "step": D(0), "min_settled": 5, "max_days": 60}
    assert km.place(api, cfg, events) == 1
    body = api.orders[0]
    assert body["side"] == "ask" and body["post_only"] and body["time_in_force"] == "good_till_canceled" and body["expiration_time"]
    assert len(kl.load_state()["quotes"]) == 1
