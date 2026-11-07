# Medic report, Fri Nov 06 2026 20:26 ET

## Since the last check
- New: Bot 5: Down 50.8% from its peak, 1.5x past the worst drop in its backtest (14%).
- Fixed: Bot 5: No saved dipbuy.log for bot 5 yet, so no cloud run has been saved for it.

## Bot 1: ORB day trader: OK
- **info** (return) $4,977.33, -0.5% since the $5,000 start.
- **info** (performance) 8 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (replay) 2026-11-06: bot 1 did what the backtest would have (2 entries).
- **ok** (slippage) Real fills cost +2.5 bps over 10 fills (backtest assumes 2).

## Bot 2: ETF rotation: OK
- **info** (return) $2,405.83, -4.8% since the $2,528 start.
- **info** (vs hold) Since 2026-10-23: bot -4.8% vs just holding SPY -3.2%.

## Bot 3: Crypto trend: OK
- **info** (return) $5,000.00, +0.0% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -6.4%.

## Bot 4c: Kalshi maker paper: OK
- **info** (return) Bot 4c: 3 settled, 1 open, $+7.07 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (losses) Bot 4e: 4 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (drawdown) Bot 4e is at $15.87 of its $20.00 start.
- **act** (errors) Bot 4e: 4 errors in the last day. Latest: 2026-11-06 17:36:30,700 ERROR STRAY POSITION: 1 NO contracts of KXSOCKEYERUN-27-B37P00-42P99 still held. Check it on Kalshi. (Flagged 3 days in a row.) Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **watch** (missed hedges) Bot 4e: 28 one-sided leftovers from missed hedges (not locked-in trades) closed for $-11.18. Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **info** (return) Bot 4e: 86 settled, 4 open, $-4.13 settled profit.

## Bot 5: Dip buyer: NEEDS ACTION
- **act** (drawdown) Down 50.8% from its peak, 1.5x past the worst drop in its backtest (14%). Fix: Not normal for this strategy.
  - Proposed change (needs OK): Pause bot 8 and re-run its backtest on the latest data to see if the edge is gone.
- **info** (return) $2,459.04, +0.4% since the $2,450 start.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.