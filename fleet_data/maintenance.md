# Medic report, Wed Nov 11 2026 01:47 ET

## Since the last check
- New: Bot 1: On 2026-11-10 the backtest would have bought SPY at 10:00 (~$750.79) but bot 1 didn't.
- New: Bot 4f: Bot 4f: 1 one-sided leftovers from missed hedges (not locked-in trades) closed for $-0.51.
- New: Bot 4f: Bot 4f: 1 errors in the last day. Latest: 2026-11-10 21:21:01,356 ERROR STRAY POSITION: 2 NO contracts of KXNBARACE-26NOV10LACPHX-10-LAC still held. Check it on Kalshi.
- Fixed: Bot 6: No saved trend.log for bot 6 yet, so no cloud run has been saved for it.

## Whole fleet: OK
- **info** (events) Coming up: CSCO earnings Thu 11/12. Odd results around these days are normal.

## Bot 1: ORB day trader: WATCH
- **watch** (replay) On 2026-11-10 the backtest would have bought SPY at 10:00 (~$750.79) but bot 1 didn't. Fix: Check trades.log that day: was it running, did a risk limit block it, or did the live data differ?
- **info** (return) $4,981.30, -0.4% since the $5,000 start.
- **info** (performance) 9 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (slippage) Real fills cost +2.4 bps over 11 fills (backtest assumes 2).

## Bot 2: ETF rotation: OK
- **info** (return) $2,428.32, -3.9% since the $2,528 start.
- **info** (vs hold) Since 2026-10-23: bot -3.9% vs just holding SPY -1.3%.

## Bot 3: Crypto trend: OK
- **info** (return) $2,500.00, +0.0% since the $2,500 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -11.6%.

## Bot 4c: Kalshi maker paper: OK
- **info** (return) Bot 4c: 3 settled, 1 open, $+7.07 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (losses) Bot 4e: 5 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (missed hedges) Bot 4e: 31 one-sided leftovers from missed hedges (not locked-in trades) closed for $-12.31. (Flagged 7 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4e is at $14.84 of its $20.00 start.
- **info** (return) Bot 4e: 92 settled, 3 open, $-5.16 settled profit.

## Bot 4f: Kalshi cushion test: WATCH
- **watch** (missed hedges) Bot 4f: 1 one-sided leftovers from missed hedges (not locked-in trades) closed for $-0.51. Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **watch** (errors) Bot 4f: 1 errors in the last day. Latest: 2026-11-10 21:21:01,356 ERROR STRAY POSITION: 2 NO contracts of KXNBARACE-26NOV10LACPHX-10-LAC still held. Check it on Kalshi. Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4f: 1 settled, 0 open, $-0.51 settled profit.

## Bot 5: Dip buyer: OK
- **info** (return) $2,445.13, -0.2% since the $2,450 start.

## Bot 6: QQQ trend: OK
- **info** (return) $2,499.73, -0.0% since the $2,500 start.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.