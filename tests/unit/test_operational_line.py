from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from cashinho.domain.enums import Timeframe
from cashinho.pipeline.backtest import BacktestTrade
from cashinho.pipeline.backtest_diagnostics import build_diagnostic_trades
from cashinho.pipeline.operational_line import (
    OperationalLineCandidate,
    compare_operational_lines,
)
from tests.unit.test_backtest import market_candle, series, trade


def _dated_trade(net: str, index: int, *, year: int, setup: str = "VWAP_REVERSION") -> BacktestTrade:
    return replace(
        trade(net, net, index),
        score=85,
        setup_type=setup,
        entered_at=datetime(year, 8, min(index + 1, 28), 13, tzinfo=UTC),
        exited_at=datetime(year, 8, min(index + 1, 28), 13, 5, tzinfo=UTC),
    )


def test_linha_operacional_aprova_quando_teste_tem_expectativa_positiva() -> None:
    candles = tuple(market_candle(i, low="9.8", high="10.2") for i in range(120))
    data = {Timeframe.M5: series(*candles)}
    trades = tuple(
        _dated_trade("1", index, year=2024 if index < 4 else 2025)
        for index in range(8)
    )
    diagnostics = build_diagnostic_trades(trades, series_by_timeframe=data)
    candidate = OperationalLineCandidate(
        "TESTE",
        minimum_score=80,
        allowed_setups=("VWAP_REVERSION",),
        minimum_test_trades=4,
    )

    rows = compare_operational_lines(
        diagnostics,
        initial_capital=Decimal("100"),
        train_until_year=2024,
        candidates=(candidate,),
    )

    assert rows[0].approved
    assert rows[0].test_trades == 4
    assert rows[0].test_metrics.expectancy == Decimal("1.00")


def test_linha_operacional_reprova_amostra_pequena_e_resultado_ruim() -> None:
    candles = tuple(market_candle(i, low="9.8", high="10.2") for i in range(120))
    data = {Timeframe.M5: series(*candles)}
    trades = (
        _dated_trade("1", 0, year=2024),
        _dated_trade("-1", 1, year=2025),
    )
    diagnostics = build_diagnostic_trades(trades, series_by_timeframe=data)
    candidate = OperationalLineCandidate(
        "TESTE",
        minimum_score=80,
        allowed_setups=("VWAP_REVERSION",),
        minimum_test_trades=3,
    )

    rows = compare_operational_lines(
        diagnostics,
        initial_capital=Decimal("100"),
        train_until_year=2024,
        candidates=(candidate,),
    )

    assert not rows[0].approved
    assert "Amostra fora da amostra pequena demais." in rows[0].rejection_reasons
    assert "Resultado líquido fora da amostra não ficou positivo." in rows[0].rejection_reasons


def test_linha_operacional_mostra_reprovacao_sem_periodo_de_teste() -> None:
    candles = tuple(market_candle(i, low="9.8", high="10.2") for i in range(120))
    data = {Timeframe.M5: series(*candles)}
    diagnostics = build_diagnostic_trades(
        (_dated_trade("1", 0, year=2024, setup="BREAKOUT_RETEST"),),
        series_by_timeframe=data,
    )
    candidate = OperationalLineCandidate(
        "TESTE_SEM_HOLDOUT",
        minimum_score=70,
        allowed_setups=("BREAKOUT_RETEST",),
        minimum_test_trades=1,
    )

    rows = compare_operational_lines(
        diagnostics,
        initial_capital=Decimal("100"),
        train_until_year=2024,
        candidates=(candidate,),
    )

    assert len(rows) == 1
    assert rows[0].test_start_year == 2025
    assert rows[0].test_trades == 0
    assert not rows[0].approved
