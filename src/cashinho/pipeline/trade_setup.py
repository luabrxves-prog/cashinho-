"""Classificacao de setup tecnico antes da decisao final."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from cashinho.domain.market import Candle, CandleSeries
from cashinho.pipeline.entry_signal import EntrySignal
from cashinho.pipeline.fibonacci import fibonacci_confluence
from cashinho.pipeline.indicators import IndicatorPanel
from cashinho.pipeline.market_regime import MarketRegime, RegimeAnalysis


class TradeSetupType(StrEnum):
    TREND_CONTINUATION = "TREND_CONTINUATION"
    PULLBACK_TREND = "PULLBACK_TREND"
    EXPANSION_BREAKOUT = "EXPANSION_BREAKOUT"
    BREAKOUT_RETEST = "BREAKOUT_RETEST"
    OPENING_RANGE_EXPANSION = "OPENING_RANGE_EXPANSION"
    RANGE_REVERSION = "RANGE_REVERSION"
    VWAP_REVERSION = "VWAP_REVERSION"
    SUPPORT_RESISTANCE_REVERSAL = "SUPPORT_RESISTANCE_REVERSAL"
    CONSOLIDATION_CONTINUATION = "CONSOLIDATION_CONTINUATION"
    NO_CLEAR_SETUP = "NO_CLEAR_SETUP"


@dataclass(frozen=True, slots=True)
class TradeSetup:
    kind: TradeSetupType
    side: str
    score: int
    approved: bool
    reasons: tuple[str, ...]


def classify_trade_setup(
    series: CandleSeries,
    panel: IndicatorPanel,
    regime: RegimeAnalysis,
    signal: EntrySignal,
) -> TradeSetup:
    """Nomeia o tipo de oportunidade que o candle atual sugere."""
    candles = series.closed_only().candles
    if len(candles) < 30 or candles[-1].close <= 0:
        return _no_setup("Dados insuficientes para classificar setup.")

    last = candles[-1]
    previous = candles[-2]
    prior = candles[-21:-1]
    average_volume = sum(c.volume for c in prior) / len(prior)
    volume_ratio = Decimal(str(last.volume)) / Decimal(str(average_volume)) if average_volume else Decimal("0")
    recent_high = max(c.high for c in prior)
    recent_low = min(c.low for c in prior)
    range_size = recent_high - recent_low
    fib = fibonacci_confluence(series)

    if regime.regime in {MarketRegime.TREND_UP, MarketRegime.TREND_DOWN}:
        expected_side = "BUY" if regime.regime is MarketRegime.TREND_UP else "SELL"
        aligned = signal.side == expected_side and signal.trigger_confirmed
        fib_ok = fib is not None and fib.side == expected_side
        setup_kind = TradeSetupType.TREND_CONTINUATION
        setup_reason = "Tendencia principal alinhada."
        tight_range = _recent_range_ratio(candles[-9:-1], last) <= Decimal("0.75")
        pullback = _pullback_recovery(expected_side, candles[-6:])
        vwap_value = _last(panel, True, "VWAP")
        near_vwap = _near_level(last.close, vwap_value, tolerance_pct=Decimal("0.35"))
        if tight_range and _breaks_level(expected_side, last, candles[-9:-1]):
            setup_kind = TradeSetupType.CONSOLIDATION_CONTINUATION
            setup_reason = "Continuidade apos consolidacao curta."
        elif pullback and (fib_ok or near_vwap):
            setup_kind = TradeSetupType.PULLBACK_TREND
            setup_reason = "Pullback voltou a favor da tendencia."
        elif near_vwap and aligned:
            setup_kind = TradeSetupType.VWAP_REVERSION
            setup_reason = "Preco retomou a VWAP a favor da tendencia."
        approved = aligned and (volume_ratio >= Decimal("1.05") or fib_ok)
        return TradeSetup(
            setup_kind,
            expected_side,
            _score(approved, volume_ratio, fib_ok, aligned),
            approved,
            tuple(
                reason
                for reason in (
                    setup_reason,
                    "Gatilho confirmou continuacao." if aligned else "Gatilho ainda nao confirmou.",
                    "Fibonacci apoia a zona." if fib_ok else "",
                    "VWAP perto do ponto." if near_vwap else "",
                )
                if reason
            ),
        )

    if regime.regime is MarketRegime.EXPANSION:
        buy_breakout = last.close > previous.high and last.close >= recent_high
        sell_breakout = last.close < previous.low and last.close <= recent_low
        side = "BUY" if buy_breakout else "SELL" if sell_breakout else signal.side
        setup_kind = TradeSetupType.EXPANSION_BREAKOUT
        if _is_opening_window(candles) and side in {"BUY", "SELL"}:
            setup_kind = TradeSetupType.OPENING_RANGE_EXPANSION
        elif _retested_breakout(side, last, prior):
            setup_kind = TradeSetupType.BREAKOUT_RETEST
        approved = signal.trigger_confirmed and volume_ratio >= Decimal("1.20") and side in {"BUY", "SELL"}
        return TradeSetup(
            setup_kind,
            side,
            _score(approved, volume_ratio, False, signal.trigger_confirmed),
            approved,
            (
                "Expansao com volume acima da media.",
                "Reteste validou o rompimento." if setup_kind is TradeSetupType.BREAKOUT_RETEST else "",
                "Abertura com expansao acima do range inicial." if setup_kind is TradeSetupType.OPENING_RANGE_EXPANSION else "",
                "Rompimento confirmado." if approved else "Rompimento ainda nao confirmou.",
            ),
        )

    if regime.regime is MarketRegime.RANGE and range_size > 0:
        close_position = (last.close - recent_low) / range_size
        rsi = _last(panel, False, "RSI(14)")
        near_support = close_position <= Decimal("0.20")
        near_resistance = close_position >= Decimal("0.80")
        buy_reversion = near_support and rsi is not None and rsi <= 42
        sell_reversion = near_resistance and rsi is not None and rsi >= 58
        side = "BUY" if buy_reversion else "SELL" if sell_reversion else "NONE"
        setup_kind = TradeSetupType.RANGE_REVERSION
        vwap_value = _last(panel, True, "VWAP")
        if side != "NONE" and _near_level(last.close, vwap_value, tolerance_pct=Decimal("0.45")):
            setup_kind = TradeSetupType.VWAP_REVERSION
        elif side != "NONE" and _reversal_candle(side, previous, last):
            setup_kind = TradeSetupType.SUPPORT_RESISTANCE_REVERSAL
        approved = side in {"BUY", "SELL"} and volume_ratio >= Decimal("0.80")
        return TradeSetup(
            setup_kind,
            side,
            _score(approved, volume_ratio, fib is not None and fib.side == side, side != "NONE"),
            approved,
            (
                "Preco em extremidade do range.",
                "Reversao em suporte/resistencia." if setup_kind is TradeSetupType.SUPPORT_RESISTANCE_REVERSAL else "",
                "Retorno a VWAP em mercado lateral." if setup_kind is TradeSetupType.VWAP_REVERSION else "",
                "RSI sugere reversao curta." if side != "NONE" else "RSI nao confirmou reversao.",
            ),
        )

    return _no_setup("Regime sem setup tecnico especifico.")


def _last(panel: IndicatorPanel, overlay: bool, label: str) -> float | None:
    result = (panel.overlays if overlay else panel.oscillators).get(label)
    return next(iter(result.last().values()), None) if result else None


def _score(approved: bool, volume_ratio: Decimal, fib_ok: bool, aligned: bool) -> int:
    score = 35 if aligned else 10
    if volume_ratio >= Decimal("1.20"):
        score += 30
    elif volume_ratio >= Decimal("1.05"):
        score += 20
    elif volume_ratio >= Decimal("0.80"):
        score += 10
    if fib_ok:
        score += 15
    if approved:
        score += 20
    return min(score, 100)


def _no_setup(reason: str) -> TradeSetup:
    return TradeSetup(TradeSetupType.NO_CLEAR_SETUP, "NONE", 0, False, (reason,))


def _near_level(close: Decimal, level: float | None, *, tolerance_pct: Decimal) -> bool:
    if level is None or close <= 0:
        return False
    distance = abs(close - Decimal(str(level))) / close * Decimal("100")
    return distance <= tolerance_pct


def _pullback_recovery(side: str, candles: tuple[Candle, ...]) -> bool:
    if len(candles) < 4:
        return False
    previous = candles[-2]
    last = candles[-1]
    counter = candles[-4:-1]
    if side == "BUY":
        pulled_back = any(candle.close < candle.open for candle in counter)
        return pulled_back and last.close > previous.high and last.close > last.open
    if side == "SELL":
        pulled_back = any(candle.close > candle.open for candle in counter)
        return pulled_back and last.close < previous.low and last.close < last.open
    return False


def _breaks_level(side: str, last: Candle, prior: tuple[Candle, ...]) -> bool:
    if not prior:
        return False
    if side == "BUY":
        return last.close >= max(candle.high for candle in prior)
    if side == "SELL":
        return last.close <= min(candle.low for candle in prior)
    return False


def _recent_range_ratio(prior: tuple[Candle, ...], last: Candle) -> Decimal:
    if not prior or last.close <= 0:
        return Decimal("1")
    recent_range = max(candle.high for candle in prior) - min(candle.low for candle in prior)
    last_range = max(last.high - last.low, Decimal("0.01"))
    return recent_range / last_range


def _retested_breakout(side: str, last: Candle, prior: tuple[Candle, ...]) -> bool:
    if side not in {"BUY", "SELL"} or len(prior) < 5:
        return False
    reference = prior[:-1]
    if side == "BUY":
        level = max(candle.high for candle in reference)
        return last.low <= level <= last.close
    level = min(candle.low for candle in reference)
    return last.high >= level >= last.close


def _is_opening_window(candles: tuple[Candle, ...]) -> bool:
    same_day = [candle for candle in candles if candle.open_time.date() == candles[-1].open_time.date()]
    return 3 <= len(same_day) <= 12


def _reversal_candle(side: str, previous: Candle, last: Candle) -> bool:
    if side == "BUY":
        return last.close > last.open and last.close > previous.close and last.low <= previous.low
    if side == "SELL":
        return last.close < last.open and last.close < previous.close and last.high >= previous.high
    return False
