"""Gameday parlay helper: advice and pretend money only. It never places a bet.

After each odds scan it builds, for every game starting in the next day, a ready 2-4 leg parlay from
Kalshi markets: the favorite to win plus the player props the props checker priced (including the
"books say 66.5, Kalshi has 60+" step rule). Legs are the likelier side of each market, best value
first (the sportsbooks' fair chance minus Kalshi's price and fee), and a leg Kalshi overprices by more
than PARLAY_MAX_OVERPAY is left out. It also builds one "favorites" parlay across different games.

Each parlay shows what it costs if you buy every leg on Kalshi, what it pays, and the fair chance all
legs hit. Same-game legs move together, so that chance is a rough guide, not a promise. Every
suggested parlay is also tracked as a pretend $1 bet and settled from Kalshi's results, so the record
shows whether following these would really have paid.

No Odds API credits: it reuses odds_data/kalshi_fair.json and props_data/compare_v2.csv plus Kalshi's
public prices.

    python -m bot.parlay_helper            # build today's parlays + settle the pretend record
    python -m bot.parlay_helper --report   # print the record
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .kalshi import D, fee
from .odds_finder import ET, kalshi_events, kalshi_result

log = logging.getLogger("parlay")
DATA = Path("parlay_data")
STATE = Path("parlay_state.json")
FAIR = Path("odds_data/kalshi_fair.json")
PROPS = Path("props_data/compare_v2.csv")
STATS = {"player_points": "points", "player_rebounds": "rebounds", "player_assists": "assists",
         "player_reception_yds": "receiving yards", "player_rush_yds": "rushing yards", "player_pass_yds": "passing yards"}
REC_COLS = ["opened", "closed", "kind", "game", "legs", "price", "fair", "result", "pnl"]


def settings() -> dict:
    return {
        "hours": float(os.getenv("PARLAY_HOURS", "24")),  # games starting this soon
        "max_overpay": float(os.getenv("PARLAY_MAX_OVERPAY", "0.03")),  # skip a leg Kalshi overprices by more
        "max_props": int(os.getenv("PARLAY_MAX_PROPS", "3")),
        "min_fav": float(os.getenv("PARLAY_MIN_FAVORITE", "0.60")),  # favorites parlay: only clear favorites
        "prop_age": float(os.getenv("PARLAY_PROP_HOURS", "18")),  # ignore prop prices older than this
    }


def cost(price: float) -> float:
    p = D(str(price))
    return float(p + fee(10, p) / 10)


def american(price: float) -> str:
    """What a parlay bought at `price` per $1 pays, in sportsbook style (+550)."""
    if not 0 < price < 1:
        return "n/a"
    return f"+{round(100 * (1 - price) / price)}" if price <= 0.5 else f"-{round(100 * price / (1 - price))}"


def leg(label: str, ticker: str, side: str, price: float, fair: float, player: str = "") -> dict:
    return {"label": label, "ticker": ticker, "side": side, "price": round(price, 4), "fair": round(fair, 4),
            "value": round(fair - cost(price), 4), "player": player}


def parlay(kind: str, game: str, start: str, legs: list[dict]) -> dict:
    price = fair = 1.0
    for l in legs:
        price, fair = price * cost(l["price"]), fair * l["fair"]
    return {"kind": kind, "game": game, "start": start, "legs": legs, "price": round(price, 4), "fair": round(fair, 4),
            "pays": american(price), "per_dollar": round(1 / price, 2) if price else 0}


# ---------- the legs ----------

def winner_legs(fair: dict, now: datetime, cfg: dict, kalshi=kalshi_events) -> dict[str, dict]:
    """{game name: {"start", "teams", "leg"}} for games starting soon: the favorite to win, at Kalshi's ask."""
    games, asks = {}, {}
    for ticker, v in fair.get("prices", {}).items():
        start = datetime.fromisoformat(v["start"].replace("Z", "+00:00"))
        if not timedelta(0) < start - now <= timedelta(hours=cfg["hours"]) or v.get("news"):
            continue
        series = ticker.split("-")[0]
        if series not in asks:
            asks[series] = {m["ticker"]: float(m.get("yes_ask_dollars") or 0) for e in kalshi(series) for m in e.get("markets", [])}
        name = " vs ".join(sorted(v["teams"]))
        g = games.setdefault(name, {"start": v["start"], "teams": v["teams"], "leg": None})
        ask = asks[series].get(ticker, 0)
        if v["fair_yes"] >= 0.5 and 0 < ask < 1 and (g["leg"] is None or v["fair_yes"] > g["leg"]["fair"]):
            g["leg"] = leg(f"{v['team']} to win", ticker, "yes", ask, v["fair_yes"])
    return games


