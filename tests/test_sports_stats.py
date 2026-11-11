from datetime import date, datetime, timedelta, timezone

import pytest

from bot import sports_stats as ss

CFG = {"leagues": ["nba"], "min_edge": 0.05, "min_games": 2, "max_odds": 4.0, "stake": 10, "backfill": 6}
NOW = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)  # 10am ET


def ev(gid, day, home, away, hs=None, as_=None, state="post", hml=None, aml=None, layout="old"):
    comp = {"competitors": [
        {"homeAway": "home", "team": {"id": home, "displayName": home, "abbreviation": home[:3]}, "score": hs},
        {"homeAway": "away", "team": {"id": away, "displayName": away, "abbreviation": away[:3]}, "score": as_}]}
    if hml is not None:
        comp["odds"] = [{"homeTeamOdds": {"moneyLine": hml}, "awayTeamOdds": {"moneyLine": aml}}] if layout == "old" else \
            [{"moneyline": {"home": {"close": {"odds": str(hml)}}, "away": {"close": {"odds": str(aml)}}}}]
    return {"id": gid, "date": f"{day}T23:00Z", "shortName": f"{away} @ {home}",
            "status": {"type": {"state": state, "completed": state == "post"}}, "competitions": [comp]}


def board_from(days: dict):
    return lambda league, d: {"events": days.get(d, [])}


def test_elo_math():
    assert ss.win_chance(1500, 1500, 0) == pytest.approx(0.5)
    assert ss.win_chance(1600, 1500, 0) == pytest.approx(0.64, abs=0.01)
    h, a = ss.elo_update(1500, 1500, 100, 90, 20, 0, True)
    assert h > 1500 > a and h - 1500 == pytest.approx(1500 - a)
    assert ss.elo_update(1500, 1500, 2, 2, 20, 0, True) == (1500, 1500)  # even teams tie: no change


def test_odds_helpers():
    assert ss.american_to_decimal(-200) == pytest.approx(1.5)
    assert ss.american_to_decimal("+150") == pytest.approx(2.5)
    assert ss.american_to_decimal("EVEN") is None
    assert ss.no_vig(1.91, 1.91) == pytest.approx(0.5)
    assert ss.bet_pnl(2.5, 10, True) == 15 and ss.bet_pnl(2.5, 10, False) == -10 and ss.bet_pnl(2, 10, None) == 0


def test_pick_rule():
    assert ss.pick_for(0.60, 0.50, 1.95, 1.95, CFG)["side"] == "home"
    assert ss.pick_for(0.40, 0.50, 1.95, 1.95, CFG)["side"] == "away"
    assert ss.pick_for(0.52, 0.50, 1.95, 1.95, CFG) is None
    assert ss.pick_for(0.35, 0.20, 5.0, 1.2, CFG) is None  # long shot over max odds


def test_both_odds_layouts_parse():
    old = ss.parse_games({"events": [ev("1", "2026-11-09", "A", "B", 1, 0, hml=-150, aml=130)]})[0]
    new = ss.parse_games({"events": [ev("1", "2026-11-09", "A", "B", 1, 0, hml=-150, aml=130, layout="new")]})[0]
    assert old["line"] == new["line"] == (pytest.approx(1 + 100 / 150), pytest.approx(2.3))


