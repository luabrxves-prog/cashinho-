"""Analise do ativo — monitoramento, sinal e boleta PAPER.

Fluxo:
entrada do usuario
-> provider
-> portao de qualidade
-> indicadores
-> sinal de entrada
-> boleta PAPER
-> grafico

Nenhuma ordem real e enviada ao mercado.
"""

from __future__ import annotations

import time as time_module
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import streamlit as st

from app.components.charts import candlestick_figure
from app.components.chrome import page_header, sidebar
from app.components.decision_card import render_decision_card
from app.components.feed import render_feed_status, render_source_banner
from app.components.paper_orders import render_paper_orders
from app.components.position_card import render_position_card
from app.components.quality import quality_panel
from app.runtime import build_paper_broker
from cashinho.adapters.providers.csv_provider import ProviderError
from cashinho.adapters.providers.factory import build_market_data_provider
from cashinho.config.settings import get_settings
from cashinho.core.time.clocks import SystemClock
from cashinho.domain.enums import DataStatus, Mode, Timeframe
from cashinho.domain.errors import CashinhoError
from cashinho.domain.risk import RiskProfile
from cashinho.pipeline.entry_signal import evaluate_entry_signal
from cashinho.pipeline.final_decision import make_final_decision
from cashinho.pipeline.indicators import IndicatorSelection, compute_panel
from cashinho.pipeline.journal_audit import decision_idempotency_key
from cashinho.pipeline.market_data import load_market_data
from cashinho.pipeline.multi_timeframe import advise_timeframe, analyze_timeframes
from cashinho.pipeline.opportunities import build_opportunity
from cashinho.pipeline.paper_broker import PaperOrderType
from cashinho.pipeline.paper_market import collect_paper_market
from cashinho.pipeline.paper_ticket import (
    build_paper_ticket,
    calculate_ticket_sizing,
)
from cashinho.pipeline.position_manager import (
    PositionRiskState,
    apply_position_decision,
)
from cashinho.pipeline.position_monitoring import evaluate_open_position

INSPECTION_MODE = Mode.RESEARCH

_TIMEFRAME_LABELS = {
    Timeframe.M1: "1m · muito curto, usado para gatilhos",
    Timeframe.M5: "5m · curto, padrão da tela de análise",
    Timeframe.M15: "15m · leitura operacional mais estável",
    Timeframe.M30: "30m · contexto intradiário",
    Timeframe.H1: "60m · contexto de tendência",
    Timeframe.D1: "1D · visão diária",
}


# ============================================================
# CONFIGURACAO
# ============================================================

settings = get_settings()
paper_broker, journal_audit = build_paper_broker()

sidebar(settings)

page_header(
    "Análise",
    "Monitoramento, oportunidades e execução simulada",
)

FIXTURES = settings.data_dir / "fixtures"

clock = SystemClock()

choice = build_market_data_provider(
    settings,
    clock,
    fixtures_root=FIXTURES,
)

provider = choice.provider
display_timezone = ZoneInfo(settings.display_timezone)


@st.cache_data(ttl=5, show_spinner=False)
def cached_market_data(
    _provider: object,
    _clock: object,
    *,
    symbol_value: str,
    timeframe_value: str,
    start_value: datetime,
    end_value: datetime,
):
    """Cache curto para conter reruns do Streamlit sem congelar o feed."""
    return load_market_data(
        _provider,
        symbol=symbol_value,
        timeframe=Timeframe(timeframe_value),
        start=start_value,
        end=end_value,
        clock=_clock,
        mode=INSPECTION_MODE,
    )


@st.cache_data(ttl=60, show_spinner=False)
def cached_available_period(
    _provider: object,
    *,
    symbol_value: str,
    timeframe_value: str,
    display_timezone: str,
) -> tuple[date, date] | None:
    """Periodo existente em fontes historicas locais, quando o provider informa."""
    available_range = getattr(_provider, "available_range", None)
    if available_range is None:
        return None
    try:
        first, last = available_range(symbol_value, Timeframe(timeframe_value))
    except (CashinhoError, RuntimeError, ValueError):
        return None
    timezone = ZoneInfo(display_timezone)
    return first.astimezone(timezone).date(), last.astimezone(timezone).date()


def _timeframe_label(timeframe: Timeframe) -> str:
    return _TIMEFRAME_LABELS.get(timeframe, timeframe.value)


# ============================================================
# SESSION STATE
# ============================================================

if "monitorando" not in st.session_state:
    st.session_state.monitorando = False

if "capital_operacional" not in st.session_state:
    st.session_state.capital_operacional = float(settings.capital)

profile_base = settings.risk_profile()

if "risco_por_operacao_pct" not in st.session_state:
    st.session_state.risco_por_operacao_pct = float(profile_base.risk_per_trade_pct)

if "exposicao_por_ativo_pct" not in st.session_state:
    st.session_state.exposicao_por_ativo_pct = float(profile_base.max_exposure_per_symbol_pct)


# ============================================================
# ATIVOS DISPONIVEIS
# ============================================================

symbols = choice.offered_symbols()

if not symbols:
    st.error(
        "Nenhum dado disponível. Gere as séries de desenvolvimento com:\n\n"
        "```\npython scripts/generate_fixtures.py\n```",
        icon="⛔",
    )

    st.stop()


render_source_banner(choice)


if settings.mode.requires_realtime_data and not choice.realtime:
    st.info(
        f"Modo operacional: **{settings.mode.value}**. "
        f"Esta tela executa **inspeção histórica** "
        f"(`{INSPECTION_MODE.value}`), pois a fonte atual "
        "não fornece dados em tempo real.",
        icon="🔎",
    )


# ============================================================
# ATIVO / TIMEFRAME / PERIODO
# ============================================================

