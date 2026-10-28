"""Guard, the risk watchdog: checks every bot's money every few minutes and speaks up at once.

    python -m bot.guard                          # one check now
    python -m bot.guard --loop 10 --until 16:10  # every 10 minutes until 4:10pm ET (the weekday task)

Medic looks at the fleet once a night; Guard watches during the day. Each check reads every Alpaca
bot's account and holdings (read-only, with each bot's own keys) and the Kalshi state files, then
alerts (bot.alerts: a popup on the PC) when:

    - a bot is down 75% of its daily loss limit today (watch) or past it (act)
    - the Alpaca bots together are down FLEET_DAY_LOSS_PCT (default 2%) today
    - one holding is bigger than the bot's max_position_share (bot.fleet)
    - a long-only bot holds a short position
    - bot 1 still holds anything after 3:55pm ET (it flattens at 3:50pm)
    - a Kalshi bot has half-filled ("stray") positions

Each alert fires once per day. It never places, cancels or closes an order: when something needs
doing, the alert says what, and the person decides. Every check is logged to fleet_data/guard.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .fleet import Bot, host, load

ET = ZoneInfo("America/New_York")
OUT = Path("fleet_data")


@dataclass
class Alarm:
    bot: str  # label, or "fleet"
    level: str  # watch or act
    key: str
    text: str


def read_alpaca(bot: Bot, client_for) -> dict:
    from .data_bot import account, positions

    client = client_for(bot)
    return {"account": account(client), "positions": positions(client)}


def check_bot(bot: Bot, s: dict, now: datetime) -> list[Alarm]:
    out, a = [], s["account"]
    if a["last_equity"] > 0:
        day = (a["equity"] / a["last_equity"] - 1) * 100
        if day <= -bot.max_day_loss_pct:
            out.append(Alarm(bot.tag, "act", "day loss", f"Bot {bot.tag} is down {day:.1f}% today, past its {bot.max_day_loss_pct:g}% "
                             "daily limit. Check what it holds; pausing it needs your OK."))
        elif day <= -0.75 * bot.max_day_loss_pct:
            out.append(Alarm(bot.tag, "watch", "day loss", f"Bot {bot.tag} is down {day:.1f}% today, close to its "
                             f"{bot.max_day_loss_pct:g}% daily limit."))
    for p in s["positions"]:
        if p["qty"] < 0:
            out.append(Alarm(bot.tag, "act", f"short {p['symbol']}", f"Bot {bot.tag} is SHORT {abs(p['qty']):g} {p['symbol']}, "
                             "but it only buys. Something placed an order it shouldn't have."))
        share = abs(p["market_value"]) / a["equity"] if a["equity"] > 0 else 0
        if share > bot.max_position_share:
            out.append(Alarm(bot.tag, "watch", f"size {p['symbol']}", f"Bot {bot.tag}'s {p['symbol']} is {share:.0%} of its money "
                             f"(normal is under {bot.max_position_share:.0%})."))
    et = now.astimezone(ET)
    if bot.num == 1 and s["positions"] and et.weekday() < 5 and (et.hour, et.minute) >= (15, 55) and et.hour < 17:
        held = ", ".join(sorted(p["symbol"] for p in s["positions"]))
        out.append(Alarm(bot.tag, "act", "after close", f"Bot 1 still holds {held} after 3:55pm. It should be flat by 3:50pm; "
                         "if its window is open, check it. The bracket stops still protect the shares."))
    return out


def check_fleet(readings: dict[str, dict], limit_pct: float) -> list[Alarm]:
    now_eq = sum(r["account"]["equity"] for r in readings.values())
    then_eq = sum(r["account"]["last_equity"] for r in readings.values())
    if then_eq > 0 and (now_eq / then_eq - 1) * 100 <= -limit_pct:
        return [Alarm("fleet", "act", "fleet day loss", f"The Alpaca bots together are down {(now_eq / then_eq - 1) * 100:.1f}% "
                      f"today (${now_eq - then_eq:+,.0f}). Guard's fleet limit is {limit_pct:g}%.")]
    return []


def check_kalshi(bot: Bot) -> list[Alarm]:
    out = []
    for mode, _folder, state, _log in bot.runs:
        p = bot.path(state)
        try:
            st = json.loads(p.read_text()) if p.exists() else {}
        except ValueError:
            continue
        stray = sum(1 for b in st.get("open", []) if b.get("sets", 1) == 0)
        if stray:
            out.append(Alarm(bot.tag, "act", f"stray {mode}", f"Bot {bot.tag} holds {stray} half-filled Kalshi positions it couldn't "
                             "sell back. Check them on Kalshi."))
    return out


def run_once(bots: list[Bot], now: datetime, client_for=None, seen_path: Path = OUT / "guard_seen.json",
             log_path: Path = OUT / "guard.csv", notify=None) -> list[Alarm]:
    from .data_bot import trading_client

    client_for = client_for or trading_client
    if notify is None:
        from .alerts import notify
    readings, alarms = {}, []
    for b in bots:
        if b.kind == "kalshi":
            if b.runs_on == host():
                alarms += check_kalshi(b)
            continue
        try:
            readings[b.tag] = read_alpaca(b, client_for)
        except Exception as e:  # bad keys or network: Medic reports those; Guard just notes it
            alarms.append(Alarm(b.tag, "info", "read", f"Couldn't read bot {b.tag}: {type(e).__name__}"))
            continue
        alarms += check_bot(b, readings[b.tag], now)
    if readings:
        alarms += check_fleet(readings, float(os.getenv("FLEET_DAY_LOSS_PCT", "2")))

    log_path.parent.mkdir(exist_ok=True)
    new = not log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "bot", "equity", "day_pct", "holdings"])
        for tag, r in readings.items():
            a = r["account"]
            w.writerow([now.isoformat(timespec="seconds"), tag, round(a["equity"], 2),
                        round((a["equity"] / a["last_equity"] - 1) * 100, 2) if a["last_equity"] else "",
                        ";".join(p["symbol"] for p in r["positions"])])

    today = now.astimezone(ET).date().isoformat()
    seen = json.loads(seen_path.read_text()) if seen_path.exists() else {}
    seen = {k: v for k, v in seen.items() if v == today}
    for al in alarms:
        k = f"{al.bot}|{al.key}|{al.level}"
        if al.level in ("watch", "act") and k not in seen:
            seen[k] = today
            notify("guard", f"Guard: bot {al.bot}" if al.bot != "fleet" else "Guard: whole fleet", al.text, al.level)
    seen_path.write_text(json.dumps(seen, indent=1))
    return alarms


def main() -> None:
    ap = argparse.ArgumentParser(description="Guard: risk watchdog (read-only)")
    ap.add_argument("--loop", type=int, default=0, help="check every N minutes")
    ap.add_argument("--until", default="", help="stop at this ET time, e.g. 16:10")
    args = ap.parse_args()
    bots = load()
    while True:
        now = datetime.now(timezone.utc)
        alarms = run_once(bots, now)
        print(f"{now.astimezone(ET):%H:%M} Guard: " + ("; ".join(f"[{a.level}] {a.text}" for a in alarms) or "all quiet"))
        if not args.loop:
            return
        if args.until:
            hh, mm = (int(x) for x in args.until.split(":"))
            et = datetime.now(ET)
            if (et.hour, et.minute) >= (hh, mm):
                return
        time.sleep(args.loop * 60)


if __name__ == "__main__":
    main()
