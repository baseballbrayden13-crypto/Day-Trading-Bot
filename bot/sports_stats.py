"""Sports stats bot: free daily scores, team ratings and betting picks for every big league. Pretend money only.

Every run it reads ESPN's free public scoreboards (no key) for the NFL, college football, NBA, WNBA, men's
and women's college basketball, NHL, MLB and the big soccer leagues, then:

  * Rates every team with Elo: a team gains points for winning and loses them for losing, more for a
    surprise result and (football/basketball) for a big margin. Home teams get a small boost.
  * Turns two ratings into a win chance for each upcoming game and compares it with the sportsbook
    line ESPN shows (margin taken out). When the ratings like a team at least SPORTS_MIN_EDGE (5 points
    of win chance) more than the line does, it makes a pretend $10 bet at that line.
  * Grades every finished game: how close the ratings were vs how close the line was (Brier score, lower
    is better), and the pretend record. The first run rates the last SPORTS_BACKFILL days (120) and
    replays the same pick rule on them, so there is a test record from day one.

Soccer gets scores and ratings but no picks (draws make a two-way pick wrong). It never bets for real.

    python -m bot.sports_stats            # update everything, write the report
    python -m bot.sports_stats --report   # print the last report

Output (in sports_data/): report.md (the daily report), summary.json, picks.csv (pretend bets, live and
test), games.csv (every graded game), today.csv (today's games with both chances), state.json.
Settings (env): SPORTS_LEAGUES, SPORTS_MIN_EDGE (0.05), SPORTS_MIN_GAMES (8), SPORTS_MAX_ODDS (4.0),
SPORTS_STAKE (10), SPORTS_BACKFILL (120).
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger("sports")
ET = ZoneInfo("America/New_York")
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
CORE = "https://sports.core.api.espn.com/v2/sports"  # per-game odds, still there after the game (scoreboards drop them)
VERSION = 2  # bump to re-rate everything from scratch on the next run
DATA = Path("sports_data")
STATE = DATA / "state.json"

# key -> (name, ESPN path, extra params, Elo K, home edge in Elo points, margin counts, two-way (picks allowed))
LEAGUES = {
    "nfl": ("NFL", "football/nfl", {}, 20, 48, True, True),
    "ncaaf": ("College football", "football/college-football", {"groups": "80"}, 25, 55, True, True),
    "nba": ("NBA", "basketball/nba", {}, 20, 70, True, True),
    "wnba": ("WNBA", "basketball/wnba", {}, 20, 60, True, True),
    "ncaab": ("Men's college basketball", "basketball/mens-college-basketball", {"groups": "50"}, 20, 80, True, True),
    "ncaaw": ("Women's college basketball", "basketball/womens-college-basketball", {"groups": "50"}, 20, 80, True, True),
    "nhl": ("NHL", "hockey/nhl", {}, 8, 35, False, True),
    "mlb": ("MLB", "baseball/mlb", {}, 4, 24, False, True),
    "mls": ("MLS", "soccer/usa.1", {}, 20, 60, False, False),
    "epl": ("Premier League", "soccer/eng.1", {}, 20, 60, False, False),
    "laliga": ("La Liga", "soccer/esp.1", {}, 20, 60, False, False),
    "bundesliga": ("Bundesliga", "soccer/ger.1", {}, 20, 60, False, False),
    "seriea": ("Serie A", "soccer/ita.1", {}, 20, 60, False, False),
    "ligue1": ("Ligue 1", "soccer/fra.1", {}, 20, 60, False, False),
    "ucl": ("Champions League", "soccer/uefa.champions", {}, 20, 60, False, False),
}
START = 1500.0
NEW_SEASON_DAYS = 75  # a team idle this long is in a new season: its rating moves a third of the way back to 1500


def settings() -> dict:
    keys = [k.strip() for k in os.getenv("SPORTS_LEAGUES", ",".join(LEAGUES)).split(",") if k.strip() in LEAGUES]
    return {
        "leagues": keys,
        "min_edge": float(os.getenv("SPORTS_MIN_EDGE", "0.05")),
        "min_games": int(os.getenv("SPORTS_MIN_GAMES", "8")),
        "max_odds": float(os.getenv("SPORTS_MAX_ODDS", "4.0")),
        "stake": float(os.getenv("SPORTS_STAKE", "10")),
        "backfill": int(os.getenv("SPORTS_BACKFILL", "120")),
    }


# ---------- the math (pure, tested) ----------

def win_chance(home: float, away: float, home_edge: float) -> float:
    """Elo chance the home team wins."""
    return 1 / (1 + 10 ** (-(home + home_edge - away) / 400))


def elo_update(home: float, away: float, home_score: float, away_score: float, k: float, home_edge: float,
               use_margin: bool) -> tuple[float, float]:
    """New (home, away) ratings after a final. A tie counts half a win each."""
    p = win_chance(home, away, home_edge)
    result = 1.0 if home_score > away_score else 0.0 if home_score < away_score else 0.5
    mult = 1.0
    if use_margin and result != 0.5:
        gap = (home + home_edge - away) if result == 1 else (away - home - home_edge)  # winner's head start
        mult = math.log(abs(home_score - away_score) + 1) * 2.2 / (gap * 0.001 + 2.2)
    delta = k * mult * (result - p)
    return home + delta, away - delta


def american_to_decimal(ml) -> float | None:
    try:
        v = float(str(ml).replace("+", "").strip())
    except (TypeError, ValueError):
        return None
    if v >= 100:
        return 1 + v / 100
    if v <= -100:
        return 1 + 100 / -v
    return None


def no_vig(home_dec: float, away_dec: float) -> float:
    """Two decimal odds -> the home team's fair chance with the book's margin taken out."""
    h, a = 1 / home_dec, 1 / away_dec
    return h / (h + a)


def brier(p: float, happened: bool) -> float:
    return (p - (1.0 if happened else 0.0)) ** 2


def pick_for(elo_home: float, market_home: float, home_dec: float, away_dec: float, cfg: dict) -> dict | None:
    """The pretend bet the rule makes on a game, or None: back the side the ratings like more than the line."""
    for side, mine, theirs, dec in (("home", elo_home, market_home, home_dec),
                                    ("away", 1 - elo_home, 1 - market_home, away_dec)):
        if mine - theirs >= cfg["min_edge"] and dec <= cfg["max_odds"]:
            return {"side": side, "odds": round(dec, 3), "elo": round(mine, 3), "market": round(theirs, 3),
                    "edge": round(mine - theirs, 3)}
    return None


def bet_pnl(odds: float, stake: float, won: bool | None) -> float:
    if won is None:  # tie / void
        return 0.0
    return round(stake * (odds - 1), 2) if won else -stake


# ---------- reading ESPN ----------

def espn_scoreboard(league: str, day: str, http=None) -> dict:
    http = http or requests
    _, path, extra, *_ = LEAGUES[league]
    for i in range(3):
        try:
            r = http.get(f"{ESPN}/{path}/scoreboard", params={"dates": day, "limit": 500, **extra}, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i == 2:
                log.warning("ESPN %s %s: %s", league, day, e)
            time.sleep(1 + i)
    return {}


def espn_game_odds(league: str, gid: str, http=None) -> dict:
    """ESPN's saved odds for one game ({"odds": [...]}, same shape _line reads). Any trouble = no line."""
    http = http or requests
    sport, lg = LEAGUES[league][1].split("/")
    try:
        r = http.get(f"{CORE}/{sport}/leagues/{lg}/events/{gid}/competitions/{gid}/odds", timeout=20)
        r.raise_for_status()
        return {"odds": r.json().get("items", [])}
    except Exception as e:
        log.debug("ESPN odds %s %s: %s", league, gid, e)
        return {}


