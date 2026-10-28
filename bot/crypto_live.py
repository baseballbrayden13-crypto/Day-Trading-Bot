"""Bot 3: crypto trend on its own Alpaca PAPER account.

    python -m bot.crypto_live            # once a day: buy or sell when a coin crosses its average
    python -m bot.crypto_live --dry-run  # show what it would hold now, place nothing

Holds each coin in CRYPTO_SYMBOLS (default BTC/USD and ETH/USD) with an equal share of the
account while its last daily close is above its CRYPTO_MA-day average (default 50), and
cash otherwise. In the 12-year test (bot.daily_rules) 30-50 days was the robust range:
for ETH it beat buy-and-hold, for BTC it mainly halved the worst drop. Expect -40% to -60%
drops at times anyway; crypto is far riskier than stocks.

Keys come from .env.crypto (python set_keys.py --file .env.crypto), never the ORB bot's
.env. Paper only. Crypto trades every day, so schedule it once a day, e.g. 8:15pm ET,
just after the UTC daily bar closes. It only trades when a coin flips in or out.
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ENV_FILE = Path(".env.crypto")
log = logging.getLogger("crypto")


def load_settings():
    from .rotation_live import load_settings as _load
    from . import rotation_live

    old, rotation_live.ENV_FILE = rotation_live.ENV_FILE, ENV_FILE
    try:
        return _load()  # same rules as bot 2: its own keys, paper only
    finally:
        rotation_live.ENV_FILE = old


def want(closes: pd.DataFrame, ma: int) -> dict[str, float]:
    """Equal share for every coin whose last close is above its `ma`-day average."""
    if len(closes) < ma:
        return {}
    last, avg = closes.iloc[-1], closes.iloc[-ma:].mean()
    share = 1 / len(closes.columns)
    return {s: share for s in closes.columns if pd.notna(avg[s]) and last[s] > avg[s]}


def plan(target: dict[str, float], held: dict[str, float], equity: float) -> list[tuple[str, str, float]]:
    """Orders as (symbol, "sell"|"buy", amount): sell the whole coin when it leaves, buy $ notional when it
    enters. Coins that stay are left alone, so the bot only trades when the trend flips."""
    sells = [(s, "sell", q) for s, q in sorted(held.items()) if s not in target and q > 0]
    buys = [(s, "buy", round(equity * w, 2)) for s, w in sorted(target.items()) if held.get(s, 0) <= 0]
    return sells + buys


def daily_closes(symbols: list[str]) -> pd.DataFrame:
    """Finished daily closes (UTC days). Alpaca's crypto data needs no keys."""
    from alpaca.data.historical import CryptoHistoricalDataClient
    from alpaca.data.requests import CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame

    bars = CryptoHistoricalDataClient().get_crypto_bars(CryptoBarsRequest(
        symbol_or_symbols=symbols, timeframe=TimeFrame.Day,
        start=datetime.now(timezone.utc) - timedelta(days=400))).df
    closes = bars["close"].unstack(level="symbol")
    today = datetime.now(timezone.utc).date()
    return closes[[d.date() < today for d in closes.index]].ffill()  # drop today's unfinished bar


def main() -> None:
    ap = argparse.ArgumentParser(description="Bot 3: crypto trend (paper)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler("crypto.log")])
    cfg = load_settings()
    symbols = [s.strip().upper() for s in os.getenv("CRYPTO_SYMBOLS", "BTC/USD,ETH/USD").split(",") if s.strip()]
    ma = int(os.getenv("CRYPTO_MA", "50"))
    from .broker import Broker
    from .notify import send

    broker = Broker(cfg)
    from .rotation_live import ensure_own_account

    ensure_own_account(broker)
    closes = daily_closes(symbols)
    target = want(closes, ma)
    # Alpaca reports crypto positions as e.g. BTCUSD; map them back to BTC/USD
    names = {s.replace("/", ""): s for s in symbols}
    held = {names.get(p.symbol, p.symbol): float(p.qty) for p in broker.client.get_all_positions()}
    equity = broker.equity()
    orders = plan(target, held, equity)
    status = ", ".join(f"{s} {'above' if s in target else 'below'} its {ma}-day average" for s in symbols)
    log.info("%s close: %s | equity $%.2f", closes.index[-1].date(), status, equity)
    for sym, side, amount in orders:
        log.info("%s %s %s", side.upper(), sym, f"${amount:,.2f}" if side == "buy" else f"{amount:g} (all)")
    if args.dry_run or not orders:
        return

    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest

    for sym, side, amount in orders:
        if side == "sell":
            broker.client.close_position(sym.replace("/", ""))
        else:
            broker.client.submit_order(MarketOrderRequest(symbol=sym, notional=amount, side=OrderSide.BUY,
                                                          time_in_force=TimeInForce.GTC))
    send(cfg, "Bot 3 traded", "; ".join(f"{side} {sym}" for sym, side, _ in orders) + f". {status}.")


if __name__ == "__main__":
    main()
