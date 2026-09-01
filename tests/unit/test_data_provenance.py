from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from cashinho.domain.enums import Timeframe
from cashinho.pipeline.data_provenance import (
    DataProvenanceError,
    assert_mt5_provenance,
)

HEADER = (
    "source,status,requested_symbol,resolved_symbol,timeframe,rows,"
    "requested_start,requested_end,first_candle,last_candle,exported_at,"
    "terminal_company,terminal_server,terminal_version,account_mode,"
    "broker_timezone,message\n"
)


def _write_provenance(
    root: Path,
    *,
    symbol: str = "PETR4",
    timeframe: str = "5m",
    rows: int = 100,
    start: str = "2020-01-01T00:00:00+00:00",
    end: str = "2021-01-01T00:00:00+00:00",
    status: str = "ok",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    body = (
        f"MetaTrader5,{status},{symbol},{symbol},{timeframe},{rows},"
        f"{start},{end},{start},{end},2026-09-01T12:00:00+00:00,"
        "Genial Investimentos,GenialInvestimentos-PRD,5.0.45,DEMO,"
        "America/Sao_Paulo,exato\n"
    )
    (root / "_mt5_provenance.csv").write_text(HEADER + body, encoding="utf-8")


def test_exige_comprovante_do_mt5(tmp_path: Path) -> None:
    with pytest.raises(DataProvenanceError, match="nao encontrado"):
        assert_mt5_provenance(
            data_root=tmp_path,
            symbols=("PETR4",),
            timeframes=(Timeframe.M5,),
            required_start=datetime(2020, 1, 1, tzinfo=UTC),
            required_end=datetime(2021, 1, 1, tzinfo=UTC),
        )


def test_aprova_quando_o_mt5_cobre_o_periodo(tmp_path: Path) -> None:
    _write_provenance(tmp_path)

    rows = assert_mt5_provenance(
        data_root=tmp_path,
        symbols=("PETR4",),
        timeframes=(Timeframe.M5,),
        required_start=datetime(2020, 1, 1, tzinfo=UTC),
        required_end=datetime(2021, 1, 1, tzinfo=UTC),
    )

    assert rows[0]["source"] == "MetaTrader5"


def test_reprova_quando_o_periodo_exportado_nao_cobre_o_estudo(tmp_path: Path) -> None:
    _write_provenance(tmp_path, start="2020-06-01T00:00:00+00:00")

    with pytest.raises(DataProvenanceError, match="nao cobre"):
        assert_mt5_provenance(
            data_root=tmp_path,
            symbols=("PETR4",),
            timeframes=(Timeframe.M5,),
            required_start=datetime(2020, 1, 1, tzinfo=UTC),
            required_end=datetime(2021, 1, 1, tzinfo=UTC),
        )


def test_reprova_quando_os_candles_reais_nao_cobrem_o_estudo(tmp_path: Path) -> None:
    root = tmp_path
    _write_provenance(root)
    path = root / "_mt5_provenance.csv"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(
            "2020-01-01T00:00:00+00:00,2021-01-01T00:00:00+00:00,"
            "2020-01-01T00:00:00+00:00",
            "2020-01-01T00:00:00+00:00,2021-01-01T00:00:00+00:00,"
            "2020-06-01T00:00:00+00:00",
        ),
        encoding="utf-8",
    )

    with pytest.raises(DataProvenanceError, match="primeiro candle real"):
        assert_mt5_provenance(
            data_root=tmp_path,
            symbols=("PETR4",),
            timeframes=(Timeframe.M5,),
            required_start=datetime(2020, 1, 1, tzinfo=UTC),
            required_end=datetime(2021, 1, 1, tzinfo=UTC),
        )


def test_reprova_exportacao_sem_candles(tmp_path: Path) -> None:
    _write_provenance(tmp_path, rows=0)

    with pytest.raises(DataProvenanceError, match="sem candles"):
        assert_mt5_provenance(
            data_root=tmp_path,
            symbols=("PETR4",),
            timeframes=(Timeframe.M5,),
            required_start=datetime(2020, 1, 1, tzinfo=UTC),
            required_end=datetime(2021, 1, 1, tzinfo=UTC),
        )
