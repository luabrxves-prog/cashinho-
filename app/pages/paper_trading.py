"""Acompanhamento operacional estritamente PAPER."""

from __future__ import annotations

from datetime import datetime, timedelta

import streamlit as st

from app.components.chrome import page_header, sidebar
from app.components.feed import render_source_banner
from app.components.paper_summary import render_paper_summary
from app.components.positions import (
    render_closed_positions,
    render_open_positions,
    render_pending_orders,
)
from app.runtime import build_paper_broker
from cashinho.adapters.providers.factory import build_market_data_provider
from cashinho.config.settings import get_settings
from cashinho.core.time.clocks import SystemClock
from cashinho.domain.enums import Mode, Timeframe
from cashinho.domain.errors import CashinhoError
from cashinho.pipeline.indicators import IndicatorSelection
from cashinho.pipeline.market_data import load_market_data
from cashinho.pipeline.paper_broker import PaperOrderStatus
from cashinho.pipeline.paper_market import collect_paper_market
from cashinho.pipeline.paper_performance import summarize_orders
from cashinho.pipeline.position_manager import (
    PositionDecision,
    PositionManager,
    PositionRiskState,
    apply_position_decision,
)
from cashinho.pipeline.position_monitoring import evaluate_open_position


@st.cache_data(ttl=10, show_spinner=False)
def cached_position_data(
    _provider: object,
    _clock: object,
    *,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
):
    return load_market_data(
        _provider,
        symbol=symbol,
        timeframe=Timeframe(timeframe),
        start=start,
        end=end,
        clock=_clock,
        mode=Mode.RESEARCH,
        minimum_candles=30,
    )

settings = get_settings()
clock = SystemClock()
sidebar(settings)
page_header("Paper Trading", "Ordens, posições e resultados simulados persistentes")

st.info(
    "Ambiente exclusivamente PAPER. Nenhuma ordem é enviada ao MetaTrader ou à corretora.",
    icon="🔒",
)
st.caption(
    "Aqui você acompanha posições e ordens simuladas. Use esta tela para aprender a leitura "
    "da operação sem risco de execução real."
)

choice = build_market_data_provider(
    settings, clock, fixtures_root=settings.data_dir / "fixtures"
)
render_source_banner(choice)
broker, _audit = build_paper_broker()
orders = broker.list_orders()
market = collect_paper_market(
    choice.provider,
    orders,
    clock=clock,
    max_age_seconds=settings.mt5_stale_seconds,
)

selection = IndicatorSelection(
    ema_periods=(9, 21),
    vwap=True,
    rsi_period=14,
    macd=True,
    atr_period=14,
)
manager = PositionManager()
position_decisions: dict[str, PositionDecision] = {}
monitoring_errors: list[str] = []
rounded_now = clock.now().replace(second=0, microsecond=0)
for position in [order for order in orders if order.status is PaperOrderStatus.OPEN]:
    try:
        series_by_timeframe = {}
        for timeframe in choice.provider.get_available_timeframes(position.ticket.symbol):
            loaded = cached_position_data(
                choice.provider,
                clock,
                symbol=position.ticket.symbol,
                timeframe=timeframe.value,
                start=rounded_now - timedelta(days=90),
                end=rounded_now + timedelta(minutes=1),
            )
            if loaded.usable_series is not None:
                series_by_timeframe[timeframe] = loaded.usable_series
        if not series_by_timeframe:
            monitoring_errors.append(
                f"{position.ticket.symbol}: sem candles aprovados para o Position Manager."
            )
            continue

        ticket_timeframe = (
            Timeframe(position.ticket.timeframe)
            if position.ticket.timeframe in {timeframe.value for timeframe in Timeframe}
            else min(series_by_timeframe, key=lambda item: item.duration)
        )
        order_series = series_by_timeframe.get(ticket_timeframe)
        if order_series is not None and order_series.last is not None:
            broker.process_candle(
                order_series.last,
                symbol=position.ticket.symbol,
                timeframe=ticket_timeframe.value,
            )
        refreshed = next((item for item in broker.list_orders() if item.id == position.id), None)
        if refreshed is None or refreshed.status is not PaperOrderStatus.OPEN:
            continue

        monitored = evaluate_open_position(
            refreshed,
            series_by_timeframe=series_by_timeframe,
            selection=selection,
            manager=manager,
            risk=PositionRiskState(
                settings.risk_profile().kill_switch_active,
                "Risk Manager está com kill switch ativo.",
            ),
            current_price=market.market_prices.get(position.ticket.symbol),
            market_exit_price=market.close_prices.get(position.id),
        )
        position_decisions[position.id] = monitored.decision
        _audit.record_position_decision(position.id, monitored.decision)
        apply_position_decision(broker, refreshed, monitored.decision)
    except (CashinhoError, RuntimeError, ValueError) as exc:
        monitoring_errors.append(f"{position.ticket.symbol}: {exc}")

orders = broker.list_orders()
summary = summarize_orders(
    orders,
    market_prices=market.market_prices,
    on_date=clock.now().date(),
)

st.subheader("Resumo do dia")
st.caption("Resumo financeiro e operacional das ordens PAPER do dia.")
render_paper_summary(summary)
for error in market.errors:
    st.caption(error)
for error in monitoring_errors:
    st.caption(error)

st.divider()
render_open_positions(
    broker,
    orders,
    market_prices=market.market_prices,
    close_prices=market.close_prices,
    now=clock.now(),
    position_decisions=position_decisions,
)
st.divider()
render_pending_orders(broker, orders)
st.divider()
render_closed_positions(orders)
