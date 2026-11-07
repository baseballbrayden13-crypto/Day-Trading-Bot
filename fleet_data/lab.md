# Lab, week 2026-45 (2026-11-07)

Fresh data, after fees. Nothing was changed.

## Bot 1: ORB day trader: holding up

| Window | Trades | Profit factor | P&L ($ for bot 1, % for 2-3) |
|---|---|---|---|
| last 90 days | 63 | 0.82 | -26.3 |
| last year | 281 | 1.16 | 104.65 |
| before that | 565 | 1.31 | 380.41 |

## Bot 2: ETF rotation: in line with its design

| Window | Trades | Profit factor | P&L ($ for bot 1, % for 2-3) |
|---|---|---|---|
| last year |  |  | 10.8 |
| last year, holding SPY |  |  | 10.9 |

## Bot 3: Crypto trend: in line with its design

| Window | Trades | Profit factor | P&L ($ for bot 1, % for 2-3) |
|---|---|---|---|
| BTC-USD last year |  |  | 10.8 |
| BTC-USD last year, holding |  |  | -26.6 |
| ETH-USD last year |  |  | 22.5 |
| ETH-USD last year, holding |  |  | -34.7 |

No experiment queued. Add one line to fleet_data/lab_queue.txt, e.g. `--set ORB_TARGET_R=1.25,1.5 --label target`.
