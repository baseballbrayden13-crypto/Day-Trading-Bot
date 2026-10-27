import dataclasses
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from bot.backtest import run_backtest
from bot.config import Settings
from bot.risk import RiskManager
from bot.strategy import add_indicators, rsi

ET = ZoneInfo("America/New_York")


def synthetic_bars(days=10, seed=0, drift=0.0, gap_sd=0.0):
    rng = np.random.default_rng(seed)
    idx = []
    for d in pd.bdate_range("2026-03-02", periods=days):
        start = pd.Timestamp(d.date()).tz_localize(ET) + pd.Timedelta(hours=9, minutes=30)
        idx += list(pd.date_range(start, periods=78, freq="5min"))
    idx = pd.DatetimeIndex(idx).tz_convert("UTC")
    steps = rng.normal(drift, 0.002, len(idx))
    if gap_sd:
        steps[::78] += rng.normal(0, gap_sd, days)  # overnight gap at each open
    close = 100 * np.exp(np.cumsum(steps))
    open_ = np.r_[close[0], close[:-1]]
    if gap_sd:
        open_[::78] = close[::78] / np.exp(rng.normal(0, 0.002, days))  # open near the gapped first close
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.001, len(idx)))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.001, len(idx)))
    vol = rng.integers(1_000, 10_000, len(idx))
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)


def test_rsi_bounds():
    r = rsi(synthetic_bars()["close"], 14)
    assert r.between(0, 100).all()


def test_indicators_have_no_lookahead():
    df = synthetic_bars()
    full = add_indicators(df, Settings())
    partial = add_indicators(df.iloc[:200], Settings())
    pd.testing.assert_frame_equal(full.iloc[:200], partial)


def test_position_size_respects_risk_and_cap():
    cfg = Settings()
    rm = RiskManager(cfg)
    qty = rm.position_size(equity=25_000, price=100, stop=98)  # $2 risk/share
    assert qty * 2 <= 25_000 * cfg.risk_per_trade + 1e-9
    assert qty * 100 <= 25_000 * cfg.max_position_pct
    assert rm.position_size(25_000, 100, 101) == 0  # stop above price is invalid


def test_daily_loss_halts_trading():
    rm = RiskManager(Settings())
    rm.new_day(datetime(2026, 3, 2).date(), 10_000)
    rm.check_daily_loss(9_790)
    assert rm.halted
    ok, why = rm.can_enter("SPY", datetime(2026, 3, 2, 11, 0, tzinfo=ET))
    assert not ok and "daily loss" in why


def test_entry_window():
    rm = RiskManager(Settings())
    assert not rm.in_entry_window(datetime(2026, 3, 2, 9, 35, tzinfo=ET))
    assert rm.in_entry_window(datetime(2026, 3, 2, 11, 0, tzinfo=ET))
    assert rm.must_flatten(datetime(2026, 3, 2, 15, 55, tzinfo=ET))


def test_backtest_runs_and_ends_flat():
    frames = {"AAA": synthetic_bars(seed=1), "BBB": synthetic_bars(seed=2)}
    res = run_backtest(frames, Settings(), 25_000)
    log = res["trade_log"]
    if len(log):
        # every trade closes the same day (no overnight holds)
        same_day = log["entry_time"].dt.tz_convert(ET).dt.date == log["exit_time"].dt.tz_convert(ET).dt.date
        assert same_day.all()
    assert abs(res["final_equity"] - (25_000 + (log["pnl"].sum() if len(log) else 0))) < 1e-6


def test_market_filter_blocks_entries_when_market_weak(monkeypatch):
    monkeypatch.setenv("MARKET_FILTER", "MKT")
    frames = {"AAA": synthetic_bars(seed=1)}
    weak = synthetic_bars(seed=3, drift=-0.002)  # steadily falling, so stays below VWAP
    filtered = run_backtest(frames, Settings(), 25_000, market=weak)
    no_market_data = run_backtest(frames, Settings(), 25_000, market=None)
    monkeypatch.delenv("MARKET_FILTER")
    baseline = run_backtest(frames, Settings(), 25_000)
    assert filtered["trades"] < baseline["trades"]
    assert no_market_data["trades"] == 0  # filter on but no market data means no entries


def test_orb_breaks_at_most_once_a_day_and_after_the_range():
    df = add_indicators(synthetic_bars(days=10, seed=4), Settings())
    breaks = df[df["orb_break"]]
    days = breaks.index.tz_convert(ET).date
    assert len(set(days)) == len(days)  # once per day
    et = breaks.index.tz_convert(ET)
    assert ((et.hour * 60 + et.minute) >= 9 * 60 + 45).all()  # only after the 15-min range closes


