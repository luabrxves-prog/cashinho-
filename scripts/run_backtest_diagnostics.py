"""Gera diagnostico de onde a logica do Cashinho ganha, perde ou fica parada.

Exemplo:
    python scripts/run_backtest_diagnostics.py --symbols PETR4 --years 2026

O relatorio cru fica em data/reports/ e os dados de mercado continuam locais.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cashinho.adapters.providers.csv_provider import (  # noqa: E402
    CsvHistoricalProvider,
    ProviderError,
)
from cashinho.core.time.clocks import FrozenClock  # noqa: E402
from cashinho.domain.enums import Mode, Timeframe  # noqa: E402
from cashinho.domain.errors import CashinhoError  # noqa: E402
from cashinho.domain.market import CandleSeries  # noqa: E402
from cashinho.domain.risk import RiskProfile  # noqa: E402
from cashinho.pipeline.backtest import (  # noqa: E402
    BacktestExitMode,
    ExecutionCostModel,
    PipelineDecisionEvaluator,
    run_backtest,
)
from cashinho.pipeline.backtest_diagnostics import (  # noqa: E402
    DiagnosticRow,
    DiagnosticTrade,
    build_diagnostic_trades,
    diagnostic_tables,
)
from cashinho.pipeline.indicators import IndicatorSelection  # noqa: E402
from cashinho.pipeline.market_data import load_market_data  # noqa: E402

DEFAULT_SYMBOLS = ("PETR4", "VALE3", "ITUB4", "BOVA11")
DEFAULT_TIMEFRAMES = (Timeframe.M15, Timeframe.H1, Timeframe.D1)


def _parse_symbols(raw: str) -> tuple[str, ...]:
    return tuple(item.strip().upper() for item in raw.split(",") if item.strip())


def _parse_years(raw: str) -> tuple[int, ...]:
    values = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if "-" in item:
            start, end = item.split("-", 1)
            values.extend(range(int(start), int(end) + 1))
        else:
            values.append(int(item))
    return tuple(dict.fromkeys(values))


def _parse_timeframes(raw: str) -> tuple[Timeframe, ...]:
    return tuple(Timeframe(item.strip()) for item in raw.split(",") if item.strip())


def _load_series(
    provider: CsvHistoricalProvider,
    *,
    symbol: str,
    timeframes: tuple[Timeframe, ...],
    start: datetime,
    end: datetime,
    clock: FrozenClock,
) -> tuple[dict[Timeframe, CandleSeries], tuple[str, ...]]:
    series_by_timeframe = {}
    notes = []
    available = set(provider.get_available_timeframes(symbol))
    for timeframe in timeframes:
        if timeframe not in available:
            notes.append(f"{symbol} sem {timeframe.value}")
            continue
        try:
            loaded = load_market_data(
                provider,
                symbol=symbol,
                timeframe=timeframe,
                start=start,
                end=end,
                clock=clock,
                mode=Mode.BACKTEST,
            )
        except (CashinhoError, ProviderError) as exc:
            notes.append(f"{symbol} {timeframe.value}: {exc}")
            continue
        if loaded.usable_series is None:
            notes.append(f"{symbol} {timeframe.value}: {loaded.report.status.value}")
        else:
            series_by_timeframe[timeframe] = loaded.usable_series
    return series_by_timeframe, tuple(notes)


def _money(value: Decimal | None) -> str:
    return "-" if value is None else f"R$ {value:,.2f}"


def _value(value: object | None, suffix: str = "") -> str:
    return "-" if value is None else f"{value}{suffix}"


def _row_dict(row: DiagnosticRow) -> dict[str, object]:
    metrics = row.metrics
    return {
        "Dimensao": row.dimension,
        "Grupo": row.bucket,
        "Trades": metrics.total_trades,
        "Win rate": metrics.win_rate,
        "Profit factor": metrics.profit_factor,
        "Expectancy": metrics.expectancy,
        "Resultado R$": metrics.net_profit,
        "Drawdown %": metrics.max_drawdown_pct,
        "Total R": metrics.total_r,
    }


def _trade_dict(item: DiagnosticTrade) -> dict[str, object]:
    trade = item.trade
    return {
        "Ativo": trade.symbol,
        "Ano": item.year,
        "Mes": item.month,
        "Hora": item.hour,
        "Lado": item.side,
        "Timeframe": item.timeframe,
        "Regime": item.regime,
        "Volatilidade": item.volatility,
        "Saida": item.close_reason,
        "Resultado": item.result_bucket,
        "P&L": trade.net_pnl,
        "R": trade.result_in_r,
        "Entrada em": trade.entered_at.isoformat(),
        "Saida em": trade.exited_at.isoformat(),
    }


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def render_markdown(
    *,
    diagnostics: tuple[DiagnosticTrade, ...],
    tables: dict[str, tuple[DiagnosticRow, ...]],
    notes: tuple[str, ...],
    output_dir: Path,
) -> str:
    lines = [
        "# Diagnostico operacional do Cashinho",
        "",
        "Este relatorio procura onde a logica funciona, quebra ou fica parada.",
        "Ele nao prova resultado futuro e nao autoriza dinheiro real.",
        "",
        f"- Trades analisados: **{len(diagnostics)}**",
        f"- CSV detalhado: `{output_dir / 'diagnostic_trades.csv'}`",
        f"- CSV agregado: `{output_dir / 'diagnostic_groups.csv'}`",
        "",
    ]
    if notes:
        lines.extend(["## Avisos", ""])
        lines.extend(f"- {note}" for note in notes)
        lines.append("")
    if not diagnostics:
        lines.append("Nenhuma operação concluída nos filtros informados.")
        return "\n".join(lines)

    for dimension, rows in tables.items():
        lines.extend(
            [
                f"## Piores grupos por {dimension}",
                "",
                "| Grupo | Trades | Win rate | Profit factor | Resultado | Drawdown |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for row in rows[:12]:
            metrics = row.metrics
            lines.append(
                f"| {row.bucket} | {metrics.total_trades} | {_value(metrics.win_rate, '%')} | "
                f"{_value(metrics.profit_factor)} | {_money(metrics.net_profit)} | "
                f"{_value(metrics.max_drawdown_pct, '%')} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--years", default="2020-2026")
    parser.add_argument("--timeframes", default=",".join(tf.value for tf in DEFAULT_TIMEFRAMES))
    parser.add_argument("--data-root", type=Path, default=ROOT / "data" / "historical")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "reports" / "diagnostics")
    args = parser.parse_args()

    symbols = _parse_symbols(args.symbols)
    years = _parse_years(args.years)
    timeframes = _parse_timeframes(args.timeframes)
    profile = RiskProfile()
    clock = FrozenClock(datetime(max(years) + 1, 1, 2, tzinfo=UTC))
    provider = CsvHistoricalProvider(args.data_root, clock, name="diagnostics")
    all_diagnostics: list[DiagnosticTrade] = []
    notes: list[str] = []

    for year in years:
        start = datetime.combine(datetime(year, 1, 1).date(), time.min, tzinfo=UTC)
        end = datetime.combine(datetime(year, 12, 31).date(), time.min, tzinfo=UTC) + timedelta(days=1)
        year_clock = FrozenClock(end + timedelta(days=1))
        for symbol in symbols:
            target, target_notes = _load_series(
                provider,
                symbol=symbol,
                timeframes=timeframes,
                start=start,
                end=end,
                clock=year_clock,
            )
            notes.extend(f"{year} {note}" for note in target_notes)
            if len(target) < 2:
                notes.append(f"{year} {symbol}: menos de dois timeframes validos")
                continue
            market_context = {}
            for market_symbol in (item for item in symbols if item != symbol):
                loaded, market_notes = _load_series(
                    provider,
                    symbol=market_symbol,
                    timeframes=timeframes,
                    start=start,
                    end=end,
                    clock=year_clock,
                )
                notes.extend(f"{year} {note}" for note in market_notes)
                if loaded:
                    market_context[market_symbol] = loaded
            evaluator = PipelineDecisionEvaluator(
                IndicatorSelection(
                    ema_periods=(9, 21),
                    vwap=True,
                    rsi_period=14,
                    macd=True,
                    atr_period=14,
                ),
                profile,
                market_series_by_symbol=market_context,
            )
            result = run_backtest(
                target,
                evaluator,
                risk_profile=profile,
                costs=ExecutionCostModel(),
                exit_mode=BacktestExitMode.FIXED,
            )
            all_diagnostics.extend(
                build_diagnostic_trades(result.trades, series_by_timeframe=target)
            )

    diagnostics = tuple(all_diagnostics)
    tables = diagnostic_tables(diagnostics, initial_capital=profile.capital)
    trade_rows = [_trade_dict(item) for item in diagnostics]
    group_rows = [
        _row_dict(row)
        for rows in tables.values()
        for row in rows
    ]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(args.output_dir / "diagnostic_trades.csv", trade_rows)
    _write_csv(args.output_dir / "diagnostic_groups.csv", group_rows)
    markdown = render_markdown(
        diagnostics=diagnostics,
        tables=tables,
        notes=tuple(dict.fromkeys(notes)),
        output_dir=args.output_dir,
    )
    report_path = args.output_dir / "diagnostic_report.md"
    report_path.write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
