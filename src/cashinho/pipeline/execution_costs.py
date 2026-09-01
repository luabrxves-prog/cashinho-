"""Cenarios padronizados de custo para estudos historicos."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from cashinho.pipeline.backtest import ExecutionCostModel


class CostScenario(StrEnum):
    SEM_CUSTOS = "SEM_CUSTOS"
    IDEAL = "IDEAL"
    REALISTA = "REALISTA"
    ESTRESSADO = "ESTRESSADO"


@dataclass(frozen=True, slots=True)
class CostScenarioConfig:
    scenario: CostScenario
    description: str
    model: ExecutionCostModel


_SCENARIOS = {
    CostScenario.SEM_CUSTOS: CostScenarioConfig(
        CostScenario.SEM_CUSTOS,
        "Referencia bruta, sem spread, slippage ou taxas.",
        ExecutionCostModel(),
    ),
    CostScenario.IDEAL: CostScenarioConfig(
        CostScenario.IDEAL,
        "Execucao favoravel, usada para medir sensibilidade baixa a custos.",
        ExecutionCostModel(
            spread=Decimal("0.01"),
            slippage=Decimal("0.00"),
            variable_fee_pct=Decimal("0.03"),
        ),
    ),
    CostScenario.REALISTA: CostScenarioConfig(
        CostScenario.REALISTA,
        "Execucao conservadora para conta pequena, com spread e escorregao.",
        ExecutionCostModel(
            spread=Decimal("0.02"),
            slippage=Decimal("0.01"),
            variable_fee_pct=Decimal("0.05"),
        ),
    ),
    CostScenario.ESTRESSADO: CostScenarioConfig(
        CostScenario.ESTRESSADO,
        "Execucao ruim, usada para reprovar setups que dependem de perfeicao.",
        ExecutionCostModel(
            spread=Decimal("0.05"),
            slippage=Decimal("0.03"),
            variable_fee_pct=Decimal("0.08"),
        ),
    ),
}


def cost_scenario_config(scenario: CostScenario | str) -> CostScenarioConfig:
    normalized = scenario if isinstance(scenario, CostScenario) else CostScenario(scenario)
    return _SCENARIOS[normalized]


def parse_cost_scenarios(raw: str) -> tuple[CostScenario, ...]:
    values = tuple(CostScenario(item.strip().upper()) for item in raw.split(",") if item.strip())
    return values or (CostScenario.SEM_CUSTOS,)
