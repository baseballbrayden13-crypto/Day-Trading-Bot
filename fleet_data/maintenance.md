# Medic report, Thu Oct 29 2026 21:26 ET

## Since the last check
- Fixed: Bot 4c: Bot 4c (maker_paper) last wrote anything Wed 10/28 20:53 ET, over 30 minutes ago.

## Bot 1: ORB day trader: OK
- **info** (return) $4,998.02, -0.0% since the $5,000 start.
- **info** (performance) 3 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (replay) 2026-10-29: bot 1 did what the backtest would have (2 entries).

## Bot 2: ETF rotation: OK
- **info** (return) $5,034.50, +0.7% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot +0.7% vs just holding SPY +1.3%.

## Bot 3: Crypto trend: OK
- **info** (return) $5,000.00, +0.0% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -4.9%.

## Bot 4c: Kalshi maker paper: OK
- **info** (return) Bot 4c: 1 settled, 2 open, $-0.99 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (losses) Bot 4e: 2 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **watch** (errors) Bot 4e: 2 errors in the last day. Latest: 2026-10-29 11:22:06,314 ERROR STRAY POSITION: 2 NO contracts of KXSAUDIPL1H-26OCT29KHAHAZ-HAZ still held. Check it on Kalshi. Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4e: 18 settled, 3 open, $+1.67 settled profit.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.