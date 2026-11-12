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
    assert fleet.rescale(3, "2026-11-11", 2500) == pytest.approx(1666)
    assert fleet.rescale(3, "2026-11-12", 1666) == 1666
    assert fleet.rescale(10, "2026-11-11", 2500) == pytest.approx(1667)


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
