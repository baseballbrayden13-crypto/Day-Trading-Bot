# Medic report, Sun Nov 08 2026 23:26 ET

## Since the last check
- New: Bot 3: Bot 3 should have run by Sun 20:15 ET but its log last changed Sat 11/07 20:32.
- New: Bot 4c: Bot 4c (maker_paper) last wrote anything Sun 11/08 22:37 ET, over 30 minutes ago.
- New: Bot 4e: Bot 4e (maker_paper) last wrote anything Sun 11/08 22:37 ET, over 30 minutes ago.

## Bot 1: ORB day trader: OK
- **info** (return) $4,977.29, -0.5% since the $5,000 start.
- **info** (performance) 8 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (slippage) Real fills cost +2.5 bps over 10 fills (backtest assumes 2).

## Bot 2: ETF rotation: OK
- **info** (return) $2,412.85, -4.5% since the $2,528 start.
- **info** (vs hold) Since 2026-10-23: bot -4.5% vs just holding SPY -3.2%.

## Bot 3: Crypto trend: NEEDS ACTION
- **act** (schedule) Bot 3 should have run by Sun 20:15 ET but its log last changed Sat 11/07 20:32. Fix: Check the Cloud bots runs on GitHub (Actions tab) for a failed or skipped run.
- **info** (return) $5,000.00, +0.0% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -9.3%.

## Bot 4c: Kalshi maker paper: NEEDS ACTION
- **act** (schedule) Bot 4c (maker_paper) last wrote anything Sun 11/08 22:37 ET, over 30 minutes ago. Fix: Its loop has stopped. Check its scheduled task and its _err.log.
- **info** (return) Bot 4c: 3 settled, 1 open, $+7.07 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (schedule) Bot 4e (maker_paper) last wrote anything Sun 11/08 22:37 ET, over 30 minutes ago. Fix: Its loop has stopped. Check its scheduled task and its _err.log.
- **act** (losses) Bot 4e: 5 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (missed hedges) Bot 4e: 31 one-sided leftovers from missed hedges (not locked-in trades) closed for $-12.31. (Flagged 4 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4e is at $15.10 of its $20.00 start.
- **act** (errors) Bot 4e: 1 errors in the last day. Latest: 2026-11-07 23:45:48,535 ERROR STRAY POSITION: 1 NO contracts of KXAHLGAME-26NOV072100SANHEN-HEN still held. Check it on Kalshi. (Flagged 5 days in a row.) Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4e: 92 settled, 3 open, $-4.90 settled profit.

## Bot 5: Dip buyer: NEEDS ACTION
- **act** (drawdown) Down 50.8% from its peak, 1.5x past the worst drop in its backtest (14%). Fix: Not normal for this strategy.
  - Proposed change (needs OK): Pause bot 8 and re-run its backtest on the latest data to see if the edge is gone.
- **info** (return) $2,462.24, +0.5% since the $2,450 start.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.