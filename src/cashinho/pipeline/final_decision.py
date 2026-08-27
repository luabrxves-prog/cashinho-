"""Decisão binária final consumida pela interface do Cashinho."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from cashinho.domain.enums import Timeframe
from cashinho.pipeline.opportunities import Opportunity


@dataclass(frozen=True, slots=True)
class FinalDecision:
    should_enter: bool
    side: str
    symbol: str
    timeframe: Timeframe | None
    confidence: int
    entry: Decimal | None
    stop: Decimal | None
    target: Decimal | None
    risk_reward: float | None
    primary_reason: str
    reasons: tuple[str, ...]
    timestamp: datetime

    @property
    def state(self) -> str:
        return "ENTRADA LIBERADA" if self.should_enter else "NÃO ENTRAR"


def make_final_decision(
    opportunity: Opportunity,
    *,
    data_quality_approved: bool,
    risk_approved: bool,
    candles_closed: bool,
    market_approved: bool = True,
    market_reason: str | None = None,
    operational_policy_approved: bool = True,
    operational_policy_reason: str | None = None,
    extra_reasons: tuple[str, ...] = (),
    minimum_confidence: int = 60,
    minimum_risk_reward: Decimal = Decimal("1.5"),
) -> FinalDecision:
    """Reduz todas as camadas técnicas a ENTRADA LIBERADA ou NÃO ENTRAR."""
    failures: list[str] = []
    if not data_quality_approved:
        failures.append("A qualidade dos dados não permite uma decisão segura.")
    if not market_approved:
        failures.append(market_reason or "O mercado amplo não aprovou a direção do ativo.")
    if not operational_policy_approved:
        failures.append(
            operational_policy_reason
            or "A base de estudo histórico bloqueou este contexto operacional."
        )
    if not candles_closed:
        failures.append("A decisão aguarda o fechamento do candle.")
    if opportunity.side not in {"BUY", "SELL"}:
        failures.append("Não existe direção operacional definida.")
    if opportunity.recommended_timeframe is None:
        failures.append("Timeframes ainda não estão suficientemente alinhados.")
    failures.extend(opportunity.rejection_reasons)
    if not opportunity.trigger_confirmed:
        failures.append("O gatilho de entrada ainda não foi confirmado.")
    geometry = (
        opportunity.entry is not None
        and opportunity.stop is not None
        and opportunity.target is not None
        and (
            opportunity.stop < opportunity.entry < opportunity.target
            if opportunity.side == "BUY"
            else opportunity.target < opportunity.entry < opportunity.stop
        )
    )
    if not geometry:
        failures.append("Entrada, stop e alvo não formam uma operação válida.")
    if (
        opportunity.risk_reward is None
        or Decimal(str(opportunity.risk_reward)) < minimum_risk_reward
    ):
        failures.append("A relação risco/retorno está abaixo do mínimo permitido.")
    if opportunity.score < minimum_confidence:
        failures.append("A confiança da oportunidade está abaixo do mínimo.")
    if not risk_approved:
        failures.append("O Risk Manager não aprovou a operação.")

    failures = list(dict.fromkeys(failures))
    approved = not failures
    reasons = (*extra_reasons, *opportunity.reasons, *failures)
    primary = "Todos os requisitos obrigatórios foram confirmados." if approved else failures[0]
    return FinalDecision(
        approved,
        opportunity.side if approved else "NONE",
        opportunity.symbol,
        opportunity.recommended_timeframe,
        opportunity.score,
        opportunity.entry if approved else None,
        opportunity.stop if approved else None,
        opportunity.target if approved else None,
        opportunity.risk_reward if approved else None,
        primary,
        reasons,
        opportunity.timestamp,
    )
