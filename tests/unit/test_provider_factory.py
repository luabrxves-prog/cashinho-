from __future__ import annotations

from cashinho.adapters.providers.factory import build_market_data_provider
from cashinho.config.settings import Settings
from cashinho.core.time.clocks import FrozenClock
from tests.conftest import REFERENCE_INSTANT


def test_metatrader_usa_lista_monitorada_configurada() -> None:
    settings = Settings(
        _env_file=None,
        mt5_enabled=True,
        monitored_symbols=("PETR4", "VALE3"),
    )

    choice = build_market_data_provider(settings, FrozenClock(REFERENCE_INSTANT))

    assert choice.is_metatrader
    assert choice.offered_symbols() == ("PETR4", "VALE3")