col1, col2, col3, col4 = st.columns([1.1, 1, 1, 1])
default_symbol = "PETR4" if "PETR4" in symbols else symbols[0]

with col1:
    symbol = st.selectbox(
        "Ativo",
        options=symbols,
        index=symbols.index(default_symbol),
        help=(
            "Papel que será analisado. No modo MT5, o gráfico usa os candles "
            "recebidos do terminal. No modo CSV, usa dados sintéticos de desenvolvimento."
        ),
    )


try:
    available = provider.get_available_timeframes(symbol)

except CashinhoError as exc:
    st.error(
        f"Sem timeframes disponíveis para {symbol}: {exc}",
        icon="⛔",
    )

    st.stop()


default_timeframe = next((tf for tf in available if tf.value == "5m"), available[0])

with col2:
    timeframe = st.selectbox(
        "Timeframe",
        options=available,
        index=available.index(default_timeframe),
        format_func=lambda item: item.value,
        help=(
            "Tamanho de cada candle do gráfico. Timeframes menores reagem mais rápido, "
            "mas oscilam mais; timeframes maiores mostram melhor o contexto."
        ),
    )
    st.caption(_timeframe_label(timeframe))


hoje = clock.now().astimezone(display_timezone).date()
available_period = cached_available_period(
    provider,
    symbol_value=symbol,
    timeframe_value=timeframe.value,
    display_timezone=settings.display_timezone,
)
period_start = available_period[0] if available_period else hoje - timedelta(days=30)
period_end = available_period[1] if available_period else hoje
default_start = max(period_start, period_end - timedelta(days=30))

with col3:
    start_date = st.date_input(
        "Início",
        value=default_start,
        min_value=period_start if available_period else None,
        max_value=period_end if available_period else None,
        format="DD/MM/YYYY",
        help=(
            "Primeiro dia usado para buscar candles. Se o período começar antes dos "
            "dados disponíveis, o gráfico só mostra o que existe na fonte."
        ),
    )

with col4:
    end_date = st.date_input(
        "Fim",
        value=period_end,
        min_value=period_start if available_period else None,
        max_value=period_end if available_period else None,
        format="DD/MM/YYYY",
        help=(
            "Último dia do filtro. Em MT5, use hoje para acompanhar o terminal; em CSV, "
            "o limite é a última data gerada nos arquivos locais."
        ),
    )

if available_period is not None:
    st.caption(
        "Período disponível nesta fonte: "
        f"**{period_start.strftime('%d/%m/%Y')}** a "
        f"**{period_end.strftime('%d/%m/%Y')}**. "
        "Se a fonte for CSV, esses candles são sintéticos e não atualizam com o mercado."
    )


if start_date > end_date:
    st.error(
        "A data inicial não pode ser posterior à data final.",
        icon="⛔",
    )

    st.stop()


# ============================================================
# FEED MT5
# ============================================================

if choice.is_metatrader:
    with st.expander(
        "📡 Feed MetaTrader 5",
        expanded=False,
    ):
        render_feed_status(
            choice,
            symbol,
            settings.display_timezone,
        )


# ============================================================
# CONFIGURACAO DA ESTRATEGIA
# ============================================================

with st.expander(
    "⚙️ Configuração da estratégia",
    expanded=False,
):
    st.caption(
        "Os indicadores participam do cálculo do sinal. "
        "A estratégia combina múltiplas condições antes de "
        "indicar COMPRA, VENDA ou NÃO OPERAR."
    )

    ind1, ind2, ind3 = st.columns(3)

    # --------------------------------------------------------
    # MEDIAS
    # --------------------------------------------------------

    with ind1:
        st.markdown("**Sobre o preço**")

        usar_sma = st.checkbox(
            "SMA",
            value=True,
            help=(
                "Média móvel simples. Ajuda a enxergar a direção média do preço. "
                "Quanto maior o período, mais lenta e suave ela fica."
            ),
        )

        sma_periods = st.multiselect(
            "Períodos SMA",
            [9, 20, 50, 200],
            default=[20],
            disabled=not usar_sma,
            help=(
                "Quantidade de candles usada em cada SMA. Exemplo: SMA 20 em gráfico "
                "de 5m olha os últimos 20 candles de 5 minutos."
            ),
        )

        usar_ema = st.checkbox(
            "EMA",
            value=True,
            help=(
                "Média móvel exponencial. Parecida com a SMA, mas dá mais peso aos "
                "candles recentes e reage mais rápido."
            ),
        )

        ema_periods = st.multiselect(
            "Períodos EMA",
            [9, 12, 21, 26, 50],
            default=[9, 21],
            disabled=not usar_ema,
            help=(
                "Períodos das EMAs no gráfico e no cálculo do sinal. EMAs curtas "
                "reagem rápido; EMAs longas ajudam a filtrar ruído."
            ),
        )

    # --------------------------------------------------------
    # REFERENCIAS
    # --------------------------------------------------------

    with ind2:
        st.markdown("**Referências**")

        usar_vwap = st.checkbox(
            "VWAP",
            value=True,
            disabled=not timeframe.is_intraday,
            help=(
                "Preço médio ponderado pelo volume do dia. Serve como referência "
                "intradiária; por isso fica desativado em gráfico diário."
            ),
        )

        if not timeframe.is_intraday:
            st.caption("VWAP é intradiário.")

        usar_bb = st.checkbox(
            "Bandas de Bollinger",
            value=False,
            help=(
                "Bandas ao redor da média que mostram expansão ou contração da "
                "volatilidade. Não são compra/venda sozinhas."
            ),
        )

        bb_period = st.number_input(
            "Período BB",
            min_value=2,
            max_value=200,
            value=20,
            disabled=not usar_bb,
            help="Quantidade de candles usada para calcular a média das Bandas de Bollinger.",
        )

        bb_dev = st.number_input(
            "Desvios BB",
            min_value=0.5,
            max_value=5.0,
            value=2.0,
            step=0.5,
            disabled=not usar_bb,
            help=(
                "Distância das bandas em relação à média. Valores maiores deixam "
                "as bandas mais largas."
            ),
        )

    # --------------------------------------------------------
    # OSCILADORES
    # --------------------------------------------------------

    with ind3:
        st.markdown("**Osciladores**")

        usar_rsi = st.checkbox(
            "RSI",
            value=True,
            help=(
                "Oscilador de força relativa. Ajuda a ver se o movimento recente "
                "está forte ou esticado demais."
            ),
        )

        rsi_period = st.number_input(
            "Período RSI",
            min_value=2,
            max_value=100,
            value=14,
            disabled=not usar_rsi,
            help="Quantidade de candles usada para calcular o RSI. O padrão comum é 14.",
        )

        usar_macd = st.checkbox(
            "MACD (12, 26, 9)",
            value=True,
            help=(
                "Compara médias rápidas e lentas para mostrar mudança de ritmo. "
                "Os números são os períodos padrão do MACD."
            ),
        )

        usar_atr = st.checkbox(
            "ATR",
            value=True,
            help=(
                "Mede a volatilidade média. O sistema usa isso para entender o "
                "tamanho normal do movimento, não para prever direção."
            ),
        )

        atr_period = st.number_input(
            "Período ATR",
            min_value=2,
            max_value=100,
            value=14,
            disabled=not usar_atr,
            help="Quantidade de candles usada para calcular a volatilidade média do ATR.",
        )

    mostrar_volume = st.checkbox(
        "Volume",
        value=True,
        help="Mostra barras de volume no gráfico. Volume ajuda a avaliar força do movimento.",
    )


