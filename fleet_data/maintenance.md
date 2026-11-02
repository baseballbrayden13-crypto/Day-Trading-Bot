# Medic report, Sun Nov 01 2026 20:32 ET

## Since the last check
- New: Bot 4e: Bot 4e: 1 half-filled positions are still held.
- New: Bot 4e: Bot 4e is at $14.00 of its $20.00 start.

## Whole fleet: OK
- **info** (events) Coming up: AAPL earnings Mon 11/02. Odd results around these days are normal.

## Bot 1: ORB day trader: OK
- **info** (return) $4,984.43, -0.3% since the $5,000 start.
- **info** (performance) 5 closed trades so far; 30 are needed before the results say anything about the strategy.

## Bot 2: ETF rotation: OK
- **info** (return) $5,018.93, +0.4% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot +0.4% vs just holding SPY -0.5%.

## Bot 3: Crypto trend: OK
- **info** (return) $5,000.00, +0.0% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -4.1%.

## Bot 4c: Kalshi maker paper: OK
- **info** (return) Bot 4c: 1 settled, 2 open, $-0.99 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (stray) Bot 4e: 1 half-filled positions are still held. Fix: Check them on Kalshi; the bot couldn't sell them back.
- **act** (losses) Bot 4e: 15 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (drawdown) Bot 4e is at $14.00 of its $20.00 start.
- **act** (errors) Bot 4e: 6 errors in the last day. Latest: 2026-11-01 17:16:34,310 ERROR STRAY POSITION: 5 NO contracts of KXKBOGAME-26NOV040430SAMKTW-KTW still held. Check it on Kalshi. Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4e: 59 settled, 3 open, $-6.00 settled profit.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.