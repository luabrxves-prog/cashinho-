"""Configuracao central e bloqueio de modos nao implementados."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from cashinho.config.settings import IMPLEMENTED_MODES, Settings, get_settings, reset_settings_cache
from cashinho.domain.enums import Mode
from cashinho.domain.errors import ModeNotAllowedError


def _settings(**kwargs: object) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_modo_padrao_e_paper() -> None:
    assert _settings().mode is Mode.PAPER


def test_mt5_fica_ligado_por_padrao() -> None:
    assert _settings().mt5_enabled is True


def test_lista_monitorada_aceita_texto_com_virgulas() -> None:
    settings = _settings(monitored_symbols="petr4, vale3, itub4")
    assert settings.monitored_symbols == ("PETR4", "VALE3", "ITUB4")


@pytest.mark.parametrize("mode", [Mode.LIVE, Mode.ASSISTED])
def test_modos_com_ordem_real_sao_recusados(mode: Mode) -> None:
    settings = _settings(mode=mode)
    assert not settings.mode_is_implemented
    with pytest.raises(ModeNotAllowedError, match="nao esta implementado"):
        settings.ensure_mode_allowed()


@pytest.mark.parametrize("mode", sorted(IMPLEMENTED_MODES))
def test_modos_implementados_sao_aceitos(mode: Mode) -> None:
    assert _settings(mode=mode).ensure_mode_allowed() is mode


def test_live_nao_esta_entre_os_modos_implementados() -> None:
    assert Mode.LIVE not in IMPLEMENTED_MODES
    assert Mode.ASSISTED not in IMPLEMENTED_MODES


def test_log_level_invalido_e_rejeitado() -> None:
    with pytest.raises(ValueError, match="log_level invalido"):
        _settings(log_level="VERBOSO")


def test_log_level_e_normalizado() -> None:
    assert _settings(log_level="debug").log_level == "DEBUG"


def test_formato_de_log_invalido_e_rejeitado() -> None:
    with pytest.raises(ValueError):
        _settings(log_format="xml")


def test_hash_da_configuracao_e_estavel() -> None:
    assert _settings().config_hash() == _settings().config_hash()


def test_hash_muda_com_o_capital() -> None:
    a = _settings(capital=Decimal("100000.00")).config_hash()
    b = _settings(capital=Decimal("200000.00")).config_hash()
    assert a != b


def test_hash_muda_com_o_modo() -> None:
    a = _settings(mode=Mode.PAPER).config_hash()
    b = _settings(mode=Mode.BACKTEST).config_hash()
    assert a != b


def test_perfil_de_risco_usa_o_capital_configurado() -> None:
    profile = _settings(capital=Decimal("50000.00")).risk_profile()
    assert profile.capital == Decimal("50000.00")


def test_settings_e_imutavel() -> None:
    settings = _settings()
    with pytest.raises(ValidationError):
        settings.mode = Mode.LIVE


def test_get_settings_usa_cache() -> None:
    reset_settings_cache()
    assert get_settings() is get_settings()
    reset_settings_cache()
