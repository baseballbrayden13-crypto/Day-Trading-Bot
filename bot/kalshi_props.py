"""Kalshi player props (points, yards, ...) checked against sportsbook prop odds. Pretend money only.

Free past prop odds don't exist, so this can't be backtested. Instead it is a forward test: each scan
it takes Kalshi's player-prop markets ("Herbert Jones: 10+ points"), finds the same player and line at
the sportsbooks (The Odds API), takes the books' margin out to get a fair chance, and when Kalshi's
price is better than fair by KALSHI_PROPS_MIN_EDGE after Kalshi's fee it records a pretend bet. Bets
settle from Kalshi's own result. Every comparison is also logged, so a week of data shows whether the
sportsbooks really know better than Kalshi's prop prices. It never places an order and is not part of
bots 4e/4f.

Prop odds cost 1 Odds API credit per stat per game (same key as the odds finder, 500 a month), so
spending is capped at KALSHI_PROPS_CREDITS a day and each game is priced once, shortly before it starts.

    python -m bot.kalshi_props --scan       # price props + settle (needs ODDS_API_KEY)
    python -m bot.kalshi_props --settle     # only settle (no credits)
    python -m bot.kalshi_props --report     # print the record
    python -m bot.kalshi_props --discover   # list Kalshi's player-prop series (public data)
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

import requests

from .kalshi import D, fee
from .odds_finder import BOOKS, ET, KALSHI, OddsAPI, _words, kalshi_events, kalshi_result, name_fits, quiet, TICKER_DATE, MONTHS

log = logging.getLogger("props")
DATA = Path("props_data")
STATE = Path("kalshi_props_state.json")
# Odds API sport -> [(Kalshi series, Odds API prop market)]. A series with no open Kalshi event costs nothing.
PROPS = {
    "basketball_nba": [("KXNBAPTS", "player_points"), ("KXNBAREB", "player_rebounds"), ("KXNBAAST", "player_assists")],
    "icehockey_nhl": [("KXNHLPTS", "player_points")],
    "americanfootball_nfl": [("KXNFLRECYDS", "player_reception_yds"), ("KXNFLRSHYDS", "player_rush_yds"),
                             ("KXNFLPASSYDS", "player_pass_yds")],
}
COMPARE_COLS = ["time", "sport", "game", "stat", "player", "line", "books", "fair_yes", "yes_ask", "no_ask", "ticker"]
BET_COLS = ["opened", "closed", "sport", "game", "stat", "player", "line", "side", "price", "contracts", "fair",
            "edge", "result", "pnl", "ticker"]
PROP_WORDS = re.compile(r"\b(points?|rebounds?|assists?|yards?|touchdowns?|td|strikeouts?|hits|home runs?|"
                        r"threes?|3-pointers?|receptions?|passing|rushing|receiving|shots|saves|goal ?scorer|"
                        r"anytime|player|pts|reb|ast|sog)\b", re.I)


def settings() -> dict:
    return {
        "key": os.getenv("ODDS_API_KEY", "").strip(),
        "on": os.getenv("KALSHI_PROPS", "off").strip().lower() == "on",
        "sports": [s.strip() for s in os.getenv("KALSHI_PROPS_SPORTS", ",".join(PROPS)).split(",") if s.strip()],
        "credits": int(os.getenv("KALSHI_PROPS_CREDITS", "6")),  # a day, out of the odds finder's 500 a month
        "min_edge": float(os.getenv("KALSHI_PROPS_MIN_EDGE", "0.05")),  # dollars per $1 contract, after the fee
        "min_books": int(os.getenv("KALSHI_PROPS_MIN_BOOKS", "3")),
        "min_price": float(os.getenv("KALSHI_PROPS_MIN_PRICE", "0.15")),  # no long shots or near-certainties:
        "max_price": float(os.getenv("KALSHI_PROPS_MAX_PRICE", "0.85")),  # the fair price is too noisy there
        "hours": float(os.getenv("KALSHI_PROPS_HOURS", "6")),  # price a game this close to its start (lines are set)
        "stake": float(os.getenv("KALSHI_PROPS_STAKE", "2")),
        "quiet": os.getenv("ODDS_QUIET", "1-8"),
    }


# ---------- the math ----------

def player_key(name: str) -> str:
    """'P.J. Washington Jr.' and 'PJ Washington' are the same player."""
    words = [w for w in _words(name.replace(".", "")) if w not in ("jr", "sr", "ii", "iii", "iv")]
    return " ".join(words)


def fair_lines(bookmakers: list[dict], market: str) -> dict[tuple[str, float], dict]:
    """{(player, line): {"fair": chance of going over, "books": n}} with each book's margin taken out.
    Only books that price both Over and Under on that exact line count."""
    sides: dict[tuple[str, float], dict[str, dict[str, float]]] = {}
    for b in bookmakers:
        for m in b.get("markets", []):
            if m.get("key") != market:
                continue
            for o in m.get("outcomes", []):
                if o.get("point") is None or not o.get("description") or float(o.get("price") or 0) <= 1:
                    continue
                k = (player_key(o["description"]), float(o["point"]))
                sides.setdefault(k, {}).setdefault(b["title"], {})[str(o["name"]).lower()] = float(o["price"])
    out = {}
    for k, books in sides.items():
        probs = [(1 / p["over"]) / (1 / p["over"] + 1 / p["under"]) for p in books.values() if "over" in p and "under" in p]
        if probs:
            out[k] = {"fair": median(probs), "books": len(probs)}
    return out


def cost(price: float) -> float:
    """Dollars per $1 contract: the ask plus Kalshi's taker fee (on a 10-contract buy)."""
    p = D(str(price))
    return float(p + fee(10, p) / 10)