def test_orb_max_per_day_allows_repeat_breakouts(monkeypatch):
    monkeypatch.setenv("ORB_MAX_PER_DAY", "3")
    df = add_indicators(synthetic_bars(days=10, seed=4), Settings())
    per_day = df[df["orb_break"]].groupby(df[df["orb_break"]].index.tz_convert(ET).date).size()
    assert per_day.max() <= 3
    one = add_indicators(synthetic_bars(days=10, seed=4), Settings(orb_max_per_day=1))
    assert one["orb_break"].sum() <= df["orb_break"].sum()


def test_orb_backtest_runs(monkeypatch):
    monkeypatch.setenv("STRATEGY", "orb")
    res = run_backtest({"AAA": synthetic_bars(seed=1)}, Settings(), 25_000)
    assert set(res["trade_log"].get("exit_reason", [])) <= {"stop", "target", "end of day", "end of test", "daily loss halt"}


def test_report_pairs_buys_with_sells():
    from types import SimpleNamespace as O

    from bot.report import round_trips

    t = pd.Timestamp("2026-10-23 14:00", tz="UTC")
    orders = [
        O(symbol="SPY", side="OrderSide.BUY", filled_qty="10", filled_avg_price="100", filled_at=t, order_type="market"),
        O(symbol="SPY", side="OrderSide.SELL", filled_qty="10", filled_avg_price="101", filled_at=t + pd.Timedelta("1h"),
          order_type="OrderType.LIMIT"),
        O(symbol="AAPL", side="OrderSide.BUY", filled_qty="5", filled_avg_price="200", filled_at=t, order_type="market"),
        O(symbol="AAPL", side="OrderSide.SELL", filled_qty="5", filled_avg_price="198", filled_at=t + pd.Timedelta("2h"),
          order_type="OrderType.STOP"),
    ]
    trips = {r["symbol"]: r for r in round_trips(orders)}
    assert trips["SPY"]["pnl"] == 10 and trips["SPY"]["exit_reason"] == "target"
    assert trips["AAPL"]["pnl"] == -10 and trips["AAPL"]["exit_reason"] == "stop"


def test_live_requires_both_flags(monkeypatch):
    monkeypatch.setenv("LIVE_TRADING", "true")
    monkeypatch.delenv("LIVE_TRADING_CONFIRM", raising=False)
    assert not Settings().is_live
    monkeypatch.setenv("LIVE_TRADING_CONFIRM", "I_UNDERSTAND_REAL_MONEY")
    assert Settings().is_live


def test_every_strategy_backtests_and_ends_flat():
    from bot.strategy import STRATEGIES

    frames = {"AAA": synthetic_bars(days=20, seed=1, gap_sd=0.01), "BBB": synthetic_bars(days=20, seed=2, gap_sd=0.01)}
    for name in STRATEGIES:
        res = run_backtest(frames, Settings(strategy=name), 25_000)
        log = res["trade_log"]
        assert len(log), f"{name} never traded on 20 days of random data"
        same_day = log["entry_time"].dt.tz_convert(ET).dt.date == log["exit_time"].dt.tz_convert(ET).dt.date
        assert same_day.all(), name


def test_mean_reversion_signals_target_above_entry_and_stop_below():
    from bot.strategy import bollinger_signal, vwap_reversion_signal

    cfg = Settings()
    df = add_indicators(synthetic_bars(days=20, seed=5), cfg)
    for fn in (vwap_reversion_signal, bollinger_signal):
        sigs = [fn("AAA", df.iloc[: i + 1], cfg) for i in range(30, len(df))]
        sigs = [s for s in sigs if s is not None]
        assert sigs, fn.__name__
        assert all(s.stop < s.price < s.target for s in sigs), fn.__name__


def test_unknown_strategy_is_a_clear_error():
    import pytest

    from bot.strategy import entry_signal

    with pytest.raises(ValueError, match="choose one of"):
        entry_signal("AAA", add_indicators(synthetic_bars(), Settings()), Settings(strategy="nope"))


def test_compare_runs_each_strategy():
    from bot.compare import compare
    from bot.strategy import STRATEGIES

    table = compare({"AAA": synthetic_bars(days=20, seed=1)}, Settings(), list(STRATEGIES))
    assert set(table.index) == set(STRATEGIES)


