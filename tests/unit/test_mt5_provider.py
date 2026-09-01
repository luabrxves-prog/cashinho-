"""O provider MetaTrader: cotacao, candles, simbolos e estado do feed."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from cashinho.adapters.providers.metatrader import (
    AmbiguousSymbolError,
    MetaTraderMarketDataProvider,
    MetaTraderProviderError,
    MetaTraderTerminal,
    SymbolNotFoundError,
    resolve_symbol,
)
from cashinho.core.time.clocks import FrozenClock
from cashinho.domain.enums import FeedStatus, Mode, Timeframe
from tests.unit.fake_mt5 import (
    GENIAL_SYMBOLS,
    NOW,
    FakeMetaTrader5,
    quote_tick,
    rate,
    server_epoch,
    trade_tick,
)

ADAPTER_DIR = Path("src/cashinho/adapters/providers/metatrader")


def build(
    library: FakeMetaTrader5 | None = None,
    *,
    now: datetime = NOW,
    connect: bool = True,
    **kwargs: object,
) -> MetaTraderMarketDataProvider:
    terminal = MetaTraderTerminal(library=library or FakeMetaTrader5())
    provider = MetaTraderMarketDataProvider(
        FrozenClock(now), terminal=terminal, **kwargs  # type: ignore[arg-type]
    )
    if connect:
        provider.connect()
    return provider


# ---------------------------------------------------------------------------
# capacidades e modo
# ---------------------------------------------------------------------------


def test_declara_tempo_real_e_habilita_paper() -> None:
    """Primeira fonte do projeto capaz de sustentar PAPER por D9."""
    capabilities = build().capabilities

    assert capabilities.supports_realtime is True
    assert capabilities.supports_quotes is True
    assert capabilities.allows_mode(Mode.PAPER) is True
    assert capabilities.min_timeframe is Timeframe.M1


def test_a_porta_nao_tem_nenhum_metodo_de_ordem() -> None:
    """Somente leitura e estrutural: a interface nao oferece envio."""
    proibidos = {"order_send", "place_order", "buy", "sell", "cancel_order",
                 "modify_order", "close_position"}

    assert not proibidos & set(dir(MetaTraderMarketDataProvider))


def test_nenhum_arquivo_do_adapter_chama_funcao_de_ordem() -> None:
    """Vale o codigo, nao a prosa: a docstring cita os nomes para nega-los."""
    enviam_ordem = {"order_send", "order_check", "place_order"}

    for path in ADAPTER_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not used & enviam_ordem, path.name


# ---------------------------------------------------------------------------
# terminal
# ---------------------------------------------------------------------------


def test_terminal_indisponivel_vira_estado_descrito() -> None:
    """Em Linux e na CI o import falha - e isso nao pode ser excecao solta."""
    class SemBiblioteca(MetaTraderTerminal):
        @property
        def library(self) -> object:
            from cashinho.adapters.providers.metatrader import MetaTraderUnavailableError

            raise MetaTraderUnavailableError("METATRADER NAO DISPONIVEL: nao instalada")

    info = SemBiblioteca().connect()

    assert info.connected is False
    assert "METATRADER NAO DISPONIVEL" in info.reason


def test_initialize_que_falha_traz_o_erro_do_terminal() -> None:
    library = FakeMetaTrader5(initialize_ok=False, error=(-6, "Terminal: no IPC"))

    info = build(library, connect=False).connect()

    assert info.connected is False
    assert "no IPC" in info.reason


def test_terminal_desconectado_barra_a_leitura() -> None:
    provider = build(FakeMetaTrader5(connected=False))

    with pytest.raises(MetaTraderProviderError, match="TERMINAL OFFLINE"):
        provider.get_quote("PETR4")


def test_o_terminal_nao_expoe_dado_da_conta() -> None:
    """account_info traz login e saldo; nada disso pode circular."""
    info = build().terminal_info()

    assert info.server == "GenialInvestimentos-PRD"
    assert "123456" not in str(info.as_dict())
    assert "98765" not in str(info.as_dict())


# ---------------------------------------------------------------------------
# simbolos
# ---------------------------------------------------------------------------


def test_petr4_resolve_por_correspondencia_exata() -> None:
    resolution = resolve_symbol("PETR4", GENIAL_SYMBOLS)

    assert resolution.resolved == "PETR4"
    assert resolution.exact is True


def test_prefixo_ambiguo_e_erro_e_nao_escolha() -> None:
    """Escolher entre PETR4F/PETR4T seria analisar outro instrumento."""
    with pytest.raises(AmbiguousSymbolError, match="SYMBOL_AMBIGUOUS"):
        resolve_symbol("PETR", GENIAL_SYMBOLS)


def test_simbolo_inexistente_e_erro_nomeado() -> None:
    with pytest.raises(SymbolNotFoundError, match="SYMBOL_NOT_FOUND"):
        resolve_symbol("XPTO9", GENIAL_SYMBOLS)


def test_resolucao_aproximada_so_com_um_candidato_e_sob_pedido() -> None:
    assert resolve_symbol("VALE", GENIAL_SYMBOLS, allow_prefix=True).resolved == "VALE3"

    with pytest.raises(AmbiguousSymbolError):
        resolve_symbol("PETR", GENIAL_SYMBOLS, allow_prefix=True)


def test_o_simbolo_resolvido_entra_na_observacao_do_mercado() -> None:
    library = FakeMetaTrader5()
    build(library).resolve("PETR4")

    assert "PETR4" in library.selected


# ---------------------------------------------------------------------------
# cotacao: duas fontes separadas
# ---------------------------------------------------------------------------


def test_bid_e_ask_vem_dos_ticks_de_cotacao() -> None:
    quote = build().get_quote("PETR4")

    assert quote.bid == Decimal("42.06")
    assert quote.ask == Decimal("42.07")


def test_last_e_volume_vem_dos_ticks_de_negocio() -> None:
    quote = build().get_quote("PETR4")

    assert quote.price == Decimal("42.07")
    assert quote.trade_volume == 400


def test_os_dois_relogios_ficam_separados() -> None:
    """Cotacao as .596 e negocio as .601: um campo so esconderia qual envelheceu."""
    quote = build().get_quote("PETR4")

    assert quote.bid_ask_time is not None
    assert quote.trade_time is not None
    assert quote.bid_ask_time != quote.trade_time


def test_o_provider_nao_usa_symbol_info_tick() -> None:
    """Ele voltou com bid=0 e ask=0 existindo book valido."""
    for path in ADAPTER_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert "symbol_info_tick" not in used, path.name


def test_o_horario_da_cotacao_e_utc() -> None:
    quote = build().get_quote("PETR4")

    assert quote.timestamp.tzinfo is not None
    assert quote.timestamp.utcoffset() == timedelta(0)


# ---------------------------------------------------------------------------
# bid/ask zerados
# ---------------------------------------------------------------------------


def test_bid_e_ask_zerados_viram_ausencia_de_livro() -> None:
    library = FakeMetaTrader5(quote_ticks=[quote_tick(bid=0.0, ask=0.0)])

    quote = build(library).get_quote("PETR4")

    assert quote.bid is None
    assert quote.ask is None
    assert quote.spread is None
    assert quote.has_active_book is False


def test_livro_zerado_nao_apaga_o_ultimo_negocio() -> None:
    library = FakeMetaTrader5(quote_ticks=[quote_tick(bid=0.0, ask=0.0)])

    quote = build(library).get_quote("PETR4")

    assert quote.price == Decimal("42.07")
    assert quote.trade_time is not None


def test_o_last_nunca_substitui_o_bid() -> None:
    """Preencher o livro com o ultimo negocio seria inventar cotacao."""
    library = FakeMetaTrader5(quote_ticks=[quote_tick(bid=0.0, ask=0.0)])

    quote = build(library).get_quote("PETR4")

    assert quote.bid is None
    assert quote.price is not None


def test_livro_zerado_vira_no_active_book() -> None:
    library = FakeMetaTrader5(quote_ticks=[quote_tick(bid=0.0, ask=0.0)])

    assert build(library).feed_status("PETR4") is FeedStatus.NO_ACTIVE_BOOK


def test_um_lado_so_nao_forma_livro() -> None:
    library = FakeMetaTrader5(quote_ticks=[quote_tick(bid=42.06, ask=0.0)])

    assert build(library).get_quote("PETR4").has_active_book is False


# ---------------------------------------------------------------------------
# estado do feed
# ---------------------------------------------------------------------------


def test_tick_recente_com_livro_e_online() -> None:
    assert build().feed_status("PETR4") is FeedStatus.ONLINE


def test_dado_parado_dentro_do_pregao_e_stale() -> None:
    old = NOW - timedelta(minutes=20)
    library = FakeMetaTrader5(
        quote_ticks=[quote_tick(moment=old)], trade_ticks=[trade_tick(moment=old)]
    )

    assert build(library).feed_status("PETR4") is FeedStatus.STALE


def test_dado_parado_fora_do_pregao_e_mercado_fechado() -> None:
    """As 20h o ultimo tick e das 17h55 e isso esta certo, nao quebrado."""
    night = datetime(2026, 8, 20, 23, 30, tzinfo=UTC)   # 20h30 em Sao Paulo
    old = datetime(2026, 8, 20, 19, 55, tzinfo=UTC)     # 16h55 em Sao Paulo
    library = FakeMetaTrader5(
        quote_ticks=[quote_tick(moment=old)], trade_ticks=[trade_tick(moment=old)]
    )

    status = build(library, now=night).feed_status("PETR4")

    assert status is FeedStatus.MARKET_CLOSED
    assert status.market_is_idle is True


def test_terminal_conectado_sem_tick_no_pregao_e_stale_e_nao_offline() -> None:
    """Terminal respondeu e nao ha tick: a FONTE parou, o terminal nao caiu."""
    library = FakeMetaTrader5(quote_ticks=[], trade_ticks=[])

    assert build(library).feed_status("PETR4") is FeedStatus.STALE


def test_terminal_desconectado_e_offline() -> None:
    """OFFLINE fica reservado para o terminal fora do ar."""
    library = FakeMetaTrader5(connected=False)

    assert build(library).feed_status("PETR4") is FeedStatus.OFFLINE


def test_sem_tick_fora_do_pregao_e_mercado_fechado() -> None:
    """Silencio as 20h e o esperado, nao defeito."""
    night = datetime(2026, 8, 20, 23, 30, tzinfo=UTC)
    library = FakeMetaTrader5(quote_ticks=[], trade_ticks=[])

    assert build(library, now=night).feed_status("PETR4") is FeedStatus.MARKET_CLOSED


def test_o_limite_de_stale_e_configuravel() -> None:
    old = NOW - timedelta(seconds=90)
    library = FakeMetaTrader5(
        quote_ticks=[quote_tick(moment=old)], trade_ticks=[trade_tick(moment=old)]
    )

    assert build(library, stale_seconds=300).feed_status("PETR4") is FeedStatus.ONLINE
    assert build(library, stale_seconds=30).feed_status("PETR4") is FeedStatus.STALE


# ---------------------------------------------------------------------------
# candles
# ---------------------------------------------------------------------------


def janela(minutes: int = 240) -> dict[str, datetime]:
    return {"start": NOW - timedelta(minutes=minutes), "end": NOW + timedelta(minutes=1)}


def test_traz_candles_reais_com_procedencia() -> None:
    series = build().get_candles("PETR4", Timeframe.M1, **janela())

    assert len(series) == 3
    assert series.source.startswith("metatrader:")
    assert series.symbol == "PETR4"


def test_o_volume_real_e_preferido_ao_tick_volume() -> None:
    series = build().get_candles("PETR4", Timeframe.M1, **janela())

    assert all(candle.volume == 340_000 for candle in series.candles)


def test_o_preco_chega_como_decimal() -> None:
    series = build().get_candles("PETR4", Timeframe.M1, **janela())

    assert isinstance(series.candles[0].close, Decimal)


def test_o_candle_em_formacao_vem_marcado_e_nao_descartado() -> None:
    """O dominio ja modela `is_closed`; descartar aqui esconderia o candle vivo."""
    library = FakeMetaTrader5(rates=[rate(3), rate(2), rate(0)])

    series = build(library).get_candles("PETR4", Timeframe.M1, **janela())

    assert series.has_open_candle is True
    assert len(series.closed_only()) == len(series) - 1


def test_virada_de_candle_nao_marca_o_anterior_como_aberto() -> None:
    """Se o servidor ja mostra o candle novo, o anterior foi fechado."""
    turn = datetime(2026, 8, 20, 17, 33, tzinfo=UTC)
    local_before_turn = turn - timedelta(milliseconds=100)

    previous = rate(0)
    previous["time"] = int(server_epoch(turn - timedelta(minutes=1)))
    current = rate(0)
    current["time"] = int(server_epoch(turn))
    library = FakeMetaTrader5(rates=[previous, current])

    series = build(library, now=local_before_turn).get_candles(
        "PETR4",
        Timeframe.M1,
        start=turn - timedelta(minutes=5),
        end=turn + timedelta(minutes=1),
    )

    assert [candle.is_closed for candle in series.candles] == [True, False]
    assert series.has_open_candle is True


def test_candles_ja_fechados_nao_sao_cortados() -> None:
    """`[:-1]` cego jogaria fora um candle fechado logo apos a virada."""
    library = FakeMetaTrader5(rates=[rate(3), rate(2), rate(1)])

    series = build(library).get_candles("PETR4", Timeframe.M1, **janela())

    assert series.has_open_candle is False
    assert len(series) == 3


def test_o_corte_respeita_a_duracao_do_timeframe() -> None:
    """Um candle de 5m aberto ha 3 minutos ainda esta em formacao."""
    library = FakeMetaTrader5(rates=[rate(10), rate(3)])

    series = build(library).get_candles("PETR4", Timeframe.M5, **janela())

    assert series.has_open_candle is True


def test_candle_futuro_filtrado_nao_fecha_candle_em_formacao() -> None:
    """Linha futura fora da janela nao pode adiantar o relogio do provider."""
    current = rate(0)
    current["time"] = int(server_epoch(NOW - timedelta(minutes=1)))
    future = rate(0)
    future["time"] = int(server_epoch(NOW + timedelta(minutes=1)))
    library = FakeMetaTrader5(rates=[current, future])

    series = build(library).get_candles(
        "PETR4",
        Timeframe.M2,
        start=NOW - timedelta(minutes=5),
        end=NOW,
    )

    assert len(series) == 1
    assert series.has_open_candle is True


@pytest.mark.parametrize("timeframe", list(Timeframe))
def test_todos_os_timeframes_do_dominio_sao_mapeados(timeframe: Timeframe) -> None:
    """Candles espacados pela duracao do proprio timeframe, todos fechados."""
    passo = int(timeframe.duration.total_seconds() // 60)
    library = FakeMetaTrader5(rates=[rate(passo * n) for n in (3, 2, 1)])

    series = build(library).get_candles(
        "PETR4", timeframe, **janela(minutes=passo * 5)
    )

    assert series.timeframe is timeframe
    assert len(series) == 3
    assert series.has_open_candle is False


def test_intervalo_invertido_e_recusado() -> None:
    with pytest.raises(ValueError, match="intervalo invalido"):
        build().get_candles(
            "PETR4", Timeframe.M1, start=NOW, end=NOW - timedelta(hours=1)
        )


def test_linha_incoerente_e_descartada_sem_derrubar_a_serie() -> None:
    ruim = rate(5)
    ruim["high"] = 1.0      # maxima abaixo da minima
    library = FakeMetaTrader5(rates=[ruim, rate(3), rate(2)])

    series = build(library).get_candles("PETR4", Timeframe.M1, **janela())

    assert len(series) == 2


# ---------------------------------------------------------------------------
# regressao: os dois defeitos encontrados na revisao
# ---------------------------------------------------------------------------


def test_usa_intervalo_ate_agora_e_nao_os_primeiros_n_ticks() -> None:
    """`copy_ticks_from` devolve os PRIMEIROS N a partir de `since`.

    Com mercado movimentado, N enche com o comeco da janela e o preco recente
    fica de fora - o adapter entregaria cotacao velha como atual. Aqui a
    janela tem 600 eventos: os 500 primeiros trazem 42.00, e so o ultimo
    traz 42.50.
    """
    antigos = [
        quote_tick(bid=42.00, ask=42.01, moment=NOW - timedelta(minutes=25, seconds=s))
        for s in range(600, 0, -1)
    ]
    recente = quote_tick(bid=42.50, ask=42.51, moment=NOW - timedelta(seconds=2))
    library = FakeMetaTrader5(quote_ticks=[*antigos, recente])

    quote = build(library).get_quote("PETR4")

    assert quote.bid == Decimal("42.50")
    assert "copy_ticks_range" in " ".join(library.calls)
    assert "copy_ticks_from" not in " ".join(library.calls)


def test_o_livro_atual_nao_retrocede_para_um_book_antigo() -> None:
    """Se o evento mais recente tem bid/ask zerados, o livro nao esta ativo.

    Procurar para tras um tick com precos validos devolveria um livro que ja
    nao existe, com cara de cotacao atual.
    """
    valido = quote_tick(bid=42.06, ask=42.07, moment=NOW - timedelta(minutes=3))
    zerado = quote_tick(bid=0.0, ask=0.0, moment=NOW - timedelta(seconds=2))
    library = FakeMetaTrader5(quote_ticks=[valido, zerado])

    provider = build(library)
    quote = provider.get_quote("PETR4")

    assert quote.bid is None
    assert quote.ask is None
    assert quote.has_active_book is False
    assert provider.feed_status("PETR4") is FeedStatus.NO_ACTIVE_BOOK


def test_um_lado_zerado_no_evento_atual_ja_invalida_o_livro() -> None:
    """Meio book nao e cotacao."""
    valido = quote_tick(bid=42.06, ask=42.07, moment=NOW - timedelta(minutes=3))
    meio = quote_tick(bid=42.06, ask=0.0, moment=NOW - timedelta(seconds=2))
    library = FakeMetaTrader5(quote_ticks=[valido, meio])

    assert build(library).get_quote("PETR4").has_active_book is False


def test_livro_inativo_ainda_prova_que_o_feed_esta_vivo() -> None:
    """NO_ACTIVE_BOOK nao pode virar OFFLINE: o terminal esta respondendo."""
    library = FakeMetaTrader5(quote_ticks=[quote_tick(bid=0.0, ask=0.0)])

    status = build(library).feed_status("PETR4")

    assert status is FeedStatus.NO_ACTIVE_BOOK
    assert status.has_data is True


def test_o_ultimo_negocio_continua_valendo_apesar_do_livro_zerado() -> None:
    """Negocio e evento, nao estado: ele nao expira porque o book fechou."""
    library = FakeMetaTrader5(
        quote_ticks=[quote_tick(bid=0.0, ask=0.0)],
        trade_ticks=[trade_tick(last=42.07, volume=400)],
    )

    quote = build(library).get_quote("PETR4")

    assert quote.price == Decimal("42.07")
    assert quote.trade_volume == 400
    assert quote.bid is None
