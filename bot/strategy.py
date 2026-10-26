"""Indicators and entry/exit signals.

Every strategy is long only and intraday, and is registered in STRATEGIES at
the bottom of this file. Pick one with STRATEGY in .env. To add a strategy,
write an entry function (and optionally an exit function) and register it;
the backtest, live loop and `python -m bot.compare` all pick it up.

  ema_cross       Fast EMA crosses above slow EMA, price above VWAP, RSI 50-70.
                  Exit on an ATR stop, an ATR target, or a bearish EMA cross.
  orb             First close above the opening range high.
  vwap_reversion  Price stretches well below VWAP with RSI oversold; target VWAP.
  bollinger       Close crosses back above the lower Bollinger band; target the middle band.
  pdh_break       First close above the previous day's high.
  gap_reversal    After a gap down, buy the first close back above the day's open; target the prior close.
  vwap_pullback   In an uptrend above VWAP, buy a bar that dips to VWAP and closes back above it.
  rsi2            Short-term dip: RSI(2) under 10 while above the slow EMA; exit when RSI(2) recovers.

These are starting points to test, not proven edges.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from .config import Settings


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    prev_close = df["close"].shift()
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP that resets each trading day. Index must be tz-aware timestamps."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    day = df.index.tz_convert("America/New_York").date
    pv = (typical * df["volume"]).groupby(day).cumsum()
    vol = df["volume"].groupby(day).cumsum()
    return pv / vol.replace(0, np.nan)


def add_indicators(df: pd.DataFrame, cfg: Settings) -> pd.DataFrame:
    out = df.copy()
    out["ema_fast"] = ema(out["close"], cfg.ema_fast)
    out["ema_slow"] = ema(out["close"], cfg.ema_slow)
    out["rsi"] = rsi(out["close"], cfg.rsi_period)
    out["atr"] = atr(out, cfg.atr_period)
    out["vwap"] = session_vwap(out)
    above = out["ema_fast"] > out["ema_slow"]
    out["cross_up"] = above & ~above.shift(1, fill_value=False)
    out["cross_down"] = ~above & above.shift(1, fill_value=False)
    mid = out["close"].rolling(cfg.bb_period).mean()
    out["bb_mid"] = mid
    out["bb_low"] = mid - cfg.bb_std * out["close"].rolling(cfg.bb_period).std()
    out["rsi2"] = rsi(out["close"], 2)
    out["vol_avg"] = out["volume"].rolling(20).mean().shift(1)  # average of the 20 bars before this one
    out = _add_daily_levels(out)
    out = _add_opening_range(out, cfg.orb_minutes, cfg.orb_max_per_day)
    return out


def _add_daily_levels(out: pd.DataFrame) -> pd.DataFrame:
    """Today's open, and yesterday's high and close (from completed sessions only)."""
    day = pd.Series(out.index.tz_convert("America/New_York").date, index=out.index)
    out["day_open"] = out["open"].groupby(day).transform("first")
    daily = out.groupby(day).agg(high=("high", "max"), close=("close", "last"))
    prev = daily.shift(1)
    out["prev_high"] = day.map(prev["high"]).astype(float)
    out["prev_close"] = day.map(prev["close"]).astype(float)
    return out


def _add_opening_range(out: pd.DataFrame, minutes: int, max_per_day: int = 1) -> pd.DataFrame:
    """High/low of the first `minutes` of each session, filled in only once that window has closed."""
    et = out.index.tz_convert("America/New_York")
    day = et.date
    mins_in = (et.hour * 60 + et.minute) - (9 * 60 + 30)
    in_range = mins_in < minutes
    out["or_high"] = out["high"].where(in_range).groupby(day).transform("max").where(~in_range)
    out["or_low"] = out["low"].where(in_range).groupby(day).transform("min").where(~in_range)
    above = (out["close"] > out["or_high"]).fillna(False)
    prev_above = above.groupby(day).shift(fill_value=False).astype(bool)
    cross = above & ~prev_above  # a close back above the range high after being at or below it
    out["orb_break"] = cross & (cross.astype(int).groupby(day).cumsum() <= max_per_day)
    return out


@dataclass
class Signal:
    symbol: str
    side: str  # "buy" or "sell"
    price: float
    stop: float
    target: float
    reason: str


def entry_signal(symbol: str, bars: pd.DataFrame, cfg: Settings) -> Signal | None:
    """Look at the last completed bar of indicator-enriched data."""
    return get_strategy(cfg.strategy).entry(symbol, bars, cfg)


def ema_cross_signal(symbol: str, bars: pd.DataFrame, cfg: Settings) -> Signal | None:
    if len(bars) < cfg.ema_slow + 2:
        return None
    row = bars.iloc[-1]
    if not (row["cross_up"] and row["close"] > row["vwap"] and 50 <= row["rsi"] <= 70):
        return None
    price = float(row["close"])
    a = float(row["atr"])
    if a <= 0 or np.isnan(a):
        return None
    return Signal(
        symbol=symbol,
        side="buy",
        price=price,
        stop=price - cfg.stop_atr * a,
        target=price + cfg.target_atr * a,
        reason=f"EMA{cfg.ema_fast}/{cfg.ema_slow} cross up, above VWAP, RSI {row['rsi']:.0f}",
    )


def orb_signal(symbol: str, bars: pd.DataFrame, cfg: Settings) -> Signal | None:
    """Opening-range breakout: buy the first close above the opening range high.
    Stop at the opening range low (or its midpoint), target at orb_target_r times the risk.
    The optional ORB_* filters below are all off by default."""
    row = bars.iloc[-1]
    if not row["orb_break"]:
        return None
    if cfg.orb_last_entry:
        h, m = map(int, cfg.orb_last_entry.split(":"))
        et = bars.index[-1].tz_convert("America/New_York")
        if et.hour * 60 + et.minute >= h * 60 + m:
            return None
    price = float(row["close"])
    if cfg.orb_vwap_filter and not price > row["vwap"]:
        return None
    if cfg.orb_volume_mult and not row["volume"] >= cfg.orb_volume_mult * row["vol_avg"]:
        return None
    if cfg.orb_max_range_pct and (row["or_high"] - row["or_low"]) / price * 100 > cfg.orb_max_range_pct:
        return None
    if cfg.orb_gap == "up" and not row["day_open"] > row["prev_close"]:
        return None
    if cfg.orb_gap == "down" and not row["day_open"] < row["prev_close"]:
        return None
    stop = float(row["or_low"]) if cfg.orb_stop == "low" else float(row["or_high"] + row["or_low"]) / 2
    if not price > stop:
        return None
    return Signal(
        symbol=symbol,
        side="buy",
        price=price,
        stop=stop,
        target=price + cfg.orb_target_r * (price - stop),
        reason=f"broke {cfg.orb_minutes}-min opening range high {row['or_high']:.2f}",
    )


def vwap_reversion_signal(symbol: str, bars: pd.DataFrame, cfg: Settings) -> Signal | None:
    """Buy the first bar that closes more than vwap_rev_atr ATRs below VWAP with RSI
    under vwap_rev_rsi. Target is VWAP, stop is stop_atr ATRs below the entry."""
    if len(bars) < cfg.atr_period + 2:
        return None

    def stretched(row) -> bool:
        return bool(row["close"] < row["vwap"] - cfg.vwap_rev_atr * row["atr"] and row["rsi"] < cfg.vwap_rev_rsi)

    row, prev = bars.iloc[-1], bars.iloc[-2]
    if not stretched(row) or stretched(prev):
        return None
    price, a = float(row["close"]), float(row["atr"])
    if a <= 0 or np.isnan(a):
        return None
    return Signal(
        symbol=symbol,
        side="buy",
        price=price,
        stop=price - cfg.stop_atr * a,
        target=float(row["vwap"]),
        reason=f"{(row['vwap'] - price) / a:.1f} ATR below VWAP, RSI {row['rsi']:.0f}",
    )


def bollinger_signal(symbol: str, bars: pd.DataFrame, cfg: Settings) -> Signal | None:
    """Buy when the close crosses back above the lower Bollinger band.
    Target is the middle band, stop is stop_atr ATRs below the entry."""
    if len(bars) < cfg.bb_period + 2:
        return None
    row, prev = bars.iloc[-1], bars.iloc[-2]
    if not (prev["close"] < prev["bb_low"] and row["close"] > row["bb_low"]):
        return None
    price, a, mid = float(row["close"]), float(row["atr"]), float(row["bb_mid"])
    if a <= 0 or np.isnan(a) or not mid > price:
        return None
    return Signal(
        symbol=symbol,
        side="buy",
        price=price,
        stop=price - cfg.stop_atr * a,
        target=mid,
        reason=f"closed back above lower band {row['bb_low']:.2f}",
    )


def _atr_bracket(symbol: str, row, reason: str, cfg: Settings) -> Signal | None:
    price, a = float(row["close"]), float(row["atr"])
    if a <= 0 or np.isnan(a):
        return None
    return Signal(symbol, "buy", price, price - cfg.stop_atr * a, price + cfg.target_atr * a, reason)


def pdh_break_signal(symbol: str, bars: pd.DataFrame, cfg: Settings) -> Signal | None:
    """Buy the first close above yesterday's high. ATR stop and target."""
    if len(bars) < 2:
        return None
    row, prev = bars.iloc[-1], bars.iloc[-2]
    pdh = row["prev_high"]
    if np.isnan(pdh) or not row["close"] > pdh:
        return None
    if prev["prev_high"] == pdh and prev["close"] > pdh:
        return None  # already above it on the previous bar today
    return _atr_bracket(symbol, row, f"broke yesterday's high {pdh:.2f}", cfg)


