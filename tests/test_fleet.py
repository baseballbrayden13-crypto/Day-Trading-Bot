import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from bot import data_bot, fleet, maintenance as mt
from bot.fleet import FLEET, Bot

ET = ZoneInfo("America/New_York")
# Tuesday 2026-10-27, 9pm ET: after every bot's run time
NOW = datetime(2026, 10, 27, 21, 0, tzinfo=ET).astimezone(timezone.utc)


class FakeClient:
    def __init__(self, number="PA1234QIE2", equity=5000.0, last=5000.0, positions=(), orders=(), fail=None):
        self.number, self.eq, self.last, self.pos, self.orders, self.fail = number, equity, last, positions, orders, fail

    def get_account(self):
        if self.fail:
            raise RuntimeError(self.fail)
        return NS(account_number=self.number, equity=str(self.eq), last_equity=str(self.last), cash="100",
                  status="AccountStatus.ACTIVE", trading_blocked=False, account_blocked=False)

    def get_all_positions(self):
        return [NS(symbol=s, qty="10", avg_entry_price="100", market_value="1000", unrealized_pl="5") for s in self.pos]

    def get_orders(self, req):
        return list(self.orders)

    def get_portfolio_history(self, req):
        if self.fail:
            raise RuntimeError(self.fail)
        t = int(datetime(2026, 10, 26, 16, tzinfo=ET).timestamp())
        return NS(timestamp=[t], equity=[4990.0])

    def get_clock(self):
        return NS(is_open=False, next_open="2026-10-28T09:30:00-04:00", next_close="2026-10-28T16:00:00-04:00")

    def get_calendar(self, req):
        return [NS(date=req.start)]


def order(symbol, side, qty, price, when, oid, legs=()):
    return NS(symbol=symbol, side=f"OrderSide.{side.upper()}", filled_qty=str(qty), filled_avg_price=str(price),
              filled_at=when, order_type="OrderType.MARKET", id=oid, legs=list(legs))


def bots_in(tmp_path):
    return [Bot(**{**b.__dict__, "home": str(tmp_path)}) for b in FLEET]


def write_log(tmp_path, name, when, extra=""):
    p = tmp_path / name
    p.write_text(f"{when:%Y-%m-%d %H:%M:%S},000 INFO started\n{extra}")
    ts = when.timestamp()
    import os
    os.utime(p, (ts, ts))


def test_fleet_overrides_from_json(tmp_path):
    cfg = tmp_path / "fleet.json"
    cfg.write_text(json.dumps({"4": {"home": "C:/kalshi-run", "flag": 1}, "1": {"account": "ABCD", "symbols": ["SPY"]}}))
    bots = fleet.by_num(fleet.load(cfg))
    assert bots[4].home == "C:/kalshi-run" and bots[4].extra == {"flag": 1}
    assert bots[1].account == "ABCD" and bots[1].symbols == ("SPY",)
    assert bots[2].account == "8T7Y"


def test_collect_reads_accounts_orders_logs_and_kalshi(tmp_path):
    bots = bots_in(tmp_path)
    write_log(tmp_path, "trades.log", datetime(2026, 10, 27, 15, 50),
              "2026-10-27 10:01:00,000 ERROR Error in loop; retrying next bar\n")
    (tmp_path / "kalshi_data").mkdir()
    (tmp_path / "kalshi_data" / "summary.json").write_text(json.dumps({"updated": NOW.isoformat(), "equity": "20.40", "start_budget": "20"}))
    (tmp_path / "kalshi_paper_state.json").write_text(json.dumps({"realized": "0.40", "open": [], "closed": [{"pnl": "0.40"}]}))
    t = datetime(2026, 10, 27, 10, 0, tzinfo=ET)
    clients = {
        1: FakeClient(orders=[order("AAPL", "buy", 5, 100, t, "a", legs=[order("AAPL", "sell", 5, 101, t + timedelta(hours=1), "b")])]),
        2: FakeClient("PA99998T7Y", positions=["XLE"]),
        3: FakeClient(fail="401 unauthorized"),
    }
    snap = data_bot.collect(bots, NOW, with_market=False, client_for=lambda b: clients[b.num], tasks=lambda: [])
    b1 = snap["bots"]["1"]
    assert b1["account"]["account"] == "QIE2" and b1["account"]["status"] == "ACTIVE"
    assert [o["side"] for o in b1["orders"]] == ["buy", "sell"]
    assert b1["log"]["errors_24h"] == 1
    assert snap["bots"]["2"]["positions"][0]["symbol"] == "XLE"
    assert "401" in snap["bots"]["3"]["errors"][0]
    assert snap["bots"]["4"]["paper"]["realized"] == 0.40
    assert snap["clock"]["trading_day"] is True

    out = tmp_path / "fleet_data"
    data_bot.save(snap, out)
    data_bot.save(snap, out)  # a second run the same day doesn't duplicate rows
    eq = data_bot._read_csv(out / "equity.csv")
    assert {(r["day"], r["bot"]) for r in eq} == {("2026-10-26", "1"), ("2026-10-26", "2"), ("2026-10-27", "1"),
                                                   ("2026-10-27", "2"), ("2026-10-27", "4"),
                                                   ("2026-10-27", "5")}
    assert len(data_bot._read_csv(out / "trades.csv")) == 2
    assert (out / "history" / "2026-10-27.json").exists()


