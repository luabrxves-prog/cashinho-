from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd

from cashinho.core.indicators import IndicatorResult
from cashinho.domain.enums import Timeframe
from cashinho.domain.market import Candle, CandleSeries
from cashinho.pipeline.entry_signal import EntrySignal
from cashinho.pipeline.indicators import IndicatorPanel
from cashinho.pipeline.market_regime import MarketRegime, RegimeAnalysis
from cashinho.pipeline.trade_setup import TradeSetupType, classify_trade_setup


def _series(*, last_close: str = "12.10", last_volume: int = 5000) -> CandleSeries:
    start = datetime(2026, 8, 20, 10, tzinfo=UTC)
    candles = []
    for index in range(30):
        base = Decimal("10") + Decimal(index) / Decimal("10")
        close = Decimal(last_close) if index == 29 else base + Decimal("0.05")
        candles.append(
            Candle(
                open_time=start + timedelta(minutes=5 * index),
                close_time=start + timedelta(minutes=5 * (index + 1)),
                open=base,
                high=max(base + Decimal("0.20"), close),
                low=min(base - Decimal("0.20"), close),
                close=close,
                volume=last_volume if index == 29 else 1000,
            )
        )
    return CandleSeries(
        symbol="PETR4",
        timeframe=Timeframe.M5,
        candles=tuple(candles),
        source="test",
        fetched_at=start + timedelta(minutes=151),
    )


def _panel(rsi: float = 60) -> IndicatorPanel:
    return IndicatorPanel(
        oscillators={
            "RSI(14)": IndicatorResult(
                name="rsi",
                symbol="PETR4",
                timeframe=Timeframe.M5,
                values=pd.DataFrame({"rsi": [rsi]}),
                warmup=0,
            )
        }
    )


def _regime(regime: MarketRegime, direction: str) -> RegimeAnalysis:
    return RegimeAnalysis(regime, 80, direction, 80, "TEST", "NORMAL", (), {})


def _signal(side: str = "BUY", confirmed: bool = True) -> EntrySignal:
    return EntrySignal(side, "ENTRADA LIBERADA", 90, Decimal("10"), Decimal("9"), Decimal("12"), 2.0, (), confirmed)


def test_classifica_continuacao_de_tendencia() -> None:
    setup = classify_trade_setup(
        _series(),
        _panel(),
        _regime(MarketRegime.TREND_UP, "BUY"),
        _signal("BUY"),
    )

    assert setup.kind is TradeSetupType.TREND_CONTINUATION
    assert setup.approved


def test_classifica_reversao_de_range_na_extremidade() -> None:
    setup = classify_trade_setup(
        _series(last_close="10.05", last_volume=1000),
        _panel(rsi=35),
        _regime(MarketRegime.RANGE, "NONE"),
        _signal("BUY", confirmed=False),
    )

    assert setup.kind is TradeSetupType.RANGE_REVERSION
    assert setup.side == "BUY"


def test_vocabulario_de_setups_inclui_contextos_operacionais() -> None:
    assert TradeSetupType.PULLBACK_TREND.value == "PULLBACK_TREND"
    assert TradeSetupType.BREAKOUT_RETEST.value == "BREAKOUT_RETEST"
    assert TradeSetupType.OPENING_RANGE_EXPANSION.value == "OPENING_RANGE_EXPANSION"
    assert TradeSetupType.VWAP_REVERSION.value == "VWAP_REVERSION"
    assert TradeSetupType.SUPPORT_RESISTANCE_REVERSAL.value == "SUPPORT_RESISTANCE_REVERSAL"
    assert TradeSetupType.CONSOLIDATION_CONTINUATION.value == "CONSOLIDATION_CONTINUATION"
