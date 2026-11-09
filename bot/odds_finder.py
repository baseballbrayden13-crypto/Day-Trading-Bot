"""The sports odds finder: alerts only, pretend money only. It never places a bet.

Every scan it pulls the moneyline (who wins) odds for upcoming games from many US sportsbooks
(The Odds API, free plan) and the matching Kalshi game markets (public prices, no keys), then flags:

  * Value bets: one book pays more than the game is worth. "Worth" is the fair chance of each team
    winning from all the OTHER books, with their built-in margin (the vig) taken out. A bet is flagged
    when it is expected to make at least ODDS_MIN_EDGE (3%) of the stake.
  * Kalshi value: same test on Kalshi's YES price, after Kalshi's fee.
  * Arbitrage: the best price on every side, across books and Kalshi, adds up to less than 100%, so
    betting every side locks in a profit whoever wins.

Each find becomes a pretend bet ($10 for a value bet, $100 split across the sides for an arb), settled
later from ESPN's free scoreboard (Kalshi bets from Kalshi's own result). The record shows if the finds
would really have made money before anyone thinks about real bets.

The free Odds API plan has 500 credits a month. One sport's odds costs 1 credit; the list of games is
free. So a sport is only priced when it has a game soon, and spending is spread over the month.

    python -m bot.odds_finder              # one scan + settle (needs ODDS_API_KEY)
    python -m bot.odds_finder --settle     # only settle open pretend bets (no credits)
    python -m bot.odds_finder --report     # print the record

Settings (env): ODDS_API_KEY, ODDS_SPORTS, ODDS_MIN_EDGE (0.03), ODDS_MIN_BOOKS (4), ODDS_MAX_ODDS (5.0),
ODDS_HOURS (36), ODDS_STAKE (10), ODDS_MONTHLY_CREDITS (500), NTFY_TOPIC (phone alerts, optional).
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

import requests

from .kalshi import D, fee

log = logging.getLogger("odds")
ET = ZoneInfo("America/New_York")
API = "https://api.the-odds-api.com/v4"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
DATA = Path("odds_data")
STATE = Path("odds_state.json")

# Odds API sport key -> (Kalshi game-winner series, ESPN scoreboard path, extra ESPN params)
SPORTS = {
    "americanfootball_nfl": ("KXNFLGAME", "football/nfl", {}),
    "basketball_nba": ("KXNBAGAME", "basketball/nba", {}),
    "icehockey_nhl": ("KXNHLGAME", "hockey/nhl", {}),
    "americanfootball_ncaaf": ("KXNCAAFGAME", "football/college-football", {"groups": "80"}),
    "basketball_ncaab": ("KXNCAAMBGAME", "basketball/mens-college-basketball", {"groups": "50"}),
    "baseball_mlb": ("KXMLBGAME", "baseball/mlb", {}),
}


def settings() -> dict:
    return {
        "key": os.getenv("ODDS_API_KEY", "").strip(),
        "sports": [s.strip() for s in os.getenv("ODDS_SPORTS", ",".join(SPORTS)).split(",") if s.strip()],
        "min_edge": float(os.getenv("ODDS_MIN_EDGE", "0.03")),
        "min_books": int(os.getenv("ODDS_MIN_BOOKS", "4")),
        "max_odds": float(os.getenv("ODDS_MAX_ODDS", "5.0")),  # long shots: the fair price is too noisy to trust
        "hours": float(os.getenv("ODDS_HOURS", "36")),  # only games starting this soon
        "stake": float(os.getenv("ODDS_STAKE", "10")),
        "monthly": int(os.getenv("ODDS_MONTHLY_CREDITS", "500")),
        "ntfy": os.getenv("NTFY_TOPIC", "").strip(),
    }


# ---------- the math (pure, tested) ----------

def no_vig(prices: dict[str, float]) -> dict[str, float]:
    """One book's decimal odds -> its fair chances with the margin taken out (scaled to add up to 1)."""
    raw = {k: 1 / v for k, v in prices.items() if v and v > 1}
    total = sum(raw.values())
    return {k: p / total for k, p in raw.items()} if total else {}


