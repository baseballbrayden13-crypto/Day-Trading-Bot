# Medic report, Thu Nov 12 2026 02:26 ET

## Since the last check
- New: Bot 4f: Bot 4f is at $17.40 of its $20.00 start.
- Fixed: Bot 4e: Bot 4e: 1 half-filled positions are still held.
- Fixed: Bot 4f: Bot 4f: 1 half-filled positions are still held.

## Whole fleet: OK
- **info** (events) Coming up: CSCO earnings Thu 11/12. Odd results around these days are normal.

## Bot 1: ORB day trader: OK
- **info** (return) $4,981.30, -0.4% since the $5,000 start.
- **info** (performance) 9 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (replay) 2026-11-11: bot 1 did what the backtest would have (0 entries).
- **ok** (slippage) Real fills cost +2.4 bps over 11 fills (backtest assumes 2).

## Bot 2: ETF rotation: OK
- **info** (return) $2,466.29, -2.4% since the $2,528 start.
- **info** (vs hold) Since 2026-10-23: bot -2.4% vs just holding SPY -0.0%.

## Bot 3: Crypto trend: OK
- **info** (return) $1,666.00, +0.0% since the $1,666 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -11.3%.

## Bot 4c: Kalshi maker paper: OK
- **info** (return) Bot 4c: 3 settled, 1 open, $+7.07 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (losses) Bot 4e: 6 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (missed hedges) Bot 4e: 33 one-sided leftovers from missed hedges (not locked-in trades) closed for $-13.39. (Flagged 8 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4e is at $13.68 of its $20.00 start.
- **watch** (errors) Bot 4e: 2 warnings last loop. Latest: 2026-11-12 06:55 STRAY POSITION: 5 NO contracts of KXNLGAME-26NOV111345HAPEVZ-EVZ still held. Check it on Kalshi.
- **watch** (errors) Bot 4e: 2 errors in the last day. Latest: 2026-11-12 01:55:02,874 ERROR STRAY POSITION: 5 NO contracts of KXNLGAME-26NOV111345HAPEVZ-EVZ still held. Check it on Kalshi. Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4e: 95 settled, 3 open, $-6.32 settled profit.

## Bot 4f: Kalshi cushion test: NEEDS ACTION
- **act** (drawdown) Bot 4f is at $17.40 of its $20.00 start.
- **watch** (missed hedges) Bot 4f: 3 one-sided leftovers from missed hedges (not locked-in trades) closed for $-2.53. Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **watch** (errors) Bot 4f: 2 errors in the last day. Latest: 2026-11-11 18:32:01,348 ERROR STRAY POSITION: 2 NO contracts of KXLIGAMXWGAME-26NOV11PACMTY-MTY still held. Check it on Kalshi. Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4f: 3 settled, 0 open, $-2.60 settled profit.

## Bot 5: Dip buyer: OK
- **info** (return) $2,463.55, +0.6% since the $2,450 start.

## Bot 6: QQQ trend: OK
- **info** (return) $1,667.27, +0.0% since the $1,667 start.

## Bot 7: Momentum: WATCH
- **watch** (schedule) No saved momentum.log for bot 7 yet, so no cloud run has been saved for it. Fix: If this stays for days, open the Actions tab and check its workflow runs and that its keys are in the repository secrets.
- **info** (return) $1,667.00, +0.0% since the $1,667 start.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.