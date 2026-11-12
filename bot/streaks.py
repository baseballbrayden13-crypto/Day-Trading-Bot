"""Hot-streak alert: tells brayden when a bot gains or loses more than 3% in a day. No orders.

    python -m bot.streaks   # nightly, after Scout saves fleet_data/equity.csv (run from the state folder)

Compares each stock/crypto bot's latest account value with the day before (account splits taken out with
fleet.rescale). A move of STREAK_PCT (3) percent or more is added to fleet_data/streaks.csv, which the website
shows, and sent to the phone through ntfy when NTFY_TOPIC is set (the same topic as the odds finder's alerts).
Each bot alerts at most once a day. The Kalshi bots are left out: with a pretend $20, one 60-cent bet is 3%.
Nov 12 2026, C-074, brayden's pick. Undo: delete the "Hot-streak alert" step in cloud-bots.yml.
"""
from __future__ import annotations

import csv
import os
import urllib.request
from pathlib import Path

from .fleet import FLEET, rescale

EQUITY = Path("fleet_data/equity.csv")
CSV = Path("fleet_data/streaks.csv")
COLS = ["day", "bot", "name", "change_pct", "equity", "prev_equity"]


def moves(rows: list[dict], threshold: float) -> list[dict]:
    """Bots whose latest day moved `threshold` percent or more against their previous day."""
    bots = {str(b.num): b for b in FLEET if b.kind == "alpaca"}
    series: dict[str, dict[str, float]] = {}
    for r in rows:
        try:
            if r["bot"] in bots:
                series.setdefault(r["bot"], {})[r["day"]] = rescale(int(r["bot"]), r["day"], float(r["equity"]))
        except (KeyError, ValueError):
            continue
    out = []
    for num, s in series.items():
        days = sorted(s)
        if len(days) < 2 or not s[days[-2]]:
            continue
        pct = (s[days[-1]] / s[days[-2]] - 1) * 100
        if abs(pct) >= threshold:
            b = bots[num]
            out.append({"day": days[-1], "bot": b.label or str(b.num), "name": b.name, "change_pct": round(pct, 2),
                        "equity": round(s[days[-1]], 2), "prev_equity": round(s[days[-2]], 2)})
    return sorted(out, key=lambda r: r["bot"])


def text(m: dict) -> tuple[str, str]:
    up = m["change_pct"] > 0
    return (f"Bot {m['bot']} {'up' if up else 'down'} {abs(m['change_pct']):.1f}% today",
            f"{m['name']}: ${m['prev_equity']:,.2f} -> ${m['equity']:,.2f} ({m['change_pct']:+.1f}%) on {m['day']}. Paper money.")


def push(topic: str, title: str, message: str, up: bool) -> bool:
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=message.encode(), method="POST",
                                 headers={"Title": title, "Tags": "fire" if up else "warning"})
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception as e:  # noqa: BLE001 - an alert that fails must never fail the run
        print("Hot-streak alert not sent:", e)
        return False


def main() -> None:
    try:
        rows = list(csv.DictReader(EQUITY.open()))
    except OSError:
        print("Hot streaks: no equity data yet")
        return
    try:
        old = list(csv.DictReader(CSV.open()))
    except OSError:
        old = []
    seen = {(r["day"], r["bot"]) for r in old}
    new = [m for m in moves(rows, float(os.getenv("STREAK_PCT", "3"))) if (m["day"], m["bot"]) not in seen]
    topic = os.getenv("NTFY_TOPIC", "").strip()
    for m in new:
        title, msg = text(m)
        sent = bool(topic) and push(topic, title, msg, m["change_pct"] > 0)
        print(title, "| phone alert sent" if sent else "| site only (no phone topic set)")
    CSV.parent.mkdir(parents=True, exist_ok=True)
    with CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows((old + new)[-500:])
    if not new:
        print("Hot streaks: no bot moved 3% or more today")


if __name__ == "__main__":
    main()
