from datetime import date, datetime
from zoneinfo import ZoneInfo

from bot import popup
from bot.config import Settings
from bot.live import in_window, load_risk, save_risk
from bot.risk import RiskManager

ET = ZoneInfo("America/New_York")


def test_start_window():
    assert in_window(datetime(2026, 11, 2, 9, 5, tzinfo=ET), "08:30-12:00")
    assert not in_window(datetime(2026, 11, 2, 8, 5, tzinfo=ET), "08:30-12:00")
    assert not in_window(datetime(2026, 11, 2, 12, 0, tzinfo=ET), "08:30-12:00")
    assert in_window(datetime(2026, 11, 2, 12, 40, tzinfo=ET), "12:00-15:50")


def test_risk_counters_carry_over_same_day_only(tmp_path):
    path = tmp_path / "risk_state.json"
    morning = RiskManager(Settings())
    morning.new_day(date(2026, 11, 2), 5012.5)
    morning.trades_today = 2
    morning.halted, morning.halt_reason = True, "daily loss limit hit"
    save_risk(morning, path)

    afternoon = RiskManager(Settings())
    assert load_risk(afternoon, date(2026, 11, 2), path)
    assert (afternoon.start_equity, afternoon.trades_today, afternoon.halted) == (5012.5, 2, True)
    assert afternoon.day == date(2026, 11, 2)

    tomorrow = RiskManager(Settings())
    assert not load_risk(tomorrow, date(2026, 11, 3), path)
    assert tomorrow.trades_today == 0 and tomorrow.day is None


def test_cloud_alerts_first_check_marks_spot_then_shows_new(tmp_path):
    seen = tmp_path / "seen.txt"
    rows = [{"time": "2026-11-02T14:00:00+00:00", "who": "guard", "level": "act", "title": "Guard: bot 1", "text": "down"}]
    assert popup.cloud_alerts(seen, fetch=lambda url: rows) == []  # old alerts aren't replayed
    rows = rows + [{"time": "2026-11-02T15:00:00+00:00", "who": "guard", "level": "watch", "title": "Guard: bot 2", "text": "big"},
                   {"time": "2026-11-02T15:01:00+00:00", "who": "medic", "level": "info", "title": "fyi", "text": ""}]
    got = popup.cloud_alerts(seen, fetch=lambda url: rows)
    assert [a["title"] for a in got] == ["Guard: bot 2"]
    assert popup.cloud_alerts(seen, fetch=lambda url: rows) == []
    assert popup.cloud_alerts(seen, fetch=lambda url: []) == []  # offline: nothing, spot kept
    assert seen.read_text() == "2026-11-02T15:01:00+00:00"
