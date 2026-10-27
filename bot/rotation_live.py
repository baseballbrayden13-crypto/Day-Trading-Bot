"""Bot 2: monthly ETF rotation on its own Alpaca PAPER account.

    python -m bot.rotation_live            # rebalances at its first run in a month it hasn't traded yet, else does nothing
    python -m bot.rotation_live --dry-run  # show what it would hold now, place nothing
    python -m bot.rotation_live --force    # rebalance today even if it's mid-month

It reads its keys from .env.rotation (run `python set_keys.py --file .env.rotation`), never
from the ORB bot's .env, so the two bots never share money. Paper only: it refuses to run
if that file turns live trading on. Schedule it once a day after 9:45am ET.

Each rebalance ranks ROTATION_SYMBOLS by their last 3 months, keeps those above their
200-day average, and holds the top 3 in equal parts (cash for empty slots), using market
orders: sells first, then buys. Writes rotation_state.json so it rebalances once a month.
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

from .rotation import DEFAULT, targets

ET = ZoneInfo("America/New_York")
ENV_FILE = Path(".env.rotation")
STATE = Path("rotation_state.json")
log = logging.getLogger("rotation")


def load_settings():
    """Settings from .env.rotation, overriding anything the ORB bot's .env set."""
    from dotenv import load_dotenv

    if not ENV_FILE.exists():
        raise SystemExit(f"{ENV_FILE} is missing. Create bot 2's paper account, then run: python set_keys.py --file {ENV_FILE}")
    for k in ("LIVE_TRADING", "LIVE_TRADING_CONFIRM", "NTFY_TOPIC"):
        os.environ.pop(k, None)  # only .env.rotation decides these for bot 2
    load_dotenv(ENV_FILE, override=True)
    from .config import Settings

    cfg = Settings()
    if cfg.live_trading or cfg.is_live:
        raise SystemExit("Bot 2 is paper only for now. Remove LIVE_TRADING from .env.rotation.")
    return cfg


BOT1_ACCOUNT = Path("bot1_account.txt")  # written by bot.live at startup: bot 1's account number (not a secret)


def ensure_own_account(broker, bot1_file: Path = BOT1_ACCOUNT) -> str:
    """Refuse to run on bot 1's account: its 3:50pm close-all and sizing would collide with this bot.
    Checks the number bot.live saved, and bot 1's keys in .env if they still work."""
    mine = broker.account_number()
    bot1 = {bot1_file.read_text().strip()} if bot1_file.exists() else set()
    try:
        from dotenv import dotenv_values
        from alpaca.trading.client import TradingClient

        main = dotenv_values(".env")
        if main.get("ALPACA_API_KEY") and main.get("ALPACA_SECRET_KEY"):
            bot1.add(str(TradingClient(main["ALPACA_API_KEY"], main["ALPACA_SECRET_KEY"], paper=True)
                         .get_account().account_number))
    except Exception:
        pass  # bot 1's keys may be stale; the saved number still protects it
    if mine in bot1:
        raise SystemExit(f"These keys open bot 1's account (...{mine[-4:]}). Make keys in a different paper account.")
    return mine


def daily_closes(symbols: list[str], cfg) -> pd.DataFrame:
    """Adjusted daily closes for the last ~14 months, finished days only."""
    from alpaca.data.enums import Adjustment
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = StockHistoricalDataClient(cfg.alpaca_key, cfg.alpaca_secret)
    today = datetime.now(ET).date()
    req = StockBarsRequest(symbol_or_symbols=symbols, timeframe=TimeFrame.Day, adjustment=Adjustment.ALL,
                           feed="iex", start=datetime.now(timezone.utc) - timedelta(days=430))
    df = client.get_stock_bars(req).df["close"].unstack(level="symbol")
    df = df[[d.tz_convert(ET).date() < today for d in df.index]]  # decide on yesterday's close
    return df.ffill()


def orders_for(want: dict[str, float], held: dict[str, int], prices: dict[str, float], equity: float) -> list[tuple[str, int]]:
    """(symbol, signed qty) to move from `held` to `want`: sells first, then buys. Whole shares only."""
    target = {s: int(equity * w // prices[s]) for s, w in want.items() if prices.get(s)}
    moves = {s: target.get(s, 0) - held.get(s, 0) for s in set(target) | set(held)}
    moves = {s: q for s, q in moves.items() if q}
    return sorted(moves.items(), key=lambda m: (m[1] > 0, m[0]))


def due(today, state: dict) -> bool:
    return state.get("last_month") != f"{today:%Y-%m}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Bot 2: monthly ETF rotation (paper)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler("rotation.log")])
    cfg = load_settings()
    symbols = [s.strip().upper() for s in os.getenv("ROTATION_SYMBOLS", DEFAULT).split(",") if s.strip()]
    from .broker import Broker
    from .notify import send

    broker = Broker(cfg)
    ensure_own_account(broker)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    today = datetime.now(ET).date()
    if not (args.force or args.dry_run or due(today, state)):
        log.info("Already rebalanced in %s; nothing to do.", f"{today:%B}")
        return
    if not args.dry_run and not broker.market_open():
        log.info("Market closed; will try at the next run.")
        return

    closes = daily_closes(symbols, cfg)
    want = targets(closes, top=3, lookback=3)
    prices = closes.iloc[-1].to_dict()
    held = {p.symbol: int(float(p.qty)) for p in broker.client.get_all_positions()}
    equity = broker.equity()
    moves = orders_for(want, held, prices, equity)
    plan = ", ".join(f"{s} {w:.0%}" for s, w in want.items()) or "all cash"
    log.info("Target on %s close: %s | equity $%.2f", closes.index[-1].date(), plan, equity)
    for sym, qty in moves:
        log.info("%s %s x%d", "BUY" if qty > 0 else "SELL", sym, abs(qty))
    if args.dry_run:
        return

    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest

    for sym, qty in moves:
        side = OrderSide.BUY if qty > 0 else OrderSide.SELL
        broker.client.submit_order(MarketOrderRequest(symbol=sym, qty=abs(qty), side=side, time_in_force=TimeInForce.DAY))
    STATE.write_text(json.dumps({"last_month": f"{today:%Y-%m}", "holding": want, "at": datetime.now(ET).isoformat()}))
    send(cfg, "Bot 2 rebalanced", f"Now holding {plan}. {len(moves)} orders.")


if __name__ == "__main__":
    main()
