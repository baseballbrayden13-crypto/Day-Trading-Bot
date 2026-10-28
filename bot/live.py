"""Paper trading loop. Run during market hours:  python -m bot.live

Every bar it: refreshes data, checks risk limits, exits on trend breaks,
looks for new entries, optionally asks Claude to review them, then places
bracket orders. Everything is logged to trades.log.

On GitHub (jobs stop at 6 hours) the day is split into two runs:
    python -m bot.live --start-window 08:30-12:00 --until 12:40
    python -m bot.live --start-window 12:00-15:50 --until 16:05
A run started outside its window exits at once. The day's starting equity, trade count and halt
are saved in risk_state.json, so the second run picks up where the first stopped.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .broker import Broker
from .config import Settings
from .data import from_alpaca
from .fills import log_order
from .notify import send
from .risk import RiskManager
from .strategy import add_indicators, entry_signal, exit_on_trend_break, get_strategy, market_ok

ET = ZoneInfo("America/New_York")
log = logging.getLogger("bot")
RISK_STATE = Path("risk_state.json")


def hhmm(text: str) -> tuple[int, int]:
    h, m = text.split(":")
    return int(h), int(m)


def in_window(now_et: datetime, window: str) -> bool:
    lo, hi = (hhmm(x) for x in window.split("-"))
    return lo <= (now_et.hour, now_et.minute) < hi


def save_risk(risk: RiskManager, path: Path = RISK_STATE) -> None:
    if risk.day:
        path.write_text(json.dumps({"day": risk.day.isoformat(), "start_equity": risk.start_equity,
                                    "trades_today": risk.trades_today, "halted": risk.halted, "halt_reason": risk.halt_reason}))


def load_risk(risk: RiskManager, today: date, path: Path = RISK_STATE) -> bool:
    """Restore today's counters from an earlier run; a file from another day is ignored."""
    try:
        s = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if s.get("day") != today.isoformat():
        return False
    risk.day, risk.start_equity, risk.trades_today = today, float(s["start_equity"]), int(s["trades_today"])
    risk.halted, risk.halt_reason = bool(s.get("halted")), s.get("halt_reason", "")
    return True


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

    if cfg.entry_limit_bps >= 0:
        for sym in broker.cancel_unfilled_entries():
            log.info("Cancelled unfilled limit entry for %s", sym)
    was_open = risk.open_symbols
    risk.open_symbols = broker.open_symbols()  # broker is the source of truth
    for sym in sorted(was_open - risk.open_symbols):  # its stop or target filled at Alpaca
        send(cfg, f"Closed {sym}", f"{sym} is no longer open (its stop or target filled). Equity ${equity:,.2f}")
    was_halted = risk.halted
    risk.check_daily_loss(equity)
    if risk.halted and not was_halted:
        send(cfg, "Bot halted for the day", risk.halt_reason, priority="high")

    if risk.halted or risk.must_flatten(now_et):
        if risk.open_symbols:
            log.info("Flattening all positions: %s", risk.halt_reason or "end of day")
            broker.close_all()
            send(cfg, "Closed everything", f"{', '.join(sorted(risk.open_symbols))}: {risk.halt_reason or 'end of day'}")
            risk.open_symbols = set()
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
                risk.open_symbols.discard(sym)
                send(cfg, f"Closed {sym}", f"{sym} closed by the bot: trend break")
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
        limit = sig.price * (1 + cfg.entry_limit_bps / 10_000) if cfg.entry_limit_bps >= 0 else None
        log.info("BUY %s x%d @%s%.2f stop %.2f target %.2f | %s", sym, qty, "limit " if limit else "~",
                 limit or sig.price, sig.stop, sig.target, sig.reason)
        order = broker.buy_bracket(sym, qty, sig.stop, sig.target, limit)
        risk.record_entry(sym)
        send(cfg, f"Bought {sym}", f"{qty} x {sym} @ ~${sig.price:.2f}, stop ${sig.stop:.2f}, target ${sig.target:.2f}")
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
    ap = argparse.ArgumentParser(description="Bot 1 paper trading loop")
    ap.add_argument("--start-window", default="", help="ET HH:MM-HH:MM; started outside it, exit at once")
    ap.add_argument("--until", default="", help="stop at this ET time (open positions keep their bracket orders)")
    args = ap.parse_args()
    if args.start_window and not in_window(datetime.now(ET), args.start_window):
        print(f"{datetime.now(ET):%H:%M} ET is outside this run's start window {args.start_window}; nothing to do.")
        return
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
    try:  # lets bots 2 and 3 refuse to run on this account
        Path("bot1_account.txt").write_text(broker.account_number())
    except Exception:
        log.exception("Could not record the account number")
    risk = RiskManager(cfg)
    if load_risk(risk, datetime.now(ET).date()):
        log.info("Picked up today's counters: start equity $%.2f, %d trades%s", risk.start_equity, risk.trades_today,
                 ", halted" if risk.halted else "")
    reviewer = None
    if cfg.ai_review:
        from .ai_review import AIReviewer

        reviewer = AIReviewer(cfg)
        log.info("Claude trade review ON (%s)", cfg.ai_model)

    log.info("Watching %s on %d-min bars. Ctrl+C to stop.", ", ".join(cfg.symbols), cfg.bar_minutes)
    send(cfg, "Bot started", f"Paper bot watching {', '.join(cfg.symbols)} ({cfg.strategy})")
    until = hhmm(args.until) if args.until else None
    while True:
        try:
            if until and (datetime.now(ET).hour, datetime.now(ET).minute) >= until:
                log.info("Run over at %s ET; positions keep their stop-loss and take-profit orders at Alpaca.", args.until)
                break
            if broker.market_open():
                run_once(cfg, broker, risk, reviewer)
                save_risk(risk)
            time.sleep(seconds_to_next_bar(cfg.bar_minutes))
        except KeyboardInterrupt:
            log.info("Stopped. Open positions keep their stop-loss and take-profit orders at Alpaca.")
            break
        except Exception as e:
            log.exception("Error in loop; retrying next bar")
            send(cfg, "Bot error", f"{type(e).__name__}: {e}"[:300], priority="high")
            time.sleep(60)


if __name__ == "__main__":
    main()
