"""Auditoria de consistencia entre timeframes."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

import pandas as pd

from cashinho.domain.enums import Timeframe
from cashinho.domain.market import Candle, CandleSeries


@dataclass(frozen=True, slots=True)
class TimeframeMismatch:
    timestamp: str
    field: str
    aggregated: object
    direct: object


@dataclass(frozen=True, slots=True)
class TimeframeComparison:
    source_timeframe: Timeframe
    target_timeframe: Timeframe
    compared: int
    mismatches: tuple[TimeframeMismatch, ...]

    @property
    def approved(self) -> bool:
        return not self.mismatches and self.compared > 0


def aggregate_timeframe(series: CandleSeries, target: Timeframe) -> CandleSeries:
    """Agrega candles fechados para um timeframe maior, preservando OHLCV."""
    if target.duration <= series.timeframe.duration:
        raise ValueError("O timeframe alvo precisa ser maior que o timeframe origem.")

    frame = series.closed_only().to_frame()
    if frame.empty:
        return series.model_copy(update={"timeframe": target, "candles": ()})

    grouped = frame.resample(target.pandas_freq, label="left", closed="left").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "is_closed": "all",
        }
    )
    grouped["count"] = frame["close"].resample(
        target.pandas_freq,
        label="left",
        closed="left",
    ).count()
    grouped = grouped.dropna(subset=["open", "high", "low", "close"])
    expected = int(target.duration / series.timeframe.duration)
    grouped = grouped[grouped["count"] >= expected]
    candles = []
    for index, row in grouped.iterrows():
        open_time = pd.Timestamp(cast(Any, index)).to_pydatetime()
        candles.append(
            Candle(
                open_time=open_time,
                close_time=open_time + target.duration,
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=int(row["volume"]),
                is_closed=bool(row["is_closed"]),
            )
        )
    return CandleSeries(
        symbol=series.symbol,
        timeframe=target,
        candles=tuple(candles),
        source=f"aggregated:{series.source}",
        fetched_at=series.fetched_at,
    )


def compare_timeframes(
    aggregated: CandleSeries,
    direct: CandleSeries,
    *,
    price_tolerance: Decimal = Decimal("0.01"),
    volume_tolerance: int = 0,
) -> TimeframeComparison:
    """Compara OHLCV por timestamp e lista divergencias exatas."""
    direct_by_open = {candle.open_time: candle for candle in direct.closed_only().candles}
    mismatches: list[TimeframeMismatch] = []
    compared = 0
    for candle in aggregated.closed_only().candles:
        direct_candle = direct_by_open.get(candle.open_time)
        if direct_candle is None:
            mismatches.append(
                TimeframeMismatch(candle.open_time.isoformat(), "timestamp", "existe", "ausente")
            )
            continue
        compared += 1
        for field in ("open", "high", "low", "close"):
            left = getattr(candle, field)
            right = getattr(direct_candle, field)
            if abs(left - right) > price_tolerance:
                mismatches.append(
                    TimeframeMismatch(candle.open_time.isoformat(), field, left, right)
                )
        if abs(candle.volume - direct_candle.volume) > volume_tolerance:
            mismatches.append(
                TimeframeMismatch(
                    candle.open_time.isoformat(),
                    "volume",
                    candle.volume,
                    direct_candle.volume,
                )
            )
    return TimeframeComparison(
        source_timeframe=aggregated.timeframe,
        target_timeframe=direct.timeframe,
        compared=compared,
        mismatches=tuple(mismatches),
    )
