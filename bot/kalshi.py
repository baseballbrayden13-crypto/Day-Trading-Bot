"""Kalshi bot math: fees, order books and locked-in baskets. No network here (see bot.kalshi_live).

The trade it looks for: in a mutually exclusive event (at most one market can resolve YES, e.g. "Who
wins the race?") buy NO on a group of its markets. At most one of them can lose, so k sets of NO on
n markets always pay at least k x (n - 1) dollars. When that beats the price plus Kalshi's fees by
$0.10 or more, the profit is locked in no matter who wins.

Per set, market i adds (1 - NO ask_i - fee_i) and the basket costs one dollar on top, so a market is
worth including whenever its YES bid is above its fee, and the trade works when the YES bids add up
to more than $1 plus fees. Markets that can't help are left out.

The YES basket (buy YES on every market) is only locked in if one of them must win, which Kalshi
doesn't promise, so it is logged for research but never traded.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal

D = Decimal
ONE = D(1)
CENT = D("0.01")
FEE_RATE = D("0.07")  # Kalshi's general taker fee: ceil_to_cent(0.07 x contracts x P x (1 - P))


def fee(count: int, price: Decimal, multiplier: Decimal = ONE) -> Decimal:
    """Kalshi trading fee for `count` contracts at `price` dollars, rounded up to the cent (worst case:
    Kalshi rounds per fill and rebates part of the rounding later)."""
    if count <= 0:
        return D(0)
    raw = FEE_RATE * multiplier * count * price * (ONE - price)
    return raw.quantize(CENT, rounding=ROUND_CEILING)


def asks_from_bids(opposite_bids: list) -> list[tuple[Decimal, int]]:
    """Kalshi books only list bids. A YES bid at p is a NO ask at 1 - p, so the NO asks (cheapest first)
    come from the YES bids (listed cheapest first, best bid last). Fractional sizes round down."""
    out = []
    for price, size in reversed(opposite_bids):
        n = int(D(str(size)))
        if n > 0:
            out.append((ONE - D(str(price)), n))
    return out


@dataclass
class Fill:
    count: int
    cost: Decimal  # dollars paid, before fees
    fee: Decimal
    worst: Decimal  # highest price paid, used as the order's limit


def buy(asks: list[tuple[Decimal, int]], count: int, multiplier: Decimal = ONE) -> Fill | None:
    """Cost of buying `count` contracts by walking up the asks. None if the book is too thin.
    Fees are charged per price level and each rounded up, which is never less than Kalshi charges."""
    left, cost, fees, worst = count, D(0), D(0), D(0)
    for price, size in asks:
        take = min(left, size)
        cost += price * take
        fees += fee(take, price, multiplier)
        worst, left = price, left - take
        if left == 0:
            return Fill(count, cost, fees, worst)
    return None


@dataclass
class Leg:
    ticker: str
    side: str  # "no" or "yes": the contract being bought
    count: int
    cost: Decimal
    fee: Decimal
    limit: Decimal  # worst price (on this side's scale) the order may pay


@dataclass
class Basket:
    event_ticker: str
    series_ticker: str
    title: str
    kind: str  # "no_basket" (locked in) or "yes_basket" (research only)
    sets: int
    legs: list[Leg]
    payout_min: Decimal  # dollars it pays at worst
    close_time: str = ""
    locked: bool = True
    fee_multiplier: Decimal = ONE
    extra: dict = field(default_factory=dict)

    @property
    def outlay(self) -> Decimal:
        return sum((l.cost + l.fee for l in self.legs), D(0))

    @property
    def fees(self) -> Decimal:
        return sum((l.fee for l in self.legs), D(0))

    @property
    def profit(self) -> Decimal:
        return self.payout_min - self.outlay

    def days_to_close(self, now: datetime | None = None) -> float:
        if not self.close_time:
            return 365.0
        end = datetime.fromisoformat(self.close_time.replace("Z", "+00:00"))
        return max((end - (now or datetime.now(timezone.utc))).total_seconds() / 86400, 0.0)

    def score(self, now: datetime | None = None) -> float:
        """Profit per dollar per day locked up, so a quick 10c beats a slow 15c on a small budget."""
        return float(self.profit / self.outlay) / max(self.days_to_close(now), 1.0) if self.outlay > 0 else 0.0


def no_basket(event: dict, books: dict[str, list[tuple[Decimal, int]]], budget: Decimal,
              max_sets: int = 50, multiplier: Decimal = ONE) -> Basket | None:
    """Most profitable NO basket that fits the budget, or None. `books` maps ticker -> NO asks."""
    best = None
    for k in range(1, max_sets + 1):
        legs = []
        for ticker, asks in books.items():
            f = buy(asks, k, multiplier)
            if f and k - f.cost - f.fee > 0:  # this market adds to the locked payout
                legs.append(Leg(ticker, "no", k, f.cost, f.fee, f.worst))
        if len(legs) < 2:
            continue
        b = Basket(event["event_ticker"], event.get("series_ticker", ""), event.get("title", ""), "no_basket",
                   k, legs, D(k * (len(legs) - 1)), event.get("close_time", ""), True, multiplier)
        if b.outlay > budget:
            break  # more sets only cost more
        if b.profit > 0 and (best is None or b.profit > best.profit):
            best = b
    return best


def yes_basket(event: dict, books: dict[str, list[tuple[Decimal, int]]], budget: Decimal,
               max_sets: int = 50, multiplier: Decimal = ONE) -> Basket | None:
    """YES on every market: pays k only if one of them must win, which isn't guaranteed. Research only."""
    best = None
    for k in range(1, max_sets + 1):
        fills = {t: buy(a, k, multiplier) for t, a in books.items()}
        if not fills or any(f is None for f in fills.values()):
            break
        legs = [Leg(t, "yes", k, f.cost, f.fee, f.worst) for t, f in fills.items()]
        b = Basket(event["event_ticker"], event.get("series_ticker", ""), event.get("title", ""), "yes_basket",
                   k, legs, D(k), event.get("close_time", ""), False, multiplier)
        if b.outlay > budget:
            break
        if b.profit > 0 and (best is None or b.profit > best.profit):
            best = b
    return best


def pick(baskets: list[Basket], budget: Decimal, min_profit: Decimal, now: datetime | None = None) -> list[Basket]:
    """Locked-in baskets worth at least `min_profit`, best return per day first, while the budget lasts."""
    chosen, left = [], budget
    for b in sorted((b for b in baskets if b.locked and b.profit >= min_profit), key=lambda b: -b.score(now)):
        if b.outlay <= left:
            chosen.append(b)
            left -= b.outlay
    return chosen


def stake(base: Decimal, realized: Decimal, settled: int, step: Decimal = D("0.25"), min_settled: int = 5) -> Decimal:
    """How much the bot may have in play. It starts at `base` ($20) and goes up one level each time
    settled profit grows the pot by another `step` (25%): $20 -> $25 -> $31.25 -> ... Profit in
    between is kept aside, not bet. No step-ups before `min_settled` baskets have paid out, so one
    lucky trade can't raise the bets. After a loss it drops to the level the pot still covers, and
    below `base` it bets only what's left."""
    pot = base + realized
    if pot < base:
        return max(pot, D(0))
    level = base
    if settled >= min_settled:
        while level * (1 + step) <= pot:
            level *= 1 + step
    return level.quantize(CENT)
