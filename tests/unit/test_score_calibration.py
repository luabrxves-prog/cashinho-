from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from cashinho.pipeline.score_calibration import calibrate_scores, score_calibration_verdict
from tests.unit.test_backtest import trade


def test_calibra_score_por_faixa() -> None:
    trades = (
        replace(trade("-2", "-1", 0), score=65),
        replace(trade("2", "1", 1), score=85),
        replace(trade("3", "1.5", 2), score=85),
    )

    rows = calibrate_scores(trades, initial_capital=Decimal("100"))

    assert [row.bucket for row in rows] == ["60-69", "80-89"]


def test_veredito_exige_amostra_minima() -> None:
    rows = calibrate_scores((replace(trade("1", "1", 0), score=95),), initial_capital=Decimal("100"))

    assert score_calibration_verdict(rows) == "INCONCLUSIVO"
