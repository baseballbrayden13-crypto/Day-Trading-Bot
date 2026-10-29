# Medic report, Wed Oct 28 2026 21:23 ET

## Since the last check
- New: Bot 4c: Bot 4c (maker_paper) last wrote anything Wed 10/28 20:53 ET, over 30 minutes ago.
- New: Bot 4e: Bot 4e: 1 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market.
- New: Bot 4e: Bot 4e: 5 warnings last loop. Latest: 2026-10-28 22:51 STRAY POSITION: 5 NO contracts of KXLOLFBLOOD-26OCT281900LYIG-2-IG still held. Check it on Kalshi.
- New: Bot 4e: Bot 4e: 2 errors in the last day. Latest: 2026-10-28 18:51:50,980 ERROR STRAY POSITION: 5 NO contracts of KXLOLFBLOOD-26OCT281900LYIG-2-IG still held. Check it on Kalshi.
- Fixed: Bot 1: trades.log doesn't exist in ., so bot 1 has never run here.
- Fixed: Bot 2: rotation.log doesn't exist in ., so bot 2 has never run here.
- Fixed: Bot 3: crypto.log doesn't exist in ., so bot 3 has never run here.

## Whole fleet: OK
- **info** (events) Coming up: MSFT earnings Wed 10/28. Odd results around these days are normal.

## Bot 1: ORB day trader: OK
- **info** (return) $5,002.80, +0.1% since the $5,000 start.
- **info** (performance) 1 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (replay) 2026-10-28: bot 1 did what the backtest would have (0 entries).

## Bot 2: ETF rotation: OK
- **info** (return) $5,028.52, +0.6% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot +0.6% vs just holding SPY +1.6%.

## Bot 3: Crypto trend: OK
- **info** (return) $5,000.00, +0.0% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -0.5%.

## Bot 4c: Kalshi maker paper: NEEDS ACTION
- **act** (schedule) Bot 4c (maker_paper) last wrote anything Wed 10/28 20:53 ET, over 30 minutes ago. Fix: Its loop has stopped. Check its scheduled task and its _err.log.
- **info** (return) Bot 4c: 1 settled, 2 open, $-0.99 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (losses) Bot 4e: 1 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **watch** (errors) Bot 4e: 5 warnings last loop. Latest: 2026-10-28 22:51 STRAY POSITION: 5 NO contracts of KXLOLFBLOOD-26OCT281900LYIG-2-IG still held. Check it on Kalshi.
- **watch** (errors) Bot 4e: 2 errors in the last day. Latest: 2026-10-28 18:51:50,980 ERROR STRAY POSITION: 5 NO contracts of KXLOLFBLOOD-26OCT281900LYIG-2-IG still held. Check it on Kalshi. Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4e: 4 settled, 2 open, $-0.94 settled profit.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.