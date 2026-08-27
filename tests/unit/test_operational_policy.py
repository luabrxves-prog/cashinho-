from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from cashinho.domain.enums import Timeframe
from cashinho.pipeline.backtest_diagnostics import build_diagnostic_trades
from cashinho.pipeline.operational_policy import (
    OperationalPolicy,
    OperationalPolicyRule,
    build_policy_from_diagnostics,
    load_operational_policy,
    save_operational_policy,
)
from tests.unit.test_backtest import market_candle, series, trade


def test_politica_bloqueia_horario_historicamente_ruim() -> None:
    rule = OperationalPolicyRule(
        dimension="hour",
        bucket="10:00",
        action="BLOCK",
        reason="Bloqueio: horario 10:00 foi ruim no estudo historico.",
        total_trades=12,
        win_rate=Decimal("10"),
        profit_factor=Decimal("0.20"),
        net_profit=Decimal("-5"),
        max_drawdown_pct=Decimal("9"),
    )
    policy = OperationalPolicy("2026-08-27T00:00:00+00:00", "teste", (rule,))

    decision = policy.evaluate(
        symbol="PETR4",
        timestamp=datetime(2026, 8, 20, 13, tzinfo=UTC),
        timeframe=Timeframe.M5,
        side="BUY",
    )

    assert not decision.approved
    assert "10:00" in decision.summary


def test_salva_e_carrega_politica(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "policy.json"
    policy = OperationalPolicy(
        "2026-08-27T00:00:00+00:00",
        "teste",
        (
            OperationalPolicyRule(
                "symbol",
                "PETR4",
                "WARN",
                "Alerta.",
                20,
                Decimal("40"),
                Decimal("0.95"),
                Decimal("-1"),
                Decimal("3"),
            ),
        ),
    )

    save_operational_policy(policy, path)
    loaded = load_operational_policy(path)

    assert loaded.rules == policy.rules


def test_constroi_politica_a_partir_do_diagnostico() -> None:
    candles = tuple(market_candle(i, low="9.8", high="10.2") for i in range(90))
    data = {Timeframe.M5: series(*candles)}
    losses = tuple(trade("-10", "-1", i) for i in range(9))
    losses = tuple(
        replace(
            item,
            entered_at=datetime(2026, 8, 20, 13, tzinfo=UTC),
            exited_at=datetime(2026, 8, 20, 13, 5, tzinfo=UTC),
        )
        for item in losses
    )
    diagnostics = build_diagnostic_trades(losses, series_by_timeframe=data)

    policy = build_policy_from_diagnostics(
        diagnostics,
        initial_capital=Decimal("100"),
        generated_at=datetime(2026, 8, 27, tzinfo=UTC),
        source="teste",
    )

    assert any(rule.dimension == "hour" and rule.bucket == "10:00" for rule in policy.rules)