def test_market_rows_trend_and_volatility():
    idx = pd.date_range("2025-01-01", periods=250, freq="D")
    closes = pd.DataFrame({"UP": np.linspace(100, 200, 250), "DOWN": np.linspace(200, 100, 250)}, index=idx)
    rows = {r["symbol"]: r for r in data_bot.market_rows(closes)}
    assert rows["UP"]["above_200d"] and rows["UP"]["above_50d"] and rows["UP"]["chg_1d_pct"] > 0
    assert rows["DOWN"]["above_200d"] is False and rows["DOWN"]["chg_1m_pct"] < 0


def healthy_snapshot():
    acct = lambda last4, eq=5000.0: {"account": last4, "equity": eq, "last_equity": eq, "cash": 100, "status": "ACTIVE",
                                     "trading_blocked": False, "account_blocked": False}
    log = {"exists": True, "modified": datetime(2026, 10, 27, 20, 30, tzinfo=ET).isoformat(), "errors_24h": 0}
    return {
        "taken": NOW.isoformat(), "clock": {"is_open": False, "trading_day": True}, "errors": [],
        "market": {"symbols": [{"symbol": "BTC/USD", "above_50d": True}, {"symbol": "ETH/USD", "above_50d": False}]},
        "bots": {
            "1": {"account": acct("QIE2"), "positions": [], "log": log, "errors": [], "fills": {}},
            "2": {"account": acct("8T7Y"), "positions": [{"symbol": "XLE"}, {"symbol": "XLK"}], "log": log, "errors": [],
                  "rotation_state": {"holding": {"XLE": 0.33, "XLK": 0.33}}},
            "3": {"account": acct("KTS7"), "positions": [{"symbol": "BTCUSD"}], "log": log, "errors": []},
            "4": {"paper": {"summary": {"updated": NOW.isoformat(), "equity": "20", "start_budget": "20", "problems": 0},
                            "closed": 0, "open": 0, "losing_trades": 0}, "errors": []},
            "5": {"maker": {"summary": None, "realized": 0.0, "closed": 0, "open": 0, "losing_trades": 0, "quotes": 2,
                            "log": {"exists": True, "modified": (NOW - timedelta(minutes=4)).isoformat(), "errors_24h": 0}},
                  "errors": []},
        },
    }


def acts(findings):
    return [(f.bot, f.check) for f in findings if f.level == "act"]


def test_healthy_fleet_needs_no_action():
    f = mt.run_checks(healthy_snapshot(), FLEET, [], [], NOW)
    assert acts(f) == [] and not [x for x in f if x.level == "watch"]
    assert mt.status(f, 1) == "info"  # too few trades to judge, nothing wrong


def test_broken_fleet_is_flagged_with_fixes():
    s = healthy_snapshot()
    s["bots"]["1"]["positions"] = [{"symbol": "NVDA"}]  # held after the close
    s["bots"]["1"]["account"]["equity"] = 4850  # -3% today
    s["bots"]["2"]["errors"] = ["account: APIError: 401 unauthorized"]
    s["bots"]["3"]["account"]["account"] = "QIE2"  # bot 3 on bot 1's account
    s["bots"]["3"]["log"] = {"exists": True, "modified": datetime(2026, 10, 25, 20, 30, tzinfo=ET).isoformat()}
    s["bots"]["4"]["paper"]["losing_trades"] = 1
    f = mt.run_checks(s, FLEET, [], [], NOW)
    got = set(acts(f))
    assert {(1, "overnight"), (1, "day loss"), (2, "keys"), (3, "account"), (3, "schedule"), (0, "account"), (4, "losses")} <= got
    assert all(x.fix for x in f if x.level == "act" and x.bot)
    rows = mt.proposals(f, FLEET, NOW)
    assert rows and all(r["status"] == "Proposed" for r in rows)


