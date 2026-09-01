"""Validacao temporal em janelas cronologicas de trades."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from cashinho.pipeline.backtest import BacktestMetrics, BacktestTrade, calculate_metrics


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    train_metrics: BacktestMetrics
    test_metrics: BacktestMetrics


def rolling_walk_forward(
    trades: tuple[BacktestTrade, ...],
    *,
    initial_capital: Decimal,
    train_size: int = 20,
    test_size: int = 10,
    step_size: int = 10,
) -> tuple[WalkForwardWindow, ...]:
    """Mede estabilidade fora da janela anterior, sem embaralhar o tempo."""
    if train_size <= 0 or test_size <= 0 or step_size <= 0:
        raise ValueError("Tamanhos de janela precisam ser positivos.")
    ordered = tuple(sorted(trades, key=lambda trade: trade.entered_at))
    windows: list[WalkForwardWindow] = []
    index = 1
    start = 0
    while start + train_size + test_size <= len(ordered):
        train = list(ordered[start : start + train_size])
        test = list(ordered[start + train_size : start + train_size + test_size])
        windows.append(
            WalkForwardWindow(
                index=index,
                train_start=train[0].entered_at,
                train_end=train[-1].exited_at,
                test_start=test[0].entered_at,
                test_end=test[-1].exited_at,
                train_metrics=calculate_metrics(train, initial_capital=initial_capital)[0],
                test_metrics=calculate_metrics(test, initial_capital=initial_capital)[0],
            )
        )
        index += 1
        start += step_size
    return tuple(windows)
