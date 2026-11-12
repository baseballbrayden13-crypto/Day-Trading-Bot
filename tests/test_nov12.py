"""Nov 12 2026: bot 7 (momentum), the KTS7 three-way split, bot 6 on QLD, bot 1's news filter."""
from datetime import datetime

import pandas as pd
import pytest

from bot import fleet, momentum_live, news, sleeves, trend_live


def closes(n=300):
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({"A": [100 + i for i in range(n)], "B": [100.0] * n, "C": [300 - i * 0.5 for i in range(n)],
                         "D": [100 + 2 * i for i in range(n)]}, index=idx)


def test_momentum_picks_best_12_1_month_gain():
    assert momentum_live.picks(closes(), top=2) == ["D", "A"]
    assert momentum_live.picks(closes(200), top=2) == []  # needs 253 days


def test_momentum_skips_the_last_month():
    c = closes()
    c.iloc[-21:, c.columns.get_loc("B")] = 1000.0  # a jump inside the skipped month doesn't count
    assert "B" not in momentum_live.picks(c, top=2)


def test_momentum_plan_and_due():
    assert momentum_live.plan(["A", "D"], {"A": 1.0, "C": 2.0}) == (["C"], ["D"])
    today = datetime(2026, 12, 1).date()
    assert momentum_live.due({"month": "2026-11"}, today, {"A": 1.0})
    assert not momentum_live.due({"month": "2026-12"}, today, {"A": 1.0})
    assert momentum_live.due({"month": "2026-12"}, today, {})  # nothing held yet: buy now


def test_resize_moves_cash_once():
    ledger = {"3": {"start": 2500, "cash": 2500.0, "shares": {}},
              "6": {"start": 2500, "cash": 25.0, "shares": {"BIL": 27.0}}}
    shared = {"3": 1666, "6": 1667, "7": 1667}
    assert len(sleeves.resize(ledger, shared)) == 2
    assert ledger["3"]["cash"] == pytest.approx(1666) and ledger["6"]["cash"] == pytest.approx(25 - 833)
    assert sleeves.resize(ledger, shared) == []  # idempotent
    assert "7" not in ledger  # new slices are opened by their own bot


def test_cover_qty():
    assert sleeves.cover_qty(-808.0, 91.5, 27.0) == pytest.approx(808 * 1.01 / 91.5, rel=1e-4)
    assert sleeves.cover_qty(10.0, 91.5, 27.0) == 0
    assert sleeves.cover_qty(-5000.0, 91.5, 27.0) == 27.0


def test_rescale_applies_every_later_split():
    assert fleet.rescale(3, "2026-11-09", 5000) == pytest.approx(5000 * 0.5 * 1666 / 2500)
    assert fleet.rescale(3, "2026-11-10", 2500) == pytest.approx(1666)
    assert fleet.rescale(3, "2026-11-11", 1666) == 1666
    assert fleet.rescale(10, "2026-11-10", 2500) == pytest.approx(1667)


def test_trend_pick_uses_signal_series():
    q = pd.Series([100.0] * 199 + [120.0])
    assert trend_live.pick(q, 200, "QLD", "BIL") == "QLD"
    assert trend_live.pick(pd.Series([100.0] * 199 + [90.0]), 200, "QLD", "BIL") == "BIL"


def test_news_window_and_own_headlines():
    et = news.ET
    assert news.window_start(datetime(2026, 11, 16, 10, 0, tzinfo=et)) == datetime(2026, 11, 13, 16, 0, tzinfo=et)  # Mon -> Fri
    arts = [{"headline": "Market up", "symbols": ["AAPL", "MSFT", "NVDA"]}, {"headline": "Apple news", "symbols": ["AAPL"]}]
    assert news.own_headlines(arts, "AAPL") == ["Apple news"]
    assert news.own_headlines(arts[:1], "AAPL") == []


