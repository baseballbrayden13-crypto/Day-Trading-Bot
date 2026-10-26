"""Bar-by-bar backtester using the same strategy and risk code as the live bot.

Signals are computed on a bar's close and filled at the NEXT bar's open plus
slippage, so the backtest never trades on information it wouldn't have had.
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Settings
from .data import load_bars
from .risk import RiskManager
from .strategy import add_indicators, entry_signal, exit_on_trend_break, market_ok


@dataclass
class Position:
    symbol: str
    qty: int
    entry: float
    stop: float
    target: float
    entry_time: pd.Timestamp


def sell_fees(qty: int, price: float, cfg: Settings) -> float:
    """SEC fee on the sale value plus the FINRA trading activity fee (capped), both charged on sells."""
    return qty * price * cfg.sec_fee_rate + min(qty * cfg.taf_per_share, cfg.taf_max)


def run_backtest(
    frames: dict[str, pd.DataFrame], cfg: Settings, starting_cash: float = 25_000,
    market: pd.DataFrame | None = None,
) -> dict:
    data = {s: add_indicators(df, cfg) for s, df in frames.items() if not df.empty}
    if cfg.market_filter and market is None:
        market = frames.get(cfg.market_filter)
    mkt = add_indicators(market, cfg) if cfg.market_filter and market is not None and not market.empty else None
    times = sorted(set().union(*[df.index for df in data.values()])) if data else []
    risk = RiskManager(cfg)
    cash = starting_cash
    positions: dict[str, Position] = {}
    pending: dict[str, object] = {}  # symbol -> Signal waiting for next open
    trades: list[dict] = []
    equity_curve: list[tuple[pd.Timestamp, float]] = []
    slip = cfg.slippage_bps / 10_000

    def mark(t) -> float:
        val = cash
        for p in positions.values():
            df = data[p.symbol]
            px = df.loc[:t, "close"].iloc[-1]
            val += p.qty * px
        return val

    def close(p: Position, px: float, t, why: str):
        nonlocal cash
        fill = px * (1 - slip)
        fees = sell_fees(p.qty, fill, cfg)
        cash += p.qty * fill - p.qty * cfg.commission_per_share - fees
        trades.append({
            "symbol": p.symbol, "entry_time": p.entry_time, "exit_time": t, "qty": p.qty,
            "entry": p.entry, "exit": fill,
            "pnl": p.qty * (fill - p.entry) - 2 * p.qty * cfg.commission_per_share - fees,
            "fees": fees + 2 * p.qty * cfg.commission_per_share,
            "exit_reason": why,
        })
        risk.record_exit(p.symbol)
        del positions[p.symbol]

    for t in times:
        now_et = t.tz_convert("America/New_York")
        if risk.day != now_et.date():
            risk.new_day(now_et.date(), mark(t))

        for sym, df in data.items():
            if t not in df.index:
                continue
            bar = df.loc[t]

            # 1. fill entries signalled on the previous bar
            sig = pending.pop(sym, None)
            if sig is not None and sym not in positions:
                fill = bar["open"] * (1 + slip)
                qty = risk.position_size(mark(t), fill, sig.stop)
                if qty > 0 and qty * fill <= cash:
                    cash -= qty * fill + qty * cfg.commission_per_share
                    positions[sym] = Position(sym, qty, fill, sig.stop, sig.target, t)
                    risk.record_entry(sym)

            # 2. manage open position: stop first (conservative), then target
            p = positions.get(sym)
            if p is not None:
                if bar["low"] <= p.stop:
                    close(p, min(p.stop, bar["open"]), t, "stop")
                elif bar["high"] >= p.target:
                    close(p, max(p.target, bar["open"]), t, "target")
                elif risk.must_flatten(now_et):
                    close(p, bar["close"], t, "end of day")
                elif exit_on_trend_break(df.loc[:t], cfg):
                    close(p, bar["close"], t, "trend break")

        risk.check_daily_loss(mark(t))
        if risk.halted:
            for p in list(positions.values()):
                close(p, data[p.symbol].loc[:t, "close"].iloc[-1], t, "daily loss halt")

        # 3. look for new entries on this bar's close
        if cfg.market_filter and not market_ok(mkt.loc[:t] if mkt is not None else None):
            equity_curve.append((t, mark(t)))
            continue
        for sym, df in data.items():
            if t not in df.index or sym in positions:
                continue
            ok, _ = risk.can_enter(sym, now_et)
            if not ok:
                continue
            sig = entry_signal(sym, df.loc[:t], cfg)
            if sig is not None:
                pending[sym] = sig

        equity_curve.append((t, mark(t)))

    # close anything left at the final price
    for p in list(positions.values()):
        close(p, data[p.symbol]["close"].iloc[-1], times[-1], "end of test")

    return summarize(trades, equity_curve, starting_cash)


def summarize(trades: list[dict], curve: list, starting_cash: float) -> dict:
    tdf = pd.DataFrame(trades)
    eq = pd.Series([v for _, v in curve], index=[t for t, _ in curve], dtype=float)
    final = eq.iloc[-1] if len(eq) else starting_cash
    dd = ((eq / eq.cummax()) - 1).min() if len(eq) else 0.0
    wins = tdf[tdf["pnl"] > 0] if len(tdf) else tdf
    losses = tdf[tdf["pnl"] <= 0] if len(tdf) else tdf
    gross_win = wins["pnl"].sum() if len(wins) else 0.0
    gross_loss = -losses["pnl"].sum() if len(losses) else 0.0
    return {
        "trades": len(tdf),
        "win_rate": len(wins) / len(tdf) if len(tdf) else 0.0,
        "profit_factor": gross_win / gross_loss if gross_loss else float("inf") if gross_win else 0.0,
        "total_return": final / starting_cash - 1,
        "max_drawdown": float(dd),
        "final_equity": float(final),
        "avg_trade": float(tdf["pnl"].mean()) if len(tdf) else 0.0,
        "fees": float(tdf["fees"].sum()) if len(tdf) else 0.0,
        "trade_log": tdf,
        "equity_curve": eq,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest the day trading strategy")
    ap.add_argument("--days", type=int, default=59)
    ap.add_argument("--source", default="yfinance", help="yfinance, alpaca, or a path to a .csv")
    ap.add_argument("--cash", type=float, default=25_000)
    ap.add_argument("--symbols", default=None, help="comma list; defaults to SYMBOLS from .env")
    ap.add_argument("--out", default="backtest_trades.csv")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = Settings()
    symbols = args.symbols.split(",") if args.symbols else cfg.symbols
    frames = {s: load_bars(s, args.days, cfg, args.source) for s in symbols}
    empty = [s for s, df in frames.items() if df.empty]
    if len(empty) == len(frames):
        raise SystemExit("No price data loaded. Check your internet connection or try --source alpaca.")
    if empty:
        print(f"No data for: {', '.join(empty)} (skipped)")
    market = None
    if cfg.market_filter:
        market = frames.get(cfg.market_filter)
        if market is None:
            market = load_bars(cfg.market_filter, args.days, cfg, args.source)
    res = run_backtest(frames, cfg, args.cash, market)

    print(f"\nSymbols: {', '.join(symbols)} | {args.days} days of {cfg.bar_minutes}-min bars")
    if cfg.market_filter:
        print(f"Market filter:  only buy when {cfg.market_filter} is above its VWAP")
    print(f"Trades:         {res['trades']}")
    print(f"Win rate:       {res['win_rate']:.1%}")
    print(f"Profit factor:  {res['profit_factor']:.2f}")
    print(f"Total return:   {res['total_return']:+.2%}")
    print(f"Max drawdown:   {res['max_drawdown']:.2%}")
    print(f"Avg trade P&L:  ${res['avg_trade']:,.2f}  (after fees and {cfg.slippage_bps:g} bps slippage each way)")
    print(f"Fees paid:      ${res['fees']:,.2f}")
    print(f"Final equity:   ${res['final_equity']:,.2f}")
    if res["trades"] < 30:
        print("\nWarning: fewer than 30 trades. This result says almost nothing yet.")
    if len(res["trade_log"]):
        res["trade_log"].to_csv(args.out, index=False)
        print(f"Trade log written to {args.out}")


if __name__ == "__main__":
    main()
