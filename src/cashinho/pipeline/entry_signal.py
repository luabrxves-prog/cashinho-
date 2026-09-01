from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from cashinho.domain.market import CandleSeries
from cashinho.pipeline.fibonacci import fibonacci_confluence
from cashinho.pipeline.indicators import IndicatorPanel


@dataclass(frozen=True, slots=True)
class EntrySignal:
    side: str
    status: str
    score: int
    entry: Decimal | None
    stop: Decimal | None
    target: Decimal | None
    risk_reward: float | None
    reasons: tuple[str, ...]
    trigger_confirmed: bool = False


def _last(panel: IndicatorPanel, overlay: bool, label: str) -> float | None:
    result = (panel.overlays if overlay else panel.oscillators).get(label)
    return next(iter(result.last().values()), None) if result else None


def evaluate_entry_signal(
    series: CandleSeries,
    panel: IndicatorPanel,
    *,
    minimum_context_score: int = 60,
    risk_reward: Decimal = Decimal("2"),
) -> EntrySignal:
    """Combina contexto e um gatilho real, sempre sobre candles fechados."""
    candles = series.closed_only()
    if len(candles) < 30 or candles.last is None:
        return EntrySignal(
            "NONE", "NÃO OPERAR", 0, None, None, None, None, ("Dados fechados insuficientes.",)
        )
    previous, last = candles.candles[-2:]
    buy_score = sell_score = 0
    buy: list[str] = []
    sell: list[str] = []

    ema9, ema21 = _last(panel, True, "EMA(9)"), _last(panel, True, "EMA(21)")
    if ema9 is not None and ema21 is not None:
        if ema9 > ema21:
            buy_score += 25
            buy.append("EMA 9 acima da EMA 21")
        elif ema9 < ema21:
            sell_score += 25
            sell.append("EMA 9 abaixo da EMA 21")
    vwap = _last(panel, True, "VWAP")
    if vwap is not None:
        if last.close > Decimal(str(vwap)):
            buy_score += 20
            buy.append("Preço fechado acima da VWAP")
        elif last.close < Decimal(str(vwap)):
            sell_score += 20
            sell.append("Preço fechado abaixo da VWAP")
    rsi = _last(panel, False, "RSI(14)")
    if rsi is not None:
        if 50 <= rsi <= 70:
            buy_score += 15
            buy.append(f"RSI favorável à compra ({rsi:.1f})")
        elif 30 <= rsi < 50:
            sell_score += 15
            sell.append(f"RSI favorável à venda ({rsi:.1f})")

    buy_structure = last.high > previous.high and last.low > previous.low
    sell_structure = last.high < previous.high and last.low < previous.low
    if buy_structure:
        buy_score += 25
        buy.append("Estrutura de máxima e mínima ascendentes")
    if sell_structure:
        sell_score += 25
        sell.append("Estrutura de máxima e mínima descendentes")
    volumes = [c.volume for c in candles.candles[-21:-1]]
    volume_ok = last.volume > sum(volumes) / len(volumes)
    if volume_ok:
        buy_score += 15
        sell_score += 15

    fib = fibonacci_confluence(candles)
    if fib is not None:
        if fib.side == "BUY":
            buy_score += 10
            buy.append(fib.reason)
        else:
            sell_score += 10
            sell.append(fib.reason)

    if buy_score == sell_score:
        return EntrySignal(
            "NONE",
            "NÃO OPERAR",
            0,
            None,
            None,
            None,
            None,
            ("Sem vantagem clara entre compra e venda.",),
        )
    side = "BUY" if buy_score > sell_score else "SELL"
    score = min(max(buy_score, sell_score), 100)
    reasons = buy if side == "BUY" else sell
    if score < minimum_context_score:
        return EntrySignal(side, "NÃO OPERAR", score, None, None, None, None, tuple(reasons))

    candle_ok = (
        last.close > last.open and last.close > previous.high
        if side == "BUY"
        else last.close < last.open and last.close < previous.low
    )
    trigger = candle_ok and volume_ok and (buy_structure if side == "BUY" else sell_structure)
    if not trigger:
        return EntrySignal(
            side,
            "AGUARDANDO GATILHO",
            score,
            None,
            None,
            None,
            None,
            (
                *reasons,
                "Contexto válido; rompimento, candle, estrutura e volume ainda não confirmados.",
            ),
        )

    entry = last.close
    if side == "BUY":
        stop = min(c.low for c in candles.candles[-5:])
        risk = entry - stop
        target = entry + risk * risk_reward
    else:
        stop = max(c.high for c in candles.candles[-5:])
        risk = stop - entry
        target = entry - risk * risk_reward
    geometry_ok = risk > 0 and (stop < entry < target if side == "BUY" else target < entry < stop)
    if not geometry_ok:
        return EntrySignal(
            side,
            "NÃO OPERAR",
            score,
            None,
            None,
            None,
            None,
            (*reasons, "Geometria de stop e alvo inválida."),
        )
    reasons.append("Gatilho confirmado por rompimento, candle, estrutura e volume")
    return EntrySignal(
        side,
        "ENTRADA LIBERADA",
        score,
        entry,
        stop,
        target,
        float(risk_reward),
        tuple(reasons),
        True,
    )
