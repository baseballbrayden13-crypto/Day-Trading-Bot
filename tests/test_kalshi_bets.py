import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

from bot import kalshi_bets as kb


def test_strike_ranges_and_probabilities():
    assert kb.strike_range({"strike_type": "between", "floor_strike": 85, "cap_strike": 86}, integer=True) == (84.5, 86.5)
    assert kb.strike_range({"strike_type": "greater", "floor_strike": 86}, integer=True) == (86.5, math.inf)
    assert kb.strike_range({"strike_type": "less", "cap_strike": 79}, integer=True) == (-math.inf, 78.5)
    assert kb.strike_range({"strike_type": "greater", "floor_strike": 100000}) == (100000.0, math.inf)
    assert kb.strike_range({"strike_type": "custom"}) is None
    # a ladder of buckets covering everything sums to 1
    edges = [-math.inf, 70.5, 72.5, 74.5, math.inf]
    total = sum(kb.prob_normal((a, b), 72.0, 2.0) for a, b in zip(edges, edges[1:]))
    assert abs(total - 1) < 1e-9
    assert abs(kb.prob_lognormal((100.0, math.inf), 100.0, 0.02) - 0.5) < 0.01  # at the money ~ 50%
    assert kb.prob_lognormal((120.0, math.inf), 100.0, 0.02) < 1e-6


def test_best_side_needs_edge_and_ten_cents_expected():
    m = {"yes_ask_dollars": "0.30", "yes_bid_dollars": "0.28", "yes_ask_size_fp": "100", "yes_bid_size_fp": "100"}
    side, count, price, fee, p = kb.best_side(m, 0.50, D("2"), 0.05, D("0.10"))
    assert side == "yes" and price == D("0.30") and count == 6 and fee > 0
    assert kb.best_side(m, 0.32, D("2"), 0.05, D("0.10")) is None  # 2c edge: too thin
    side, *_ = kb.best_side(m, 0.10, D("2"), 0.05, D("0.10"))
    assert side == "no"  # model says YES is overpriced: buy NO at 0.72
    thin = {**m, "yes_ask_size_fp": "1"}
    assert kb.best_side(thin, 0.40, D("2"), 0.05, D("0.10")) is None  # 1 contract can't expect 10c at a 10c edge


def test_event_date_and_hourly_sigma():
    assert kb.event_date("KXHIGHNY-26OCT27") == date(2026, 10, 27)
    assert kb.event_date("KXHIGHNY") is None
    assert kb.hourly_sigma([100.0] * 20) == 0.0
    assert kb.hourly_sigma([100 * (1.01 if i % 2 else 1) for i in range(40)]) > 0.005


def _event(series, ticker, markets):
    return {"series_ticker": series, "event_ticker": ticker, "markets": markets}


def test_weather_bets_against_the_forecast():
    now = datetime(2026, 10, 27, 1, 0, tzinfo=timezone.utc)  # 9pm ET the evening before
    close = (now + timedelta(hours=27)).isoformat()
    mk = lambda t, lo, hi, bid, ask: {"ticker": t, "status": "active", "strike_type": "between", "floor_strike": lo,
                                      "cap_strike": hi, "yes_bid_dollars": bid, "yes_ask_dollars": ask,
                                      "yes_bid_size_fp": "50", "yes_ask_size_fp": "50", "close_time": close}
    e = _event("KXHIGHNY", "KXHIGHNY-26OCT27", [mk("A", 60, 61, "0.10", "0.12"), mk("B", 70, 71, "0.40", "0.42")])
    cfg = {"stake": D("2"), "min_edge": 0.05, "min_profit": D("0.10")}
    bets = kb.weather([e], now, cfg, data={"KXHIGHNY": {date(2026, 10, 27): 61.0}})
    by = {b.ticker: b for b in bets}
    assert by["A"].side == "yes" and by["A"].prob > 0.2  # forecast 61F: 60-61 is far likelier than 12c
    assert by["B"].side == "no"  # and 70-71 is very unlikely
    assert all(b.expected >= D("0.10") for b in bets)


def test_crypto_and_favorites():
    now = datetime(2026, 10, 27, 18, 0, tzinfo=timezone.utc)
    m = {"ticker": "BTC-110K", "status": "active", "strike_type": "greater", "floor_strike": 110000,
         "yes_bid_dollars": "0.30", "yes_ask_dollars": "0.32", "yes_bid_size_fp": "100", "yes_ask_size_fp": "100",
         "close_time": (now + timedelta(hours=3)).isoformat()}
    cfg = {"stake": D("2"), "min_edge": 0.05, "min_profit": D("0.10")}
    bets = kb.crypto([_event("KXBTCD", "KXBTCD-26OCT2717", [m])], now, cfg, data={"BTC-USD": (100000.0, 0.005)})
    assert len(bets) == 1 and bets[0].side == "no"  # 10% away in 3 hours at 0.5%/h: almost never
    fav = {**m, "ticker": "FAV", "strike_type": "", "yes_bid_dollars": "0.85", "yes_ask_dollars": "0.86",
           "close_time": (now + timedelta(hours=24)).isoformat()}
    f = kb.favorites([_event("X", "X-1", [fav])], now, cfg)
    assert len(f) == 1 and f[0].side == "no" and D(f[0].price) == D("0.15")
    assert not kb.favorites([_event("X", "X-1", [{**fav, "close_time": (now + timedelta(hours=3)).isoformat()}])], now, cfg)


def test_paper_book_places_settles_and_keeps_pots_apart(tmp_path, monkeypatch):
    monkeypatch.setattr(kb, "STATE", tmp_path / "s.json")
    monkeypatch.setattr(kb, "DATA", tmp_path / "d")
    state = kb.load_state()
    mk = lambda strat, t, ev, n, price: kb.Bet(strat, t, ev, "S", "yes", n, price, "0.02", 0.9, "", "now")
    placed = kb.place(state, [mk("weather", "T1", "E1", 10, "0.50"), mk("weather", "T2", "E1", 10, "0.50"),
                              mk("crypto", "T3", "E2", 10, "0.50")], D(20))
    assert [b.ticker for b in placed] in (["T1", "T3"], ["T3", "T1"])  # one bet per event per strategy
    assert kb.pot(state, "weather", D(20)) == (D(20), D("14.98"))
    big = mk("weather", "T4", "E3", 40, "0.50")  # $20 + fee: more than the free $14.98
    assert not kb.place(state, [big], D(20))

    class Api:
        def market(self, t):
            return {"result": "yes" if t == "T1" else ""}
    assert kb.settle(Api(), state) == 1
    s = kb.summary(state, D(20), datetime.now(timezone.utc))
    assert s["strategies"]["weather"]["realized_profit"] == "4.98" and s["strategies"]["crypto"]["open_bets"] == 1
    assert (tmp_path / "d" / "summary.json").exists()
