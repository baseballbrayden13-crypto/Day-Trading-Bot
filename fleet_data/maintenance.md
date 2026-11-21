# Medic report, Sat Nov 21 2026 02:26 ET

## Since the last check
- New: Bot 4f: Bot 4f: 2 warnings last loop. Latest: 2026-11-21 02:11 STRAY POSITION: 2 NO contracts of KXLVBPGAME-26NOV201800ANZMAG-ANZ still held. Check it on Kalshi.
- New: Bot 4f: Bot 4f: 1 errors in the last day. Latest: 2026-11-20 21:11:28,625 ERROR STRAY POSITION: 2 NO contracts of KXLVBPGAME-26NOV201800ANZMAG-ANZ still held. Check it on Kalshi.

## Bot 1: ORB day trader: NEEDS ACTION
- **act** (schedule) Bot 1 should have run by Fri 09:20 ET but its log last changed Mon 11/16 16:05. Fix: Check the Cloud bots runs on GitHub (Actions tab) for a failed or skipped run.
- **info** (return) $4,982.21, -0.4% since the $5,000 start.
- **info** (performance) 11 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (slippage) Real fills cost +2.0 bps over 13 fills (backtest assumes 2).

## Bot 2: ETF rotation: OK
- **info** (return) $2,364.20, -6.5% since the $2,528 start.
- **info** (vs hold) Since 2026-10-23: bot -6.5% vs just holding SPY -9.1%.

## Bot 3: Crypto trend: OK
- **info** (return) $1,666.00, +0.0% since the $1,666 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -29.8%.

## Bot 4c: Kalshi maker paper: OK
- **info** (return) Bot 4c: 3 settled, 1 open, $+7.07 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (losses) Bot 4e: 12 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (missed hedges) Bot 4e: 37 one-sided leftovers from missed hedges (not locked-in trades) closed for $-14.35. (Flagged 17 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4e is at $13.80 of its $20.00 start.
- **info** (return) Bot 4e: 112 settled, 3 open, $-6.20 settled profit.

## Bot 4f: Kalshi cushion test: NEEDS ACTION
- **act** (losses) Bot 4f: 7 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4f until the losing trades are explained.
- **act** (missed hedges) Bot 4f: 9 one-sided leftovers from missed hedges (not locked-in trades) closed for $-4.40. (Flagged 11 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4f is at $14.91 of its $20.00 start.
- **watch** (errors) Bot 4f: 2 warnings last loop. Latest: 2026-11-21 02:11 STRAY POSITION: 2 NO contracts of KXLVBPGAME-26NOV201800ANZMAG-ANZ still held. Check it on Kalshi.
- **watch** (errors) Bot 4f: 1 errors in the last day. Latest: 2026-11-20 21:11:28,625 ERROR STRAY POSITION: 2 NO contracts of KXLVBPGAME-26NOV201800ANZMAG-ANZ still held. Check it on Kalshi. Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4f: 17 settled, 0 open, $-5.09 settled profit.

## Bot 5: Dip buyer: OK
- **info** (return) $2,462.81, +0.5% since the $2,450 start.

## Bot 6: QQQ trend: OK
- **info** (return) $1,582.58, -5.1% since the $1,667 start.

## Bot 7: Momentum: OK
- **info** (return) $1,411.12, -15.3% since the $1,667 start.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.