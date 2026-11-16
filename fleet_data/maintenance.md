# Medic report, Mon Nov 16 2026 16:18 ET

## Since the last check
- Fixed: Bot 1: Bot 1 should have run by Fri 09:20 ET but its log last changed Thu 11/12 16:05.
- Fixed: Bot 4e: Bot 4e: 1 errors in the last day. Latest: 2026-11-15 13:36:03,683 ERROR STRAY POSITION: 1 NO contracts of KXBBSERIEA2GAME-26NOV151200BASCRE-BAS still held. Check it on Kalshi. (Flagged 3 days in a row.)
- Fixed: Bot 4f: Bot 4f: 1 errors in the last day. Latest: 2026-11-15 13:36:00,777 ERROR STRAY POSITION: 1 NO contracts of KXBBSERIEA2GAME-26NOV151200BASCRE-BAS still held. Check it on Kalshi. (Flagged 6 days in a row.)

## Whole fleet: OK
- **info** (events) Coming up: NVDA earnings Tue 11/17; HD earnings Tue 11/17; DIS earnings Tue 11/17; WMT earnings Thu 11/19. Odd results around these days are normal.

## Bot 1: ORB day trader: OK
- **info** (return) $4,982.21, -0.4% since the $5,000 start.
- **info** (performance) 11 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (replay) 2026-11-16: bot 1 did what the backtest would have (0 entries).
- **ok** (slippage) Real fills cost +2.0 bps over 13 fills (backtest assumes 2).

## Bot 2: ETF rotation: OK
- **info** (return) $2,464.95, -2.5% since the $2,528 start.
- **info** (vs hold) Since 2026-10-23: bot -2.5% vs just holding SPY -2.6%.

## Bot 3: Crypto trend: OK
- **info** (return) $1,666.00, +0.0% since the $1,666 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -21.3%.

## Bot 4c: Kalshi maker paper: NEEDS ACTION
- **act** (schedule) Bot 4c (maker_paper) last wrote anything Mon 11/16 11:03 ET, over 30 minutes ago. Fix: Its loop has stopped. Check its scheduled task and its _err.log.
- **info** (return) Bot 4c: 3 settled, 1 open, $+7.07 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (schedule) Bot 4e (maker_paper) last wrote anything Mon 11/16 11:03 ET, over 30 minutes ago. Fix: Its loop has stopped. Check its scheduled task and its _err.log.
- **act** (losses) Bot 4e: 10 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (missed hedges) Bot 4e: 36 one-sided leftovers from missed hedges (not locked-in trades) closed for $-14.21. (Flagged 12 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4e is at $12.88 of its $20.00 start.
- **info** (return) Bot 4e: 104 settled, 4 open, $-7.12 settled profit.

## Bot 4f: Kalshi cushion test: NEEDS ACTION
- **act** (schedule) Bot 4f (maker_paper) last wrote anything Mon 11/16 11:03 ET, over 30 minutes ago. Fix: Its loop has stopped. Check its scheduled task and its _err.log.
- **act** (losses) Bot 4f: 5 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4f until the losing trades are explained.
- **act** (missed hedges) Bot 4f: 8 one-sided leftovers from missed hedges (not locked-in trades) closed for $-4.06. (Flagged 6 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4f is at $15.23 of its $20.00 start.
- **info** (return) Bot 4f: 13 settled, 2 open, $-4.77 settled profit.

## Bot 5: Dip buyer: OK
- **info** (return) $2,462.81, +0.5% since the $2,450 start.

## Bot 6: QQQ trend: OK
- **info** (return) $1,581.72, -5.1% since the $1,667 start.

## Bot 7: Momentum: OK
- **info** (return) $1,551.50, -6.9% since the $1,667 start.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.