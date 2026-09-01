"""Confluencia entre series independentes de múltiplos timeframes."""

from __future__ import annotations

from dataclasses import dataclass

from cashinho.domain.enums import Timeframe
from cashinho.domain.market import CandleSeries
from cashinho.pipeline.entry_signal import EntrySignal, evaluate_entry_signal
from cashinho.pipeline.indicators import IndicatorSelection, compute_panel
from cashinho.pipeline.market_regime import RegimeAnalysis, analyze_market_regime
from cashinho.pipeline.trade_setup import TradeSetup, classify_trade_setup

TIMEFRAME_ORDER = (Timeframe.D1, Timeframe.H1, Timeframe.M15, Timeframe.M5, Timeframe.M1)


@dataclass(frozen=True, slots=True)
class TimeframeAnalysis:
    timeframe: Timeframe
    regime: RegimeAnalysis
    signal: EntrySignal
    setup: TradeSetup | None = None


@dataclass(frozen=True, slots=True)
class TimeframeAdvice:
    recommended_timeframe: Timeframe | None
    context_timeframes: tuple[Timeframe, ...]
    trigger_timeframe: Timeframe | None
    score: int
    side: str
    reasons: tuple[str, ...]
    rejection_reason: str | None = None


def analyze_timeframes(
    series_by_timeframe: dict[Timeframe, CandleSeries],
    selection: IndicatorSelection,
) -> dict[Timeframe, TimeframeAnalysis]:
    analyses: dict[Timeframe, TimeframeAnalysis] = {}
    for timeframe, raw_series in series_by_timeframe.items():
        closed = raw_series.closed_only()
        if closed.timeframe is not timeframe:
            raise ValueError("Serie associada ao timeframe incorreto.")
        panel = compute_panel(closed, selection)
        regime = analyze_market_regime(closed)
        signal = evaluate_entry_signal(closed, panel)
        analyses[timeframe] = TimeframeAnalysis(
            timeframe,
            regime,
            signal,
            classify_trade_setup(closed, panel, regime, signal),
        )
    return analyses


def advise_timeframe(analyses: dict[Timeframe, TimeframeAnalysis]) -> TimeframeAdvice:
    available = [tf for tf in TIMEFRAME_ORDER if tf in analyses]
    if len(available) < 2:
        return TimeframeAdvice(
            None,
            tuple(available),
            None,
            0,
            "NONE",
            (),
            "Timeframes insuficientes para confluência.",
        )

    macro = [tf for tf in (Timeframe.D1, Timeframe.H1) if tf in analyses]
    macro_directions = [
        analyses[tf].regime.direction for tf in macro if analyses[tf].regime.direction != "NONE"
    ]
    if not macro_directions or len(set(macro_directions)) > 1:
        return TimeframeAdvice(
            None,
            tuple(macro),
            None,
            20,
            "NONE",
            ("Contexto macro sem direção comum.",),
            "Conflito macro.",
        )
    side = macro_directions[0]
    candidates = [tf for tf in (Timeframe.M15, Timeframe.M5, Timeframe.M1) if tf in analyses]
    aligned = [tf for tf in candidates if analyses[tf].regime.direction in {side, "NONE"}]
    conflicts = [tf for tf in candidates if analyses[tf].regime.direction not in {side, "NONE"}]
    if conflicts:
        return TimeframeAdvice(
            None,
            tuple(macro),
            min(candidates, key=lambda tf: tf.duration),
            35,
            side,
            ("Timeframe operacional conflita com o macro.",),
            "Alinhamento multi-timeframe insuficiente.",
        )
    if not aligned:
        return TimeframeAdvice(None, tuple(macro), None, 30, side, (), "Sem timeframe operacional.")

    recommended = max(aligned, key=lambda tf: analyses[tf].signal.score)
    lower = [tf for tf in aligned if tf.duration < recommended.duration]
    trigger = max(lower, key=lambda tf: tf.duration) if lower else recommended
    signal = analyses[recommended].signal
    score = min(
        100,
        int(
            (signal.score + sum(analyses[tf].regime.confidence for tf in macro)) / (len(macro) + 1)
        ),
    )
    rejection = None if score >= 60 else "Score multi-timeframe abaixo do mínimo."
    return TimeframeAdvice(
        recommended if rejection is None else None,
        tuple(macro),
        trigger,
        score,
        side,
        ("Contexto macro alinhado.", "Timeframe operacional sem conflito."),
        rejection,
    )
