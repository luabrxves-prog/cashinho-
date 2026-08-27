"""Modelos de risco.

Apenas os modelos. O algoritmo de dimensionamento e as regras do Risk
Manager entram na Fase 4, com cobertura de testes de prioridade maxima.
Manter os modelos estaveis antes torna aquela fase uma implementacao de
regras, e nao uma renegociacao de contratos.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from cashinho.domain.types import DomainModel, Money, Price


class RiskProfile(DomainModel):
    """Limites de risco vigentes.

    O Risk Manager tem autoridade superior a estrategia: nenhum destes
    limites pode ser sobrescrito por um sinal, por melhor que seja o score.
    """

    name: str = "default"
    capital: Money = Decimal("100.00")

    risk_per_trade_pct: Decimal = Field(
        default=Decimal("2.0"), gt=0, le=100, description="Risco maximo por operacao (%)"
    )
    max_daily_loss_pct: Decimal = Field(
        default=Decimal("4.0"), gt=0, le=100, description="Perda diaria maxima (%)"
    )
    max_drawdown_pct: Decimal = Field(
        default=Decimal("10.0"), gt=0, le=100, description="Drawdown maximo tolerado (%)"
    )
    max_exposure_pct: Decimal = Field(
        default=Decimal("100.0"), gt=0, le=100, description="Exposicao maxima total (%)"
    )
    max_exposure_per_symbol_pct: Decimal = Field(
        default=Decimal("60.0"), gt=0, le=100, description="Exposicao maxima por ativo (%)"
    )

    max_trades_per_day: int = Field(default=2, ge=0)
    max_consecutive_losses: int = Field(default=2, ge=0)
    max_open_positions: int = Field(default=1, ge=0)

    min_risk_reward: Decimal = Field(
        default=Decimal("2.0"), gt=0, description="Relacao risco/retorno minima aceita"
    )

    kill_switch_active: bool = False

    @property
    def monetary_risk_per_trade(self) -> Decimal:
        """Risco monetario maximo por operacao, em reais."""
        return (self.capital * self.risk_per_trade_pct / Decimal("100")).quantize(
            Decimal("0.01")
        )


class PositionSize(DomainModel):
    """Resultado do dimensionamento de posicao.

    Todos os passos intermediarios sao preservados. `limiting_constraint`
    responde a pergunta "por que a quantidade nao foi maior", que e
    exigencia de explicabilidade.
    """

    capital: Money
    risk_pct: Decimal
    monetary_risk: Money
    entry: Price
    stop: Price
    risk_per_share: Money
    raw_quantity: int = Field(ge=0)
    final_quantity: int = Field(ge=0)
    lot_size: int = Field(default=100, gt=0)
    limiting_constraint: str | None = None
    notional: Money = Decimal("0.00")


class RiskDecision(DomainModel):
    """Veredito do Risk Manager sobre uma oportunidade.

    `blocking_rules` nomeia as regras que rejeitaram. Uma decisao negativa
    sem regra nomeada nao e auditavel e nao deve existir.
    """

    approved: bool
    blocking_rules: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    sizing: PositionSize | None = None
    profile_name: str = "default"
    profile_hash: str = Field(
        default="", description="Hash da configuracao de risco usada, para auditoria"
    )

    @property
    def rejected(self) -> bool:
        return not self.approved
