from __future__ import annotations

from cashinho.pipeline.monitoring_schedule import MonitoringState, cadence_for_alert
from cashinho.pipeline.opportunity_quality import AlertLevel


def test_entrada_possivel_tem_maior_prioridade() -> None:
    cadence = cadence_for_alert(AlertLevel.POSSIBLE_ENTRY, base_refresh_seconds=5)
    assert cadence.state is MonitoringState.POSSIBLE_ENTRY
    assert cadence.refresh_seconds == 5


def test_ativo_frio_atualiza_com_menos_frequencia() -> None:
    cadence = cadence_for_alert(AlertLevel.NO_TRADE, base_refresh_seconds=5)
    assert cadence.state is MonitoringState.COLD
    assert cadence.refresh_seconds == 60
