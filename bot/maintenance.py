"""Medic, the maintenance bot: checks every bot in the fleet and flags the ones that aren't working or performing.

    python -m bot.maintenance             # check the data bot's latest snapshot
    python -m bot.maintenance --collect   # run the data bot first, then check
    python -m bot.maintenance --alert     # also pop up a summary on the PC when something needs a look (bot.alerts)

It reads fleet_data/ (written by Scout, python -m bot.data_bot) and compares each bot with what its
backtest says is normal (limits in bot.fleet). Each finding is one of:

    ok     nothing to do
    info   worth knowing, no action (e.g. too few trades to judge yet)
    watch  out of the ordinary; look again tomorrow
    act    broken or past its limits; the finding says what to do

It never changes a bot, its settings or its orders. Fixes that would change how a bot trades are
written to fleet_data/proposals.csv in the Strategy Lab Changes-log format (status "Proposed"),
so each one can be approved, applied and logged with an undo, or ignored.

A "watch" that shows up REPEAT_TO_ACT days in a row becomes "act", and the report lists what is
new and what got fixed since the last check.

Writes fleet_data/maintenance.md (the report), maintenance.json, proposals.csv, and for the
Strategy Lab site health.csv (one row per bot) and findings.csv.
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

from .fleet import Bot, by_num, host, load

ET = ZoneInfo("America/New_York")
OUT = Path("fleet_data")
LEVELS = ["ok", "info", "watch", "act"]
STALE_HOURS = 26  # a daily job that is later than this missed a run
REPEAT_TO_ACT = 3  # days in a row a "watch" can stay before it becomes "act"


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


def bot_rows(rows: list[dict], num: int) -> list[dict]:
    """A bot's equity rows by day, skipping $0 days from before its account was funded."""
    return [r for r in sorted(rows, key=lambda r: r["day"]) if str(r["bot"]) == str(num) and float(r["equity"] or 0) > 0]


