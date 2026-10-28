"""Chart data for the Strategy Lab site, written next to the other fleet_data files so the site
can be fed from the bot-state branch without the PC.

    python -m bot.site_data            # from state/: writes fleet_data/bars.csv and fleet_data/rank.csv

bars.csv: today's SPY 5-minute bars for bot 1's chart, with 3- and 9-bar averages and the
opening range (high/low of the first 3 bars). rank.csv: bot 2's 3-month ranking of its ETFs,
picked = what the rotation rule would hold today. Read-only: uses bot 1's keys for market data.
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from .rotation import DEFAULT, targets

OUT = Path("fleet_data")
BARS_COLS = "bot symbol t o h l c v ma_fast ma_slow ref_hi ref_lo sample".split()
log = logging.getLogger("site_data")


def bar_rows(df: pd.DataFrame, bot: int = 1, symbol: str = "SPY") -> list[list]:
    """df: one day of bars (open/high/low/close/volume) with an ET index."""
    rows, closes = [], []
    if df.empty:
        return rows
    hi, lo = df["high"].iloc[:3].max(), df["low"].iloc[:3].min()
    for i, (t, r) in enumerate(df.iterrows()):
        closes.append(r["close"])
        fast, slow = sum(closes[-3:]) / len(closes[-3:]), sum(closes[-9:]) / len(closes[-9:])
        rh, rl = (df["high"].iloc[:i + 1].max(), df["low"].iloc[:i + 1].min()) if i < 3 else (hi, lo)
        rows.append([bot, symbol, t.strftime("%H:%M"), f"{r['open']:.2f}", f"{r['high']:.2f}", f"{r['low']:.2f}",
                     f"{r['close']:.2f}", int(r["volume"]), round(fast, 2), round(slow, 2), f"{rh:.2f}", f"{rl:.2f}", 0])
    return rows


def rank_rows(close: pd.DataFrame, lookback: int = 3) -> list[list]:
    """close: daily closes, one column per ETF. Sorted best first."""
    if len(close) < 21 * lookback + 1:
        return []
    mom = close.iloc[-1] / close.iloc[-1 - 21 * lookback] - 1
    picked = targets(close, top=3, lookback=lookback)
    return [[s, round(float(m), 4), "yes" if s in picked else "no", 0] for s, m in mom.dropna().sort_values(ascending=False).items()]


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from dotenv import load_dotenv

    load_dotenv(".env")
    from .config import Settings
    from .data import from_alpaca
    from .rotation_live import ET, daily_closes

    cfg = Settings()
    try:
        df = from_alpaca("SPY", 1, cfg, realtime=True)
        df.index = df.index.tz_convert(ET)
        df = df[df.index.date == datetime.now(ET).date()]
        if not df.empty:
            _write(OUT / "bars.csv", BARS_COLS, bar_rows(df))
    except Exception as e:  # the chart is nice to have; never fail the bot's job over it
        log.warning("bars: %s", e)
    try:
        rows = rank_rows(daily_closes(DEFAULT.split(","), cfg))
        if rows:
            _write(OUT / "rank.csv", ["etf", "ret_3m", "picked", "sample"], rows)
    except Exception as e:
        log.warning("rank: %s", e)


if __name__ == "__main__":
    main()
