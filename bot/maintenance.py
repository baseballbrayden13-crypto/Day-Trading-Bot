"""Maintenance bot: checks every bot in the fleet and flags the ones that aren't working or performing.

    python -m bot.maintenance             # check the data bot's latest snapshot
    python -m bot.maintenance --collect   # run the data bot first, then check
    python -m bot.maintenance --alert     # also push new "act" findings to the phone (NTFY_TOPIC in .env)

It reads fleet_data/ (written by python -m bot.data_bot) and compares each bot with what its
backtest says is normal (limits in bot.fleet). Each finding is one of:

    ok     nothing to do
    info   worth knowing, no action (e.g. too few trades to judge yet)
    watch  out of the ordinary; look again tomorrow
    act    broken or past its limits; the finding says what to do

It never changes a bot, its settings or its orders. Fixes that would change how a bot trades are
written to fleet_data/proposals.csv in the Strategy Lab Changes-log format (status "Proposed"),
so each one can be approved, applied and logged with an undo, or ignored.

Writes fleet_data/maintenance.md (the report), maintenance.json and proposals.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from .fleet import Bot, by_num, load

ET = ZoneInfo("America/New_York")
OUT = Path("fleet_data")
LEVELS = ["ok", "info", "watch", "act"]
STALE_HOURS = 26  # a daily job that is later than this missed a run


@dataclass
class Finding:
    bot: int  # 0 = the fleet as a whole
    level: str
    check: str
    message: str
    fix: str = ""  # what to do about it
    proposal: str = ""  # a change to how the bot trades: needs brayden's OK, goes to proposals.csv
    risk: str = "Low"


# ---------------------------------------------------------------- helpers

def _t(s: str) -> datetime | None:
    try:
        t = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=ET)


def last_due(bot: Bot, now: datetime, trading_today: bool | None = None) -> datetime:
    """The most recent time the bot should already have written to its log."""
    now = now.astimezone(ET)
    hh, mm = (int(x) for x in bot.runs_at.split(":"))
    day = now.date()
    for _ in range(10):
        t = datetime(day.year, day.month, day.day, hh, mm, tzinfo=ET)
        runs = True
        if bot.days == "weekdays":
            runs = day.weekday() < 5 and (trading_today is not False or day != now.date())
        if runs and t <= now:
            return t
        day -= timedelta(days=1)
    return now - timedelta(days=10)


def drawdown(series: list[float]) -> float:
    """Current drop from the peak, in % (0 at a new high)."""
    if not series:
        return 0.0
    peak = max(series)
    return (1 - series[-1] / peak) * 100 if peak > 0 else 0.0


def equity_series(rows: list[dict], num: int) -> list[float]:
    return [float(r["equity"]) for r in sorted(rows, key=lambda r: r["day"]) if str(r["bot"]) == str(num)]


def round_trips(trades: list[dict], num: int) -> list[dict]:
    """bot.report's FIFO pairing on the data bot's trades.csv rows."""
    from .report import round_trips as pair

    orders = [SimpleNamespace(symbol=r["symbol"], side=r["side"], filled_qty=r["qty"], filled_avg_price=r["price"],
                              filled_at=r["time"], order_type=r["type"])
              for r in sorted(trades, key=lambda r: r["time"]) if str(r["bot"]) == str(num)]
    return pair(orders)


def profit_factor(trips: list[dict]) -> float:
    won = sum(t["pnl"] for t in trips if t["pnl"] > 0)
    lost = -sum(t["pnl"] for t in trips if t["pnl"] <= 0)
    return won / lost if lost else (float("inf") if won else 0.0)


# ---------------------------------------------------------------- checks

def check_connection(bot: Bot, s: dict) -> list[Finding]:
    out = []
    errs = s.get("errors", [])
    if any("no Alpaca keys" in e for e in errs):
        return [Finding(bot.num, "act", "keys", f"No Alpaca keys in {bot.env_file}, so the bot can't trade.",
                        f"Run python set_keys.py --file {bot.env_file} with keys from paper account ...{bot.account}.")]
    if any(w in e.lower() for e in errs for w in ("401", "unauthorized", "forbidden", "403")):
        out.append(Finding(bot.num, "act", "keys", f"Alpaca rejected bot {bot.num}'s keys: {errs[0]}",
                           f"Make new keys on paper account ...{bot.account} (pick it top-left in Alpaca first) and run "
                           f"python set_keys.py --file {bot.env_file}. Making keys on the wrong account revokes that account's keys."))
    elif errs:
        out.append(Finding(bot.num, "watch", "data", f"Couldn't read everything from Alpaca: {'; '.join(errs)[:300]}",
                           "Usually a network blip. If it repeats tomorrow, check the keys and Alpaca's status page."))
    a = s.get("account")
    if a:
        if bot.account and a["account"] != bot.account:
            out.append(Finding(bot.num, "act", "account", f"Keys open account ...{a['account']}, expected ...{bot.account}.",
                               "Stop the bot until the keys match its own account, or update fleet.json if the move was on purpose.", risk="High"))
        if a["trading_blocked"] or a["account_blocked"] or (a["status"] and a["status"] != "ACTIVE"):
            out.append(Finding(bot.num, "act", "account", f"Alpaca account status {a['status']}, trading blocked: {a['trading_blocked']}.",
                               "Check the account on alpaca.markets; a blocked paper account can be reset there."))
    return out


# Windows task result codes worth naming (anything else nonzero is shown as hex)
TASK_CODES = {0: "finished OK", 0x41301: "still running", 0x41303: "has not run yet", 0x41306: "stopped by Task Scheduler",
              0xC000013A: "its window was closed (or Ctrl+C)", 0x1: "the script exited with an error", 0x8007010B: "its start-in folder is wrong",
              0x800710E0: "refused to start (the PC was busy or asleep)"}


def find_task(bot: Bot, tasks: list[dict]) -> dict | None:
    if not bot.task:
        return None
    exact = [t for t in tasks if t.get("name", "").lower() == bot.task.lower()]
    loose = [t for t in tasks if bot.task.lower() in t.get("name", "").lower()]
    return (exact or loose or [None])[0]


def check_task(bot: Bot, tasks: list[dict], snap: dict, now: datetime) -> list[Finding]:
    """Uses the Windows task itself, which knows more than the log: is it running, did it crash."""
    t = find_task(bot, tasks)
    if t is None:
        return []
    out = []
    code = int(t.get("last_result") or 0) & 0xFFFFFFFF
    clock = snap.get("clock", {})
    state = str(t.get("state", ""))
    if state == "Disabled":
        out.append(Finding(bot.num, "act", "task", f"Its Windows task \"{t['name']}\" is disabled, so bot {bot.num} won't run.",
                           "Re-enable it in Task Scheduler if that wasn't on purpose."))
    if bot.always_on and clock.get("is_open") and state != "Running":
        out.append(Finding(bot.num, "act", "task", f"The market is open but \"{t['name']}\" isn't running "
                           f"(last result: {TASK_CODES.get(code, hex(code))}). Bot 1 can't trade today until it's restarted.",
                           f"Start the task again (Task Scheduler > {t['name']} > Run), and keep its window open."))
    elif code not in (0, 0x41301, 0x41303):
        out.append(Finding(bot.num, "act" if bot.always_on else "watch", "task",
                           f"Its last run ended badly: {TASK_CODES.get(code, hex(code))} (code {hex(code)}).",
                           "Read the end of its log. If the window was closed, the bot stopped with it."))
    return out


def check_schedule(bot: Bot, s: dict, now: datetime, trading_today: bool | None, task: dict | None = None) -> list[Finding]:
    lg = s.get("log") or {}
    if bot.kind == "kalshi":
        return []  # bot 4 reports through its summary file (check_kalshi)
    if bot.always_on and task is not None:
        return []  # a loop's log can sit still for hours; check_task looks at the task instead
    if not lg.get("exists"):
        return [Finding(bot.num, "act", "schedule", f"{bot.log_file} doesn't exist in {bot.home}, so bot {bot.num} has never run here.",
                        "Check its Windows scheduled task, or set this bot's home folder in fleet.json.")]
    due = last_due(bot, now, trading_today)
    seen = _t(lg.get("modified", ""))
    if seen is None or seen < due:
        # A run that's under an hour late may still be going; one missed outright needs a look.
        missed = seen is None or seen < due - timedelta(hours=20) or now - due > timedelta(hours=1)
        return [Finding(bot.num, "act" if missed else "watch", "schedule",
                        f"Bot {bot.num} should have run by {due:%a %H:%M} ET but its log last changed {seen:%a %m/%d %H:%M}." if seen else
                        f"Bot {bot.num}'s log has no timestamp.",
                        "Check its Windows scheduled task (last run result), that the PC was awake, and the end of the log for a crash.")]
    return []


def check_log(bot: Bot, lg: dict) -> list[Finding]:
    out = []
    if lg.get("live_warning"):
        out.append(Finding(bot.num, "act", "live", f"Bot {bot.num}'s log says it connected to a LIVE account.",
                           "Stop it now. The fleet is paper only; remove LIVE_TRADING from its env file.", risk="High"))
    n = lg.get("errors_24h", 0)
    if n:
        last = (lg.get("last_errors") or [""])[-1]
        out.append(Finding(bot.num, "act" if n >= 5 else "watch", "errors", f"{n} errors in the last day. Latest: {last[:200]}",
                           "Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug."))
    return out


def check_risk(bot: Bot, s: dict, equity_rows: list[dict]) -> list[Finding]:
    out = []
    a = s.get("account")
    if a and a["last_equity"] > 0:
        day = (a["equity"] / a["last_equity"] - 1) * 100
        if day <= -bot.max_day_loss_pct:
            out.append(Finding(bot.num, "act", "day loss", f"Down {day:.1f}% today (limit for this bot {bot.max_day_loss_pct:g}%).",
                               "Check what it holds and whether its own loss limits worked."
                               + (" Bot 1 halts itself at -2%, so this means the halt didn't fire." if bot.num == 1 else "")))
    series = equity_series(equity_rows, bot.num)
    dd = drawdown(series)
    if dd > bot.max_drawdown_pct * 1.5:
        out.append(Finding(bot.num, "act", "drawdown",
                           f"Down {dd:.1f}% from its peak, 1.5x past the worst drop in its backtest ({bot.max_drawdown_pct:g}%).",
                           "Not normal for this strategy.",
                           proposal=f"Pause bot {bot.num} and re-run its backtest on the latest data to see if the edge is gone.", risk="Medium"))
    elif dd > bot.max_drawdown_pct:
        out.append(Finding(bot.num, "watch", "drawdown", f"Down {dd:.1f}% from its peak, past its backtest worst ({bot.max_drawdown_pct:g}%).",
                           "Within what can happen, but rare. Keep watching."))
    if series and len(series) > 1:
        ret = (series[-1] / bot.start_equity - 1) * 100
        out.append(Finding(bot.num, "info", "return", f"${series[-1]:,.2f}, {ret:+.1f}% since the ${bot.start_equity:,.0f} start."))
    return out


def check_holdings(bot: Bot, s: dict, snap: dict, now: datetime) -> list[Finding]:
    held = {p["symbol"]: p for p in s.get("positions", [])}
    clock = snap.get("clock", {})
    et = now.astimezone(ET)
    if bot.num == 1 and held and clock and not clock.get("is_open") and (et.hour >= 16 or et.hour < 9):
        return [Finding(1, "act", "overnight", f"Bot 1 still holds {', '.join(sorted(held))} after the close. Its 3:50pm flatten didn't run.",
                        "Check trades.log around 3:50pm. The bracket stops still protect the shares.",
                        proposal="Close bot 1's leftover positions at the next open.", risk="Medium")]
    if bot.num == 2:
        state = s.get("rotation_state") or {}
        want = set((state.get("holding") or {}))
        if not state:
            return [Finding(2, "info" if not held else "watch", "holdings",
                            "No rotation_state.json yet: bot 2 hasn't made its first rebalance." if not held else
                            f"Holds {', '.join(sorted(held))} but has no rotation_state.json.")]
        if set(held) != want:
            return [Finding(2, "watch", "holdings", f"Holds {', '.join(sorted(held)) or 'nothing'}, but its last rebalance chose "
                            f"{', '.join(sorted(want)) or 'all cash'}.", "Orders may still have been filling. If it's the same tomorrow, "
                            "check rotation.log for rejected orders.")]
    if bot.num == 3:
        rows = {r["symbol"]: r for r in snap.get("market", {}).get("symbols", [])}
        diffs = []
        for sym in bot.symbols:
            r = rows.get(sym)
            if r is None or r.get("above_50d") is None:
                continue
            holds = sym.replace("/", "") in held or sym in held
            if holds != r["above_50d"]:
                diffs.append(f"{sym} is {'above' if r['above_50d'] else 'below'} its 50-day average but bot 3 "
                             f"{'holds' if holds else 'does not hold'} it")
        if diffs:
            return [Finding(3, "watch", "holdings", "; ".join(diffs) + ".",
                            "Bot 3 decides at 8:15pm ET on finished daily bars; before then this can differ. If it's the same "
                            "after 8:15pm, check crypto.log.")]
    return []


def check_performance(bot: Bot, trades: list[dict], s: dict) -> list[Finding]:
    if bot.num != 1:
        return []
    from .report import BACKTEST

    out = []
    trips = round_trips(trades, 1)
    if len(trips) < bot.min_trades:
        out.append(Finding(1, "info", "performance", f"{len(trips)} closed trades so far; {bot.min_trades} are needed before the "
                           "results say anything about the strategy."))
    else:
        pf = profit_factor(trips)
        wins = sum(t["pnl"] > 0 for t in trips) / len(trips)
        msg = (f"{len(trips)} closed trades: profit factor {pf:.2f} (backtest {BACKTEST['profit_factor']:.2f}), "
               f"win rate {wins:.0%} (backtest {BACKTEST['win_rate']:.0%}).")
        if pf < bot.min_profit_factor:
            out.append(Finding(1, "act", "performance", msg + " It's losing money.",
                               "Compare its trades with the backtest's on the same days to find where they differ.",
                               proposal="Pause bot 1 and re-run the 3-year ORB research with the newest year.", risk="Medium"))
        elif pf < BACKTEST["profit_factor"] * 0.8:
            out.append(Finding(1, "watch", "performance", msg + " Profitable, but well under the backtest."))
        else:
            out.append(Finding(1, "ok", "performance", msg))
    f = s.get("fills") or {}
    n, bps = f.get("fills", 0), f.get("avg_bps")
    if bps is not None and n >= 10:
        if bps >= 5:
            out.append(Finding(1, "act", "slippage", f"Real fills cost {bps:+.1f} bps on average over {n} fills. The ORB edge is "
                               "about gone at 5 bps.", "Limit entries held up at 5 bps in the backtest (out-of-sample PF ~1.2 vs 0.98).",
                               proposal="Turn on limit entries for bot 1 (ENTRY_LIMIT_BPS=5 in .env).", risk="Medium"))
        elif bps > 2 and n >= 20:
            out.append(Finding(1, "watch", "slippage", f"Real fills cost {bps:+.1f} bps over {n} fills, worse than the 2 bps the backtest assumed.",
                               proposal="Turn on limit entries for bot 1 (ENTRY_LIMIT_BPS=5 in .env); they beat market orders in the backtest."))
        else:
            out.append(Finding(1, "ok", "slippage", f"Real fills cost {bps:+.1f} bps over {n} fills (backtest assumes 2)."))
    return out


def check_kalshi(bot: Bot, s: dict, now: datetime) -> list[Finding]:
    out = []
    for e in s.get("errors", []):
        out.append(Finding(4, "act", "data", f"Kalshi: {e}.", "Run the Kalshi bot at least once, or set bot 4's home folder in fleet.json."))
    for mode in ("paper", "demo"):
        m = s.get(mode)
        if not m:
            continue
        summ = m.get("summary") or {}
        when = _t(summ.get("updated", ""))
        if when is None or now - when > timedelta(hours=STALE_HOURS):
            out.append(Finding(4, "act" if mode == "paper" else "watch", "schedule",
                               f"Kalshi {mode} run last updated {when:%a %m/%d %H:%M}." if when else f"Kalshi {mode} has no summary.json.",
                               "Check that its loop or scheduled task is still running."))
        if int(summ.get("stray_positions", 0) or 0):
            out.append(Finding(4, "act", "stray", f"Kalshi {mode}: {summ['stray_positions']} half-filled positions are still held.",
                               "Check them on Kalshi; the bot couldn't sell them back."))
        if m.get("losing_trades"):
            out.append(Finding(4, "act", "losses", f"Kalshi {mode}: {m['losing_trades']} 'locked-in' trades lost money. Locked trades can't lose "
                               "unless a leg missed or the bot misread a market.", "Read kalshi_data/opportunities.csv for those events.",
                               proposal=f"Pause Kalshi {mode} trading until the losing trades are explained.", risk="Medium"))
        eq, start = float(summ.get("equity", 0) or 0), float(summ.get("start_budget", bot.start_equity) or bot.start_equity)
        if eq and eq < start * (1 - bot.max_drawdown_pct / 100):
            out.append(Finding(4, "act", "drawdown", f"Kalshi {mode} is at ${eq:.2f} of its ${start:.2f} start."))
        if int(summ.get("problems", 0) or 0):
            out.append(Finding(4, "watch", "errors", f"Kalshi {mode}: {summ['problems']} warnings last loop. Latest: "
                               f"{(summ.get('last_problems') or [''])[-1][:200]}"))
        if mode == "paper" and summ and not m.get("closed") and not m.get("open"):
            out.append(Finding(4, "info", "performance", "No Kalshi paper trades yet. Expected: the 14-day backtest found 0 taker "
                               "trades worth $0.10, which is why resting maker bids are being tested on demo."))
    return out


def check_fleet(snap: dict, bots: list[Bot], now: datetime) -> list[Finding]:
    out = []
    taken = _t(snap.get("taken", ""))
    if taken is None or now - taken > timedelta(hours=STALE_HOURS):
        out.append(Finding(0, "act", "data", f"The newest fleet data is from {taken:%a %m/%d %H:%M}." if taken else "No fleet data yet.",
                           "Run python -m bot.data_bot (or schedule bot.maintenance --collect daily)."))
    seen: dict[str, int] = {}
    for num, s in snap.get("bots", {}).items():
        acct = (s.get("account") or {}).get("account")
        if acct and acct in seen:
            out.append(Finding(0, "act", "account", f"Bots {seen[acct]} and {num} trade the same account ...{acct}.",
                               "Each bot needs its own paper account until shared-account support exists: bot 1's 3:50pm "
                               "close-all would sell the other bot's holdings.", risk="High"))
        elif acct:
            seen[acct] = int(num)
    for e in snap.get("errors", []):
        out.append(Finding(0, "info", "data", f"Data bot: {e}"))
    return out


def run_checks(snap: dict, bots: list[Bot], equity_rows: list[dict], trades: list[dict], now: datetime) -> list[Finding]:
    findings = check_fleet(snap, bots, now)
    trading_today = snap.get("clock", {}).get("trading_day")
    for b in bots:
        s = snap.get("bots", {}).get(str(b.num))
        if s is None:
            findings.append(Finding(b.num, "watch", "data", f"No data for bot {b.num} in the snapshot."))
            continue
        if b.kind == "kalshi":
            findings += check_kalshi(b, s, now)
            for t in [t for t in snap.get("tasks", []) if "kalshi" in t.get("name", "").lower()]:  # paper bot, maker test, ...
                findings += check_task(replace(b, task=t["name"]), [t], snap, now)
            continue
        tasks = snap.get("tasks", [])
        found = check_connection(b, s) + check_task(b, tasks, snap, now)
        found += check_schedule(b, s, now, trading_today, find_task(b, tasks)) + check_log(b, s.get("log") or {})
        found += check_risk(b, s, equity_rows) + check_holdings(b, s, snap, now) + check_performance(b, trades, s)
        findings += found
    return findings


# ---------------------------------------------------------------- output

def status(findings: list[Finding], num: int) -> str:
    levels = [f.level for f in findings if f.bot == num]
    return max(levels, key=LEVELS.index) if levels else "ok"


LABEL = {"ok": "OK", "info": "OK", "watch": "WATCH", "act": "NEEDS ACTION"}


def report(findings: list[Finding], bots: list[Bot], now: datetime) -> str:
    lines = [f"# Fleet maintenance report, {now.astimezone(ET):%a %b %d %Y %H:%M} ET", ""]
    for num, name in [(0, "Whole fleet")] + [(b.num, f"Bot {b.num}: {b.name}") for b in bots]:
        mine = sorted((f for f in findings if f.bot == num), key=lambda f: -LEVELS.index(f.level))
        if num == 0 and not mine:
            continue
        lines.append(f"## {name}: {LABEL[status(findings, num)]}")
        for f in mine:
            lines.append(f"- **{f.level}** ({f.check}) {f.message}" + (f" Fix: {f.fix}" if f.fix else ""))
            if f.proposal:
                lines.append(f"  - Proposed change (needs OK): {f.proposal}")
        if not mine:
            lines.append("- Nothing to report.")
        lines.append("")
    lines.append("This bot only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.")
    return "\n".join(lines)


def proposals(findings: list[Finding], bots: list[Bot], now: datetime) -> list[dict]:
    """Changes-log rows (id,date,area,title,what,why,status,risk,undo) for brayden to approve or ignore."""
    names = {b.num: f"Bot {b.num}" for b in bots} | {0: "Fleet"}
    return [{"id": "", "date": now.astimezone(ET).date().isoformat(), "area": names.get(f.bot, "Fleet"), "title": f.proposal,
             "what": f.proposal, "why": f.message, "status": "Proposed", "risk": f.risk,
             "undo": "Not applied yet. If approved, the change is logged here with its own undo."}
            for f in findings if f.proposal]


def new_alerts(findings: list[Finding], sent_path: Path, now: datetime) -> list[Finding]:
    """'act' findings not already alerted in the last day (so the phone isn't spammed every run)."""
    sent = json.loads(sent_path.read_text()) if sent_path.exists() else {}
    fresh, keep = [], {}
    for k, t in sent.items():
        if now - datetime.fromisoformat(t) < timedelta(days=1):
            keep[k] = t
    for f in findings:
        k = f"{f.bot}|{f.check}|{f.message[:80]}"
        if f.level == "act" and k not in keep:
            fresh.append(f)
            keep[k] = now.isoformat()
    sent_path.write_text(json.dumps(keep, indent=1))
    return fresh


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    ap = argparse.ArgumentParser(description="Maintenance bot: check every bot (read-only)")
    ap.add_argument("--collect", action="store_true", help="run the data bot first")
    ap.add_argument("--alert", action="store_true", help="push new 'act' findings to the phone")
    args = ap.parse_args()
    bots = load()
    now = datetime.now(timezone.utc)
    if args.collect:
        from . import data_bot

        data_bot.save(data_bot.collect(bots, now))
    snap_path = OUT / "snapshot.json"
    snap = json.loads(snap_path.read_text()) if snap_path.exists() else {}
    findings = run_checks(snap, bots, _read_csv(OUT / "equity.csv"), _read_csv(OUT / "trades.csv"), now)
    OUT.mkdir(exist_ok=True)
    text = report(findings, bots, now)
    (OUT / "maintenance.md").write_text(text, encoding="utf-8")
    (OUT / "maintenance.json").write_text(json.dumps({
        "checked": now.isoformat(timespec="seconds"),
        "status": {str(n): status(findings, n) for n in [0] + [b.num for b in bots]},
        "findings": [asdict(f) for f in findings]}, indent=1))
    rows = proposals(findings, bots, now)
    with (OUT / "proposals.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["id", "date", "area", "title", "what", "why", "status", "risk", "undo"])
        w.writeheader()
        w.writerows(rows)
    print(text)
    if args.alert:
        from dotenv import dotenv_values

        from .notify import send

        topic = (dotenv_values(".env").get("NTFY_TOPIC") or "").strip() if Path(".env").exists() else ""
        for f in new_alerts(findings, OUT / "alerted.json", now):
            send(SimpleNamespace(ntfy_topic=topic), f"Bot {f.bot or 'fleet'} needs attention", f"{f.message} {f.fix}"[:400], "high")


if __name__ == "__main__":
    main()
