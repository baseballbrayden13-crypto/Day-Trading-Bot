"""The army fund: pretend money that moves toward the winning bots every week. No orders, no real money.

    python -m bot.army_fund   # nightly, after Scout saves fleet_data/equity.csv (run from the state folder)

Real paper accounts can't pass money between each other, so this keeps score instead: a pretend $10,000 spread
over the stock and crypto bots (1, 2, 3, 5, 6, 7). Each bot's slice grows or shrinks with that bot's own equity.
On the first run of every week it re-splits the whole fund:
  - half evenly over all the bots, so no bot is ever dropped,
  - half over the bots that made money in the last 4 weeks, in proportion to their gain (evenly if none did).
Compare its value with "even split, never moved" (also tracked) to see if following the winners helps.
Writes army_fund.json (state) and fleet_data/army_fund.csv (day, value, even_value, weights).

Draft day (Nov 12 2026, C-067, brayden's pick): on the first run of each month the fund's worst member over the
last 4 weeks is benched and its pretend money goes to the best candidate on the bench, if that candidate did
better. The bench is the rookies (bot.rookies: test strategies tracked with pretend money, labels R1, R2, ...)
plus any bot benched earlier, so a benched bot can win its place back. Only members get a share at the weekly
re-split. Nobody is judged on less than 2 weeks of data. Real bots keep running on their paper accounts either
way; only the pretend money moves. Each draft is listed in fleet_data/draft.csv. The "even split, never moved"
comparison stays the original bots only, so it shows whether the shifting and drafting together help.
Undo: delete the "Draft day" block in step() (members then never change).
"""
from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

from .fleet import rescale, scale

START = 10_000.0
BOTS = {"1": 1, "2": 2, "3": 3, "5": 8, "6": 10, "7": 11}  # site label -> fleet number (bot 7 joined Nov 12)
LOOKBACK_DAYS = 28
START_DAY = "2026-11-02"  # first Monday with bots 1-3 all running; past weeks use only data known then
EQUITY = Path("fleet_data/equity.csv")
STATE = Path("army_fund.json")
CSV = Path("fleet_data/army_fund.csv")
ROOKIES = Path("fleet_data/rookies.csv")
DRAFTS = Path("fleet_data/draft.csv")
MIN_DAYS = 14  # draft day judges nobody on less history than this


def read_equity(path: Path = EQUITY) -> dict[str, dict[str, float]]:
    """{label: {day: equity}} for the fund's bots, with sleeve splits taken out (fleet.rescale)."""
    nums = {str(n): lab for lab, n in BOTS.items()}
    out: dict[str, dict[str, float]] = {lab: {} for lab in BOTS}
    try:
        rows = list(csv.DictReader(path.open()))
    except OSError:
        return out
    for r in rows:
        lab = nums.get(r.get("bot", ""))
        try:
            if lab:
                out[lab][r["day"]] = rescale(int(r["bot"]), r["day"], float(r["equity"]))
        except (KeyError, ValueError):
            continue
    try:  # the bench (bot.rookies): pretend test strategies, labels R1, R2, ...
        for r in csv.DictReader(ROOKIES.open()):
            out.setdefault(r["rookie"], {})[r["day"]] = float(r["equity"])
    except (OSError, KeyError, ValueError):
        pass
    return out


