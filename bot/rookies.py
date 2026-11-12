"""The bench: test strategies ("rookies") tracked with pretend money for draft day. No account, no orders.

    python -m bot.rookies   # nightly, before bot.army_fund (run from the state folder)

Each rookie starts as a pretend $1,000 and grows or shrinks with its strategy's daily close-to-close return,
minus 5 bps on every dollar it trades. On draft day (bot.army_fund, first run of each month) the army fund's
worst bot can lose its pretend money to the best rookie. A rookie that keeps winning is a candidate to be
built as a real paper bot (brayden decides).

  R1  Top 3 momentum     the 3 of bot 7's 39 big stocks with the best 12-1 month gain, re-picked monthly
  R2  QQQ 150-day trend  plain QQQ while it closes above its 150-day average, else BIL (T-bills)
  R3  Bot 3b             the pretend fear & greed copy of bot 3 (read from crypto_shadow.json)
  R4  Income bot         high-dividend ETFs SCHD, VYM, JEPI and JEPQ, a quarter each, evened out monthly. Prices are
                         dividend-adjusted, so payouts count as if reinvested (Nov 12 2026, C-075, brayden's pick).
                         Test: +12.5% a year since mid-2022 with a -16% worst drop (SPY: +16.3%, -20%).

State: rookies.json. Output: fleet_data/rookies.csv (day, rookie, equity).
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pandas as pd

from .fleet import DIP_SYMBOLS

START = 1000.0
COST = 0.0005  # per dollar traded
STATE = Path("rookies.json")
CSV = Path("fleet_data/rookies.csv")
SHADOW = Path("crypto_shadow.json")
NAMES = {"R1": "Top 3 momentum", "R2": "QQQ 150-day trend", "R3": "Bot 3b (fear & greed crypto)", "R4": "Income bot"}
INCOME = ("SCHD", "VYM", "JEPI", "JEPQ")


def top3(closes: pd.DataFrame, old: dict, new_month: bool) -> dict[str, float]:
    from .momentum_live import picks

    if old and not new_month:
        return old
    stocks = [s for s in DIP_SYMBOLS.split(",") if s in closes.columns]
    best = picks(closes[stocks], top=3)
    return {s: 1 / 3 for s in best} if best else old


def qqq150(closes: pd.DataFrame, old: dict, new_month: bool) -> dict[str, float]:
    q = closes["QQQ"].dropna()
    if len(q) < 150:
        return old
    return {"QQQ": 1.0} if q.iloc[-1] > q.iloc[-150:].mean() else {"BIL": 1.0}


def income(closes: pd.DataFrame, old: dict, new_month: bool) -> dict[str, float]:
    if old and not new_month:
        return old
    have = [s for s in INCOME if s in closes.columns and pd.notna(closes[s].iloc[-1])]
    return {s: 1 / len(have) for s in have} if have else old


RULES = {"R1": top3, "R2": qqq150, "R4": income}


def advance(book: dict, closes: pd.DataFrame, rule) -> dict:
    """One finished day: earn yesterday's weights' return, then set today's weights (paying for the change)."""
    day = str(closes.index[-1].date())
    if book.get("day") == day:
        return book
    eq, w = book.get("equity", START), book.get("weights", {})
    if book.get("day") and len(closes) >= 2:
        last, prev = closes.iloc[-1], closes.iloc[-2]
        eq *= 1 + sum(x * (last[s] / prev[s] - 1) for s, x in w.items() if s in closes.columns and prev[s] > 0)
    new = rule(closes, w, new_month=book.get("day", "")[:7] != day[:7])
    turnover = sum(abs(new.get(s, 0) - w.get(s, 0)) for s in set(new) | set(w))
    return {"day": day, "equity": eq * (1 - turnover * COST), "weights": new}


def shadow_rows(path: Path = SHADOW) -> list[tuple[str, float]]:
    try:
        d = json.loads(path.read_text())
        return [(h[0], START * h[1] / d["start"]) for h in d["history"]]
    except (OSError, ValueError, KeyError, IndexError, ZeroDivisionError):
        return []


def write_csv(state: dict, path: Path = CSV) -> None:
    rows = {(d, r): e for r, hist in state.get("history", {}).items() for d, e in hist}
    for d, e in shadow_rows():
        rows[(d, "R3")] = e
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        out = csv.writer(f)
        out.writerow(["day", "rookie", "equity"])
        for (d, r), e in sorted(rows.items()):
            out.writerow([d, r, round(e, 2)])


def main() -> None:
    from . import rotation_live
    from .dipbuy_live import daily_closes

    old, rotation_live.ENV_FILE = rotation_live.ENV_FILE, Path(os.getenv("ROOKIE_ENV", ".env.rotation"))
    try:
        cfg = rotation_live.load_settings()  # market data only; nothing here can place an order
    finally:
        rotation_live.ENV_FILE = old
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    closes = daily_closes(DIP_SYMBOLS.split(",") + ["QQQ", "BIL", *INCOME], cfg)
    books, hist = state.setdefault("books", {}), state.setdefault("history", {})
    for r, rule in RULES.items():
        books[r] = advance(books.get(r, {}), closes, rule)
        h = [x for x in hist.get(r, []) if x[0] != books[r]["day"]] + [[books[r]["day"], round(books[r]["equity"], 2)]]
        hist[r] = h[-800:]
        print(f"Rookie {r} {NAMES[r]}: ${books[r]['equity']:,.2f} holding {sorted(books[r]['weights']) or 'nothing'}")
    STATE.write_text(json.dumps(state, indent=1))
    write_csv(state)


if __name__ == "__main__":
    main()
