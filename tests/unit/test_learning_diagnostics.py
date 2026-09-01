from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from cashinho.domain.enums import Timeframe
from cashinho.domain.risk import RiskProfile
from cashinho.pipeline.backtest import BacktestDecisionLog
from cashinho.pipeline.backtest_diagnostics import build_diagnostic_trades
from cashinho.pipeline.learning_diagnostics import (
    analyze_filter_contribution,
    build_daily_learning_reports,
    build_loss_autopsies,
    find_missed_opportunities,
    simulate_missed_opportunity_trades,
    summarize_error_causes,
)
from tests.unit.test_backtest import START, market_candle, series, trade


def test_autopsia_diferencia_setup_indefinido_de_perda_normal() -> None:
    candles = tuple(market_candle(i, low="9", high="10.5") for i in range(90))
    data = {Timeframe.M5: series(*candles)}
    undefined_loss = trade("-1", "-1", 1)
    planned_loss = replace(trade("-1", "-1", 2), setup_type="RANGE_REVERSION")
    diagnostics = build_diagnostic_trades((undefined_loss, planned_loss), series_by_timeframe=data)

    autopsies = build_loss_autopsies(diagnostics, series_by_timeframe=data)
    causes = {row.setup_type: row for row in autopsies}

    assert causes["NO_CLEAR_SETUP"].primary_cause == "SETUP_INDEFINIDO"
    assert causes["RANGE_REVERSION"].primary_cause == "PERDA_NORMAL_DA_ESTRATEGIA"
    assert not causes["RANGE_REVERSION"].is_model_error


def test_resumo_de_causas_ranqueia_prejuizo() -> None:
    candles = tuple(market_candle(i, low="9", high="10.5") for i in range(90))
    data = {Timeframe.M5: series(*candles)}
    losses = (trade("-3", "-1", 1), trade("-1", "-1", 2))
    diagnostics = build_diagnostic_trades(losses, series_by_timeframe=data)

    summary = summarize_error_causes(build_loss_autopsies(diagnostics, series_by_timeframe=data))

    assert summary
    assert summary[0].net_loss == Decimal("4.00")
    assert summary[0].occurrences == 2


def test_relatorio_diario_explica_dia_sem_operacao() -> None:
    candles = tuple(market_candle(i, low="9.8", high="10.2") for i in range(12))
    data = series(*candles)
    decision = BacktestDecisionLog(
        symbol="PETR4",
        timestamp=START + timedelta(minutes=5),
        side="NONE",
        timeframe=Timeframe.M5,
        score=45,
        setup_type="NO_CLEAR_SETUP",
        should_enter=False,
        primary_reason="Gatilho de entrada ainda não foi confirmado.",
        reasons=("Gatilho de entrada ainda não foi confirmado.",),
    )

    daily = build_daily_learning_reports(
        symbol="PETR4",
        series=data,
        decisions=(decision,),
        trades=(),
    )

    assert daily[0].entries == 0
    assert daily[0].avoided == 1
    assert daily[0].learning.startswith("Não operei hoje porque")
    assert daily[0].classification == "RUIM"


def test_contribuicao_de_filtro_preserva_contexto_do_bloqueio() -> None:
    decisions = (
        BacktestDecisionLog(
            symbol="PETR4",
            timestamp=START,
            side="BUY",
            timeframe=Timeframe.M5,
            score=70,
            setup_type="RANGE_REVERSION",
            should_enter=False,
            primary_reason="Risk Manager bloqueou o ativo.",
            reasons=("Risk Manager bloqueou o ativo.",),
        ),
        BacktestDecisionLog(
            symbol="VALE3",
            timestamp=START + timedelta(minutes=5),
            side="SELL",
            timeframe=Timeframe.M5,
            score=80,
            setup_type="EXPANSION_BREAKOUT",
            should_enter=False,
            primary_reason="Risk Manager bloqueou o ativo.",
            reasons=("Risk Manager bloqueou o ativo.",),
        ),
    )

    rows = analyze_filter_contribution(decisions)

    assert rows[0].reason == "Risk Manager bloqueou o ativo."
    assert rows[0].occurrences == 2
    assert rows[0].average_score == Decimal("75.00")
    assert rows[0].affected_symbols == ("PETR4", "VALE3")


def test_oportunidade_perdida_detecta_bloqueio_possivelmente_conservador() -> None:
    candles = (
        market_candle(0, low="9.8", high="10.2"),
        market_candle(1, low="10.0", high="10.4"),
        market_candle(2, low="10.1", high="10.9"),
        market_candle(3, low="10.3", high="11.2"),
    )
    decision = BacktestDecisionLog(
        symbol="PETR4",
        timestamp=candles[0].close_time,
        side="BUY",
        timeframe=Timeframe.M5,
        score=78,
        setup_type="PULLBACK_TREND",
        should_enter=False,
        primary_reason="Mercado amplo dividido; o estudo profundo bloqueou a entrada.",
        reasons=("Mercado amplo dividido; o estudo profundo bloqueou a entrada.",),
    )

    missed = find_missed_opportunities(
        (decision,),
        series=series(*candles),
        minimum_score=65,
        horizon_candles=3,
    )

    assert len(missed) == 1
    assert missed[0].verdict == "BLOQUEIO_POSSIVELMENTE_CONSERVADOR"
    assert "conservador demais" in missed[0].learning


def test_simula_trade_bloqueado_com_plano_historico() -> None:
    candles = (
        market_candle(0, low="9.8", high="10.2"),
        market_candle(1, low="9.9", high="10.1"),
        market_candle(2, low="10.4", high="12.1"),
    )
    decision = BacktestDecisionLog(
        symbol="PETR4",
        timestamp=candles[0].close_time,
        side="NONE",
        timeframe=Timeframe.M5,
        score=82,
        setup_type="BREAKOUT_RETEST",
        should_enter=False,
        primary_reason="Filtro histórico bloqueou o contexto.",
        reasons=("Filtro histórico bloqueou o contexto.",),
        planned_side="BUY",
        planned_entry=Decimal("10"),
        planned_stop=Decimal("9"),
        planned_target=Decimal("12"),
        planned_risk_reward=2.0,
    )

    simulated = simulate_missed_opportunity_trades(
        (decision,),
        series=series(*candles),
        risk_profile=RiskProfile(),
        minimum_score=70,
        horizon_candles=3,
    )

    assert len(simulated) == 1
    assert simulated[0].trade.close_reason == "TARGET"
    assert simulated[0].trade.net_pnl > 0
    assert simulated[0].verdict == "BLOQUEIO_PERDEU_ALVO"
