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

To try a grid of settings on top of your current `.env` (or your current
settings on other stocks), use `bot.sweep`. It uses the same cache and split:

```bash
python -m bot.sweep --set ORB_TARGET_R=1.25,1.5,1.75 --set ORB_GAP_MIN_PCT=0,0.5 --label target-gap
python -m bot.sweep --symbols AMZN,GOOGL,META,TSLA --label new-stocks
```

## Bot 2: monthly ETF rotation (paper)

Once a month it holds the 3 strongest of 15 ETFs over the last 3 months, skipping any
below their 200-day average (cash instead). Over 2006-2026 that made about 9.6% a year
vs 11.2% for SPY, with a worst drop of -26% vs -55% (`python -m bot.rotation`).
It runs on its own Alpaca paper account so it never shares money with ORB:

```
python set_keys.py --file .env.rotation      # bot 2's paper keys (hidden input)
python -m bot.rotation_live --dry-run         # what it would hold now; places nothing
python -m bot.rotation_live                   # rebalances on the first trading day of a month
```

Schedule `python -m bot.rotation_live` once a day after 9:45am ET; it does nothing
except on the first trading day of each month.

## Crypto trend bot (paper)

Holds BTC and ETH, half the account each, while each is above its 50-day average, and
cash otherwise (`python -m bot.daily_rules` for the research). Over 2014-2026 it beat
holding ETH and roughly halved BTC's worst drop, but expect -40% to -60% drops anyway.
It runs on its own Alpaca paper account:

```
python set_keys.py --file .env.crypto
python -m bot.crypto_live --dry-run    # what it would hold now; places nothing
python -m bot.crypto_live              # schedule daily, e.g. 8:15pm ET
```

## Kalshi bot (demo)

Scans every open Kalshi market for trades that lock in at least $0.10 after Kalshi's fees, with a
$20 budget. In an event where only one outcome can win, buying NO on several outcomes always pays
at least (outcomes - 1) dollars per set, so when the YES bids add up to more than $1 plus fees the
profit is guaranteed whoever wins (`bot/kalshi.py`). Every sweep also logs each market's prices and
updates a scorecard of which series produce trades, for testing expected-profit ideas later.

```
python -m bot.kalshi_live --scan          # read-only sweep of real prices; no keys, no orders
python -m bot.kalshi_live --scorecard     # which series have had $0.10+ trades
python set_kalshi_key.py                  # demo key from demo.kalshi.co -> .env.kalshi
python -m bot.kalshi_live --paper         # real prices, pretend $20 (the main test)
python -m bot.kalshi_live --trade         # sweep and trade on the DEMO account (checks ordering works)
python -m bot.kalshi_backtest --days 14  # replay settled events (rough: assumes 10 contracts per price)
```

Settings in `.env.kalshi`: `KALSHI_BUDGET` (20), `KALSHI_MIN_PROFIT` (0.10), `KALSHI_MAX_DAYS` (60,
skips trades that tie money up longer), `KALSHI_STEP` (0.25: the budget steps up 25% each time settled
profits grow it 25%, after `KALSHI_MIN_SETTLED`=5 paid-out baskets). Real money needs `KALSHI_ENV=prod` and
`KALSHI_LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY`.

## Helper bots: Scout (data) and Medic (diagnostics), read-only

Two bots that look after the trading bots: **Scout** (`bot.data_bot`) gathers the data and
**Medic** (`bot.maintenance`) checks every bot with it. Neither places, cancels or closes an order, and neither
edits a `.env` file. The fleet (which bot uses which keys, log, account and backtest limits) is in
`bot/fleet.py`; override any of it without touching code in `fleet.json`, e.g.
`{"4": {"home": "C:/Users/baseb/Downloads/kalshi-run"}}` if the Kalshi bot runs in another folder.

```
python -m bot.data_bot                     # collect accounts, fills, positions, logs, Kalshi, prices, news -> fleet_data/
python -m bot.maintenance --collect        # collect, then check every bot -> fleet_data/maintenance.md
python -m bot.maintenance --collect --alert  # same, and push new problems to the phone (NTFY_TOPIC)
```

**Scout** writes `fleet_data/snapshot.json` (everything from the run), `equity.csv` (one row
per bot per day, same columns as the Strategy Lab equity data), `trades.csv` (every fill, all
bots), `positions.csv`, `market.csv` (trend and volatility for every symbol the fleet trades) and
`news.csv` and `benchmarks.csv` (SPY, BTC and ETH, to compare each bot with just holding). It also
reads each bot's Windows task and any `*_err.log` crash file. One failing source (bad keys, network) is recorded and the rest still run.

