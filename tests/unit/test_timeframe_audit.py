from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cashinho.domain.enums import Timeframe
from cashinho.domain.market import Candle, CandleSeries
from cashinho.pipeline.timeframe_audit import aggregate_timeframe, compare_timeframes

BASE = datetime(2026, 8, 20, 13, 0, tzinfo=UTC)


def _minute(index: int, close: str) -> Candle:
    open_time = BASE + timedelta(minutes=index)
    value = Decimal(close)
    return Candle(
        open_time=open_time,
        close_time=open_time + timedelta(minutes=1),
        open=value,
        high=value + Decimal("0.10"),
        low=value - Decimal("0.10"),
        close=value,
        volume=10 + index,
        is_closed=True,
    )


def _series(candles: tuple[Candle, ...], timeframe: Timeframe) -> CandleSeries:
    return CandleSeries(
        symbol="PETR4",
        timeframe=timeframe,
        candles=candles,
        source="teste",
        fetched_at=BASE + timedelta(days=1),
    )


def test_agregado_de_1m_bate_com_60m_direto() -> None:
    minutes = tuple(_minute(i, str(40 + i / 100)) for i in range(60))
    aggregated = aggregate_timeframe(_series(minutes, Timeframe.M1), Timeframe.H1)
    direct = _series((aggregated.candles[0],), Timeframe.H1)

    comparison = compare_timeframes(aggregated, direct)

    assert comparison.approved
    assert comparison.compared == 1


def test_comparacao_aponta_divergencia_do_60m() -> None:
    minutes = tuple(_minute(i, str(40 + i / 100)) for i in range(60))
    aggregated = aggregate_timeframe(_series(minutes, Timeframe.M1), Timeframe.H1)
    wrong = aggregated.candles[0].model_copy(update={"close": Decimal("40.50")})
    direct = _series((wrong,), Timeframe.H1)

    comparison = compare_timeframes(aggregated, direct)

    assert not comparison.approved
    assert comparison.mismatches[0].field == "close"
    assert comparison.mismatches[0].timestamp == BASE.isoformat()
