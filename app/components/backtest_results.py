"""Renderização de BacktestResult, sem regras de estratégia."""

from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

from cashinho.pipeline.backtest import BacktestComparison, BacktestResult, metrics_by


def _value(value: object, suffix: str = "") -> str:
    return "—" if value is None else f"{value}{suffix}"


def render_backtest_result(result: BacktestResult, *, initial_capital: object) -> None:
    metrics = result.metrics
    cards = st.columns(6)
    cards[0].metric(
        "Trades",
        metrics.total_trades,
        help="Quantidade de operações concluídas neste recorte do backtest.",
    )
    cards[1].metric(
        "Win rate",
        _value(metrics.win_rate, "%"),
        help="Percentual de operações vencedoras. Sozinho, não mede qualidade da estratégia.",
    )
    cards[2].metric(
        "Profit factor",
        _value(metrics.profit_factor),
        help="Relação entre lucro bruto e perda bruta. Acima de 1 indica lucro bruto maior que perda bruta.",
    )
    cards[3].metric(
        "Expectancy",
        _value(metrics.expectancy),
        help="Resultado médio esperado por operação no histórico simulado.",
    )
    cards[4].metric(
        "Resultado",
        f"R$ {metrics.net_profit:,.2f}",
        help="Lucro ou prejuízo final da simulação depois dos custos informados.",
    )
    cards[5].metric(
        "Max drawdown",
        f"R$ {metrics.max_drawdown:,.2f}",
        help="Maior queda observada na curva de capital durante o período.",
    )

    if not result.trades:
        st.info("Nenhuma FinalDecision liberou e concluiu uma operação neste recorte.")
        return

    chart_left, chart_right = st.columns(2)
    equity = pd.DataFrame(result.equity_curve, columns=["Data", "Capital"]).set_index("Data")
    drawdown = pd.DataFrame(result.drawdown_curve, columns=["Data", "Drawdown %"]).set_index(
        "Data"
    )
    chart_left.markdown("#### Curva de capital")
    chart_left.caption("Evolução simulada do capital ao longo dos trades.")
    chart_left.line_chart(equity)
    chart_right.markdown("#### Drawdown")
    chart_right.caption("Queda percentual desde o topo anterior da curva.")
    chart_right.line_chart(drawdown)

    rows = [
        {
            "Ativo": trade.symbol,
            "Lado": trade.side,
            "TF": trade.timeframe.value,
            "Entrada": trade.entry_price,
            "Saída": trade.exit_price,
            "Qtd": trade.quantity,
            "Motivo": trade.close_reason,
            "P&L": trade.net_pnl,
            "R": trade.result_in_r,
            "Custos": trade.costs,
            "Entrada em": trade.entered_at,
            "Saída em": trade.exited_at,
        }
        for trade in result.trades
    ]
    st.markdown("#### Trades")
    st.caption("Lista operação por operação, com entrada, saída, resultado e custos.")
    st.dataframe(rows, use_container_width=True, hide_index=True)

    reasons = Counter(trade.close_reason for trade in result.trades)
    st.markdown("#### Encerramentos por motivo")
    st.caption("Mostra se as saídas ocorreram por stop, alvo, posição gerenciada ou outro motivo.")
    st.dataframe(
        [
            {
                "Motivo": reason,
                "Trades": count,
                "Participação": f"{count / len(result.trades) * 100:.1f}%",
            }
            for reason, count in reasons.most_common()
        ],
        use_container_width=True,
        hide_index=True,
    )

    side_metrics = metrics_by(result.trades, initial_capital=initial_capital, field="side")
    timeframe_metrics = metrics_by(
        result.trades, initial_capital=initial_capital, field="timeframe"
    )
    side_col, timeframe_col = st.columns(2)
    side_col.markdown("#### Por BUY/SELL")
    side_col.caption("Resultado separado por lado da operação: compra ou venda.")
    side_col.dataframe(
        [
            {
                "Lado": key,
                "Trades": value.total_trades,
                "Win rate": value.win_rate,
                "Profit factor": value.profit_factor,
                "Expectancy": value.expectancy,
            }
            for key, value in side_metrics.items()
        ],
        hide_index=True,
        use_container_width=True,
    )
    timeframe_col.markdown("#### Por timeframe")
    timeframe_col.caption("Resultado separado pelo tempo gráfico que originou o sinal.")
    timeframe_col.dataframe(
        [
            {
                "Timeframe": key,
                "Trades": value.total_trades,
                "Win rate": value.win_rate,
                "Profit factor": value.profit_factor,
                "Expectancy": value.expectancy,
            }
            for key, value in timeframe_metrics.items()
        ],
        hide_index=True,
        use_container_width=True,
    )


def render_backtest_comparison(
    comparison: BacktestComparison, *, initial_capital: object
) -> None:
    """Compara sem atribuir superioridade prévia à saída dinâmica."""

    rows = []
    for label, result in (
        ("A · STOP + TARGET", comparison.fixed),
        ("B · + POSITION MANAGER", comparison.dynamic),
    ):
        metrics = result.metrics
        rows.append(
            {
                "Modo": label,
                "Trades": metrics.total_trades,
                "Expectancy": metrics.expectancy,
                "Profit factor": metrics.profit_factor,
                "Drawdown R$": metrics.max_drawdown,
                "Resultado em R": metrics.total_r,
                "Resultado R$": metrics.net_profit,
            }
        )
    st.markdown("### Comparação das formas de saída")
    st.caption(
        "Compara a saída simples por stop/alvo com a saída que usa o Position Manager."
    )
    st.dataframe(rows, use_container_width=True, hide_index=True)
    fixed_tab, dynamic_tab = st.tabs(["MODO A", "MODO B"])
    with fixed_tab:
        st.caption("Modo A encerra operações apenas por stop e alvo planejados.")
        render_backtest_result(comparison.fixed, initial_capital=initial_capital)
    with dynamic_tab:
        st.caption("Modo B permite que o Position Manager antecipe ou mantenha a saída.")
        render_backtest_result(comparison.dynamic, initial_capital=initial_capital)