def gap_reversal_signal(symbol: str, bars: pd.DataFrame, cfg: Settings) -> Signal | None:
    """After opening at least gap_min_pct below yesterday's close, buy the first close back
    above today's open. Target yesterday's close (the gap fill), stop stop_atr ATRs below."""
    if len(bars) < 2:
        return None
    row, prev = bars.iloc[-1], bars.iloc[-2]
    pc, op = row["prev_close"], row["day_open"]
    if np.isnan(pc) or not op <= pc * (1 - cfg.gap_min_pct / 100):
        return None
    same_day = prev["day_open"] == op
    if not (row["close"] > op and (not same_day or prev["close"] <= op)):
        return None
    sig = _atr_bracket(symbol, row, f"gapped down {(1 - op / pc) * 100:.1f}%, back above the open", cfg)
    if sig is None or not pc > sig.price:
        return None
    sig.target = float(pc)
    return sig


def vwap_pullback_signal(symbol: str, bars: pd.DataFrame, cfg: Settings) -> Signal | None:
    """Fast EMA above slow EMA, the bar dips to VWAP and closes back above it, green bar."""
    if len(bars) < cfg.ema_slow + 2:
        return None
    row = bars.iloc[-1]
    if not (row["ema_fast"] > row["ema_slow"] and row["low"] <= row["vwap"] < row["close"] and row["close"] > row["open"]):
        return None
    return _atr_bracket(symbol, row, "pulled back to VWAP in an uptrend", cfg)


