# Lab, week 2026-44 (2026-10-31)

Fresh data, after fees. Nothing was changed.

## Bot 1: ORB day trader: holding up

| Window | Trades | Profit factor | P&L ($ for bot 1, % for 2-3) |
|---|---|---|---|
| last 90 days | 65 | 1.27 | 35.43 |
| last year | 287 | 1.15 | 105.56 |
| before that | 560 | 1.34 | 410.51 |

## Bot 2: ETF rotation: in line with its design

| Window | Trades | Profit factor | P&L ($ for bot 1, % for 2-3) |
|---|---|---|---|
| last year |  |  | 13.1 |
| last year, holding SPY |  |  | 12.4 |

## Bot 3: Crypto trend: in line with its design

| Window | Trades | Profit factor | P&L ($ for bot 1, % for 2-3) |
|---|---|---|---|
| BTC-USD last year |  |  | 10.8 |
| BTC-USD last year, holding |  |  | -29.4 |
| ETH-USD last year |  |  | 22.5 |
| ETH-USD last year, holding |  |  | -41.6 |

No experiment queued. Add one line to fleet_data/lab_queue.txt, e.g. `--set ORB_TARGET_R=1.25,1.5 --label target`.
