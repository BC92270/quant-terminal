"""Transparent L1/L2 microstructure calculations.

Order-flow imbalance follows the best-quote event formulation of Cont,
Kukanov and Stoikov.  Replenishment and cancellation rates are intentionally
not inferred from snapshots; they require sequenced provider messages.
"""

from __future__ import annotations

import math
from typing import Iterable, Mapping


def _non_negative(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return number


def queue_imbalance(bid_size: float | None, ask_size: float | None) -> float | None:
    if bid_size is None or ask_size is None:
        return None
    bid = _non_negative(bid_size, "bid_size")
    ask = _non_negative(ask_size, "ask_size")
    total = bid + ask
    return None if total == 0.0 else (bid - ask) / total


def microprice(
    best_bid: float | None,
    best_ask: float | None,
    bid_size: float | None,
    ask_size: float | None,
) -> float | None:
    if None in (best_bid, best_ask, bid_size, ask_size):
        return None
    bid = float(best_bid)
    ask = float(best_ask)
    if not (math.isfinite(bid) and math.isfinite(ask)) or bid > ask:
        raise ValueError("Quotes must be finite and non-crossed")
    bid_q = _non_negative(float(bid_size), "bid_size")
    ask_q = _non_negative(float(ask_size), "ask_size")
    total = bid_q + ask_q
    if total == 0.0:
        return None
    value = (ask * bid_q + bid * ask_q) / total
    return min(max(value, bid), ask)


def order_flow_imbalance(quotes: Iterable[Mapping[str, float]]) -> float | None:
    rows = list(quotes)
    if len(rows) < 2:
        return None
    total = 0.0
    for previous, current in zip(rows, rows[1:]):
        pb0, pa0 = float(previous["best_bid"]), float(previous["best_ask"])
        qb0 = _non_negative(previous["bid_size"], "bid_size")
        qa0 = _non_negative(previous["ask_size"], "ask_size")
        pb1, pa1 = float(current["best_bid"]), float(current["best_ask"])
        qb1 = _non_negative(current["bid_size"], "bid_size")
        qa1 = _non_negative(current["ask_size"], "ask_size")
        if pb0 > pa0 or pb1 > pa1:
            raise ValueError("Crossed quote in OFI sequence")
        bid_event = (qb1 if pb1 >= pb0 else 0.0) - (qb0 if pb1 <= pb0 else 0.0)
        ask_event = -(qa1 if pa1 <= pa0 else 0.0) + (qa0 if pa1 >= pa0 else 0.0)
        total += bid_event + ask_event
    return total


def trade_imbalance(buy_volume: float | None, sell_volume: float | None) -> float | None:
    if buy_volume is None or sell_volume is None:
        return None
    buys = _non_negative(buy_volume, "buy_volume")
    sells = _non_negative(sell_volume, "sell_volume")
    total = buys + sells
    return None if total == 0.0 else (buys - sells) / total
