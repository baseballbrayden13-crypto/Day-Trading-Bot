from datetime import datetime, timezone

from bot import parlay_helper as ph

NOW = datetime(2026, 11, 12, 21, 0, tzinfo=timezone.utc)
CFG = {"hours": 24, "max_overpay": 0.03, "max_props": 3, "min_fav": 0.60, "prop_age": 18}
TEAMS = ["New York Giants", "Washington Commanders"]


def fair_file():
    g = {"start": "2026-11-13T01:15:00Z", "sport": "americanfootball_nfl", "teams": TEAMS}
    m = {"start": "2026-11-13T01:00:00Z", "sport": "americanfootball_ncaaf", "teams": ["South Florida Bulls", "Memphis Tigers"]}
    return {"prices": {"KXNFLGAME-X-NYG": {**g, "team": "New York Giants", "fair_yes": 0.62},
                       "KXNFLGAME-X-WAS": {**g, "team": "Washington Commanders", "fair_yes": 0.38},
                       "KXNCAAFGAME-Y-MEM": {**m, "team": "Memphis Tigers", "fair_yes": 0.65},
                       "KXNCAAFGAME-Y-USF": {**m, "team": "South Florida Bulls", "fair_yes": 0.35},
                       "KXNFLGAME-OLD-DAL": {**g, "start": "2026-11-12T18:00:00Z", "team": "Dallas Cowboys", "fair_yes": 0.7}}}


def kalshi(series):
    asks = {"KXNFLGAME": {"KXNFLGAME-X-NYG": "0.6200", "KXNFLGAME-X-WAS": "0.4000"},
            "KXNCAAFGAME": {"KXNCAAFGAME-Y-MEM": "0.6500", "KXNCAAFGAME-Y-USF": "0.3700"}}[series]
    return [{"markets": [{"ticker": t, "yes_ask_dollars": a} for t, a in asks.items()]}]


def row(player, line, fair, yes, no, stat="player_reception_yds", ticker=None, time="2026-11-12T20:39:49+00:00"):
    return {"time": time, "game": "Washington Commanders at New York Giants", "stat": stat, "player": player, "line": str(line),
            "fair_yes": str(fair), "yes_ask": str(yes), "no_ask": str(no), "ticker": ticker or f"T-{player}-{line}"}


ROWS = [row("Malik Nabers", 59.5, 0.58, 0.57, 0.44), row("Jayden Daniels", 199.5, 0.46, 0.55, 0.49, stat="player_pass_yds"),
        row("Theo Johnson", 4.5, 0.62, 0.52, 0.49), row("Theo Johnson", 9.5, 0.40, 0.45, 0.58),
        row("Pricey Guy", 29.5, 0.55, 0.65, 0.36), row("Old News", 9.5, 0.9, 0.5, 0.5, time="2026-11-11T01:00:00+00:00")]


def test_american_odds():
    assert ph.american(0.25) == "+300" and ph.american(0.8) == "-400" and ph.american(0) == "n/a"


def test_game_parlay_picks_the_favorite_and_best_value_props_one_per_player():
    out = ph.build(fair_file(), ROWS, NOW, CFG, kalshi)
    main = next(p for p in out if p["kind"] == "game")
    labels = [l["label"] for l in main["legs"]]
    assert labels[0] == "New York Giants to win" and len(labels) == 4
    assert "Theo Johnson 5+ receiving yards" in labels and "Jayden Daniels under 200 passing yards" in labels
    assert "Malik Nabers 60+ receiving yards" in labels
    assert not any("Pricey" in l or "Old News" in l for l in labels)  # overpriced and stale legs are left out
    assert sum("Theo Johnson" in l for l in labels) == 1
    assert 0 < main["price"] < main["legs"][0]["price"] and main["pays"].startswith("+")
    safer = next(p for p in out if p["kind"] == "game (safer 2-leg)")
    assert len(safer["legs"]) == 2 and safer["fair"] > main["fair"]


def test_favorites_parlay_spans_games_and_skips_started_ones():
    fav = next(p for p in ph.build(fair_file(), [], NOW, CFG, kalshi) if p["kind"] == "favorites")
    assert sorted(l["label"] for l in fav["legs"]) == ["Memphis Tigers to win", "New York Giants to win"]


def test_pretend_record_tracks_once_and_needs_every_leg(tmp_path, monkeypatch):
    monkeypatch.setattr(ph, "DATA", tmp_path)
    out = ph.build(fair_file(), ROWS, NOW, CFG, kalshi)
    state = {"open": [], "seen": {}}
    assert ph.track(out, state, NOW) == 2 and ph.track(out, state, NOW) == 0  # game + favorites; never the safer copy
    fav = next(p for p in state["open"] if p["kind"] == "favorites")
    res = {"KXNFLGAME-X-NYG": "yes", "KXNCAAFGAME-Y-MEM": "yes", "T-Malik Nabers-59.5": "no"}
    done = ph.settle(state, NOW, kresult=lambda t: res.get(t))
    assert {d["kind"]: d["result"] for d in done} == {"favorites": "won", "game": "lost"}  # one missed leg loses it
    assert state["open"] == [] and ph.record() == {"parlays": 2, "won": 1, "profit": round(round(1 / fav["price"] - 1, 2) - 1.0, 2)}
    assert "Pretend record so far: 2 settled, 1 won" in ph.text(out, NOW, ph.record())