def book_prices(game: dict) -> dict[str, dict[str, float]]:
    """{book: {team: decimal odds}} from an Odds API game; books missing a side are left out."""
    teams = {game["home_team"], game["away_team"]}
    out = {}
    for b in game.get("bookmakers", []):
        for m in b.get("markets", []):
            if m.get("key") != "h2h":
                continue
            prices = {o["name"]: float(o["price"]) for o in m.get("outcomes", [])}
            if teams <= set(prices) and all(p > 1 for p in prices.values()):
                out[b.get("title") or b["key"]] = prices
    return out


def fair_odds(books: dict[str, dict[str, float]], leave_out: str | None = None) -> dict[str, float]:
    """Fair chance of each side: the median of every book's no-vig chances (optionally skipping one
    book, so a book is never judged against itself), scaled to add up to 1."""
    sides: dict[str, list[float]] = {}
    for name, prices in books.items():
        if name == leave_out:
            continue
        for k, p in no_vig(prices).items():
            sides.setdefault(k, []).append(p)
    mid = {k: median(v) for k, v in sides.items()}
    total = sum(mid.values())
    return {k: p / total for k, p in mid.items()} if total else {}


def value_bets(game: dict, books: dict[str, dict[str, float]], cfg: dict) -> list[dict]:
    """Prices that pay more than the other books say the game is worth."""
    out = []
    if len(books) < cfg["min_books"]:
        return out
    for name, prices in books.items():
        fair = fair_odds(books, leave_out=name)
        for team, odds in prices.items():
            if team not in fair or odds > cfg["max_odds"]:
                continue
            edge = fair[team] * odds - 1
            if edge >= cfg["min_edge"]:
                out.append({"kind": "value", "game": game_name(game), "game_id": game["id"], "sport": game["sport_key"],
                            "start": game["commence_time"], "team": team, "book": name, "odds": round(odds, 3),
                            "fair": round(fair[team], 4), "edge": round(edge, 4)})
    return out


def kalshi_cost(ask: float) -> float:
    """Dollars per $1 Kalshi contract: the YES ask plus Kalshi's taker fee (on a 10-contract buy)."""
    price = D(str(ask))
    return float(price + fee(10, price) / 10)


def kalshi_value(game: dict, books: dict, kalshi: dict[str, dict], cfg: dict) -> list[dict]:
    """Kalshi YES prices below the sportsbooks' fair chance (after the fee)."""
    out = []
    if len(books) < cfg["min_books"]:
        return out
    fair = fair_odds(books)
    for team, k in kalshi.items():
        cost = kalshi_cost(k["ask"])
        if team not in fair or not 0 < cost < 1 or 1 / cost > cfg["max_odds"]:
            continue
        edge = fair[team] / cost - 1
        if edge >= cfg["min_edge"]:
            out.append({"kind": "kalshi", "game": game_name(game), "game_id": game["id"], "sport": game["sport_key"],
                        "start": game["commence_time"], "team": team, "book": "Kalshi", "odds": round(1 / cost, 3),
                        "fair": round(fair[team], 4), "edge": round(edge, 4), "ticker": k["ticker"], "ask": k["ask"]})
    return out


def arbitrage(game: dict, books: dict, kalshi: dict[str, dict], total: float = 100.0) -> dict | None:
    """Best price on each side across books and Kalshi; an arb when 1/odds adds up below 1."""
    best: dict[str, tuple[float, str]] = {}
    sides = {game["home_team"], game["away_team"]}
    for name, prices in books.items():
        for team, odds in prices.items():
            if odds > best.get(team, (0, ""))[0]:
                best[team] = (odds, name)
    for team, k in kalshi.items():
        cost = kalshi_cost(k["ask"])
        if 0 < cost < 1 and 1 / cost > best.get(team, (0, ""))[0]:
            best[team] = (1 / cost, "Kalshi")
    if set(best) != sides:
        return None
    s = sum(1 / o for o, _ in best.values())
    if s >= 0.995:  # under half a percent isn't worth the risk of a price moving mid-bet
        return None
    legs = [{"team": t, "book": b, "odds": round(o, 3), "stake": round(total / o / s, 2),
             **({"ticker": kalshi[t]["ticker"], "ask": kalshi[t]["ask"]} if b == "Kalshi" else {})}
            for t, (o, b) in best.items()]
    return {"kind": "arb", "game": game_name(game), "game_id": game["id"], "sport": game["sport_key"],
            "start": game["commence_time"], "legs": legs, "edge": round(1 / s - 1, 4)}


