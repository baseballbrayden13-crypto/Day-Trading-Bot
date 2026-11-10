from datetime import datetime, timedelta, timezone

import pytest

from bot import odds_finder as of

NOW = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)
CFG = {"min_edge": 0.03, "min_books": 4, "max_odds": 5.0, "hours": 36, "stake": 10, "monthly": 500, "ntfy": "",
       "sports": ["americanfootball_nfl"], "key": "k"}


def game(prices: dict[str, tuple[float, float]], start=NOW + timedelta(hours=3), gid="g1"):
    return {"id": gid, "sport_key": "americanfootball_nfl", "commence_time": start.isoformat().replace("+00:00", "Z"),
            "home_team": "Miami Dolphins", "away_team": "Buffalo Bills",
            "bookmakers": [{"key": b.lower(), "title": b, "markets": [{"key": "h2h", "outcomes": [
                {"name": "Miami Dolphins", "price": h}, {"name": "Buffalo Bills", "price": a}]}]}
                for b, (h, a) in prices.items()]}


FAIR = {"A": (2.5, 1.57), "B": (2.45, 1.59), "C": (2.55, 1.56), "D": (2.5, 1.58)}


def test_no_vig_adds_to_one():
    p = of.no_vig({"x": 1.91, "y": 1.91})
    assert p == pytest.approx({"x": 0.5, "y": 0.5})


def test_value_bet_found_only_for_the_outlier_book():
    g = game({**FAIR, "Soft": (2.9, 1.40)})
    finds = of.value_bets(g, of.book_prices(g), CFG)
    assert [(f["book"], f["team"]) for f in finds] == [("Soft", "Miami Dolphins")]
    assert finds[0]["edge"] > 0.10


def test_no_value_when_books_agree_or_too_few():
    g = game(FAIR)
    assert of.value_bets(g, of.book_prices(g), CFG) == []
    g2 = game({"A": (2.9, 1.4), "B": (2.4, 1.6)})
    assert of.value_bets(g2, of.book_prices(g2), CFG) == []


def test_arbitrage_and_stakes():
    g = game({**FAIR, "X": (2.75, 1.4), "Y": (1.9, 1.75)})
    arb = of.arbitrage(g, of.book_prices(g), {})
    assert arb and arb["edge"] == pytest.approx(1 / (1 / 2.75 + 1 / 1.75) - 1, abs=1e-4)
    payouts = {round(l["stake"] * l["odds"], 0) for l in arb["legs"]}
    assert len(payouts) == 1  # the same payout whoever wins
    assert sum(l["stake"] for l in arb["legs"]) == pytest.approx(100, abs=0.02)
    assert of.arbitrage(game(FAIR), of.book_prices(game(FAIR)), {}) is None


def test_kalshi_value_counts_the_fee():
    g = game(FAIR)
    books = of.book_prices(g)
    fair_miami = of.fair_odds(books)["Miami Dolphins"]  # ~0.385
    cheap = {"Miami Dolphins": {"ask": 0.35, "ticker": "T-MIA"}}
    assert of.kalshi_value(g, books, cheap, CFG)[0]["edge"] == pytest.approx(fair_miami / of.kalshi_cost(0.35) - 1, abs=1e-4)
    assert of.kalshi_cost(0.35) > 0.35
    assert of.kalshi_value(g, books, {"Miami Dolphins": {"ask": 0.38, "ticker": "T"}}, CFG) == []


def test_kalshi_matching_by_short_names_and_date():
    g = game(FAIR)
    ev = {"event_ticker": "KXNFLGAME-26NOV09BUFMIA", "markets": [
        {"ticker": "KXNFLGAME-26NOV09BUFMIA-BUF", "yes_sub_title": "Buffalo", "yes_ask_dollars": "0.62"},
        {"ticker": "KXNFLGAME-26NOV09BUFMIA-MIA", "yes_sub_title": "Miami", "yes_ask_dollars": "0.39"}]}
    wrong_day = {**ev, "event_ticker": "KXNFLGAME-26DEC21BUFMIA"}
    assert of.kalshi_for_game(g, [wrong_day]) == {}
    k = of.kalshi_for_game(g, [wrong_day, ev])
    assert k["Buffalo Bills"]["ask"] == 0.62 and k["Miami Dolphins"]["ticker"].endswith("MIA")
    assert of.name_fits("New York G", "New York Giants") and not of.name_fits("New York G", "New York Jets")


