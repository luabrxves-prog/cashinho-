"""Portao de qualidade de dados.

Ponto unico onde se decide se uma serie pode ser analisada. O status e
derivado dos problemas encontrados; nenhum chamador informa o status
diretamente.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from cashinho.core.data_quality import checks
from cashinho.domain.enums import Mode
from cashinho.domain.errors import DataQualityBlockedError
from cashinho.domain.market import CandleSeries
from cashinho.domain.quality import DataQualityIssue, DataQualityReport
from cashinho.observability.logging import get_logger
from cashinho.ports.clock import Clock

logger = get_logger(__name__)

DEFAULT_MINIMUM_CANDLES = 20
"""Piso para que indicadores de janela curta tenham o que calcular."""


def evaluate(
    series: CandleSeries,
    *,
    clock: Clock,
    mode: Mode = Mode.RESEARCH,
    minimum_candles: int = DEFAULT_MINIMUM_CANDLES,
    session_bounds: Sequence[tuple[datetime, datetime]] | None = None,
    latency_ms: int | None = None,
) -> DataQualityReport:
    """Avalia a serie e devolve o relatorio consolidado.

    Serie vazia interrompe a bateria: os demais checks nao teriam o que
    dizer e produziriam uma lista de problemas redundantes que esconderia
    a causa real.
    """
    issues: list[DataQualityIssue] = list(checks.check_empty(series))

    if not issues:
        issues.extend(checks.check_timezone(series))
        issues.extend(checks.check_duplicates(series))
        issues.extend(checks.check_chronological_order(series))
        issues.extend(checks.check_ohlc(series))
        issues.extend(checks.check_volume(series))
        issues.extend(checks.check_insufficient(series, minimum_candles))
        issues.extend(checks.check_gaps(series, session_bounds=session_bounds))
        issues.extend(checks.check_price_jumps(series))
        issues.extend(checks.check_future_closed_candles(series, now=clock.now()))
        issues.extend(checks.check_open_candle_state(series, now=clock.now()))
        if mode.requires_realtime_data:
            issues.extend(checks.check_staleness(series, now=clock.now()))

    report = DataQualityReport.from_issues(
        symbol=series.symbol,
        source=series.source,
        issues=tuple(issues),
        checked_at=clock.now(),
        latency_ms=latency_ms,
        candles_evaluated=len(series),
    )

    logger.info(
        "qualidade de dados avaliada",
        extra={
            "symbol": series.symbol,
            "timeframe": series.timeframe.value,
            "source": series.source,
            "status": report.status.value,
            "issues": len(report.issues),
            "candles": len(series),
        },
    )
    if report.blocked:
        logger.warning(
            "sinal bloqueado por qualidade de dados",
            extra={
                "symbol": series.symbol,
                "timeframe": series.timeframe.value,
                "source": series.source,
                "reasons": [issue.model_dump(mode="json") for issue in report.critical_issues],
            },
        )
    return report


def enforce(report: DataQualityReport) -> DataQualityReport:
    """Interrompe o pipeline quando o status for BLOCKED.

    Usar quando prosseguir com dado ruim seria pior que falhar. A
    interface prefere `evaluate` e renderiza o motivo do bloqueio.
    """
    if report.blocked:
        motivos = "; ".join(str(i) for i in report.critical_issues)
        raise DataQualityBlockedError(f"ANALISE BLOQUEADA — {report.symbol}: {motivos}")
    return report