def test_has_news_fails_open_and_caches():
    news._seen.clear()
    now = datetime(2026, 11, 12, 10, 0, tzinfo=news.ET)
    def boom(*a):
        raise OSError("down")
    assert news.has_news("AAPL", now, "k", "s", fetcher=boom)
    assert not news.has_news("MSFT", now, "k", "s", fetcher=lambda *a: [])
    calls = []
    def one(*a):
        calls.append(1)
        return [{"headline": "x", "symbols": ["NVDA"]}]
    assert news.has_news("NVDA", now, "k", "s", fetcher=one) and news.has_news("NVDA", now, "k", "s", fetcher=one)
    assert len(calls) == 1


def test_bots_on_kts7_trade_different_symbols():
    kts7 = [b for b in fleet.FLEET if b.account == "KTS7"]
    assert sorted(b.label or str(b.num) for b in kts7) == ["3", "6", "7"]
    seen = set()
    for b in kts7:
        assert not (set(b.symbols) & seen)
        seen |= set(b.symbols)


def _series(start, days, daily):
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return {(d0 + timedelta(days=i)).isoformat(): 1000 * (1 + daily) ** i for i in range(days)}


def test_draft_swaps_worst_member_for_best_rookie(monkeypatch):
    from bot import army_fund as af
    monkeypatch.setattr(af, "BOTS", {"1": 1, "2": 2})
    eq = {"1": _series("2026-11-01", 40, 0.001), "2": _series("2026-11-01", 40, -0.002),
          "R1": _series("2026-11-01", 40, 0.003), "R2": _series("2026-11-25", 10, 0.01)}  # R2: too new to judge
    assert af.draft(["1", "2"], eq, "2026-12-01")[:2] == ("2", "R1")
    assert af.draft(["1", "R1"], eq, "2026-12-01") is None  # the bench (bot 2) did worse: no swap
    state = {}
    for day in sorted(eq["1"]):
        state = af.step(state, eq, day)
    assert state["members"] == ["1", "R1"] and state["benched"] == ["2"]
    assert state["drafts"][0][:3] == ["2026-12-01", "2", "R1"]
    assert set(state["units"]) == {"1", "R1"} and set(state["even_units"]) == {"1", "2"}
    before = state["history"][-2][1]
    assert state["history"][-1][1] == pytest.approx(before, rel=0.02)  # a draft moves money, it doesn't create it


def test_army_fund_survives_a_new_split(monkeypatch):
    from bot import army_fund as af
    monkeypatch.setattr(af, "BOTS", {"3": 3})
    state = {"start": "2026-11-02", "week": "2026-W46", "units": {"3": 2.0}, "even_units": {"3": 2.0}, "history": []}
    eq = {"3": {"2026-11-10": 1666.0, "2026-11-12": 1666.0}}  # history already scaled to the new third
    state = af.step(state, eq, "2026-11-12")
    assert state["history"][-1][1] == pytest.approx(2.0 * 2500)  # the slice is worth what it was before the split


def test_rookie_advance_earns_then_rebalances():
    from bot import rookies
    idx = pd.bdate_range("2026-01-01", periods=3)
    c = pd.DataFrame({"QQQ": [100.0, 100.0, 110.0], "BIL": [90.0, 90.0, 90.0]}, index=idx)
    rule = lambda closes, old, new_month: {"QQQ": 1.0}
    b = rookies.advance({}, c.iloc[:2], rule)
    assert b["equity"] == pytest.approx(1000 * (1 - 0.0005)) and b["weights"] == {"QQQ": 1.0}
    b2 = rookies.advance(b, c, rule)
    assert b2["equity"] == pytest.approx(b["equity"] * 1.10)
    assert rookies.advance(b2, c, rule) is b2  # same day twice changes nothing


def test_income_rookie_holds_the_four_etfs_evenly():
    from bot import rookies
    idx = pd.bdate_range("2026-01-01", periods=2)
    c = pd.DataFrame({s: [50.0, 51.0] for s in rookies.INCOME} | {"QQQ": [1.0, 1.0]}, index=idx)
    w = rookies.income(c, {}, True)
    assert w == {s: 0.25 for s in rookies.INCOME}
    assert rookies.income(c, {"SCHD": 1.0}, False) == {"SCHD": 1.0}  # only evened out on a new month
