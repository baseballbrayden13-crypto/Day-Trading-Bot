from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from bot import kalshi_live as kl
from bot.kalshi import asks_from_bids, best_ladder, buy, fee, implies, no_basket, pick, stake, yes_basket

NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)
SOON = (NOW + timedelta(days=3)).isoformat()


def test_fee_matches_kalshi_schedule():
    assert fee(1, D("0.50")) == D("0.02")  # 0.0175 rounds up
    assert fee(100, D("0.50")) == D("1.75")
    assert fee(10, D("0.10")) == D("0.07")  # 0.063 rounds up
    assert fee(1, D("0.99")) == D("0.01")
    assert fee(0, D("0.5")) == 0


def test_no_asks_come_from_yes_bids():
    assert asks_from_bids([["0.4100", "10.00"], ["0.4200", "13.50"]]) == [(D("0.58"), 13), (D("0.59"), 10)]


def test_buy_walks_the_book_and_refuses_thin_books():
    f = buy([(D("0.58"), 2), (D("0.60"), 5)], 3)
    assert f.cost == D("1.76") and f.worst == D("0.60") and f.fee == D("0.06")  # 0.04 + 0.02, each level rounded up
    assert buy([(D("0.58"), 2)], 3) is None


def event(n=3):
    return {"event_ticker": "EV", "series_ticker": "SER", "title": "Who wins?", "close_time": SOON}


def test_no_basket_locks_in_profit_when_yes_bids_beat_a_dollar_plus_fees():
    # YES bids 0.45 + 0.40 + 0.30 = 1.15 > $1: NO on all three costs 0.55+0.60+0.70 = 1.85 per set, pays >= 2.
    books = {"A": [(D("0.55"), 10)], "B": [(D("0.60"), 10)], "C": [(D("0.70"), 10)]}
    b = no_basket(event(), books, D(20))
    assert b.locked and len(b.legs) == 3
    per_set = D(2) - D("1.85")
    assert b.payout_min == 2 * b.sets
    assert b.profit == b.sets * per_set - b.fees
    assert b.outlay <= 20 and b.profit >= D("0.10")


def test_no_basket_skips_markets_that_do_not_help_and_fair_prices():
    fair = {"A": [(D("0.51"), 10)], "B": [(D("0.61"), 10)], "C": [(D("0.91"), 10)]}  # YES bids sum to 0.97
    assert no_basket(event(), fair, D(20)) is None
    books = {"A": [(D("0.40"), 1)], "B": [(D("0.50"), 1)], "C": [(D("0.99"), 1)]}  # C's 1c edge is eaten by its 1c fee
    b = no_basket(event(), books, D(20))
    assert {l.ticker for l in b.legs} == {"A", "B"}


def test_budget_caps_the_basket():
    books = {"A": [(D("0.55"), 100)], "B": [(D("0.60"), 100)], "C": [(D("0.70"), 100)]}
    assert no_basket(event(), books, D(20)).outlay <= 20
    assert no_basket(event(), books, D("1.00")) is None


def test_yes_basket_is_research_only():
    b = yes_basket(event(), {"A": [(D("0.30"), 5)], "B": [(D("0.30"), 5)], "C": [(D("0.30"), 5)]}, D(20))
    assert b and not b.locked
    assert pick([b], D(20), D("0.10"), NOW) == []


def test_pick_prefers_quick_payoffs_and_respects_min_profit_and_budget():
    books = {"A": [(D("0.55"), 10)], "B": [(D("0.60"), 10)], "C": [(D("0.70"), 10)]}
    quick = no_basket({**event(), "event_ticker": "QUICK"}, books, D(5))
    slow = no_basket({**event(), "event_ticker": "SLOW", "close_time": (NOW + timedelta(days=50)).isoformat()}, books, D(5))
    assert [b.event_ticker for b in pick([slow, quick], D(5), D("0.10"), NOW)] == ["QUICK"]
    assert pick([quick], D(5), D(100), NOW) == []


def test_prod_needs_both_flags(monkeypatch, tmp_path):
    monkeypatch.setattr(kl, "ENV_FILE", tmp_path / "none")
    monkeypatch.setenv("KALSHI_ENV", "prod")
    monkeypatch.delenv("KALSHI_LIVE_CONFIRM", raising=False)
    with pytest.raises(SystemExit):
        kl.load_settings()
    monkeypatch.setenv("KALSHI_ENV", "demo")
    assert kl.load_settings()["env"] == "demo"


class FakeApi:
    def __init__(self, fail_on=None):
        self.fail_on, self.orders = fail_on, []

    def order(self, ticker, outcome, count, limit, tif="fill_or_kill", reduce_only=False):
        self.orders.append((ticker, outcome, count, limit, tif, reduce_only))
        return 0 if ticker == self.fail_on and not reduce_only else count


def test_execute_sells_back_filled_legs_when_one_misses():
    books = {"A": [(D("0.55"), 10)], "B": [(D("0.60"), 10)], "C": [(D("0.70"), 10)]}
    b = no_basket(event(), books, D(20))
    api = FakeApi(fail_on="B")
    assert not kl.execute(api, b)
    sells = [o for o in api.orders if o[5]]
    assert [(o[0], o[1]) for o in sells] == [("A", "yes")]  # sold A's NO back by buying YES
    assert sells[0][3] == 1 - (D("0.55") - D("0.05"))  # losing at most 5c a contract
    assert kl.execute(FakeApi(), b)


