"""Provider historico em CSV."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from cashinho.adapters.providers.csv_provider import (
    CsvHistoricalProvider,
    ProviderError,
    SymbolNotAvailableError,
)
from cashinho.core.time.clocks import FrozenClock
from cashinho.domain.enums import Mode, Timeframe
from cashinho.ports.market_data import MarketDataProvider
from tests.conftest import REFERENCE_INSTANT

HEADER = "timestamp,open,high,low,close,volume\n"
BASE = datetime(2026, 8, 20, 13, 0, tzinfo=UTC)


def _write(root: Path, symbol: str, timeframe: Timeframe, body: str) -> Path:
    path = root / symbol / f"{timeframe.value}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def _rows(count: int, *, start: datetime = BASE, step_minutes: int = 5) -> str:
    linhas = []
    for i in range(count):
        moment = start + timedelta(minutes=step_minutes * i)
        price = 10 + i * 0.1
        linhas.append(
            f"{moment.isoformat()},{price:.2f},{price + 0.2:.2f},"
            f"{price - 0.2:.2f},{price + 0.1:.2f},{1000 + i}"
        )
    return "\n".join(linhas) + "\n"


@pytest.fixture
def provider(tmp_path: Path) -> CsvHistoricalProvider:
    _write(tmp_path, "PETR4", Timeframe.M5, _rows(20))
    _write(tmp_path, "PETR4", Timeframe.D1, _rows(5, step_minutes=1440))
    _write(tmp_path, "VALE3", Timeframe.M5, _rows(10))
    return CsvHistoricalProvider(tmp_path, FrozenClock(REFERENCE_INSTANT))


def test_satisfaz_a_porta(provider: CsvHistoricalProvider) -> None:
    assert isinstance(provider, MarketDataProvider)


def test_lista_ativos(provider: CsvHistoricalProvider) -> None:
    assert provider.list_symbols() == ("PETR4", "VALE3")


def test_timeframes_disponiveis_por_ativo(provider: CsvHistoricalProvider) -> None:
    assert provider.get_available_timeframes("PETR4") == (Timeframe.M5, Timeframe.D1)
    assert provider.get_available_timeframes("VALE3") == (Timeframe.M5,)


def test_timeframes_de_ativo_inexistente(provider: CsvHistoricalProvider) -> None:
    assert provider.get_available_timeframes("XXXX9") == ()


def test_ticker_e_normalizado(provider: CsvHistoricalProvider) -> None:
    assert provider.get_available_timeframes("petr4") == (Timeframe.M5, Timeframe.D1)


def test_carrega_candles(provider: CsvHistoricalProvider) -> None:
    serie = provider.get_candles(
        "PETR4", Timeframe.M5, start=BASE, end=BASE + timedelta(hours=3)
    )
    assert len(serie) == 20
    assert serie.symbol == "PETR4"
    assert serie.timeframe is Timeframe.M5
    assert serie.candles[0].open == Decimal("10.00")


def test_procedencia_e_registrada(provider: CsvHistoricalProvider) -> None:
    serie = provider.get_candles(
        "PETR4", Timeframe.M5, start=BASE, end=BASE + timedelta(hours=3)
    )
    assert serie.source == "csv:PETR4/5m.csv"
    assert serie.fetched_at == REFERENCE_INSTANT


def test_intervalo_e_semiaberto(provider: CsvHistoricalProvider) -> None:
    """`[start, end)`: o candle que abre exatamente em `end` fica fora."""
    serie = provider.get_candles(
        "PETR4", Timeframe.M5, start=BASE, end=BASE + timedelta(minutes=10)
    )
    assert len(serie) == 2
    assert serie.candles[0].open_time == BASE
    assert serie.candles[-1].open_time == BASE + timedelta(minutes=5)


def test_nao_entrega_candle_com_fechamento_no_futuro(tmp_path: Path) -> None:
    """CSV pode conter o dia todo, mas a tela so pode ver candle ja fechado."""
    _write(tmp_path, "PETR4", Timeframe.M5, _rows(4))
    provider = CsvHistoricalProvider(tmp_path, FrozenClock(BASE + timedelta(minutes=10)))

    serie = provider.get_candles(
        "PETR4",
        Timeframe.M5,
        start=BASE,
        end=BASE + timedelta(hours=1),
    )

    assert len(serie) == 2
    assert serie.candles[-1].close_time == BASE + timedelta(minutes=10)


def test_periodo_sem_dados_devolve_serie_vazia(provider: CsvHistoricalProvider) -> None:
    """Vazio e retorno valido; classificar isso cabe ao portao."""
    serie = provider.get_candles(
        "PETR4",
        Timeframe.M5,
        start=BASE + timedelta(days=100),
        end=BASE + timedelta(days=101),
    )
    assert serie.is_empty
    assert serie.source == "csv:PETR4/5m.csv"


def test_intervalo_invertido_e_erro(provider: CsvHistoricalProvider) -> None:
    with pytest.raises(ValueError, match="intervalo invalido"):
        provider.get_candles("PETR4", Timeframe.M5, start=BASE, end=BASE)


def test_ativo_inexistente(provider: CsvHistoricalProvider) -> None:
    with pytest.raises(SymbolNotAvailableError, match="sem dados para XXXX9"):
        provider.get_candles(
            "XXXX9", Timeframe.M5, start=BASE, end=BASE + timedelta(hours=1)
        )


def test_timeframe_indisponivel_lista_alternativas(provider: CsvHistoricalProvider) -> None:
    with pytest.raises(SymbolNotAvailableError, match="Timeframes disponiveis"):
        provider.get_candles(
            "VALE3", Timeframe.H1, start=BASE, end=BASE + timedelta(hours=1)
        )


def test_cabecalho_incompleto(tmp_path: Path) -> None:
    path = tmp_path / "PETR4" / "5m.csv"
    path.parent.mkdir(parents=True)
    path.write_text("timestamp,open,close\n2026-08-20T13:00:00+00:00,10,10\n", encoding="utf-8")
    provider = CsvHistoricalProvider(tmp_path, FrozenClock(REFERENCE_INSTANT))
    with pytest.raises(ProviderError, match="cabecalho sem as colunas"):
        provider.get_candles("PETR4", Timeframe.M5, start=BASE, end=BASE + timedelta(hours=1))


def test_volume_negativo_no_csv_e_recusado(tmp_path: Path) -> None:
    _write(tmp_path, "PETR4", Timeframe.M5, f"{BASE.isoformat()},10,11,9,10,-5\n")
    provider = CsvHistoricalProvider(tmp_path, FrozenClock(REFERENCE_INSTANT))
    with pytest.raises(ProviderError, match="volume negativo"):
        provider.get_candles("PETR4", Timeframe.M5, start=BASE, end=BASE + timedelta(hours=1))


def test_ohlc_invalido_no_csv_e_recusado(tmp_path: Path) -> None:
    _write(tmp_path, "PETR4", Timeframe.M5, f"{BASE.isoformat()},10,5,1,9,100\n")
    provider = CsvHistoricalProvider(tmp_path, FrozenClock(REFERENCE_INSTANT))
    with pytest.raises(ProviderError, match="OHLC incoerente"):
        provider.get_candles("PETR4", Timeframe.M5, start=BASE, end=BASE + timedelta(hours=1))


def test_timestamp_sem_fuso_e_recusado(tmp_path: Path) -> None:
    _write(tmp_path, "PETR4", Timeframe.M5, "2026-08-20T13:00:00,10,11,9,10,100\n")
    provider = CsvHistoricalProvider(tmp_path, FrozenClock(REFERENCE_INSTANT))
    with pytest.raises(ProviderError, match="sem fuso horario"):
        provider.get_candles("PETR4", Timeframe.M5, start=BASE, end=BASE + timedelta(hours=1))


def test_timestamp_mal_formado_e_recusado(tmp_path: Path) -> None:
    _write(tmp_path, "PETR4", Timeframe.M5, "ontem,10,11,9,10,100\n")
    provider = CsvHistoricalProvider(tmp_path, FrozenClock(REFERENCE_INSTANT))
    with pytest.raises(ProviderError, match="mal formado"):
        provider.get_candles("PETR4", Timeframe.M5, start=BASE, end=BASE + timedelta(hours=1))


def test_cotacao_ao_vivo_nao_e_suportada(provider: CsvHistoricalProvider) -> None:
    """Devolver o ultimo fechamento seria apresentar preco antigo como atual."""
    with pytest.raises(SymbolNotAvailableError, match="preco antigo"):
        provider.get_quote("PETR4")


def test_capacidades_nao_habilitam_modos_ao_vivo(provider: CsvHistoricalProvider) -> None:
    capabilities = provider.capabilities
    assert not capabilities.supports_realtime
    assert not capabilities.allows_mode(Mode.PAPER)
    assert not capabilities.allows_mode(Mode.LIVE)
    assert capabilities.allows_mode(Mode.BACKTEST)
    assert capabilities.allows_mode(Mode.RESEARCH)


def test_leitura_e_deterministica(provider: CsvHistoricalProvider) -> None:
    kwargs = {"start": BASE, "end": BASE + timedelta(hours=3)}
    primeira = provider.get_candles("PETR4", Timeframe.M5, **kwargs)  # type: ignore[arg-type]
    segunda = provider.get_candles("PETR4", Timeframe.M5, **kwargs)  # type: ignore[arg-type]
    assert primeira.candles == segunda.candles


def test_diretorio_inexistente_nao_quebra(tmp_path: Path) -> None:
    provider = CsvHistoricalProvider(tmp_path / "ausente", FrozenClock(REFERENCE_INSTANT))
    assert provider.list_symbols() == ()
