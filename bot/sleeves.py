"""Shared accounts: several bots on one Alpaca paper account, each with its own slice ("sleeve") of the money.

A sleeve is a small ledger in sleeves.json: the bot's cash and the shares it bought. A bot only sizes trades
from its sleeve's value (its cash plus its own shares at today's price) and only ever sells its own shares,
so it can never spend another bot's money or sell another bot's stocks. The bots on one account must trade
different symbols (checked at start).

Set on the account's run as SLEEVES="2=5000,5=5000" (bot=starting dollars). A sleeve that doesn't exist yet
is opened with that amount; if the account already holds some of that bot's symbols (bot 2 before sleeves
existed), they become the sleeve's shares and its cash is what's left of the amount.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

LEDGER = Path("sleeves.json")
log = logging.getLogger("sleeves")


def budgets(spec: str | None = None) -> dict[str, float]:
    """"2=5000,5=5000" -> {"2": 5000.0, "5": 5000.0}. Empty means this account isn't shared."""
    spec = os.getenv("SLEEVES", "") if spec is None else spec
    out = {}
    for part in spec.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = float(v)
    return out


def load(path: Path = LEDGER) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save(ledger: dict, path: Path = LEDGER) -> None:
    path.write_text(json.dumps(ledger, indent=1, sort_keys=True))


class Sleeve:
    def __init__(self, ledger: dict, bot: str, symbols: list[str]):
        self.ledger, self.bot, self.symbols = ledger, bot, set(symbols)
        self.book = ledger[bot]

    @property
    def shares(self) -> dict[str, float]:
        return {s: q for s, q in self.book["shares"].items() if q > 1e-9}

    @property
    def cash(self) -> float:
        return self.book["cash"]

    def value(self, prices: dict[str, float]) -> float:
        return self.cash + sum(q * prices.get(s, 0) for s, q in self.shares.items())

    def record(self, symbol: str, qty: float, price: float) -> None:
        """A fill: qty > 0 bought, < 0 sold, at `price` a share."""
        if symbol not in self.symbols:
            raise ValueError(f"bot {self.bot} doesn't trade {symbol}")
        self.book["shares"][symbol] = self.book["shares"].get(symbol, 0) + qty
        self.book["cash"] -= qty * price
        self.book.setdefault("trades", []).append([time.strftime("%Y-%m-%dT%H:%M:%S"), symbol, qty, price])
        self.book["trades"] = self.book["trades"][-500:]


def open_sleeve(ledger: dict, bot: str, symbols: list[str], start: float, account_qty: dict[str, float],
                prices: dict[str, float], others: dict[str, list[str]] | None = None) -> Sleeve:
    """This bot's sleeve, opened with `start` dollars the first time. Refuses symbols another bot on the
    account also trades, and adopts shares of its own symbols already in the account."""
    for other, syms in (others or {}).items():
        both = set(symbols) & set(syms)
        if other != bot and both:
            raise SystemExit(f"Bots {bot} and {other} share this account but both trade {sorted(both)}.")
    if bot not in ledger:
        mine = {s: q for s, q in account_qty.items() if s in set(symbols) and q}
        ledger[bot] = {"start": start, "cash": start - sum(q * prices.get(s, 0) for s, q in mine.items()),
                       "shares": mine, "opened": time.strftime("%Y-%m-%d")}
        log.info("Opened bot %s's sleeve with $%.2f%s", bot, start, f", adopting {mine}" if mine else "")
    return Sleeve(ledger, bot, symbols)


def ready(ledger: dict, shares: dict[str, float], account_equity: float) -> bool:
    """Open new sleeves only once the account holds enough for all of them (e.g. after a reset to the total),
    so a half-funded account never leaves a sleeve counting money that isn't there."""
    return all(b in ledger for b in shares) or account_equity >= sum(shares.values()) * 0.95


def check_account(ledger: dict, account_qty: dict[str, float]) -> list[str]:
    """Problems: a sleeve says it owns more of a symbol than the account holds."""
    owned: dict[str, float] = {}
    for book in ledger.values():
        for s, q in book.get("shares", {}).items():
            owned[s] = owned.get(s, 0) + q
    return [f"{s}: sleeves own {q:g}, account holds {account_qty.get(s, 0):g}"
            for s, q in owned.items() if q > account_qty.get(s, 0) + 1e-6]


def wait_fill(client, order_id, timeout: float = 60) -> tuple[float, float]:
    """(filled qty, average price) of an order once it's done, or what filled by the timeout."""
    deadline = time.time() + timeout
    while True:
        o = client.get_order_by_id(order_id)
        status = str(getattr(o.status, "value", o.status))
        if status in {"filled", "canceled", "expired", "rejected", "done_for_day"} or time.time() > deadline:
            return float(o.filled_qty or 0), float(o.filled_avg_price or 0)
        time.sleep(1)
