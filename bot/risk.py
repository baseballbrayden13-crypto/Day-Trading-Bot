"""Risk controls. These run before every order and can veto it."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time

from .config import Settings

MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


@dataclass
class RiskManager:
    cfg: Settings
    day: date | None = None
    start_equity: float = 0.0
    trades_today: int = 0
    halted: bool = False
    halt_reason: str = ""
    open_symbols: set[str] = field(default_factory=set)

    def new_day(self, day: date, equity: float) -> None:
        self.day = day
        self.start_equity = equity
        self.trades_today = 0
        self.halted = False
        self.halt_reason = ""

    def check_daily_loss(self, equity: float) -> None:
        if self.start_equity and equity <= self.start_equity * (1 - self.cfg.max_daily_loss_pct):
            self.halted = True
            self.halt_reason = f"daily loss limit hit ({equity:.2f} vs start {self.start_equity:.2f})"

    def in_entry_window(self, now_et: datetime) -> bool:
        m = _minutes(now_et.time())
        return (
            _minutes(MARKET_OPEN) + self.cfg.no_entry_first_minutes
            <= m
            < _minutes(MARKET_CLOSE) - self.cfg.flatten_minutes_before_close - 15
        )

    def must_flatten(self, now_et: datetime) -> bool:
        return _minutes(now_et.time()) >= _minutes(MARKET_CLOSE) - self.cfg.flatten_minutes_before_close

    def position_size(self, equity: float, price: float, stop: float) -> int:
        """Shares so that hitting the stop loses about risk_per_trade of equity,
        capped so one position never exceeds max_position_pct of equity."""
        per_share_risk = price - stop
        if per_share_risk <= 0 or price <= 0:
            return 0
        by_risk = (equity * self.cfg.risk_per_trade) / per_share_risk
        by_cap = (equity * self.cfg.max_position_pct) / price
        return max(0, math.floor(min(by_risk, by_cap)))

    def can_enter(self, symbol: str, now_et: datetime) -> tuple[bool, str]:
        if self.halted:
            return False, self.halt_reason
        if symbol in self.open_symbols:
            return False, "already holding"
        if len(self.open_symbols) >= self.cfg.max_open_positions:
            return False, "max open positions"
        if self.trades_today >= self.cfg.max_trades_per_day:
            return False, "max trades per day"
        if not self.in_entry_window(now_et):
            return False, "outside entry window"
        if self.cfg.skip_event_days:
            from .events import skip_reason

            reason = skip_reason(symbol, now_et.date())
            if reason:
                return False, reason
        return True, ""

    def record_entry(self, symbol: str) -> None:
        self.open_symbols.add(symbol)
        self.trades_today += 1

    def record_exit(self, symbol: str) -> None:
        self.open_symbols.discard(symbol)
