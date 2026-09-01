from __future__ import annotations

from decimal import Decimal

import pytest

from cashinho.pipeline.walk_forward import rolling_walk_forward
from tests.unit.test_backtest import trade


def test_walk_forward_cria_janelas_cronologicas() -> None:
    trades = tuple(trade("1", "1", index) for index in range(35))

    windows = rolling_walk_forward(
        trades,
        initial_capital=Decimal("100"),
        train_size=20,
        test_size=10,
        step_size=5,
    )

    assert len(windows) == 2
    assert windows[0].test_start > windows[0].train_end


def test_walk_forward_valida_tamanhos() -> None:
    with pytest.raises(ValueError):
        rolling_walk_forward((), initial_capital=Decimal("100"), train_size=0)
