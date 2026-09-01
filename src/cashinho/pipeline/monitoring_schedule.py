"""Priorizacao de monitoramento em tempo real."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from cashinho.pipeline.opportunity_quality import AlertLevel


class MonitoringState(StrEnum):
    COLD = "FRIO"
    OBSERVATION = "OBSERVAÇÃO"
    PREPARATION = "PREPARAÇÃO"
    POSSIBLE_ENTRY = "ENTRADA POSSÍVEL"


@dataclass(frozen=True, slots=True)
class MonitoringCadence:
    state: MonitoringState
    refresh_seconds: int
    reason: str


def cadence_for_alert(alert_level: AlertLevel, *, base_refresh_seconds: int = 5) -> MonitoringCadence:
    """Escolhe frequencia de leitura conforme proximidade da oportunidade."""
    if alert_level is AlertLevel.POSSIBLE_ENTRY:
        return MonitoringCadence(
            MonitoringState.POSSIBLE_ENTRY,
            max(1, base_refresh_seconds),
            "Condições principais confirmadas; monitoramento intensivo.",
        )
    if alert_level is AlertLevel.PREPARATION:
        return MonitoringCadence(
            MonitoringState.PREPARATION,
            max(2, base_refresh_seconds * 2),
            "A maior parte das condições apareceu; acompanhar de perto.",
        )
    if alert_level is AlertLevel.OBSERVATION:
        return MonitoringCadence(
            MonitoringState.OBSERVATION,
            max(5, base_refresh_seconds * 4),
            "Setup começou a aparecer; atualização moderada.",
        )
    return MonitoringCadence(
        MonitoringState.COLD,
        max(15, base_refresh_seconds * 12),
        "Sem condição relevante; atualização econômica.",
    )
