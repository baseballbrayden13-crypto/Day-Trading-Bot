"""Thin wrapper over Alpaca's trading API. Paper unless Settings.is_live."""
from __future__ import annotations

import logging

from .config import Settings

log = logging.getLogger(__name__)


class Broker:
    def __init__(self, cfg: Settings):
        from alpaca.trading.client import TradingClient

        if not cfg.alpaca_key or not cfg.alpaca_secret:
            raise SystemExit("Set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env first.")
        self.paper = not cfg.is_live
        if cfg.live_trading and self.paper:
            log.warning("LIVE_TRADING=true but LIVE_TRADING_CONFIRM is not set correctly. Staying on PAPER.")
        self.client = TradingClient(cfg.alpaca_key, cfg.alpaca_secret, paper=self.paper)
        log.info("Connected to Alpaca %s account", "PAPER" if self.paper else "*** LIVE ***")

    def equity(self) -> float:
        return float(self.client.get_account().equity)

    def market_open(self) -> bool:
        return bool(self.client.get_clock().is_open)

    def open_symbols(self) -> set[str]:
        return {p.symbol for p in self.client.get_all_positions()}

    def buy_bracket(self, symbol: str, qty: int, stop: float, target: float, limit: float | None = None):
        """Buy with an attached stop-loss and take-profit, so the position is protected
        at the broker even if this program crashes. Market order, or a limit order at `limit`."""
        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest, StopLossRequest, TakeProfitRequest

        args = dict(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round(target, 2)),
            stop_loss=StopLossRequest(stop_price=round(stop, 2)),
        )
        req = LimitOrderRequest(limit_price=round(limit, 2), **args) if limit else MarketOrderRequest(**args)
        return self.client.submit_order(req)

    def cancel_unfilled_entries(self) -> list[str]:
        """Cancel buy orders still waiting to fill (a limit entry gets one bar). Returns their symbols."""
        from alpaca.trading.enums import OrderSide, QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        open_orders = self.client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, side=OrderSide.BUY))
        for o in open_orders:
            self.client.cancel_order_by_id(o.id)
        return [o.symbol for o in open_orders]

    def close(self, symbol: str):
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        # Drop this symbol's bracket legs first, leaving other positions' protection alone.
        open_orders = self.client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol]))
        for o in open_orders:
            self.client.cancel_order_by_id(o.id)
        return self.client.close_position(symbol)

    def close_all(self):
        return self.client.close_all_positions(cancel_orders=True)
