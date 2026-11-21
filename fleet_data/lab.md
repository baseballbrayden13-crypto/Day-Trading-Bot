# Lab, week 2026-47 (2026-11-21)

Fresh data, after fees. Nothing was changed.

## Bot 1: ORB day trader: holding up

| Window | Trades | Profit factor | P&L ($ for bot 1, % for 2-3) |
|---|---|---|---|
| last 90 days | 66 | 0.73 | -45.24 |
| last year | 276 | 1.15 | 95.12 |
| before that | 571 | 1.26 | 343.24 |

## Bot 2: ETF rotation: in line with its design

| Window | Trades | Profit factor | P&L ($ for bot 1, % for 2-3) |
|---|---|---|---|
| last year |  |  | 10.7 |
| last year, holding SPY |  |  | 6.9 |

## Bot 3: Crypto trend: in line with its design

| Window | Trades | Profit factor | P&L ($ for bot 1, % for 2-3) |
|---|---|---|---|
| BTC-USD last year |  |  | 10.8 |
| BTC-USD last year, holding |  |  | -29.2 |
| ETH-USD last year |  |  | 22.5 |
| ETH-USD last year, holding |  |  | -39.1 |

No experiment queued. Add one line to fleet_data/lab_queue.txt, e.g. `--set ORB_TARGET_R=1.25,1.5 --label target`.
