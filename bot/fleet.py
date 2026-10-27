"""The bot fleet: one place that says which bots exist, where their keys and logs live, when they
run, and what their backtests say is normal. Used by the data bot (bot.data_bot) and the
maintenance bot (bot.maintenance); the trading bots themselves don't read it.

Defaults match the 2026-10-27 lineup. To change an account, a folder or a limit without editing
code, put overrides in fleet.json next to .env, keyed by bot number, e.g.

    {"4": {"home": "C:/Users/baseb/Downloads/kalshi-run"}, "1": {"account": "QIE2"}}
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

CONFIG = Path("fleet.json")


@dataclass(frozen=True)
class Bot:
    num: int
    name: str
    kind: str  # "alpaca" or "kalshi"
    env_file: str  # where its keys live (never read for anything but the keys)
    account: str  # last 4 of the Alpaca account number it must trade on ("" = not checked)
    log_file: str
    home: str = "."  # folder the bot runs in (its logs and state files are there)
    days: str = "weekdays"  # "weekdays" or "daily"
    runs_at: str = "09:20"  # ET; the log should be newer than this on a run day
    start_equity: float = 5000.0
    # What the backtest says is normal. Past these, the maintenance bot raises a flag.
    max_drawdown_pct: float = 10.0  # backtest worst drop from peak; watch past it, act past 1.5x
    max_day_loss_pct: float = 5.0  # one day's loss that is out of character
    min_profit_factor: float = 1.0  # after min_trades closed trades, below this = act
    min_trades: int = 30  # fewer closed trades than this says little
    symbols: tuple[str, ...] = ()
    notes: str = ""
    extra: dict = field(default_factory=dict, compare=False, hash=False)

    def path(self, name: str) -> Path:
        return Path(self.home) / name


ROTATION_ETFS = ("SPY", "QQQ", "IWM", "EFA", "EEM", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "GLD", "TLT")

FLEET: list[Bot] = [
    Bot(1, "ORB day trader", "alpaca", ".env", "QIE2", "trades.log", days="weekdays", runs_at="09:45",
        # Tuned ORB, 3 years: worst drop 2.6%, out-of-sample PF 1.22. Risk halt at -2% a day.
        max_drawdown_pct=2.6, max_day_loss_pct=2.0, min_profit_factor=1.0, min_trades=30,
        symbols=("SPY", "QQQ", "AAPL", "MSFT", "NVDA"),
        notes="Flat by 3:50pm every day; any position after the close is a problem."),
    Bot(2, "ETF rotation", "alpaca", ".env.rotation", "8T7Y", "rotation.log", days="weekdays", runs_at="09:55",
        # 20 years top 3 / 3 months / cash: 9.6%/yr, worst drop -26%.
        max_drawdown_pct=26.0, max_day_loss_pct=6.0, min_profit_factor=0, min_trades=0,
        symbols=ROTATION_ETFS, notes="Trades once a month; holdings should match rotation_state.json."),
    Bot(3, "Crypto trend", "alpaca", ".env.crypto", "KTS7", "crypto.log", days="daily", runs_at="20:20",
        # 12 years BTC/ETH above the 50-day: worst drops -29% to -60%.
        max_drawdown_pct=45.0, max_day_loss_pct=15.0, min_profit_factor=0, min_trades=0,
        symbols=("BTC/USD", "ETH/USD"), notes="Holds a coin only while it closes above its 50-day average."),
    Bot(4, "Kalshi", "kalshi", ".env.kalshi", "", "kalshi_paper.log", days="daily", runs_at="00:00",
        start_equity=20.0, max_drawdown_pct=10.0, max_day_loss_pct=10.0, min_profit_factor=0, min_trades=0,
        notes="Locked-in trades only, so any loss means a leg missed or a market was misread."),
]


def load(config: Path = CONFIG) -> list[Bot]:
    """FLEET with fleet.json overrides applied. Unknown keys go to Bot.extra."""
    if not config.exists():
        return list(FLEET)
    over = json.loads(config.read_text())
    names = set(Bot.__dataclass_fields__)
    out = []
    for b in FLEET:
        o = dict(over.get(str(b.num), {}))
        known = {k: (tuple(v) if k == "symbols" else v) for k, v in o.items() if k in names and k != "extra"}
        extra = {k: v for k, v in o.items() if k not in names}
        out.append(replace(b, **known, extra={**b.extra, **extra}))
    return out


def by_num(bots: list[Bot]) -> dict[int, Bot]:
    return {b.num: b for b in bots}
