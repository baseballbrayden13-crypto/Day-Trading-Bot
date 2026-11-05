import numpy as np
import pandas as pd

from bot import dipbuy_live as db


def closes(**paths):
    idx = pd.bdate_range("2025-01-01", periods=260)
    return pd.DataFrame({s: p for s, p in paths.items()}, index=idx)


def test_dip_in_uptrend_is_bought_and_downtrend_dip_is_not():
    up = np.linspace(100, 200, 260)
    up[-2:] = [up[-3] * 0.97, up[-3] * 0.94]  # two sharp down days near the high
    down = np.linspace(200, 100, 260)
    down[-2:] = [down[-3] * 0.97, down[-3] * 0.94]
    dips, bounced = db.signals(closes(UP=up, DOWN=down))
    assert dips == ["UP"]
    assert "UP" not in bounced


def test_bounced_stock_is_sold():
    up = np.linspace(100, 200, 260)
    _, bounced = db.signals(closes(UP=up))
    assert "UP" in bounced


def test_plan_sells_bounced_and_stale_and_fills_free_slots_in_rank_order():
    held = {"A": 1, "B": 1, "C": 1}
    sells, buys = db.plan(held, {"A": 2, "B": 10, "C": 1}, ["X", "A", "Y", "Z"], {"C"}, slots=4, max_days=10)
    assert sells == ["B", "C"]
    assert buys == ["X", "Y", "Z"]


def test_plan_never_exceeds_slots():
    sells, buys = db.plan({"A": 1, "B": 1}, {}, ["X", "Y"], set(), slots=2, max_days=10)
    assert sells == [] and buys == []


def test_trading_days_since_entry():
    idx = pd.bdate_range("2026-11-02", periods=5)
    assert db.trading_days_since(idx, "2026-11-03") == 3


def test_too_little_history_means_no_signals():
    assert db.signals(closes(A=np.ones(260)).iloc[:100]) == ([], set())


# --- shared accounts (bot.sleeves) ---
import pytest  # noqa: E402

from bot import sleeves  # noqa: E402


def test_budgets_parse():
    assert sleeves.budgets("2=5000, 5=2500.5") == {"2": 5000.0, "5": 2500.5}
    assert sleeves.budgets("") == {}


def test_new_sleeve_adopts_its_own_positions_and_ignores_the_other_bots():
    ledger = {}
    acct = {"XLP": 10, "AAPL": 2}
    s2 = sleeves.open_sleeve(ledger, "2", ["XLP", "SPY"], 5000, acct, {"XLP": 90, "AAPL": 300})
    assert s2.shares == {"XLP": 10} and s2.cash == 4100
    s5 = sleeves.open_sleeve(ledger, "5", ["AAPL", "MSFT"], 5000, acct, {"AAPL": 300})
    assert s5.shares == {"AAPL": 2} and s5.cash == 4400


def test_sleeve_value_and_fills():
    ledger = {}
    s = sleeves.open_sleeve(ledger, "5", ["AAPL"], 1000, {}, {})
    s.record("AAPL", 2, 300)
    assert s.cash == 400 and s.value({"AAPL": 310}) == 1020
    s.record("AAPL", -2, 320)
    assert s.shares == {} and s.cash == 1040
    with pytest.raises(ValueError):
        s.record("XLP", 1, 90)  # never another bot's symbol


def test_bots_on_one_account_cannot_share_symbols():
    with pytest.raises(SystemExit):
        sleeves.open_sleeve({}, "5", ["AAPL", "SPY"], 1000, {}, {}, others={"2": ["SPY", "QQQ"]})


def test_default_lists_are_disjoint():
    from bot.rotation import DEFAULT

    assert not set(DEFAULT.split(",")) & set(db.SYMBOLS.split(","))


def test_account_check_flags_missing_shares():
    ledger = {"5": {"cash": 0, "shares": {"AAPL": 3}}, "2": {"cash": 0, "shares": {"XLP": 1}}}
    assert sleeves.check_account(ledger, {"AAPL": 3, "XLP": 1}) == []
    assert sleeves.check_account(ledger, {"AAPL": 1, "XLP": 1}) == ["AAPL: sleeves own 3, account holds 1"]


def test_sleeves_open_only_once_the_account_is_funded():
    assert not sleeves.ready({}, {"2": 5000, "5": 5000}, 4936)
    assert sleeves.ready({}, {"2": 5000, "5": 5000}, 10000)
    assert sleeves.ready({"2": {}, "5": {}}, {"2": 5000, "5": 5000}, 4000)  # already open: losses don't close them