def rsi2_signal(symbol: str, bars: pd.DataFrame, cfg: Settings) -> Signal | None:
    """RSI(2) under 10 while price is above the slow EMA. Exits when RSI(2) gets back over 70."""
    if len(bars) < cfg.ema_slow + 2:
        return None
    row = bars.iloc[-1]
    if not (row["rsi2"] < 10 and row["close"] > row["ema_slow"]):
        return None
    return _atr_bracket(symbol, row, f"RSI(2) {row['rsi2']:.0f} dip above EMA{cfg.ema_slow}", cfg)


def rsi2_exit(bars: pd.DataFrame, cfg: Settings | None) -> bool:
    return bool(bars.iloc[-1]["rsi2"] > 70)


def market_ok(market_bars: pd.DataFrame | None) -> bool:
    """True when the market symbol's last close is above its session VWAP. No data = don't trade."""
    if market_bars is None or market_bars.empty:
        return False
    row = market_bars.iloc[-1]
    return bool(row["close"] > row["vwap"])


def exit_on_trend_break(bars: pd.DataFrame, cfg: Settings | None = None) -> bool:
    return get_strategy(cfg.strategy if cfg is not None else "ema_cross").exit(bars, cfg)


def ema_cross_exit(bars: pd.DataFrame, cfg: Settings | None) -> bool:
    return bool(bars.iloc[-1]["cross_down"])


def hold_to_bracket(bars: pd.DataFrame, cfg: Settings | None) -> bool:
    """Hold until the stop, the target, or the end of the day."""
    return False


@dataclass(frozen=True)
class Strategy:
    name: str
    entry: Callable[[str, pd.DataFrame, Settings], Signal | None]
    exit: Callable[[pd.DataFrame, Settings | None], bool] = hold_to_bracket


STRATEGIES: dict[str, Strategy] = {
    s.name: s
    for s in [
        Strategy("ema_cross", ema_cross_signal, ema_cross_exit),
        Strategy("orb", orb_signal),
        Strategy("vwap_reversion", vwap_reversion_signal),
        Strategy("bollinger", bollinger_signal),
        Strategy("pdh_break", pdh_break_signal),
        Strategy("gap_reversal", gap_reversal_signal),
        Strategy("vwap_pullback", vwap_pullback_signal),
        Strategy("rsi2", rsi2_signal, rsi2_exit),
    ]
}


def get_strategy(name: str) -> Strategy:
    try:
        return STRATEGIES[name]
    except KeyError:
        raise ValueError(f"unknown STRATEGY {name!r}; choose one of {', '.join(STRATEGIES)}") from None
