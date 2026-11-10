"""The army fund: pretend money that moves toward the winning bots every week. No orders, no real money.

    python -m bot.army_fund   # nightly, after Scout saves fleet_data/equity.csv (run from the state folder)

Real paper accounts can't pass money between each other, so this keeps score instead: a pretend $10,000 spread
over the stock and crypto bots (1, 2, 3, 5, 6). Each bot's slice grows or shrinks with that bot's own equity.
On the first run of every week it re-splits the whole fund:
  - half evenly over all the bots, so no bot is ever dropped,
  - half over the bots that made money in the last 4 weeks, in proportion to their gain (evenly if none did).
Compare its value with "even split, never moved" (also tracked) to see if following the winners helps.
Writes army_fund.json (state) and fleet_data/army_fund.csv (day, value, even_value, weights).
"""
from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

from .fleet import rescale

START = 10_000.0
BOTS = {"1": 1, "2": 2, "3": 3, "5": 8, "6": 10}  # site label -> fleet number
LOOKBACK_DAYS = 28
START_DAY = "2026-11-02"  # first Monday with bots 1-3 all running; past weeks use only data known then
EQUITY = Path("fleet_data/equity.csv")
STATE = Path("army_fund.json")
CSV = Path("fleet_data/army_fund.csv")


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
    return out


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
        return sum(u * (last_on(eq[b], day) or 0) for b, u in units.items())

    if not state:
        w = weights(eq, day)
        units = {b: START * x / last_on(eq[b], day) for b, x in w.items()}
        state = {"start": day, "week": "", "units": units, "even_units": dict(units), "history": []}
    fund, even = value(state["units"]), value(state["even_units"])
    week = "%d-W%02d" % date.fromisoformat(day).isocalendar()[:2]
    if week != state["week"]:
        w = weights(eq, day)
        state["units"] = {b: fund * x / last_on(eq[b], day) for b, x in w.items()}
        # bots that joined after the start get an even share of the "never moved" fund at their first week
        missing = [b for b in w if b not in state["even_units"]]
        if missing:
            share = even / len(w)
            state["even_units"] = {b: u * (even - share * len(missing)) / even for b, u in state["even_units"].items()}
            state["even_units"].update({b: share / last_on(eq[b], day) for b in missing})
        state["week"] = week
    w_now = {b: round(u * (last_on(eq[b], day) or 0) / fund, 3) for b, u in state["units"].items()} if fund else {}
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
    day, v, e, w = state["history"][-1]
    print(f"Army fund {day}: ${v:,.2f} (even split ${e:,.2f}); weights {w}")


if __name__ == "__main__":
    main()
