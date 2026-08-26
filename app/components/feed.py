"""Blocos de tela para o estado da fonte de dados.

Camada fina: aqui so ha renderizacao. A decisao de qual provider usar mora em
`cashinho.adapters.providers.factory`, e o estado do feed vem do proprio
provider.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from cashinho.adapters.providers.factory import ProviderChoice
from cashinho.domain.enums import FeedStatus
from cashinho.domain.errors import CashinhoError
from cashinho.domain.market import Quote

_STATUS_ICON = {
    FeedStatus.ONLINE: "🟢",
    FeedStatus.NO_ACTIVE_BOOK: "🟡",
    FeedStatus.MARKET_CLOSED: "🔵",
    FeedStatus.STALE: "🟠",
    FeedStatus.OFFLINE: "🔴",
}

_STATUS_HELP = {
    FeedStatus.ONLINE: "Tick recente e livro com os dois lados.",
    FeedStatus.NO_ACTIVE_BOOK: (
        "O terminal devolveu bid e ask zerados. Isso e ausencia de livro, "
        "nao preco zero. O ultimo negocio continua valido, com a idade dele."
    ),
    FeedStatus.MARKET_CLOSED: "Pregao fechado: dado parado e o esperado.",
    FeedStatus.STALE: (
        "O mercado esta aberto e a fonte parou de atualizar. "
        "Nenhuma decisao ao vivo deve se apoiar neste dado."
    ),
    FeedStatus.OFFLINE: "Sem dado. Terminal fechado ou biblioteca ausente.",
}


def local_time(moment: datetime | None, timezone_name: str) -> str:
    """UTC internamente; conversao para o fuso de exibicao acontece aqui."""
    if moment is None:
        return "—"
    return moment.astimezone(ZoneInfo(timezone_name)).strftime("%H:%M:%S.%f")[:-3]


def render_source_banner(choice: ProviderChoice) -> None:
    """Diz de onde vem o dado, sempre - o usuario nunca adivinha a origem."""
    if choice.is_metatrader:
        st.info(
            "Fonte ativa: **MetaTrader 5** da corretora, em tempo real e "
            "**somente leitura**. Nenhuma ordem e enviada por esta aplicacao.",
            icon="📡",
        )
        return
    st.warning(
        "Fonte ativa: **arquivos CSV locais**. As séries de desenvolvimento são "
        "**sintéticas** e não correspondem a preços reais negociados na B3.",
        icon="⚠️",
    )


def render_feed_status(choice: ProviderChoice, symbol: str, timezone_name: str) -> None:
    """Estado do feed em tempo real, com terminal, servidor e a trava."""
    provider = choice.provider
    if not choice.is_metatrader:
        st.error(
            "Fonte historica: nenhuma cotacao em tempo real disponivel. "
            "ANALISE AO VIVO BLOQUEADA.",
            icon="⛔",
        )
        return

    if not provider.available:  # type: ignore[attr-defined]
        st.error(
            "**METATRADER NAO DISPONIVEL** — a biblioteca `MetaTrader5` nao esta "
            "instalada. Na maquina do terminal: `pip install 'cashinho[metatrader]'`.",
            icon="⛔",
        )
        return

    info = provider.terminal_info()  # type: ignore[attr-defined]
    if not info.connected:
        st.error(
            f"**TERMINAL OFFLINE** — {info.reason or 'o MetaTrader nao respondeu'}. "
            "Abra o terminal da corretora e autentique manualmente.",
            icon="⛔",
        )
        st.caption(
            "Nenhum dado historico substitui o feed ao vivo: novas oportunidades "
            "permanecem bloqueadas."
        )
        return

    col1, col2, col3 = st.columns(3)
    col1.metric(
        "Terminal",
        "ONLINE",
        help="Indica que o MetaTrader respondeu e está disponível para leitura de dados.",
    )
    col2.metric(
        "Servidor",
        info.server or "—",
        help="Servidor da corretora conectado no terminal MetaTrader.",
    )
    col3.metric(
        "Trading real",
        "BLOQUEADO",
        help="Esta fonte é somente leitura. O Cashinho não envia ordens reais ao MT5.",
    )

    try:
        status = provider.feed_status(symbol)  # type: ignore[attr-defined]
        quote = provider.get_quote(symbol)
    except CashinhoError as exc:
        st.error(f"Sem cotacao para {symbol}: {exc}", icon="⛔")
        return

    st.markdown(f"{_STATUS_ICON[status]} **{symbol} · {status.value}**")
    st.caption(_STATUS_HELP[status])
    render_quote(quote, timezone_name)


def render_quote(quote: Quote, timezone_name: str) -> None:
    """Bid, ask, spread e ultimo negocio - com os dois relogios separados."""
    col1, col2, col3, col4 = st.columns(4)
    if quote.has_active_book:
        col1.metric(
            "Bid",
            f"{quote.bid}",
            help="Maior preço que compradores estão ofertando agora.",
        )
        col2.metric(
            "Ask",
            f"{quote.ask}",
            help="Menor preço que vendedores estão pedindo agora.",
        )
        col3.metric(
            "Spread",
            f"{quote.spread}",
            help="Diferença entre ask e bid. Spreads maiores encarecem a operação.",
        )
    else:
        col1.metric(
            "Bid",
            "—",
            help="Sem preço comprador ativo no livro da fonte.",
        )
        col2.metric(
            "Ask",
            "—",
            help="Sem preço vendedor ativo no livro da fonte.",
        )
        col3.metric("Spread", "—", help="Sem livro ativo: bid e ask zerados na fonte.")
    col4.metric(
        "Ultimo negocio",
        f"{quote.price}",
        help="Preço do último negócio informado pela fonte, que pode ser mais antigo que bid/ask.",
    )

    st.caption(
        f"Cotacao em {local_time(quote.bid_ask_time, timezone_name)} · "
        f"negocio em {local_time(quote.trade_time, timezone_name)} · "
        f"volume {quote.trade_volume if quote.trade_volume is not None else '—'} · "
        f"latencia {quote.latency_ms} ms · fonte `{quote.source}`"
    )
