"""Checks de qualidade de dados.

Estrategia dos testes: as invariantes ja impostas por `Candle` e
`CandleSeries` (OHLC, volume negativo, ordem, duplicata, timezone) sao
verificadas em dois niveis — na fronteira de entrada, com linhas cruas,
e nos checks, montando a serie por caminho que contorne a validacao do
Pydantic. So assim a rede de seguranca fica testada de fato.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cashinho.core.data_quality import checks
from cashinho.core.time.clocks import FrozenClock
from cashinho.domain.enums import Severity, Timeframe
from cashinho.domain.market import Candle, CandleSeries
from tests.conftest import REFERENCE_INSTANT, make_candle, make_series


def _unsafe_series(candles: tuple[Candle, ...], timeframe: Timeframe = Timeframe.M5) -> CandleSeries:
    """Monta a serie sem revalidar.

    Necessario para exercitar os checks contra estados que o construtor
    normalmente recusa — exatamente os estados que uma fonte externa
    futura poderia produzir.
    """
    return CandleSeries.model_construct(
        symbol="PETR4",
        timeframe=timeframe,
        candles=candles,
        source="teste",
        fetched_at=REFERENCE_INSTANT,
    )


# --- dados vazios -----------------------------------------------------


def test_serie_vazia_e_critica() -> None:
    serie = make_series(count=0)
    issues = checks.check_empty(serie)
    assert len(issues) == 1
    assert issues[0].code == "EMPTY"
    assert issues[0].severity is Severity.CRITICAL


def test_serie_com_candles_nao_dispara_vazio() -> None:
    assert checks.check_empty(make_series(count=3)) == []


def test_amostra_insuficiente_e_critica() -> None:
    issues = checks.check_insufficient(make_series(count=5), minimum=20)
    assert issues[0].code == "INSUFFICIENT"
    assert issues[0].severity is Severity.CRITICAL


def test_amostra_suficiente_passa() -> None:
    assert checks.check_insufficient(make_series(count=20), minimum=20) == []


# --- timestamps duplicados -------------------------------------------


def test_timestamps_duplicados_sao_criticos() -> None:
    candle = make_candle(REFERENCE_INSTANT)
    issues = checks.check_duplicates(_unsafe_series((candle, candle)))
    assert issues[0].code == "DUPLICATE"
    assert issues[0].severity is Severity.CRITICAL
    assert REFERENCE_INSTANT.isoformat() in issues[0].evidence


def test_serie_sem_duplicatas() -> None:
    assert checks.check_duplicates(make_series(count=5)) == []


# --- ordem cronologica ------------------------------------------------


def test_ordem_invertida_e_critica() -> None:
    recente = make_candle(REFERENCE_INSTANT)
    antigo = make_candle(REFERENCE_INSTANT - timedelta(minutes=5))
    issues = checks.check_chronological_order(_unsafe_series((recente, antigo)))
    assert issues[0].code == "OUT_OF_ORDER"
    assert issues[0].severity is Severity.CRITICAL


def test_ordem_correta_passa() -> None:
    assert checks.check_chronological_order(make_series(count=5)) == []


# --- OHLC invalido ----------------------------------------------------


def test_ohlc_incoerente_e_critico() -> None:
    quebrado = Candle.model_construct(
        open_time=REFERENCE_INSTANT,
        close_time=REFERENCE_INSTANT + timedelta(minutes=5),
        open=Decimal("10.00"),
        high=Decimal("9.00"),
        low=Decimal("8.00"),
        close=Decimal("9.50"),
        volume=100,
        is_closed=True,
    )
    issues = checks.check_ohlc(_unsafe_series((quebrado,)))
    assert issues[0].code == "INVALID_OHLC"
    assert issues[0].severity is Severity.CRITICAL


def test_ohlc_coerente_passa() -> None:
    assert checks.check_ohlc(make_series(count=5)) == []


# --- volume -----------------------------------------------------------


def test_volume_negativo_e_critico() -> None:
    negativo = make_candle(REFERENCE_INSTANT).model_copy(update={"volume": -50})
    issues = checks.check_volume(_unsafe_series((negativo,)))
    assert issues[0].code == "NEGATIVE_VOLUME"
    assert issues[0].severity is Severity.CRITICAL


def test_volume_zero_apenas_alerta() -> None:
    """Volume zero e suspeito, nao impossivel: nao pode bloquear sozinho."""
    zerado = make_candle(REFERENCE_INSTANT, volume=0)
    issues = checks.check_volume(_unsafe_series((zerado,)))
    assert issues[0].code == "ZERO_VOLUME"
    assert issues[0].severity is Severity.WARNING


def test_volume_normal_passa() -> None:
    assert checks.check_volume(make_series(count=5)) == []


# --- timezone ---------------------------------------------------------


def test_timestamp_naive_e_critico() -> None:
    naive = make_candle(REFERENCE_INSTANT).model_copy(
        update={"open_time": datetime(2026, 8, 20, 14, 0)}
    )
    issues = checks.check_timezone(_unsafe_series((naive,)))
    assert issues[0].code == "NAIVE_TIMESTAMP"
    assert issues[0].severity is Severity.CRITICAL


def test_timestamps_aware_passam() -> None:
    assert checks.check_timezone(make_series(count=5)) == []


# --- candles ausentes -------------------------------------------------


def test_lacuna_intradiaria_gera_alerta() -> None:
    primeiro = make_candle(REFERENCE_INSTANT - timedelta(minutes=30))
    depois = make_candle(REFERENCE_INSTANT)
    issues = checks.check_gaps(_unsafe_series((primeiro, depois)))
    assert issues[0].code == "GAP"
    assert issues[0].severity is Severity.WARNING
    assert "+5" in issues[0].evidence


def test_serie_contigua_nao_tem_lacuna() -> None:
    assert checks.check_gaps(make_series(count=10)) == []


def test_virada_de_pregao_nao_e_lacuna() -> None:
    """Sem isso, todo intervalo noturno viraria alerta e o operador
    aprenderia a ignorar o aviso."""
    ontem = make_candle(datetime(2026, 8, 19, 19, 55, tzinfo=UTC))
    hoje = make_candle(datetime(2026, 8, 20, 13, 0, tzinfo=UTC))
    assert checks.check_gaps(_unsafe_series((ontem, hoje))) == []


def test_timeframe_diario_nao_avalia_lacuna() -> None:
    serie = make_series(count=5, timeframe=Timeframe.D1)
    assert checks.check_gaps(serie, session_bounds=None) == []


# --- dados velhos -----------------------------------------------------


def test_dado_velho_e_critico() -> None:
    serie = make_series(count=5, end=REFERENCE_INSTANT)
    clock = FrozenClock(REFERENCE_INSTANT + timedelta(hours=2))
    issues = checks.check_staleness(serie, now=clock.now())
    assert issues[0].code == "STALE"
    assert issues[0].severity is Severity.CRITICAL


def test_dado_recente_passa() -> None:
    serie = make_series(count=5, end=REFERENCE_INSTANT)
    assert checks.check_staleness(serie, now=REFERENCE_INSTANT) == []


def test_tolerancia_escala_com_o_timeframe() -> None:
    """Um atraso de 10 min e grave em 1m e irrelevante em 60m."""
    depois = REFERENCE_INSTANT + timedelta(minutes=10)
    m1 = make_series(count=3, timeframe=Timeframe.M1, end=REFERENCE_INSTANT)
    h1 = make_series(count=3, timeframe=Timeframe.H1, end=REFERENCE_INSTANT)
    assert checks.check_staleness(m1, now=depois)
    assert checks.check_staleness(h1, now=depois) == []


def test_staleness_usa_ultimo_candle_fechado() -> None:
    fechado = make_candle(REFERENCE_INSTANT - timedelta(minutes=30))
    aberto = make_candle(REFERENCE_INSTANT + timedelta(minutes=30), is_closed=False)
    serie = _unsafe_series((fechado, aberto))

    issues = checks.check_staleness(serie, now=REFERENCE_INSTANT)

    assert issues[0].code == "STALE"


# --- saltos de preco --------------------------------------------------


def test_salto_de_preco_gera_alerta() -> None:
    antes = make_candle(REFERENCE_INSTANT - timedelta(minutes=5), close="40.00")
    depois = make_candle(REFERENCE_INSTANT, close="20.00")
    issues = checks.check_price_jumps(_unsafe_series((antes, depois)))
    assert issues[0].code == "PRICE_JUMP"
    assert issues[0].severity is Severity.WARNING


def test_variacao_normal_nao_alerta() -> None:
    assert checks.check_price_jumps(make_series(count=10)) == []


def test_candle_fechado_no_futuro_e_critico() -> None:
    futuro = make_candle(REFERENCE_INSTANT + timedelta(minutes=5), is_closed=True)
    issues = checks.check_future_closed_candles(
        _unsafe_series((futuro,)),
        now=REFERENCE_INSTANT,
    )
    assert issues[0].code == "FUTURE_CANDLE"
    assert issues[0].severity is Severity.CRITICAL


def test_candle_aberto_vencido_e_critico() -> None:
    vencido = make_candle(
        REFERENCE_INSTANT - timedelta(minutes=10),
        is_closed=False,
    )
    issues = checks.check_open_candle_state(
        _unsafe_series((vencido,)),
        now=REFERENCE_INSTANT,
    )
    assert issues[0].code == "STALE_OPEN_CANDLE"
    assert issues[0].severity is Severity.CRITICAL


def test_candle_aberto_em_formacao_passa() -> None:
    aberto = make_candle(REFERENCE_INSTANT, is_closed=False)
    assert checks.check_open_candle_state(
        _unsafe_series((aberto,)),
        now=REFERENCE_INSTANT + timedelta(minutes=1),
    ) == []


# --- fronteira de entrada ---------------------------------------------


def test_linha_crua_valida_passa() -> None:
    checks.validate_raw_rows(
        [{"timestamp": "x", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "10"}],
        origin="teste.csv",
    )


def test_linha_crua_sem_campo_obrigatorio() -> None:
    with pytest.raises(checks.RawRowError, match="sem os campos"):
        checks.validate_raw_rows([{"timestamp": "x", "open": "1"}], origin="teste.csv")


def test_linha_crua_com_numero_invalido() -> None:
    with pytest.raises(checks.RawRowError, match="numero invalido"):
        checks.validate_raw_rows(
            [{"timestamp": "x", "open": "abc", "high": "2", "low": "1", "close": "1", "volume": "1"}],
            origin="teste.csv",
        )


def test_linha_crua_com_volume_negativo() -> None:
    with pytest.raises(checks.RawRowError, match="volume negativo"):
        checks.validate_raw_rows(
            [{"timestamp": "x", "open": "1", "high": "2", "low": "1", "close": "1", "volume": "-5"}],
            origin="teste.csv",
        )


def test_linha_crua_com_ohlc_incoerente() -> None:
    with pytest.raises(checks.RawRowError, match="OHLC incoerente"):
        checks.validate_raw_rows(
            [{"timestamp": "x", "open": "10", "high": "5", "low": "1", "close": "9", "volume": "1"}],
            origin="teste.csv",
        )


def test_erro_de_linha_crua_identifica_a_posicao() -> None:
    boa = {"timestamp": "x", "open": "1", "high": "2", "low": "1", "close": "1", "volume": "1"}
    ruim = {**boa, "volume": "-1"}
    with pytest.raises(checks.RawRowError, match="linha 2"):
        checks.validate_raw_rows([boa, ruim], origin="teste.csv")


def test_contagem_esperada_de_candles() -> None:
    start = REFERENCE_INSTANT
    end = start + timedelta(hours=1)
    assert checks.expected_candle_count(start, end, Timeframe.M5) == 12
    assert checks.expected_candle_count(end, start, Timeframe.M5) == 0