def scoreboard(home_won=True, done=True):
    return {"events": [{"status": {"type": {"completed": done}}, "competitions": [{"competitors": [
        {"homeAway": "home", "winner": home_won, "team": {"displayName": "Miami Dolphins"}},
        {"homeAway": "away", "winner": not home_won, "team": {"displayName": "Buffalo Bills"}}]}]}]}


def test_paper_bets_open_once_and_settle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    g = game({**FAIR, "Soft": (2.9, 1.40)})
    state = {"open": [], "seen": {}, "credits": {}}
    finds = of.value_bets(g, of.book_prices(g), CFG)
    assert len(of.open_bets(finds, state, 10, NOW)) == 1
    assert of.open_bets(finds, state, 10, NOW) == []  # same find next scan: not bet twice
    assert of.settle(state, NOW + timedelta(hours=4), scoreboard=lambda s, d: scoreboard(done=False)) == []
    done = of.settle(state, NOW + timedelta(hours=6), scoreboard=lambda s, d: scoreboard(home_won=True))
    assert done[0]["pnl"] == pytest.approx(19.0) and state["open"] == []
    rec = of.record()
    assert rec["value"]["bets"] == 1 and rec["all"]["pnl"] == pytest.approx(19.0)


def test_arb_settles_to_a_profit_either_way(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    g = game({**FAIR, "X": (2.75, 1.4), "Y": (1.9, 1.75)})
    for home_won in (True, False):
        state = {"open": [], "seen": {}, "credits": {}}
        of.open_bets([of.arbitrage(g, of.book_prices(g), {})], state, 10, NOW)
        done = of.settle(state, NOW + timedelta(hours=6), scoreboard=lambda s, d: scoreboard(home_won=home_won))
        assert done[0]["pnl"] > 0


def test_kalshi_leg_settles_from_kalshi(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = {"open": [], "seen": {}, "credits": {}}
    g = game(FAIR)
    f = of.kalshi_value(g, of.book_prices(g), {"Miami Dolphins": {"ask": 0.30, "ticker": "T-MIA"}}, CFG)
    of.open_bets(f, state, 10, NOW)
    done = of.settle(state, NOW + timedelta(hours=6), scoreboard=lambda s, d: {}, kresult=lambda t: "yes")
    assert done[0]["pnl"] == pytest.approx(10 * (f[0]["odds"] - 1), abs=0.02)


def test_unfound_game_is_void_after_four_days(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    g = game({**FAIR, "Soft": (2.9, 1.40)})
    state = {"open": [], "seen": {}, "credits": {}}
    of.open_bets(of.value_bets(g, of.book_prices(g), CFG), state, 10, NOW)
    assert of.settle(state, NOW + timedelta(days=1), scoreboard=lambda s, d: {}) == []
    done = of.settle(state, NOW + timedelta(days=5), scoreboard=lambda s, d: {})
    assert done[0]["pnl"] == 0 and done[0]["winner"] == "unknown"


def test_daily_allowance_spreads_credits():
    nov9 = datetime(2026, 11, 9, 12)
    assert of.daily_allowance(None, nov9, 500) == 16
    assert of.daily_allowance(440, nov9, 500) == 20  # 440 over 22 days
    assert of.daily_allowance(440, datetime(2026, 11, 30, 12), 500) == 32  # capped at twice the even share
    assert of.daily_allowance(0, nov9, 500) == 0


class FakeAPI:
    def __init__(self, games):
        self.games, self.spent, self.remaining, self.odds_calls = games, 0, 100, 0

    def events(self, sport):
        return [{k: g[k] for k in ("id", "commence_time")} for g in self.games]

    def odds(self, sport):
        self.odds_calls += 1
        self.spent += 1
        self.remaining -= 1
        return self.games


def test_scan_skips_sports_with_no_games_soon_and_respects_the_allowance():
    far = game(FAIR, start=NOW + timedelta(days=5))
    api = FakeAPI([far])
    finds, stats = of.scan(api, CFG, {"open": [], "seen": {}, "credits": {}}, NOW, kalshi=lambda s: [])
    assert api.odds_calls == 0 and finds == []
    api = FakeAPI([game({**FAIR, "Soft": (2.9, 1.40)})])
    state = {"open": [], "seen": {}, "credits": {"day": "2026-11-09", "spent": 99, "remaining": 100}}
    finds, stats = of.scan(api, CFG, state, NOW, kalshi=lambda s: [])
    assert api.odds_calls == 0 and stats["skipped"] == ["americanfootball_nfl"]
    state["credits"]["spent"] = 0
    finds, stats = of.scan(api, CFG, state, NOW, kalshi=lambda s: [])
    assert api.odds_calls == 1 and [f["kind"] for f in finds] == ["value", "arb"] and state["credits"]["remaining"] == 99


def test_new_finds_can_be_described_and_alerted(tmp_path, monkeypatch):
    # Nov 9 crash: alert() was handed the pretend bets instead of the finds (KeyError 'team')
    monkeypatch.chdir(tmp_path)
    g = game({**FAIR, "Soft": (2.9, 1.40)})
    finds, _ = of.scan(FakeAPI([g]), CFG, {"open": [], "seen": {}, "credits": {}}, NOW, kalshi=lambda s: [])
    state = {"open": [], "seen": {}, "credits": {}}
    new = of.open_bets(finds, state, 10, NOW)
    assert {f["kind"] for f in new} == {"value", "arb"} and len(state["open"]) == 2
    assert all(of.describe(f) for f in new)
    of.alert(CFG, new)
    assert "Odds finder" in (tmp_path / "fleet_data" / "alerts.csv").read_text()


def test_quiet_hours_and_gap_save_credits():
    g = game({**FAIR, "Soft": (2.9, 1.40)})
    cfg = {**CFG, "gap": 2.5, "quiet": "1-8"}
    api = FakeAPI([g])
    night = datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc)  # 3am ET
    of.scan(api, cfg, {"open": [], "seen": {}, "credits": {}}, night, kalshi=lambda s: [])
    assert api.odds_calls == 0
    state = {"open": [], "seen": {}, "credits": {}}
    of.scan(api, cfg, state, NOW, kalshi=lambda s: [])
    of.scan(api, cfg, state, NOW + timedelta(hours=1), kalshi=lambda s: [])
    assert api.odds_calls == 1  # priced an hour ago: wait
    of.scan(api, cfg, state, NOW + timedelta(hours=2.6), kalshi=lambda s: [])
    assert api.odds_calls == 2


def test_kalshi_fair_prices_written_for_matched_games(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ev = {"event_ticker": "KXNFLGAME-26NOV09BUFMIA", "markets": [
        {"ticker": "T-BUF", "yes_sub_title": "Buffalo", "yes_ask_dollars": "0.62"},
        {"ticker": "T-MIA", "yes_sub_title": "Miami", "yes_ask_dollars": "0.39"}]}
    _, stats = of.scan(FakeAPI([game(FAIR)]), CFG, {"open": [], "seen": {}, "credits": {}}, NOW, kalshi=lambda s: [ev])
    of.write_kalshi_fair(stats.pop("kalshi_fair"), NOW)
    prices = __import__("json").loads((tmp_path / "odds_data" / "kalshi_fair.json").read_text())["prices"]
    assert prices["T-BUF"]["fair_yes"] + prices["T-MIA"]["fair_yes"] == pytest.approx(1, abs=1e-3)
    of.write_kalshi_fair({}, NOW + timedelta(hours=4))  # game started: dropped
    assert __import__("json").loads((tmp_path / "odds_data" / "kalshi_fair.json").read_text())["prices"] == {}