def test_sell_back_loss_is_booked_and_strays_are_tracked():
    books = {"A": [(D("0.55"), 10)], "B": [(D("0.60"), 10)], "C": [(D("0.70"), 10)]}
    b = no_basket(event(), books, D(20))
    state = {"realized": "0", "open": [], "closed": []}
    assert not kl.execute(FakeApi(fail_on="B"), b, state)
    assert D(state["realized"]) < 0 and state["open"] == []  # sold back at a (worst-case) loss

    class NoBuyers(FakeApi):
        def order(self, ticker, outcome, count, limit, tif="fill_or_kill", reduce_only=False):
            return 0 if reduce_only else super().order(ticker, outcome, count, limit, tif, reduce_only)

    state = {"realized": "0", "open": [], "closed": []}
    assert not kl.execute(NoBuyers(fail_on="B"), b, state)
    assert D(state["realized"]) == 0 and state["open"][0]["legs"][0]["ticker"] == "A"  # held until it settles
    cfg = {"budget": D(20), "step": D("0.25"), "min_settled": 5}
    assert kl.free_budget(cfg, state) < 20  # the stray's cost isn't available to bet


def test_candidates_need_mutually_exclusive_events_closing_soon():
    soon = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    later = (datetime.now(timezone.utc) + timedelta(days=400)).isoformat()
    mk = lambda t, c: {"ticker": t, "status": "active", "close_time": c}
    events = [{"event_ticker": "OK", "mutually_exclusive": True, "markets": [mk("a", soon), mk("b", soon)]},
              {"event_ticker": "NOTME", "mutually_exclusive": False, "markets": [mk("a", soon), mk("b", soon)]},
              {"event_ticker": "LATE", "mutually_exclusive": True, "markets": [mk("a", later), mk("b", later)]}]
    cfg = {"max_days": 60}
    assert [e["event_ticker"] for e, _ in kl.candidates(events, cfg)] == ["OK", "NOTME"]  # ladders don't need "only one wins"


def test_sweep_and_logs_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setattr(kl, "DATA", tmp_path)
    soon = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    mk = lambda t, bid: {"ticker": t, "status": "active", "close_time": soon, "yes_bid_dollars": bid, "yes_bid_size_fp": "10.00",
                         "yes_ask_dollars": "0.99", "yes_ask_size_fp": "1.00"}
    ev = {"event_ticker": "EV", "series_ticker": "SER", "title": "t", "mutually_exclusive": True,
          "markets": [mk("A", "0.4500"), mk("B", "0.4000"), mk("C", "0.3000")]}

    class Api:
        def open_events(self):
            return [ev]

        def orderbooks(self, tickers):
            return {m["ticker"]: {"yes_dollars": [[m["yes_bid_dollars"], "10.00"]]} for m in ev["markets"]}

    cfg = {"max_days": 60, "max_sets": 50, "min_profit": D("0.10")}
    events, baskets = kl.sweep(Api(), cfg, D(20))
    good = [b for b in baskets if b.locked]
    assert len(good) == 1 and good[0].profit >= D("0.10")
    when = datetime.now(timezone.utc)
    kl.log_prices(events, when)
    kl.log_baskets(baskets, set(), when, D("0.10"))
    ranked = kl.update_scorecard(events, baskets, D("0.10"))
    assert ranked[0]["series"] == "SER" and ranked[0]["opportunities"] == 1
    assert (tmp_path / "opportunities.csv").exists() and list((tmp_path / "prices").iterdir())


def test_stake_steps_up_only_after_real_growth():
    assert stake(D(20), D(0), 0) == 20
    assert stake(D(20), D("4.99"), 10) == 20  # not 25% up yet: extra profit is kept aside
    assert stake(D(20), D(5), 10) == 25
    assert stake(D(20), D(5), 4) == 20  # too few paid-out baskets
    assert stake(D(20), D("11.25"), 10) == D("31.25")
    assert stake(D(20), D(-3), 10) == 17  # below the start it bets only what's left
    assert stake(D(20), D(50), 10, step=D(0)) == 20  # step 0 = flat budget


def test_free_budget_uses_the_step_level():
    cfg = {"budget": D(20), "step": D("0.25"), "min_settled": 5}
    state = {"realized": "6", "open": [{"outlay": "8"}], "closed": [{}] * 5}
    assert kl.free_budget(cfg, state) == 17  # level $25, $8 in play


def rung(t, floor=None, cap=None, kind="greater"):
    return {"ticker": t, "strike_type": kind, "floor_strike": floor, "cap_strike": cap}


def test_ladder_rungs_imply_each_other():
    assert implies(rung("A105", 105), rung("A100", 100))
    assert not implies(rung("A100", 100), rung("A105", 105))
    assert implies(rung("B60", cap=60, kind="less"), rung("B65", cap=65, kind="less_or_equal"))
    assert not implies(rung("A100", 100), rung("B65", cap=65, kind="less"))
    assert not implies(rung("A100", 100), rung("A100b", 100, kind="greater_or_equal"))  # same strike: skip


def test_backwards_ladder_locks_in_a_dollar_a_pair():
    markets = [rung("A100", 100), rung("A105", 105)]
    # "above 105" bid at 0.50 while "above 100" is offered at 0.40: NO 105 costs 0.50, YES 100 costs 0.40.
    no_asks = {"A105": [(D("0.50"), 10)], "A100": [(D("0.45"), 10)]}
    yes_asks = {"A100": [(D("0.40"), 10)], "A105": [(D("0.55"), 10)]}
    b = best_ladder(event(), markets, no_asks, yes_asks, D(20))
    assert {(l.ticker, l.side) for l in b.legs} == {("A105", "no"), ("A100", "yes")}
    assert b.payout_min == b.sets and b.profit == b.sets * D("0.10") - b.fees and b.profit >= D("0.10")
    fair = {"A100": [(D("0.60"), 10)], "A105": [(D("0.55"), 10)]}
    assert best_ladder(event(), markets, no_asks, fair, D(20)) is None