**Medic** grades each bot (including the Kalshi maker, "bot 4b") ok / info / watch / act: keys rejected or missing, keys on
the wrong account or two bots on one account, a missed scheduled run, errors in the log, a LIVE
connection, a day loss or drop from peak past the backtest's worst, bot 1 holding after the close,
bot 2/3 holdings that don't match their rules, bot 1's profit factor and real slippage once there
are enough trades, and Kalshi stray positions or losing "locked-in" trades. Every finding says
what to do. Fixes that would change how a bot trades go to `fleet_data/proposals.csv` in the
Strategy Lab Changes-log format (status "Proposed"); nothing is applied without an OK. A "watch"
that repeats 3 days in a row becomes "act", the report starts with what's new and what got fixed
since the last check, `--alert` sends one summary push per run, and `health.csv` / `findings.csv`
feed the Strategy Lab site.

On Windows it also reads each bot's scheduled task (running or not, last result code), which
catches a bot whose window was closed even when its log looks fine. Schedule it once a day after
bot 3's 8:15pm run with `Run fleet maintenance.bat` (the command to register it is inside).

## More helpers: Guard, Lab, Reporter (read-only)

| Helper | Command | When | What it does |
|---|---|---|---|
| Guard | `python -m bot.guard --loop 10 --until 16:10` | weekdays 9:25am | every 10 minutes: daily loss near or past each bot's limit, the whole fleet down 2%, a holding too big, a short, bot 1 holding after 3:55pm, Kalshi stray positions |
| Lab | `python -m bot.lab` | Saturdays | re-tests every bot on fresh data ("is the edge fading?") and runs one experiment from `fleet_data/lab_queue.txt` |
| Reporter | `python -m bot.reporter` | Sundays | a plain-English report card per bot, grade A to D |
| Summary | `python -m bot.popup --summary` | at logon | Medic's latest grades (PC and cloud) and the helpers' alerts since last time |

Medic also replays bot 1's day through the backtest (did it trade when it should have?) and lists
upcoming earnings for the fleet's stocks plus any dates in `fleet_events.json`
(`[{"date": "2026-11-10", "what": "CPI"}]`). The helpers' alerts are PC popups (`bot.alerts`);
set `ALERTS_PHONE=true` in `.env` to also get "act" alerts on the phone. No popups 11pm-7am ET (`ALERTS_QUIET=23-7`, or `off`); those wait for the next summary. Set all the tasks up with
`Install fleet helpers.bat` (they catch up after the PC was asleep); undo with
`powershell -File install_helpers.ps1 -Remove`.

## Bots 2 and 3 in the cloud (GitHub Actions, free)

`.github/workflows/cloud-bots.yml` runs bot 2 (weekdays ~9:52am ET), bot 3 (nightly ~8:20pm ET) and
Scout + Medic for them on GitHub, so they run with the PC off. Their logs, state and Medic's results
are saved on the `bot-state` branch (public, like the repo; keys never are). To turn it on:

1. `Copy keys to GitHub.bat` (or `python set_cloud_keys.py`) copies bots 2 and 3's keys from `.env.rotation` / `.env.crypto` into the
   repository's secrets (and bot 1's account number, and bot 2's month state) without showing them.
2. Turn off the PC's tasks for bots 2 and 3, and put `{"2": {"runs_on": "cloud"}, "3": {"runs_on": "cloud"}}`
   in the PC's `fleet.json`.
3. Run it once from the Actions tab ("Cloud bots (paper)" > Run workflow > all).

Scheduled runs only start once the workflow is on the default branch (main).

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

### Moving bot 1 and the helpers to GitHub

`Move bots to GitHub.bat` (double-click before 9am or after 4pm on a weekday) turns off the PC tasks
for bots 1-3, Guard, Lab and Reporter, copies bot 1's `.env` into the `BOT1_ENV` secret and sets the
repository variable `BOT1_CLOUD=on`. Then `Cloud bot 1 (paper)` trades in two runs a day (9:05am-12:38pm
and 12:40-4:05pm ET, with Guard alongside) and `Cloud weekly helpers` runs Lab and Reporter. Until
`BOT1_CLOUD` is on, both workflows do nothing. Alerts from the GitHub bots pop up on the PC through the
"Fleet alerts from GitHub" task (`install_helpers.ps1`). Undo: `"Move bots to GitHub.bat" undo`.
The Kalshi bots and the PC's Medic stay on the PC for now.
