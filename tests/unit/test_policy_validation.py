from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from cashinho.domain.enums import Timeframe
from cashinho.pipeline.backtest_diagnostics import build_diagnostic_trades
from cashinho.pipeline.policy_validation import validate_policy_holdout
from tests.unit.test_backtest import market_candle, series, trade


def test_holdout_treina_no_passado_e_testa_no_futuro() -> None:
    candles = tuple(market_candle(i, low="9.8", high="10.2") for i in range(90))
    data = {Timeframe.M5: series(*candles)}
    train_losses = tuple(
        replace(
            trade("-1", "-1", i),
            entered_at=datetime(2021, 8, 20, 13, tzinfo=UTC),
            exited_at=datetime(2021, 8, 20, 13, 5, tzinfo=UTC),
        )
        for i in range(8)
    )
    future_win = replace(
        trade("2", "2", 20),
        entered_at=datetime(2025, 8, 20, 13, tzinfo=UTC),
        exited_at=datetime(2025, 8, 20, 13, 5, tzinfo=UTC),
    )
    diagnostics = build_diagnostic_trades((*train_losses, future_win), series_by_timeframe=data)

    result = validate_policy_holdout(
        diagnostics,
        initial_capital=Decimal("100"),
        train_until_year=2024,
        generated_at=datetime(2026, 8, 31, tzinfo=UTC),
        source="teste",
    )

    assert result is not None
    assert result.rows[0].group == "TESTE_ANTES_POLITICA"
    assert result.rows[0].trades == 1
    assert result.policy.rules