def game_name(g: dict) -> str:
    return f"{g['away_team']} at {g['home_team']}"


# ---------- matching Kalshi and ESPN games to the odds ----------

def _words(s: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]", " ", s.lower().replace("&", " ")).split()


def name_fits(short: str, full: str) -> bool:
    """Kalshi names teams short ("Los Angeles R", "New York G"); every word must start a word of the full name."""
    words, full_words = _words(short), _words(full)
    return bool(words) and all(any(f.startswith(w) for f in full_words) for w in words)


TICKER_DATE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})")
MONTHS = {m: i for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}


def kalshi_for_game(game: dict, events: list[dict]) -> dict[str, dict]:
    """{team: {"ask", "ticker"}} from the Kalshi event for this game (same day, both teams matched)."""
    start = datetime.fromisoformat(game["commence_time"].replace("Z", "+00:00")).astimezone(ET).date()
    teams = [game["home_team"], game["away_team"]]
    for e in events:
        m = TICKER_DATE.search(e.get("event_ticker", ""))
        if m and m.group(2) in MONTHS:
            day = datetime(2000 + int(m.group(1)), MONTHS[m.group(2)], int(m.group(3))).date()
            if abs((day - start).days) > 1:
                continue
        out = {}
        for mk in e.get("markets", []):
            label = mk.get("yes_sub_title") or ""
            fits = [t for t in teams if name_fits(label, t)]
            ask = float(mk.get("yes_ask_dollars") or 0)
            if len(fits) == 1 and 0 < ask < 1:
                out[fits[0]] = {"ask": ask, "ticker": mk["ticker"]}
        if len(out) == 2:
            return out
    return {}


def espn_winner(game: dict, scoreboard: dict) -> str | None:
    """The winning team's Odds API name once ESPN shows the game final; "void" for a tie; None if not found/final."""
    teams = [game["home_team"], game["away_team"]]
    for ev in scoreboard.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        cs = comp.get("competitors", [])
        names = {c.get("homeAway"): c.get("team", {}).get("displayName", "") for c in cs}
        if not (_same(names.get("home", ""), teams[0]) and _same(names.get("away", ""), teams[1])):
            continue
        if not ev.get("status", {}).get("type", {}).get("completed"):
            return None
        for c in cs:
            if c.get("winner"):
                return teams[0] if c.get("homeAway") == "home" else teams[1]
        return "void"
    return None


def _same(a: str, b: str) -> bool:
    return bool(a) and (_words(a) == _words(b) or name_fits(a, b) or name_fits(b, a))


# ---------- data sources ----------

class OddsAPI:
    def __init__(self, key: str, http=None):
        self.key, self.http = key, http or requests.Session()
        self.remaining: int | None = None
        self.spent = 0

    def get(self, path: str, **params):
        r = self.http.get(f"{API}{path}", params={"apiKey": self.key, **params}, timeout=20)
        if r.headers.get("x-requests-remaining") is not None:
            self.remaining = int(float(r.headers["x-requests-remaining"]))
        self.spent += int(float(r.headers.get("x-requests-last") or 0))
        if r.status_code == 401:
            raise SystemExit("The Odds API says the key is wrong (401). Check the ODDS_API_KEY secret.")
        r.raise_for_status()
        return r.json()

    def events(self, sport: str) -> list[dict]:  # free
        return self.get(f"/sports/{sport}/events")

    def odds(self, sport: str) -> list[dict]:  # 1 credit (1 region x 1 market)
        return self.get(f"/sports/{sport}/odds", regions="us", markets="h2h", oddsFormat="decimal")


