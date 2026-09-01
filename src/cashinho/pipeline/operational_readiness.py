"""Nota de prontidao operacional baseada em evidencias do estudo historico."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from cashinho.pipeline.backtest import BacktestTrade
from cashinho.pipeline.backtest_diagnostics import DiagnosticTrade
from cashinho.pipeline.monte_carlo import MonteCarloSummary
from cashinho.pipeline.operational_line import OperationalLineResult
from cashinho.pipeline.policy_validation import PolicyHoldoutResult, PolicyHoldoutRow
from cashinho.pipeline.score_calibration import ScoreCalibrationRow, score_calibration_verdict

ZERO = Decimal("0")
HUNDRED = Decimal("100")


@dataclass(frozen=True, slots=True)
class ReadinessFactor:
    area: str
    name: str
    points: Decimal
    max_points: Decimal
    explanation: str


@dataclass(frozen=True, slots=True)
class OperationalReadiness:
    technical_pct: Decimal
    operational_pct: Decimal
    verdict: str
    factors: tuple[ReadinessFactor, ...]


def evaluate_operational_readiness(
    diagnostics: tuple[DiagnosticTrade, ...],
    *,
    score_rows: tuple[ScoreCalibrationRow, ...],
    monte_carlo: MonteCarloSummary | None,
    policy_holdout: PolicyHoldoutResult | None,
    operational_lines: tuple[OperationalLineResult, ...],
    simulated_lines: tuple[OperationalLineResult, ...],
    simulated_trades: tuple[BacktestTrade, ...],
) -> OperationalReadiness:
    """Calcula uma nota reproduzivel para estudo e uso operacional.

    A nota tecnica mede se o Cashinho esta bem instrumentado para estudar.
    A nota operacional mede se os resultados ja sustentam operar dinheiro real.
    """

    factors = (
        _sample_factor(diagnostics),
        _cost_factor(diagnostics),
        _score_factor(score_rows),
        _holdout_factor(policy_holdout),
        _monte_carlo_factor(monte_carlo),
        _line_factor(operational_lines),
        _simulated_factor(simulated_lines, simulated_trades),
    )
    technical_pct = _pct(factors, area="TECNICA")
    operational_pct = _pct(factors, area="OPERACIONAL")
    return OperationalReadiness(
        technical_pct=technical_pct,
        operational_pct=operational_pct,
        verdict=_verdict(operational_pct),
        factors=factors,
    )


def _sample_factor(diagnostics: tuple[DiagnosticTrade, ...]) -> ReadinessFactor:
    trades = len(diagnostics)
    points = ZERO
    if trades >= 200:
        points = Decimal("20")
        explanation = "Amostra ampla, adequada para comparar setups e regimes."
    elif trades >= 100:
        points = Decimal("15")
        explanation = "Amostra razoavel, mas ainda merece mais ativos e janelas."
    elif trades >= 30:
        points = Decimal("9")
        explanation = "Amostra minima para expectativa, ainda fraca para regra final."
    elif trades >= 10:
        points = Decimal("5")
        explanation = "Amostra pequena; qualquer conclusao operacional ainda e fragil."
    else:
        explanation = "Amostra insuficiente para confiar em estatistica operacional."
    return ReadinessFactor("TECNICA", "Amostra historica", points, Decimal("20"), explanation)


def _cost_factor(diagnostics: tuple[DiagnosticTrade, ...]) -> ReadinessFactor:
    if any(item.trade.costs > 0 for item in diagnostics):
        points = Decimal("15")
        explanation = "Os resultados consideram custos, spread ou slippage."
    else:
        points = Decimal("5") if diagnostics else ZERO
        explanation = "O estudo ainda precisa custos realistas para medir dinheiro real."
    return ReadinessFactor("TECNICA", "Custos operacionais", points, Decimal("15"), explanation)


def _score_factor(score_rows: tuple[ScoreCalibrationRow, ...]) -> ReadinessFactor:
    rows_with_sample = [row for row in score_rows if row.metrics.total_trades >= 3]
    verdict = score_calibration_verdict(score_rows)
    if verdict == "SIM" and len(rows_with_sample) >= 3:
        points = Decimal("15")
        explanation = "Score sobe junto com resultado em varias faixas."
    elif verdict == "SIM":
        points = Decimal("9")
        explanation = "Score parece fazer sentido, mas poucas faixas tem amostra."
    elif verdict == "NAO":
        points = Decimal("3")
        explanation = "Score alto nao esta acompanhando resultado melhor."
    else:
        points = Decimal("5") if score_rows else ZERO
        explanation = "Calibracao do score ainda inconclusiva."
    return ReadinessFactor("TECNICA", "Calibracao do score", points, Decimal("15"), explanation)


def _holdout_factor(policy_holdout: PolicyHoldoutResult | None) -> ReadinessFactor:
    approved = _holdout_row(policy_holdout, "TESTE_APROVADOS")
    if approved is None:
        return ReadinessFactor(
            "OPERACIONAL",
            "Holdout da politica",
            ZERO,
            Decimal("20"),
            "Sem teste fora da amostra suficiente para a politica.",
        )
    metrics = approved.metrics
    if metrics.total_trades >= 20 and metrics.net_profit > 0 and _positive(metrics.expectancy):
        points = Decimal("20")
        explanation = "Politica passou fora da amostra com resultado e expectativa positivos."
    elif metrics.total_trades >= 5 and metrics.net_profit > 0:
        points = Decimal("10")
        explanation = "Politica ficou positiva fora da amostra, mas com pouca amostra."
    elif metrics.net_profit > 0:
        points = Decimal("5")
        explanation = "Holdout positivo, porem com amostra pequena demais."
    else:
        points = ZERO
        explanation = "Politica nao ficou positiva fora da amostra."
    return ReadinessFactor("OPERACIONAL", "Holdout da politica", points, Decimal("20"), explanation)


def _monte_carlo_factor(monte_carlo: MonteCarloSummary | None) -> ReadinessFactor:
    if monte_carlo is None:
        return ReadinessFactor(
            "OPERACIONAL",
            "Monte Carlo",
            ZERO,
            Decimal("20"),
            "Sem trades para simular sequencias ruins.",
        )
    negative = monte_carlo.probability_negative_return_pct
    if negative <= Decimal("20") and monte_carlo.final_equity_p05 >= Decimal("100"):
        points = Decimal("20")
        explanation = "Sequencias embaralhadas preservam capital mesmo no pior 5%."
    elif negative <= Decimal("40"):
        points = Decimal("12")
        explanation = "Risco estatistico aceitavel, mas ainda exige cautela."
    elif negative <= Decimal("60"):
        points = Decimal("7")
        explanation = "Muitas sequencias simuladas ainda terminam negativas."
    else:
        points = Decimal("2")
        explanation = "Monte Carlo mostra alta chance de terminar abaixo do capital inicial."
    return ReadinessFactor("OPERACIONAL", "Monte Carlo", points, Decimal("20"), explanation)


def _line_factor(operational_lines: tuple[OperationalLineResult, ...]) -> ReadinessFactor:
    approved = [row for row in operational_lines if row.approved]
    if not operational_lines:
        points = ZERO
        explanation = "Nenhuma linha operacional foi avaliada."
    elif approved:
        best = approved[0]
        points = Decimal("25") if best.test_trades >= 30 else Decimal("12")
        explanation = f"Linha {best.candidate.name} passou, com {best.test_trades} trades em teste."
    else:
        points = ZERO
        explanation = "Nenhuma linha real passou nos criterios minimos."
    return ReadinessFactor("OPERACIONAL", "Linha operacional real", points, Decimal("25"), explanation)


def _simulated_factor(
    simulated_lines: tuple[OperationalLineResult, ...],
    simulated_trades: tuple[BacktestTrade, ...],
) -> ReadinessFactor:
    approved = [row for row in simulated_lines if row.approved]
    if approved:
        points = Decimal("12")
        explanation = "Entradas bloqueadas geraram uma candidata para novo holdout."
    elif simulated_trades:
        profitable = sum(1 for trade in simulated_trades if trade.net_pnl > 0)
        points = Decimal("5")
        explanation = (
            f"{profitable} de {len(simulated_trades)} entradas bloqueadas teriam sido positivas; "
            "ainda nao sustenta afrouxar regra."
        )
    else:
        points = Decimal("2")
        explanation = "O estudo ainda precisa mais planos bloqueados completos para simular."
    return ReadinessFactor("TECNICA", "Replay de bloqueios", points, Decimal("15"), explanation)


def _holdout_row(
    policy_holdout: PolicyHoldoutResult | None,
    group: str,
) -> PolicyHoldoutRow | None:
    if policy_holdout is None:
        return None
    return next((row for row in policy_holdout.rows if row.group == group), None)


def _positive(value: Decimal | None) -> bool:
    return value is not None and value > 0


def _pct(factors: tuple[ReadinessFactor, ...], *, area: str) -> Decimal:
    selected = [factor for factor in factors if factor.area == area]
    if not selected:
        return ZERO
    points = sum((factor.points for factor in selected), ZERO)
    max_points = sum((factor.max_points for factor in selected), ZERO)
    return (points / max_points * HUNDRED).quantize(Decimal("0.01")) if max_points else ZERO


def _verdict(operational_pct: Decimal) -> str:
    if operational_pct >= Decimal("80"):
        return "PRONTO_PARA_PAPER_INTENSIVO"
    if operational_pct >= Decimal("65"):
        return "QUASE_PRONTO_PARA_PAPER_CONTROLADO"
    if operational_pct >= Decimal("45"):
        return "ESTUDO_PROMISSOR_MAS_NAO_OPERACIONAL"
    return "AINDA_NAO_OPERAR_DINHEIRO_REAL"
