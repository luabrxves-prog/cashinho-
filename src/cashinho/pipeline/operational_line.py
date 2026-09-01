"""Comparacao de linhas operacionais candidatas para conta pequena."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from cashinho.pipeline.backtest import BacktestMetrics, BacktestTrade, calculate_metrics
from cashinho.pipeline.backtest_diagnostics import DiagnosticTrade

HUNDRED = Decimal("100")


@dataclass(frozen=True, slots=True)
class OperationalLineCandidate:
    name: str
    minimum_score: int
    allowed_setups: tuple[str, ...]
    blocked_setups: tuple[str, ...] = ("NO_CLEAR_SETUP",)
    max_drawdown_pct: Decimal = Decimal("3.00")
    minimum_test_trades: int = 8
    minimum_profit_factor: Decimal = Decimal("1.10")


@dataclass(frozen=True, slots=True)
class OperationalLineResult:
    candidate: OperationalLineCandidate
    train_metrics: BacktestMetrics
    test_metrics: BacktestMetrics
    train_until_year: int
    test_start_year: int
    train_trades: int
    test_trades: int
    monthly_stability_pct: Decimal | None
    dominant_setups: tuple[str, ...]
    approved: bool
    rejection_reasons: tuple[str, ...]


DEFAULT_OPERATIONAL_LINES = (
    OperationalLineCandidate(
        name="CONSERVADORA",
        minimum_score=90,
        allowed_setups=(
            "EXPANSION_BREAKOUT",
            "BREAKOUT_RETEST",
            "OPENING_RANGE_EXPANSION",
            "VWAP_REVERSION",
        ),
        minimum_test_trades=5,
    ),
    OperationalLineCandidate(
        name="EQUILIBRADA",
        minimum_score=80,
        allowed_setups=(
            "EXPANSION_BREAKOUT",
            "BREAKOUT_RETEST",
            "OPENING_RANGE_EXPANSION",
            "PULLBACK_TREND",
            "TREND_CONTINUATION",
            "VWAP_REVERSION",
            "SUPPORT_RESISTANCE_REVERSAL",
        ),
        minimum_test_trades=8,
    ),
    OperationalLineCandidate(
        name="AGRESSIVA_CONTROLADA",
        minimum_score=70,
        allowed_setups=(
            "EXPANSION_BREAKOUT",
            "BREAKOUT_RETEST",
            "OPENING_RANGE_EXPANSION",
            "PULLBACK_TREND",
            "TREND_CONTINUATION",
            "VWAP_REVERSION",
            "RANGE_REVERSION",
            "SUPPORT_RESISTANCE_REVERSAL",
            "CONSOLIDATION_CONTINUATION",
        ),
        max_drawdown_pct=Decimal("4.00"),
        minimum_test_trades=12,
        minimum_profit_factor=Decimal("1.15"),
    ),
    OperationalLineCandidate(
        name="VWAP_E_REVERSAO",
        minimum_score=70,
        allowed_setups=(
            "VWAP_REVERSION",
            "RANGE_REVERSION",
            "SUPPORT_RESISTANCE_REVERSAL",
        ),
        max_drawdown_pct=Decimal("3.50"),
        minimum_test_trades=6,
    ),
)


def compare_operational_lines(
    diagnostics: tuple[DiagnosticTrade, ...],
    *,
    initial_capital: Decimal,
    train_until_year: int,
    candidates: tuple[OperationalLineCandidate, ...] = DEFAULT_OPERATIONAL_LINES,
) -> tuple[OperationalLineResult, ...]:
    """Testa perfis de operação no passado e mede somente nos anos seguintes."""
    if not diagnostics:
        return ()
    test_years = [int(item.year) for item in diagnostics if int(item.year) > train_until_year]
    test_start_year = min(test_years) if test_years else train_until_year + 1
    rows = []
    for candidate in candidates:
        train_items = _allowed_items(
            diagnostics,
            candidate=candidate,
            max_year=train_until_year,
        )
        test_items = _allowed_items(
            diagnostics,
            candidate=candidate,
            min_year=train_until_year + 1,
        )
        train_trades = [item.trade for item in train_items]
        test_trades = [item.trade for item in test_items]
        train_metrics = calculate_metrics(train_trades, initial_capital=initial_capital)[0]
        test_metrics = calculate_metrics(test_trades, initial_capital=initial_capital)[0]
        stability = _monthly_stability(test_trades)
        rejection = _rejection_reasons(
            candidate,
            test_metrics=test_metrics,
            test_trades=len(test_trades),
            monthly_stability_pct=stability,
        )
        rows.append(
            OperationalLineResult(
                candidate=candidate,
                train_metrics=train_metrics,
                test_metrics=test_metrics,
                train_until_year=train_until_year,
                test_start_year=test_start_year,
                train_trades=len(train_trades),
                test_trades=len(test_trades),
                monthly_stability_pct=stability,
                dominant_setups=_dominant_setups(test_items),
                approved=not rejection,
                rejection_reasons=rejection,
            )
        )
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                row.approved,
                row.test_metrics.expectancy or Decimal("-999"),
                row.test_metrics.net_profit,
                row.test_trades,
            ),
            reverse=True,
        )
    )


def _allowed_items(
    diagnostics: tuple[DiagnosticTrade, ...],
    *,
    candidate: OperationalLineCandidate,
    min_year: int | None = None,
    max_year: int | None = None,
) -> tuple[DiagnosticTrade, ...]:
    allowed = []
    for item in diagnostics:
        year = int(item.year)
        if min_year is not None and year < min_year:
            continue
        if max_year is not None and year > max_year:
            continue
        if item.trade.score < candidate.minimum_score:
            continue
        if item.setup_type in candidate.blocked_setups:
            continue
        if item.setup_type not in candidate.allowed_setups:
            continue
        allowed.append(item)
    return tuple(allowed)


def _rejection_reasons(
    candidate: OperationalLineCandidate,
    *,
    test_metrics: BacktestMetrics,
    test_trades: int,
    monthly_stability_pct: Decimal | None,
) -> tuple[str, ...]:
    reasons = []
    if test_trades < candidate.minimum_test_trades:
        reasons.append("Amostra fora da amostra pequena demais.")
    if test_metrics.net_profit <= 0:
        reasons.append("Resultado líquido fora da amostra não ficou positivo.")
    if test_metrics.expectancy is None or test_metrics.expectancy <= 0:
        reasons.append("Expectativa matemática fora da amostra não ficou positiva.")
    if test_metrics.profit_factor is not None and test_metrics.profit_factor < candidate.minimum_profit_factor:
        reasons.append("Profit factor fora da amostra abaixo do mínimo.")
    if (
        test_metrics.max_drawdown_pct is not None
        and test_metrics.max_drawdown_pct > candidate.max_drawdown_pct
    ):
        reasons.append("Drawdown fora da amostra acima do limite.")
    if monthly_stability_pct is not None and monthly_stability_pct < Decimal("50"):
        reasons.append("Estabilidade mensal fora da amostra fraca.")
    return tuple(reasons)


def _monthly_stability(trades: list[BacktestTrade]) -> Decimal | None:
    if not trades:
        return None
    months: dict[str, list[BacktestTrade]] = {}
    for trade in trades:
        months.setdefault(trade.entered_at.strftime("%Y-%m"), []).append(trade)
    if len(months) < 2:
        return None
    positive = 0
    for group in months.values():
        if sum((trade.net_pnl for trade in group), Decimal("0")) > 0:
            positive += 1
    return (Decimal(positive) / Decimal(len(months)) * HUNDRED).quantize(Decimal("0.01"))


def _dominant_setups(items: tuple[DiagnosticTrade, ...]) -> tuple[str, ...]:
    return tuple(setup for setup, _count in Counter(item.setup_type for item in items).most_common(5))
