# Medic report, Thu Nov 19 2026 02:39 ET

## Since the last check
- Fixed: Bot 1: On 2026-11-17 the backtest would have bought AAPL at 09:55 (~$354.76) but bot 1 didn't.
- Fixed: Bot 4c: Bot 4c (maker_paper) last wrote anything Wed 11/18 00:52 ET, over 30 minutes ago.
- Fixed: Bot 4e: Bot 4e: 1 errors in the last day. Latest: 2026-11-17 21:11:18,086 ERROR Maker loop error; carrying on
- Fixed: Bot 4f: Bot 4f (maker_paper) last wrote anything Wed 11/18 00:53 ET, over 30 minutes ago.

## Whole fleet: OK
- **info** (events) Coming up: WMT earnings Thu 11/19. Odd results around these days are normal.

## Bot 1: ORB day trader: NEEDS ACTION
- **act** (schedule) Bot 1 should have run by Wed 09:20 ET but its log last changed Mon 11/16 16:05. Fix: Check the Cloud bots runs on GitHub (Actions tab) for a failed or skipped run.
- **info** (return) $4,982.21, -0.4% since the $5,000 start.
- **info** (performance) 11 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (replay) 2026-11-18: bot 1 did what the backtest would have (0 entries).
- **ok** (slippage) Real fills cost +2.0 bps over 13 fills (backtest assumes 2).

## Bot 2: ETF rotation: OK
- **info** (return) $2,396.39, -5.2% since the $2,528 start.
- **info** (vs hold) Since 2026-10-23: bot -5.2% vs just holding SPY -3.9%.

## Bot 3: Crypto trend: OK
- **info** (return) $1,666.00, +0.0% since the $1,666 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -24.0%.

## Bot 4c: Kalshi maker paper: OK
- **info** (return) Bot 4c: 3 settled, 1 open, $+7.07 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (schedule) Bot 4e (maker_paper) last wrote anything Thu 11/19 02:06 ET, over 30 minutes ago. Fix: Its loop has stopped. Check its scheduled task and its _err.log.
- **act** (losses) Bot 4e: 12 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (missed hedges) Bot 4e: 37 one-sided leftovers from missed hedges (not locked-in trades) closed for $-14.35. (Flagged 15 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4e is at $13.43 of its $20.00 start.
- **info** (return) Bot 4e: 111 settled, 3 open, $-6.57 settled profit.

## Bot 4f: Kalshi cushion test: NEEDS ACTION
- **act** (losses) Bot 4f: 7 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4f until the losing trades are explained.
- **act** (missed hedges) Bot 4f: 8 one-sided leftovers from missed hedges (not locked-in trades) closed for $-4.06. (Flagged 9 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4f is at $15.25 of its $20.00 start.
- **info** (return) Bot 4f: 16 settled, 0 open, $-4.75 settled profit.

## Bot 5: Dip buyer: OK
- **info** (return) $2,462.81, +0.5% since the $2,450 start.

## Bot 6: QQQ trend: OK
- **info** (return) $1,582.23, -5.1% since the $1,667 start.

## Bot 7: Momentum: OK
- **info** (return) $1,583.63, -5.0% since the $1,667 start.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.