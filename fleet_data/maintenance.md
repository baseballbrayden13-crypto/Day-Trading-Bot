# Medic report, Wed Oct 28 2026 10:36 ET

## Since the last check
- New: Bot 1: trades.log doesn't exist in ., so bot 1 has never run here.

## Whole fleet: OK
- **info** (events) Coming up: MSFT earnings Wed 10/28. Odd results around these days are normal.

## Bot 1: ORB day trader: NEEDS ACTION
- **act** (schedule) trades.log doesn't exist in ., so bot 1 has never run here. Fix: Check the Cloud bots run on GitHub (Actions tab) and that its keys are in the repository secrets.
- **info** (return) $5,002.80, +0.1% since the $5,000 start.
- **info** (performance) 1 closed trades so far; 30 are needed before the results say anything about the strategy.
- **ok** (replay) 2026-10-28: bot 1 did what the backtest would have (0 entries).

## Bot 2: ETF rotation: NEEDS ACTION
- **act** (schedule) rotation.log doesn't exist in ., so bot 2 has never run here. Fix: Check the Cloud bots run on GitHub (Actions tab) and that its keys are in the repository secrets.
- **info** (return) $5,018.30, +0.4% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot +0.4% vs just holding SPY +1.4%.

## Bot 3: Crypto trend: NEEDS ACTION
- **act** (schedule) crypto.log doesn't exist in ., so bot 3 has never run here. Fix: Check the Cloud bots run on GitHub (Actions tab) and that its keys are in the repository secrets.
- **info** (return) $5,000.00, +0.0% since the $5,000 start.
- **info** (vs hold) Since 2026-10-23: bot +0.0% vs just holding BTC/USD + ETH/USD -1.0%.

## Bot 4: Kalshi paper: OK
- **info** (performance) No Bot 4 trades yet. Expected: the 14-day backtest found 0 taker trades worth $0.10.

## Bot 4c: Kalshi maker paper: OK
- **info** (performance) No Bot 4c trades yet; 1 maker quotes resting.

Medic only reads. Proposed changes are in fleet_data/proposals.csv; none were applied.