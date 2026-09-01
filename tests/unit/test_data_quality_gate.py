"""Portao de qualidade: derivacao do status e bloqueio do pipeline."""

from __future__ import annotations

from datetime import timedelta

import pytest

from cashinho.core.data_quality.gate import enforce, evaluate
from cashinho.core.time.clocks import FrozenClock
from cashinho.domain.enums import DataStatus, Mode, Timeframe
from cashinho.domain.errors import DataQualityBlockedError
from tests.conftest import REFERENCE_INSTANT, make_candle, make_series


def test_serie_saudavel_resulta_em_ok(frozen_clock: FrozenClock) -> None:
    serie = make_series(count=30, end=REFERENCE_INSTANT)
    report = evaluate(serie, clock=frozen_clock, mode=Mode.RESEARCH)
    assert report.status is DataStatus.OK
    assert not report.blocked
    assert report.candles_evaluated == 30


def test_serie_vazia_bloqueia(frozen_clock: FrozenClock) -> None:
    report = evaluate(make_series(count=0), clock=frozen_clock)
    assert report.status is DataStatus.BLOCKED
    assert [i.code for i in report.issues] == ["EMPTY"]


def test_serie_vazia_nao_acumula_problemas_redundantes(frozen_clock: FrozenClock) -> None:
    """Um unico problema aponta a causa; uma lista longa a esconderia."""
    report = evaluate(make_series(count=0), clock=frozen_clock)
    assert len(report.issues) == 1


def test_amostra_curta_bloqueia(frozen_clock: FrozenClock) -> None:
    report = evaluate(make_series(count=3), clock=frozen_clock, minimum_candles=20)
    assert report.blocked
    assert any(i.code == "INSUFFICIENT" for i in report.issues)


def test_lacuna_degrada_mas_nao_bloqueia(frozen_clock: FrozenClock) -> None:
    candles = tuple(
        make_candle(REFERENCE_INSTANT - timedelta(minutes=5 * i))
        for i in range(29, 0, -1)
        if i != 5
    )
    serie = make_series(count=30).model_copy(update={"candles": candles})
    report = evaluate(serie, clock=frozen_clock, minimum_candles=5)
    assert report.status is DataStatus.DEGRADED
    assert not report.blocked


def test_modo_com_tempo_real_verifica_atraso() -> None:
    serie = make_series(count=30, end=REFERENCE_INSTANT)
    clock = FrozenClock(REFERENCE_INSTANT + timedelta(hours=3))
    report = evaluate(serie, clock=clock, mode=Mode.PAPER)
    assert report.blocked
    assert any(i.code == "STALE" for i in report.issues)


def test_bloqueia_candle_fechado_no_futuro(frozen_clock: FrozenClock) -> None:
    serie = make_series(count=30, end=frozen_clock.now() + timedelta(hours=1))
    report = evaluate(serie, clock=frozen_clock, mode=Mode.RESEARCH)
    assert report.blocked
    assert any(i.code == "FUTURE_CANDLE" for i in report.issues)


def test_modo_historico_ignora_atraso() -> None:
    """BACKTEST sobre dado antigo e o caso normal, nao um defeito."""
    serie = make_series(count=30, end=REFERENCE_INSTANT)
    clock = FrozenClock(REFERENCE_INSTANT + timedelta(days=365))
    report = evaluate(serie, clock=clock, mode=Mode.BACKTEST)
    assert report.status is DataStatus.OK


def test_enforce_levanta_em_serie_bloqueada(frozen_clock: FrozenClock) -> None:
    report = evaluate(make_series(count=0), clock=frozen_clock)
    with pytest.raises(DataQualityBlockedError, match="ANALISE BLOQUEADA"):
        enforce(report)


def test_enforce_devolve_relatorio_valido(frozen_clock: FrozenClock) -> None:
    report = evaluate(make_series(count=30), clock=frozen_clock)
    assert enforce(report) is report


def test_relatorio_registra_procedencia(frozen_clock: FrozenClock) -> None:
    serie = make_series(count=30)
    report = evaluate(serie, clock=frozen_clock, latency_ms=42)
    assert report.source == "fixture"
    assert report.latency_ms == 42
    assert report.checked_at == frozen_clock.now()


def test_timeframe_diario_e_avaliado(frozen_clock: FrozenClock) -> None:
    serie = make_series(count=30, timeframe=Timeframe.D1, end=REFERENCE_INSTANT)
    report = evaluate(serie, clock=frozen_clock, mode=Mode.RESEARCH)
    assert report.status is DataStatus.OK
