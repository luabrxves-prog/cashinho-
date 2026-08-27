"""Modelos de risco.

O algoritmo de dimensionamento chega na Fase 4. Aqui garantimos que os
contratos nao aceitem valores incoerentes.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from cashinho.domain.risk import PositionSize, RiskDecision, RiskProfile


def test_risco_monetario_por_operacao() -> None:
    profile = RiskProfile(capital=Decimal("100000.00"), risk_per_trade_pct=Decimal("0.5"))
    assert profile.monetary_risk_per_trade == Decimal("500.00")


def test_risco_monetario_com_capital_pequeno() -> None:
    profile = RiskProfile(capital=Decimal("1000.00"), risk_per_trade_pct=Decimal("1"))
    assert profile.monetary_risk_per_trade == Decimal("10.00")


@pytest.mark.parametrize("valor", [Decimal("0"), Decimal("-1"), Decimal("101")])
def test_percentual_de_risco_fora_do_intervalo(valor: Decimal) -> None:
    with pytest.raises(ValidationError):
        RiskProfile(risk_per_trade_pct=valor)


def test_kill_switch_desligado_por_padrao() -> None:
    assert RiskProfile().kill_switch_active is False


def test_perfil_padrao_usa_conta_pequena_de_estudo() -> None:
    profile = RiskProfile()
    assert profile.capital == Decimal("100.00")
    assert profile.risk_per_trade_pct == Decimal("2.0")
    assert profile.max_exposure_per_symbol_pct == Decimal("60.0")
    assert profile.max_open_positions == 1
    assert profile.min_risk_reward == Decimal("2.0")


def test_quantidade_negativa_e_rejeitada() -> None:
    with pytest.raises(ValidationError):
        PositionSize(
            capital=Decimal("100000.00"),
            risk_pct=Decimal("0.5"),
            monetary_risk=Decimal("500.00"),
            entry=Decimal("10.00"),
            stop=Decimal("9.50"),
            risk_per_share=Decimal("0.50"),
            raw_quantity=-1,
            final_quantity=0,
        )


def test_decisao_rejeitada_expoe_regras() -> None:
    decision = RiskDecision(approved=False, blocking_rules=("perda_diaria_maxima",))
    assert decision.rejected
    assert decision.sizing is None
    assert "perda_diaria_maxima" in decision.blocking_rules


def test_decisao_aprovada() -> None:
    assert RiskDecision(approved=True).rejected is False
