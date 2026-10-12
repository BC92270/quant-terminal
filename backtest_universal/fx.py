"""Historical multi-currency conversion graph."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import math
import re


_CURRENCY = re.compile(r"^[A-Z]{3}$")


class MissingFXRate(LookupError):
    """Raised when no contemporaneous conversion path exists."""


def _currency(value: str) -> str:
    code = str(value).strip().upper()
    if not _CURRENCY.fullmatch(code):
        raise ValueError(f"invalid currency code: {value!r}")
    return code


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc)


class FXMatrix:
    """Mutable point-in-time FX graph.

    ``set_rate("EUR", "USD", 1.08)`` means one EUR buys 1.08 USD.  The
    reciprocal edge is installed automatically and indirect paths are resolved
    deterministically with breadth-first search.
    """

    def __init__(self, base_currency: str = "USD") -> None:
        self.base_currency = _currency(base_currency)
        self._rates: dict[tuple[str, str], float] = {}
        self._as_of: dict[tuple[str, str], datetime] = {}
        self._valuation_at: datetime | None = None
        self._max_age_seconds: float | None = None

    def set_valuation_clock(
        self,
        at: datetime,
        *,
        max_age_seconds: float | None,
    ) -> None:
        stamp = _utc(at)
        if self._valuation_at is not None and stamp < self._valuation_at:
            raise ValueError("FX valuation clock cannot move backwards")
        if max_age_seconds is not None and float(max_age_seconds) < 0:
            raise ValueError("FX max age must be non-negative")
        self._valuation_at = stamp
        self._max_age_seconds = (
            None if max_age_seconds is None else float(max_age_seconds)
        )

    def _fresh(self, pair: tuple[str, str]) -> bool:
        if self._valuation_at is None or self._max_age_seconds is None:
            return True
        observed = self._as_of.get(pair)
        if observed is None or observed > self._valuation_at:
            return False
        return (self._valuation_at - observed).total_seconds() <= self._max_age_seconds

    def set_rate(
        self,
        base_currency: str,
        quote_currency: str,
        rate: float,
        *,
        as_of: datetime | None = None,
    ) -> None:
        base = _currency(base_currency)
        quote = _currency(quote_currency)
        value = float(rate)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("FX rate must be finite and positive")
        stamp = _utc(as_of)
        prior = self._as_of.get((base, quote))
        if prior is not None and stamp < prior:
            raise ValueError("retroactive FX update rejected")
        self._rates[(base, quote)] = value
        self._rates[(quote, base)] = 1.0 / value
        self._as_of[(base, quote)] = stamp
        self._as_of[(quote, base)] = stamp

    def rate(self, from_currency: str, to_currency: str) -> float:
        source = _currency(from_currency)
        target = _currency(to_currency)
        if source == target:
            return 1.0
        direct = self._rates.get((source, target))
        if direct is not None and self._fresh((source, target)):
            return direct
        graph: dict[str, list[tuple[str, float]]] = {}
        for (left, right), value in sorted(self._rates.items()):
            if not self._fresh((left, right)):
                continue
            graph.setdefault(left, []).append((right, value))
        queue: deque[tuple[str, float, tuple[str, ...]]] = deque(
            [(source, 1.0, (source,))]
        )
        while queue:
            currency, accumulated, path = queue.popleft()
            for neighbor, edge in graph.get(currency, []):
                if neighbor in path:
                    continue
                converted = accumulated * edge
                if neighbor == target:
                    return converted
                queue.append((neighbor, converted, (*path, neighbor)))
        suffix = (
            " within the configured staleness limit"
            if self._valuation_at is not None and self._max_age_seconds is not None
            else ""
        )
        raise MissingFXRate(f"DATA REQUIRED: no FX path {source}/{target}{suffix}")

    def convert(self, amount: float, from_currency: str, to_currency: str) -> float:
        return float(amount) * self.rate(from_currency, to_currency)

    def to_base(self, amount: float, currency: str) -> float:
        return self.convert(amount, currency, self.base_currency)

    def snapshot(self) -> dict[str, float]:
        currencies = {self.base_currency}
        for left, right in self._rates:
            currencies.update((left, right))
        output: dict[str, float] = {}
        for currency in sorted(currencies):
            try:
                output[currency] = self.rate(currency, self.base_currency)
            except MissingFXRate:
                continue
        return output
