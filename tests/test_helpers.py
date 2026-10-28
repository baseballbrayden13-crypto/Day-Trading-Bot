import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from bot import data_bot, guard, lab, maintenance as mt, popup, reporter
from bot.fleet import FLEET, load

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 27, 14, 0, tzinfo=ET).astimezone(timezone.utc)


def reading(eq=5000.0, last=5000.0, pos=()):
    return {"account": {"account": "X", "equity": eq, "last_equity": last, "cash": 0, "status": "ACTIVE",
                        "trading_blocked": False, "account_blocked": False},
            "positions": [{"symbol": s, "qty": q, "avg_entry": 1, "market_value": v, "unrealized_pl": 0} for s, q, v in pos]}


def test_guard_limits():
    b1, b2 = FLEET[0], FLEET[1]
    assert guard.check_bot(b1, reading(), NOW) == []
    assert [a.level for a in guard.check_bot(b1, reading(4920), NOW)] == ["watch"]  # -1.6% of a 2% limit
    assert [a.level for a in guard.check_bot(b1, reading(4890), NOW)] == ["act"]
    assert [a.key for a in guard.check_bot(b2, reading(pos=[("XLE", 10, 2500)]), NOW)] == ["size XLE"]
    assert [a.key for a in guard.check_bot(b2, reading(pos=[("XLE", -5, 500)]), NOW)] == ["short XLE"]
    late = datetime(2026, 10, 27, 15, 58, tzinfo=ET)
    assert [a.key for a in guard.check_bot(b1, reading(pos=[("NVDA", 5, 900)]), late)] == ["after close"]
    assert guard.check_fleet({"1": reading(4900), "2": reading(4880)}, 2.0)[0].level == "act"


def test_guard_alerts_once_a_day(tmp_path):
    sent = []
    bots = [b for b in FLEET if b.num == 1]
    client = lambda b: NS(get_account=lambda: NS(account_number="PAQIE2", equity="4850", last_equity="5000", cash="0",
                                                 status="ACTIVE", trading_blocked=False, account_blocked=False),
                          get_all_positions=lambda: [])
    kw = dict(client_for=client, seen_path=tmp_path / "seen.json", log_path=tmp_path / "g.csv",
              notify=lambda who, title, text, level: sent.append(level))
    guard.run_once(bots, NOW, **kw)
    guard.run_once(bots, NOW + timedelta(minutes=10), **kw)
    assert sent == ["act", "act"]  # bot 1 past its limit, and so the fleet as a whole; neither repeats
    assert len((tmp_path / "g.csv").read_text().splitlines()) == 3  # header + 2 checks


def test_lab_windows_and_verdict():
    end = pd.Timestamp("2026-10-27", tz="UTC")
    times = pd.date_range(end - pd.Timedelta(days=1000), end - pd.Timedelta(days=1), periods=200)
    pnl = np.where(times < end - pd.Timedelta(days=365), np.tile([10, -5], 100), np.tile([4, -5], 100))
    rows = lab.windows(pd.DataFrame({"entry_time": times, "pnl": pnl}), end)
    by = {r["window"]: r for r in rows}
    assert by["before that"]["pf"] > 1.9 and by["last year"]["pf"] < 1.0
    assert lab.orb_verdict(rows).startswith("FADING")


def test_lab_queue(tmp_path):
    q = tmp_path / "q.txt"
    q.write_text("# a note\n--set ORB_TARGET_R=1.25,1.5 --label t\n--label two\n")
    i, cmd = lab.next_experiment(q)
    assert cmd.startswith("--set") and i == 1
    lab.mark_done(q, i, "2026-10-31")
    assert lab.next_experiment(q)[1] == "--label two"


def test_reporter_card():
    b = FLEET[1]
    eq = [{"day": "2026-10-19", "bot": "2", "equity": "5000"}, {"day": "2026-10-23", "bot": "2", "equity": "5100"},
          {"day": "2026-10-27", "bot": "2", "equity": "5150"}]
    c = reporter.card(b, eq, [], [{"day": "2026-10-25", "status": {"2": "act"}}], [], [], "2026-10-21", "2026-10-27")
    assert c["week_pct"] == 3.0 and c["medic_act_days"] == 1 and c["grade"] == "B"
    assert "grade B: up 3.0% this week" in reporter.sentence(c)


def test_popup_prefers_where_the_bot_runs():
    bots = [b if b.num != 2 else type(b)(**{**b.__dict__, "runs_on": "cloud"}) for b in FLEET]
    local = [{"bot": "1", "label": "1", "name": "ORB", "status": "ok", "headline": "", "checked": "t"},
             {"bot": "2", "label": "2", "name": "ETF", "status": "act", "headline": "rotation.log missing", "checked": "t"}]
    cloud = [{"bot": "2", "label": "2", "name": "ETF", "status": "ok", "headline": "", "checked": "t"}]
    rows = popup.merge(local, cloud, bots)
    assert [r["status"] for r in rows] == ["ok", "ok"]
    text, bad = popup.summary(rows, [{"title": "Guard: bot 1", "text": "down 1.6%"}])
    assert not bad and "Guard: bot 1" in text


