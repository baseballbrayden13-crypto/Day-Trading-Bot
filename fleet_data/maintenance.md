# Medic report, Fri Nov 13 2026 01:57 ET

## Since the last check
- Fixed: Bot 4e: Bot 4e: 2 errors in the last day. Latest: 2026-11-12 01:55:02,874 ERROR STRAY POSITION: 5 NO contracts of KXNLGAME-26NOV111345HAPEVZ-EVZ still held. Check it on Kalshi.

## Bot 1: ORB day trader: WATCH
- **watch** (replay) On 2026-11-12 the backtest would have bought QQQ at 10:55 (~$689.86) but bot 1 didn't. Fix: Check trades.log that day: was it running, did a risk limit block it, or did the live data differ?
- **info** (return) $4,982.24, -0.4% since the $5,000 start.
- **info** (performance) 11 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (slippage) Real fills cost +2.0 bps over 13 fills (backtest assumes 2).

## Bot 2: ETF rotation: OK
- **info** (return) $2,468.96, -2.3% since the $2,528 start.
- **info** (vs hold) Since 2026-10-23: bot -2.3% vs just holding SPY -0.4%.

## Bot 3: Crypto trend: OK
- **info** (return) $1,666.00, +0.0% since the $1,666 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -13.7%.

## Bot 4c: Kalshi maker paper: OK
- **info** (return) Bot 4c: 3 settled, 1 open, $+7.07 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (losses) Bot 4e: 7 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (missed hedges) Bot 4e: 33 one-sided leftovers from missed hedges (not locked-in trades) closed for $-13.39. (Flagged 9 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4e is at $13.58 of its $20.00 start.
- **info** (return) Bot 4e: 96 settled, 3 open, $-6.42 settled profit.

## Bot 4f: Kalshi cushion test: NEEDS ACTION
- **act** (missed hedges) Bot 4f: 4 one-sided leftovers from missed hedges (not locked-in trades) closed for $-3.29. (Flagged 3 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4f is at $16.49 of its $20.00 start.
- **act** (errors) Bot 4f: 2 errors in the last day. Latest: 2026-11-12 14:50:50,110 ERROR Maker loop error; carrying on (Flagged 3 days in a row.) Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4f: 4 settled, 0 open, $-3.51 settled profit.

## Bot 5: Dip buyer: OK
- **info** (return) $2,462.81, +0.5% since the $2,450 start.

## Bot 6: QQQ trend: OK
- **info** (return) $1,660.70, -0.4% since the $1,667 start.

## Bot 7: Momentum: OK
- **info** (return) $1,668.14, +0.1% since the $1,667 start.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.