def test_backtest_charges_sell_fees():
    frames = {"AAA": synthetic_bars(days=20, seed=1)}
    free = run_backtest(frames, Settings(sec_fee_rate=0, taf_per_share=0), 25_000)
    paid = run_backtest(frames, Settings(), 25_000)
    assert paid["fees"] > 0 and free["fees"] == 0
    assert paid["final_equity"] < free["final_equity"]
    log = paid["trade_log"]
    assert abs(paid["final_equity"] - (25_000 + log["pnl"].sum())) < 1e-6


def test_taf_is_capped():
    from bot.backtest import sell_fees

    cfg = Settings(sec_fee_rate=0)
    assert sell_fees(1_000_000, 10, cfg) == cfg.taf_max


def test_daily_levels_use_only_finished_days():
    df = add_indicators(synthetic_bars(days=3, seed=1), Settings())
    days = df.index.tz_convert(ET).date
    first, second = df[days == days[0]], df[days == sorted(set(days))[1]]
    assert first["prev_high"].isna().all()
    assert (second["prev_high"] == first["high"].max()).all()
    assert (second["prev_close"] == first["close"].iloc[-1]).all()
    assert (second["day_open"] == second["open"].iloc[0]).all()


def test_orb_filters_only_remove_trades(monkeypatch):
    frames = {"AAA": synthetic_bars(days=20, seed=1), "BBB": synthetic_bars(days=20, seed=2)}
    base = run_backtest(frames, Settings(strategy="orb"), 25_000)["trades"]
    for kw in [dict(orb_vwap_filter=True), dict(orb_volume_mult=1.5), dict(orb_max_range_pct=0.3), dict(orb_gap="up")]:
        assert run_backtest(frames, Settings(strategy="orb", **kw), 25_000)["trades"] <= base, kw


def test_orb_mid_stop_is_tighter():
    from bot.strategy import orb_signal

    df = add_indicators(synthetic_bars(days=10, seed=4), Settings())
    i = int(np.flatnonzero(df["orb_break"].to_numpy())[0])
    low = orb_signal("AAA", df.iloc[: i + 1], Settings(orb_stop="low"))
    mid = orb_signal("AAA", df.iloc[: i + 1], Settings(orb_stop="mid"))
    assert low.stop < mid.stop < mid.price