def kalshi_events(series: str, http=None) -> list[dict]:
    """Open Kalshi game events in one series (public, no keys). Any trouble = no Kalshi prices this scan."""
    http = http or requests
    try:
        r = http.get(f"{KALSHI}/events", params={"series_ticker": series, "status": "open",
                                                 "with_nested_markets": "true", "limit": 200}, timeout=20)
        r.raise_for_status()
        return r.json().get("events", [])
    except Exception as e:
        log.warning("Kalshi %s: %s", series, e)
        return []


def kalshi_result(ticker: str, http=None) -> str | None:
    http = http or requests
    try:
        r = http.get(f"{KALSHI}/markets/{ticker}", timeout=20)
        r.raise_for_status()
        return r.json().get("market", {}).get("result") or None
    except Exception as e:
        log.warning("Kalshi %s: %s", ticker, e)
        return None


def espn_scoreboard(sport: str, day: str, http=None) -> dict:
    http = http or requests
    _, path, extra = SPORTS.get(sport, (None, None, {}))
    if not path:
        return {}
    try:
        r = http.get(f"{ESPN}/{path}/scoreboard", params={"dates": day, "limit": 400, **extra}, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("ESPN %s %s: %s", sport, day, e)
        return {}


# ---------- credits ----------

def daily_allowance(remaining: int | None, now: datetime, monthly: int) -> int:
    """Credits this scan's day may spend: what's left spread over the days left in the month."""
    nxt = (now.replace(day=28) + timedelta(days=4)).replace(day=1)
    days_left = (nxt.date() - now.date()).days
    even = max(1, monthly // 30)
    if remaining is None:
        return even
    return min(max(0, remaining // max(days_left, 1)), 2 * even)  # the free plan may reset mid-month


# ---------- state and the pretend record ----------

def load_state() -> dict:
    s = json.loads(STATE.read_text()) if STATE.exists() else {}
    s.setdefault("open", [])
    s.setdefault("seen", {})
    s.setdefault("credits", {})
    return s


def save_state(s: dict) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    s["seen"] = {k: v for k, v in s["seen"].items() if v >= cutoff}
    STATE.write_text(json.dumps(s, indent=1))


def find_key(f: dict) -> str:
    if f["kind"] == "arb":
        return "arb|" + f["game_id"] + "|" + "|".join(sorted(f"{l['team']}@{l['book']}" for l in f["legs"]))
    return f"{f['kind']}|{f['game_id']}|{f['team']}|{f['book']}"


def open_bets(finds: list[dict], state: dict, stake: float, now: datetime) -> list[dict]:
    """New finds become pretend bets (each game/side/book only once)."""
    new = []
    for f in finds:
        k = find_key(f)
        if k in state["seen"]:
            continue
        state["seen"][k] = now.isoformat()
        legs = f["legs"] if f["kind"] == "arb" else [{"team": f["team"], "book": f["book"], "odds": f["odds"], "stake": stake,
                                                       **({"ticker": f["ticker"]} if f.get("ticker") else {})}]
        bet = {**{x: f[x] for x in ("kind", "game", "game_id", "sport", "start", "edge")},
               "home": f["game"].split(" at ")[1], "away": f["game"].split(" at ")[0], "legs": legs,
               "opened": now.isoformat(timespec="seconds")}
        state["open"].append(bet)
        new.append(bet)
    return new


def leg_profit(leg: dict, winner: str) -> float:
    if winner == "void":
        return 0.0
    return round(leg["stake"] * (leg["odds"] - 1), 2) if leg["team"] == winner else -leg["stake"]


def settle(state: dict, now: datetime, scoreboard=espn_scoreboard, kresult=kalshi_result) -> list[dict]:
    """Settle pretend bets on games that finished. Kalshi legs settle on Kalshi's own result."""
    done, keep, boards = [], [], {}
    for bet in state["open"]:
        start = datetime.fromisoformat(bet["start"].replace("Z", "+00:00"))
        if now < start + timedelta(hours=2.5):
            keep.append(bet)
            continue
        game = {"home_team": bet["home"], "away_team": bet["away"]}
        winner = None
        for day in {start.astimezone(ET).strftime("%Y%m%d"), start.strftime("%Y%m%d")}:
            key = (bet["sport"], day)
            if key not in boards:
                boards[key] = scoreboard(bet["sport"], day)
            winner = winner or espn_winner(game, boards[key])
        pnl, missing = 0.0, False
        for leg in bet["legs"]:
            if leg["book"] == "Kalshi" and leg.get("ticker"):
                res = kresult(leg["ticker"])
                if res in ("yes", "no"):
                    contracts = leg["stake"] / (1 / leg["odds"])
                    pnl += round(contracts - leg["stake"], 2) if res == "yes" else -leg["stake"]
                    continue
            if winner is None:
                missing = True
                break
            pnl += leg_profit(leg, winner)
        if missing:
            if now - start > timedelta(days=4):  # never found: count it as void, not a win or loss
                done.append({**bet, "winner": "unknown", "pnl": 0.0, "settled": now.isoformat(timespec="seconds")})
            else:
                keep.append(bet)
            continue
        done.append({**bet, "winner": winner or "kalshi", "pnl": round(pnl, 2), "settled": now.isoformat(timespec="seconds")})
    state["open"] = keep
    if done:
        write_ledger(done)
    return done


LEDGER_COLS = ["settled", "kind", "sport", "game", "start", "picks", "staked", "edge", "winner", "pnl"]


def write_ledger(done: list[dict]) -> None:
    DATA.mkdir(exist_ok=True)
    path = DATA / "paper_bets.csv"
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LEDGER_COLS)
        for b in done:
            picks = "; ".join(f"{l['team']} @ {l['book']} {l['odds']}" for l in b["legs"])
            w.writerow([b["settled"], b["kind"], b["sport"], b["game"], b["start"], picks,
                        round(sum(l["stake"] for l in b["legs"]), 2), b["edge"], b["winner"], b["pnl"]])


def record() -> dict:
    path = DATA / "paper_bets.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8"))) if path.exists() else []
    out = {}
    for kind in ("value", "kalshi", "arb", "all"):
        rs = [r for r in rows if kind == "all" or r["kind"] == kind]
        staked = sum(float(r["staked"]) for r in rs)
        pnl = sum(float(r["pnl"]) for r in rs)
        out[kind] = {"bets": len(rs), "wins": sum(float(r["pnl"]) > 0 for r in rs), "staked": round(staked, 2),
                     "pnl": round(pnl, 2), "roi": round(pnl / staked, 4) if staked else 0.0}
    return out


