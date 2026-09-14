"""Projeções visuais do diário auditável."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from cashinho.domain.journal import (
    DecisionJournalRecord,
    PaperTradeJournalRecord,
    PositionDecisionJournalRecord,
)

DEFAULT_DISPLAY_TIMEZONE = "America/Sao_Paulo"


def _timezone_label(display_timezone: str) -> str:
    return "BRT" if display_timezone == "America/Sao_Paulo" else display_timezone


def _format_datetime(value: datetime | None, display_timezone: str) -> str:
    if value is None:
        return "—"
    return value.astimezone(ZoneInfo(display_timezone)).strftime("%d/%m/%Y %H:%M:%S")


def _format_number(value: object | None, places: int = 2) -> str:
    if value is None:
        return "—"
    try:
        return f"{value:.{places}f}"
    except (TypeError, ValueError):
        return str(value)


def _format_percent(value: object | None) -> str:
    if value is None:
        return "—"
    return f"{_format_number(value)}%"


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def decision_rows(
    records: list[DecisionJournalRecord],
    display_timezone: str = DEFAULT_DISPLAY_TIMEZONE,
) -> list[dict[str, Any]]:
    timezone_label = _timezone_label(display_timezone)
    return [
        {
            "Ativo": record.symbol,
            "Decisão": "ENTRADA LIBERADA" if record.should_enter else "NÃO ENTRAR",
            "Lado": record.side if record.should_enter else "—",
            "Timeframe": record.timeframe or "—",
            "Confiança": record.confidence,
            f"Horário ({timezone_label})": _format_datetime(record.timestamp, display_timezone),
            "Motivo principal": record.primary_reason,
        }
        for record in records
    ]


def paper_trade_rows(
    records: list[PaperTradeJournalRecord],
    display_timezone: str = DEFAULT_DISPLAY_TIMEZONE,
) -> list[dict[str, Any]]:
    timezone_label = _timezone_label(display_timezone)
    return [
        {
            "ID": record.paper_order_id[:8],
            "Ativo": record.symbol,
            "Lado": record.side,
            "Timeframe": record.timeframe or "—",
            "Qtd": record.quantity,
            "Tipo": record.order_type,
            f"Criada em ({timezone_label})": _format_datetime(record.created_at, display_timezone),
            "Entrada planejada": _format_number(record.entry),
            "Stop": _format_number(record.stop),
            "Alvo": _format_number(record.target),
            f"Preenchida em ({timezone_label})": _format_datetime(
                record.filled_at, display_timezone
            ),
            "Preço preenchido": _format_number(record.fill_price),
            "Saída": _format_number(record.close_price),
            f"Fechada em ({timezone_label})": _format_datetime(record.closed_at, display_timezone),
            "Risco": _format_number(record.monetary_risk),
            "Notional": _format_number(record.notional),
            "Resultado": _format_number(record.pnl_value),
            "Resultado %": _format_percent(record.pnl_pct),
            "Resultado em R": _format_number(record.result_in_r),
            "Duração": _format_duration(record.duration_seconds),
            "Status": record.status,
            "Motivo": record.close_reason or "—",
        }
        for record in records
    ]


def operational_decision_rows(
    entries: list[DecisionJournalRecord],
    positions: list[PositionDecisionJournalRecord],
    display_timezone: str = DEFAULT_DISPLAY_TIMEZONE,
) -> list[dict[str, Any]]:
    """Une ENTRAR/NÃO ENTRAR e MANTER/SAIR em uma cronologia simples."""

    timezone_label = _timezone_label(display_timezone)
    timestamp_column = f"Horário ({timezone_label})"
    rows: list[tuple[datetime, dict[str, Any]]] = []

    for record in entries:
        rows.append(
            (
                record.timestamp,
                {
                    "Ativo": record.symbol,
                    "Decisão": "ENTRADA LIBERADA" if record.should_enter else "NÃO ENTRAR",
                    "Lado": record.side if record.should_enter else "—",
                    "Timeframe": record.timeframe or "—",
                    "Confiança": record.confidence,
                    timestamp_column: _format_datetime(record.timestamp, display_timezone),
                    "Motivo principal": record.primary_reason,
                },
            )
        )

    for record in positions:
        rows.append(
            (
                record.timestamp,
                {
                    "Ativo": record.symbol,
                    "Decisão": "MANTER" if record.action == "HOLD" else "SAIR",
                    "Lado": record.side,
                    "Timeframe": "—",
                    "Confiança": record.confidence,
                    timestamp_column: _format_datetime(record.timestamp, display_timezone),
                    "Motivo principal": record.primary_reason,
                },
            )
        )

    return [row for _timestamp, row in sorted(rows, key=lambda item: item[0], reverse=True)]