def gain(series: dict[str, float], day: str, min_days: int = MIN_DAYS) -> float | None:
    """Gain over the last 4 weeks, or None with less than `min_days` of history."""
    since = (date.fromisoformat(day) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    days = sorted(d for d in series if since <= d <= day)
    if not days or (date.fromisoformat(day) - date.fromisoformat(min(series))).days < min_days or not series[days[0]]:
        return None
    return series[days[-1]] / series[days[0]] - 1


def draft(members: list[str], eq: dict[str, dict[str, float]], day: str) -> tuple[str, str, float, float] | None:
    """(out, in, out's gain, in's gain): the worst member swaps with the best outsider, if the outsider did better."""
    inside = {b: g for b in members if (g := gain(eq.get(b, {}), day)) is not None}
    outside = {b: g for b in eq if b not in members and (g := gain(eq[b], day)) is not None}
    if not inside or not outside:
        return None
    worst, best = min(inside, key=inside.get), max(outside, key=outside.get)
    return (worst, best, inside[worst], outside[best]) if outside[best] > inside[worst] else None


def fix_splits(state: dict) -> None:
    """A bot's account was split again (bot 7 joined ...KTS7 on Nov 12): its equity history is scaled down, so its
    units are scaled up to keep the fund's value the same."""
    seen = state.setdefault("scale", {b: scale(n, "2026-11-11") for b, n in BOTS.items()})
    for b, n in BOTS.items():
        now, old = scale(n), seen.get(b, scale(n))
        if abs(now - old) > 1e-12:
            for units in (state.get("units", {}), state.get("even_units", {})):
                if b in units:
                    units[b] *= old / now
        seen[b] = now


def last_on(series: dict[str, float], day: str) -> float | None:
    days = [d for d in series if d <= day]
    return series[max(days)] if days else None


def weights(eq: dict[str, dict[str, float]], day: str) -> dict[str, float]:
    """Half even over bots with data, half over bots with a 4-week gain, by size of gain."""
    live = [b for b, s in eq.items() if last_on(s, day)]
    if not live:
        return {}
    since = (date.fromisoformat(day) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    gains = {}
    for b in live:
        s = eq[b]
        first = [d for d in s if d >= since and d <= day]
        if first:
            g = last_on(s, day) / s[min(first)] - 1
            if g > 0:
                gains[b] = g
    w = {b: 0.5 / len(live) for b in live}
    total = sum(gains.values())
    for b in live:
        w[b] += 0.5 * (gains[b] / total if total else 1 / len(live)) if (b in gains or not total) else 0
    return w


def step(state: dict, eq: dict[str, dict[str, float]], day: str) -> dict:
    """Value the fund on `day`, re-split it if it's a new week. Returns the new state."""
    def value(units):
        return sum(u * (last_on(eq.get(b, {}), day) or 0) for b, u in units.items())

    if not state:
        w = weights({b: s for b, s in eq.items() if b in BOTS}, day)
        units = {b: START * x / last_on(eq[b], day) for b, x in w.items()}
        state = {"start": day, "week": "", "units": units, "even_units": dict(units), "history": [],
                 "scale": {b: scale(n) for b, n in BOTS.items()}}
    fix_splits(state)
    members = state.setdefault("members", list(BOTS))
    members += [b for b in BOTS if b not in members and b not in state.get("benched", [])]  # a newly built bot joins
    fund, even = value(state["units"]), value(state["even_units"])
    # Draft day (C-067): first run of a new month. Undo: delete this block.
    if state.setdefault("draft_month", day[:7]) != day[:7]:
        state["draft_month"] = day[:7]
        swap = draft(members, eq, day)
        if swap:
            out, new, g_out, g_new = swap
            members[members.index(out)] = new
            state["benched"] = [b for b in state.get("benched", []) if b != new] + ([out] if out in BOTS else [])
            state.setdefault("drafts", []).append([day, out, new, round(g_out, 4), round(g_new, 4)])
            state["week"] = ""  # re-split now so the money moves today
    week = "%d-W%02d" % date.fromisoformat(day).isocalendar()[:2]
    if week != state["week"]:
        w = weights({b: s for b, s in eq.items() if b in members}, day)
        state["units"] = {b: fund * x / last_on(eq[b], day) for b, x in w.items()}
        # bots that joined after the start get an even share of the "never moved" fund at their first week
        missing = [b for b in w if b not in state["even_units"] and b in BOTS]  # rookies never join the comparison
        if missing:
            share = even / (len(state["even_units"]) + len(missing))
            state["even_units"] = {b: u * (even - share * len(missing)) / even for b, u in state["even_units"].items()}
            state["even_units"].update({b: share / last_on(eq[b], day) for b in missing})
        state["week"] = week
    w_now = {b: round(u * (last_on(eq.get(b, {}), day) or 0) / fund, 3) for b, u in state["units"].items()} if fund else {}
    state["history"] = [h for h in state["history"] if h[0] != day] + [[day, round(fund, 2), round(even, 2), w_now]]
    return state


def write_csv(state: dict, path: Path = CSV) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        out = csv.writer(f)
        out.writerow(["day", "value", "even_value", "weights"])
        for day, v, e, w in state["history"]:
            out.writerow([day, v, e, " ".join(f"{b}:{x:.0%}" for b, x in sorted(w.items()))])


def main() -> None:
    eq = read_equity()
    days = sorted({d for s in eq.values() for d in s})
    if not days:
        print("Army fund: no equity data yet")
        return
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    start = state.get("start") or START_DAY
    for day in [d for d in days if d >= start and (not state.get("history") or d >= state["history"][-1][0])]:
        state = step(state, eq, day)
    STATE.write_text(json.dumps(state, indent=1))
    write_csv(state)
    with DRAFTS.open("w", newline="") as f:
        out = csv.writer(f)
        out.writerow(["day", "out", "in", "out_gain", "in_gain"])
        out.writerows(state.get("drafts", []))
    day, v, e, w = state["history"][-1]
    print(f"Army fund {day}: ${v:,.2f} (even split ${e:,.2f}); weights {w}")


if __name__ == "__main__":
    main()
