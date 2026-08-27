"""Roda uma bateria de cenarios historicos do Cashinho.

Uso:
    python scripts/run_scenario_suite.py

O script nao baixa cotacoes e nao inventa dados. Cada cenario aponta para uma
pasta CSV local no mesmo formato do CsvHistoricalProvider:

    <raiz>/<ATIVO>/<timeframe>.csv

Se a pasta historica real ainda nao existir, o cenario aparece como SKIP no
relatorio.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

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
    BacktestComparison,
    ExecutionCostModel,
    PipelineDecisionEvaluator,
    compare_exit_modes,
)
from cashinho.pipeline.indicators import IndicatorSelection  # noqa: E402
from cashinho.pipeline.market_data import load_market_data  # noqa: E402


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    name: str
    symbol: str
    start: date
    end: date
    data_root: Path
    timeframes: tuple[Timeframe, ...]
    market_symbols: tuple[str, ...]
    expected_behavior: str
    source_note: str
    checks: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ScenarioReport:
    scenario: Scenario
    status: str
    notes: tuple[str, ...]
    comparison: BacktestComparison | None = None


def _parse_date(raw: str) -> date:
    return date.fromisoformat(raw)


def _parse_timeframes(values: list[str]) -> tuple[Timeframe, ...]:
    return tuple(Timeframe(value) for value in values)


def _money(value: Decimal | None) -> str:
    return "—" if value is None else f"R$ {value:,.2f}"


def _value(value: object | None, suffix: str = "") -> str:
    return "—" if value is None else f"{value}{suffix}"


def load_scenarios(path: Path) -> tuple[Scenario, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    scenarios = []
    for raw in payload.get("scenarios", []):
        scenarios.append(
            Scenario(
                id=raw["id"],
                name=raw["name"],
                symbol=raw["symbol"].upper(),
                start=_parse_date(raw["start"]),
                end=_parse_date(raw["end"]),
                data_root=(ROOT / raw.get("data_root", "data/historical")).resolve(),
                timeframes=_parse_timeframes(raw.get("timeframes", ["1m", "5m", "15m", "60m", "1D"])),
                market_symbols=tuple(symbol.upper() for symbol in raw.get("market_symbols", ())),
                expected_behavior=raw.get("expected_behavior", ""),
                source_note=raw.get("source_note", ""),
                checks=dict(raw.get("checks", {})),
            )
        )
    return tuple(scenarios)


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
            notes.append(
                f"{symbol} {timeframe.value}: "
                f"{loaded.rejection_reason or loaded.report.status.value}"
            )
        else:
            series_by_timeframe[timeframe] = loaded.usable_series
    return series_by_timeframe, tuple(notes)


def _evaluate_checks(comparison: BacktestComparison, checks: dict[str, Any]) -> tuple[str, ...]:
    metrics = comparison.dynamic.metrics
    notes = []
    if metrics.total_trades == 0 and not checks.get("allow_no_trades", False):
        notes.append("nenhuma entrada concluida")
    max_drawdown_pct = checks.get("max_drawdown_pct")
    if (
        max_drawdown_pct is not None
        and metrics.max_drawdown_pct is not None
        and metrics.max_drawdown_pct > Decimal(str(max_drawdown_pct))
    ):
        notes.append(
            f"drawdown {metrics.max_drawdown_pct}% acima do limite {max_drawdown_pct}%"
        )
    min_profit_factor = checks.get("min_profit_factor")
    if min_profit_factor is not None:
        if metrics.profit_factor is None:
            if metrics.total_trades > 0 and metrics.losses == 0:
                pass
            else:
                notes.append("profit factor indisponivel")
        elif metrics.profit_factor < Decimal(str(min_profit_factor)):
            notes.append(
                f"profit factor {metrics.profit_factor} abaixo de {min_profit_factor}"
            )
    max_trades = checks.get("max_trades")
    if max_trades is not None and metrics.total_trades > int(max_trades):
        notes.append(f"trades demais para o cenario: {metrics.total_trades} > {max_trades}")
    return tuple(notes)


def run_scenario(scenario: Scenario) -> ScenarioReport:
    if not scenario.data_root.is_dir():
        return ScenarioReport(
            scenario,
            "SKIP",
            (f"pasta de dados nao encontrada: {scenario.data_root}",),
        )

    start = datetime.combine(scenario.start, time.min, tzinfo=UTC)
    end = datetime.combine(scenario.end, time.min, tzinfo=UTC) + timedelta(days=1)
    clock = FrozenClock(end + timedelta(days=1))
    provider = CsvHistoricalProvider(scenario.data_root, clock, name="scenario-suite")

    target, notes = _load_series(
        provider,
        symbol=scenario.symbol,
        timeframes=scenario.timeframes,
        start=start,
        end=end,
        clock=clock,
    )
    if len(target) < 2:
        return ScenarioReport(
            scenario,
            "SKIP",
            (*notes, "menos de dois timeframes validos para FinalDecision"),
        )

    market_symbols = scenario.market_symbols or tuple(
        symbol for symbol in provider.list_symbols() if symbol != scenario.symbol
    )
    market_context = {}
    for symbol in market_symbols:
        loaded, market_notes = _load_series(
            provider,
            symbol=symbol,
            timeframes=scenario.timeframes,
            start=start,
            end=end,
            clock=clock,
        )
        notes = (*notes, *market_notes)
        if loaded:
            market_context[symbol] = loaded

    profile = RiskProfile()
    evaluator = PipelineDecisionEvaluator(
        IndicatorSelection(ema_periods=(9, 21), vwap=True, rsi_period=14, macd=True, atr_period=14),
        profile,
        market_series_by_symbol=market_context,
    )
    comparison = compare_exit_modes(
        target,
        evaluator,
        risk_profile=profile,
        costs=ExecutionCostModel(),
    )
    failures = _evaluate_checks(comparison, scenario.checks)
    status = "FAIL" if failures else "PASS"
    return ScenarioReport(scenario, status, (*notes, *failures), comparison)


def render_markdown(reports: tuple[ScenarioReport, ...]) -> str:
    lines = [
        "# Relatorio de cenarios historicos do Cashinho",
        "",
        "Este relatorio e uma simulacao tecnica. Resultado historico nao garante resultado futuro.",
        "Cenarios sem CSV real aparecem como SKIP para evitar falsa conclusao.",
        "",
        "| Status | Cenario | Trades | Win rate | Profit factor | Resultado | Drawdown | Observacao |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for report in reports:
        if report.comparison is None:
            lines.append(
                f"| {report.status} | {report.scenario.name} | — | — | — | — | — | "
                f"{'; '.join(report.notes)} |"
            )
            continue
        metrics = report.comparison.dynamic.metrics
        lines.append(
            f"| {report.status} | {report.scenario.name} | {metrics.total_trades} | "
            f"{_value(metrics.win_rate, '%')} | {_value(metrics.profit_factor)} | "
            f"{_money(metrics.net_profit)} | {_value(metrics.max_drawdown_pct, '%')} | "
            f"{'; '.join(report.notes) or report.scenario.expected_behavior} |"
        )
    lines.extend(["", "## Detalhes", ""])
    for report in reports:
        lines.extend(
            [
                f"### {report.scenario.name}",
                "",
                f"- ID: `{report.scenario.id}`",
                f"- Ativo: `{report.scenario.symbol}`",
                f"- Periodo: {report.scenario.start.isoformat()} a {report.scenario.end.isoformat()}",
                f"- Base esperada: {report.scenario.expected_behavior or 'nao definida'}",
                f"- Fonte/contexto: {report.scenario.source_note or 'nao informado'}",
                f"- Status: **{report.status}**",
            ]
        )
        if report.notes:
            lines.append(f"- Notas: {'; '.join(report.notes)}")
        if report.comparison is not None:
            fixed = report.comparison.fixed.metrics
            dynamic = report.comparison.dynamic.metrics
            lines.extend(
                [
                    f"- Saida fixa: {fixed.total_trades} trades, resultado {_money(fixed.net_profit)}, drawdown {_value(fixed.max_drawdown_pct, '%')}",
                    f"- Saida dinamica: {dynamic.total_trades} trades, resultado {_money(dynamic.net_profit)}, drawdown {_value(dynamic.max_drawdown_pct, '%')}",
                ]
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "docs" / "scenario_suite.example.json",
        help="Arquivo JSON com a lista de cenarios.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "reports" / "scenario_suite.md",
        help="Destino do relatorio Markdown.",
    )
    args = parser.parse_args()

    scenarios = load_scenarios(args.config)
    reports = tuple(run_scenario(scenario) for scenario in scenarios)
    markdown = render_markdown(reports)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    print(markdown)
    return 1 if any(report.status == "FAIL" for report in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
