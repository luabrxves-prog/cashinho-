"""Score profissional e niveis de alerta para oportunidades.

O score nao e probabilidade de acerto. Ele e uma leitura auditavel de
qualidade: dados, mercado, historico, gatilho, risco e confluencia.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from cashinho.domain.enums import DataStatus
from cashinho.pipeline.market_regime import MarketRegime
from cashinho.pipeline.multi_timeframe import TimeframeAnalysis
from cashinho.pipeline.operational_policy import OperationalPolicyDecision
from cashinho.pipeline.opportunities import Opportunity
from cashinho.pipeline.study_mode import MarketStudy
from cashinho.pipeline.trade_setup import TradeSetupType


class AlertLevel(StrEnum):
    NO_TRADE = "NÃO OPERAR"
    OBSERVATION = "OBSERVAÇÃO"
    PREPARATION = "PREPARAÇÃO"
    POSSIBLE_ENTRY = "POSSÍVEL ENTRADA"


@dataclass(frozen=True, slots=True)
class QualityFactor:
    name: str
    score: int
    maximum: int
    approved: bool
    explanation: str
    plain_language: str


@dataclass(frozen=True, slots=True)
class OpportunityQuality:
    total_score: int
    alert_level: AlertLevel
    factors: tuple[QualityFactor, ...]
    missing_confirmations: tuple[str, ...]
    blocking_reasons: tuple[str, ...]

    @property
    def approved_for_entry(self) -> bool:
        return self.alert_level is AlertLevel.POSSIBLE_ENTRY and not self.blocking_reasons

    @property
    def confirmations(self) -> tuple[QualityFactor, ...]:
        return tuple(factor for factor in self.factors if factor.approved)

    @property
    def summary(self) -> str:
        if self.blocking_reasons:
            return "Não operar: " + " | ".join(self.blocking_reasons)
        if self.alert_level is AlertLevel.POSSIBLE_ENTRY:
            return "Possível entrada: critérios principais atendidos."
        if self.alert_level is AlertLevel.PREPARATION:
            return "Preparação: oportunidade perto do ponto, mas ainda incompleta."
        return "Observação: existe algo interessante, mas ainda sem entrada."


def assess_opportunity_quality(
    opportunity: Opportunity,
    *,
    data_status: DataStatus,
    risk_approved: bool,
    market_study: MarketStudy,
    policy_decision: OperationalPolicyDecision,
    selected_analysis: TimeframeAnalysis | None,
    minimum_entry_score: int = 80,
) -> OpportunityQuality:
    """Calcula qualidade da oportunidade sem prometer resultado futuro."""

    factors = (
        _data_factor(data_status),
        _market_factor(market_study),
        _historical_factor(policy_decision),
        _trigger_factor(opportunity),
        _risk_factor(opportunity, risk_approved),
        _confluence_factor(opportunity, selected_analysis),
    )
    total = sum(factor.score for factor in factors)
    blocking = _blocking_reasons(opportunity, factors, policy_decision)
    missing = tuple(factor.name for factor in factors if not factor.approved)
    level = _alert_level(
        opportunity,
        total_score=total,
        blocking_reasons=blocking,
        missing_confirmations=missing,
        minimum_entry_score=minimum_entry_score,
    )
    return OpportunityQuality(
        total_score=total,
        alert_level=level,
        factors=factors,
        missing_confirmations=missing,
        blocking_reasons=blocking,
    )


def _data_factor(data_status: DataStatus) -> QualityFactor:
    approved = data_status is not DataStatus.BLOCKED
    return QualityFactor(
        "Dados",
        15 if approved else 0,
        15,
        approved,
        "Qualidade dos candles e integridade da fonte.",
        "Se os dados estiverem velhos, incompletos ou quebrados, o app nao deve sinalizar.",
    )


def _market_factor(market_study: MarketStudy) -> QualityFactor:
    approved = market_study.approved
    partial = min(10, max(0, market_study.confidence // 10)) if not approved else 15
    return QualityFactor(
        "Mercado amplo",
        partial,
        15,
        approved,
        market_study.reason,
        "Antes do ativo, o app confere se o mercado como um todo apoia essa direcao.",
    )


def _historical_factor(policy_decision: OperationalPolicyDecision) -> QualityFactor:
    approved = policy_decision.approved
    score = 15 if approved and not policy_decision.warnings else 8 if approved else 0
    return QualityFactor(
        "Base historica",
        score,
        15,
        approved,
        policy_decision.summary,
        "O app compara o contexto atual com padroes que ja foram ruins no estudo.",
    )


def _trigger_factor(opportunity: Opportunity) -> QualityFactor:
    if opportunity.trigger_confirmed:
        score = 20
        plain = "O ponto de entrada foi confirmado por candle fechado e volume."
    elif opportunity.side in {"BUY", "SELL"} and opportunity.recommended_timeframe is not None:
        score = 10
        plain = "Existe direcao, mas ainda falta o gatilho final."
    else:
        score = 0
        plain = "Ainda nao existe direcao operacional clara."
    return QualityFactor(
        "Gatilho",
        score,
        20,
        opportunity.trigger_confirmed,
        "Entrada confirmada." if opportunity.trigger_confirmed else "Aguardando confirmacao.",
        plain,
    )


def _risk_factor(opportunity: Opportunity, risk_approved: bool) -> QualityFactor:
    rr_ok = opportunity.risk_reward is not None and opportunity.risk_reward >= 2
    approved = risk_approved and rr_ok
    score = 15 if approved else 8 if risk_approved else 0
    return QualityFactor(
        "Risco",
        score,
        15,
        approved,
        "Risco e retorno compativeis." if approved else "Risco ainda nao aprovado.",
        "A entrada so presta se o stop, o alvo e o tamanho couberem no capital.",
    )


def _confluence_factor(
    opportunity: Opportunity,
    selected_analysis: TimeframeAnalysis | None,
) -> QualityFactor:
    technical_score = opportunity.score
    regime_score = selected_analysis.regime.confidence if selected_analysis is not None else 0
    combined = int((technical_score * 0.7) + (regime_score * 0.3))
    score = min(20, max(0, combined // 5))
    regime = selected_analysis.regime.regime if selected_analysis is not None else None
    setup = selected_analysis.setup if selected_analysis is not None else None
    if regime is MarketRegime.RANGE:
        valid_range_setups = {
            TradeSetupType.RANGE_REVERSION,
            TradeSetupType.VWAP_REVERSION,
            TradeSetupType.SUPPORT_RESISTANCE_REVERSAL,
        }
        if setup is not None and setup.kind in valid_range_setups and setup.approved:
            score = min(20, max(score, setup.score // 5))
            approved = True
            explanation = "Range aprovado apenas com reversao, VWAP ou suporte/resistencia."
            plain = "Mercado lateral so entra perto das bordas ou voltando para a VWAP."
        else:
            score = min(score, 8)
            approved = False
            explanation = "Regime lateral exige setup especifico; rompimento comum nao basta."
            plain = "Quando o mercado esta andando de lado, o app precisa de uma entrada propria de range."
    elif regime is MarketRegime.HIGH_VOLATILITY:
        valid_expansion_setups = {
            TradeSetupType.EXPANSION_BREAKOUT,
            TradeSetupType.BREAKOUT_RETEST,
            TradeSetupType.OPENING_RANGE_EXPANSION,
        }
        if setup is not None and setup.kind in valid_expansion_setups and setup.approved:
            score = min(20, max(score, setup.score // 5))
            approved = True
            explanation = "Alta volatilidade aceita apenas com expansao, reteste ou abertura forte."
            plain = "Mercado agitado so entra se houver rompimento limpo, reteste ou abertura forte."
        else:
            score = min(score, 8)
            approved = False
            explanation = "Alta volatilidade sem expansao clara aumenta demais o risco da conta pequena."
            plain = "Quando o mercado esta muito agitado, o app precisa esperar expansao mais limpa."
    else:
        approved = score >= 14 and len(opportunity.reasons) >= 2
        explanation = f"{len(opportunity.reasons)} fator(es) tecnico(s) considerados."
        plain = "O app exige varias evidencias juntas; um indicador isolado nao basta."
    return QualityFactor(
        "Confluencia",
        score,
        20,
        approved,
        explanation,
        plain,
    )


def _blocking_reasons(
    opportunity: Opportunity,
    factors: tuple[QualityFactor, ...],
    policy_decision: OperationalPolicyDecision,
) -> tuple[str, ...]:
    reasons = [*opportunity.rejection_reasons, *policy_decision.blocking_rules]
    for factor in factors:
        if factor.name in {"Dados", "Base historica", "Risco", "Confluencia"} and not factor.approved:
            reasons.append(f"{factor.name}: {factor.explanation}")
    return tuple(dict.fromkeys(reasons))


def _alert_level(
    opportunity: Opportunity,
    *,
    total_score: int,
    blocking_reasons: tuple[str, ...],
    missing_confirmations: tuple[str, ...],
    minimum_entry_score: int,
) -> AlertLevel:
    if blocking_reasons:
        return AlertLevel.NO_TRADE
    if opportunity.trigger_confirmed and total_score >= minimum_entry_score:
        return AlertLevel.POSSIBLE_ENTRY
    if total_score >= 65 and "Gatilho" in missing_confirmations:
        return AlertLevel.PREPARATION
    if total_score >= 40:
        return AlertLevel.OBSERVATION
    return AlertLevel.NO_TRADE
