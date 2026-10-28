"""Reporter: a plain-English report card for the week, from what Scout, Medic, Guard and Lab saved.

    python -m bot.reporter            # the last 7 days (the Sunday task)
    python -m bot.reporter --days 30

Writes fleet_data/weekly_<date>.md and report_card.csv (one row per bot, for the Strategy Lab site),
and pops the short version up on the PC. Read-only.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .fleet import Bot, load

ET = ZoneInfo("America/New_York")
OUT = Path("fleet_data")


def _csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def grade(change_pct: float | None, problems: int) -> str:
    """A for a quiet week ... D for one that kept needing attention; a loss of over 2% costs one more letter.
    Running properly counts more than a week's paper profit."""
    score = min(problems, 3) + (1 if change_pct is not None and change_pct < -2 else 0)
    return "ABCD"[min(score, 3)]


def card(bot: Bot, equity: list[dict], trades: list[dict], history: list[dict], alerts: list[dict], lab: list[dict],
         start: str, end: str) -> dict:
    eq = [r for r in sorted(equity, key=lambda r: r["day"]) if r["bot"] == str(bot.num) and float(r["equity"] or 0) > 0]
    week = [r for r in eq if start <= r["day"] <= end]
    before = [r for r in eq if r["day"] < start]
    base = before[-1] if before else week[0] if week else None
    first = float(base["equity"]) if base else None
    last = float(week[-1]["equity"]) if week else None
    change = (last / first - 1) * 100 if first and last else None
    fills = sum(1 for t in trades if t["bot"] == str(bot.num) and start <= t["time"][:10] <= end)
    bad_days = sum(1 for h in history if h["status"].get(str(bot.num)) == "act")
    watch_days = sum(1 for h in history if h["status"].get(str(bot.num)) == "watch")
    guard = sum(1 for a in alerts if a["who"] == "guard" and f"bot {bot.tag}" in a["title"].lower() and start <= a["time"][:10] <= end)
    verdict = next((r["verdict"] for r in lab if r["bot"] == str(bot.num)), "")
    return {"bot": bot.num, "label": bot.tag, "name": bot.name, "equity": round(last, 2) if last else "",
            "week_pct": round(change, 2) if change is not None else "", "since_start_pct":
            round((last / bot.start_equity - 1) * 100, 2) if last else "", "fills": fills, "medic_act_days": bad_days,
            "medic_watch_days": watch_days, "guard_alerts": guard, "lab": verdict,
            "grade": grade(change, bad_days + guard)}


def sentence(c: dict) -> str:
    money = (f"{'up' if c['week_pct'] >= 0 else 'down'} {abs(c['week_pct']):.1f}% this week (${c['equity']:,.2f}, "
             f"{c['since_start_pct']:+.1f}% since start)" if c["week_pct"] != "" else "no money readings this week")
    health = ("ran without problems" if not (c["medic_act_days"] or c["guard_alerts"]) else
              f"needed attention on {c['medic_act_days']} night{'s' if c['medic_act_days'] != 1 else ''}" + (f" and set off Guard {c['guard_alerts']} times" if c["guard_alerts"] else ""))
    lab = f" Lab: {c['lab']}." if c["lab"] else ""
    return f"Bot {c['label']} ({c['name']}), grade {c['grade']}: {money}, {c['fills']} fills, {health}.{lab}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Reporter: weekly report card (read-only)")
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()
    now = datetime.now(timezone.utc).astimezone(ET)
    start, end = (now - timedelta(days=args.days - 1)).date().isoformat(), now.date().isoformat()
    # Medic's last grade of each day (it writes medic_history.csv)
    history = [{"day": r["day"], "status": json.loads(r["status"])} for r in _csv(OUT / "medic_history.csv") if start <= r["day"] <= end]
    cards = [card(b, _csv(OUT / "equity.csv"), _csv(OUT / "trades.csv"), history, _csv(OUT / "alerts.csv"),
                  _csv(OUT / "lab.csv"), start, end) for b in load()]
    lines = [f"# Weekly report card, {start} to {end}", ""] + [f"- {sentence(c)}" for c in cards]
    lines += ["", "Grades: A = ran cleanly all week, B/C = needed attention once/twice, D = kept needing it (a loss over 2% costs a letter). Paper money only."]
    text = "\n".join(lines)
    OUT.mkdir(exist_ok=True)
    (OUT / f"weekly_{end}.md").write_text(text, encoding="utf-8")
    with (OUT / "report_card.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(cards[0]) + ["week"])
        w.writeheader()
        w.writerows({**c, "week": f"{start} to {end}"} for c in cards)
    print(text)
    from .alerts import popup

    popup("Reporter: your week", "\n".join(sentence(c) for c in cards)[:1500])


if __name__ == "__main__":
    main()