def test_full_run_rates_backfills_picks_and_settles(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Strong beats Weak every day for 5 days (each game priced as a coin flip), so ratings love Strong.
    days = {}
    for i in range(4, 0, -1):
        d = date(2026, 11, 10) - timedelta(days=i)
        days[d.strftime("%Y%m%d")] = [ev(f"p{i}", d.isoformat(), "Strong", "Weak", 110, 90, hml=-110, aml=-110)]
    days["20261110"] = [ev("t1", "2026-11-10", "Strong", "Weak", state="pre", hml=-110, aml=-110)]
    s = ss.run(CFG, NOW, board=board_from(days), odds=lambda *a: {})
    picks = ss.read_csv(ss.DATA / "picks.csv")
    live = [p for p in picks if p["kind"] == "live"]
    assert [p["team"] for p in live] == ["Strong"] and live[0]["status"] == "open"
    assert s["test"]["bets"] >= 1 and s["test"]["wins"] == s["test"]["bets"]  # past picks on Strong all won
    report = (ss.DATA / "report.md").read_text()
    assert "Strong @" in report and "Yesterday's scores" in report

    # Next day: the game went final, Strong won. Second run settles it and doesn't re-add test picks.
    days["20261110"] = [ev("t1", "2026-11-10", "Strong", "Weak", 100, 95, hml=-110, aml=-110)]
    n_test = len([p for p in picks if p["kind"] != "live"])
    s2 = ss.run(CFG, NOW + timedelta(days=1), board=board_from(days), odds=lambda *a: {})
    picks2 = ss.read_csv(ss.DATA / "picks.csv")
    assert s2["live"]["bets"] == 1 and s2["live"]["pnl"] == pytest.approx(9.09, abs=0.01)
    assert len([p for p in picks2 if p["kind"] == "test"]) == n_test
    assert ss.load_state()["leagues"]["nba"]["through"] == "2026-11-10"


def test_one_league_failing_does_not_stop_the_rest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def board(league, d):
        if league == "nhl":
            raise RuntimeError("boom")
        return {"events": []}
    s = ss.run({**CFG, "leagues": ["nhl", "nba"]}, NOW, board=board, odds=lambda *a: {})
    assert s["live"]["bets"] == 0 and (ss.DATA / "report.md").exists()


def test_new_season_pulls_rating_back():
    r = {"x": [1800.0, 30, "2026-03-01"]}
    t = ss.team(r, "x", "2026-10-01")
    assert t[0] == pytest.approx(1700) and t[1] == 0


def test_past_games_get_their_line_from_the_odds_lookup_or_saved_pregame_line(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    days = {}
    for i in range(5, 0, -1):  # scoreboards for past days carry no odds (like ESPN's)
        d = date(2026, 11, 10) - timedelta(days=i)
        days[d.strftime("%Y%m%d")] = [ev(f"p{i}", d.isoformat(), "Strong", "Weak", 110, 90)]
    days["20261110"] = [ev("t1", "2026-11-10", "Strong", "Weak", state="pre", hml=-110, aml=-110)]
    asked = []

    def odds(league, gid):
        asked.append(gid)
        return {"odds": [{"homeTeamOdds": {"moneyLine": -110}, "awayTeamOdds": {"moneyLine": -110}}]}
    s = ss.run(CFG, NOW, board=board_from(days), odds=odds)
    assert asked and "p5" not in asked  # only games where both teams were seasoned
    assert s["test"]["bets"] == len(asked) and s["accuracy"]["nba"]["games"] == len(asked)
    assert ss.load_state()["lines"]["nba"]["t1"] == [pytest.approx(1.9091, abs=1e-3)] * 2

    # Next day the scoreboard drops t1's odds; the saved pre-game line is used, no lookup needed.
    days["20261110"] = [ev("t1", "2026-11-10", "Strong", "Weak", 100, 95)]
    asked.clear()
    ss.run(CFG, NOW + timedelta(days=1), board=board_from(days), odds=odds)
    assert asked == [] and "t1" not in ss.load_state()["lines"]["nba"]
    games = ss.read_csv(ss.DATA / "games.csv")
    assert games[-1]["game"] == "Weak @ Strong" and games[-1]["market_home"] == "0.5"


def test_old_state_is_rebuilt_but_live_picks_kept(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ss.DATA.mkdir()
    ss.STATE.write_text('{"leagues": {"nba": {"ratings": {}, "through": "2026-11-09"}}}')
    ss.write_csv(ss.DATA / "picks.csv", ss.PICK_COLS, [
        {"kind": "live", "day": "2026-11-09", "league": "nba", "id": "x", "side": "home", "odds": 2, "status": "open"},
        {"kind": "test", "day": "2026-11-01", "league": "nba", "id": "y", "status": "settled", "won": 1, "pnl": 10}])
    ss.run(CFG, NOW, board=board_from({}), odds=lambda *a: {})
    st = ss.load_state()
    assert st["version"] == ss.VERSION and st["leagues"]["nba"]["through"] == "2026-11-09"  # backfilled again
    assert [p["kind"] for p in ss.read_csv(ss.DATA / "picks.csv")] == ["live"]