def _line(comp: dict) -> tuple[float, float] | None:
    """(home, away) decimal moneyline from the first ESPN odds entry that has both sides."""
    for o in comp.get("odds") or []:
        h = (o.get("homeTeamOdds") or {}).get("moneyLine")
        a = (o.get("awayTeamOdds") or {}).get("moneyLine")
        ml = o.get("moneyline") or {}
        if h is None or a is None:  # newer layout: moneyline.home.close.odds
            side = lambda s: ((ml.get(s) or {}).get("close") or (ml.get(s) or {}).get("open") or {}).get("odds")
            h, a = side("home"), side("away")
        hd, ad = american_to_decimal(h), american_to_decimal(a)
        if hd and ad:
            return hd, ad
    return None


def parse_games(board: dict) -> list[dict]:
    """ESPN scoreboard -> simple game rows."""
    out = []
    for ev in board.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        cs = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        if "home" not in cs or "away" not in cs:
            continue
        st = (ev.get("status") or {}).get("type") or {}
        row = {"id": str(ev.get("id")), "start": ev.get("date", ""), "name": ev.get("shortName") or ev.get("name", ""),
               "state": st.get("state", ""), "final": bool(st.get("completed")), "neutral": bool(comp.get("neutralSite")),
               "line": _line(comp)}
        for side in ("home", "away"):
            t = cs[side].get("team") or {}
            row[side] = str(t.get("id") or t.get("displayName"))
            row[side + "_name"] = t.get("displayName") or t.get("shortDisplayName") or row[side]
            row[side + "_abbr"] = t.get("abbreviation") or row[side + "_name"]
            try:
                row[side + "_score"] = float(cs[side].get("score"))
            except (TypeError, ValueError):
                row[side + "_score"] = None
        out.append(row)
    return sorted(out, key=lambda g: g["start"])


