# Medic report, Tue Nov 17 2026 03:09 ET

## Since the last check
- New: Bot 4e: Bot 4e: 1 errors in the last day. Latest: 2026-11-16 19:26:04,828 ERROR STRAY POSITION: 1 NO contracts of KXNBARACE-26NOV16MEMWAS-20-MEM still held. Check it on Kalshi.
- New: Bot 4f: Bot 4f: 1 errors in the last day. Latest: 2026-11-16 19:16:36,849 ERROR Maker loop error; carrying on
- Fixed: Bot 4c: Bot 4c (maker_paper) last wrote anything Mon 11/16 11:03 ET, over 30 minutes ago.
- Fixed: Bot 4e: Bot 4e (maker_paper) last wrote anything Mon 11/16 11:03 ET, over 30 minutes ago.
- Fixed: Bot 4f: Bot 4f (maker_paper) last wrote anything Mon 11/16 11:03 ET, over 30 minutes ago.

## Whole fleet: OK
- **info** (events) Coming up: NVDA earnings Tue 11/17; HD earnings Tue 11/17; DIS earnings Tue 11/17; WMT earnings Thu 11/19. Odd results around these days are normal.

## Bot 1: ORB day trader: OK
- **info** (return) $4,982.21, -0.4% since the $5,000 start.
- **info** (performance) 11 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (replay) 2026-11-16: bot 1 did what the backtest would have (0 entries).
- **ok** (slippage) Real fills cost +2.0 bps over 13 fills (backtest assumes 2).

## Bot 2: ETF rotation: OK
- **info** (return) $2,456.89, -2.8% since the $2,528 start.
- **info** (vs hold) Since 2026-10-23: bot -2.8% vs just holding SPY -2.6%.

## Bot 3: Crypto trend: OK
- **info** (return) $1,666.00, +0.0% since the $1,666 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -21.9%.

## Bot 4c: Kalshi maker paper: OK
- **info** (return) Bot 4c: 3 settled, 1 open, $+7.07 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (losses) Bot 4e: 10 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (missed hedges) Bot 4e: 37 one-sided leftovers from missed hedges (not locked-in trades) closed for $-14.35. (Flagged 13 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4e is at $13.05 of its $20.00 start.
- **watch** (errors) Bot 4e: 1 errors in the last day. Latest: 2026-11-16 19:26:04,828 ERROR STRAY POSITION: 1 NO contracts of KXNBARACE-26NOV16MEMWAS-20-MEM still held. Check it on Kalshi. Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4e: 107 settled, 3 open, $-6.95 settled profit.

## Bot 4f: Kalshi cushion test: NEEDS ACTION
- **act** (losses) Bot 4f: 6 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4f until the losing trades are explained.
- **act** (missed hedges) Bot 4f: 8 one-sided leftovers from missed hedges (not locked-in trades) closed for $-4.06. (Flagged 7 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4f is at $15.12 of its $20.00 start.
- **watch** (errors) Bot 4f: 1 errors in the last day. Latest: 2026-11-16 19:16:36,849 ERROR Maker loop error; carrying on Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4f: 14 settled, 1 open, $-4.88 settled profit.

## Bot 5: Dip buyer: OK
- **info** (return) $2,462.81, +0.5% since the $2,450 start.

## Bot 6: QQQ trend: OK
- **info** (return) $1,581.89, -5.1% since the $1,667 start.

## Bot 7: Momentum: OK
- **info** (return) $1,557.62, -6.6% since the $1,667 start.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.