def test_replay_compares_backtest_and_live():
    day = "2026-10-27"
    snap = {"replay": {"day": day, "trades": [{"symbol": "AAPL", "entry_time": "2026-10-27T14:05:00+00:00", "entry": 100.0},
                                               {"symbol": "NVDA", "entry_time": "2026-10-27T14:10:00+00:00", "entry": 50.0}]}}
    trades = [{"bot": "1", "side": "buy", "symbol": "AAPL", "price": "100.5", "time": "2026-10-27T14:05:10+00:00"}]
    f = mt.check_replay(snap, trades)
    assert [(x.level, "NVDA" in x.message) for x in f if x.check == "replay"] == [("info", False), ("watch", True)]


def test_events_and_earnings():
    rows = {"2026-10-28": [{"symbol": "NVDA", "time": "time-after-hours"}, {"symbol": "ZZZ"}]}
    got = data_bot.earnings(["NVDA", "AAPL"], NOW, fetch=lambda d: rows.get(d, []))
    assert got == [{"date": "2026-10-28", "what": "NVDA earnings", "symbol": "NVDA", "when": "time-after-hours"}]
    f = mt.check_events({"events": got}, NOW)
    assert f and "NVDA earnings Wed 10/28" in f[0].message


def test_cloud_host_checks_only_cloud_bots(tmp_path, monkeypatch):
    cfg = tmp_path / "fleet.json"
    cfg.write_text((__import__("pathlib").Path(__file__).parents[1] / "cloud" / "fleet.json").read_text())
    bots = load(cfg)
    assert [b.tag for b in bots] == ["2", "3", "4c", "4e"] and all(b.runs_on == "cloud" for b in bots)
    monkeypatch.setenv("FLEET_HOST", "pc")
    s = {"taken": NOW.isoformat(), "errors": [], "bots": {"2": {"account": reading()["account"], "positions": [], "errors": [],
                                                             "log": {"exists": False}}}}
    f = mt.run_checks(s, bots[:1], [], [], NOW)  # on the PC, bot 2's log lives in the cloud: no schedule alarm
    assert not [x for x in f if x.check == "schedule"]
    monkeypatch.setenv("FLEET_HOST", "cloud")
    f = mt.run_checks(s, bots[:1], [], [], NOW)
    assert [x.level for x in f if x.check == "schedule"] == ["watch"]  # no saved cloud log yet: watch, escalates after 3 days


def test_network_errors_are_not_key_errors():
    s = {"errors": ["account: ProxyError: Tunnel connection failed: 403 Forbidden"]}
    f = mt.check_connection(FLEET[1], s)
    assert [x.check for x in f] == ["data"]


def test_quiet_hours(monkeypatch):
    from bot import alerts

    monkeypatch.setattr(alerts, "_env", lambda name: "")
    assert alerts.quiet_hours(datetime(2026, 10, 28, 0, 50, tzinfo=ET))
    assert not alerts.quiet_hours(datetime(2026, 10, 28, 10, 0, tzinfo=ET))
    monkeypatch.setattr(alerts, "_env", lambda name: "off" if name == "ALERTS_QUIET" else "")
    assert not alerts.quiet_hours(datetime(2026, 10, 28, 0, 50, tzinfo=ET))


def test_cloud_bot_without_a_saved_log_is_a_watch_not_an_act(monkeypatch):
    monkeypatch.setenv("FLEET_HOST", "cloud")
    from dataclasses import replace

    bot = replace(FLEET[1], runs_on="cloud")
    f = mt.check_schedule(bot, {"log": {"exists": False}}, NOW, True)
    assert [x.level for x in f] == ["watch"] and "cloud run" in f[0].message
    pc = replace(FLEET[1], runs_on="pc")
    assert [x.level for x in mt.check_schedule(pc, {"log": {"exists": False}}, NOW, True)] == ["act"]


def test_kalshi_bots_on_the_other_machine_or_retired_are_not_checked(monkeypatch):
    from dataclasses import replace

    monkeypatch.setenv("FLEET_HOST", "pc")
    kal = next(b for b in FLEET if b.kind == "kalshi" and b.label == "4b")
    snap = {"taken": NOW.isoformat(), "errors": [], "bots": {str(kal.num): {"errors": ["no files"]}}}
    assert [f.check for f in mt.run_checks(snap, [replace(kal, runs_on="pc")], [], [], NOW)] == ["data"]
    assert mt.run_checks(snap, [replace(kal, runs_on="cloud")], [], [], NOW) == []
    assert mt.run_checks(snap, [replace(kal, runs_on="off")], [], [], NOW) == []
