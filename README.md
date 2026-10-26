# Day Trading Bot (Alpaca paper trading)

A Python bot that watches a few stocks on 5-minute bars, finds trend-following
entries, sizes each trade so a stop-out loses about 0.5% of the account, and
places bracket orders (stop-loss + take-profit attached) on an **Alpaca paper
account**. An optional Claude reviewer can veto setups before they're placed.

> **Read this first.** Most day traders lose money, and no bot guarantees
> profit. This bot is a tool for testing ideas safely. Paper trade for at least
> a couple of months, and only consider real money if the paper results are
> consistently positive after costs over 100+ trades.

## How it works

| Part | File | What it does |
|---|---|---|
| Strategies | `bot/strategy.py` | Four plug-in strategies, picked with `STRATEGY` in `.env` (see below). |
| Compare | `bot/compare.py` | Backtests every strategy on the same data and prints them side by side. |
| Risk | `bot/risk.py` | ~0.5% risk per trade, max 20% of equity per position, max 3 positions, max 10 trades/day, **stops for the day at −2%**, no entries in the first 15 min, **flat 10 min before the close** (no overnight holds). |
| AI review | `bot/ai_review.py` | Optional. Claude sees the last 30 bars and approves or rejects each signal. It can only say no to a trade, never invent one. If the call fails, the trade is skipped. |
| Backtest | `bot/backtest.py` | Replays history bar by bar with the same strategy and risk code. Fills at the next bar's open plus slippage, so it can't cheat with future data. Charges Alpaca's sell-side regulatory fees (SEC fee and FINRA TAF). |
| Paper loop | `bot/live.py` | Runs during market hours, checks every 5 minutes, logs to `trades.log`. |
| Broker | `bot/broker.py` | Alpaca API. Paper unless you deliberately set two separate live flags. |

## Strategies

| `STRATEGY=` | Entry | Exit |
|---|---|---|
| `ema_cross` (default) | EMA 9 crosses above EMA 21, price above VWAP, RSI 50–70 | Stop 1.5×ATR below, target 3×ATR above, or EMAs cross back down |
| `orb` | First close above the opening range high | Stop at the range low, target `ORB_TARGET_R`× the risk |
| `vwap_reversion` | Price closes `VWAP_REV_ATR` ATRs below VWAP with RSI under `VWAP_REV_RSI` | Target VWAP, stop 1.5×ATR below |
| `bollinger` | Close crosses back above the lower Bollinger band (20, 2) | Target the middle band, stop 1.5×ATR below |
| `pdh_break` | First close above yesterday's high | Stop 1.5×ATR below, target 3×ATR above |
| `gap_reversal` | Opens `GAP_MIN_PCT`% or more below yesterday's close, then closes back above today's open | Target yesterday's close (gap fill), stop 1.5×ATR below |
| `vwap_pullback` | Fast EMA above slow EMA, bar dips to VWAP and closes green above it | Stop 1.5×ATR below, target 3×ATR above |
| `rsi2` | RSI(2) under 10 while above the slow EMA | RSI(2) back over 70, or stop/target |

ORB also has optional filters, all off by default: `ORB_STOP=mid` (tighter
stop), `ORB_VWAP_FILTER`, `ORB_VOLUME_MULT`, `ORB_MAX_RANGE_PCT` and `ORB_GAP`.
See `.env.example`.

To add one, write an entry function in `bot/strategy.py` that returns a
`Signal` (or `None`) and add it to `STRATEGIES` at the bottom of the file. The
backtest, the paper loop and the compare command all pick it up.

Compare them on the same data (use your real account size for `--cash`):

```bash
python -m bot.compare --source alpaca --days 180 --cash 5000
```

For a deeper look, `bot.research` tests each ORB filter on its own, keeps only
the ones that help on the older two thirds of the history, then checks the
result on the most recent third, which it never tuned on. It also runs every
strategy on the same split. Bars are cached in `data_cache/`, and the report is
saved to `reports/research_<date>.md`. Nothing in `.env` is changed.

```bash
python -m bot.research --source alpaca --days 1095 --cash 5000
```

## Setup (about 10 minutes)

1. **Install Python 3.11+**, then in this folder:
   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. **Get Alpaca paper keys:** sign up free at https://app.alpaca.markets, make
   sure the account switcher (top left) says **Paper**, then generate API keys.
3. `cp .env.example .env` and paste your keys into `.env`.
4. **Backtest:**
   ```bash
   python -m bot.backtest --source alpaca --days 180 --cash 5000
   ```
   (`--source yfinance` also works with no keys, but only goes back ~60 days.)
5. **Paper trade** (leave it running during market hours, 9:30–4:00 ET):
   ```bash
   python -m bot.live
   ```
   Watch fills and P&L in the Alpaca paper dashboard.
6. **Optional Claude review:** set `AI_REVIEW=true` and `ANTHROPIC_API_KEY` in
   `.env`. Each signal costs one API call.

Run the tests with `python -m pytest`.

## Reading backtest results

- **Trades:** under 30 means the numbers are noise. Aim for 100+.
- **Profit factor:** gross wins ÷ gross losses. Below 1.0 loses money. You
  want 1.3+ after costs before taking it seriously.
- **Costs:** every result is after 2 bps slippage on each fill and the
  regulatory fees Alpaca charges on sells (`SEC_FEE_RATE`, `TAF_PER_SHARE`).
  Alpaca charges no commission on stocks. Check the current fee rates at
  https://alpaca.markets/support/regulatory-fees and update `.env` if they change.
- **Max drawdown:** the worst peak-to-trough drop. Expect live results to be
  worse than the backtest.
- **Don't over-tune.** If you tweak settings until the backtest looks great,
  you've usually just fit the past. Test changes on a time period you didn't
  tune on.

On random price data the default strategy loses about 3% over 40 days (246
trades, profit factor 0.76). That's what you'd expect with no edge, because
slippage eats a little on every trade. Real market data is where you find out
whether it does better than that.

## Things to know

- **Pattern day trader rule:** in a US margin account under $25k, 4+ day trades
  in 5 business days can get you restricted. Paper accounts don't enforce it,
  so check the current rule with your broker before going live.
- **Free data is IEX-only.** It's fine for testing but is a slice of total
  volume, so VWAP and volume are approximate.
- If the program crashes, open positions still have their stop-loss and
  take-profit orders sitting at Alpaca, but the end-of-day flatten won't run.
  Check the dashboard before the close.
- **Going live** needs `LIVE_TRADING=true` *and*
  `LIVE_TRADING_CONFIRM=I_UNDERSTAND_REAL_MONEY`, plus your *live* account
  keys. Don't flip these without a long, positive paper record.

## Ideas to try next

- Add a market filter (only trade long when SPY is above its VWAP).
- Add short selling and compare.
- Run several strategies at once in the paper loop, each with its own slice of the account.
- Feed news headlines to the Claude reviewer so it can skip stocks with earnings or big news.
- Track paper results weekly in a spreadsheet to see if live matches the backtest.