def equity_series(rows: list[dict], num: int) -> list[float]:
    return [float(r["equity"]) for r in bot_rows(rows, num)]


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
    network = ("proxy", "connection", "timeout", "timed out", "name resolution", "max retries")
    rejected = [e for e in errs if any(w in e.lower() for w in ("401", "unauthorized", "forbidden", "403"))
                and not any(w in e.lower() for w in network)]
    if rejected:
        out.append(Finding(bot.num, "act", "keys", f"Alpaca rejected bot {bot.num}'s keys: {rejected[0]}",
                           f"Make new keys on paper account ...{bot.account} (pick it top-left in Alpaca first) and run "
                           f"python set_keys.py --file {bot.env_file}" + (" then python set_cloud_keys.py" if bot.runs_on == "cloud" else "") + ". Making keys on the wrong account revokes that account's keys."))
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
    if bot.always_on and (clock.get("is_open") or bot.kind == "kalshi") and state != "Running":
        out.append(Finding(bot.num, "act", "task", f"{'The market is open but ' if bot.kind != 'kalshi' else ''}\"{t['name']}\" isn't running "
                           f"(last result: {TASK_CODES.get(code, hex(code))}). Bot {bot.tag} can't trade until it's restarted.",
                           f"Start the task again (Task Scheduler > {t['name']} > Run), and keep its window open."))
    elif state != "Running" and code not in (0, 0x41301, 0x41303):  # while running, Windows still shows the last run's code
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
                        "Check its Windows scheduled task, or set this bot's home folder in fleet.json." if bot.runs_on == "pc" else
                        "Check the Cloud bots run on GitHub (Actions tab) and that its keys are in the repository secrets.")]
    due = last_due(bot, now, trading_today)
    seen = _t(lg.get("modified", ""))
    if seen is None or seen < due:
        # A run that's under an hour late may still be going; one missed outright needs a look.
        missed = seen is None or seen < due - timedelta(hours=20) or now - due > timedelta(hours=1)
        return [Finding(bot.num, "act" if missed else "watch", "schedule",
                        f"Bot {bot.num} should have run by {due:%a %H:%M} ET but its log last changed {seen:%a %m/%d %H:%M}." if seen else
                        f"Bot {bot.num}'s log has no timestamp.",
                        "Check its Windows scheduled task (last run result), that the PC was awake, and the end of the log for a crash."
                        if bot.runs_on == "pc" else "Check the Cloud bots runs on GitHub (Actions tab) for a failed or skipped run.")]
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
    out, n, name = [], bot.num, f"Bot {bot.tag}"
    for e in s.get("errors", []):
        out.append(Finding(n, "act", "data", f"{name}: {e}", f"Run it at least once, or set bot {bot.tag}'s home folder in fleet.json."))
    for mode, *_ in bot.runs:
        m = s.get(mode)
        if not m:
            continue
        summ = m.get("summary") or {}
        seen = [t for t in (_t(summ.get("updated", "")), _t((m.get("log") or {}).get("modified", ""))) if t]
        when = max(seen) if seen else None
        limit = timedelta(minutes=bot.stale_minutes) if bot.stale_minutes else timedelta(hours=STALE_HOURS)
        if when is None or now - when > limit:
            out.append(Finding(n, "act", "schedule", f"{name} ({mode}) last wrote anything {when:%a %m/%d %H:%M} ET, "
                               f"over {limit.total_seconds() / 60:.0f} minutes ago." if when else f"{name} ({mode}) has no log or summary.",
                               "Its loop has stopped. Check its scheduled task and its _err.log."))
        stray = int(summ.get("stray_positions", 0) or 0) or m.get("stray", 0)
        if stray:
            out.append(Finding(n, "act", "stray", f"{name}: {stray} half-filled positions are still held.",
                               "Check them on Kalshi; the bot couldn't sell them back."))
        if m.get("losing_trades"):
            out.append(Finding(n, "act", "losses", f"{name}: {m['losing_trades']} 'locked-in' trades lost money. Locked trades can't lose "
                               "unless a leg missed or the bot misread a market.", "Read kalshi_data/opportunities.csv for those events.",
                               proposal=f"Pause {name} until the losing trades are explained.", risk="Medium"))
        start = float(summ.get("start_budget", bot.start_equity) or bot.start_equity)
        eq = float(summ.get("equity", 0) or 0) or start + float(m.get("realized", 0) or 0)
        if eq < start * (1 - bot.max_drawdown_pct / 100):
            out.append(Finding(n, "act", "drawdown", f"{name} is at ${eq:.2f} of its ${start:.2f} start."))
        if int(summ.get("problems", 0) or 0):
            out.append(Finding(n, "watch", "errors", f"{name}: {summ['problems']} warnings last loop. Latest: "
                               f"{(summ.get('last_problems') or [''])[-1][:200]}"))
        out += [replace(f, message=f"{name}: {f.message}") for f in check_log(bot, m.get("log") or {})]
        if not m.get("closed") and not m.get("open"):
            out.append(Finding(n, "info", "performance", f"No {name} trades yet" + (
                f"; {m['quotes']} maker quotes resting." if m.get("quotes") else
                ". Expected: the 14-day backtest found 0 taker trades worth $0.10.")))
        else:
            out.append(Finding(n, "info", "return", f"{name}: {m.get('closed', 0)} settled, {m.get('open', 0)} open, "
                               f"${float(m.get('realized', 0)):+.2f} settled profit."))
    return out