# ---------- state ----------

def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(s: dict) -> None:
    DATA.mkdir(exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, separators=(",", ":")))
    tmp.replace(STATE)


def team(ratings: dict, tid: str, day: str) -> list:
    """[rating, games this season, last game day]; idle a long time = new season, pulled toward 1500."""
    t = ratings.setdefault(tid, [START, 0, day])
    if (date.fromisoformat(day) - date.fromisoformat(t[2])).days > NEW_SEASON_DAYS:
        t[0], t[1] = START + (t[0] - START) * 2 / 3, 0
    return t


# ---------- one league ----------

def grade_final(league: str, g: dict, ratings: dict, cfg: dict, day: str, lookup=None) -> tuple[dict, dict | None]:
    """Rates a final, returns its graded row and the pick the rule would have made before it (if any).
    lookup(league, id) finds the line when the scoreboard no longer shows one (only asked for seasoned two-way games)."""
    _, _, _, k, edge, margin, two_way = LEAGUES[league]
    hfa = 0 if g["neutral"] else edge
    h, a = team(ratings, g["home"], day), team(ratings, g["away"], day)
    p = win_chance(h[0], a[0], hfa)
    seasoned = min(h[1], a[1]) >= cfg["min_games"]
    if not g["line"] and lookup and two_way and seasoned:
        g["line"] = lookup(league, g["id"])
    hs, as_ = g["home_score"], g["away_score"]
    home_won = None if hs == as_ else hs > as_
    market = no_vig(*g["line"]) if g["line"] else None
    row = {"day": day, "league": league, "game": g["name"], "home": g["home_name"], "away": g["away_name"],
           "score": f"{as_:g}-{hs:g}", "elo_home": round(p, 3), "market_home": round(market, 3) if market else "",
           "home_won": "" if home_won is None else int(home_won), "seasoned": int(seasoned),
           "elo_brier": round(brier(p, bool(home_won)), 4) if home_won is not None else "",
           "market_brier": round(brier(market, bool(home_won)), 4) if market and home_won is not None else ""}
    pick = None
    if two_way and seasoned and market:
        pick = pick_for(p, market, *g["line"], cfg)
        if pick:
            won = None if home_won is None else (home_won == (pick["side"] == "home"))
            pick.update(id=g["id"], league=league, day=day, game=g["name"], team=g[pick["side"] + "_name"],
                        status="settled", won="" if won is None else int(won), pnl=bet_pnl(pick["odds"], cfg["stake"], won))
    h[0], a[0] = elo_update(h[0], a[0], hs, as_, k, hfa, margin)
    h[1], a[1], h[2], a[2] = h[1] + 1, a[1] + 1, day, day
    return row, pick


