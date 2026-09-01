"""Modelo e ranking explicável de oportunidades, independente da UI."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from cashinho.domain.enums import DataStatus, Timeframe
from cashinho.pipeline.market_regime import MarketRegime
from cashinho.pipeline.multi_timeframe import TimeframeAdvice, TimeframeAnalysis


@dataclass(frozen=True, slots=True)
class Opportunity:
    symbol: str
    side: str
    regime: MarketRegime
    recommended_timeframe: Timeframe | None
    context_timeframes: tuple[Timeframe, ...]
    trigger_timeframe: Timeframe | None
    score: int
    entry: Decimal | None
    stop: Decimal | None
    target: Decimal | None
    risk_reward: float | None
    trigger_confirmed: bool
    reasons: tuple[str, ...]
    rejection_reasons: tuple[str, ...]
    timestamp: datetime
    setup_type: str = "NO_CLEAR_SETUP"

    @property
    def state(self) -> str:
        if self.rejection_reasons:
            return "NÃO OPERAR"
        return "ENTRADA LIBERADA" if self.trigger_confirmed else "AGUARDANDO GATILHO"


def build_opportunity(
    *,
    symbol: str,
    advice: TimeframeAdvice,
    analyses: dict[Timeframe, TimeframeAnalysis],
    data_status: DataStatus,
    risk_approved: bool,
    timestamp: datetime,
) -> Opportunity:
    rejection: list[str] = []
    if data_status is DataStatus.BLOCKED:
        rejection.append("Data Quality bloqueou o ativo.")
    if not risk_approved:
        rejection.append("Risk Manager bloqueou o ativo.")
    if advice.rejection_reason:
        rejection.append(advice.rejection_reason)
    selected = analyses.get(advice.recommended_timeframe) if advice.recommended_timeframe else None
    signal = selected.signal if selected else None
    regime = selected.regime.regime if selected else MarketRegime.INDETERMINATE
    setup_type = selected.setup.kind.value if selected and selected.setup else "NO_CLEAR_SETUP"
    trigger = bool(signal and signal.trigger_confirmed and not rejection)
    score = advice.score + (10 if trigger else 0)
    return Opportunity(
        symbol,
        advice.side,
        regime,
        advice.recommended_timeframe,
        advice.context_timeframes,
        advice.trigger_timeframe,
        min(score, 100),
        signal.entry if signal else None,
        signal.stop if signal else None,
        signal.target if signal else None,
        signal.risk_reward if signal else None,
        trigger,
        advice.reasons,
        tuple(rejection),
        timestamp,
        setup_type,
    )


def rank_opportunities(opportunities: list[Opportunity]) -> list[Opportunity]:
    normalized = [
        replace(item, score=0, trigger_confirmed=False) if item.rejection_reasons else item
        for item in opportunities
    ]
    return sorted(
        normalized, key=lambda item: (not item.rejection_reasons, item.score), reverse=True
    )