def check_crashes(snap: dict, bots: list[Bot], now: datetime, seen: dict | None = None) -> list[Finding]:
    """Scheduled tasks send crashes to *_err.log files. Flags Traceback/Error/Exception lines written since
    the last check (`seen`: file -> size then, updated in place); with no earlier check, those from the last day."""
    out = []
    seen = {} if seen is None else seen
    for e in snap.get("err_logs", []):
        name = f"{e['home']}/{e['file']}"
        before = seen.get(name)
        seen[name] = e.get("size", 0)
        if before is not None and e.get("size", 0) < before:
            before = 0  # the file was emptied or replaced
        when = _t(e.get("modified", ""))
        if before is None and (when is None or now - when > timedelta(days=1)):
            continue
        fresh = [c for c in e.get("crashes", []) if before is None or c["at"] >= before]
        if not fresh:
            continue
        owner = next((b for b in bots if b.err_log and b.err_log == e["file"] and Path(b.home) == Path(e["home"])), None)
        owner = owner or next((b for b in bots if b.err_log == e["file"]), None)
        out.append(Finding(owner.num if owner else 0, "act", "crash",
                           f"{e['file']} got {len(fresh)} new crash lines (by {when:%a %H:%M} ET). Latest: {fresh[-1]['line'][:200]}",
                           "Read that file for the traceback; the bot may have stopped."))
    return out


def check_benchmark(bot: Bot, equity_rows: list[dict], bench: list[dict]) -> list[Finding]:
    """Compare a bot with just holding its market (bot 2: SPY, bot 3: half BTC, half ETH) since its first day."""
    pick = {2: ("SPY",), 3: ("BTC/USD", "ETH/USD")}.get(bot.num)
    rows = bot_rows(equity_rows, bot.num)
    if not pick or len(rows) < 2:
        return []
    first, last = rows[0]["day"], rows[-1]["day"]
    closes = {(r["day"], r["symbol"]): float(r["close"]) for r in bench}
    moves = []
    for sym in pick:
        days = sorted(d for d, s in closes if s == sym and first <= d <= last)
        if len(days) < 2:
            return []
        if closes[(days[0], sym)] <= 0:
            return []
        moves.append(closes[(days[-1], sym)] / closes[(days[0], sym)] - 1)
    hold = sum(moves) / len(moves) * 100
    mine = (float(rows[-1]["equity"]) / float(rows[0]["equity"]) - 1) * 100
    return [Finding(bot.num, "info", "vs hold", f"Since {first}: bot {mine:+.1f}% vs just holding {' + '.join(pick)} {hold:+.1f}%.")]


def check_replay(snap: dict, trades: list[dict]) -> list[Finding]:
    """Bot 1's real day vs the backtest on the same bars: missed or unexpected entries point at a live bug."""
    rp = snap.get("replay") or {}
    if not rp.get("day"):
        return []
    day = rp["day"]
    live = {}
    for t in trades:
        if str(t["bot"]) == "1" and t["side"] == "buy" and _t(t["time"]) and _t(t["time"]).astimezone(ET).date().isoformat() == day:
            live.setdefault(t["symbol"], []).append(t)
    test = {}
    for t in rp.get("trades", []):
        test.setdefault(t["symbol"], []).append(t)
    out = []
    for sym in sorted(set(test) | set(live)):
        n_test, n_live = len(test.get(sym, [])), len(live.get(sym, []))
        if n_test > n_live:
            t = test[sym][n_live]
            out.append(Finding(1, "watch", "replay", f"On {day} the backtest would have bought {sym} at "
                               f"{_t(t['entry_time']).astimezone(ET):%H:%M} (~${t['entry']:.2f}) but bot 1 didn't.",
                               "Check trades.log that day: was it running, did a risk limit block it, or did the live data differ?"))
        elif n_live > n_test:
            out.append(Finding(1, "watch", "replay", f"On {day} bot 1 bought {sym} {n_live - n_test} more time(s) than the backtest would have.",
                               "Check trades.log for that entry's reason; live and backtest should agree."))
        else:
            for lt, bt in zip(live.get(sym, []), test.get(sym, [])):
                bps = (float(lt["price"]) / bt["entry"] - 1) * 10_000
                if abs(bps) > 25:
                    out.append(Finding(1, "info", "replay", f"{sym} on {day}: live entry ${float(lt['price']):.2f} vs backtest "
                                       f"${bt['entry']:.2f} ({bps:+.0f} bps)."))
    if not out:
        out.append(Finding(1, "ok", "replay", f"{day}: bot 1 did what the backtest would have ({sum(map(len, test.values()))} entries)."))
    return out