def update_league(league: str, state: dict, cfg: dict, today: date, board=espn_scoreboard, odds=espn_game_odds) -> dict:
    """Rates every finished day since last time, then prices today. Returns this league's news."""
    lg = state.setdefault("leagues", {}).setdefault(league, {"ratings": {}, "through": None})
    ratings = lg["ratings"]
    names = state.setdefault("names", {}).setdefault(league, {})
    saved = state.setdefault("lines", {}).setdefault(league, {})  # pre-game lines seen on earlier runs

    def lookup(lg_key, gid):
        if gid in saved:
            return tuple(saved[gid])
        return _line(odds(lg_key, gid))
    first = lg["through"] is None
    start = today - timedelta(days=cfg["backfill"]) if first else date.fromisoformat(lg["through"]) + timedelta(days=1)
    news = {"finals": [], "graded": [], "test_picks": [], "today": []}
    d = start
    while d < today:
        day = d.isoformat()
        for g in parse_games(board(league, d.strftime("%Y%m%d"))):
            names[g["home"]], names[g["away"]] = g["home_name"], g["away_name"]
            if g["final"] and g["home_score"] is not None and g["away_score"] is not None:
                row, pick = grade_final(league, g, ratings, cfg, day, lookup)
                saved.pop(g["id"], None)
                news["graded"].append(row)
                if d == today - timedelta(days=1):
                    news["finals"].append(row)
                if pick:
                    pick["kind"] = "test" if first else "replay"
                    news["test_picks"].append(pick)
        lg["through"] = day
        d += timedelta(days=1)
    _, _, _, _, edge, _, two_way = LEAGUES[league]
    for g in parse_games(board(league, today.strftime("%Y%m%d"))):
        h, a = ratings.get(g["home"]), ratings.get(g["away"])
        p = win_chance(h[0] if h else START, a[0] if a else START, 0 if g["neutral"] else edge)
        if g["line"] and g["state"] == "pre":
            saved[g["id"]] = [round(x, 4) for x in g["line"]]  # last line before the game: graded tomorrow
        market = no_vig(*g["line"]) if g["line"] else None
        seasoned = bool(h and a and min(h[1], a[1]) >= cfg["min_games"])
        row = {"league": league, "id": g["id"], "start": g["start"], "game": g["name"], "home": g["home_name"],
               "away": g["away_name"], "state": g["state"], "elo_home": round(p, 3),
               "market_home": round(market, 3) if market else "", "seasoned": int(seasoned), "pick": ""}
        if two_way and seasoned and market and g["state"] == "pre":
            pick = pick_for(p, market, *g["line"], cfg)
            if pick:
                row["pick"] = f"{g[pick['side'] + '_name']} @ {pick['odds']:.2f} (+{pick['edge'] * 100:.0f} pts)"
                pick.update(id=g["id"], league=league, day=today.isoformat(), game=g["name"],
                            team=g[pick["side"] + "_name"], status="open", won="", pnl="", kind="live")
                row["new_pick"] = pick
        news["today"].append(row)
    return news


def settle_open(picks: list[dict], today: date, cfg: dict, board=espn_scoreboard) -> int:
    """Settles open live picks whose game is now final (checks the pick day and the next, for late games)."""
    n, boards = 0, {}
    for p in picks:
        if p.get("status") != "open":
            continue
        d0 = date.fromisoformat(p["day"])
        for d in (d0, d0 + timedelta(days=1)):
            if d > today:
                continue
            key = (p["league"], d)
            if key not in boards:
                boards[key] = {g["id"]: g for g in parse_games(board(p["league"], d.strftime("%Y%m%d")))}
            g = boards[key].get(p["id"])
            if g and g["final"] and g["home_score"] is not None:
                home_won = None if g["home_score"] == g["away_score"] else g["home_score"] > g["away_score"]
                won = None if home_won is None else home_won == (p["side"] == "home")
                p.update(status="settled", won="" if won is None else int(won),
                         pnl=bet_pnl(float(p["odds"]), cfg["stake"], won))
                n += 1
                break
        else:
            if (today - d0).days > 5:  # postponed / vanished: void it
                p.update(status="settled", won="", pnl=0.0)
                n += 1
    return n


# ---------- files ----------

