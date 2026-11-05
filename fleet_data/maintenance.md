# Medic report, Wed Nov 04 2026 20:32 ET

## Since the last check
- New: Bot 4e: Bot 4e: 2 errors in the last day. Latest: 2026-11-04 19:22:50,620 ERROR STRAY POSITION: 4 NO contracts of KXNBARACE-26NOV04ATLWAS-20-WAS still held. Check it on Kalshi.
- Fixed: Bot 4e: Bot 4e: 1 half-filled positions are still held.
- Fixed: Bot 4e: Bot 4e is at $15.25 of its $20.00 start.

## Bot 1: ORB day trader: OK
- **info** (return) $4,979.70, -0.4% since the $5,000 start.
- **info** (performance) 6 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (replay) 2026-11-04: bot 1 did what the backtest would have (0 entries).

## Bot 2: ETF rotation: OK
- **info** (return) $4,936.36, -1.3% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot -1.3% vs just holding SPY +0.9%.

## Bot 3: Crypto trend: OK
- **info** (return) $5,000.00, +0.0% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD +0.4%.

## Bot 4c: Kalshi maker paper: OK
- **info** (return) Bot 4c: 3 settled, 1 open, $+7.07 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (losses) Bot 4e: 18 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **watch** (errors) Bot 4e: 2 errors in the last day. Latest: 2026-11-04 19:22:50,620 ERROR STRAY POSITION: 4 NO contracts of KXNBARACE-26NOV04ATLWAS-20-WAS still held. Check it on Kalshi. Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4e: 70 settled, 3 open, $-1.73 settled profit.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.