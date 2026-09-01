from __future__ import annotations

from decimal import Decimal

from cashinho.pipeline.monte_carlo import MonteCarloSummary
from cashinho.pipeline.operational_readiness import evaluate_operational_readiness
from cashinho.pipeline.score_calibration import calibrate_scores
from tests.unit.test_operational_line import _dated_trade


def _monte_carlo(negative: str) -> MonteCarloSummary:
    return MonteCarloSummary(
        simulations=100,
        trades_per_simulation=10,
        median_final_equity=Decimal("101"),
        final_equity_p05=Decimal("99"),
        final_equity_p95=Decimal("105"),
        drawdown_p50_pct=Decimal("1"),
        drawdown_p95_pct=Decimal("3"),
        loss_streak_p95=3,
        probability_negative_return_pct=Decimal(negative),
        risk_of_ruin_pct=Decimal("0"),
    )


def test_prontidao_operacional_fica_baixa_sem_linha_aprovada() -> None:
    trades = tuple(_dated_trade("-1", index, year=2025) for index in range(12))
    readiness = evaluate_operational_readiness(
        (),
        score_rows=calibrate_scores(trades, initial_capital=Decimal("100")),
        monte_carlo=_monte_carlo("90"),
        policy_holdout=None,
        operational_lines=(),
        simulated_lines=(),
        simulated_trades=trades,
    )

    assert readiness.operational_pct < Decimal("20")
    assert readiness.verdict == "AINDA_NAO_OPERAR_DINHEIRO_REAL"


def test_prontidao_tecnica_sobe_com_custos_score_e_replay() -> None:
    trades = tuple(_dated_trade("1", index, year=2025) for index in range(12))
    readiness = evaluate_operational_readiness(
        (),
        score_rows=calibrate_scores(trades, initial_capital=Decimal("100")),
        monte_carlo=_monte_carlo("30"),
        policy_holdout=None,
        operational_lines=(),
        simulated_lines=(),
        simulated_trades=trades,
    )

    assert readiness.technical_pct > Decimal("10")
    assert any(factor.name == "Replay de bloqueios" for factor in readiness.factors)