PICK_COLS = ["kind", "day", "league", "game", "team", "side", "odds", "elo", "market", "edge", "status", "won", "pnl", "id"]
GAME_COLS = ["day", "league", "game", "home", "away", "score", "elo_home", "market_home", "home_won", "seasoned",
             "elo_brier", "market_brier"]
TODAY_COLS = ["league", "start", "game", "home", "away", "state", "elo_home", "market_home", "seasoned", "pick", "id"]


def read_csv(path: Path) -> list[dict]:
    try:
        with path.open(newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def write_csv(path: Path, cols: list[str], rows: list[dict], append: bool = False) -> None:
    DATA.mkdir(exist_ok=True)
    new = not path.exists() or not append
    with path.open("a" if append else "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def record(picks: list[dict], kinds: tuple[str, ...]) -> dict:
    done = [p for p in picks if p.get("kind") in kinds and p.get("status") == "settled" and p.get("won") != ""]
    staked = float(len(done))
    pnl = round(sum(float(p["pnl"]) for p in done), 2)
    wins = sum(1 for p in done if int(p["won"]))
    by = {}
    for p in done:
        b = by.setdefault(p["league"], {"bets": 0, "wins": 0, "pnl": 0.0})
        b["bets"] += 1
        b["wins"] += int(p["won"])
        b["pnl"] = round(b["pnl"] + float(p["pnl"]), 2)
    stake = float(os.getenv("SPORTS_STAKE", "10"))
    return {"bets": len(done), "wins": wins, "losses": len(done) - wins, "pnl": pnl,
            "roi": round(pnl / (staked * stake), 4) if staked else 0.0, "by_league": by,
            "open": sum(1 for p in picks if p.get("kind") in kinds and p.get("status") == "open")}


def accuracy(games: list[dict]) -> dict:
    """Ratings vs line on games that had both (seasoned teams only): lower Brier = closer guesses."""
    out = {}
    for g in games:
        if g.get("market_brier") in ("", None) or g.get("elo_brier") in ("", None) or str(g.get("seasoned")) != "1":
            continue
        a = out.setdefault(g["league"], {"games": 0, "elo": 0.0, "market": 0.0})
        a["games"] += 1
        a["elo"] += float(g["elo_brier"])
        a["market"] += float(g["market_brier"])
    return {k: {"games": v["games"], "elo_brier": round(v["elo"] / v["games"], 4),
                "market_brier": round(v["market"] / v["games"], 4)} for k, v in out.items()}


def top_teams(state: dict, league: str, n: int = 5) -> list[tuple[str, float]]:
    names = state.get("names", {}).get(league, {})
    r = state.get("leagues", {}).get(league, {}).get("ratings", {})
    best = sorted(((v[0], tid) for tid, v in r.items() if v[1] >= 3), reverse=True)[:n]
    return [(names.get(tid, tid), round(v)) for v, tid in best]


def money(x: float) -> str:
    return f"{'+' if x >= 0 else '-'}${abs(x):,.2f}"


def write_report(state: dict, news: dict, picks: list[dict], games: list[dict], cfg: dict, now: datetime) -> dict:
    live, test = record(picks, ("live",)), record(picks, ("test", "replay"))
    acc = accuracy(games)
    L = [f"# Sports stats bot: {now:%a %b %d, %I:%M %p} ET", "",
         "Pretend money only. Ratings = Elo from ESPN results; line = sportsbook odds ESPN shows, margin removed.", ""]
    L += ["## Pretend record",
          f"- Live picks: {live['bets']} settled, {live['wins']}-{live['losses']}, {money(live['pnl'])} "
          f"({live['roi'] * 100:+.1f}% of money bet), {live['open']} open",
          f"- Test on past games: {test['bets']} bets, {test['wins']}-{test['losses']}, {money(test['pnl'])} "
          f"({test['roi'] * 100:+.1f}%)", ""]
    picks_today = [r for k in cfg["leagues"] for r in news[k]["today"] if r.get("pick")]
    L += ["## Today's picks"] + ([f"- {LEAGUES[r['league']][0]}: {r['game']}: **{r['pick']}** "
                                  f"(ratings {r['elo_home'] * 100:.0f}% home, line {float(r['market_home']) * 100:.0f}% home)"
                                  for r in picks_today] or ["- None today."]) + [""]
    L.append("## Yesterday's scores")
    any_final = False
    for k in cfg["leagues"]:
        fs = news[k]["finals"]
        if not fs:
            continue
        any_final = True
        ups = [f for f in fs if f["home_won"] != "" and ((int(f["home_won"]) and f["elo_home"] < 0.35)
                                                         or (not int(f["home_won"]) and f["elo_home"] > 0.65))]
        L.append(f"**{LEAGUES[k][0]}** ({len(fs)} games" + (f", {len(ups)} upsets" if ups else "") + ")")
        for f in fs[:12]:
            L.append(f"- {f['away']} at {f['home']}: {f['score']}" + (" (upset)" if f in ups else ""))
        if len(fs) > 12:
            L.append(f"- and {len(fs) - 12} more")
    if not any_final:
        L.append("- No finals yesterday.")
    L += ["", "## Today's games"]
    for k in cfg["leagues"]:
        rows = news[k]["today"]
        if rows:
            L.append(f"**{LEAGUES[k][0]}**: {len(rows)} games, {sum(1 for r in rows if r['market_home'] != '')} with a line")
    L += ["", "## Top teams by rating"]
    for k in cfg["leagues"]:
        t = top_teams(state, k)
        if t:
            L.append(f"- {LEAGUES[k][0]}: " + ", ".join(f"{n} {r}" for n, r in t))
    L += ["", "## Ratings vs the line (lower = closer guesses)"]
    for k, a in acc.items():
        better = "ratings closer" if a["elo_brier"] < a["market_brier"] else "line closer"
        L.append(f"- {LEAGUES[k][0]}: {a['games']} games, ratings {a['elo_brier']:.3f} vs line {a['market_brier']:.3f} ({better})")
    if not acc:
        L.append("- No graded games with a line yet.")
    DATA.mkdir(exist_ok=True)
    (DATA / "report.md").write_text("\n".join(L) + "\n")
    summary = {"updated": now.isoformat(timespec="seconds"), "live": live, "test": test, "accuracy": acc,
               "picks_today": len(picks_today), "settings": cfg}
    (DATA / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


# ---------- run ----------

def run(cfg: dict, now: datetime, board=espn_scoreboard, odds=espn_game_odds) -> dict:
    today = now.astimezone(ET).date()
    state = load_state()
    picks = read_csv(DATA / "picks.csv")
    if state.get("version") != VERSION:  # re-rate from scratch; live picks are kept
        state = {"version": VERSION}
        picks = [p for p in picks if p.get("kind") == "live"]
        (DATA / "games.csv").unlink(missing_ok=True)
    have = {(p["kind"] == "live", p["id"]) for p in picks}
    news, graded, today_rows = {}, [], []
    for k in cfg["leagues"]:
        try:
            news[k] = update_league(k, state, cfg, today, board, odds)
        except Exception as e:  # one league's trouble never stops the rest
            log.warning("%s: %s", k, e)
            news[k] = {"finals": [], "graded": [], "test_picks": [], "today": []}
        graded += news[k]["graded"]
        for p in news[k]["test_picks"]:
            if (False, p["id"]) not in have:
                picks.append(p)
                have.add((False, p["id"]))
        for r in news[k]["today"]:
            p = r.pop("new_pick", None)
            if p and (True, p["id"]) not in have:
                picks.append(p)
                have.add((True, p["id"]))
            today_rows.append(r)
    settle_open(picks, today, cfg, board)
    write_csv(DATA / "games.csv", GAME_COLS, graded, append=True)
    write_csv(DATA / "picks.csv", PICK_COLS, picks)
    write_csv(DATA / "today.csv", TODAY_COLS, today_rows)
    save_state(state)
    return write_report(state, news, picks, read_csv(DATA / "games.csv"), cfg, now.astimezone(ET))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--report", action="store_true", help="print the last report")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if args.report:
        print((DATA / "report.md").read_text() if (DATA / "report.md").exists() else "No report yet.")
        return
    s = run(settings(), datetime.now(timezone.utc))
    print((DATA / "report.md").read_text())
    log.info("live %s | test %s", s["live"], s["test"])


if __name__ == "__main__":
    main()
