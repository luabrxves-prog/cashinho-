from __future__ import annotations

from decimal import Decimal

from cashinho.pipeline.execution_costs import (
    CostScenario,
    cost_scenario_config,
    parse_cost_scenarios,
)


def test_cenario_realista_tem_custos_maiores_que_sem_custos() -> None:
    free = cost_scenario_config(CostScenario.SEM_CUSTOS).model
    realistic = cost_scenario_config(CostScenario.REALISTA).model

    assert realistic.entry_price(Decimal("10"), "BUY") > free.entry_price(Decimal("10"), "BUY")
    assert realistic.exit_price(Decimal("11"), "BUY") < free.exit_price(Decimal("11"), "BUY")


def test_parse_cenarios_preserva_ordem_sem_duplicar_contrato() -> None:
    assert parse_cost_scenarios("SEM_CUSTOS,REALISTA") == (
        CostScenario.SEM_CUSTOS,
        CostScenario.REALISTA,
    )
