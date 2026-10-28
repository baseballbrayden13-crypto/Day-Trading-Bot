"""Where the helpers' alerts go: a popup on the PC (when it's on), a line in fleet_data/alerts.csv,
and the phone only if ALERTS_PHONE=true in .env (the trading bots' own ntfy alerts are separate).

    python -m bot.alerts --test     # show a test popup
"""
from __future__ import annotations

import csv
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

LOG = Path("fleet_data") / "alerts.csv"


def _env(name: str) -> str:
    from dotenv import dotenv_values

    return (dotenv_values(".env").get(name) or "").strip() if Path(".env").exists() else ""


def popup(title: str, text: str, warn: bool = False) -> bool:
    """A Windows message box in its own process, so the caller never waits for someone to click OK."""
    if sys.platform != "win32":
        return False
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([sys.executable, "-m", "bot.popup", "--title", title, "--text", text] + (["--warn"] if warn else []),
                     creationflags=flags, close_fds=True)
    return True


def quiet_hours(now: datetime | None = None) -> bool:
    """No popups from 11pm to 7am ET (ALERTS_QUIET=23-7 in .env to change, "off" for none)."""
    from zoneinfo import ZoneInfo

    span = _env("ALERTS_QUIET") or "23-7"
    if span.lower() == "off":
        return False
    start, end = (int(x) for x in span.split("-"))
    h = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York")).hour
    return (h >= start or h < end) if start > end else start <= h < end


def notify(who: str, title: str, text: str, level: str = "info", log: Path = LOG) -> None:
    """level: info, watch or act. Every alert is logged; watch/act pop up on the PC."""
    log.parent.mkdir(exist_ok=True)
    new = not log.exists()
    with log.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "who", "level", "title", "text"])
        w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), who, level, title, text])
    if level in ("watch", "act") and not quiet_hours():
        popup(title, text, warn=level == "act")  # at night it waits for the logon / morning summary instead
    if _env("ALERTS_PHONE").lower() in {"1", "true", "yes", "on"} and level == "act":
        from .notify import send

        send(SimpleNamespace(ntfy_topic=_env("NTFY_TOPIC")), title, text[:400], "high")


if __name__ == "__main__":
    if "--test" in sys.argv:
        print("Popup shown." if popup("Fleet helpers", "Test popup: alerts will look like this.") else "Popups only work on Windows.")
