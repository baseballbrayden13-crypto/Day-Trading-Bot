"""Kalshi player props (points, yards, ...) checked against sportsbook prop odds. Pretend money only.

Step 1 (this file for now): find which player-prop markets Kalshi lists and what they look like, so the
checker can match them to The Odds API's player-prop lines. Public Kalshi data only, no keys, no orders.

    python -m bot.kalshi_props --discover
"""
from __future__ import annotations

import argparse
import json
import re

import requests

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
PROP_WORDS = re.compile(r"\b(points?|rebounds?|assists?|yards?|touchdowns?|td|strikeouts?|hits|home runs?|"
                        r"threes?|3-pointers?|receptions?|passing|rushing|receiving|shots|saves|goal ?scorer|"
                        r"anytime|player|pts|reb|ast|sog)\b", re.I)


def get(path: str, **params) -> dict:
    r = requests.get(f"{KALSHI}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def sports_series() -> list[dict]:
    out, cursor = [], None
    for _ in range(50):
        d = get("/series", category="Sports", limit=1000, **({"cursor": cursor} if cursor else {}))
        out += d.get("series") or []
        cursor = d.get("cursor")
        if not cursor:
            break
    return out


def discover(per_series: int = 2) -> None:
    series = sports_series()
    print(f"{len(series)} sports series on Kalshi")
    props = [s for s in series if PROP_WORDS.search(f"{s.get('title', '')} {s.get('ticker', '')}")]
    print(f"{len(props)} look like player props:")
    shown = 0
    for s in props:
        try:
            evs = get("/events", series_ticker=s["ticker"], status="open", with_nested_markets="true", limit=50).get("events", [])
        except Exception as e:  # noqa: BLE001
            print(f"  {s['ticker']}: {e}")
            continue
        n = sum(len(e.get("markets") or []) for e in evs)
        print(f"  {s['ticker']:<28} {s.get('title', '')[:60]!r} open events {len(evs)}, markets {n}")
        if evs and shown < 25:
            shown += 1
            for e in evs[:per_series]:
                print(f"    event {e.get('event_ticker')} {e.get('title', '')!r} sub {e.get('sub_title', '')!r}")
                for m in (e.get("markets") or [])[:4]:
                    keep = {k: m.get(k) for k in ("ticker", "title", "yes_sub_title", "no_sub_title", "subtitle",
                                                  "floor_strike", "cap_strike", "strike_type", "custom_strike",
                                                  "yes_bid", "yes_ask", "volume", "close_time", "rules_primary")}
                    print("      " + json.dumps(keep)[:600])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true")
    a = ap.parse_args()
    if a.discover:
        discover()


if __name__ == "__main__":
    main()
