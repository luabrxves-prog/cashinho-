"""Entrypoint do Cashinho.

    streamlit run app/main.py

Responsabilidades desta camada: configurar a pagina, montar a navegacao e
delegar. Nenhuma regra de negocio vive aqui.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Permite executar sem instalar o pacote (`pip install -e .`).
# `src` expoe o pacote `cashinho`; a raiz expoe o pacote `app`.
_ROOT = Path(__file__).resolve().parents[1]
for _path in (_ROOT / "src", _ROOT):
    if str(_path) not in sys.path:  # pragma: no cover
        sys.path.insert(0, str(_path))

import streamlit as st

from cashinho.config.settings import get_settings
from cashinho.domain.errors import ModeNotAllowedError
from cashinho.observability.logging import configure_logging, get_logger

st.set_page_config(
    page_title="Cashinho",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

settings = get_settings()
configure_logging(settings.log_level, settings.log_format)
logger = get_logger(__name__)

try:
    settings.ensure_mode_allowed()
except ModeNotAllowedError as exc:
    st.error(str(exc), icon="⛔")
    st.stop()

PAGES = [
    st.Page("pages/dashboard.py", title="Dashboard", icon="📊", default=True),
    st.Page("pages/scanner.py", title="Scanner B3", icon="🔎"),
    st.Page("pages/analise.py", title="Análise", icon="📈"),
    st.Page("pages/backtest.py", title="Backtest", icon="🧪"),
    st.Page("pages/aprendizado.py", title="Aprendizado", icon="🧠"),
    st.Page("pages/paper_trading.py", title="Paper Trading", icon="📝"),
    st.Page("pages/diario.py", title="Diário", icon="📒"),
    st.Page("pages/risk_manager.py", title="Risk Manager", icon="🛡️"),
    st.Page("pages/configuracoes.py", title="Configurações", icon="⚙️"),
    st.Page("pages/system_health.py", title="Saúde do Mercado", icon="🩺"),
]

navigation = st.navigation(PAGES, position="sidebar")
logger.debug("pagina carregada", extra={"mode": settings.mode.value})
navigation.run()