# ============================================================
# SELECAO DOS INDICADORES
# ============================================================

selection = IndicatorSelection(
    sma_periods=(tuple(sma_periods) if usar_sma else ()),
    ema_periods=(tuple(ema_periods) if usar_ema else ()),
    vwap=(usar_vwap and timeframe.is_intraday),
    bollinger_period=(int(bb_period) if usar_bb else None),
    bollinger_deviations=float(bb_dev),
    rsi_period=(int(rsi_period) if usar_rsi else None),
    macd=usar_macd,
    atr_period=(int(atr_period) if usar_atr else None),
)


# ============================================================
# MONITORAMENTO
# ============================================================

st.divider()

status_col, acao_col = st.columns([3, 1])


with status_col:
    if st.session_state.monitorando:
        if choice.is_metatrader:
            st.success(
                f"🟢 MT5 AO VIVO · {symbol} · atualização a cada "
                f"{settings.mt5_refresh_seconds}s"
            )
        else:
            st.info(
                f"🔎 HISTÓRICO CSV · {symbol} · o gráfico usa dados sintéticos locais, "
                "não cotação em tempo real."
            )

    else:
        st.info(f"⚪ Monitoramento parado · {symbol}")


with acao_col:
    if st.session_state.monitorando:
        if st.button(
            "■ Parar",
            use_container_width=True,
            key="stop_monitoring",
            help="Pausa as atualizações da tela. Não cancela ordens nem muda posições.",
        ):
            st.session_state.monitorando = False
            st.rerun()

    else:
        if st.button(
            "▶ Iniciar",
            type="primary",
            use_container_width=True,
            key="start_monitoring",
            help=(
                "Carrega os candles do ativo/timeframe selecionado. Com MT5 habilitado, "
                "a tela atualiza pelo terminal; com CSV, usa histórico sintético local."
            ),
        ):
            st.session_state.monitorando = True
            st.rerun()


if not st.session_state.monitorando:
    render_paper_orders(paper_broker)
    st.stop()


# ============================================================
# INTERVALO
# ============================================================

start = datetime.combine(
    start_date,
    time.min,
    tzinfo=display_timezone,
).astimezone(UTC)

requested_end = datetime.combine(
    end_date,
    time.min,
    tzinfo=display_timezone,
) + timedelta(days=1)
end = requested_end.astimezone(UTC)
now = clock.now()
if end_date >= now.astimezone(display_timezone).date():
    end = min(end, now)

if end <= start:
    st.warning(
        "Ainda não há candle fechado para o período selecionado no horário atual.",
        icon="⏳",
    )
    render_paper_orders(paper_broker)
    st.stop()


# ============================================================
# CARREGAMENTO
# ============================================================

try:
    result = cached_market_data(
        provider,
        clock,
        symbol_value=symbol,
        timeframe_value=timeframe.value,
        start_value=start,
        end_value=end,
    )

except (ProviderError, CashinhoError) as exc:
    st.error(
        f"Falha ao carregar dados: {exc}",
        icon="⛔",
    )

    st.stop()


# ============================================================
# SERIE VALIDADA
# ============================================================

if result.blocked:
    st.divider()

    with st.expander(
        "⚠️ Qualidade dos dados",
        expanded=True,
    ):
        quality_panel(
            result.report,
            rejection_reason=result.rejection_reason,
        )

    st.stop()

series = result.series


# ============================================================
# INDICADORES CALCULADOS
# ============================================================

# O grafico conserva os candles da serie completa. Seus overlays terminam no
# ultimo fechamento; o painel decisorio e um objeto separado e fechado.
panel = compute_panel(series, selection)
closed_series = series.closed_only()
signal_panel = panel if closed_series is series else compute_panel(closed_series, selection)


if panel.failures:
    with st.expander(
        "⚠️ Avisos dos indicadores",
        expanded=False,
    ):
        for label, motivo in panel.failures.items():
            st.warning(
                f"**{label}** não calculado — {motivo}",
                icon="⚠️",
            )


