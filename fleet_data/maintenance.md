# Medic report, Fri Oct 30 2026 21:25 ET

## Whole fleet: OK
- **info** (events) Coming up: AAPL earnings Mon 11/02. Odd results around these days are normal.

## Bot 1: ORB day trader: OK
- **info** (return) $4,984.47, -0.3% since the $5,000 start.
- **info** (performance) 5 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (replay) 2026-10-30: bot 1 did what the backtest would have (2 entries).

## Bot 2: ETF rotation: OK
- **info** (return) $5,010.94, +0.2% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot +0.2% vs just holding SPY -0.5%.

## Bot 3: Crypto trend: OK
- **info** (return) $5,000.00, +0.0% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -5.4%.

## Bot 4c: Kalshi maker paper: OK
- **info** (return) Bot 4c: 1 settled, 2 open, $-0.99 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (losses) Bot 4e: 4 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (errors) Bot 4e: 1 warnings last loop. Latest: 2026-10-31 01:13 Quote KXSSHIELDMATCH-26OCT272000WEARED: hedge missed on KXSSHIELDMATCH-26OCT272000WEARED-RED. Selling back 5 contracts on 1 legs. (Flagged 3 days in a row.)
- **act** (errors) Bot 4e: 2 errors in the last day. Latest: 2026-10-30 05:18:53,593 ERROR STRAY POSITION: 6 NO contracts of KXEBASKETBALLGAME-26OCT300512MICKJASO-JASO still held. Check it on Kalshi. (Flagged 3 days in a row.) Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4e: 30 settled, 3 open, $+1.50 settled profit.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.