def prop_legs(rows: list[dict], teams: list[str], now: datetime, cfg: dict) -> list[dict]:
    """The likelier side of each player prop the props checker priced for this game (latest price per market)."""
    latest = {}
    for r in rows:
        if all(t in r["game"] for t in teams) and now - datetime.fromisoformat(r["time"]) <= timedelta(hours=cfg["prop_age"]):
            latest[r["ticker"]] = r
    out = []
    for r in latest.values():
        fair, stat, n = float(r["fair_yes"]), STATS.get(r["stat"], r["stat"]), float(r["line"])
        over = f"{n + 0.5:g}+" if (n + 0.5).is_integer() else f"over {n:g}"
        under = f"under {n + 0.5:g}" if (n + 0.5).is_integer() else f"under {n:g}"
        if fair >= 0.5:
            out.append(leg(f"{r['player']} {over} {stat}", r["ticker"], "yes", float(r["yes_ask"]), fair, r["player"]))
        else:
            out.append(leg(f"{r['player']} {under} {stat}", r["ticker"], "no", float(r["no_ask"]), 1 - fair, r["player"]))
    return out


def build(fair: dict, rows: list[dict], now: datetime, cfg: dict, kalshi=kalshi_events) -> list[dict]:
    games, out = winner_legs(fair, now, cfg, kalshi), []
    for name, g in sorted(games.items(), key=lambda kv: kv[1]["start"]):
        ok = [l for l in prop_legs(rows, g["teams"], now, cfg) if l["value"] >= -cfg["max_overpay"]]
        props, players = [], set()
        for l in sorted(ok, key=lambda l: -l["value"]):
            if l["player"] not in players:
                players.add(l["player"])
                props.append(l)
        legs = ([g["leg"]] if g["leg"] and g["leg"]["value"] >= -cfg["max_overpay"] else []) + props[:cfg["max_props"]]
        if len(legs) >= 2:
            out.append(parlay("game", name, g["start"], legs))
            safer = sorted(legs, key=lambda l: -l["fair"])[:2]
            if len(legs) > 2:
                out.append(parlay("game (safer 2-leg)", name, g["start"], safer))
    favs = sorted((g["leg"] for g in games.values() if g["leg"] and g["leg"]["fair"] >= cfg["min_fav"]
                   and g["leg"]["value"] >= -cfg["max_overpay"]), key=lambda l: -l["value"])[:3]
    if len(favs) >= 2:
        last = max(g["start"] for g in games.values() if g["leg"] in favs)
        out.append(parlay("favorites", "Favorites across games", last, favs))
    return out


# ---------- the pretend record ----------

def load_state() -> dict:
    s = json.loads(STATE.read_text()) if STATE.exists() else {}
    s.setdefault("open", [])
    s.setdefault("seen", {})
    return s


def track(parlays: list[dict], state: dict, now: datetime) -> int:
    """Each game's main parlay and each day's favorites parlay becomes one pretend $1 bet, once."""
    n = 0
    for p in parlays:
        if "safer" in p["kind"]:
            continue
        key = f"{p['kind']}|{p['game']}|{p['start'][:10] if p['kind'] == 'game' else now.astimezone(ET).date()}"
        if key not in state["seen"]:
            state["seen"][key] = now.isoformat()
            state["open"].append({**p, "opened": now.isoformat(timespec="seconds")})
            n += 1
    return n


