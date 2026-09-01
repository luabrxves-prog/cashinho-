from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cashinho.domain.enums import DataStatus, Timeframe
from cashinho.pipeline.market_regime import MarketRegime, RegimeAnalysis
from cashinho.pipeline.multi_timeframe import TimeframeAnalysis
from cashinho.pipeline.operational_policy import OperationalPolicyDecision
from cashinho.pipeline.opportunities import Opportunity
from cashinho.pipeline.opportunity_quality import AlertLevel, assess_opportunity_quality
from cashinho.pipeline.study_mode import MarketStudy
from tests.unit.test_entry_signal_v2 import _panel, _series


def _opportunity(**changes: object) -> Opportunity:
    values: dict[str, object] = {
        "symbol": "PETR4",
        "side": "BUY",
        "regime": MarketRegime.TREND_UP,
        "recommended_timeframe": Timeframe.M15,
        "context_timeframes": (Timeframe.H1, Timeframe.D1),
        "trigger_timeframe": Timeframe.M15,
        "score": 85,
        "entry": Decimal("10"),
        "stop": Decimal("9"),
        "target": Decimal("12"),
        "risk_reward": 2.0,
        "trigger_confirmed": True,
        "reasons": ("Tendencia alinhada.", "Volume confirmou."),
        "rejection_reasons": (),
        "timestamp": datetime(2026, 8, 28, 13, tzinfo=UTC),
    }
    values.update(changes)
    return Opportunity(**values)  # type: ignore[arg-type]


def _market(approved: bool = True) -> MarketStudy:
    return MarketStudy(
        side="BUY",
        bias="BUY" if approved else "SELL",
        approved=approved,
        confidence=75 if approved else 25,
        symbols_evaluated=4,
        directional_symbols=4,
        aligned_symbols=3 if approved else 1,
        neutral_symbols=0,
        reason="Mercado amplo apoia." if approved else "Mercado amplo bloqueou.",
        sample_limited=False,
        directions={"PETR4": "BUY", "VALE3": "BUY"},
    )


def _analysis() -> TimeframeAnalysis:
    regime = RegimeAnalysis(
        MarketRegime.TREND_UP,
        80,
        "BUY",
        80,
        "ASCENDENTE",
        "NORMAL",
        ("Tendencia de alta.",),
        {},
    )
    return TimeframeAnalysis(Timeframe.M15, regime, _panel_signal())


def _range_analysis() -> TimeframeAnalysis:
    regime = RegimeAnalysis(
        MarketRegime.RANGE,
        80,
        "BUY",
        80,
        "LATERAL",
        "NORMAL",
        ("Mercado lateral.",),
        {},
    )
    return TimeframeAnalysis(Timeframe.M15, regime, _panel_signal())


def _high_volatility_analysis() -> TimeframeAnalysis:
    regime = RegimeAnalysis(
        MarketRegime.HIGH_VOLATILITY,
        80,
        "SELL",
        80,
        "INDEFINIDA",
        "HIGH",
        ("Volatilidade alta.",),
        {},
    )
    return TimeframeAnalysis(Timeframe.M15, regime, _panel_signal())


def _panel_signal():
    from cashinho.pipeline.entry_signal import evaluate_entry_signal

    return evaluate_entry_signal(_series(trigger=True), _panel())


def test_qualidade_libera_apenas_possivel_entrada_forte() -> None:
    quality = assess_opportunity_quality(
        _opportunity(),
        data_status=DataStatus.OK,
        risk_approved=True,
        market_study=_market(),
        policy_decision=OperationalPolicyDecision(True),
        selected_analysis=_analysis(),
    )

    assert quality.alert_level is AlertLevel.POSSIBLE_ENTRY
    assert quality.approved_for_entry
    assert quality.total_score >= 80


def test_qualidade_vira_preparacao_quando_falta_gatilho() -> None:
    quality = assess_opportunity_quality(
        _opportunity(trigger_confirmed=False, entry=None, stop=None, target=None),
        data_status=DataStatus.OK,
        risk_approved=True,
        market_study=_market(),
        policy_decision=OperationalPolicyDecision(True),
        selected_analysis=_analysis(),
    )

    assert quality.alert_level is AlertLevel.PREPARATION
    assert not quality.approved_for_entry
    assert "Gatilho" in quality.missing_confirmations


def test_qualidade_bloqueia_quando_base_historica_bloqueia() -> None:
    quality = assess_opportunity_quality(
        _opportunity(),
        data_status=DataStatus.OK,
        risk_approved=True,
        market_study=_market(),
        policy_decision=OperationalPolicyDecision(
            False,
            blocking_rules=("Horario 10:00 historicamente ruim.",),
        ),
        selected_analysis=_analysis(),
    )

    assert quality.alert_level is AlertLevel.NO_TRADE
    assert not quality.approved_for_entry
    assert "10:00" in quality.summary


def test_qualidade_nao_libera_rompimento_comum_em_range() -> None:
    quality = assess_opportunity_quality(
        _opportunity(),
        data_status=DataStatus.OK,
        risk_approved=True,
        market_study=_market(),
        policy_decision=OperationalPolicyDecision(True),
        selected_analysis=_range_analysis(),
    )

    assert quality.alert_level is AlertLevel.NO_TRADE
    assert not quality.approved_for_entry
    assert "Regime lateral" in quality.summary


def test_qualidade_nao_libera_alta_volatilidade_sem_expansao() -> None:
    quality = assess_opportunity_quality(
        _opportunity(side="SELL"),
        data_status=DataStatus.OK,
        risk_approved=True,
        market_study=_market(),
        policy_decision=OperationalPolicyDecision(True),
        selected_analysis=_high_volatility_analysis(),
    )

    assert quality.alert_level is AlertLevel.NO_TRADE
    assert not quality.approved_for_entry
    assert "Alta volatilidade" in quality.summary
