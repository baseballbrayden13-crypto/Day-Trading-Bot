"""Bot 7: big-stock momentum on a slice of account ...KTS7 (shared with bots 3 and 6), Alpaca PAPER.

    python -m bot.momentum_live            # once a day after the open: rebalance on the first run of each month
    python -m bot.momentum_live --dry-run  # show the picks, place nothing

Rule (Nov 12 2026 test, /mnt/project-files/reports/bot-tests-nov12.md): once a month, hold the MOM_TOP (5) stocks
from DIP_SYMBOLS (39 big US stocks) with the best gain from 12 months ago to 1 month ago, each about 1/MOM_TOP of
the slice. 2005-2026: about +30% a year, worst drop -43%, against +19.6% for the same 39 stocks held evenly and
+10.8% for SPY. The list is today's big winners, so those numbers are inflated; the fair edge is about +10% a year
over holding the same stocks evenly. Expect big swings (2008: -29%).

Shares ...KTS7 through bot.sleeves (SLEEVES="3=1666,6=1667,7=1667", SLEEVES_FILE=sleeves_kts7.json): it only spends
its own slice and only sells its own shares. Keys come from .env.momentum (a copy of bot 3's). Paper only.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .fleet import DIP_SYMBOLS

ENV_FILE = Path(".env.momentum")
STATE = Path("momentum_state.json")
ET = ZoneInfo("America/New_York")
log = logging.getLogger("momentum")


def picks(closes: pd.DataFrame, top: int = 5, lookback: int = 252, skip: int = 21) -> list[str]:
    """Best `top` by the gain from `lookback` to `skip` finished days ago, best first. [] if too little history."""
    if len(closes) < lookback + 1:
        return []
    mom = closes.iloc[-1 - skip] / closes.iloc[-1 - lookback] - 1
    return list(mom.dropna().sort_values(ascending=False).index[:top])


def plan(want: list[str], held: dict[str, float]) -> tuple[list[str], list[str]]:
    """(sells, buys): sell what dropped out, buy the new picks. Stocks that stay are left alone."""
    held = {s for s, q in held.items() if q > 1e-9}
    return sorted(held - set(want)), [s for s in want if s not in held]


def due(state: dict, today, held: dict[str, float]) -> bool:
    """Rebalance on the first run of a new month, or whenever the slice holds nothing yet."""
    return state.get("month") != f"{today:%Y-%m}" or not any(q > 1e-9 for q in held.values())


def main() -> None:
    ap = argparse.ArgumentParser(description="Bot 7: big-stock momentum (paper)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler("momentum.log")])
    from . import rotation_live

    old, rotation_live.ENV_FILE = rotation_live.ENV_FILE, ENV_FILE
    try:
        cfg = rotation_live.load_settings()  # same rules as bot 2: its own keys, paper only
    finally:
        rotation_live.ENV_FILE = old
    symbols = [s.strip().upper() for s in os.getenv("MOM_SYMBOLS", DIP_SYMBOLS).split(",") if s.strip()]
    top = int(os.getenv("MOM_TOP", "5"))
    from . import sleeves
    from .broker import Broker
    from .dipbuy_live import daily_closes
    from .notify import send

    broker = Broker(cfg)
    rotation_live.ensure_own_account(broker)
    today = datetime.now(ET).date()
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    if state.get("last_run") == str(today) and not args.dry_run:
        log.info("Already ran today; nothing to do.")
        return
    if not args.dry_run and not broker.market_open():
        log.info("Market closed; will try at the next run.")
        return
    shared = sleeves.budgets()
    if "7" not in shared:
        raise SystemExit("Bot 7 only runs on a shared account slice (SLEEVES with 7=...).")
    coins = os.getenv("CRYPTO_SYMBOLS", "BTC/USD,ETH/USD").split(",")
    names = {c.replace("/", ""): c for c in coins}
    account_qty = {names.get(p.symbol, p.symbol): float(p.qty) for p in broker.client.get_all_positions()}
    ledger = sleeves.load()
    sleeves.resize(ledger, shared)
    if not sleeves.ready(ledger, shared, broker.equity()):
        log.info("Waiting for the shared account to hold $%.0f for sleeves %s; nothing to do.", sum(shared.values()), shared)
        return
    closes = daily_closes(symbols, cfg)
    prices = closes.iloc[-1].to_dict()
    others = {"3": coins, "6": [os.getenv("TREND_SYMBOL", "QLD").upper(), os.getenv("TREND_SAFE", "BIL").upper()]}
    sleeve = sleeves.open_sleeve(ledger, "7", symbols, shared["7"], account_qty, prices, others)
    for problem in sleeves.check_account(ledger, account_qty):
        log.error("Sleeve mismatch: %s", problem)
    held = sleeve.shares
    want = picks(closes, top)
    value = sleeve.value(prices)
    if not want:
        log.error("Only %d days of closes; need 253.", len(closes))
        return
    log.info("%s close: top %d by 12-1 month gain %s | holding %s | bot 7 value $%.2f (cash $%.2f)",
             closes.index[-1].date(), top, want, sorted(held) or "nothing", value, sleeve.cash)
    if not due(state, today, held):
        log.info("Not a rebalance day (next: first run of next month).")
        if not args.dry_run:
            sleeves.save(ledger)
            STATE.write_text(json.dumps({**state, "last_run": str(today)}, indent=1))
        return
    sells, buys = plan(want, held)
    for s in sells:
        log.info("SELL %s x%g (dropped out of the top %d)", s, held[s], top)
    for s in buys:
        log.info("BUY %s about $%.2f", s, value / top)
    if args.dry_run:
        return

    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest

    done = []
    for s in sells:
        o = broker.client.submit_order(MarketOrderRequest(symbol=s, qty=held[s], side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
        qty, px = sleeves.wait_fill(broker.client, o.id)
        if qty:
            sleeve.record(s, -qty, px)
            done.append(f"sold {s} at ${px:.2f}")
    for i, s in enumerate(buys):
        free_cash = float(broker.client.get_account().cash)  # never borrow: bots 3 and 6's money isn't ours
        each = sleeve.cash / (len(buys) - i)  # split what's left evenly over the remaining buys
        amount = round(min(each, sleeve.cash, free_cash) * 0.99, 2)
        if amount < 1:
            continue
        o = broker.client.submit_order(MarketOrderRequest(symbol=s, notional=amount, side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
        qty, px = sleeves.wait_fill(broker.client, o.id)
        if qty:
            sleeve.record(s, qty, px)
            done.append(f"bought {s} at ${px:.2f}")
    sleeves.save(ledger)
    STATE.write_text(json.dumps({"month": f"{today:%Y-%m}", "last_run": str(today), "picks": want}, indent=1))
    if done:
        send(cfg, "Bot 7 traded", "; ".join(done))


if __name__ == "__main__":
    main()
