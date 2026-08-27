from __future__ import annotations

from decimal import Decimal

from cashinho.domain.enums import Timeframe
from cashinho.pipeline.entry_signal import EntrySignal
from cashinho.pipeline.market_regime import MarketRegime, RegimeAnalysis
from cashinho.pipeline.multi_timeframe import TimeframeAnalysis
from cashinho.pipeline.study_mode import build_market_study, market_direction


def analysis(timeframe: Timeframe, direction: str) -> TimeframeAnalysis:
    regime = MarketRegime.TREND_UP if direction == "BUY" else MarketRegime.TREND_DOWN
    return TimeframeAnalysis(
        timeframe,
        RegimeAnalysis(regime, 80, direction, 80, "TREND", "NORMAL", (), {}),
        EntrySignal(
            direction,
            "ENTRADA LIBERADA",
            80,
            Decimal("10"),
            Decimal("9") if direction == "BUY" else Decimal("11"),
            Decimal("12") if direction == "BUY" else Decimal("8"),
            2.0,
            (),
            True,
        ),
    )


def test_direcao_macro_usa_timeframes_altos() -> None:
    analyses = {
        Timeframe.H1: analysis(Timeframe.H1, "BUY"),
        Timeframe.M5: analysis(Timeframe.M5, "SELL"),
    }
    assert market_direction(analyses) == "BUY"


def test_estudo_profundo_aprova_quando_mercado_apoia_lado() -> None:
    report = build_market_study(
        {
            "A": {Timeframe.H1: analysis(Timeframe.H1, "BUY")},
            "B": {Timeframe.H1: analysis(Timeframe.H1, "BUY")},
            "C": {Timeframe.H1: analysis(Timeframe.H1, "SELL")},
        },
        side="BUY",
    )
    assert report.approved
    assert report.bias == "BUY"
    assert report.aligned_symbols == 2


def test_estudo_profundo_bloqueia_lado_contra_o_mercado() -> None:
    report = build_market_study(
        {
            "A": {Timeframe.H1: analysis(Timeframe.H1, "SELL")},
            "B": {Timeframe.H1: analysis(Timeframe.H1, "SELL")},
            "C": {Timeframe.H1: analysis(Timeframe.H1, "BUY")},
        },
        side="BUY",
    )
    assert not report.approved
    assert "oposto" in report.reason
