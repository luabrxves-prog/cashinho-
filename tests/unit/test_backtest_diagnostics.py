from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from cashinho.domain.enums import Timeframe
from cashinho.pipeline.backtest_diagnostics import (
    build_diagnostic_trades,
    diagnostic_table,
    diagnostic_tables,
)
from tests.unit.test_backtest import START, market_candle, series, trade


def test_diagnostico_classifica_horario_regime_e_resultado() -> None:
    candles = tuple(market_candle(i, low="9.8", high="10.2") for i in range(90))
    data = {Timeframe.M5: series(*candles)}
    first = trade("20", "2", 0)
    diagnostics = build_diagnostic_trades((first,), series_by_timeframe=data)
    assert diagnostics[0].symbol == "PETR4"
    assert diagnostics[0].year == "2026"
    assert diagnostics[0].hour == "07:00"
    assert diagnostics[0].result_bucket == "WIN"
    assert diagnostics[0].setup_type == "NO_CLEAR_SETUP"
    assert diagnostics[0].regime


def test_tabela_aponta_piores_buckets_primeiro() -> None:
    candles = tuple(market_candle(i, low="9.8", high="10.2") for i in range(90))
    data = {Timeframe.M5: series(*candles)}
    win = trade("20", "2", 0)
    loss = trade("-10", "-1", 1)
    late_loss = trade("-5", "-0.5", 2)
    late_loss = replace(
        late_loss,
        entered_at=START + timedelta(hours=4),
        exited_at=START + timedelta(hours=4, minutes=5),
    )
    diagnostics = build_diagnostic_trades((win, loss, late_loss), series_by_timeframe=data)
    rows = diagnostic_table(diagnostics, initial_capital=Decimal("100"), dimension="hour")
    assert rows[0].metrics.net_profit <= rows[-1].metrics.net_profit


def test_tabelas_validam_dimensoes() -> None:
    tables = diagnostic_tables(
        (),
        initial_capital=Decimal("100"),
        dimensions=("year", "symbol", "regime"),
    )
    assert set(tables) == {"year", "symbol", "regime"}
