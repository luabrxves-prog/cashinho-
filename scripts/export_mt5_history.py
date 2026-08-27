"""Exporta candles historicos do MetaTrader 5 para CSV local.

Uso basico:
    python scripts/export_mt5_history.py

Somente leitura. Este script nao chama order_send, nao le senha e nao usa dados
da conta. Ele exige o MetaTrader 5 aberto e autenticado manualmente.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cashinho.adapters.providers.metatrader.broker_time import BrokerTimeNormalizer  # noqa: E402
from cashinho.adapters.providers.metatrader.symbols import (  # noqa: E402
    AmbiguousSymbolError,
    SymbolNotFoundError,
    resolve_symbol,
)
from cashinho.adapters.providers.metatrader.terminal import (  # noqa: E402
    TIMEFRAME_CONSTANTS,
    MetaTraderTerminal,
)
from cashinho.config.settings import get_settings  # noqa: E402
from cashinho.domain.enums import Timeframe  # noqa: E402

DEFAULT_SYMBOLS = ("PETR4", "VALE3", "ITUB4", "BOVA11")
DEFAULT_TIMEFRAMES = (Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.D1)
CSV_HEADER = ("timestamp", "open", "high", "low", "close", "volume")


def _parse_date(raw: str) -> date:
    return date.fromisoformat(raw)


def _parse_timeframes(raw: str) -> tuple[Timeframe, ...]:
    return tuple(Timeframe(item.strip()) for item in raw.split(",") if item.strip())


def _parse_symbols(raw: str) -> tuple[str, ...]:
    return tuple(item.strip().upper() for item in raw.split(",") if item.strip())


def _as_dict(record: Any) -> dict[str, Any]:
    dtype = getattr(record, "dtype", None)
    names = getattr(dtype, "names", None) if dtype is not None else None
    if names:
        return {
            name: (record[name].item() if hasattr(record[name], "item") else record[name])
            for name in names
        }
    if hasattr(record, "_asdict"):
        return dict(record._asdict())
    if isinstance(record, dict):
        return dict(record)
    return {key: getattr(record, key) for key in dir(record) if not key.startswith("_")}


def _price(value: object) -> Decimal:
    try:
        price = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"preco invalido: {value!r}") from exc
    if price <= 0:
        raise ValueError(f"preco invalido: {value!r}")
    return price


def _volume(row: dict[str, Any]) -> int:
    raw = row.get("real_volume") or row.get("tick_volume") or row.get("volume") or 0
    return max(int(float(raw)), 0)


def _server_query_time(moment: datetime, normalizer: BrokerTimeNormalizer) -> datetime:
    """UTC do Cashinho -> relogio de parede do servidor marcado para consulta MT5."""

    return normalizer.from_utc(moment).replace(tzinfo=UTC)


def _iter_ranges(start: datetime, end: datetime, chunk_days: int) -> tuple[tuple[datetime, datetime], ...]:
    ranges = []
    current = start
    step = timedelta(days=chunk_days)
    while current < end:
        nxt = min(current + step, end)
        ranges.append((current, nxt))
        current = nxt
    return tuple(ranges)


def export_symbol_timeframe(
    *,
    library: Any,
    terminal: MetaTraderTerminal,
    normalizer: BrokerTimeNormalizer,
    requested_symbol: str,
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
    output_root: Path,
    chunk_days: int,
) -> int:
    resolution = resolve_symbol(requested_symbol, terminal.symbols())
    terminal.select(resolution.resolved)
    constant_name = TIMEFRAME_CONSTANTS[timeframe]
    constant = getattr(library, constant_name)
    rows_by_timestamp: dict[str, dict[str, object]] = {}

    for chunk_start, chunk_end in _iter_ranges(start, end, chunk_days):
        server_start = _server_query_time(chunk_start, normalizer)
        server_end = _server_query_time(chunk_end, normalizer)
        raw = library.copy_rates_range(resolution.resolved, constant, server_start, server_end)
        if raw is None:
            code, message = library.last_error()
            print(
                f"[aviso] {requested_symbol} {timeframe.value}: "
                f"copy_rates_range falhou {code} {message}"
            )
            continue
        for record in raw:
            row = _as_dict(record)
            raw_time = row.get("time")
            if raw_time is None:
                continue
            timestamp = normalizer.to_utc(raw_time).isoformat()
            try:
                rows_by_timestamp[timestamp] = {
                    "timestamp": timestamp,
                    "open": str(_price(row.get("open"))),
                    "high": str(_price(row.get("high"))),
                    "low": str(_price(row.get("low"))),
                    "close": str(_price(row.get("close"))),
                    "volume": str(_volume(row)),
                }
            except ValueError:
                continue

    output_dir = output_root / requested_symbol
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{timeframe.value}.csv"
    rows = [rows_by_timestamp[key] for key in sorted(rows_by_timestamp)]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)

    exact = "exato" if resolution.exact else f"resolvido como {resolution.resolved}"
    print(f"[ok] {requested_symbol:<6} {timeframe.value:<3} {len(rows):>7} candles ({exact})")
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Exporta historico do MT5 para data/historical")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--timeframes", default=",".join(tf.value for tf in DEFAULT_TIMEFRAMES))
    parser.add_argument("--start", default="2012-01-02")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "historical")
    parser.add_argument("--chunk-days", type=int, default=180)
    args = parser.parse_args()

    settings = get_settings()
    terminal = MetaTraderTerminal(settings.mt5_terminal_path)
    info = terminal.connect()
    if not info.connected:
        print(f"[falha] terminal MT5 nao conectado: {info.reason}")
        return 2

    library = terminal.library
    normalizer = BrokerTimeNormalizer(settings.mt5_server_timezone)
    start = datetime.combine(_parse_date(args.start), time.min, tzinfo=UTC)
    end = datetime.combine(_parse_date(args.end), time.max, tzinfo=UTC)
    symbols = _parse_symbols(args.symbols)
    timeframes = _parse_timeframes(args.timeframes)

    print("EXPORTACAO HISTORICA MT5")
    print("=" * 72)
    print(f"Terminal: {info.company} · {info.server}")
    print(f"Periodo : {args.start} a {args.end}")
    print(f"Destino : {args.output}")
    print("Somente leitura: nenhuma ordem sera enviada.")
    print("=" * 72)

    exported = 0
    failures = 0
    for symbol in symbols:
        for timeframe in timeframes:
            try:
                exported += export_symbol_timeframe(
                    library=library,
                    terminal=terminal,
                    normalizer=normalizer,
                    requested_symbol=symbol,
                    timeframe=timeframe,
                    start=start,
                    end=end,
                    output_root=args.output,
                    chunk_days=args.chunk_days,
                )
            except (AmbiguousSymbolError, SymbolNotFoundError, AttributeError, ValueError) as exc:
                failures += 1
                print(f"[falha] {symbol:<6} {timeframe.value:<3} {exc}")

    print("=" * 72)
    print(f"Exportados: {exported} candles")
    print(f"Falhas: {failures}")
    return 1 if exported == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
