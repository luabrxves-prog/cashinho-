"""Comprovacao de origem dos dados usados nos estudos historicos."""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cashinho.domain.enums import Timeframe

MT5_PROVENANCE_FILE = "_mt5_provenance.csv"
MT5_SOURCE = "MetaTrader5"


class DataProvenanceError(ValueError):
    """Os arquivos locais nao tem comprovacao suficiente de origem real."""


def read_mt5_provenance(data_root: Path) -> tuple[dict[str, str], ...]:
    path = data_root / MT5_PROVENANCE_FILE
    if not path.is_file():
        raise DataProvenanceError(
            f"{MT5_PROVENANCE_FILE} nao encontrado em {data_root}. "
            "Exporte o historico pelo MT5 antes de rodar estudo real."
        )
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(csv.DictReader(handle))


def assert_mt5_provenance(
    *,
    data_root: Path,
    symbols: tuple[str, ...],
    timeframes: tuple[Timeframe, ...],
    required_start: datetime,
    required_end: datetime,
) -> tuple[dict[str, str], ...]:
    """Garante que cada simbolo/timeframe foi exportado do MT5 para o periodo."""

    rows = read_mt5_provenance(data_root)
    index = {
        (
            row.get("requested_symbol", "").upper(),
            row.get("timeframe", ""),
        ): row
        for row in rows
        if row.get("source") == MT5_SOURCE
    }
    problems: list[str] = []
    effective_end = _ensure_utc(required_end)
    effective_start = _ensure_utc(required_start)

    start_tolerance = timedelta(days=7)
    for symbol in symbols:
        for timeframe in timeframes:
            row = index.get((symbol.upper(), timeframe.value))
            label = f"{symbol.upper()} {timeframe.value}"
            if row is None:
                problems.append(f"{label}: sem comprovante MT5")
                continue
            if row.get("status") != "ok":
                problems.append(f"{label}: exportacao MT5 falhou ({row.get('message', '')})")
                continue
            try:
                exported_rows = int(row.get("rows", "0"))
            except ValueError:
                exported_rows = 0
            if exported_rows <= 0:
                problems.append(f"{label}: exportacao MT5 sem candles")
                continue
            requested_start = _parse_datetime(row.get("requested_start", ""))
            requested_end = _parse_datetime(row.get("requested_end", ""))
            first_candle = _parse_datetime(row.get("first_candle", ""))
            last_candle = _parse_datetime(row.get("last_candle", ""))
            if (
                requested_start is None
                or requested_end is None
                or first_candle is None
                or last_candle is None
            ):
                problems.append(f"{label}: comprovante sem periodo e candles exportados")
                continue
            if requested_start > effective_start or requested_end < effective_end:
                problems.append(
                    f"{label}: periodo solicitado na exportacao "
                    f"{requested_start.date()} a {requested_end.date()} "
                    f"nao cobre {effective_start.date()} a {effective_end.date()}"
                )
                continue
            if first_candle > effective_start + start_tolerance:
                problems.append(
                    f"{label}: primeiro candle real em {first_candle.date()} "
                    f"fica longe demais do inicio {effective_start.date()}"
                )
                continue
            covers_current_day = last_candle.date() >= effective_end.date()
            if last_candle + timeframe.duration < effective_end and not covers_current_day:
                problems.append(
                    f"{label}: ultimo candle real em {last_candle.date()} "
                    f"nao cobre o fim {effective_end.date()}"
                )

    if problems:
        raise DataProvenanceError(
            "Dados reais MT5 nao comprovados:\n- " + "\n- ".join(problems)
        )
    return rows


def _parse_datetime(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return _ensure_utc(datetime.fromisoformat(raw))
    except ValueError:
        return None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
