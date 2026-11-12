# Medic report, Wed Nov 11 2026 22:08 ET

## Whole fleet: OK
- **info** (data) Scout: crypto prices: APIError: {"message": "too many requests."}

- **info** (events) Coming up: CSCO earnings Thu 11/12. Odd results around these days are normal.

## Bot 1: ORB day trader: OK
- **info** (return) $4,981.30, -0.4% since the $5,000 start.
- **info** (performance) 9 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (replay) 2026-11-11: bot 1 did what the backtest would have (0 entries).
- **ok** (slippage) Real fills cost +2.4 bps over 11 fills (backtest assumes 2).

## Bot 2: ETF rotation: OK
- **info** (return) $2,456.28, -2.8% since the $2,528 start.
- **info** (vs hold) Since 2026-10-23: bot -2.8% vs just holding SPY -0.0%.

## Bot 3: Crypto trend: OK
- **info** (return) $1,666.00, +0.0% since the $1,666 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -11.3%.

## Bot 4c: Kalshi maker paper: OK
- **info** (return) Bot 4c: 3 settled, 1 open, $+7.07 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (stray) Bot 4e: 1 half-filled positions are still held. Fix: Check them on Kalshi; the bot couldn't sell them back.
- **act** (losses) Bot 4e: 5 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (missed hedges) Bot 4e: 31 one-sided leftovers from missed hedges (not locked-in trades) closed for $-12.31. (Flagged 7 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4e is at $14.84 of its $20.00 start.
- **watch** (errors) Bot 4e: 2 warnings last loop. Latest: 2026-11-12 02:23 STRAY POSITION: 1 NO contracts of KXLVBPGAME-26NOV111800LARLAG-LAR still held. Check it on Kalshi.
- **watch** (errors) Bot 4e: 1 errors in the last day. Latest: 2026-11-11 21:23:07,103 ERROR STRAY POSITION: 1 NO contracts of KXLVBPGAME-26NOV111800LARLAG-LAR still held. Check it on Kalshi. Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4e: 92 settled, 5 open, $-5.16 settled profit.

## Bot 4f: Kalshi cushion test: NEEDS ACTION
- **act** (stray) Bot 4f: 1 half-filled positions are still held. Fix: Check them on Kalshi; the bot couldn't sell them back.
- **watch** (missed hedges) Bot 4f: 2 one-sided leftovers from missed hedges (not locked-in trades) closed for $-0.85. Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **watch** (errors) Bot 4f: 3 warnings last loop. Latest: 2026-11-11 23:32 STRAY POSITION: 2 NO contracts of KXLIGAMXWGAME-26NOV11PACMTY-MTY still held. Check it on Kalshi.
- **watch** (errors) Bot 4f: 2 errors in the last day. Latest: 2026-11-11 18:32:01,348 ERROR STRAY POSITION: 2 NO contracts of KXLIGAMXWGAME-26NOV11PACMTY-MTY still held. Check it on Kalshi. Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4f: 2 settled, 1 open, $-0.92 settled profit.

## Bot 5: Dip buyer: OK
- **info** (return) $2,460.07, +0.4% since the $2,450 start.

## Bot 6: QQQ trend: OK
- **info** (return) $1,667.00, +0.0% since the $1,667 start.

## Bot 7: Momentum: WATCH
- **watch** (schedule) No saved momentum.log for bot 7 yet, so no cloud run has been saved for it. Fix: If this stays for days, open the Actions tab and check its workflow runs and that its keys are in the repository secrets.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.