def test_weekday_bot_is_not_late_on_weekend():
    bot1 = FLEET[0]
    sunday = datetime(2026, 11, 1, 12, tzinfo=ET)
    assert mt.last_due(bot1, sunday) == datetime(2026, 10, 30, 9, 20, tzinfo=ET)  # Friday's run
    assert mt.last_due(bot1, datetime(2026, 10, 27, 9, 0, tzinfo=ET)) == datetime(2026, 10, 26, 9, 20, tzinfo=ET)
    holiday = datetime(2026, 11, 26, 12, tzinfo=ET)  # Thanksgiving
    assert mt.last_due(bot1, holiday, trading_today=False).date().isoformat() == "2026-11-25"


def test_performance_and_slippage_after_enough_trades():
    t0 = datetime(2026, 9, 1, 10, tzinfo=ET)
    trades = []
    for i in range(30):  # 30 round trips, 10 winners of $5, 20 losers of $5: PF 0.5
        t = (t0 + timedelta(days=i)).isoformat()
        trades.append({"bot": "1", "symbol": "AAPL", "side": "buy", "qty": "5", "price": "100", "time": t, "type": "market"})
        trades.append({"bot": "1", "symbol": "AAPL", "side": "sell", "qty": "5", "price": "101" if i % 3 == 0 else "99",
                       "time": t[:11] + "15:00:00-04:00", "type": "stop"})
    s = healthy_snapshot()
    s["bots"]["1"]["fills"] = {"fills": 25, "avg_bps": 6.0}
    f = mt.run_checks(s, FLEET, [], trades, NOW)
    perf = {x.check: x for x in f if x.bot == 1}
    assert perf["performance"].level == "act" and "0.50" in perf["performance"].message
    assert perf["slippage"].level == "act" and "ENTRY_LIMIT_BPS" in perf["slippage"].proposal


def test_drawdown_watch_then_act():
    rows = [{"day": f"2026-10-{d:02d}", "bot": "2", "equity": e} for d, e in [(1, 5000), (2, 6000), (3, 4300)]]  # -28%
    f = mt.check_risk(FLEET[1], {}, rows)
    assert [x.level for x in f if x.check == "drawdown"] == ["watch"]
    rows.append({"day": "2026-10-04", "bot": "2", "equity": 3500})  # -42% > 1.5 x 26%
    assert [x.level for x in mt.check_risk(FLEET[1], {}, rows) if x.check == "drawdown"] == ["act"]


def test_alerts_once_a_day(tmp_path):
    f = [mt.Finding(1, "act", "keys", "bad keys"), mt.Finding(1, "watch", "errors", "x")]
    p = tmp_path / "alerted.json"
    assert len(mt.new_alerts(f, p, NOW)) == 1
    assert mt.new_alerts(f, p, NOW + timedelta(hours=2)) == []
    assert len(mt.new_alerts(f, p, NOW + timedelta(hours=25))) == 1


def test_scheduled_task_checks():
    s = healthy_snapshot()
    s["clock"]["is_open"] = True
    s["tasks"] = [{"name": "Trading bot (paper)", "state": "Ready", "last_result": 0xC000013A},
                  {"name": "Trading bot 2 (rotation, paper)", "state": "Ready", "last_result": 0},
                  {"name": "Trading bot 4 (Kalshi, paper)", "state": "Ready", "last_result": 0xC000013A},
                  {"name": "Trading bot 4b (Kalshi maker, demo)", "state": "Running", "last_result": 0x41301}]
    s["bots"]["1"]["log"] = {**s["bots"]["1"]["log"], "modified": datetime(2026, 10, 27, 9, 30, tzinfo=ET).isoformat()}  # quiet loop log is fine
    f = mt.run_checks(s, FLEET, [], [], NOW)
    task1 = [x for x in f if x.bot == 1 and x.check == "task"]
    assert len(task1) == 1 and task1[0].level == "act" and "window was closed" in task1[0].message
    assert not [x for x in f if x.bot == 1 and x.check == "schedule"]
    assert [x.level for x in f if x.bot == 4 and x.check == "task"] == ["act"]  # a Kalshi loop should always run
    assert not [x for x in f if x.bot == 5 and x.check == "task"]
    assert not [x for x in f if x.bot == 2 and x.level in ("watch", "act")]


def test_log_written_at_task_start_counts():
    s = healthy_snapshot()
    nine_fifty = datetime(2026, 10, 27, 9, 50, 30, tzinfo=ET)
    s["bots"]["2"]["log"]["modified"] = nine_fifty.isoformat()
    assert mt.check_schedule(FLEET[1], s["bots"]["2"], nine_fifty + timedelta(minutes=5), True) == []


