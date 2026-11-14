# Lab, week 2026-46 (2026-11-14)

Fresh data, after fees. Nothing was changed.

## Bot 1: ORB day trader: holding up

| Window | Trades | Profit factor | P&L ($ for bot 1, % for 2-3) |
|---|---|---|---|
| last 90 days | 65 | 0.87 | -18.34 |
| last year | 283 | 1.17 | 114.77 |
| before that | 565 | 1.29 | 367.52 |

## Bot 2: ETF rotation: in line with its design

| Window | Trades | Profit factor | P&L ($ for bot 1, % for 2-3) |
|---|---|---|---|
| last year |  |  | 12.7 |
| last year, holding SPY |  |  | 13.5 |

## Bot 3: Crypto trend: in line with its design

| Window | Trades | Profit factor | P&L ($ for bot 1, % for 2-3) |
|---|---|---|---|
| BTC-USD last year |  |  | 10.8 |
| BTC-USD last year, holding |  |  | -29.9 |
| ETH-USD last year |  |  | 22.5 |
| ETH-USD last year, holding |  |  | -40.2 |

No experiment queued. Add one line to fleet_data/lab_queue.txt, e.g. `--set ORB_TARGET_R=1.25,1.5 --label target`.
