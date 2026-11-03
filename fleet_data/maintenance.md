# Medic report, Mon Nov 02 2026 20:28 ET

## Whole fleet: OK
- **info** (events) Coming up: AAPL earnings Mon 11/02. Odd results around these days are normal.

## Bot 1: ORB day trader: OK
- **info** (return) $4,984.43, -0.3% since the $5,000 start.
- **info** (performance) 5 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (replay) 2026-11-02: bot 1 did what the backtest would have (0 entries).

## Bot 2: ETF rotation: OK
- **info** (return) $4,959.44, -0.8% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot -0.8% vs just holding SPY -1.0%.

## Bot 3: Crypto trend: OK
- **info** (return) $5,000.00, +0.0% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -5.5%.

## Bot 4c: Kalshi maker paper: OK
- **info** (return) Bot 4c: 1 settled, 2 open, $-0.99 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (stray) Bot 4e: 1 half-filled positions are still held. Fix: Check them on Kalshi; the bot couldn't sell them back.
- **act** (losses) Bot 4e: 16 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (drawdown) Bot 4e is at $14.62 of its $20.00 start.
- **watch** (errors) Bot 4e: 2 errors in the last day. Latest: 2026-11-02 11:03:08,856 ERROR STRAY POSITION: 5 NO contracts of KXLIGAPROMATCH-26NOV021015ALEKHA-ALE still held. Check it on Kalshi. Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4e: 64 settled, 3 open, $-5.38 settled profit.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.