def test_research_scores_in_and_out_of_sample_separately():
    from bot import research

    frames = {"AAA": synthetic_bars(days=20, seed=1)}
    split = frames["AAA"].index[len(frames["AAA"]) // 2]
    research._init(frames, None, split, 25_000)
    r = research.evaluate(Settings(strategy="orb"))
    whole = run_backtest(frames, Settings(strategy="orb"), 25_000)
    assert r["is"]["trades"] + r["oos"]["trades"] == whole["trades"]
    assert abs(r["is"]["pnl"] + r["oos"]["pnl"] - whole["trade_log"]["pnl"].sum()) < 1e-6
    assert not research.better(r, r)  # equal is not an improvement


def test_gap_min_pct_needs_a_bigger_gap():
    from bot.strategy import orb_signal

    df = add_indicators(synthetic_bars(days=20, seed=4, gap_sd=0.01), Settings())
    for i in np.flatnonzero(df["orb_break"].to_numpy()):
        row = df.iloc[i]
        gap = (row["day_open"] / row["prev_close"] - 1) * 100
        if np.isnan(gap):
            continue
        any_down = orb_signal("A", df.iloc[: i + 1], Settings(orb_gap="down"))
        big_down = orb_signal("A", df.iloc[: i + 1], Settings(orb_gap="down", orb_gap_min_pct=0.5))
        assert (any_down is not None) == (gap < 0)
        assert (big_down is not None) == (gap <= -0.5)


def test_sweep_parses_a_grid():
    from bot.sweep import parse_sets

    combos = parse_sets(["ORB_TARGET_R=1,2", "ORB_GAP=any,down", "ORB_VWAP_FILTER=true"], Settings())
    assert len(combos) == 4
    assert {"orb_target_r": 2.0, "orb_gap": "down", "orb_vwap_filter": True} in combos
    assert parse_sets([], Settings()) == [{}]


def test_breakeven_and_trailing_stops_only_rise():
    from bot.backtest import Position, raise_stop
    cfg = dataclasses.replace(Settings(), stop_breakeven_r=1.0, stop_trail_r=1.5)
    p = Position("X", 10, 100.0, 98.0, 106.0, pd.Timestamp("2026-03-02", tz="UTC"), 2.0, 100.0)
    raise_stop(p, 101.0, cfg)
    assert p.stop == 98.0  # not up 1R yet; trail (101 - 3) is still below the stop
    raise_stop(p, 102.5, cfg)
    assert p.stop == 100.0  # reached 1R: breakeven
    raise_stop(p, 104.0, cfg)
    assert p.stop == 101.0  # trails 1.5R (3.00) under the high
    raise_stop(p, 103.0, cfg)
    assert p.stop == 101.0  # never lowered


def test_fill_tracker_measures_slippage(tmp_path):
    from types import SimpleNamespace as NS
    from bot.fills import check, log_order, slippage_bps, summary
    import csv

    assert slippage_bps(100, 100.05, "buy") == pytest.approx(5)
    assert slippage_bps(100, 99.95, "sell") == pytest.approx(5)
    path = tmp_path / "signals.csv"
    log_order("AAPL", 10, 200.0, 198.0, 203.0, "o1", path)
    log_order("NVDA", 5, 100.0, 99.0, 101.5, "o2", path)
    orders = {
        "o1": NS(filled_avg_price="200.04", legs=[NS(filled_avg_price="197.98", order_type="stop"),
                                                  NS(filled_avg_price=None, order_type="limit")]),
        "o2": NS(filled_avg_price=None, legs=[]),  # never filled
    }
    rows = check(list(csv.DictReader(path.open())), orders.get)
    assert len(rows) == 1
    assert rows[0]["entry_bps"] == pytest.approx(2.0)
    assert rows[0]["exit"] == "stop" and rows[0]["exit_bps"] == pytest.approx(1.01, abs=0.01)
    assert "as good as the backtest" in summary(rows)


def test_limit_entries_fill_only_at_or_under_the_limit():
    from bot.backtest import entry_fill
    cfg = Settings()
    bar = {"open": 100.10, "low": 99.95}
    assert entry_fill(100.0, bar, cfg) == pytest.approx(100.10 * (1 + cfg.slippage_bps / 10_000))  # market
    lim = dataclasses.replace(cfg, entry_limit_bps=5)
    assert entry_fill(100.0, bar, lim) == pytest.approx(100.05)  # opened above the limit, dipped back to it
    assert entry_fill(100.0, {"open": 100.10, "low": 100.08}, lim) is None  # never came back: no fill
    assert entry_fill(100.0, {"open": 99.90, "low": 99.80}, lim) == pytest.approx(99.90)  # better open


def test_short_orb_books_profit_when_price_falls_and_cash_adds_up():
    frames = {"AAA": synthetic_bars(days=30, seed=3, gap_sd=0.01), "BBB": synthetic_bars(days=30, seed=4, gap_sd=0.01)}
    for name in ("orb", "orb_short"):
        res = run_backtest(frames, Settings(strategy=name), 25_000)
        log = res["trade_log"]
        assert len(log), name
        # the equity curve and the trade log must agree: every dollar is accounted for
        assert res["final_equity"] == pytest.approx(25_000 + log["pnl"].sum(), abs=0.01), name
    log = run_backtest(frames, Settings(strategy="orb_short"), 25_000)["trade_log"]
    assert (log["side"] == "short").all()
    wins = log[log["exit"] < log["entry"]]
    assert (wins["pnl"] > -wins["fees"]).all()  # covering lower than the short price makes money before costs
    stops = log[log["exit_reason"] == "stop"]
    assert (stops["exit"] > stops["entry"]).all()  # a short's stop is above the entry


def test_short_stops_move_down_only():
    from bot.backtest import Position, raise_stop
    cfg = dataclasses.replace(Settings(), stop_breakeven_r=1.0, stop_trail_r=1.5)
    p = Position("X", 10, 100.0, 102.0, 94.0, pd.Timestamp("2026-03-02", tz="UTC"), 2.0, 100.0, True)
    raise_stop(p, 97.5, cfg)
    assert p.stop == 100.0  # down 1R: breakeven
    raise_stop(p, 96.0, cfg)
    assert p.stop == 99.0  # trails 1.5R above the low
    raise_stop(p, 98.0, cfg)
    assert p.stop == 99.0


def synthetic_daily(days=900, seed=0, drift=0.0004):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.015, days)))
    open_ = close * np.exp(rng.normal(0, 0.004, days))
    idx = pd.bdate_range("2020-01-01", periods=days, tz="UTC")
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.005,
                         "low": np.minimum(open_, close) * 0.995, "close": close, "volume": 1e6}, index=idx)


