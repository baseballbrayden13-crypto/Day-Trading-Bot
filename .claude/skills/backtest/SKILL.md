---
name: backtest
description: Run and report a backtest of the day trading bot. Use when the user asks to backtest, test a strategy or setting on past data, or asks how the bot would have done historically.
---

# Backtest the bot

Run from the repo root with the project's venv:

```bash
.venv/Scripts/python -m bot.backtest --source alpaca --days 180 --out backtest_trades_alpaca_180d.csv
```

Options (see `main()` in `bot/backtest.py`):

| Flag | Default | Notes |
|---|---|---|
| `--source` | `yfinance` | `alpaca` (needs keys in `.env`, goes back years), `yfinance` (no keys, ~60 days max), or a path to a `.csv` |
| `--days` | `59` | Use `--source alpaca` for anything over 59 |
| `--symbols` | `SYMBOLS` in `.env` | Comma list, e.g. `SPY,QQQ,NVDA` |
| `--cash` | `25000` | Starting equity |
| `--out` | `backtest_trades.csv` | Trade-by-trade CSV: `symbol,entry_time,exit_time,qty,entry,exit,pnl,exit_reason` |

To compare every strategy on the same data in one table, run `.venv/Scripts/python -m bot.compare --source alpaca --days 180 --cash 5000` (same flags, plus `--strategies` to pick a subset). brayden's paper account is $5,000, so pass `--cash 5000`.

Strategy and risk settings come from `.env` through `bot/config.py` (`STRATEGY`, `ORB_*`, `EMA_*`, `STOP_ATR`, `TARGET_ATR`, `MARKET_FILTER`, `SLIPPAGE_BPS`, ...). To try a setting without editing `.env`, set it as an environment variable for one run only, e.g. `STRATEGY=orb ORB_TARGET_R=1 .venv/Scripts/python -m bot.backtest ...`. Never edit `.env` itself.

Default to `--out` names that don't overwrite earlier results the user may want to keep (e.g. `backtest_trades_<label>.csv`).

## Reporting the result

Always report, in this order:

1. **Trade count.** Under 30 trades: say plainly the result is noise and proves nothing. Under 100: call it preliminary.
2. **Profit factor.** Below 1.0 loses money; below 1.3 is not good enough to take seriously after costs.
3. **Win rate, total return and max drawdown**, with return compared against drawdown.
4. **Settings used**: source, days, symbols, strategy, and any env overrides.

Also mention:
- If `SLIPPAGE_BPS` is 0, the result is optimistic.
- Expect paper/live results to be worse than the backtest.
- Free Alpaca data is IEX-only, so VWAP and volume are approximate.

To dig deeper, load the `--out` CSV with pandas and break P&L down by `symbol`, `exit_reason`, and time of day of `entry_time`.

Do not tune settings over and over on the same period to make the numbers look better. If the user wants to tune, follow the `strategy-change` skill.
