"""Bot 5: big-stock dip-buyer on its own Alpaca PAPER account.

    python -m bot.dipbuy_live            # once a day, just after the open: sell bounced stocks, buy new dips
    python -m bot.dipbuy_live --dry-run  # show what it would do now, place nothing

Rules (Nov 5 2026 test, /mnt/project-files/reports/bot5-strategy-tests.md): on yesterday's close, a stock from
DIP_SYMBOLS that is above its 200-day average with a 2-day RSI under DIP_RSI (5) is a dip. Buy the most
oversold dips at the open, up to DIP_SLOTS (5) at a time, each 1/DIP_SLOTS of the account. Sell at the open
after it closes above its 5-day average, or after DIP_MAX_DAYS (10) trading days. 2018-2026 unseen test:
about +6.5% a year, worst drop -14%, profit factor 1.31, ~100 trades a year, with 5 bps costs a side.

Keys come from .env.dipbuy. Paper only, never on bot 1's account. It can share an account with bot 2 through
bot.sleeves (SLEEVES="2=5000,5=5000"): it then only spends its own slice and only sells its own stocks.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ENV_FILE = Path(".env.dipbuy")
STATE = Path("dipbuy_state.json")
from .fleet import DIP_SYMBOLS as SYMBOLS  # noqa: E402
log = logging.getLogger("dipbuy")


def rsi(c: pd.Series, n: int = 2) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.where(dn != 0))


def signals(closes: pd.DataFrame, rsi_max: float = 5) -> tuple[list[str], set[str]]:
    """From finished daily closes: (dips, most oversold first; stocks closed above their 5-day average)."""
    if len(closes) < 200:
        return [], set()
    last = closes.iloc[-1]
    m200, m5 = closes.iloc[-200:].mean(), closes.iloc[-5:].mean()
    r2 = closes.apply(rsi).iloc[-1]
    dips = [s for s in closes.columns if pd.notna(m200[s]) and last[s] > m200[s] and r2[s] < rsi_max]
    return sorted(dips, key=lambda s: r2[s]), {s for s in closes.columns if last[s] > m5[s]}


def plan(held: dict[str, int], days_held: dict[str, int], dips: list[str], bounced: set[str], slots: int,
         max_days: int) -> tuple[list[str], list[str]]:
    """(sells, buys). Sell what bounced or is out of time; fill free slots with the most oversold new dips."""
    sells = sorted(s for s in held if s in bounced or days_held.get(s, 0) >= max_days)
    free = slots - (len(held) - len(sells))
    buys = [s for s in dips if s not in held][:max(free, 0)]
    return sells, buys


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"entered": {}}


def trading_days_since(index: pd.DatetimeIndex, day: str) -> int:
    """Finished trading days since the entry day (the entry day itself doesn't count)."""
    return int((index.date > pd.Timestamp(day).date()).sum())


def daily_closes(symbols: list[str], cfg) -> pd.DataFrame:
    from alpaca.data.enums import Adjustment
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = StockHistoricalDataClient(cfg.alpaca_key, cfg.alpaca_secret)
    req = StockBarsRequest(symbol_or_symbols=symbols, timeframe=TimeFrame.Day, adjustment=Adjustment.ALL, feed="iex",
                           start=datetime.now(timezone.utc) - timedelta(days=420))
    closes = client.get_stock_bars(req).df["close"].unstack(level="symbol")
    today = datetime.now(timezone.utc).astimezone().date()
    return closes[[d.date() < today for d in closes.index]].ffill()  # finished days only


def main() -> None:
    ap = argparse.ArgumentParser(description="Bot 5: big-stock dip-buyer (paper)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler("dipbuy.log")])
    from . import rotation_live

    old, rotation_live.ENV_FILE = rotation_live.ENV_FILE, ENV_FILE
    try:
        cfg = rotation_live.load_settings()  # same rules as bot 2: its own keys, paper only
    finally:
        rotation_live.ENV_FILE = old
    symbols = [s.strip().upper() for s in os.getenv("DIP_SYMBOLS", SYMBOLS).split(",") if s.strip()]
    slots, max_days = int(os.getenv("DIP_SLOTS", "5")), int(os.getenv("DIP_MAX_DAYS", "10"))
    from .broker import Broker
    from .notify import send

    broker = Broker(cfg)
    rotation_live.ensure_own_account(broker)
    from . import sleeves
    from .rotation import DEFAULT as BOT2_SYMBOLS

    state = load_state()
    today = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date()
    if state.get("last_run") == str(today) and not args.dry_run:
        log.info("Already ran today; nothing to do.")
        return
    if not broker.market_open():
        log.info("Market closed; nothing to do.")
        return
    closes = daily_closes(symbols, cfg)
    prices = closes.iloc[-1].to_dict()
    account_qty = {p.symbol: float(p.qty) for p in broker.client.get_all_positions()}
    ledger = sleeves.load()
    shared = sleeves.budgets()
    if "5" in shared and not sleeves.ready(ledger, shared, broker.equity()):
        log.info("Waiting for the shared account to hold $%.0f for sleeves %s; nothing to do.", sum(shared.values()), shared)
        return
    budget = shared.get("5") or broker.equity()
    sleeve = sleeves.open_sleeve(ledger, "5", symbols, budget, account_qty, prices,
                                 others={"2": BOT2_SYMBOLS.split(",")})
    for problem in sleeves.check_account(ledger, account_qty):
        log.error("Sleeve mismatch: %s", problem)
    dips, bounced = signals(closes, float(os.getenv("DIP_RSI", "5")))
    held = sleeve.shares
    entered = {s: d for s, d in state.get("entered", {}).items() if s in held}
    days = {s: trading_days_since(closes.index, d) for s, d in entered.items()}
    sells, buys = plan(held, days, dips, bounced, slots, max_days)
    equity = sleeve.value(prices)
    log.info("%s close: dips %s | holding %s | bot 5 value $%.2f (cash $%.2f)", closes.index[-1].date(), dips or "none",
             {s: days.get(s, 0) for s in held} or "nothing", equity, sleeve.cash)
    for s in sells:
        log.info("SELL %s x%g (%s)", s, held[s], "bounced" if s in bounced else f"held {days.get(s)} days")
    for s in buys:
        log.info("BUY %s $%.2f", s, equity / slots)
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
        if qty >= held[s] - 1e-9:
            entered.pop(s, None)
    for s in buys:
        free_cash = float(broker.client.get_account().cash)  # never borrow: the other bot's money isn't ours either
        amount = round(min(equity / slots, sleeve.cash, free_cash) * 0.99, 2)
        if amount < 1:
            continue
        o = broker.client.submit_order(MarketOrderRequest(symbol=s, notional=amount, side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
        qty, px = sleeves.wait_fill(broker.client, o.id)
        if qty:
            sleeve.record(s, qty, px)
            entered[s] = str(closes.index[-1].date())
            done.append(f"bought {s} at ${px:.2f}")
    sleeves.save(ledger)
    STATE.write_text(json.dumps({"entered": entered, "last_run": str(today)}, indent=1))
    if done:
        send(cfg, "Bot 5 traded", "; ".join(done))

if __name__ == "__main__":
    main()