# ============================================================
# ENTRY SIGNAL
# ============================================================

signal = evaluate_entry_signal(
    closed_series,
    signal_panel,
)

# Toda a complexidade técnica converge em uma oportunidade e, depois, em uma
# decisão binária. A UI não interpreta regras individuais.
series_by_timeframe = {timeframe: closed_series}
raw_series_by_timeframe = {timeframe: series}
quality_statuses = [result.report.status]
ignored_timeframes: list[str] = []
for context_timeframe in available:
    if context_timeframe is timeframe:
        continue
    context_result = cached_market_data(
        provider,
        clock,
        symbol_value=symbol,
        timeframe_value=context_timeframe.value,
        start_value=start,
        end_value=end,
    )
    if context_result.usable_series is not None:
        quality_statuses.append(context_result.report.status)
        series_by_timeframe[context_timeframe] = context_result.usable_series
        raw_series_by_timeframe[context_timeframe] = context_result.series
    else:
        ignored_timeframes.append(
            f"{context_timeframe.value}: "
            f"{context_result.rejection_reason or context_result.report.status.value}"
        )

timeframe_analyses = analyze_timeframes(series_by_timeframe, selection)
timeframe_advice = advise_timeframe(timeframe_analyses)
selected_analysis = (
    timeframe_analyses.get(timeframe_advice.recommended_timeframe)
    if timeframe_advice.recommended_timeframe
    else None
)
if selected_analysis is not None:
    signal = selected_analysis.signal

risk_approved = False
if signal.entry is not None and signal.stop is not None and not profile_base.kill_switch_active:
    try:
        calculate_ticket_sizing(entry=signal.entry, stop=signal.stop, profile=profile_base)
        risk_approved = True
    except ValueError:
        pass

data_status = (
    DataStatus.BLOCKED
    if DataStatus.BLOCKED in quality_statuses
    else DataStatus.DEGRADED
    if DataStatus.DEGRADED in quality_statuses
    else DataStatus.OK
)
selected_series = (
    series_by_timeframe.get(timeframe_advice.recommended_timeframe)
    if timeframe_advice.recommended_timeframe
    else None
)
decision_timestamp = (
    selected_series.last.close_time
    if selected_series is not None and selected_series.last is not None
    else max(
        current.last.close_time
        for current in series_by_timeframe.values()
        if current.last is not None
    )
)
opportunity = build_opportunity(
    symbol=symbol,
    advice=timeframe_advice,
    analyses=timeframe_analyses,
    data_status=data_status,
    risk_approved=risk_approved,
    timestamp=decision_timestamp,
)
decision = make_final_decision(
    opportunity,
    data_quality_approved=data_status is not DataStatus.BLOCKED,
    risk_approved=risk_approved,
    candles_closed=not closed_series.has_open_candle,
    minimum_risk_reward=profile_base.min_risk_reward,
)
journal_audit.record_decision(decision, mode=INSPECTION_MODE)

if decision.timeframe is not None and decision.timeframe in raw_series_by_timeframe:
    timeframe = decision.timeframe
    series = raw_series_by_timeframe[timeframe]
    panel = compute_panel(series, selection)
    closed_series = series.closed_only()

last_closed = closed_series.last
if last_closed is not None:
    paper_broker.process_candle(last_closed, symbol=symbol, timeframe=timeframe.value)

# Uma posição aberta tem prioridade absoluta sobre qualquer nova decisão de entrada.
open_position = next(
    (
        order
        for order in paper_broker.list_orders()
        if order.ticket.symbol == symbol and order.status.value == "OPEN"
    ),
    None,
)
position_decision = None
if open_position is not None:
    position_timeframe = (
        Timeframe(open_position.ticket.timeframe)
        if open_position.ticket.timeframe in {item.value for item in Timeframe}
        else timeframe
    )
    position_series = series_by_timeframe.get(position_timeframe, closed_series)
    if position_series.last is not None:
        paper_broker.process_candle(
            position_series.last,
            symbol=symbol,
            timeframe=position_timeframe.value,
        )
    open_position = next(
        (
            order
            for order in paper_broker.list_orders()
            if order.id == open_position.id and order.status.value == "OPEN"
        ),
        None,
    )
    if open_position is not None:
        paper_market = collect_paper_market(
            provider,
            [open_position],
            clock=clock,
            max_age_seconds=settings.mt5_stale_seconds,
        )
        monitored = evaluate_open_position(
            open_position,
            series_by_timeframe=series_by_timeframe,
            selection=selection,
            risk=PositionRiskState(
                profile_base.kill_switch_active,
                "Risk Manager está com kill switch ativo.",
            ),
            current_price=paper_market.market_prices.get(symbol),
            market_exit_price=paper_market.close_prices.get(open_position.id),
        )
        position_decision = monitored.decision
        journal_audit.record_position_decision(open_position.id, position_decision)
        apply_position_decision(paper_broker, open_position, position_decision)
        timeframe = monitored.operational_timeframe
        if timeframe in raw_series_by_timeframe:
            series = raw_series_by_timeframe[timeframe]
            panel = compute_panel(series, selection)
            closed_series = series.closed_only()


# ============================================================
# OPORTUNIDADE ATUAL
# ============================================================

st.divider()
last_price = series.last.close if series.last else None
entrada_liberada = (
    open_position is None
    and position_decision is None
    and decision.should_enter
    and decision.side in {"BUY", "SELL"}
    and decision.entry is not None
    and decision.stop is not None
    and decision.target is not None
)
ticket_context = f"{symbol}:{decision.timeframe}:{decision.timestamp.isoformat()}:{decision.side}"
if st.session_state.get("paper_ticket_context") != ticket_context:
    st.session_state["paper_ticket_context"] = ticket_context
    st.session_state["paper_ticket_open"] = False