def test_tasks_parse_single_or_list():
    one = '{"name": "Kalshi", "state": "Running", "last_result": 267009}'
    assert data_bot.scheduled_tasks(lambda: one)[0]["state"] == "Running"
    assert len(data_bot.scheduled_tasks(lambda: "[" + one + "," + one + "]")) == 2
    assert data_bot.scheduled_tasks(lambda: "") == []


def test_running_task_ignores_last_runs_code():
    s = healthy_snapshot()
    s["clock"]["is_open"] = True
    s["tasks"] = [{"name": "Trading bot (paper)", "state": "Running", "last_result": 0xC000013A}]  # restarted after a crash
    assert mt.check_task(FLEET[0], s["tasks"], s, NOW) == []


def test_repeated_watch_becomes_act(tmp_path):
    p = tmp_path / "streaks.json"
    w = [mt.Finding(2, "watch", "holdings", "mismatch")]
    assert [f.level for f in mt.escalate(w, p)] == ["watch"]
    assert [f.level for f in mt.escalate(w, p)] == ["watch"]
    assert [f.level for f in mt.escalate(w, p)] == ["act"]
    mt.escalate([], p)  # cleared once it goes away
    assert [f.level for f in mt.escalate(w, p)] == ["watch"]


def test_new_and_fixed_since_last_check():
    prev = [{"bot": 1, "check": "task", "level": "act", "message": "window closed"}]
    new, fixed = mt.changes([mt.Finding(3, "watch", "holdings", "x"), mt.Finding(1, "info", "return", "y")], prev)
    assert [f.bot for f in new] == [3] and fixed[0]["message"] == "window closed"


def test_crash_log_is_flagged_on_its_bot():
    s = healthy_snapshot()
    s["err_logs"] = [{"home": ".", "file": "kalshi_paper_err.log", "modified": (NOW - timedelta(hours=1)).isoformat(),
                      "tail": ["Traceback ...", "KeyError: 'x'"]},
                     {"home": ".", "file": "old_err.log", "modified": (NOW - timedelta(days=3)).isoformat(), "tail": ["x"]}]
    crashes = [f for f in mt.run_checks(s, FLEET, [], [], NOW) if f.check == "crash"]
    assert len(crashes) == 1 and crashes[0].bot == 4 and crashes[0].level == "act" and "KeyError" in crashes[0].message


def test_bot_compared_with_just_holding():
    eq = [{"day": "2026-10-01", "bot": "3", "equity": "5000"}, {"day": "2026-10-20", "bot": "3", "equity": "5500"}]
    bench = [{"day": d, "symbol": s, "close": c} for d, s, c in
             [("2026-10-01", "BTC/USD", 100), ("2026-10-20", "BTC/USD", 120), ("2026-10-01", "ETH/USD", 10), ("2026-10-20", "ETH/USD", 10)]]
    f = mt.check_benchmark(FLEET[2], eq, bench)
    assert f and "+10.0%" in f[0].message and "+10.0%" in f[0].message.split("holding")[1]


def test_digest_and_site_rows():
    f = mt.run_checks(healthy_snapshot(), FLEET, [], [], NOW)
    assert mt.digest(f, FLEET, [])[0] == "Medic: all bots OK"
    bad = f + [mt.Finding(1, "act", "task", "Bot 1 isn't running.")]
    title, text, prio = mt.digest(bad, FLEET, [bad[-1]])
    assert title == "Medic: 1 need action" and "bot 1: Bot 1 isn't running." in text and prio == "high"
    health, rows = mt.site_rows(bad, FLEET, NOW)
    assert [h["label"] for h in health] == ["fleet", "1", "2", "3", "4", "4b"]
    assert health[1]["status"] == "act" and health[2]["headline"] == "Running normally."


def test_unfunded_zero_days_are_ignored_and_a_broken_check_is_contained():
    eq = [{"day": "2026-09-28", "bot": "3", "equity": "0.0"}, {"day": "2026-10-01", "bot": "3", "equity": "5000"},
          {"day": "2026-10-20", "bot": "3", "equity": "5500"}]
    bench = [{"day": d, "symbol": s, "close": c} for d, s, c in
             [("2026-10-01", "BTC/USD", 100), ("2026-10-20", "BTC/USD", 120), ("2026-10-01", "ETH/USD", 10), ("2026-10-20", "ETH/USD", 10)]]
    assert mt.check_benchmark(FLEET[2], eq, bench)
    assert [f.level for f in mt.check_risk(FLEET[2], {}, eq) if f.check == "drawdown"] == []
    f = mt.run_checks(healthy_snapshot(), FLEET, [{"day": "2026-10-01", "bot": "2", "equity": "oops"}], [], NOW)
    assert any(x.check == "medic" for x in f) and any(x.bot == 4 for x in f)  # later checks still ran
