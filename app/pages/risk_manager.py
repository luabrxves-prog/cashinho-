"""Risk Manager — limites vigentes."""

from __future__ import annotations

import streamlit as st

from app.components.chrome import page_header, placeholder, sidebar
from cashinho.config.settings import get_settings

settings = get_settings()
profile = settings.risk_profile()
sidebar(settings)
page_header(
    "Risk Manager",
    "O Risk Manager tem autoridade superior a estrategia. Uma rejeicao de risco nao pode ser sobrescrita.",
)
st.info(
    "Conta inicial configurada para **R$ 100,00**. O Cashinho dimensiona a boleta pelo "
    "dinheiro disponível agora: se o stop de 1 ação passar do limite, a entrada fica bloqueada.",
    icon="❔",
)

if profile.kill_switch_active:
    st.error("KILL SWITCH ATIVO — nenhuma nova operacao sera aprovada.", icon="⛔")
else:
    st.success("Kill switch inativo.", icon="✅")

st.subheader("Limites vigentes")
st.caption(
    "Esses limites são as travas de segurança que a estratégia precisa respeitar antes de liberar entrada."
)
col1, col2, col3 = st.columns(3)
col1.metric(
    "Capital",
    f"R$ {profile.capital:,.2f}",
    help="Base financeira usada para calcular risco e tamanho máximo das operações.",
)
col1.metric(
    "Risco por operacao",
    f"{profile.risk_per_trade_pct}%",
    help=(
        "Percentual máximo do capital que uma única operação pode perder no stop. "
        "Com R$100 e 2%, o limite é R$2 por tentativa."
    ),
)
col1.metric(
    "Risco monetario por operacao",
    f"R$ {profile.monetary_risk_per_trade:,.2f}",
    help="Valor em reais correspondente ao risco máximo por operação.",
)

col2.metric(
    "Perda diaria maxima",
    f"{profile.max_daily_loss_pct}%",
    help="Limite de perda no dia antes de bloquear novas entradas.",
)
col2.metric(
    "Drawdown maximo",
    f"{profile.max_drawdown_pct}%",
    help="Queda máxima permitida em relação ao capital antes de acionar proteção.",
)
col2.metric(
    "R:R minimo",
    f"{profile.min_risk_reward}",
    help="Relação mínima entre ganho esperado e perda no stop para aceitar uma operação.",
)

col3.metric(
    "Trades por dia",
    profile.max_trades_per_day,
    help="Quantidade máxima de operações permitidas em um mesmo dia.",
)
col3.metric(
    "Perdas consecutivas",
    profile.max_consecutive_losses,
    help="Número de perdas seguidas aceito antes de bloquear novas operações.",
)
col3.metric(
    "Posicoes abertas",
    profile.max_open_positions,
    help="Quantidade máxima de posições simultâneas permitidas.",
)

st.divider()
placeholder(
    "Fase 4",
    [
        "Avaliacao das regras contra o estado real do dia",
        "Consumo acumulado de perda diaria, exposicao e numero de operacoes",
        "Dimensionamento de posicao derivado do risco, com a restricao limitante nomeada",
        "Acionamento manual e automatico do kill switch",
    ],
    nota="Os valores acima vem da configuracao, ainda nao do estado operacional.",
)
