"""Modo de estudo profundo para filtrar oportunidades antes do gatilho."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from cashinho.domain.enums import Timeframe
from cashinho.pipeline.multi_timeframe import TIMEFRAME_ORDER, TimeframeAnalysis

SIDES = {"BUY", "SELL"}
MACRO_PRIORITY = (Timeframe.D1, Timeframe.H1, Timeframe.M30, Timeframe.M15)


@dataclass(frozen=True, slots=True)
class MarketStudy:
    """Leitura do mercado amplo antes de aprovar um ativo especifico."""

    side: str
    bias: str
    approved: bool
    confidence: int
    symbols_evaluated: int
    directional_symbols: int
    aligned_symbols: int
    neutral_symbols: int
    reason: str
    sample_limited: bool
    directions: dict[str, str]

    @property
    def summary(self) -> str:
        if self.side not in SIDES:
            return "Mercado amplo lido; o ativo ainda não definiu compra ou venda."
        return (
            f"Viés do mercado: {self.bias_label}. "
            f"{self.aligned_symbols}/{self.directional_symbols or self.symbols_evaluated} "
            f"ativos direcionais apoiam {self.side_label}."
        )

    @property
    def side_label(self) -> str:
        return "compra" if self.side == "BUY" else "venda" if self.side == "SELL" else "neutro"

    @property
    def bias_label(self) -> str:
        return "compra" if self.bias == "BUY" else "venda" if self.bias == "SELL" else "neutro"


def market_direction(analyses: Mapping[Timeframe, TimeframeAnalysis]) -> str:
    """Extrai a direcao macro de um ativo a partir dos timeframes mais altos."""

    candidates = [timeframe for timeframe in MACRO_PRIORITY if timeframe in analyses]
    if not candidates:
        candidates = [timeframe for timeframe in TIMEFRAME_ORDER if timeframe in analyses][:2]

    directions = [
        analyses[timeframe].regime.direction
        for timeframe in candidates
        if analyses[timeframe].regime.direction in SIDES
    ]
    if not directions:
        return "NONE"

    buys = directions.count("BUY")
    sells = directions.count("SELL")
    if buys == sells:
        return "NONE"
    return "BUY" if buys > sells else "SELL"


def build_market_study(
    analyses_by_symbol: Mapping[str, Mapping[Timeframe, TimeframeAnalysis]],
    *,
    side: str,
    minimum_alignment_pct: int = 55,
    minimum_symbols_for_full_sample: int = 3,
) -> MarketStudy:
    """Resume se o mercado inteiro apoia ou bloqueia a direcao estudada."""

    directions = {
        symbol: market_direction(analyses)
        for symbol, analyses in analyses_by_symbol.items()
        if analyses
    }
    symbols_evaluated = len(directions)
    neutral_symbols = sum(direction == "NONE" for direction in directions.values())
    directional = [direction for direction in directions.values() if direction in SIDES]
    directional_symbols = len(directional)
    aligned_symbols = sum(direction == side for direction in directional)
    sample_limited = symbols_evaluated < minimum_symbols_for_full_sample

    if side not in SIDES:
        return MarketStudy(
            side,
            "NONE",
            True,
            0,
            symbols_evaluated,
            directional_symbols,
            0,
            neutral_symbols,
            "O mercado foi lido, mas o ativo ainda não tem direção operacional.",
            sample_limited,
            directions,
        )

    if directional_symbols == 0:
        return MarketStudy(
            side,
            "NONE",
            False,
            0,
            symbols_evaluated,
            directional_symbols,
            aligned_symbols,
            neutral_symbols,
            "Mercado amplo sem direção suficiente; o estudo profundo bloqueou a entrada.",
            sample_limited,
            directions,
        )

    buys = directional.count("BUY")
    sells = directional.count("SELL")
    bias = "BUY" if buys > sells else "SELL" if sells > buys else "NONE"
    confidence = int(aligned_symbols / directional_symbols * 100)
    approved = bias == side and confidence >= minimum_alignment_pct
    if approved:
        reason = (
            "Mercado amplo apoia a direção do ativo."
            if not sample_limited
            else "Amostra de mercado pequena, mas a direção disponível apoia o ativo."
        )
    elif bias == "NONE":
        reason = "Mercado amplo dividido; o estudo profundo bloqueou a entrada."
    elif bias != side:
        reason = "Mercado amplo aponta para o lado oposto; entrada bloqueada."
    else:
        reason = "Poucos ativos confirmam a mesma direção; entrada bloqueada."

    return MarketStudy(
        side,
        bias,
        approved,
        confidence,
        symbols_evaluated,
        directional_symbols,
        aligned_symbols,
        neutral_symbols,
        reason,
        sample_limited,
        directions,
    )
