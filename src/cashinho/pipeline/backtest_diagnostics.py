"""Diagnosticos agregados para descobrir onde o backtest quebra."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from cashinho.domain.enums import Timeframe
from cashinho.domain.market import CandleSeries
from cashinho.pipeline.backtest import (
    BacktestMetrics,
    BacktestTrade,
    calculate_metrics,
    truncate_at,
)
from cashinho.pipeline.market_regime import MarketRegime, analyze_market_regime


@dataclass(frozen=True, slots=True)
class DiagnosticTrade:
    trade: BacktestTrade
    symbol: str
    year: str
    month: str
    hour: str
    side: str
    timeframe: str
    score_bucket: str
    setup_type: str
    close_reason: str
    regime: str
    volatility: str
    result_bucket: str


@dataclass(frozen=True, slots=True)
class DiagnosticRow:
    dimension: str
    bucket: str
    metrics: BacktestMetrics


def classify_trade(
    trade: BacktestTrade,
    *,
    series_by_timeframe: dict[Timeframe, CandleSeries],
    display_timezone: str = "America/Sao_Paulo",
    max_regime_bars: int = 80,
) -> DiagnosticTrade:
    local = trade.entered_at.astimezone(ZoneInfo(display_timezone))
    regime, volatility = _regime_for(
        trade,
        series_by_timeframe=series_by_timeframe,
        max_regime_bars=max_regime_bars,
    )
    return DiagnosticTrade(
        trade=trade,
        symbol=trade.symbol,
        year=str(local.year),
        month=f"{local.year}-{local.month:02d}",
        hour=f"{local.hour:02d}:00",
        side=trade.side,
        timeframe=trade.timeframe.value,
        score_bucket=_score_bucket(trade.score),
        setup_type=trade.setup_type,
        close_reason=trade.close_reason,
        regime=regime.value,
        volatility=volatility,
        result_bucket="WIN" if trade.net_pnl > 0 else "LOSS" if trade.net_pnl < 0 else "FLAT",
    )


def build_diagnostic_trades(
    trades: Iterable[BacktestTrade],
    *,
    series_by_timeframe: dict[Timeframe, CandleSeries],
    display_timezone: str = "America/Sao_Paulo",
) -> tuple[DiagnosticTrade, ...]:
    return tuple(
        classify_trade(
            trade,
            series_by_timeframe=series_by_timeframe,
            display_timezone=display_timezone,
        )
        for trade in trades
    )


def diagnostic_table(
    trades: Iterable[DiagnosticTrade],
    *,
    initial_capital: Decimal,
    dimension: str,
) -> tuple[DiagnosticRow, ...]:
    getter = _dimension_getter(dimension)
    groups: dict[str, list[BacktestTrade]] = {}
    for item in trades:
        groups.setdefault(getter(item), []).append(item.trade)
    rows = [
        DiagnosticRow(
            dimension=dimension,
            bucket=bucket,
            metrics=calculate_metrics(group, initial_capital=initial_capital)[0],
        )
        for bucket, group in groups.items()
    ]
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                row.metrics.net_profit,
                row.metrics.profit_factor or Decimal("-1"),
                -row.metrics.total_trades,
            ),
        )
    )


def diagnostic_tables(
    trades: Iterable[DiagnosticTrade],
    *,
    initial_capital: Decimal,
    dimensions: tuple[str, ...] = (
        "year",
        "month",
        "hour",
        "symbol",
        "side",
        "timeframe",
        "score_bucket",
        "setup_type",
        "close_reason",
        "regime",
        "volatility",
    ),
) -> dict[str, tuple[DiagnosticRow, ...]]:
    items = tuple(trades)
    return {
        dimension: diagnostic_table(
            items,
            initial_capital=initial_capital,
            dimension=dimension,
        )
        for dimension in dimensions
    }


def _dimension_getter(dimension: str) -> Callable[[DiagnosticTrade], str]:
    if dimension not in {
        "year",
        "month",
        "hour",
        "symbol",
        "side",
        "timeframe",
        "score_bucket",
        "setup_type",
        "close_reason",
        "regime",
        "volatility",
        "result_bucket",
    }:
        raise ValueError(f"dimensao de diagnostico invalida: {dimension}")
    return lambda item: str(getattr(item, dimension))


def _score_bucket(score: int) -> str:
    if score < 50:
        return "00-49"
    if score < 60:
        return "50-59"
    if score < 70:
        return "60-69"
    if score < 80:
        return "70-79"
    if score < 90:
        return "80-89"
    return "90-100"


def _regime_for(
    trade: BacktestTrade,
    *,
    series_by_timeframe: dict[Timeframe, CandleSeries],
    max_regime_bars: int,
) -> tuple[MarketRegime, str]:
    series = series_by_timeframe.get(trade.timeframe)
    if series is None:
        return MarketRegime.INDETERMINATE, "UNKNOWN"
    prefix = truncate_at(series, trade.signal_at)
    if max_regime_bars > 0 and len(prefix.candles) > max_regime_bars:
        prefix = prefix.model_copy(update={"candles": prefix.candles[-max_regime_bars:]})
    analysis = analyze_market_regime(prefix)
    return analysis.regime, analysis.volatility