def settle(state: dict, now: datetime, kresult=kalshi_result) -> list[dict]:
    done, still = [], []
    for p in state["open"]:
        results = [kresult(l["ticker"]) or "" for l in p["legs"]]
        lost = any(r in ("yes", "no") and r != l["side"] for r, l in zip(results, p["legs"]))
        won = all(r == l["side"] for r, l in zip(results, p["legs"]))
        if lost or won:
            pnl = round(1 / p["price"] - 1, 2) if won else -1.0  # $1 staked at the parlay's price (fees included)
            done.append({**p, "closed": now.isoformat(timespec="seconds"), "result": "won" if won else "lost", "pnl": pnl,
                         "legs": "; ".join(l["label"] for l in p["legs"])})
        else:
            still.append(p)
    state["open"] = still
    if done:
        DATA.mkdir(parents=True, exist_ok=True)
        path = DATA / "record.csv"
        new = not path.exists()
        with path.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=REC_COLS, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerows(done)
    return done


def record() -> dict:
    path = DATA / "record.csv"
    rows = list(csv.DictReader(path.open())) if path.exists() else []
    return {"parlays": len(rows), "won": sum(r["result"] == "won" for r in rows), "profit": round(sum(float(r["pnl"]) for r in rows), 2)}


# ---------- output ----------

def text(parlays: list[dict], now: datetime, rec: dict) -> str:
    lines = [f"# Gameday parlays ({now.astimezone(ET):%a %b %-d, %-I:%M %p} ET)", "",
             "Advice and pretend money only. Prices are Kalshi's, with its fee. The fair chance multiplies the legs' "
             "chances, so same-game legs (which move together) make it a rough guide.", ""]
    if not parlays:
        lines.append("No parlay right now: no game in the next day has two fairly priced legs.")
    for p in parlays:
        when = datetime.fromisoformat(p["start"].replace("Z", "+00:00")).astimezone(ET)
        lines += [f"## {p['game']} ({p['kind']}, {when:%a %-I:%M %p} ET)",
                  f"Pays {p['pays']} (${p['per_dollar']:.2f} back per $1). Fair chance all legs hit: {p['fair']:.0%}.", ""]
        lines += [f"- {l['label']}: Kalshi {l['price'] * 100:.0f}c {l['side'].upper()}, fair {l['fair']:.0%}" for l in p["legs"]]
        lines.append("")
    lines.append(f"Pretend record so far: {rec['parlays']} settled, {rec['won']} won, profit ${rec['profit']:.2f} on $1 each.")
    return "\n".join(lines) + "\n"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    if ap.parse_args().report:
        return print(json.dumps(record(), indent=1))
    cfg, now, state = settings(), datetime.now(timezone.utc), load_state()
    done = settle(state, now)
    fair = json.loads(FAIR.read_text()) if FAIR.exists() else {}
    rows = list(csv.DictReader(PROPS.open())) if PROPS.exists() else []
    parlays = build(fair, rows, now, cfg)
    new = track(parlays, state, now)
    cutoff = (now - timedelta(days=10)).isoformat()
    state["seen"] = {k: v for k, v in state["seen"].items() if v >= cutoff}
    STATE.write_text(json.dumps(state, indent=1))
    DATA.mkdir(parents=True, exist_ok=True)
    rec = record()
    (DATA / "today.json").write_text(json.dumps({"updated": now.isoformat(timespec="seconds"), "parlays": parlays,
                                                 "open_pretend": len(state["open"]), "record": rec}, indent=1))
    (DATA / "today.md").write_text(text(parlays, now, rec))
    log.info("Parlays: %d built, %d new pretend bets, %d settled; record %s", len(parlays), new, len(done), rec)


if __name__ == "__main__":
    main()
