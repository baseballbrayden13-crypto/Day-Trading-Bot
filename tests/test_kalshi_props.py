from datetime import datetime, timezone

from bot import kalshi_props as kp

CFG = {"near_edge": 0.08, "min_edge": 0.05, "min_books": 3, "min_price": 0.15, "max_price": 0.85, "credits": 6, "hours": 6,
       "stake": 2, "quiet": "off", "sports": ["basketball_nba"]}
NOW = datetime(2026, 11, 11, 22, 0, tzinfo=timezone.utc)
GAME = {"id": "g1", "home_team": "New Orleans Pelicans", "away_team": "Brooklyn Nets", "commence_time": "2026-11-12T01:00:00Z"}


def book(title, over, under, player="Herbert Jones", point=9.5, key="player_points"):
    return {"title": title, "markets": [{"key": key, "outcomes": [
        {"name": "Over", "description": player, "price": over, "point": point},
        {"name": "Under", "description": player, "price": under, "point": point}]}]}


def event(yes_ask="0.5000", no_ask="0.5200"):
    return {"event_ticker": "KXNBAPTS-26NOV11BKNNOP", "title": "Brooklyn vs New Orleans: Points", "markets": [
        {"ticker": "KXNBAPTS-26NOV11BKNNOP-NOPHJONES2-10", "yes_sub_title": "Herbert Jones: 10+", "floor_strike": 9.5,
         "strike_type": "greater", "yes_ask_dollars": yes_ask, "no_ask_dollars": no_ask},
        {"ticker": "KXNBAPTS-26NOV11BKNNOP-NOPHJONES2-15", "yes_sub_title": "Herbert Jones: 15+", "floor_strike": 14.5,
         "strike_type": "greater", "yes_ask_dollars": "0.2000", "no_ask_dollars": "0.8200"}]}


BOOKS3 = [book("A", 1.6, 2.4), book("B", 1.62, 2.35), book("C", 1.58, 2.45)]


def test_fair_takes_the_margin_out_and_needs_both_sides():
    lines = kp.fair_lines(BOOKS3 + [{"title": "D", "markets": [{"key": "player_points", "outcomes": [
        {"name": "Over", "description": "Herbert Jones", "price": 1.2, "point": 9.5}]}]}], "player_points")
    line = lines[("herbert jones", 9.5)]
    assert line["books"] == 3 and abs(line["fair"] - 0.6) < 0.01


def test_player_names_match_across_spellings():
    assert kp.player_key("P.J. Washington Jr.") == kp.player_key("PJ Washington")


def test_pick_needs_edge_after_fee_and_skips_long_shots():
    assert kp.pick(0.60, 0.50, 0.52, CFG)["side"] == "yes"
    assert kp.pick(0.60, 0.56, 0.46, CFG) is None  # 4c before the fee is not enough
    assert kp.pick(0.40, 0.62, 0.50, CFG)["side"] == "no"
    assert kp.pick(0.20, 0.10, 0.92, CFG) is None  # long shot: skipped even though it looks cheap


def test_pnl_includes_the_fee_and_refunds_voids():
    bet = {"side": "yes", "price": 0.5, "contracts": 4}
    assert kp.bet_pnl(bet, "yes") == 4 - 2 - 0.07
    assert kp.bet_pnl(bet, "no") == -2.07
    assert kp.bet_pnl(bet, "void") == 0.0


def test_event_matches_teams_and_day():
    assert kp.event_for_game(GAME, [event()])
    assert kp.event_for_game({**GAME, "home_team": "Boston Celtics"}, [event()]) is None
    assert kp.event_for_game({**GAME, "commence_time": "2026-11-15T01:00:00Z"}, [event()]) is None


def test_compare_only_same_player_and_line_with_enough_books():
    rows = kp.compare(event(), kp.fair_lines(BOOKS3, "player_points"), CFG)
    assert [r["ticker"][-2:] for r in rows] == ["10"]
    assert kp.compare(event(), kp.fair_lines(BOOKS3[:2], "player_points"), CFG) == []


class FakeAPI:
    def __init__(self):
        self.spent, self.remaining, self.calls = 0, 400, []

    def events(self, sport):
        return [GAME, {**GAME, "id": "late", "commence_time": "2026-11-13T01:00:00Z"}]

    def get(self, path, **params):
        self.calls.append((path, params["markets"]))
        self.spent += 1
        return {"bookmakers": BOOKS3}


def test_scan_bets_once_logs_and_respects_the_credit_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(kp, "DATA", tmp_path)
    monkeypatch.setattr(kp, "STATE", tmp_path / "s.json")
    state, api = kp.load_state(), FakeAPI()
    kal = lambda s: [event()] if s == "KXNBAPTS" else []  # noqa: E731
    stats = kp.scan(api, CFG, state, NOW, kalshi=kal)
    assert stats["games"] == 1 and stats["bets"] == 1 and stats["spent_today"] == 1
    assert api.calls == [("/sports/basketball_nba/events/g1/odds", "player_points")]
    bet = state["open"][0]
    assert bet["side"] == "yes" and bet["contracts"] == 4
    assert kp.scan(api, CFG, state, NOW, kalshi=kal)["games"] == 0  # each game is priced once
    state["priced"].clear()
    assert kp.scan(api, {**CFG, "credits": 1}, state, NOW, kalshi=kal)["games"] == 0  # cap already spent today
    done = kp.settle(state, NOW, kresult=lambda t: "yes")
    assert done[0]["pnl"] == 1.93 and state["open"] == []
    assert kp.record() == {"bets": 1, "won": 1, "profit": 1.93, "staked": 2.0}


def test_near_line_uses_kalshis_step_below_the_books_line():
    books = [book(t, 1.91, 1.91, player="Malik Nabers", point=66.5, key="player_reception_yds") for t in "ABC"]
    ev = {"markets": [
        {"ticker": "K-60", "yes_sub_title": "Malik Nabers: 60+", "floor_strike": 59.5, "strike_type": "greater",
         "yes_ask_dollars": "0.5500", "no_ask_dollars": "0.4700"},
        {"ticker": "K-50", "yes_sub_title": "Malik Nabers: 50+", "floor_strike": 49.5, "strike_type": "greater",
         "yes_ask_dollars": "0.6500", "no_ask_dollars": "0.3700"},
        {"ticker": "K-70", "yes_sub_title": "Malik Nabers: 70+", "floor_strike": 69.5, "strike_type": "greater",
         "yes_ask_dollars": "0.4500", "no_ask_dollars": "0.5700"}]}
    rows = kp.compare(ev, kp.fair_lines(books, "player_reception_yds"), CFG, "player_reception_yds")
    assert len(rows) == 1 and rows[0]["ticker"] == "K-60" and rows[0]["match"] == "near" and rows[0]["book_line"] == 66.5
    assert 0.55 < rows[0]["fair_yes"] < 0.60  # 50% to clear 66.5 -> a bit better than that to clear 59.5
    assert kp.shifted(0.5, 66.5, 29.5, "player_reception_yds") is None  # too far from the book's line
    assert kp.shifted(0.5, 66.5, 59.5, "unknown_stat") is None