def test_swing_rules_trade_and_account_for_every_dollar():
    from bot.swing import RULES, run_swing
    frames = {"AAA": synthetic_daily(seed=1), "BBB": synthetic_daily(seed=2), "CCC": synthetic_daily(seed=3)}
    for rule in RULES:
        res = run_swing(frames, rule, Settings(), 5_000, slots=2)
        t = res["trades"]
        assert len(t), rule
        assert res["final"] == pytest.approx(5_000 + t["pnl"].sum(), abs=0.01), rule
        assert (t["exit_time"] > t["entry_time"]).all(), rule  # never sells on the day it buys
        assert (t["qty"] * t["entry"] <= 5_000 / 2 * 1.5).all(), rule  # roughly one slot each


def test_alerts_are_off_without_a_topic_and_never_raise(monkeypatch):
    from bot import notify
    assert notify.send(Settings(), "t", "m") is False  # no NTFY_TOPIC: nothing sent

    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(notify.urllib.request, "urlopen", boom)
    assert notify.send(dataclasses.replace(Settings(), ntfy_topic="x"), "t", "m") is False


def test_live_entry_uses_a_limit_only_when_asked(monkeypatch):
    from types import SimpleNamespace as NS
    from bot import live
    from bot.strategy import Signal

    calls = []
    broker = NS(equity=lambda: 5_000.0, open_symbols=lambda: set(), close_all=lambda: None,
                cancel_unfilled_entries=lambda: calls.append("cancel") or [],
                buy_bracket=lambda sym, qty, stop, target, limit=None: calls.append(limit) or NS(id="o1"))
    monkeypatch.setattr(live, "from_alpaca", lambda *a, **k: synthetic_bars(days=2))
    monkeypatch.setattr(live, "add_indicators", lambda df, cfg: df)
    monkeypatch.setattr(live, "entry_signal", lambda sym, bars, cfg: Signal(sym, "buy", 100.0, 99.0, 101.5, "test"))
    monkeypatch.setattr(live, "log_order", lambda *a, **k: None)
    monkeypatch.setattr(live, "datetime", NS(now=lambda tz: datetime(2026, 3, 2, 10, 0, tzinfo=tz)))
    for bps, expected in ((-1, None), (5, 100.05)):
        calls.clear()
        cfg = dataclasses.replace(Settings(), symbols=["AAA"], entry_limit_bps=bps, market_filter="")
        live.run_once(cfg, broker, RiskManager(cfg))
        assert ("cancel" in calls) == (bps >= 0)
        assert calls[-1] == (pytest.approx(expected) if expected else None)


def test_momentum_decides_once_a_day_after_the_first_30_minutes():
    df = add_indicators(synthetic_bars(days=10, seed=5, gap_sd=0.01), Settings())
    et = df.index.tz_convert(ET)
    first = (et.hour * 60 + et.minute) < 10 * 60
    assert df.loc[first, "r30"].isna().all()  # unknown before 10:00
    trades = run_backtest({"AAA": synthetic_bars(days=30, seed=5, gap_sd=0.01)},
                          Settings(strategy="momentum", market_filter=""), 25_000)["trade_log"]
    assert len(trades)
    entries = trades["entry_time"].dt.tz_convert(ET)
    assert ((entries.dt.hour == 15) & (entries.dt.minute == 25)).all()  # filled at the open after the 15:20 bar
    assert entries.dt.date.is_unique


def test_overnight_trade_returns_include_costs():
    from bot.overnight import RULES, overnight_trades
    df = synthetic_daily(days=400, seed=7)
    free = overnight_trades(df, "every", Settings(slippage_bps=0, sec_fee_rate=0, taf_per_share=0))
    raw = (df["open"].shift(-1) / df["close"] - 1).dropna()
    assert free.values == pytest.approx(raw.values)  # no costs: exactly close-to-next-open
    costly = overnight_trades(df, "every", Settings(slippage_bps=5))
    assert (costly < free).all()
    for rule in RULES:  # every rule only picks nights from the full set
        assert set(overnight_trades(df, rule, Settings()).index) <= set(free.index)


def test_rotation_holds_cash_when_nothing_qualifies_and_accounts_for_costs():
    from bot.rotation import run_rotation
    up = synthetic_daily(days=700, seed=1, drift=0.002)
    down = synthetic_daily(days=700, seed=2, drift=-0.002)
    eq = run_rotation({"DOWN": down}, Settings(), top=1, lookback=3)
    assert eq.iloc[-1] == pytest.approx(5_000)  # always below its 200-day average: never buys
    eq = run_rotation({"UP": up, "DOWN": down}, Settings(), top=1, lookback=3)
    assert eq.iloc[-1] > 5_000  # holds the rising one
    free = run_rotation({"UP": up, "DOWN": down}, Settings(slippage_bps=0, sec_fee_rate=0, taf_per_share=0), top=1, lookback=3)
    assert free.iloc[-1] > eq.iloc[-1]  # costs are charged


