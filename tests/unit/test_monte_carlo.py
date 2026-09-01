from __future__ import annotations

from decimal import Decimal

from cashinho.pipeline.monte_carlo import run_monte_carlo
from tests.unit.test_backtest import trade


def test_monte_carlo_e_reprodutivel_com_seed() -> None:
    trades = (trade("2", "1", 0), trade("-1", "-1", 1), trade("3", "1.5", 2))

    first = run_monte_carlo(trades, initial_capital=Decimal("100"), simulations=50, seed=7)
    second = run_monte_carlo(trades, initial_capital=Decimal("100"), simulations=50, seed=7)

    assert first == second
    assert first is not None
    assert first.trades_per_simulation == 3


def test_monte_carlo_sem_trades_fica_inconclusivo() -> None:
    assert run_monte_carlo((), initial_capital=Decimal("100")) is None
