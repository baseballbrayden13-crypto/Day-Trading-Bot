# Medic report, Thu Nov 12 2026 15:49 ET

## Since the last check
- New: Bot 1: On 2026-11-12 the backtest would have bought QQQ at 10:55 (~$689.86) but bot 1 didn't.
- New: Bot 2: Bot 2 should have run by Thu 09:50 ET but its log last changed Thu 11/12 09:42.
- New: Bot 4c: Bot 4c (maker_paper) last wrote anything Thu 11/12 14:53 ET, over 30 minutes ago.
- New: Bot 4e: Bot 4e (maker_paper) last wrote anything Thu 11/12 14:53 ET, over 30 minutes ago.
- New: Bot 4f: Bot 4f (maker_paper) last wrote anything Thu 11/12 14:54 ET, over 30 minutes ago.
- New: Bot 5: Bot 8 should have run by Thu 09:50 ET but its log last changed Thu 11/12 09:42.
- New: Bot 6: Bot 10 should have run by Thu 09:50 ET but its log last changed Thu 11/12 09:42.

## Whole fleet: OK
- **info** (events) Coming up: CSCO earnings Thu 11/12. Odd results around these days are normal.

## Bot 1: ORB day trader: WATCH
- **watch** (replay) On 2026-11-12 the backtest would have bought QQQ at 10:55 (~$689.86) but bot 1 didn't. Fix: Check trades.log that day: was it running, did a risk limit block it, or did the live data differ?
- **info** (return) $4,982.42, -0.4% since the $5,000 start.
- **info** (performance) 9 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (slippage) Real fills cost +2.0 bps over 13 fills (backtest assumes 2).

## Bot 2: ETF rotation: NEEDS ACTION
- **act** (schedule) Bot 2 should have run by Thu 09:50 ET but its log last changed Thu 11/12 09:42. Fix: Check the Cloud bots runs on GitHub (Actions tab) for a failed or skipped run.
- **info** (return) $2,464.03, -2.5% since the $2,528 start.
- **info** (vs hold) Since 2026-10-23: bot -2.5% vs just holding SPY -0.4%.

## Bot 3: Crypto trend: OK
- **info** (return) $1,666.00, +0.0% since the $1,666 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -11.3%.

## Bot 4c: Kalshi maker paper: NEEDS ACTION
- **act** (schedule) Bot 4c (maker_paper) last wrote anything Thu 11/12 14:53 ET, over 30 minutes ago. Fix: Its loop has stopped. Check its scheduled task and its _err.log.
- **info** (return) Bot 4c: 3 settled, 1 open, $+7.07 settled profit.

## Bot 4e: Kalshi combined: NEEDS ACTION
- **act** (schedule) Bot 4e (maker_paper) last wrote anything Thu 11/12 14:53 ET, over 30 minutes ago. Fix: Its loop has stopped. Check its scheduled task and its _err.log.
- **act** (losses) Bot 4e: 7 'locked-in' trades lost money. Locked trades can't lose unless a leg missed or the bot misread a market. Fix: Read kalshi_data/opportunities.csv for those events.
  - Proposed change (needs OK): Pause Bot 4e until the losing trades are explained.
- **act** (missed hedges) Bot 4e: 33 one-sided leftovers from missed hedges (not locked-in trades) closed for $-13.39. (Flagged 8 days in a row.) Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **act** (drawdown) Bot 4e is at $13.58 of its $20.00 start.
- **watch** (errors) Bot 4e: 2 errors in the last day. Latest: 2026-11-12 01:55:02,874 ERROR STRAY POSITION: 5 NO contracts of KXNLGAME-26NOV111345HAPEVZ-EVZ still held. Check it on Kalshi. Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4e: 96 settled, 3 open, $-6.42 settled profit.

## Bot 4f: Kalshi cushion test: NEEDS ACTION
- **act** (schedule) Bot 4f (maker_paper) last wrote anything Thu 11/12 14:54 ET, over 30 minutes ago. Fix: Its loop has stopped. Check its scheduled task and its _err.log.
- **act** (drawdown) Bot 4f is at $16.49 of its $20.00 start.
- **watch** (missed hedges) Bot 4f: 4 one-sided leftovers from missed hedges (not locked-in trades) closed for $-3.29. Fix: If this keeps growing, stop quoting the series that miss most (or let the hedge chase pay a little more).
- **watch** (errors) Bot 4f: 3 warnings last loop. Latest: 2026-11-12 19:50 Maker loop error; carrying on
- **watch** (errors) Bot 4f: 4 errors in the last day. Latest: 2026-11-12 14:50:50,110 ERROR Maker loop error; carrying on Fix: Read the end of the log. Repeated errors usually mean bad keys, no network or a code bug.
- **info** (return) Bot 4f: 4 settled, 0 open, $-3.51 settled profit.

## Bot 5: Dip buyer: NEEDS ACTION
- **act** (schedule) Bot 8 should have run by Thu 09:50 ET but its log last changed Thu 11/12 09:42. Fix: Check the Cloud bots runs on GitHub (Actions tab) for a failed or skipped run.
- **info** (return) $2,462.81, +0.5% since the $2,450 start.

## Bot 6: QQQ trend: NEEDS ACTION
- **act** (schedule) Bot 10 should have run by Thu 09:50 ET but its log last changed Thu 11/12 09:42. Fix: Check the Cloud bots runs on GitHub (Actions tab) for a failed or skipped run.
- **info** (return) $1,665.98, -0.1% since the $1,667 start.

## Bot 7: Momentum: NEEDS ACTION
- **act** (schedule) Bot 11 should have run by Thu 09:50 ET but its log last changed Thu 11/12 09:42. Fix: Check the Cloud bots runs on GitHub (Actions tab) for a failed or skipped run.
- **info** (return) $1,676.40, +0.6% since the $1,667 start.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.