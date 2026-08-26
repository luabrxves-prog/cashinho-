"""Telas com o MetaTrader habilitado, mas sem terminal disponivel.

Este e o cenario mais provavel em desenvolvimento: a configuracao aponta para
o MT5 e a maquina nao tem o terminal (Linux, CI, ou Windows com o programa
fechado). A tela precisa **dizer o que houve** e seguir legivel - nunca
quebrar, e nunca trocar por dado historico fingindo que e mercado.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from cashinho.config.settings import reset_settings_cache

PAGES_DIR = Path(__file__).resolve().parents[2] / "app" / "pages"


@pytest.fixture
def com_metatrader(monkeypatch: pytest.MonkeyPatch) -> None:
    """Liga o MT5 na configuracao do processo, sem terminal por tras."""
    monkeypatch.setenv("CASHINHO_MT5_ENABLED", "true")
    monkeypatch.setenv(
        "CASHINHO_MT5_TERMINAL_PATH",
        r"C:\__cashinho_terminal_inexistente__\terminal64.exe",
    )
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_system_health_declara_metatrader_indisponivel(com_metatrader: None) -> None:
    app = AppTest.from_file(str(PAGES_DIR / "system_health.py"), default_timeout=60).run()

    assert not app.exception, [str(e) for e in app.exception]
    erros = " ".join(e.value for e in app.error)
    assert "METATRADER NAO DISPONIVEL" in erros or "TERMINAL OFFLINE" in erros


def test_system_health_nao_expoe_dado_da_conta(com_metatrader: None) -> None:
    app = AppTest.from_file(str(PAGES_DIR / "system_health.py"), default_timeout=60).run()

    texto = " ".join(
        [e.value for e in app.error] + [m.value for m in app.markdown]
        + [c.value for c in app.caption]
    )
    assert "login" not in texto.lower()
    assert "saldo" not in texto.lower()


def test_dashboard_mostra_a_fonte_em_vez_de_placeholder(com_metatrader: None) -> None:
    """O placeholder da Fase 5 nao pode esconder informacao que ja existe."""
    app = AppTest.from_file(str(PAGES_DIR / "dashboard.py"), default_timeout=60).run()

    assert not app.exception, [str(e) for e in app.exception]
    rotulos = [m.label for m in app.metric]
    assert "Provider" in rotulos
    assert "Tempo real" in rotulos


def test_analise_nao_quebra_sem_terminal(com_metatrader: None) -> None:
    """Feed ausente para a tela com motivo; nao derruba a aplicacao."""
    app = AppTest.from_file(str(PAGES_DIR / "analise.py"), default_timeout=60).run()

    assert not app.exception, [str(e) for e in app.exception]
    erros = " ".join(e.value for e in app.error)
    assert "TERMINAL OFFLINE" in erros or "METATRADER NAO DISPONIVEL" in erros


def test_analise_nao_cai_para_csv_quando_o_feed_falha(com_metatrader: None) -> None:
    """Sem fallback silencioso: nada de grafico historico passando por realtime."""
    app = AppTest.from_file(str(PAGES_DIR / "analise.py"), default_timeout=60).run()

    assert len(app.get("plotly_chart")) == 0


def test_com_csv_a_analise_continua_desenhando(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configuracao sem MT5 segue funcionando como antes.

    Declara o proprio ambiente em vez de herdar: o teste descreve a
    configuracao CSV, e nao pode depender de como a maquina esta configurada.
    """
    monkeypatch.setenv("CASHINHO_MT5_ENABLED", "false")
    reset_settings_cache()

    if not (PAGES_DIR.parents[1] / "data" / "fixtures" / "PETR4" / "5m.csv").is_file():
        pytest.skip("fixtures nao geradas; rode scripts/generate_fixtures.py")

    app = AppTest.from_file(str(PAGES_DIR / "analise.py"), default_timeout=90).run()
    assert not app.exception

    app.selectbox[0].select("PETR4")
    app.selectbox[1].select("15m")
    app.button[0].click().run()

    assert len(app.get("plotly_chart")) == 1
    reset_settings_cache()
