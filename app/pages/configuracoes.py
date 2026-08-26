"""Configuracoes efetivas."""

from __future__ import annotations

import streamlit as st

from app.components.chrome import page_header, placeholder, sidebar
from cashinho.config.settings import IMPLEMENTED_MODES, get_settings

settings = get_settings()
sidebar(settings)
page_header("Configurações", "Configuracao efetiva carregada do ambiente")
st.caption(
    "Esta tela mostra quais valores o aplicativo carregou ao iniciar. Ela é somente leitura."
)

st.warning(
    "Somente leitura. A configuracao vem de variaveis de ambiente e do arquivo `.env`, "
    "que nunca e versionado.",
    icon="🔒",
)

st.table(
    {
        "Parametro": [
            "Modo",
            "Banco de dados",
            "Nivel de log",
            "Formato de log",
            "Fuso de exibicao",
            "Capital",
            "Hash da configuracao",
        ],
        "Valor": [
            settings.mode.value,
            settings.database_url,
            settings.log_level,
            settings.log_format,
            settings.display_timezone,
            f"R$ {settings.capital:,.2f}",
            settings.config_hash(),
        ],
        "O que significa": [
            "Define se o app roda para estudo, backtest ou operação controlada.",
            "Endereço usado para guardar diário, decisões e ordens PAPER.",
            "Quantidade de detalhe registrada nos logs técnicos.",
            "Formato em que os logs são escritos.",
            "Fuso usado para mostrar datas e horários na interface.",
            "Valor base para cálculos de risco.",
            "Assinatura curta da configuração carregada, útil para auditoria.",
        ],
    }
)

st.caption(f"Modos habilitados: {', '.join(sorted(m.value for m in IMPLEMENTED_MODES))}")
st.caption("Nenhuma credencial e exibida nesta tela por principio.")

st.divider()
placeholder(
    "Fase 4",
    [
        "Perfil de risco em arquivo versionado e hasheado",
        "Configuracao do modelo multi-timeframe",
        "Pesos do score em configuracao, nunca em codigo",
    ],
)
