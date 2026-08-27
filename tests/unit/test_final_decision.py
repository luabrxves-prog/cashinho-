from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cashinho.domain.enums import Timeframe
from cashinho.pipeline.final_decision import make_final_decision
from cashinho.pipeline.market_regime import MarketRegime
from cashinho.pipeline.opportunities import Opportunity


def opportunity(side: str = "BUY", **changes: object) -> Opportunity:
    values: dict[str, object] = {
        "symbol": "PETR4",
        "side": side,
        "regime": MarketRegime.TREND_UP,
        "recommended_timeframe": Timeframe.M5,
        "context_timeframes": (Timeframe.H1,),
        "trigger_timeframe": Timeframe.M1,
        "score": 80,
        "entry": Decimal("10"),
        "stop": Decimal("9") if side == "BUY" else Decimal("11"),
        "target": Decimal("12") if side == "BUY" else Decimal("8"),
        "risk_reward": 2.0,
        "trigger_confirmed": True,
        "reasons": ("alinhado",),
        "rejection_reasons": (),
        "timestamp": datetime(2026, 8, 20, tzinfo=UTC),
    }
    values.update(changes)
    return Opportunity(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_entrada_valida(side: str) -> None:
    decision = make_final_decision(
        opportunity(side),
        data_quality_approved=True,
        risk_approved=True,
        candles_closed=True,
    )
    assert decision.should_enter
    assert decision.side == side


@pytest.mark.parametrize(
    ("changes", "kwargs", "reason"),
    [
        ({"trigger_confirmed": False}, {}, "gatilho"),
        (
            {"recommended_timeframe": None, "rejection_reasons": ("Conflito forte.",)},
            {},
            "Timeframes",
        ),
        ({}, {"data_quality_approved": False}, "qualidade"),
        ({}, {"market_approved": False}, "mercado"),
        ({}, {"operational_policy_approved": False}, "base de estudo"),
        ({}, {"risk_approved": False}, "Risk Manager"),
        ({"risk_reward": 1.0}, {}, "risco/retorno"),
    ],
)
def test_requisitos_obrigatorios_bloqueiam(
    changes: dict[str, object], kwargs: dict[str, bool], reason: str
) -> None:
    arguments = {"data_quality_approved": True, "risk_approved": True, "candles_closed": True}
    arguments.update(kwargs)
    decision = make_final_decision(opportunity(**changes), **arguments)
    assert not decision.should_enter
    assert decision.side == "NONE"
    assert reason.lower() in " ".join(decision.reasons).lower()


def test_candle_aberto_nunca_libera() -> None:
    assert not make_final_decision(
        opportunity(), data_quality_approved=True, risk_approved=True, candles_closed=False
    ).should_enter


def test_timeframe_analisado_e_preservado_quando_nao_entra() -> None:
    decision = make_final_decision(
        opportunity(trigger_confirmed=False),
        data_quality_approved=True,
        risk_approved=True,
        candles_closed=True,
    )
    assert not decision.should_enter
    assert decision.timeframe is Timeframe.M5


def test_score_sozinho_nunca_libera() -> None:
    decision = make_final_decision(
        opportunity(score=100, trigger_confirmed=False),
        data_quality_approved=True,
        risk_approved=True,
        candles_closed=True,
    )
    assert not decision.should_enter
