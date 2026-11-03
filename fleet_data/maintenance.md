# Medic report, Tue Nov 03 2026 15:59 ET

## Since the last check
- Fixed: Bot 4e: Bot 4e: 2 errors in the last day. Latest: 2026-11-02 11:03:08,856 ERROR STRAY POSITION: 5 NO contracts of KXLIGAPROMATCH-26NOV021015ALEKHA-ALE still held. Check it on Kalshi.

## Bot 1: ORB day trader: OK
- **info** (return) $4,979.73, -0.4% since the $5,000 start.
- **info** (performance) 6 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (replay) 2026-11-03: bot 1 did what the backtest would have (1 entries).

## Bot 2: ETF rotation: OK
- **info** (return) $4,908.26, -1.8% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot -1.8% vs just holding SPY -0.7%.

## Bot 3: Crypto trend: OK
- **info** (return) $5,000.00, +0.0% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -5.5%.

## Bot 4c: Kalshi maker paper: OK
- **info** (return) Bot 4c: 3 settled, 1 open, $+7.07 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (stray) Bot 4e: 1 half-filled positions are still held. Fix: Check them on Kalshi; the bot couldn't sell them back.
- **act** (losses) Bot 4e: 16 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (drawdown) Bot 4e is at $15.62 of its $20.00 start.
- **info** (return) Bot 4e: 66 settled, 4 open, $-4.38 settled profit.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.