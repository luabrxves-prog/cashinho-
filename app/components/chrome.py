"""Elementos visuais compartilhados entre as paginas.

A UI e camada fina (decisao D1): renderiza objetos ja decididos pelo core
e nao contem regra de negocio.
"""

from __future__ import annotations

import streamlit as st

from app.components.theme import apply_app_theme
from cashinho.config.settings import Settings, get_settings
from cashinho.domain.enums import Mode
from cashinho.version import __version__

_MODE_COLORS: dict[Mode, str] = {
    Mode.RESEARCH: "#5B8DEF",
    Mode.BACKTEST: "#7C5BEF",
    Mode.REPLAY: "#8A8F98",
    Mode.PAPER: "#1F9D55",
    Mode.ASSISTED: "#D97706",
    Mode.LIVE: "#DC2626",
}


def mode_badge(settings: Settings | None = None) -> None:
    """Indicador permanente do modo de operacao.

    Fica visivel em todas as paginas. O modo determina se uma acao pode
    tocar dinheiro real; deixa-lo implicito seria um risco operacional.
    """
    settings = settings or get_settings()
    color = _MODE_COLORS.get(settings.mode, "#8A8F98")
    st.markdown(
        f"""
        <div class="cashinho-mode-badge" style="--cashinho-mode-color:{color};">
          <div class="cashinho-mode-badge__label">Modo</div>
          <div class="cashinho-mode-badge__value">{settings.mode.value}</div>
          <div class="cashinho-mode-badge__note">
            execucao real de ordens desativada
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def sidebar(settings: Settings | None = None) -> None:
    """Barra lateral com modo, versao e origem da configuracao."""
    settings = settings or get_settings()
    apply_app_theme()
    with st.sidebar:
        mode_badge(settings)
        st.caption(f"Cashinho v{__version__}")
        st.caption(f"config `{settings.config_hash()}`")
        st.caption(f"fuso de exibicao: {settings.display_timezone}")
        if settings.mode.touches_real_money:
            st.error("Modo com potencial de ordem real. Nao implementado.", icon="⛔")


def page_header(title: str, subtitle: str = "") -> None:
    """Cabecalho padrao de pagina."""
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def placeholder(fase: str, itens: list[str], *, nota: str = "") -> None:
    """Bloco padrao para funcionalidade ainda nao implementada.

    Declara explicitamente o que falta. Uma tela vazia sem essa marcacao
    seria indistinguivel de uma funcionalidade quebrada.
    """
    st.info(f"Nao implementado. Previsto para a **{fase}**.", icon="🚧")
    st.markdown("**Escopo previsto:**")
    for item in itens:
        st.markdown(f"- {item}")
    if nota:
        st.caption(nota)
