# Medic report, Tue Nov 10 2026 02:30 ET

## Since the last check
- New: Bot 6: No saved trend.log for bot 6 yet, so no cloud run has been saved for it.
- Fixed: Bot 4e: Bot 4e: 1 warnings last loop. Latest: 2026-11-09 06:06 Quote KXCZEFNLGAME-26NOV07HANTRI: hedge missed on KXCZEFNLGAME-26NOV07HANTRI-TRI. Selling back 2 contracts on 1 legs. (Flagged 6 days in a row.)

## Whole fleet: OK
- **info** (events) Coming up: CSCO earnings Thu 11/12. Odd results around these days are normal.

## Bot 1: ORB day trader: OK
- **info** (return) $4,981.33, -0.4% since the $5,000 start.
- **info** (performance) 9 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (replay) 2026-11-09: bot 1 did what the backtest would have (1 entries).
- **ok** (slippage) Real fills cost +2.4 bps over 11 fills (backtest assumes 2).

## Bot 2: ETF rotation: OK
- **info** (return) $2,430.57, -3.8% since the $2,528 start.
- **info** (vs hold) Since 2026-10-23: bot -3.8% vs just holding SPY -0.9%.

## Bot 3: Crypto trend: OK
- **info** (return) $2,500.00, +0.0% since the $2,500 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -8.9%.

## Bot 4c: Kalshi maker paper: OK
- **info** (return) Bot 4c: 3 settled, 1 open, $+7.07 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (losses) Bot 4e: 5 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (missed hedges) Bot 4e: 31 one-sided leftovers from missed hedges (not locked-in trades) closed for $-12.31. (Flagged 6 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4e is at $14.84 of its $20.00 start.
- **info** (return) Bot 4e: 92 settled, 3 open, $-5.16 settled profit.

## Bot 4f: Kalshi cushion test: OK
- **info** (performance) No Bot 4f trades yet. Expected: the 14-day backtest found 0 taker trades worth $0.10.

## Bot 5: Dip buyer: OK
- **info** (return) $2,444.71, -0.2% since the $2,450 start.

## Bot 6: QQQ trend: WATCH
- **watch** (schedule) No saved trend.log for bot 6 yet, so no cloud run has been saved for it. Fix: If this stays for days, open the Actions tab and check its workflow runs and that its keys are in the repository secrets.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.