def pick(fair_yes: float, yes_ask: float, no_ask: float, cfg: dict) -> dict | None:
    """The side (if any) whose fair chance beats its price plus fee by the minimum edge."""
    best = None
    for side, fair, ask in (("yes", fair_yes, yes_ask), ("no", 1 - fair_yes, no_ask)):
        if not cfg["min_price"] <= ask <= cfg["max_price"]:
            continue
        edge = fair - cost(ask)
        if edge >= cfg["min_edge"] and (best is None or edge > best["edge"]):
            best = {"side": side, "price": ask, "fair": round(fair, 4), "edge": round(edge, 4)}
    return best


def bet_pnl(bet: dict, result: str) -> float:
    n, price = int(bet["contracts"]), D(str(bet["price"]))
    if result not in ("yes", "no"):  # voided: money back
        return 0.0
    paid = n * price + fee(n, price)
    return float((n if result == bet["side"] else 0) - paid)


# ---------- matching Kalshi to the books ----------

def event_for_game(game: dict, events: list[dict]) -> dict | None:
    """The Kalshi prop event for this game: 'Washington vs New York G: Rushing Yards', same day."""
    start = datetime.fromisoformat(game["commence_time"].replace("Z", "+00:00")).astimezone(ET).date()
    teams = [game["home_team"], game["away_team"]]
    for e in events:
        m = TICKER_DATE.search(e.get("event_ticker", ""))
        if not m or m.group(2) not in MONTHS:
            continue
        if abs((datetime(2000 + int(m.group(1)), MONTHS[m.group(2)], int(m.group(3))).date() - start).days) > 1:
            continue
        names = re.split(r"\s+(?:vs\.?|at|@)\s+", (e.get("title") or "").split(":")[0])
        if len(names) == 2 and sorted(t for n in names for t in teams if name_fits(n, t)) == sorted(teams):
            return e
    return None


def compare(event: dict, lines: dict, cfg: dict) -> list[dict]:
    """Kalshi markets in one prop event that the books price on the same player and line."""
    out = []
    for mk in event.get("markets", []):
        label = mk.get("yes_sub_title") or mk.get("title") or ""
        strike = mk.get("floor_strike")
        if ":" not in label or strike is None or mk.get("strike_type") not in (None, "greater"):
            continue
        line = lines.get((player_key(label.split(":")[0]), float(strike)))
        yes_ask, no_ask = float(mk.get("yes_ask_dollars") or 0), float(mk.get("no_ask_dollars") or 0)
        if not line or line["books"] < cfg["min_books"] or not (0 < yes_ask < 1 and 0 < no_ask < 1):
            continue
        out.append({"player": label.split(":")[0].strip(), "line": float(strike), "books": line["books"],
                    "fair_yes": round(line["fair"], 4), "yes_ask": yes_ask, "no_ask": no_ask, "ticker": mk["ticker"]})
    return out


# ---------- state ----------

def load_state() -> dict:
    s = json.loads(STATE.read_text()) if STATE.exists() else {}
    for k, v in (("open", []), ("priced", {}), ("bet", {}), ("credits", {})):
        s.setdefault(k, v)
    return s


def save_state(s: dict) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    s["priced"] = {k: v for k, v in s["priced"].items() if v >= cutoff}
    s["bet"] = {k: v for k, v in s["bet"].items() if v >= cutoff}
    s["credits"] = dict(sorted(s["credits"].items())[-10:])
    STATE.write_text(json.dumps(s, indent=1))


def append_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def record() -> dict:
    path = DATA / "bets.csv"
    rows = list(csv.DictReader(path.open())) if path.exists() else []
    pnl = [float(r["pnl"]) for r in rows]
    staked = sum(float(r["price"]) * int(r["contracts"]) for r in rows)
    return {"bets": len(rows), "won": sum(p > 0 for p in pnl), "profit": round(sum(pnl), 2), "staked": round(staked, 2)}


# ---------- scan and settle ----------

