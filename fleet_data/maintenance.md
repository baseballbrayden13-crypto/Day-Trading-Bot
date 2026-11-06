# Medic report, Thu Nov 05 2026 20:35 ET

## Since the last check
- New: Bot 4e: Bot 4e: 24 one-sided leftovers from missed hedges (not locked-in trades) closed for $-10.14.
- New: Bot 4e: Bot 4e is at $16.48 of its $20.00 start.
- New: Bot 5: No saved dipbuy.log for bot 5 yet, so no cloud run has been saved for it.

## Bot 1: ORB day trader: OK
- **info** (return) $4,979.70, -0.4% since the $5,000 start.
- **info** (performance) 6 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (replay) 2026-11-05: bot 1 did what the backtest would have (0 entries).

## Bot 2: ETF rotation: OK
- **info** (return) $4,846.61, -3.1% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot -3.1% vs just holding SPY -3.5%.

## Bot 3: Crypto trend: OK
- **info** (return) $5,000.00, +0.0% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -6.3%.

## Bot 4c: Kalshi maker paper: OK
- **info** (return) Bot 4c: 3 settled, 1 open, $+7.07 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (losses) Bot 4e: 3 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (drawdown) Bot 4e is at $16.48 of its $20.00 start.
- **watch** (missed hedges) Bot 4e: 24 one-sided leftovers from missed hedges (not locked-in trades) closed for $-10.14. Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **watch** (errors) Bot 4e: 4 errors in the last day. Latest: 2026-11-05 10:57:01,524 ERROR STRAY POSITION: 2 NO contracts of KXMLBBGAME-26NOV051000CHEMBW-CHEM still held. Check it on Kalshi. Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4e: 78 settled, 3 open, $-3.52 settled profit.

## Bot 5: Dip buyer: WATCH
- **watch** (schedule) No saved dipbuy.log for bot 5 yet, so no cloud run has been saved for it. Fix: If this stays for days, open the Actions tab and check its workflow runs and that its keys are in the repository secrets.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.