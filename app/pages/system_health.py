"""Saude do Mercado — estado tecnico verificavel."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from app.components.chrome import page_header, sidebar
from cashinho.adapters.persistence.session import (
    create_db_engine,
    init_db,
    resolve_database_url,
)
from cashinho.adapters.providers.factory import build_market_data_provider
from cashinho.config.settings import get_settings
from cashinho.core.time.b3_calendar import B3Calendar
from cashinho.core.time.clocks import SystemClock
from cashinho.domain.enums import Mode, Timeframe
from cashinho.pipeline.market_health import MarketHealthColor, assess_market_health
from cashinho.version import __version__

MONITORED_SYMBOL = "PETR4"
"""Ativo usado para verificar o feed. Primeiro papel integrado ao MT5."""

settings = get_settings()
sidebar(settings)
page_header("Saúde do Mercado", "Prova se o app está lendo dados atuais do MT5")
st.caption(
    "Antes de qualquer entrada, esta tela precisa estar saudável. Se o semáforo "
    "ficar vermelho, o Cashinho bloqueia sinais ao vivo."
)

clock = SystemClock()
calendar = B3Calendar()
now = clock.now()

col1, col2, col3 = st.columns(3)
col1.metric(
    "Versao do codigo",
    __version__,
    help="Versão do Cashinho que está rodando nesta máquina.",
)
col2.metric(
    "Relogio",
    clock.kind,
    help="Origem do horário usado pelo app para filtros, auditoria e simulações.",
)
col3.metric(
    "Hash da configuracao",
    settings.config_hash(),
    help="Assinatura curta da configuração carregada. Ajuda a perceber se o ambiente mudou.",
)

st.subheader("Tempo")
st.caption("Compara o horário interno em UTC com o horário local da B3.")
st.write(f"Instante logico (UTC): `{now.isoformat()}`")
st.write(f"Horario local da B3: `{calendar.to_local(now).strftime('%d/%m/%Y %H:%M:%S')}`")
if calendar.is_open(now):
    st.success("Pregao regular aberto.", icon="🟢")
else:
    st.info("Pregao regular fechado.", icon="🔴")
if not calendar.holidays_loaded:
    st.warning(
        "Calendario de feriados da B3 nao carregado. Dias uteis sao aproximados "
        "ate a integracao de uma fonte oficial (Fase 2).",
        icon="⚠️",
    )

st.subheader("Banco de dados")
st.caption("Verifica se o diário, decisões e ordens PAPER conseguem ser gravados.")
try:
    engine = create_db_engine(settings)
    init_db(engine)
    st.success(f"Conectado: `{resolve_database_url(settings.database_url)}`", icon="✅")
except Exception as exc:  # a tela deve mostrar a falha, nao quebrar
    st.error(f"Falha ao conectar: {exc}", icon="⛔")

choice = build_market_data_provider(settings, clock)
symbols = choice.offered_symbols() or (MONITORED_SYMBOL,)
display_timezone = ZoneInfo(settings.display_timezone)

st.subheader("Saúde do Mercado")
st.caption("Mostra se o app está usando MT5 ao vivo ou uma fonte histórica/local.")
col_symbol, col_tf = st.columns(2)
symbol = col_symbol.selectbox(
    "Símbolo",
    symbols,
    index=symbols.index(MONITORED_SYMBOL) if MONITORED_SYMBOL in symbols else 0,
    help="Ativo usado nesta checagem de saúde do feed.",
)
timeframe = col_tf.selectbox(
    "Timeframe",
    tuple(Timeframe),
    index=tuple(Timeframe).index(Timeframe.M5),
    format_func=lambda item: item.value,
    help="Tamanho do candle usado para medir se os dados estão atuais.",
)

health = assess_market_health(
    choice,
    symbol=symbol,
    timeframe=timeframe,
    start=now - timedelta(days=2),
    end=now,
    clock=clock,
    mode=settings.mode if choice.realtime else Mode.RESEARCH,
)

if health.color is MarketHealthColor.GREEN:
    st.success("VERDE — dados atuais", icon="🟢")
elif health.color is MarketHealthColor.YELLOW:
    st.warning("AMARELO — dados atrasados ou incompletos", icon="🟡")
else:
    offline = "TERMINAL OFFLINE. " if not health.mt5_connected else ""
    st.error(
        f"VERMELHO — dados inválidos para sinal ao vivo. {offline}{health.reason}",
        icon="🔴",
    )
st.caption(health.reason)

top = st.columns(4)
top[0].metric("MT5 conectado", "SIM" if health.mt5_connected else "NÃO")
top[1].metric("Conta conectada", "SIM" if health.mt5_connected else "NÃO")
top[2].metric("Servidor", health.server or "—")
top[3].metric("Modo", health.account_mode)

mid = st.columns(4)
mid[0].metric("Símbolo", health.symbol)
mid[1].metric("Timeframe", health.timeframe.value)
mid[2].metric("Spread atual", health.spread if health.spread is not None else "—")
mid[3].metric("Candles carregados", health.candles_loaded)

def _local(moment: object) -> str:
    if not isinstance(moment, datetime):
        return "—"
    return moment.astimezone(display_timezone).strftime("%d/%m/%Y %H:%M:%S")


age = "—" if health.data_age_seconds is None else f"{health.data_age_seconds:.0f}s"
bottom = st.columns(4)
bottom[0].metric("Horário atual", _local(health.current_time))
bottom[1].metric("Último tick recebido", _local(health.last_tick_at))
bottom[2].metric("Último candle recebido", _local(health.last_candle_at))
bottom[3].metric("Idade do último dado", age)

if health.data_quality is not None and health.data_quality.issues:
    with st.expander("Problemas encontrados"):
        for issue in health.data_quality.issues:
            st.write(f"**{issue.code}** — {issue.message}")
            if issue.evidence:
                st.caption(issue.evidence)

st.caption(
    f"Provider ativo: `{choice.provider.capabilities.name}` — {choice.reason}. "
    f"Fuso interno: UTC · exibição: {settings.display_timezone} · "
    f"MT5: {settings.mt5_server_timezone} · agora UTC {now.astimezone(UTC).isoformat()}"
)
