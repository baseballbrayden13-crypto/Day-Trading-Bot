"""Settings loaded from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


@dataclass
class Settings:
    # Broker
    alpaca_key: str = field(default_factory=lambda: os.getenv("ALPACA_API_KEY", ""))
    alpaca_secret: str = field(default_factory=lambda: os.getenv("ALPACA_SECRET_KEY", ""))
    # Live trading needs BOTH flags. Anything else means paper.
    live_trading: bool = field(default_factory=lambda: _bool("LIVE_TRADING", False))
    live_confirm: str = field(default_factory=lambda: os.getenv("LIVE_TRADING_CONFIRM", ""))

    # What to trade
    symbols: list[str] = field(
        default_factory=lambda: [s.strip().upper() for s in os.getenv("SYMBOLS", "SPY,QQQ,AAPL,MSFT,NVDA").split(",") if s.strip()]
    )
    bar_minutes: int = field(default_factory=lambda: _int("BAR_MINUTES", 5))

    # Strategy: a name from STRATEGIES in bot/strategy.py, e.g. ema_cross (default) or orb.
    strategy: str = field(default_factory=lambda: os.getenv("STRATEGY", "ema_cross").strip().lower())
    orb_minutes: int = field(default_factory=lambda: _int("ORB_MINUTES", 15))
    orb_target_r: float = field(default_factory=lambda: _float("ORB_TARGET_R", 2.0))  # target = 2x the risk
    orb_max_per_day: int = field(default_factory=lambda: _int("ORB_MAX_PER_DAY", 1))  # breakouts per stock per day
    orb_last_entry: str = field(default_factory=lambda: os.getenv("ORB_LAST_ENTRY", "").strip())  # e.g. 11:30 ET; empty = all day
    # Optional ORB filters, all off by default (see bot/strategy.py orb_signal)
    orb_stop: str = field(default_factory=lambda: os.getenv("ORB_STOP", "low").strip().lower())  # low or mid of the range
    orb_vwap_filter: bool = field(default_factory=lambda: _bool("ORB_VWAP_FILTER", False))  # breakout must be above VWAP
    orb_volume_mult: float = field(default_factory=lambda: _float("ORB_VOLUME_MULT", 0))  # breakout volume vs 20-bar avg; 0 = off
    orb_max_range_pct: float = field(default_factory=lambda: _float("ORB_MAX_RANGE_PCT", 0))  # skip wider ranges, % of price; 0 = off
    orb_gap: str = field(default_factory=lambda: os.getenv("ORB_GAP", "any").strip().lower())  # any, up or down
    gap_min_pct: float = field(default_factory=lambda: _float("GAP_MIN_PCT", 1.0))  # gap_reversal: minimum gap down, %
    ema_fast: int = field(default_factory=lambda: _int("EMA_FAST", 9))
    ema_slow: int = field(default_factory=lambda: _int("EMA_SLOW", 21))
    rsi_period: int = field(default_factory=lambda: _int("RSI_PERIOD", 14))
    atr_period: int = field(default_factory=lambda: _int("ATR_PERIOD", 14))
    stop_atr: float = field(default_factory=lambda: _float("STOP_ATR", 1.5))
    target_atr: float = field(default_factory=lambda: _float("TARGET_ATR", 3.0))
    vwap_rev_atr: float = field(default_factory=lambda: _float("VWAP_REV_ATR", 1.5))  # how far below VWAP, in ATRs
    vwap_rev_rsi: float = field(default_factory=lambda: _float("VWAP_REV_RSI", 30))  # RSI must be under this
    bb_period: int = field(default_factory=lambda: _int("BB_PERIOD", 20))
    bb_std: float = field(default_factory=lambda: _float("BB_STD", 2.0))
    # Only buy when this symbol (e.g. SPY) is above its session VWAP. Empty = off.
    market_filter: str = field(default_factory=lambda: os.getenv("MARKET_FILTER", "").strip().upper())

    # Risk
    risk_per_trade: float = field(default_factory=lambda: _float("RISK_PER_TRADE", 0.005))  # 0.5% of equity
    max_position_pct: float = field(default_factory=lambda: _float("MAX_POSITION_PCT", 0.20))  # 20% of equity
    max_open_positions: int = field(default_factory=lambda: _int("MAX_OPEN_POSITIONS", 3))
    max_daily_loss_pct: float = field(default_factory=lambda: _float("MAX_DAILY_LOSS_PCT", 0.02))  # stop for the day at -2%
    max_trades_per_day: int = field(default_factory=lambda: _int("MAX_TRADES_PER_DAY", 10))
    no_entry_first_minutes: int = field(default_factory=lambda: _int("NO_ENTRY_FIRST_MINUTES", 15))
    flatten_minutes_before_close: int = field(default_factory=lambda: _int("FLATTEN_MINUTES_BEFORE_CLOSE", 10))

    # Backtest costs
    slippage_bps: float = field(default_factory=lambda: _float("SLIPPAGE_BPS", 2.0))
    commission_per_share: float = field(default_factory=lambda: _float("COMMISSION_PER_SHARE", 0.0))
    # Regulatory fees Alpaca passes through on every sell. Defaults are deliberately on the high side;
    # check https://alpaca.markets/support/regulatory-fees for the current rates.
    sec_fee_rate: float = field(default_factory=lambda: _float("SEC_FEE_RATE", 0.0000278))  # per $ of sale value
    taf_per_share: float = field(default_factory=lambda: _float("TAF_PER_SHARE", 0.000195))  # FINRA TAF per share sold
    taf_max: float = field(default_factory=lambda: _float("TAF_MAX", 9.79))  # TAF cap per trade

    # Optional Claude trade reviewer
    ai_review: bool = field(default_factory=lambda: _bool("AI_REVIEW", False))
    ai_model: str = field(default_factory=lambda: os.getenv("AI_MODEL", "claude-opus-5-5"))
    ai_min_confidence: float = field(default_factory=lambda: _float("AI_MIN_CONFIDENCE", 0.6))
    ai_news: bool = field(default_factory=lambda: _bool("AI_NEWS", True))  # give the reviewer Alpaca headlines

    @property
    def is_live(self) -> bool:
        return self.live_trading and self.live_confirm == "I_UNDERSTAND_REAL_MONEY"
