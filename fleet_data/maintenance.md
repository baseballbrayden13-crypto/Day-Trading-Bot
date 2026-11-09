# Medic report, Mon Nov 09 2026 01:53 ET

## Since the last check
- Fixed: Bot 3: Bot 3 should have run by Sun 20:15 ET but its log last changed Sat 11/07 20:32.
- Fixed: Bot 4c: Bot 4c (maker_paper) last wrote anything Sun 11/08 22:37 ET, over 30 minutes ago.
- Fixed: Bot 4e: Bot 4e (maker_paper) last wrote anything Sun 11/08 22:37 ET, over 30 minutes ago.
- Fixed: Bot 5: Down 50.8% from its peak, 1.5x past the worst drop in its backtest (14%).

## Whole fleet: OK
- **info** (events) Coming up: CSCO earnings Thu 11/12. Odd results around these days are normal.

## Bot 1: ORB day trader: OK
- **info** (return) $4,977.29, -0.5% since the $5,000 start.
- **info** (performance) 8 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (replay) 2026-11-06: bot 1 did what the backtest would have (2 entries).
- **ok** (slippage) Real fills cost +2.5 bps over 10 fills (backtest assumes 2).

## Bot 2: ETF rotation: OK
- **info** (return) $2,424.66, -4.1% since the $2,528 start.
- **info** (vs hold) Since 2026-10-23: bot -4.1% vs just holding SPY -3.2%.

## Bot 3: Crypto trend: OK
- **info** (return) $5,000.00, +0.0% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -9.3%.

## Bot 4c: Kalshi maker paper: OK
- **info** (return) Bot 4c: 3 settled, 1 open, $+7.07 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (losses) Bot 4e: 5 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (missed hedges) Bot 4e: 31 one-sided leftovers from missed hedges (not locked-in trades) closed for $-12.31. (Flagged 5 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4e is at $14.97 of its $20.00 start.
- **act** (errors) Bot 4e: 1 warnings last loop. Latest: 2026-11-09 06:06 Quote KXCZEFNLGAME-26NOV07HANTRI: hedge missed on KXCZEFNLGAME-26NOV07HANTRI-TRI. Selling back 2 contracts on 1 legs. (Flagged 6 days in a row.)
- **info** (return) Bot 4e: 92 settled, 3 open, $-5.03 settled profit.

## Bot 5: Dip buyer: OK
- **info** (return) $2,463.34, +0.5% since the $2,450 start.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.