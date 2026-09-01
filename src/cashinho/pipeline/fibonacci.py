"""Leitura simples de Fibonacci para confluencia tecnica."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from cashinho.domain.market import CandleSeries


@dataclass(frozen=True, slots=True)
class FibonacciConfluence:
    side: str
    level_name: str
    level_price: Decimal
    distance_pct: Decimal
    reason: str


def fibonacci_confluence(
    series: CandleSeries,
    *,
    lookback: int = 55,
    tolerance_pct: Decimal = Decimal("0.45"),
) -> FibonacciConfluence | None:
    """Procura preco atual proximo de zonas 38,2%, 50% ou 61,8% do ultimo swing."""
    candles = series.closed_only().candles[-lookback:]
    if len(candles) < 20:
        return None
    swing_high = max(c.high for c in candles)
    swing_low = min(c.low for c in candles)
    last = candles[-1]
    amplitude = swing_high - swing_low
    if amplitude <= 0 or last.close <= 0:
        return None

    uptrend = last.close >= (swing_low + amplitude * Decimal("0.50"))
    levels = {
        "38,2%": swing_high - amplitude * Decimal("0.382"),
        "50,0%": swing_high - amplitude * Decimal("0.500"),
        "61,8%": swing_high - amplitude * Decimal("0.618"),
    }
    nearest_name, nearest_price = min(
        levels.items(),
        key=lambda item: abs(last.close - item[1]),
    )
    distance_pct = (abs(last.close - nearest_price) / last.close * Decimal("100")).quantize(
        Decimal("0.01")
    )
    if distance_pct > tolerance_pct:
        return None

    side = "BUY" if uptrend else "SELL"
    action = "suporte" if side == "BUY" else "resistencia"
    return FibonacciConfluence(
        side=side,
        level_name=nearest_name,
        level_price=nearest_price.quantize(Decimal("0.01")),
        distance_pct=distance_pct,
        reason=f"Preço próximo do {action} de Fibonacci {nearest_name}",
    )
