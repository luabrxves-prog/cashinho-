"""Tabelas e comandos explícitos das ordens PAPER."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import streamlit as st

from cashinho.pipeline.paper_broker import PaperBroker, PaperOrder, PaperOrderStatus
from cashinho.pipeline.paper_performance import realized_pnl, unrealized_pnl
from cashinho.pipeline.position_manager import PositionAction, PositionDecision


def _opened_rows(
    orders: list[PaperOrder],
    market_prices: dict[str, Decimal],
    position_decisions: dict[str, PositionDecision] | None = None,
) -> list[dict[str, Any]]:
    position_decisions = position_decisions or {}
    rows: list[dict[str, Any]] = []
    for order in orders:
        result = unrealized_pnl(order, market_prices.get(order.ticket.symbol))
        rows.append(
            {
                "Ativo": order.ticket.symbol,
                "Lado": order.ticket.side,
                "Quantidade": order.ticket.quantity,
                "Entrada": order.fill_price,
                "Preço atual": market_prices.get(order.ticket.symbol),
                "Stop": order.ticket.stop,
                "Alvo": order.ticket.target,
                "P&L atual": result.pnl_value if result else None,
                "R atual": result.result_in_r if result else None,
                "Decisão": (
                    "SAIR"
                    if position_decisions.get(order.id) is not None
                    and position_decisions[order.id].action is PositionAction.EXIT
                    else "MANTER"
                    if position_decisions.get(order.id) is not None
                    else "—"
                ),
                "Abertura (UTC)": order.filled_at,
            }
        )
    return rows


def _pending_rows(orders: list[PaperOrder]) -> list[dict[str, Any]]:
    return [
        {
            "Ativo": order.ticket.symbol,
            "Lado": order.ticket.side,
            "Tipo": order.order_type.value,
            "Quantidade": order.ticket.quantity,
            "Entrada": order.ticket.entry,
            "Stop": order.ticket.stop,
            "Alvo": order.ticket.target,
            "Horário (UTC)": order.created_at,
            "Status": order.status.value,
        }
        for order in orders
    ]


def _closed_rows(orders: list[PaperOrder]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for order in orders:
        result = realized_pnl(order)
        rows.append(
            {
                "Ativo": order.ticket.symbol,
                "Lado": order.ticket.side,
                "Entrada": order.fill_price,
                "Saída": order.close_price,
                "Quantidade": order.ticket.quantity,
                "Resultado R$": result.pnl_value if result else None,
                "Resultado %": result.pnl_pct if result else None,
                "Resultado em R": result.result_in_r if result else None,
                "Motivo": order.close_reason,
                "Duração": str(result.duration) if result and result.duration else None,
            }
        )
    return rows


def render_open_positions(
    broker: PaperBroker,
    orders: list[PaperOrder],
    *,
    market_prices: dict[str, Decimal],
    close_prices: dict[str, Decimal],
    now: datetime,
    position_decisions: dict[str, PositionDecision] | None = None,
) -> None:
    opened = [order for order in orders if order.status is PaperOrderStatus.OPEN]
    st.subheader("Posições abertas")
    st.caption(
        "Posições PAPER que ainda estão em andamento. O fechamento manual também é apenas simulado."
    )
    if not opened:
        st.info("Nenhuma posição PAPER aberta.")
        return
    st.dataframe(
        _opened_rows(opened, market_prices, position_decisions),
        use_container_width=True,
        hide_index=True,
    )
    selected = st.selectbox(
        "Posição para encerrar",
        opened,
        format_func=lambda order: f"{order.id[:8]} · {order.ticket.symbol} · {order.ticket.side}",
        key="paper_close_position",
        help="Escolha qual posição PAPER será encerrada manualmente pelo preço disponível.",
    )
    price = close_prices.get(selected.id)
    if price is None:
        st.warning("Encerramento bloqueado: a fonte não possui bid/ask ativo para esta posição.")
    elif st.button(
        "Fechar posição PAPER manualmente",
        key="paper_close_button",
        help="Registra um fechamento simulado. Nenhuma ordem real é enviada ao mercado.",
    ):
        broker.close_position(selected.id, price=price, closed_at=now)
        st.success(f"Posição {selected.id[:8]} encerrada a {price} no ambiente PAPER.")
        st.rerun()


def render_pending_orders(broker: PaperBroker, orders: list[PaperOrder]) -> None:
    pending = [order for order in orders if order.status is PaperOrderStatus.PENDING]
    st.subheader("Ordens pendentes")
    st.caption("Ordens PAPER criadas, mas ainda sem execução simulada.")
    if not pending:
        st.info("Nenhuma ordem PAPER pendente.")
        return
    st.dataframe(_pending_rows(pending), use_container_width=True, hide_index=True)
    selected = st.selectbox(
        "Ordem para cancelar",
        pending,
        format_func=lambda order: f"{order.id[:8]} · {order.ticket.symbol} · {order.ticket.side}",
        key="paper_cancel_pending",
        help="Escolha qual ordem PAPER pendente será cancelada.",
    )
    if st.button(
        "Cancelar ordem PENDING",
        key="paper_cancel_pending_button",
        help="Cancela a ordem simulada antes de ela ser executada no ambiente PAPER.",
    ):
        broker.cancel_order(selected.id)
        st.success(f"Ordem PAPER {selected.id[:8]} cancelada.")
        st.rerun()


def render_closed_positions(orders: list[PaperOrder]) -> None:
    terminal = {
        PaperOrderStatus.CLOSED,
        PaperOrderStatus.STOPPED,
        PaperOrderStatus.TARGETED,
    }
    closed = [order for order in orders if order.status in terminal]
    st.subheader("Operações encerradas")
    st.caption("Histórico das operações PAPER já finalizadas por stop, alvo ou fechamento manual.")
    if not closed:
        st.info("Nenhuma operação PAPER encerrada.")
        return
    st.dataframe(_closed_rows(closed), use_container_width=True, hide_index=True)
