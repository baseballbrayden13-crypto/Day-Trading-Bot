"""Bot 3b: a pretend copy of bot 3 with the crypto fear & greed rule. No account, no orders, no money.

    python -m bot.crypto_shadow

Same as bot 3 (BTC/USD and ETH/USD, an equal half each while the last daily close is above its 50-day
average), plus: hold only while the crypto fear & greed index (alternative.me) is above its own 30-day
average. Starts with a pretend $5,000 and trades at the last close with Alpaca's 0.25% crypto fee a side.
brayden asked on Nov 10 2026 to run both versions; this one tracks pretend money so bot 3 keeps its full
account. Nov 10 test: worst drop since 2022 -26% vs bot 3's -42%, but +30%/yr vs +44%/yr over the last two
years (/mnt/project-files/reports/free-data-filters.md).

State: crypto_shadow.json (cash, coins, history) in the working folder (saved on bot-state).
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from pathlib import Path

import pandas as pd

STATE = Path("crypto_shadow.json")
CSV = Path("crypto_shadow.csv")  # day,equity,holding,fear_greed,action (one row a day, for the website)
FEE = 0.0025
START_CASH = 5_000.0
log = logging.getLogger("crypto_shadow")


def fear_greed() -> pd.Series:
    req = urllib.request.Request("https://api.alternative.me/fng/?limit=120&format=json",
                                 headers={"User-Agent": "Mozilla/5.0 (trading bot)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())["data"]
    s = pd.Series({pd.Timestamp(int(d["timestamp"]), unit="s").normalize(): int(d["value"]) for d in data})
    return s.sort_index()


def greed_rising(fg: pd.Series, n: int = 30) -> bool:
    return len(fg) >= n and fg.iloc[-1] > fg.iloc[-n:].mean()


def step(state: dict, prices: dict[str, float], target: set[str], day: str) -> list[str]:
    """Rebalance the pretend book to `target` at `prices` (sell what left, buy what entered with an equal
    share of the book's value). Returns what it did."""
    coins, done = state["coins"], []
    for s in sorted(list(coins)):
        if s not in target and coins[s] > 0:
            state["cash"] += coins.pop(s) * prices[s] * (1 - FEE)
            done.append(f"sold {s}")
    value = state["cash"] + sum(q * prices[s] for s, q in coins.items())
    share = value / len(prices)
    for s in sorted(target):
        if coins.get(s, 0) <= 0:
            amt = min(share, state["cash"])
            coins[s] = amt * (1 - FEE) / prices[s]
            state["cash"] -= amt
            done.append(f"bought {s}")
    equity = state["cash"] + sum(q * prices[s] for s, q in coins.items())
    hist = [h for h in state["history"] if h[0] != day]
    state["history"] = hist + [[day, round(equity, 2), ",".join(sorted(coins)) or "cash"]]
    return done


def write_csv(day: str, state: dict, fg_value: int, action: str) -> None:
    """Upsert today's row in CSV (day,equity,holding,fear_greed,action)."""
    import csv

    rows = []
    if CSV.exists():
        with CSV.open(newline="") as f:
            rows = [r for r in csv.DictReader(f) if r["day"] != day]
    h = state["history"][-1]
    rows.append({"day": day, "equity": f"{h[1]:.2f}", "holding": h[2], "fear_greed": fg_value, "action": action})
    with CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["day", "equity", "holding", "fear_greed", "action"])
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["day"]))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from .crypto_live import daily_closes, want

    symbols = [s.strip().upper() for s in os.getenv("CRYPTO_SYMBOLS", "BTC/USD,ETH/USD").split(",") if s.strip()]
    ma = int(os.getenv("CRYPTO_MA", "50"))
    closes = daily_closes(symbols)
    fg = fear_greed()
    rising = greed_rising(fg)
    target = set(want(closes, ma)) if rising else set()
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {"start": START_CASH, "cash": START_CASH, "coins": {}, "history": []}
    day = str(closes.index[-1].date())
    prices = closes.iloc[-1].to_dict()
    done = step(state, prices, target, day)
    STATE.write_text(json.dumps(state, indent=1))
    write_csv(day, state, int(fg.iloc[-1]), "; ".join(done) or "hold")
    log.info("%s close: fear & greed %d (30-day avg %.0f, %s) | holds %s | pretend $%.2f%s", day, fg.iloc[-1],
             fg.iloc[-30:].mean(), "rising" if rising else "not rising", sorted(target) or "cash",
             state["history"][-1][1], f" | {'; '.join(done)}" if done else "")


if __name__ == "__main__":
    main()
