"""Visualizacao e comandos das ordens persistidas pelo Paper Broker."""

from __future__ import annotations

from typing import Any

import streamlit as st

from cashinho.pipeline.paper_broker import PaperBroker, PaperOrder, PaperOrderStatus


def order_rows(orders: list[PaperOrder]) -> list[dict[str, Any]]:
    return [
        {
            "ID": order.id[:8],
            "Ativo": order.ticket.symbol,
            "Lado": order.ticket.side,
            "Tipo": order.order_type.value,
            "Quantidade": order.ticket.quantity,
            "Entrada": float(order.ticket.entry),
            "Stop": float(order.ticket.stop),
            "Alvo": float(order.ticket.target),
            "Status": order.status.value,
            "Criada em (UTC)": order.created_at.isoformat(),
            "Executada em (UTC)": order.filled_at.isoformat() if order.filled_at else None,
            "Preço de execução": float(order.fill_price) if order.fill_price else None,
            "Preço de fechamento": float(order.close_price) if order.close_price else None,
            "Motivo do fechamento": order.close_reason,
        }
        for order in orders
    ]


def render_paper_orders(broker: PaperBroker, *, expanded: bool = False) -> None:
    orders = broker.list_orders()
    with st.expander(f"📋 Ordens PAPER ({len(orders)})", expanded=expanded):
        st.caption(
            "Lista das ordens simuladas. Elas existem apenas no Paper Broker do app."
        )
        if not orders:
            st.caption("Nenhuma ordem PAPER registrada.")
            return
        st.dataframe(order_rows(orders), use_container_width=True, hide_index=True)

        pending = [order for order in orders if order.status is PaperOrderStatus.PENDING]
        if pending:
            selected = st.selectbox(
                "Ordem pendente para cancelar",
                options=pending,
                format_func=lambda order: (
                    f"{order.id[:8]} · {order.ticket.symbol} · "
                    f"{order.ticket.side} {order.ticket.quantity}"
                ),
                key="paper_cancel_order",
                help="Escolha qual ordem PAPER pendente será cancelada.",
            )
            if st.button(
                "Cancelar ordem PENDING",
                key="paper_cancel_button",
                help="Cancela apenas a ordem simulada, sem qualquer envio ao MT5 ou corretora.",
            ):
                broker.cancel_order(selected.id)
                st.success(f"Ordem PAPER {selected.id[:8]} cancelada.")
                st.rerun()
