"""Calibracao historica do score gerado pela estrategia."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise

from cashinho.pipeline.backtest import BacktestMetrics, BacktestTrade, calculate_metrics


@dataclass(frozen=True, slots=True)
class ScoreCalibrationRow:
    bucket: str
    metrics: BacktestMetrics


def score_bucket(score: int) -> str:
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


def calibrate_scores(
    trades: tuple[BacktestTrade, ...],
    *,
    initial_capital: Decimal,
) -> tuple[ScoreCalibrationRow, ...]:
    groups: dict[str, list[BacktestTrade]] = {}
    for trade in trades:
        groups.setdefault(score_bucket(trade.score), []).append(trade)
    return tuple(
        ScoreCalibrationRow(bucket, calculate_metrics(group, initial_capital=initial_capital)[0])
        for bucket, group in sorted(groups.items())
    )


def score_calibration_verdict(rows: tuple[ScoreCalibrationRow, ...]) -> str:
    """Diz se scores maiores estao acompanhados de resultado melhor."""
    expectancies: list[Decimal] = [
        expectancy
        for row in rows
        if row.metrics.total_trades >= 3 and (expectancy := row.metrics.expectancy) is not None
    ]
    if len(expectancies) < 2:
        return "INCONCLUSIVO"
    improving_steps = sum(later >= earlier for earlier, later in pairwise(expectancies))
    return "SIM" if improving_steps == len(expectancies) - 1 else "NAO"
