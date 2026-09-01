"""Validacao temporal da politica operacional."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from cashinho.pipeline.backtest import BacktestMetrics, BacktestTrade, calculate_metrics
from cashinho.pipeline.backtest_diagnostics import DiagnosticTrade
from cashinho.pipeline.operational_policy import (
    OperationalPolicy,
    build_policy_from_diagnostics,
)


@dataclass(frozen=True, slots=True)
class PolicyHoldoutRow:
    group: str
    train_until_year: int
    test_start_year: int
    trades: int
    metrics: BacktestMetrics


@dataclass(frozen=True, slots=True)
class PolicyHoldoutResult:
    policy: OperationalPolicy
    rows: tuple[PolicyHoldoutRow, ...]


def validate_policy_holdout(
    diagnostics: tuple[DiagnosticTrade, ...],
    *,
    initial_capital: Decimal,
    train_until_year: int,
    generated_at: datetime,
    source: str,
) -> PolicyHoldoutResult | None:
    """Treina a politica no passado e testa somente nos anos seguintes."""
    train = tuple(item for item in diagnostics if int(item.year) <= train_until_year)
    test = tuple(item for item in diagnostics if int(item.year) > train_until_year)
    if not train or not test:
        return None

    policy = build_policy_from_diagnostics(
        train,
        initial_capital=initial_capital,
        generated_at=generated_at,
        source=source,
    )
    before = [item.trade for item in test]
    allowed: list[BacktestTrade] = []
    blocked: list[BacktestTrade] = []
    for item in test:
        decision = policy.evaluate(
            symbol=item.symbol,
            timestamp=item.trade.entered_at,
            timeframe=item.trade.timeframe,
            side=item.side,
            score=item.trade.score,
            setup_type=item.setup_type,
            regime=item.regime,
            volatility=item.volatility,
        )
        (allowed if decision.approved else blocked).append(item.trade)
    test_start_year = min(int(item.year) for item in test)
    return PolicyHoldoutResult(
        policy,
        (
            _row(
                "TESTE_ANTES_POLITICA",
                train_until_year,
                test_start_year,
                before,
                initial_capital,
            ),
            _row("TESTE_APROVADOS", train_until_year, test_start_year, allowed, initial_capital),
            _row("TESTE_BLOQUEADOS", train_until_year, test_start_year, blocked, initial_capital),
        ),
    )


def _row(
    group: str,
    train_until_year: int,
    test_start_year: int,
    trades: list[BacktestTrade],
    initial_capital: Decimal,
) -> PolicyHoldoutRow:
    return PolicyHoldoutRow(
        group,
        train_until_year,
        test_start_year,
        len(trades),
        calculate_metrics(trades, initial_capital=initial_capital)[0],
    )
