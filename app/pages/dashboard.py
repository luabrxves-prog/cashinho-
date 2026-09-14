"""Dashboard operacional baseado no diário e no Paper Broker."""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo
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

settings = get_settings()
clock = SystemClock()
sidebar(settings)
page_header("Dashboard", "Decisões auditadas e operação PAPER")
choice = build_market_data_provider(settings, clock, fixtures_root=settings.data_dir / "fixtures")

feed_status = "HISTÓRICO"
if choice.is_metatrader:
    try:
        feed_status = choice.provider.feed_status("PETR4").value  # type: ignore[attr-defined]
    except (CashinhoError, RuntimeError):
        feed_status = "OFFLINE"

profile = settings.risk_profile()
a, b, c = st.columns(3)
a.metric("Provider", choice.provider.capabilities.name)
b.metric("Tempo real", "SIM" if choice.provider.capabilities.supports_realtime else "NÃO")
c.metric("Status do feed", feed_status)
a, b, c = st.columns(3)
a.metric("Modo", settings.mode.value)
b.metric("Capital", money(profile.capital))
c.metric("Risco por operação", f"{profile.risk_per_trade_pct}%")


def _today_bounds_utc() -> tuple[datetime, datetime]:
    tz = ZoneInfo(settings.display_timezone)
    start = datetime.combine(clock.now().astimezone(tz).date(), time.min, tzinfo=tz)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


@st.fragment(run_every=f"{settings.mt5_refresh_seconds}s")
def live_content() -> None:
    broker, _audit = build_paper_broker()
    orders = broker.list_orders()
    market = collect_paper_market(choice.provider, orders, clock=clock, max_age_seconds=settings.mt5_stale_seconds)
    summary = summarize_orders(orders, market_prices=market.market_prices, on_date=clock.now().date())
    start, end = _today_bounds_utc()
    with journal_session_factory()() as session:
        repo = JournalRepository(session)
        decisions = repo.list_recent_decisions(limit=100)
        positions = repo.list_recent_position_decisions(limit=100)
        trades = repo.list_recent_paper_trades(limit=100)
        released_today = repo.count_released_decisions(start=start, end=end)

    left, right = st.columns([1, 4])
    left.button("Atualizar agora", key="dashboard_refresh")
    right.caption(f"Atualização automática a cada {settings.mt5_refresh_seconds}s")

    st.divider()
    st.subheader("Resumo")
    a, b, c = st.columns(3)
    a.metric("Entradas liberadas hoje", released_today)
    b.metric("Operações PAPER abertas", summary.open_positions)
    c.metric("Ordens pendentes", summary.pending_orders)
    a, b, c = st.columns(3)
    a.metric("P&L PAPER realizado", money(summary.realized_pnl))
    b.metric("P&L PAPER aberto", money(summary.unrealized_pnl))
    c.metric("Risco em uso", money(summary.exposed_risk))

    st.divider()
    st.subheader("Últimas decisões")
    rows = operational_decision_rows(decisions, positions, settings.display_timezone)
    if rows:
        st.dataframe(rows[:50], use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma decisão operacional auditada ainda.")

    st.divider()
    st.subheader("Últimas operações")
    st.caption("Campos ainda inexistentes em ordens PENDING aparecem como —.")
    rows = paper_trade_rows(trades, settings.display_timezone)
    if rows:
        st.dataframe(rows[:50], use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma operação PAPER auditada ainda.")

    with st.expander("Status detalhado do feed"):
        render_feed_status(choice, "PETR4", settings.display_timezone)


live_content()
