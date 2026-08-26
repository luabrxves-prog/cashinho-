"""Card binário da FinalDecision; nenhuma regra técnica vive aqui."""

from __future__ import annotations

from decimal import Decimal

import streamlit as st

from cashinho.pipeline.final_decision import FinalDecision


def render_decision_card(
    decision: FinalDecision,
    *,
    symbol: str,
    last_price: Decimal | None,
    feed_label: str,
) -> bool:
    """Renderiza a decisão e retorna se a abertura da boleta foi solicitada."""
    header_left, header_right = st.columns(2)
    header_left.markdown(f"### {symbol}")
    header_left.caption(
        f"Timeframe analisado: **{decision.timeframe.value if decision.timeframe else '—'}**"
    )
    header_right.markdown(f"### R$ {last_price:.2f}" if last_price is not None else "### —")
    header_right.caption(feed_label)

    open_ticket = False
    with st.container(border=True):
        if decision.should_enter:
            side_label = "COMPRA" if decision.side == "BUY" else "VENDA"
            st.success(f"## 🟢 ENTRADA LIBERADA\n### {side_label}")
            entry_col, stop_col, target_col, rr_col = st.columns(4)
            entry_col.metric(
                "Entrada",
                f"R$ {decision.entry:.2f}",
                help="Preço de referência para abrir a operação PAPER.",
            )
            stop_col.metric(
                "Stop",
                f"R$ {decision.stop:.2f}",
                help="Preço em que a perda simulada seria limitada.",
            )
            target_col.metric(
                "Alvo",
                f"R$ {decision.target:.2f}",
                help="Preço em que o ganho planejado seria realizado.",
            )
            rr_col.metric(
                "R:R",
                f"{decision.risk_reward:.2f}",
                help="Relação entre ganho potencial e perda no stop. Quanto maior, melhor a folga.",
            )
            confidence_col, button_col = st.columns([1, 2])
            confidence_col.metric(
                "Confiança",
                f"{decision.confidence}/100",
                help="Pontuação interna do sinal. Não é probabilidade garantida de acerto.",
            )
            open_ticket = button_col.button(
                "ABRIR BOLETA PAPER",
                type="primary",
                use_container_width=True,
                help="Abre a boleta simulada para revisar quantidade, risco, stop e alvo antes de registrar.",
            )
        else:
            st.info("## ⚪ NÃO ENTRAR")
            st.write("Ainda não existe uma entrada válida neste momento.")
            st.write(f"**{decision.primary_reason}**")
    st.caption("Análise e execução exclusivamente PAPER.")
    return open_ticket
