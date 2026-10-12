"""Asset-aware initial and maintenance margin aggregation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .fx import FXMatrix
from .portfolio import Position
from .types import AssetClass, Instrument


_DEFAULTS: dict[AssetClass, tuple[float, float]] = {
    AssetClass.EQUITY: (0.50, 0.25),
    AssetClass.ETF: (0.50, 0.25),
    AssetClass.FX: (0.0333, 0.0250),
    AssetClass.CRYPTO_SPOT: (1.00, 1.00),
    AssetClass.CRYPTO_PERPETUAL: (0.10, 0.05),
    AssetClass.FUTURE: (0.10, 0.075),
    AssetClass.CFD: (0.20, 0.10),
    AssetClass.RATE: (0.10, 0.075),
    AssetClass.OPTION: (1.00, 1.00),
}


@dataclass(frozen=True)
class MarginSnapshot:
    equity_base: float
    initial_required_base: float
    maintenance_required_base: float
    initial_excess_base: float
    maintenance_excess_base: float
    gross_notional_base: float
    available: bool
    reasons: tuple[str, ...]

    @property
    def margin_call(self) -> bool:
        return self.available and self.maintenance_excess_base < 0


class UniversalMarginModel:
    def rates(self, instrument: Instrument, quantity: float = 0.0) -> tuple[float, float]:
        default_initial, default_maintenance = _DEFAULTS[instrument.asset_class]
        initial_rate = (
            float(instrument.initial_margin_rate)
            if instrument.initial_margin_rate is not None
            else default_initial
        )
        maintenance_rate = (
            float(instrument.maintenance_margin_rate)
            if instrument.maintenance_margin_rate is not None
            else default_maintenance
        )
        if instrument.asset_class == AssetClass.OPTION and quantity < 0:
            if instrument.initial_margin_rate is None or instrument.maintenance_margin_rate is None:
                raise ValueError(
                    "short-option margin requires broker or clearing parameters"
                )
        return initial_rate, maintenance_rate

    def requirements(
        self,
        *,
        equity_base: float,
        positions: Mapping[str, Position],
        instruments: Mapping[str, Instrument],
        fx: FXMatrix,
    ) -> MarginSnapshot:
        initial = 0.0
        maintenance = 0.0
        gross = 0.0
        reasons: list[str] = []
        for symbol, position in positions.items():
            if not position.quantity:
                continue
            instrument = instruments[symbol]
            notional_quote = abs(
                position.quantity * position.last_price * float(instrument.multiplier)
            )
            notional_base = abs(fx.to_base(notional_quote, instrument.quote_currency))
            gross += notional_base
            try:
                initial_rate, maintenance_rate = self.rates(
                    instrument, position.quantity
                )
            except ValueError as exc:
                reasons.append(f"{symbol}: {exc}")
                continue
            initial += notional_base * initial_rate
            maintenance += notional_base * maintenance_rate
        available = not reasons
        return MarginSnapshot(
            equity_base=float(equity_base),
            initial_required_base=float(initial),
            maintenance_required_base=float(maintenance),
            initial_excess_base=float(equity_base - initial),
            maintenance_excess_base=float(equity_base - maintenance),
            gross_notional_base=float(gross),
            available=available,
            reasons=tuple(reasons),
        )
