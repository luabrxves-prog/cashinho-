#!/usr/bin/env python3
"""Compara 1m agregado contra timeframe direto do MT5."""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from cashinho.adapters.providers.metatrader import MetaTraderMarketDataProvider  # noqa: E402
from cashinho.config.settings import get_settings  # noqa: E402
from cashinho.core.time.clocks import SystemClock  # noqa: E402
from cashinho.domain.enums import Timeframe  # noqa: E402
from cashinho.pipeline.timeframe_audit import (  # noqa: E402
    aggregate_timeframe,
    compare_timeframes,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audita consistencia de timeframes no MT5")
    parser.add_argument("--symbol", default="PETR4")
    parser.add_argument("--target", default="60m", choices=[t.value for t in Timeframe])
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--price-tolerance", default="0.01")
    parser.add_argument("--volume-tolerance", type=int, default=0)
    args = parser.parse_args(argv)

    target = Timeframe(args.target)
    if target.duration <= Timeframe.M1.duration:
        print("O alvo precisa ser maior que 1m.")
        return 2

    settings = get_settings()
    clock = SystemClock()
    provider = MetaTraderMarketDataProvider(
        clock,
        terminal_path=settings.mt5_terminal_path,
        server_timezone=settings.mt5_server_timezone,
        stale_seconds=settings.mt5_stale_seconds,
    )
    info = provider.connect()
    if not info.connected:
        print(f"MT5 offline: {info.reason}")
        return 2

    now = clock.now()
    start = now - timedelta(days=args.days)
    one_minute = provider.get_candles(args.symbol, Timeframe.M1, start=start, end=now)
    direct = provider.get_candles(args.symbol, target, start=start, end=now)
    aggregated = aggregate_timeframe(one_minute, target)
    comparison = compare_timeframes(
        aggregated,
        direct,
        price_tolerance=Decimal(args.price_tolerance),
        volume_tolerance=args.volume_tolerance,
    )

    print(f"MT5: {info.company} · {info.server} · conta {info.account_mode}")
    print(f"{args.symbol} 1m->{target.value}: {len(aggregated.closed_only())} agregado(s)")
    print(f"{args.symbol} {target.value} direto: {len(direct.closed_only())} candle(s)")
    print(f"Comparados: {comparison.compared}")
    if comparison.approved:
        print("APROVADO: OHLCV compatível dentro das tolerâncias.")
        return 0
    print("REPROVADO: divergências encontradas.")
    for mismatch in comparison.mismatches[:20]:
        print(
            f"- {mismatch.timestamp} {mismatch.field}: "
            f"agregado={mismatch.aggregated} direto={mismatch.direct}"
        )
    if len(comparison.mismatches) > 20:
        print(f"... mais {len(comparison.mismatches) - 20} divergência(s)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