if open_position is not None and position_decision is not None:
    render_position_card(open_position, position_decision)
else:
    if not decision.should_enter and timeframe_analyses:
        strongest_analysis = max(
            timeframe_analyses.values(),
            key=lambda item: item.signal.score,
        )
        study_signal = strongest_analysis.signal
        if study_signal.score > 0:
            side_label = (
                "compra"
                if study_signal.side == "BUY"
                else "venda"
                if study_signal.side == "SELL"
                else "neutra"
            )
            st.info(
                f"Leitura de estudo: **{study_signal.status}** no timeframe "
                f"**{strongest_analysis.timeframe.value}**, lado **{side_label}**, "
                f"confiança **{study_signal.score}/100**. "
                "Ainda não é entrada liberada porque faltam todos os filtros obrigatórios.",
                icon="🔎",
            )
            if study_signal.reasons:
                st.caption(" · ".join(study_signal.reasons[-2:]))
    if render_decision_card(
        decision,
        symbol=symbol,
        last_price=last_price,
        feed_label="MT5 ONLINE" if choice.is_metatrader else "DADOS HISTÓRICOS",
    ):
        st.session_state["paper_ticket_open"] = True


# ============================================================
# GRAFICO
# ============================================================

st.divider()
st.subheader(f"📈 {symbol} · {timeframe.value}")
if choice.is_metatrader:
    st.caption(
        "Este gráfico usa candles fechados recebidos do MetaTrader 5. "
        "Com o monitoramento ligado, a tela busca novos candles do terminal."
    )
else:
    st.caption(
        "Este gráfico usa candles históricos dos CSV locais. Ele serve para estudo e "
        "desenvolvimento; para atualizar pelo mercado, habilite o MT5 e deixe o terminal aberto."
    )
st.plotly_chart(
    candlestick_figure(
        series,
        display_timezone=settings.display_timezone,
        panel=panel,
        show_volume=mostrar_volume,
    ),
    theme="streamlit",
    use_container_width=True,
)


# ============================================================
# BOLETA PAPER
# ============================================================

st.divider()


boleta_disponivel = entrada_liberada and st.session_state.get("paper_ticket_open", False)


if not boleta_disponivel:
    st.markdown("## Boleta PAPER")
    if entrada_liberada:
        st.info("Clique em **ABRIR BOLETA PAPER** para preparar a simulação.")
    else:
        st.info("A boleta PAPER fica disponível somente quando a entrada é liberada.")


