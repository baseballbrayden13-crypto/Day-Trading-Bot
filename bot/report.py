"""Weekly paper-trading report:  python -m bot.report [--days 7] [--open]

Pulls filled orders from Alpaca, pairs buys with sells into round trips,
counts Claude reviewer approvals/rejections from trades.log, and compares
the week with what the 3-year backtest expects. Writes reports/weekly_<date>.txt.
"""
from __future__ import annotations

import argparse
import re
import subprocess
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .broker import Broker
from .config import Settings

ET = ZoneInfo("America/New_York")
# Tuned ORB (1.5R, SPY filter, gap-down days, 2/day, entries by 11:30), Oct 2023 - Oct 2026: 839 trades.
BACKTEST = {"win_rate": 0.51, "profit_factor": 1.30, "trades_per_day": 1.1}


def filled_orders(broker: Broker, since: datetime) -> list:
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest

    orders = broker.client.get_orders(
        GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=since, limit=500, nested=True, direction="asc")
    )
    flat = []
    for o in orders:
        flat.append(o)
        flat.extend(o.legs or [])
    return sorted((o for o in flat if o.filled_at and float(o.filled_qty or 0) > 0), key=lambda o: o.filled_at)


def exit_kind(o) -> str:
    t = str(o.order_type).lower()
    if "stop" in t:
        return "stop"
    if "limit" in t:
        return "target"
    return "closed by bot"


def round_trips(orders: list) -> list[dict]:
    """FIFO-pair buys and sells per symbol (the bot is long only)."""
    open_lots: dict[str, deque] = defaultdict(deque)
    trips = []
    for o in orders:
        qty, px = float(o.filled_qty), float(o.filled_avg_price)
        if "buy" in str(o.side).lower():
            open_lots[o.symbol].append([qty, px, o.filled_at])
            continue
        while qty > 0 and open_lots[o.symbol]:
            lot = open_lots[o.symbol][0]
            q = min(qty, lot[0])
            trips.append({"symbol": o.symbol, "entry_time": lot[2], "exit_time": o.filled_at, "qty": q,
                          "entry": lot[1], "exit": px, "pnl": q * (px - lot[1]), "exit_reason": exit_kind(o)})
            lot[0] -= q
            qty -= q
            if lot[0] <= 0:
                open_lots[o.symbol].popleft()
    return trips


def ai_counts(log_path: Path, since: datetime) -> tuple[int, int, list[str]]:
    approved = rejected = 0
    reasons = []
    if not log_path.exists():
        return 0, 0, reasons
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if not m or datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=ET) < since:
            continue
        if "AI approved" in line:
            approved += 1
        elif "AI rejected" in line or "AI review error" in line:
            rejected += 1
            reasons.append(line.split(" ", 3)[-1].strip())  # drop date, time, level
    return approved, rejected, reasons


def build(cfg: Settings, days: int) -> str:
    broker = Broker(cfg)
    now = datetime.now(ET)
    since = now - timedelta(days=days)
    trips = round_trips(filled_orders(broker, since.astimezone(timezone.utc)))
    approved, rejected, reasons = ai_counts(Path("trades.log"), since)
    trading_days = sum((since + timedelta(days=i)).weekday() < 5 for i in range(1, days + 1))

    wins = [t for t in trips if t["pnl"] > 0]
    gross_w = sum(t["pnl"] for t in wins)
    gross_l = -sum(t["pnl"] for t in trips if t["pnl"] <= 0)
    pf = gross_w / gross_l if gross_l else (float("inf") if gross_w else 0.0)
    total = sum(t["pnl"] for t in trips)

    out = [f"Trading bot weekly report  |  {since:%b %d} to {now:%b %d, %Y}  |  PAPER account", ""]
    out.append(f"Account equity now: ${broker.equity():,.2f}")
    out.append(f"Profit/loss from closed trades this period: ${total:+,.2f}")
    out.append("")
    out.append(f"{'':28}{'This period':>14}{'Backtest expects':>18}")
    out.append(f"{'Trades':28}{len(trips):>14}{BACKTEST['trades_per_day'] * trading_days:>18.0f}")
    out.append(f"{'Win rate':28}{(len(wins) / len(trips) if trips else 0):>14.0%}{BACKTEST['win_rate']:>18.0%}")
    out.append(f"{'Profit factor (>1 = profit)':28}{pf:>14.2f}{BACKTEST['profit_factor']:>18.2f}")
    out.append("")
    out.append(f"Claude reviewer: approved {approved}, rejected {rejected}")
    for r in reasons[-5:]:
        out.append(f"  - {r[:160]}")
    out.append("")
    if trips:
        out.append("Trades:")
        for t in trips:
            out.append(f"  {t['entry_time'].astimezone(ET):%a %m/%d %H:%M}  {t['symbol']:<5} x{t['qty']:<5.0f} "
                       f"{t['entry']:>8.2f} -> {t['exit']:>8.2f}  {t['pnl']:>+9.2f}  ({t['exit_reason']})")
    else:
        out.append("No closed trades this period.")
    out.append("")
    if len(trips) < 30:
        out.append("Note: under 30 trades says very little. Judge it after a month or more.")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Weekly paper-trading report")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--open", action="store_true", help="open the report in Notepad")
    args = ap.parse_args()
    text = build(Settings(), args.days)
    Path("reports").mkdir(exist_ok=True)
    path = Path("reports") / f"weekly_{datetime.now(ET):%Y-%m-%d}.txt"
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nSaved to {path.resolve()}")
    if args.open:
        subprocess.Popen(["notepad.exe", str(path.resolve())])


if __name__ == "__main__":
    main()
