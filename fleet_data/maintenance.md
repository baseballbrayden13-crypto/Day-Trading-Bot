# Medic report, Sun Nov 15 2026 01:50 ET

## Since the last check
- New: Bot 4c: Bot 4c: 2 errors in the last day. Latest: 2026-11-14 16:15:15,842 ERROR Maker loop error; carrying on
- Fixed: Bot 4e: Bot 4e: 1 half-filled positions are still held.

## Whole fleet: OK
- **info** (events) Coming up: NVDA earnings Tue 11/17; HD earnings Tue 11/17; DIS earnings Tue 11/17. Odd results around these days are normal.

## Bot 1: ORB day trader: NEEDS ACTION
- **act** (schedule) Bot 1 should have run by Fri 09:20 ET but its log last changed Thu 11/12 16:05. Fix: Check the Cloud bots runs on GitHub (Actions tab) for a failed or skipped run.
- **info** (return) $4,982.21, -0.4% since the $5,000 start.
- **info** (performance) 11 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (slippage) Real fills cost +2.0 bps over 13 fills (backtest assumes 2).

## Bot 2: ETF rotation: OK
- **info** (return) $2,483.61, -1.7% since the $2,528 start.
- **info** (vs hold) Since 2026-10-23: bot -1.7% vs just holding SPY -0.7%.

## Bot 3: Crypto trend: OK
- **info** (return) $1,666.00, +0.0% since the $1,666 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -23.4%.

## Bot 4c: Kalshi maker paper: WATCH
- **watch** (errors) Bot 4c: 2 errors in the last day. Latest: 2026-11-14 16:15:15,842 ERROR Maker loop error; carrying on Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4c: 3 settled, 1 open, $+7.07 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (losses) Bot 4e: 9 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (missed hedges) Bot 4e: 35 one-sided leftovers from missed hedges (not locked-in trades) closed for $-14.13. (Flagged 11 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4e is at $13.01 of its $20.00 start.
- **watch** (errors) Bot 4e: 2 warnings last loop. Latest: 2026-11-15 02:10 STRAY POSITION: 1 NO contracts of KXNCAAHGAME-26NOV14UMDSCS-UMD still held. Check it on Kalshi.
- **watch** (errors) Bot 4e: 1 errors in the last day. Latest: 2026-11-14 21:10:01,248 ERROR STRAY POSITION: 1 NO contracts of KXNCAAHGAME-26NOV14UMDSCS-UMD still held. Check it on Kalshi. Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4e: 102 settled, 3 open, $-6.99 settled profit.

## Bot 4f: Kalshi cushion test: NEEDS ACTION
- **act** (losses) Bot 4f: 3 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4f until the losing trades are explained.
- **act** (missed hedges) Bot 4f: 7 one-sided leftovers from missed hedges (not locked-in trades) closed for $-3.98. (Flagged 5 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4f is at $15.46 of its $20.00 start.
- **act** (errors) Bot 4f: 2 warnings last loop. Latest: 2026-11-15 04:39 STRAY POSITION: 2 NO contracts of KXNCAAWVMATCH-26NOV142200WASHUSC-WASH still held. Check it on Kalshi. (Flagged 5 days in a row.)
- **act** (errors) Bot 4f: 1 errors in the last day. Latest: 2026-11-14 23:39:15,624 ERROR STRAY POSITION: 2 NO contracts of KXNCAAWVMATCH-26NOV142200WASHUSC-WASH still held. Check it on Kalshi. (Flagged 5 days in a row.) Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4f: 10 settled, 2 open, $-4.54 settled profit.

## Bot 5: Dip buyer: OK
- **info** (return) $2,462.81, +0.5% since the $2,450 start.

## Bot 6: QQQ trend: OK
- **info** (return) $1,627.59, -2.4% since the $1,667 start.

## Bot 7: Momentum: OK
- **info** (return) $1,610.22, -3.4% since the $1,667 start.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.