else:
    lado_sinal = "COMPRA" if signal.side == "BUY" else "VENDA"

    st.markdown(f"## Boleta PAPER — {symbol}")

    st.caption(f"Decisão atual: **{lado_sinal}** · Confiança {decision.confidence}/100 · PAPER")

    # ========================================================
    # CAPITAL E RISCO
    # ========================================================

    with st.expander(
        "💰 Capital e limites de risco",
        expanded=True,
    ):
        col_capital, col_risco, col_exposicao = st.columns(3)

        with col_capital:
            capital_operacional = st.number_input(
                "Capital disponível (R$)",
                min_value=1.00,
                value=float(st.session_state.capital_operacional),
                step=100.00,
                format="%.2f",
                key="boleta_capital",
                help=(
                    "Capital usado apenas para calcular tamanho da simulação PAPER. "
                    "Não consulta saldo real da corretora."
                ),
            )

        with col_risco:
            risco_por_operacao_pct = st.number_input(
                "Risco por operação (%)",
                min_value=0.01,
                max_value=100.00,
                value=float(st.session_state.risco_por_operacao_pct),
                step=0.10,
                format="%.2f",
                key="boleta_risco_pct",
                help=(
                    "Percentual máximo do capital que você aceita perder se o stop for atingido."
                ),
            )

        with col_exposicao:
            exposicao_por_ativo_pct = st.number_input(
                "Exposição máx. por ativo (%)",
                min_value=0.01,
                max_value=100.00,
                value=float(st.session_state.exposicao_por_ativo_pct),
                step=1.00,
                format="%.2f",
                key="boleta_exposicao_pct",
                help=(
                    "Limite de quanto do capital pode ficar concentrado neste ativo."
                ),
            )

        st.session_state.capital_operacional = capital_operacional

        st.session_state.risco_por_operacao_pct = risco_por_operacao_pct

        st.session_state.exposicao_por_ativo_pct = exposicao_por_ativo_pct

        profile = RiskProfile(
            name="boleta",
            capital=Decimal(str(capital_operacional)),
            risk_per_trade_pct=Decimal(str(risco_por_operacao_pct)),
            max_daily_loss_pct=(profile_base.max_daily_loss_pct),
            max_drawdown_pct=(profile_base.max_drawdown_pct),
            max_exposure_pct=(profile_base.max_exposure_pct),
            max_exposure_per_symbol_pct=Decimal(str(exposicao_por_ativo_pct)),
            max_trades_per_day=(profile_base.max_trades_per_day),
            max_consecutive_losses=(profile_base.max_consecutive_losses),
            max_open_positions=(profile_base.max_open_positions),
            min_risk_reward=(profile_base.min_risk_reward),
            kill_switch_active=(profile_base.kill_switch_active),
        )

        risco_maximo_reais = (
            Decimal(str(capital_operacional))
            * Decimal(str(risco_por_operacao_pct))
            / Decimal("100")
        )

        exposicao_maxima_reais = (
            Decimal(str(capital_operacional))
            * Decimal(str(exposicao_por_ativo_pct))
            / Decimal("100")
        )

        r1, r2 = st.columns(2)

        r1.metric(
            "Risco máximo por operação",
            f"R$ {risco_maximo_reais:,.2f}",
            help="Valor máximo em reais que a simulação permite arriscar nesta operação.",
        )

        r2.metric(
            "Exposição máxima por ativo",
            f"R$ {exposicao_maxima_reais:,.2f}",
            help="Valor máximo em reais que pode ficar comprado ou vendido neste ativo.",
        )

    # ========================================================
    # TIPO DA ORDEM
    # ========================================================

    tipo_padrao = "Compra" if signal.side == "BUY" else "Venda"

    tipos_ordem = [
        "Compra",
        "Compra Stop",
        "Venda",
        "Venda Stop",
    ]

    tipo_ordem = st.radio(
        "Tipo da ordem",
        options=tipos_ordem,
        index=tipos_ordem.index(tipo_padrao),
        horizontal=True,
        key="paper_order_type",
        help=(
            "Define se a simulação é compra ou venda. Nesta fase, apenas Compra e Venda "
            "limitadas são executadas pelo Paper Broker."
        ),
    )

    ordem_stop = tipo_ordem in {
        "Compra Stop",
        "Venda Stop",
    }

    if ordem_stop:
        st.warning(
            "Compra Stop e Venda Stop aparecem para "
            "preparar a interface, mas ainda não estão "
            "implementadas no Paper Broker.",
            icon="🟡",
        )

    lado_boleta = "BUY" if tipo_ordem in {"Compra", "Compra Stop"} else "SELL"

    # ========================================================
    # VALIDADE
    # ========================================================

    col_validade, col_data = st.columns(2)

    with col_validade:
        validade = st.selectbox(
            "Validade",
            options=[
                "Hoje",
                "Data específica",
            ],
            index=0,
            key="paper_validity",
            help=(
                "Até quando a ordem PAPER poderia ficar pendente. Hoje significa que "
                "ela vale só para a data atual da simulação."
            ),
        )

    with col_data:
        if validade == "Hoje":
            data_validade = st.date_input(
                "Data Validade",
                value=hoje,
                disabled=True,
                key="paper_validity_today",
                help="Data usada quando a validade escolhida é Hoje.",
            )

        else:
            data_validade = st.date_input(
                "Data Validade",
                value=hoje,
                min_value=hoje,
                key="paper_validity_date",
                help="Última data em que a ordem PAPER pode permanecer válida.",
            )

    # ========================================================
    # PRECO
    # ========================================================

    col_preco, col_mercado = st.columns([2, 1])

    with col_mercado:
        a_mercado = st.checkbox(
            "A Mercado",
            value=False,
            key="paper_market_order",
            help=(
                "Ordem a mercado executaria pelo melhor preço disponível. Nesta tela "
                "ela fica bloqueada quando não há bid/ask confiável."
            ),
        )

    with col_preco:
        preco_ordem = st.number_input(
            "Preço",
            min_value=0.01,
            value=float(signal.entry),
            step=0.01,
            format="%.2f",
            disabled=a_mercado,
            key=f"paper_price_{symbol}",
            help="Preço de entrada da simulação PAPER. Não envia ordem real ao mercado.",
        )

    # ========================================================
    # OCO
    # ========================================================

    st.markdown("### Estratégia OCO")

    usar_oco = st.toggle(
        "Ativar Gain + Loss",
        value=True,
        key="paper_oco",
        help=(
            "Liga a estratégia OCO: um alvo de ganho e um stop de perda. "
            "Na simulação atual, isso é obrigatório para controlar risco."
        ),
    )

    col_gain, col_loss, col_offset = st.columns(3)

    with col_gain:
        gain = st.number_input(
            "Gain",
            min_value=0.01,
            value=float(signal.target),
            step=0.01,
            format="%.2f",
            disabled=not usar_oco,
            key=f"paper_gain_{symbol}",
            help="Preço-alvo da operação. Se chegar nele, a simulação encerra com ganho.",
        )

    with col_loss:
        loss = st.number_input(
            "Loss",
            min_value=0.01,
            value=float(signal.stop),
            step=0.01,
            format="%.2f",
            disabled=not usar_oco,
            key=f"paper_loss_{symbol}",
            help="Preço de stop. Se chegar nele, a simulação encerra para limitar perda.",
        )

    with col_offset:
        offset = st.number_input(
            "Offset",
            min_value=0.00,
            value=0.10,
            step=0.01,
            format="%.2f",
            disabled=not usar_oco,
            key=f"paper_offset_{symbol}",
            help=(
                "Folga de preço usada para preparar ordens stop/limit futuras. "
                "Hoje é apenas parâmetro visual da boleta PAPER."
            ),
        )

    # ========================================================
    # CONVERSAO DOS VALORES DA BOLETA
    # ========================================================

    preco_decimal = Decimal(str(preco_ordem))

    gain_decimal = Decimal(str(gain))

    loss_decimal = Decimal(str(loss))

    # ========================================================
    # VALIDACAO DA GEOMETRIA DA ORDEM
    # ========================================================

    if lado_boleta == "BUY":
        estrutura_preco_valida = loss_decimal < preco_decimal and gain_decimal > preco_decimal

    else:
        estrutura_preco_valida = loss_decimal > preco_decimal and gain_decimal < preco_decimal

    risco_por_acao_manual = abs(preco_decimal - loss_decimal)

    retorno_por_acao_manual = abs(gain_decimal - preco_decimal)

    if risco_por_acao_manual > 0:
        rr_manual = retorno_por_acao_manual / risco_por_acao_manual

    else:
        rr_manual = Decimal("0")

    # ========================================================
    # DIMENSIONAMENTO
    # ========================================================

    sizing = None

    if estrutura_preco_valida:
        try:
            sizing = calculate_ticket_sizing(
                entry=preco_decimal,
                stop=loss_decimal,
                profile=profile,
                lot_size=1,
            )

        except ValueError as exc:
            st.error(
                f"Boleta bloqueada pelo Risk Manager: {exc}",
                icon="⛔",
            )

    if sizing is not None:
        # ====================================================
        # ATIVO / QUANTIDADE / TOTAL
        # ====================================================

        col_ativo, col_qtd, col_total = st.columns([1.3, 1, 1])

        with col_ativo:
            st.text_input(
                "Ativo",
                value=symbol,
                disabled=True,
                key="paper_symbol",
                help=(
                    "Ativo que veio da análise acima. Ele fica travado para evitar "
                    "abrir uma boleta no papel errado."
                ),
            )

        qty_key = f"paper_qty_{symbol}_{timeframe.value}"

        # O Risk Manager e a autoridade: toda reexecucao recalcula e ajusta
        # o valor do widget quando capital, risco, exposicao, preco ou stop mudam.
        st.session_state[qty_key] = min(
            int(st.session_state.get(qty_key, sizing.quantity)), sizing.quantity
        )

        with col_qtd:
            quantidade = st.number_input(
                "Quantidade",
                min_value=1,
                max_value=sizing.quantity,
                step=1,
                key=qty_key,
                help=(
                    "Número de ações simuladas. O máximo vem do Risk Manager, baseado "
                    "no capital, risco e distância até o stop."
                ),
            )

        quantidade = int(quantidade)

        total_operacao = preco_decimal * Decimal(quantidade)

        with col_total:
            st.metric(
                "Total",
                f"R$ {total_operacao:,.2f}",
                help="Preço de entrada multiplicado pela quantidade escolhida.",
            )

        # ====================================================
        # CONTROLE DE RISCO
        # ====================================================

        risco_ordem = risco_por_acao_manual * Decimal(quantidade)

        exposicao_ordem = preco_decimal * Decimal(quantidade)

        st.markdown("### Controle de risco")

        row1_col1, row1_col2 = st.columns(2)

        row1_col1.metric(
            "Risco da ordem",
            f"R$ {risco_ordem:,.2f}",
            help="Quanto a simulação perderia se o preço batesse no stop.",
        )

        row1_col2.metric(
            "Risco máximo",
            f"R$ {sizing.monetary_risk_limit:,.2f}",
            help="Limite em reais calculado a partir do risco por operação.",
        )

        row2_col1, row2_col2 = st.columns(2)

        row2_col1.metric(
            "Exposição",
            f"R$ {exposicao_ordem:,.2f}",
            help="Valor financeiro total exposto na operação simulada.",
        )

        row2_col2.metric(
            "R:R",
            f"{rr_manual:.2f}",
            help=(
                "Relação risco-retorno. Exemplo: 2.00 significa buscar ganhar "
                "duas vezes o valor que está sendo arriscado."
            ),
        )

        st.caption(
            f"Quantidade recomendada: "
            f"**{sizing.quantity} ações** · "
            f"limitante: "
            f"`{sizing.limiting_constraint}`"
        )

        # ====================================================
        # VALIDACOES
        # ====================================================

        quantidade_valida = quantidade <= sizing.quantity

        rr_valido = rr_manual >= profile.min_risk_reward

        direcao_valida = lado_boleta == signal.side

        kill_switch_ok = not profile.kill_switch_active

        oco_valido = usar_oco

        if not direcao_valida:
            st.error(
                f"O sinal atual é de **{lado_sinal}**. "
                "A direção não pode ser invertida "
                "manualmente nesta fase.",
                icon="⛔",
            )

        if not quantidade_valida:
            st.error(
                "Quantidade acima do máximo calculado pelo Risk Manager.",
                icon="⛔",
            )

        if not rr_valido:
            st.error(
                f"R:R atual ({rr_manual:.2f}) está abaixo "
                f"do mínimo permitido "
                f"({profile.min_risk_reward}).",
                icon="⛔",
            )

        if not kill_switch_ok:
            st.error(
                "KILL SWITCH ATIVO — novas operações estão bloqueadas.",
                icon="⛔",
            )

        if not oco_valido:
            st.warning(
                "Nesta versão PAPER, mantenha a estratégia "
                "OCO ativa para que a posição tenha "
                "stop e alvo definidos.",
                icon="⚠️",
            )

        pode_simular = (
            not ordem_stop
            and not a_mercado
            and estrutura_preco_valida
            and direcao_valida
            and quantidade_valida
            and rr_valido
            and kill_switch_ok
            and oco_valido
        )

        if a_mercado:
            st.error(
                "Ordem a mercado PAPER bloqueada: esta tela não possui bid/ask ativo "
                "e não inventa preço de execução.",
                icon="⛔",
            )

        # ====================================================
        # BOTAO
        # ====================================================

        st.divider()

        texto_botao = "🟢 Simular Compra" if lado_boleta == "BUY" else "🔴 Simular Venda"

        if st.button(
            texto_botao,
            type="primary",
            disabled=not pode_simular,
            use_container_width=True,
            key="paper_submit",
            help=(
                "Registra a ordem apenas no ambiente PAPER. Nenhuma ordem real é enviada "
                "ao MetaTrader ou à corretora."
            ),
        ):
            try:
                ticket = build_paper_ticket(
                    symbol=symbol,
                    side=lado_boleta,
                    entry=preco_decimal,
                    stop=loss_decimal,
                    target=gain_decimal,
                    quantity=quantidade,
                    min_risk_reward=profile.min_risk_reward,
                    maximum_quantity=sizing.quantity,
                    timeframe=decision.timeframe.value if decision.timeframe else timeframe.value,
                )

            except ValueError as exc:
                st.error(
                    f"Não foi possível criar a ordem PAPER: {exc}",
                    icon="⛔",
                )

            else:
                agora = datetime.now(UTC)

                paper_broker.register(
                    ticket,
                    PaperOrderType.LIMIT,
                    now=agora,
                    decision_key=decision_idempotency_key(decision),
                )

                st.success(f"✅ Ordem PAPER de {lado_sinal} registrada: {quantidade} {symbol}.")

                st.caption("Nenhuma chamada de order_send() foi realizada.")

    elif not estrutura_preco_valida:
        if lado_boleta == "BUY":
            st.error(
                "Para COMPRA: Loss deve ficar abaixo da entrada e Gain acima da entrada.",
                icon="⛔",
            )

        else:
            st.error(
                "Para VENDA: Loss deve ficar acima da entrada e Gain abaixo da entrada.",
                icon="⛔",
            )