def scan(api: OddsAPI, cfg: dict, state: dict, now: datetime, kalshi=kalshi_events) -> dict:
    day = now.astimezone(ET).date().isoformat()
    spent = int(state["credits"].get(day, 0))
    stats = {"games": 0, "compared": 0, "bets": 0, "spent_today": spent, "cap": cfg["credits"]}
    if quiet(now, cfg["quiet"]):
        return {**stats, "note": "quiet hours"}
    rows, bets = [], []
    for sport in cfg["sports"]:
        series = {s: (m, kalshi(s)) for s, m in PROPS.get(sport, [])}
        series = {s: v for s, v in series.items() if v[1]}
        if not series or spent >= cfg["credits"]:
            continue
        try:
            games = api.events(sport)
        except Exception as e:  # noqa: BLE001
            log.warning("%s games: %s", sport, e)
            continue
        soon = sorted((g for g in games if g["id"] not in state["priced"] and timedelta(0) < datetime.fromisoformat(
            g["commence_time"].replace("Z", "+00:00")) - now <= timedelta(hours=cfg["hours"])), key=lambda g: g["commence_time"])
        for g in soon:
            found = {m: e for s, (m, evs) in series.items() if (e := event_for_game(g, evs))}
            found = dict(list(found.items())[:max(0, cfg["credits"] - spent)])
            if not found:
                continue
            before = api.spent
            try:
                odds = api.get(f"/sports/{sport}/events/{g['id']}/odds", bookmakers=BOOKS, markets=",".join(found),
                               oddsFormat="decimal")
            except Exception as e:  # noqa: BLE001
                log.warning("%s props: %s", g["id"], e)
                continue
            spent += (api.spent - before) or len(found)
            state["priced"][g["id"]] = now.isoformat()
            stats["games"] += 1
            name = f"{g['away_team']} at {g['home_team']}"
            for market, event in found.items():
                for c in compare(event, fair_lines(odds.get("bookmakers", []), market), cfg):
                    base = {"time": now.isoformat(timespec="seconds"), "sport": sport, "game": name, "stat": market, **c}
                    rows.append(base)
                    p = pick(c["fair_yes"], c["yes_ask"], c["no_ask"], cfg)
                    if p and c["ticker"] not in state["bet"]:
                        n = max(1, int(cfg["stake"] // p["price"]))
                        bets.append({**base, **p, "contracts": n, "opened": base["time"]})
                        state["bet"][c["ticker"]] = now.isoformat()
            if spent >= cfg["credits"]:
                break
    state["credits"][day] = spent
    state["open"] += bets
    append_csv(DATA / "compare.csv", COMPARE_COLS, rows)
    stats.update(compared=len(rows), bets=len(bets), spent_today=spent, credits_left=api.remaining)
    return stats


def settle(state: dict, now: datetime, kresult=kalshi_result) -> list[dict]:
    done, still = [], []
    for b in state["open"]:
        res = kresult(b["ticker"])
        if res:
            done.append({**b, "closed": now.isoformat(timespec="seconds"), "result": res, "pnl": round(bet_pnl(b, res), 2)})
        else:
            still.append(b)
    state["open"] = still
    append_csv(DATA / "bets.csv", BET_COLS, done)
    return done


def write_summary(stats: dict, state: dict, now: datetime) -> dict:
    s = {"updated": now.isoformat(timespec="seconds"), "mode": "pretend money, forward test (not part of 4e/4f)",
         "scan": stats, "open_bets": len(state["open"]), "record": record()}
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "summary.json").write_text(json.dumps(s, indent=1))
    return s


# ---------- discovery (which prop series Kalshi has) ----------

def discover() -> None:
    series, cursor = [], None
    for _ in range(50):
        r = requests.get(f"{KALSHI}/series", params={"category": "Sports", "limit": 1000, **({"cursor": cursor} if cursor else {})}, timeout=30)
        r.raise_for_status()
        series += r.json().get("series") or []
        cursor = r.json().get("cursor")
        if not cursor:
            break
    for s in series:
        if PROP_WORDS.search(f"{s.get('title', '')} {s.get('ticker', '')}"):
            evs = kalshi_events(s["ticker"])
            if evs:
                first = (evs[0].get("markets") or [{}])[0]
                print(f"{s['ticker']:<26} {s.get('title', '')[:40]!r} events {len(evs)} e.g. {evs[0].get('title')!r} / {first.get('title')!r}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    for flag in ("--scan", "--settle", "--report", "--discover"):
        ap.add_argument(flag, action="store_true")
    a = ap.parse_args()
    if a.discover:
        return discover()
    if a.report:
        return print(json.dumps(record(), indent=1))
    cfg, now, state = settings(), datetime.now(timezone.utc), load_state()
    done = settle(state, now)
    stats: dict = {"note": "settle only"}
    if a.scan:
        if not cfg["on"]:
            stats = {"note": "KALSHI_PROPS is off"}
        elif not cfg["key"]:
            stats = {"note": "No ODDS_API_KEY secret, so no prop odds were checked."}
        else:
            stats = scan(OddsAPI(cfg["key"]), cfg, state, now)
    save_state(state)
    s = write_summary(stats, state, now)
    log.info("Props: %s; settled %d; record %s", stats, len(done), s["record"])


if __name__ == "__main__":
    main()
