import pandas as pd

from bot.site_data import bar_rows, rank_rows


def test_bar_rows_opening_range_and_averages():
    idx = pd.date_range("2026-10-28 09:30", periods=5, freq="5min", tz="America/New_York")
    df = pd.DataFrame({"open": [10, 11, 12, 13, 14], "high": [11, 13, 12, 15, 16], "low": [9, 10, 8, 12, 13],
                       "close": [10, 12, 11, 14, 15], "volume": [100] * 5}, index=idx)
    rows = bar_rows(df)
    assert [r[2] for r in rows] == ["09:30", "09:35", "09:40", "09:45", "09:50"]
    assert rows[0][10:12] == ["11.00", "9.00"]   # range so far after the first bar
    assert rows[4][10:12] == ["13.00", "8.00"]   # fixed to the first 3 bars afterwards
    assert rows[4][8] == round((11 + 14 + 15) / 3, 2)
    assert rows[4][-1] == 0


def test_rank_rows_sorted_with_picks():
    n = 260
    close = pd.DataFrame({"UP": [100 + i for i in range(n)], "FLAT": [100.0] * n,
                          "DOWN": [400 - i for i in range(n)]})
    rows = rank_rows(close)
    assert [r[0] for r in rows] == ["UP", "FLAT", "DOWN"]
    assert rows[0][2] == "yes" and rows[2][2] == "no"