def check_events(snap: dict, now: datetime) -> list[Finding]:
    soon = now.astimezone(ET).date() + timedelta(days=3)
    up = [e for e in snap.get("events", []) if e["date"] <= soon.isoformat()]
    if not up:
        return []
    return [Finding(0, "info", "events", "Coming up: " + "; ".join(f"{e['what']} {datetime.fromisoformat(e['date']):%a %m/%d}"
                                                                    for e in up[:8]) + ". Odd results around these days are normal.")]


def check_fleet(snap: dict, bots: list[Bot], now: datetime) -> list[Finding]:
    out = []
    taken = _t(snap.get("taken", ""))
    if taken is None or now - taken > timedelta(hours=STALE_HOURS):
        out.append(Finding(0, "act", "data", f"Scout's newest data is from {taken:%a %m/%d %H:%M}." if taken else "No Scout data yet.",
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
        out.append(Finding(0, "info", "data", f"Scout: {e}"))
    return out


def safely(fn, num: int, *args) -> list[Finding]:
    """One broken check becomes a finding instead of killing the whole report."""
    try:
        return fn(*args)
    except Exception as e:
        return [Finding(num, "watch", "medic", f"Medic's {fn.__name__} check failed: {type(e).__name__}: {e}"[:300],
                        "A Medic bug, not a bot problem. The other checks still ran.")]


def run_checks(snap: dict, bots: list[Bot], equity_rows: list[dict], trades: list[dict], now: datetime,
               bench: list[dict] = (), err_seen: dict | None = None) -> list[Finding]:
    findings = safely(check_fleet, 0, snap, bots, now) + safely(check_crashes, 0, snap, bots, now, err_seen)
    findings += safely(check_events, 0, snap, now) + safely(check_replay, 1, snap, trades)
    trading_today = snap.get("clock", {}).get("trading_day")
    tasks = snap.get("tasks", [])
    for b in bots:
        s = snap.get("bots", {}).get(str(b.num))
        if b.optional and not find_task(b, tasks) and not any(m in (s or {}) for m, *_ in b.runs):
            findings.append(Finding(b.num, "info", "setup", f"Bot {b.tag} isn't set up on this PC yet."))
            continue
        if s is None:
            findings.append(Finding(b.num, "watch", "data", f"No Scout data for bot {b.tag} in the snapshot."))
            continue
        if b.kind == "kalshi":
            findings += safely(check_kalshi, b.num, b, s, now) + safely(check_task, b.num, b, tasks, snap, now)
            continue
        found = safely(check_connection, b.num, b, s)
        if b.runs_on == host():  # its logs, task and state files are on this machine
            found += safely(check_task, b.num, b, tasks, snap, now)
            found += safely(lambda: check_schedule(b, s, now, trading_today, find_task(b, tasks)), b.num)
            found += safely(check_log, b.num, b, s.get("log") or {}) + safely(check_holdings, b.num, b, s, snap, now)
        found += safely(check_risk, b.num, b, s, equity_rows) + safely(check_performance, b.num, b, trades, s)
        found += safely(check_benchmark, b.num, b, equity_rows, bench)
        findings += found
    return findings


# ---------------------------------------------------------------- output

def key(f: Finding) -> str:
    return f"{f.bot}|{f.check}"


def escalate(findings: list[Finding], streaks_path: Path, now: datetime | None = None) -> list[Finding]:
    """A 'watch' seen on REPEAT_TO_ACT days in a row is no longer a blip: make it 'act'. Counts days, not
    runs, so checking several times in one day (or a 1-day error window) doesn't escalate anything."""
    today = (now or datetime.now(timezone.utc)).astimezone(ET).date()
    old = json.loads(streaks_path.read_text()) if streaks_path.exists() else {}
    streaks, out = {}, []
    for f in findings:
        if f.level == "watch":
            prev = old.get(key(f))
            prev = prev if isinstance(prev, dict) else {"days": 0, "last": ""}
            last = datetime.fromisoformat(prev["last"]).date() if prev["last"] else None
            days = prev["days"] if last == today else prev["days"] + 1 if last == today - timedelta(days=1) else 1
            streaks[key(f)] = {"days": days, "last": today.isoformat()}
            if days >= REPEAT_TO_ACT:
                f = replace(f, level="act", message=f"{f.message} (Flagged {days} days in a row.)")
        out.append(f)
    streaks_path.write_text(json.dumps(streaks, indent=1))
    return out


def changes(findings: list[Finding], previous: list[dict]) -> tuple[list[Finding], list[dict]]:
    """(new problems, problems from last check that are gone). Problems = watch or act."""
    before = {f"{p['bot']}|{p['check']}": p for p in previous if p["level"] in ("watch", "act")}
    now = {key(f) for f in findings if f.level in ("watch", "act")}
    new = [f for f in findings if f.level in ("watch", "act") and key(f) not in before]
    return new, [p for k, p in before.items() if k not in now]


def status(findings: list[Finding], num: int) -> str:
    levels = [f.level for f in findings if f.bot == num]
    return max(levels, key=LEVELS.index) if levels else "ok"


LABEL = {"ok": "OK", "info": "OK", "watch": "WATCH", "act": "NEEDS ACTION"}


def names(bots: list[Bot]) -> dict[int, str]:
    return {0: "Whole fleet"} | {b.num: f"Bot {b.tag}: {b.name}" for b in bots}


def headline(findings: list[Finding], num: int) -> str:
    worst = sorted((f for f in findings if f.bot == num), key=lambda f: -LEVELS.index(f.level))
    if not worst or worst[0].level in ("ok", "info"):
        return "Running normally."
    return worst[0].message


def report(findings: list[Finding], bots: list[Bot], now: datetime, new: list[Finding] = (), fixed: list[dict] = ()) -> str:
    title = names(bots)
    lines = [f"# Medic report, {now.astimezone(ET):%a %b %d %Y %H:%M} ET", ""]
    if new or fixed:
        lines.append("## Since the last check")
        lines += [f"- New: {title.get(f.bot, f.bot).split(':')[0]}: {f.message}" for f in new]
        lines += [f"- Fixed: {title.get(p['bot'], p['bot']).split(':')[0]}: {p['message']}" for p in fixed]
        lines.append("")
    for num, name in title.items():
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
    lines.append("Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.")
    return "\n".join(lines)


def proposals(findings: list[Finding], bots: list[Bot], now: datetime) -> list[dict]:
    """Changes-log rows (id,date,area,title,what,why,status,risk,undo) for brayden to approve or ignore."""
    area = {b.num: f"Bot {b.tag}" for b in bots} | {0: "Fleet"}
    return [{"id": "", "date": now.astimezone(ET).date().isoformat(), "area": area.get(f.bot, "Fleet"), "title": f.proposal,
             "what": f.proposal, "why": f.message, "status": "Proposed", "risk": f.risk,
             "undo": "Not applied yet. If approved, the change is logged here with its own undo."}
            for f in findings if f.proposal]


def site_rows(findings: list[Finding], bots: list[Bot], now: datetime) -> tuple[list[dict], list[dict]]:
    """health.csv (one row per bot) and findings.csv, for the Strategy Lab site."""
    checked = now.isoformat(timespec="seconds")
    tags = {0: "fleet"} | {b.num: b.tag for b in bots}
    health = [{"checked": checked, "bot": n, "label": tags[n], "name": names(bots)[n].split(": ")[-1],
               "status": status(findings, n), "headline": headline(findings, n)} for n in tags]
    rows = [{"checked": checked, "bot": f.bot, "label": tags.get(f.bot, f.bot), "level": f.level, "check": f.check,
             "message": f.message, "fix": f.fix} for f in findings]
    return health, rows


def digest(findings: list[Finding], bots: list[Bot], new: list[Finding]) -> tuple[str, str, str]:
    """One phone message per run: (title, text, priority). Loud only when something new needs action."""
    bad = [(n, status(findings, n)) for n in [0] + [b.num for b in bots] if status(findings, n) in ("watch", "act")]
    tags = {0: "fleet"} | {b.num: f"bot {b.tag}" for b in bots}
    if not bad:
        return "Medic: all bots OK", f"All {len(bots)} bots checked, nothing needs you.", "low"
    acts = [n for n, st in bad if st == "act"]
    title = f"Medic: {len(acts)} need action" if acts else f"Medic: {len(bad)} to watch"
    text = "; ".join(f"{tags[n]}: {headline(findings, n)}" for n, _ in bad)
    return title, text[:900], "high" if any(f.level == "act" for f in new) else "default"


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


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Medic, the maintenance bot: check every bot (read-only)")
    ap.add_argument("--collect", action="store_true", help="run Scout (the data bot) first")
    ap.add_argument("--alert", action="store_true", help="pop up a summary when something needs a look")
    args = ap.parse_args()
    bots = load()
    now = datetime.now(timezone.utc)
    if args.collect:
        from . import data_bot

        data_bot.save(data_bot.collect(bots, now))
    snap_path = OUT / "snapshot.json"
    snap = json.loads(snap_path.read_text()) if snap_path.exists() else {}
    OUT.mkdir(exist_ok=True)
    seen_path = OUT / "err_seen.json"
    err_seen = json.loads(seen_path.read_text()) if seen_path.exists() else {}
    findings = run_checks(snap, bots, _read_csv(OUT / "equity.csv"), _read_csv(OUT / "trades.csv"), now,
                          _read_csv(OUT / "benchmarks.csv"), err_seen)
    seen_path.write_text(json.dumps(err_seen, indent=1))
    findings = escalate(findings, OUT / "medic_streaks.json", now)
    last_path = OUT / "maintenance.json"
    previous = json.loads(last_path.read_text()).get("findings", []) if last_path.exists() else []
    new, fixed = changes(findings, previous)
    text = report(findings, bots, now, new, fixed)
    (OUT / "maintenance.md").write_text(text, encoding="utf-8")
    last_path.write_text(json.dumps({
        "checked": now.isoformat(timespec="seconds"),
        "status": {str(n): status(findings, n) for n in [0] + [b.num for b in bots]},
        "findings": [asdict(f) for f in findings]}, indent=1))
    day = now.astimezone(ET).date().isoformat()  # one row per day, the day's last check (Reporter reads it)
    hist = [r for r in _read_csv(OUT / "medic_history.csv") if r["day"] != day]
    hist.append({"day": day, "status": json.dumps({str(n): status(findings, n) for n in [0] + [b.num for b in bots]})})
    _write_csv(OUT / "medic_history.csv", hist, ["day", "status"])
    _write_csv(OUT / "proposals.csv", proposals(findings, bots, now), ["id", "date", "area", "title", "what", "why", "status", "risk", "undo"])
    health, rows = site_rows(findings, bots, now)
    _write_csv(OUT / "health.csv", health, ["checked", "bot", "label", "name", "status", "headline"])
    _write_csv(OUT / "findings.csv", rows, ["checked", "bot", "label", "level", "check", "message", "fix"])
    print(text)
    if args.alert:
        from .alerts import notify

        fresh = new_alerts(findings, OUT / "alerted.json", now)
        title, body, priority = digest(findings, bots, fresh)
        notify("medic", title, body, "act" if priority == "high" else "info" if priority == "low" else "watch")

if __name__ == "__main__":
    main()
