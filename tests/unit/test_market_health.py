from __future__ import annotations

from datetime import timedelta

from cashinho.adapters.providers.csv_provider import CsvHistoricalProvider
from cashinho.adapters.providers.factory import ProviderChoice
from cashinho.adapters.providers.metatrader import MetaTraderMarketDataProvider, MetaTraderTerminal
from cashinho.core.time.clocks import FrozenClock
from cashinho.domain.enums import Mode, Timeframe
from cashinho.pipeline.market_health import MarketHealthColor, assess_market_health
from tests.conftest import REFERENCE_INSTANT
from tests.unit.fake_mt5 import NOW, FakeMetaTrader5, quote_tick, rate, trade_tick


def test_saude_reprova_fonte_que_nao_e_mt5(tmp_path) -> None:
    clock = FrozenClock(REFERENCE_INSTANT)
    choice = ProviderChoice(
        CsvHistoricalProvider(tmp_path, clock),
        kind="csv",
        realtime=False,
        reason="teste",
    )

    health = assess_market_health(
        choice,
        symbol="PETR4",
        timeframe=Timeframe.M5,
        start=REFERENCE_INSTANT - timedelta(days=1),
        end=REFERENCE_INSTANT,
        clock=clock,
    )

    assert health.color is MarketHealthColor.RED
    assert health.blocks_signal
    assert "MT5" in health.reason


def test_saude_reprova_candle_atrasado_no_paper() -> None:
    old = NOW - timedelta(hours=3)
    library = FakeMetaTrader5(
        quote_ticks=[quote_tick(moment=NOW - timedelta(seconds=5))],
        trade_ticks=[trade_tick(moment=NOW - timedelta(seconds=5))],
        rates=[rate(180), rate(120), rate(60)],
    )
    provider = MetaTraderMarketDataProvider(
        FrozenClock(NOW),
        terminal=MetaTraderTerminal(library=library),
    )
    provider.connect()
    choice = ProviderChoice(
        provider,
        kind="metatrader",
        realtime=True,
        reason="teste",
        monitored_symbols=("PETR4",),
    )

    health = assess_market_health(
        choice,
        symbol="PETR4",
        timeframe=Timeframe.M1,
        start=old,
        end=NOW,
        clock=FrozenClock(NOW),
        mode=Mode.PAPER,
    )

    assert health.color is MarketHealthColor.RED
    assert health.blocks_signal
    assert health.data_quality is not None
    assert any(issue.code == "STALE" for issue in health.data_quality.critical_issues)