# ============================================================
# ORDENS PAPER
# ============================================================

st.divider()
render_paper_orders(paper_broker)

with st.expander("Por que essa decisão?", expanded=False):
    st.caption(
        "Resumo em linguagem direta dos motivos que fizeram o sistema liberar, negar "
        "ou manter a decisão atual."
    )
    for reason in decision.reasons:
        st.write(f"• {reason}")

with st.expander("Multi-timeframe", expanded=False):
    st.caption(
        "Mostra quais tempos de gráfico foram usados como contexto, qual tempo ficou "
        "como operacional e qual pode servir como gatilho."
    )
    st.write(
        "Timeframes de contexto:",
        ", ".join(tf.value for tf in timeframe_advice.context_timeframes) or "—",
    )
    st.write(
        "Timeframe operacional:",
        timeframe_advice.recommended_timeframe.value
        if timeframe_advice.recommended_timeframe
        else "—",
    )
    st.write(
        "Timeframe de gatilho:",
        timeframe_advice.trigger_timeframe.value if timeframe_advice.trigger_timeframe else "—",
    )
    for reason in timeframe_advice.reasons:
        st.write(f"• {reason}")
    if ignored_timeframes:
        st.caption(
            "Timeframes ignorados por falta de dados suficientes ou qualidade bloqueada: "
            + " · ".join(ignored_timeframes)
        )


