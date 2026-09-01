"""Teste de robustez por reamostragem dos trades historicos."""

from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal
from statistics import quantiles

from cashinho.pipeline.backtest import HUNDRED, ZERO, BacktestTrade


@dataclass(frozen=True, slots=True)
class MonteCarloSummary:
    simulations: int
    trades_per_simulation: int
    median_final_equity: Decimal
    final_equity_p05: Decimal
    final_equity_p95: Decimal
    drawdown_p50_pct: Decimal
    drawdown_p95_pct: Decimal
    loss_streak_p95: int
    probability_negative_return_pct: Decimal
    risk_of_ruin_pct: Decimal


def run_monte_carlo(
    trades: tuple[BacktestTrade, ...],
    *,
    initial_capital: Decimal,
    simulations: int = 1000,
    seed: int = 42,
    ruin_level_pct: Decimal = Decimal("30"),
) -> MonteCarloSummary | None:
    """Embaralha resultados com reposicao para estimar sequencia ruim plausivel."""
    if not trades:
        return None
    if simulations <= 0:
        raise ValueError("Monte Carlo exige ao menos uma simulacao.")
    rng = random.Random(seed)
    final_equities: list[Decimal] = []
    drawdowns: list[Decimal] = []
    loss_streaks: list[int] = []
    negative = 0
    ruined = 0
    ruin_floor = initial_capital * (HUNDRED - ruin_level_pct) / HUNDRED
    for _ in range(simulations):
        sample = [rng.choice(trades) for _ in trades]
        equity = initial_capital
        peak = initial_capital
        max_drawdown_pct = ZERO
        loss_streak = max_loss_streak = 0
        hit_ruin = False
        for trade in sample:
            equity += trade.net_pnl
            peak = max(peak, equity)
            drawdown_pct = (peak - equity) / peak * HUNDRED if peak else HUNDRED
            max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)
            if trade.net_pnl < 0:
                loss_streak += 1
                max_loss_streak = max(max_loss_streak, loss_streak)
            elif trade.net_pnl > 0:
                loss_streak = 0
            if equity <= ruin_floor:
                hit_ruin = True
        final_equities.append(equity)
        drawdowns.append(max_drawdown_pct)
        loss_streaks.append(max_loss_streak)
        negative += int(equity < initial_capital)
        ruined += int(hit_ruin)

    return MonteCarloSummary(
        simulations=simulations,
        trades_per_simulation=len(trades),
        median_final_equity=_percentile(final_equities, 50),
        final_equity_p05=_percentile(final_equities, 5),
        final_equity_p95=_percentile(final_equities, 95),
        drawdown_p50_pct=_percentile(drawdowns, 50),
        drawdown_p95_pct=_percentile(drawdowns, 95),
        loss_streak_p95=int(_percentile([Decimal(item) for item in loss_streaks], 95)),
        probability_negative_return_pct=(Decimal(negative) / Decimal(simulations) * HUNDRED).quantize(
            Decimal("0.01")
        ),
        risk_of_ruin_pct=(Decimal(ruined) / Decimal(simulations) * HUNDRED).quantize(
            Decimal("0.01")
        ),
    )


def _percentile(values: list[Decimal], percentile: int) -> Decimal:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0].quantize(Decimal("0.01"))
    buckets = quantiles(ordered, n=100, method="inclusive")
    if percentile <= 0:
        value = ordered[0]
    elif percentile >= 100:
        value = ordered[-1]
    else:
        value = buckets[percentile - 1]
    return value.quantize(Decimal("0.01"))
