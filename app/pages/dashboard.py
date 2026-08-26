"""Dashboard operacional baseado no diário e no Paper Broker."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import streamlit as st

from app.components.chrome import page_header, sidebar
from app.components.feed import render_feed_status
from app.components.journal import operational_decision_rows, paper_trade_rows
from app.components.paper_summary import money
from app.runtime import build_paper_broker, journal_session_factory
from cashinho.adapters.persistence.repositories import JournalRepository
from cashinho.adapters.providers.factory import build_market_data_provider
from cashinho.config.settings import get_settings
from cashinho.core.time.clocks import SystemClock
from cashinho.domain.errors import CashinhoError
from cashinho.pipeline.paper_market import collect_paper_market
from cashinho.pipeline.paper_performance import summarize_orders

MONITORED_SYMBOL = "PETR4"

settings = get_settings()
clock = SystemClock()
sidebar(settings)
page_header("Dashboard", "Decisões auditadas e operação PAPER")
st.caption(
    "Visão geral do que o Cashinho já decidiu, simulou e mantém em aberto. "
    "Use os ícones de ajuda para entender cada número antes de agir."
)

choice = build_market_data_provider(
    settings, clock, fixtures_root=settings.data_dir / "fixtures"
)
feed_status = "HISTÓRICO"
if choice.is_metatrader:
    try:
        feed_status = choice.provider.feed_status(MONITORED_SYMBOL).value  # type: ignore[attr-defined]
    except (CashinhoError, RuntimeError):
        feed_status = "OFFLINE"

profile = settings.risk_profile()
source_top = st.columns(3)
source_top[0].metric(
    "Provider",
    choice.provider.capabilities.name,
    help="Fonte de dados ativa agora. Pode ser MT5 em tempo real ou CSV histórico local.",
)
source_top[1].metric(
    "Tempo real",
    "SIM" if choice.provider.capabilities.supports_realtime else "NÃO",
    help="Mostra se a fonte consegue trazer cotação atual do mercado.",
)
source_top[2].metric(
    "Status do feed",
    feed_status,
    help="Estado do dado para o ativo monitorado. Offline ou histórico não deve ser tratado como ao vivo.",
)
account_top = st.columns(3)
account_top[0].metric(
    "Modo",
    settings.mode.value,
    help="Modo operacional carregado da configuração. Ele define quais travas do sistema ficam ativas.",
)
account_top[1].metric(
    "Capital",
    money(profile.capital),
    help="Capital usado como base para calcular tamanho de posição e risco máximo.",
)
account_top[2].metric(
    "Risco por operação",
    f"{profile.risk_per_trade_pct}%",
    help="Percentual máximo do capital que uma única operação PAPER pode arriscar.",
)

broker, _audit = build_paper_broker()
orders = broker.list_orders()
market = collect_paper_market(
    choice.provider,
    orders,
    clock=clock,
    max_age_seconds=settings.mt5_stale_seconds,
)
summary = summarize_orders(
    orders,
    market_prices=market.market_prices,
    on_date=clock.now().date(),
)
with journal_session_factory()() as session:
    repository = JournalRepository(session)
    decisions = repository.list_recent_decisions(limit=20)
    position_decisions = repository.list_recent_position_decisions(limit=20)
    trades = repository.list_recent_paper_trades(limit=20)
    today = clock.now().date()
    day_start = datetime.combine(today, time.min, tzinfo=UTC)
    released_today = repository.count_released_decisions(
        start=day_start,
        end=day_start + timedelta(days=1),
    )

st.divider()
st.subheader("Resumo")
st.caption("Números do dia e da carteira PAPER simulada. Eles não representam ordens reais.")
first = st.columns(3)
first[0].metric(
    "Entradas liberadas hoje",
    released_today,
    help="Quantidade de decisões auditadas hoje que liberaram entrada.",
)
first[1].metric(
    "Operações PAPER abertas",
    summary.open_positions,
    help="Posições simuladas que ainda estão abertas no Paper Broker.",
)
first[2].metric(
    "P&L PAPER realizado",
    money(summary.realized_pnl),
    help="Resultado financeiro das operações PAPER já encerradas.",
)
second = st.columns(2)
second[0].metric(
    "P&L PAPER aberto",
    money(summary.unrealized_pnl),
    help="Resultado estimado das posições abertas usando a cotação disponível.",
)
second[1].metric(
    "Risco em uso",
    money(summary.exposed_risk),
    help="Soma do risco que ainda está exposto nas posições simuladas.",
)
if summary.unpriced_positions:
    st.caption("P&L aberto oculto porque não há cotação válida para todas as posições.")

st.divider()
st.subheader("Últimas decisões")
st.caption("Histórico recente do que a inteligência decidiu para análise, entrada ou posição.")
if decisions or position_decisions:
    st.dataframe(
        operational_decision_rows(decisions, position_decisions)[:20],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("Nenhuma decisão operacional auditada ainda.")

st.divider()
st.subheader("Últimas operações")
st.caption("Registros mais recentes de ordens e fechamentos no ambiente PAPER.")
if trades:
    st.dataframe(paper_trade_rows(trades), use_container_width=True, hide_index=True)
else:
    st.info("Nenhuma operação PAPER auditada ainda.")

with st.expander("Status detalhado do feed"):
    st.caption(
        "Mostra terminal, servidor, cotação e motivo do status da fonte de dados atual."
    )
    render_feed_status(choice, MONITORED_SYMBOL, settings.display_timezone)
