"""Paper trading loop. Run during market hours:  python -m bot.live

Every bar it: refreshes data, checks risk limits, exits on trend breaks,
looks for new entries, optionally asks Claude to review them, then places
bracket orders. Everything is logged to trades.log.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .broker import Broker
from .config import Settings
from .data import from_alpaca
from .fills import log_order
from .risk import RiskManager
from .strategy import add_indicators, entry_signal, exit_on_trend_break, get_strategy, market_ok

ET = ZoneInfo("America/New_York")
log = logging.getLogger("bot")


def seconds_to_next_bar(minutes: int) -> float:
    now = time.time()
    period = minutes * 60
    return period - (now % period) + 5  # a few seconds after the bar closes


def run_once(cfg: Settings, broker: Broker, risk: RiskManager, reviewer=None) -> None:
    now_et = datetime.now(ET)
    equity = broker.equity()
    if risk.day != now_et.date():
        risk.new_day(now_et.date(), equity)
        log.info("New day %s, starting equity $%.2f", now_et.date(), equity)

    risk.open_symbols = broker.open_symbols()  # broker is the source of truth
    risk.check_daily_loss(equity)

    if risk.halted or risk.must_flatten(now_et):
        if risk.open_symbols:
            log.info("Flattening all positions: %s", risk.halt_reason or "end of day")
            broker.close_all()
        return

    allow_entries = True
    if cfg.market_filter:
        mkt = from_alpaca(cfg.market_filter, days=5, cfg=cfg, realtime=True)
        allow_entries = market_ok(add_indicators(mkt, cfg) if not mkt.empty else None)

    for sym in cfg.symbols:
        bars = from_alpaca(sym, days=5, cfg=cfg, realtime=True)
        if bars.empty:
            continue
        bars = add_indicators(bars, cfg)

        if sym in risk.open_symbols:
            if exit_on_trend_break(bars, cfg):
                log.info("EXIT %s: trend break", sym)
                broker.close(sym)
            continue

        if not allow_entries:
            continue
        ok, why = risk.can_enter(sym, now_et)
        if not ok:
            continue
        sig = entry_signal(sym, bars, cfg)
        if sig is None:
            continue
        if reviewer is not None:
            approved, note = reviewer.review(sig, bars)
            log.info("%s %s", sym, note)
            if not approved:
                continue
        qty = risk.position_size(equity, sig.price, sig.stop)
        if qty <= 0:
            continue
        log.info("BUY %s x%d @~%.2f stop %.2f target %.2f | %s", sym, qty, sig.price, sig.stop, sig.target, sig.reason)
        order = broker.buy_bracket(sym, qty, sig.stop, sig.target)
        risk.record_entry(sym)
        try:
            log_order(sym, qty, sig.price, sig.stop, sig.target, str(order.id))
        except Exception:
            log.exception("Could not log %s to the fill tracker", sym)


def keep_awake() -> None:
    """On Windows, stop the PC from going back to sleep while the bot runs."""
    import sys

    if sys.platform == "win32":
        import ctypes

        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def main() -> None:
    keep_awake()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler("trades.log")],
    )
    cfg = Settings()
    if get_strategy(cfg.strategy).short:
        raise SystemExit(f"{cfg.strategy} is backtest only for now; the live bot can't place short orders yet.")
    broker = Broker(cfg)
    risk = RiskManager(cfg)
    reviewer = None
    if cfg.ai_review:
        from .ai_review import AIReviewer

        reviewer = AIReviewer(cfg)
        log.info("Claude trade review ON (%s)", cfg.ai_model)

    log.info("Watching %s on %d-min bars. Ctrl+C to stop.", ", ".join(cfg.symbols), cfg.bar_minutes)
    while True:
        try:
            if broker.market_open():
                run_once(cfg, broker, risk, reviewer)
            time.sleep(seconds_to_next_bar(cfg.bar_minutes))
        except KeyboardInterrupt:
            log.info("Stopped. Open positions keep their stop-loss and take-profit orders at Alpaca.")
            break
        except Exception:
            log.exception("Error in loop; retrying next bar")
            time.sleep(60)


if __name__ == "__main__":
    main()
