"""Popups on the PC.

    python -m bot.popup --summary        # Medic's latest grades (PC + cloud), and helper alerts since the last summary
    python -m bot.popup --summary --print   # the same, printed instead of a window
    python -m bot.popup --title T --text X [--warn]   # one message box (bot.alerts uses this)

The summary is meant for a "when I log on" task, so whenever the PC is on you see how every bot did,
including bots 2 and 3 running on GitHub while it was off.
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .fleet import load

OUT = Path("fleet_data")
CLOUD = "https://raw.githubusercontent.com/baseballbrayden13-crypto/Day-Trading-Bot/bot-state/fleet_data/health.csv"
WORDS = {"ok": "OK", "info": "OK", "watch": "watch", "act": "NEEDS ACTION"}


def box(title: str, text: str, warn: bool = False) -> None:
    if sys.platform != "win32":
        print(f"{title}\n{text}")
        return
    import ctypes

    ctypes.windll.user32.MessageBoxW(0, text, title, 0x30 if warn else 0x40)  # warning / information icon


def _rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def cloud_health(url: str = CLOUD) -> list[dict]:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return _rows(r.read().decode("utf-8"))
    except Exception:
        return []  # no cloud runs yet, or offline


def merge(local: list[dict], cloud: list[dict], bots) -> list[dict]:
    """One row per bot: from the machine it runs on (cloud for bots 2/3 once moved), else whichever exists."""
    where = {str(b.num): b.runs_on for b in bots}
    by_local = {r["bot"]: r for r in local}
    by_cloud = {r["bot"]: r for r in cloud}
    out = []
    for num in sorted(set(by_local) | set(by_cloud), key=int):
        first, second = (by_cloud, by_local) if where.get(num) == "cloud" else (by_local, by_cloud)
        out.append(first.get(num) or second[num])
    return out


def summary(rows: list[dict], alerts: list[dict]) -> tuple[str, bool]:
    lines, bad = [], False
    for r in rows:
        if r["bot"] == "0" and r["status"] in ("ok", "info"):
            continue
        name = "Fleet" if r["bot"] == "0" else f"Bot {r['label']} ({r['name']})"
        word = WORDS.get(r["status"], r["status"])
        bad |= r["status"] in ("watch", "act")
        when = r.get("checked", "")[:16].replace("T", " ")
        lines.append(f"{name}: {word}" + ("" if r["status"] in ("ok", "info") else f" - {r['headline'][:160]}") + f"  [{when} UTC]")
    if alerts:
        lines += ["", f"{len(alerts)} helper alerts since last time:"] + [f"- {a['title']}: {a['text'][:120]}" for a in alerts[-5:]]
    return "\n".join(lines) or "No Medic results yet.", bad


def main() -> None:
    ap = argparse.ArgumentParser(description="Fleet popups")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--title", default="Fleet helpers")
    ap.add_argument("--text", default="")
    ap.add_argument("--warn", action="store_true")
    ap.add_argument("--print", action="store_true", help="print the summary instead of a window (and don't mark alerts seen)")
    args = ap.parse_args()
    if not args.summary:
        box(args.title, args.text, args.warn)
        return
    local = _rows((OUT / "health.csv").read_text(encoding="utf-8")) if (OUT / "health.csv").exists() else []
    seen_file = OUT / "popup_seen.txt"
    since = seen_file.read_text().strip() if seen_file.exists() else ""
    alerts = [a for a in (_rows((OUT / "alerts.csv").read_text(encoding="utf-8")) if (OUT / "alerts.csv").exists() else [])
              if a["time"] > since and a["level"] in ("watch", "act")]
    text, bad = summary(merge(local, cloud_health(), load()), alerts)
    if args.print:
        print(text)
        return
    OUT.mkdir(exist_ok=True)
    seen_file.write_text(datetime.now(timezone.utc).isoformat(timespec="seconds"))
    box("Medic: something needs a look" if bad else "Medic: all bots OK", text, bad)


if __name__ == "__main__":
    main()
