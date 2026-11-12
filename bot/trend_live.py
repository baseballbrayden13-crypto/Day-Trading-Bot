"""Bot 6: QQQ trend on a slice of bot 3's Alpaca PAPER account.

    python -m bot.trend_live            # once a day after the open: switch between QQQ and BIL when the trend flips
    python -m bot.trend_live --dry-run  # show what it would hold now, place nothing

Rule (Nov 5 2026 test, /mnt/project-files/reports/strategy-research-round2.md): hold TREND_SYMBOL (QQQ) with the
whole slice while its last daily close is above its TREND_MA-day average (200), else TREND_SAFE (BIL, T-bills).
2008-2026: about +14.7% a year with a -23% worst drop (QQQ buy-and-hold: +18.9%, -35%). It only trades when the
trend flips, a few times a year.

Shares account ...KTS7 with bot 3 through bot.sleeves (SLEEVES="3=2500,6=2500", SLEEVES_FILE=sleeves_kts7.json),
so it only spends its own slice and only sells its own shares. Keys come from .env.trend (a copy of bot 3's).
Paper only, never on bot 1's account.
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

ENV_FILE = Path(".env.trend")
STATE = Path("trend_state.json")
ET = ZoneInfo("America/New_York")
log = logging.getLogger("trend")


def pick(closes: pd.Series, ma: int, risky: str, safe: str) -> str | None:
    """Which one to hold on these finished closes of the risky ETF; None if there's too little history."""
    closes = closes.dropna()
    if len(closes) < ma:
        return None
    return risky if closes.iloc[-1] > closes.iloc[-ma:].mean() else safe


def plan(want: str, held: dict[str, float]) -> tuple[list[str], bool]:
    """(symbols to sell, whether to buy `want`): sell anything else this bot holds, buy `want` if not held."""
    return sorted(s for s, q in held.items() if q > 1e-9 and s != want), held.get(want, 0) <= 1e-9


def main() -> None:
    ap = argparse.ArgumentParser(description="Bot 6: QQQ trend (paper)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler("trend.log")])
    from . import rotation_live

    old, rotation_live.ENV_FILE = rotation_live.ENV_FILE, ENV_FILE
    try:
        cfg = rotation_live.load_settings()  # same rules as bot 2: its own keys, paper only
    finally:
        rotation_live.ENV_FILE = old
    risky, safe = os.getenv("TREND_SYMBOL", "QQQ").upper(), os.getenv("TREND_SAFE", "BIL").upper()
    ma = int(os.getenv("TREND_MA", "200"))
    from . import sleeves
    from .broker import Broker
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
    closes = rotation_live.daily_closes([risky, safe], cfg)
    want = pick(closes[risky], ma, risky, safe)
    if want is None:
        log.error("Only %d days of %s closes; need %d.", len(closes[risky].dropna()), risky, ma)
        return
    prices = closes.iloc[-1].to_dict()
    coins = os.getenv("CRYPTO_SYMBOLS", "BTC/USD,ETH/USD").split(",")
    names = {c.replace("/", ""): c for c in coins}  # Alpaca says BTCUSD; bot 3's slice says BTC/USD
    account_qty = {names.get(p.symbol, p.symbol): float(p.qty) for p in broker.client.get_all_positions()}
    shared = sleeves.budgets()
    ledger = sleeves.load()
    if "6" in shared and not sleeves.ready(ledger, shared, broker.equity()):
        log.info("Waiting for the shared account to hold $%.0f for sleeves %s; nothing to do.", sum(shared.values()), shared)
        return
    others = {"3": coins}
    sleeve = sleeves.open_sleeve(ledger, "6", [risky, safe], shared.get("6") or broker.equity(), account_qty, prices, others)
    for problem in sleeves.check_account(ledger, account_qty):
        log.error("Sleeve mismatch: %s", problem)
    held = sleeve.shares
    sells, buy = plan(want, held)
    avg = closes[risky].dropna().iloc[-ma:].mean()
    value = sleeve.value(prices)
    log.info("%s close: %s $%.2f vs %d-day average $%.2f -> hold %s | holding %s | bot 6 value $%.2f (cash $%.2f)",
             closes.index[-1].date(), risky, prices[risky], ma, avg, want, held or "nothing", value, sleeve.cash)
    for s in sells:
        log.info("SELL %s x%g", s, held[s])
    if buy:
        log.info("BUY %s with the slice's cash", want)
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
    if buy:
        free_cash = float(broker.client.get_account().cash)  # never borrow: bot 3's money isn't ours
        amount = round(min(sleeve.cash, free_cash) * 0.99, 2)
        if amount >= 1:
            o = broker.client.submit_order(MarketOrderRequest(symbol=want, notional=amount, side=OrderSide.BUY,
                                                              time_in_force=TimeInForce.DAY))
            qty, px = sleeves.wait_fill(broker.client, o.id)
            if qty:
                sleeve.record(want, qty, px)
                done.append(f"bought {want} at ${px:.2f}")
    sleeves.save(ledger)
    STATE.write_text(json.dumps({"last_run": str(today), "holding": want, "close": prices[risky], "average": round(avg, 2)}))
    if done:
        send(cfg, "Bot 6 traded", "; ".join(done))


if __name__ == "__main__":
    main()