def test_rotation_orders_sell_first_and_reach_the_targets():
    from datetime import date
    from bot.rotation_live import due, orders_for
    moves = orders_for({"QQQ": 0.5, "GLD": 0.5}, {"SPY": 3, "QQQ": 1}, {"QQQ": 500.0, "GLD": 250.0, "SPY": 600.0}, 5_000)
    assert moves == [("SPY", -3), ("GLD", 10), ("QQQ", 4)]  # sells come first
    assert orders_for({}, {"SPY": 2}, {"SPY": 600.0}, 5_000) == [("SPY", -2)]  # nothing qualifies: all cash
    assert due(date(2026, 11, 2), {"last_month": "2026-10"}) and not due(date(2026, 11, 20), {"last_month": "2026-11"})


def test_rotation_bot_refuses_live_and_ignores_the_orb_env(tmp_path, monkeypatch):
    from bot import rotation_live
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rotation_live, "ENV_FILE", tmp_path / ".env.rotation")
    with pytest.raises(SystemExit, match="missing"):
        rotation_live.load_settings()
    (tmp_path / ".env.rotation").write_text("ALPACA_API_KEY=bot2key\nALPACA_SECRET_KEY=bot2secret\n")
    monkeypatch.setenv("ALPACA_API_KEY", "orbkey")
    monkeypatch.setenv("LIVE_TRADING", "true")  # set for the ORB bot; must not leak into bot 2
    cfg = rotation_live.load_settings()
    assert cfg.alpaca_key == "bot2key" and not cfg.live_trading
    (tmp_path / ".env.rotation").write_text("ALPACA_API_KEY=k\nLIVE_TRADING=true\n")
    with pytest.raises(SystemExit, match="paper only"):
        rotation_live.load_settings()


def test_daily_rules_hold_the_right_days_and_charge_switches():
    from bot.daily_rules import RULES, strategy_returns, turn_of_month
    df = synthetic_daily(days=600, seed=9)
    tom = turn_of_month(df)
    first_day = df.index.to_series().groupby(df.index.year * 12 + df.index.month).transform("min") == df.index
    assert tom[first_day].all()  # always holds over the first day of a month
    assert 0.2 < tom.mean() < 0.35  # about 6 of ~21 days
    free = strategy_returns(df, "trend200", 0.0)
    paid = strategy_returns(df, "trend200", 0.001)
    hold = RULES["trend200"](df)
    assert (free[~hold] == 0).all()  # cash on days out of the market
    assert (paid <= free + 1e-12).all() and paid.sum() < free.sum()


def test_crypto_bot_trades_only_when_a_coin_flips():
    from bot.crypto_live import plan, want
    idx = pd.date_range("2026-01-01", periods=60, tz="UTC")
    closes = pd.DataFrame({"BTC/USD": np.linspace(50, 100, 60), "ETH/USD": np.linspace(100, 50, 60)}, index=idx)
    assert want(closes, 50) == {"BTC/USD": 0.5}  # rising coin above its average, falling one below
    assert want(closes.iloc[:10], 50) == {}  # not enough history: cash
    assert plan({"BTC/USD": 0.5}, {}, 5_000) == [("BTC/USD", "buy", 2500.0)]
    assert plan({"BTC/USD": 0.5}, {"BTC/USD": 0.03}, 5_000) == []  # still in: no trade
    assert plan({}, {"BTC/USD": 0.03, "ETH/USD": 0.5}, 5_000) == [("BTC/USD", "sell", 0.03), ("ETH/USD", "sell", 0.5)]


def test_crypto_bot_uses_its_own_keys(tmp_path, monkeypatch):
    from bot import crypto_live
    monkeypatch.setattr(crypto_live, "ENV_FILE", tmp_path / ".env.crypto")
    with pytest.raises(SystemExit, match=".env.crypto"):
        crypto_live.load_settings()
    (tmp_path / ".env.crypto").write_text("ALPACA_API_KEY=bot3key\nALPACA_SECRET_KEY=s\n")
    assert crypto_live.load_settings().alpaca_key == "bot3key"