# ============================================================
# DIAGNOSTICO
# ============================================================

with st.expander(
    "🩺 Qualidade e origem dos dados",
    expanded=False,
):
    st.caption(
        "Antes de calcular sinal, o Cashinho verifica se os candles estão completos, "
        "recentes e coerentes com a fonte usada."
    )
    quality_panel(
        result.report,
        rejection_reason=result.rejection_reason,
    )


# ============================================================
# ULTIMOS INDICADORES
# ============================================================

if panel.has_content:
    with st.expander(
        "📐 Últimos valores dos indicadores",
        expanded=False,
    ):
        st.caption(
            "Última leitura calculada de cada indicador. O aquecimento indica quantos "
            "candles o indicador precisa antes de ficar confiável."
        )
        linhas = []

        for label, resultado in {
            **panel.overlays,
            **panel.oscillators,
        }.items():
            for coluna, valor in resultado.last().items():
                linhas.append(
                    {
                        "Indicador": label,
                        "Linha": coluna,
                        "Valor": ("—" if valor is None else f"{valor:,.4f}"),
                        "Aquecimento": resultado.warmup,
                    }
                )

        st.dataframe(
            linhas,
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# RESUMO TECNICO
# ============================================================

primeiro = series.candles[0]
ultimo = series.candles[-1]

variacao = (ultimo.close - primeiro.open) / primeiro.open * 100


with st.expander(
    "📊 Resumo técnico do período",
    expanded=False,
):
    st.caption(
        "Resumo simples do intervalo escolhido no topo da tela, não uma recomendação de compra ou venda."
    )
    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Candles",
        len(series),
        help="Quantidade de candles carregados no período filtrado.",
    )

    col2.metric(
        "Último fechamento",
        f"R$ {ultimo.close}",
        help="Preço de fechamento do candle mais recente carregado na tela.",
    )

    col3.metric(
        "Variação",
        f"{variacao:.2f}%",
        help=(
            "Diferença percentual entre o primeiro preço de abertura e o último "
            "fechamento do período."
        ),
    )

    col4.metric(
        "Volume total",
        f"{sum(c.volume for c in series.candles):,}".replace(
            ",",
            ".",
        ),
        help=(
            "Soma do volume informado pelos candles carregados. Em CSV sintético, "
            "é apenas dado de desenvolvimento."
        ),
    )

    st.caption(
        f"Período efetivo: "
        f"{primeiro.timestamp.astimezone(display_timezone).strftime('%d/%m/%Y %H:%M')} "
        f"até "
        f"{ultimo.close_time.astimezone(display_timezone).strftime('%d/%m/%Y %H:%M')} · "
        f"origem `{series.source}` · "
        f"coleta "
        f"{series.fetched_at.strftime('%H:%M:%S UTC')}"
    )


# ============================================================
# TABELA
# ============================================================

with st.expander(
    "🗃️ Dados carregados",
    expanded=False,
):
    st.caption(
        "Tabela com os candles usados no cálculo. É útil para conferir datas, preços, "
        "volume e origem dos dados."
    )
    rows = series.to_records()[-200:]
    for row in rows:
        timestamp = row["timestamp"]
        if isinstance(timestamp, datetime):
            row["timestamp"] = timestamp.astimezone(display_timezone)
    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# REFRESH AUTOMATICO
#
# PRECISA SER O ULTIMO BLOCO DO ARQUIVO.
# ============================================================

if st.session_state.monitorando and choice.is_metatrader:
    time_module.sleep(settings.mt5_refresh_seconds)

    st.rerun()