def append_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    DATA.mkdir(exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


FIND_COLS = ["time", "kind", "sport", "game", "start", "team", "book", "odds", "fair", "edge", "picks"]


def describe(f: dict) -> str:
    when = datetime.fromisoformat(f["start"].replace("Z", "+00:00")).astimezone(ET).strftime("%a %-I:%M%p")
    if f["kind"] == "arb":
        legs = ", ".join(f"${l['stake']:.0f} {l['team']} @ {l['book']} {l['odds']}" for l in f["legs"])
        return f"ARB {f['edge']:.1%} locked: {f['game']} ({when}): {legs}"
    return (f"{f['team']} @ {f['book']} {f['odds']} (fair {1 / f['fair']:.2f}, +{f['edge']:.1%} expected) "
            f"{f['game']} ({when})")


# ---------- one scan ----------

def scan(api: OddsAPI, cfg: dict, state: dict, now: datetime, kalshi=kalshi_events) -> tuple[list[dict], dict]:
    """Price the sports with games soon, within today's credit allowance. Returns (finds, scan stats)."""
    credits = state["credits"]
    today = now.astimezone(ET).date().isoformat()
    if credits.get("day") != today:
        credits.update(day=today, spent=0)
    allowance = daily_allowance(credits.get("remaining"), now.astimezone(ET), cfg["monthly"])
    soon = now + timedelta(hours=cfg["hours"])
    finds, stats = [], {"sports": [], "games": 0, "kalshi_matched": 0, "skipped": []}
    for sport in cfg["sports"]:
        try:
            upcoming = [e for e in api.events(sport)
                        if now < datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")) < soon]
        except requests.HTTPError as e:
            log.warning("%s events: %s", sport, e)
            continue
        if not upcoming:
            continue
        if credits["spent"] >= allowance:
            stats["skipped"].append(sport)
            continue
        before = api.spent
        games = api.odds(sport)
        credits["spent"] += max(api.spent - before, 1)
        credits["remaining"] = api.remaining
        series = SPORTS.get(sport, (None,))[0]
        k_events = kalshi(series) if series else []
        stats["sports"].append(sport)
        for g in games:
            start = datetime.fromisoformat(g["commence_time"].replace("Z", "+00:00"))
            if not now < start < soon:
                continue  # started already (live odds move too fast) or too far out
            stats["games"] += 1
            books = book_prices(g)
            k = kalshi_for_game(g, k_events) if k_events else {}
            stats["kalshi_matched"] += bool(k)
            finds += value_bets(g, books, cfg) + kalshi_value(g, books, k, cfg)
            arb = arbitrage(g, books, k)
            if arb:
                finds.append(arb)
        time.sleep(0.2)
    stats.update(credits_left=credits.get("remaining"), spent_today=credits["spent"], allowance=allowance)
    return finds, stats


def alert(cfg: dict, new: list[dict]) -> None:
    """New finds go to the fleet alert log (the PC popup picks up arbs) and the phone if NTFY_TOPIC is set."""
    if not new:
        return
    lines = [describe(f) for f in sorted(new, key=lambda f: (f["kind"] != "arb", -f["edge"]))[:6]]
    title = f"Odds finder: {len(new)} new find{'s' * (len(new) > 1)} (pretend bets)"
    text = "\n".join(lines)
    try:
        from .alerts import notify

        notify("odds finder", title, text, level="watch" if any(f["kind"] == "arb" for f in new) else "info")
    except Exception as e:
        log.warning("alert log: %s", e)
    if cfg["ntfy"]:
        from types import SimpleNamespace

        from .notify import send

        send(SimpleNamespace(ntfy_topic=cfg["ntfy"]), title, text[:900])


def write_summary(stats: dict, new: list[dict], state: dict, now: datetime) -> dict:
    s = {"updated": now.isoformat(timespec="seconds"), "scan": stats, "new_finds": [describe(f) for f in new],
         "open_bets": len(state["open"]), "record": record()}
    DATA.mkdir(exist_ok=True)
    (DATA / "summary.json").write_text(json.dumps(s, indent=1))
    return s


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Sports odds finder (alerts + pretend bets only)")
    ap.add_argument("--settle", action="store_true", help="only settle open pretend bets")
    ap.add_argument("--report", action="store_true", help="print the record")
    args = ap.parse_args()
    if args.report:
        print(json.dumps(record(), indent=1))
        return
    cfg, state, now = settings(), load_state(), datetime.now(timezone.utc)
    done = settle(state, now)
    if done:
        log.info("Settled %d pretend bets: %+.2f", len(done), sum(b["pnl"] for b in done))
    stats, new = {"note": "settle only"}, []
    if not args.settle:
        if not cfg["key"]:
            stats = {"note": "No ODDS_API_KEY secret yet, so no odds were checked (settling still runs)."}
            log.warning(stats["note"])
        else:
            finds, stats = scan(OddsAPI(cfg["key"]), cfg, state, now)
            new = open_bets(finds, state, cfg["stake"], now)
            append_csv(DATA / "finds.csv", FIND_COLS, [
                {**f, "time": now.isoformat(timespec="seconds"),
                 "picks": "; ".join(f"{l['team']} @ {l['book']} {l['odds']} ${l['stake']}" for l in f.get("legs", []))}
                for f in new])
            alert(cfg, new)
            log.info("Scanned %s: %d games, %d with Kalshi, %d new finds. Credits left %s (today %s of %s).",
                     ", ".join(stats["sports"]) or "nothing", stats["games"], stats["kalshi_matched"], len(new),
                     stats["credits_left"], stats["spent_today"], stats["allowance"])
            for f in new:
                log.info("  %s", describe(f))
    save_state(state)
    write_summary(stats, new, state, now)


if __name__ == "__main__":
    main()
