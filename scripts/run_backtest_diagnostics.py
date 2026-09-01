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
from time import perf_counter

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
    BacktestDecisionLog,
    BacktestExitMode,
    PipelineDecisionEvaluator,
    calculate_metrics,
    run_backtest,
)
from cashinho.pipeline.backtest_diagnostics import (  # noqa: E402
    DiagnosticRow,
    DiagnosticTrade,
    build_diagnostic_trades,
    diagnostic_tables,
)
from cashinho.pipeline.data_provenance import (  # noqa: E402
    DataProvenanceError,
    assert_mt5_provenance,
)
from cashinho.pipeline.execution_costs import (  # noqa: E402
    CostScenario,
    cost_scenario_config,
    parse_cost_scenarios,
)
from cashinho.pipeline.indicators import IndicatorSelection  # noqa: E402
from cashinho.pipeline.learning_diagnostics import (  # noqa: E402
    AnnualLearningReport,
    DailyLearningReport,
    ErrorCauseSummary,
    FilterContribution,
    LossAutopsy,
    MissedOpportunity,
    SimulatedMissedTrade,
    analyze_filter_contribution,
    build_annual_learning_reports,
    build_daily_learning_reports,
    build_loss_autopsies,
    find_missed_opportunities,
    simulate_missed_opportunity_trades,
    summarize_error_causes,
)
from cashinho.pipeline.market_data import load_market_data  # noqa: E402
from cashinho.pipeline.monte_carlo import MonteCarloSummary, run_monte_carlo  # noqa: E402
from cashinho.pipeline.operational_line import (  # noqa: E402
    OperationalLineResult,
    compare_operational_lines,
)
from cashinho.pipeline.operational_policy import (  # noqa: E402
    OperationalPolicy,
    build_policy_from_diagnostics,
    load_operational_policy,
    save_operational_policy,
)
from cashinho.pipeline.operational_readiness import (  # noqa: E402
    OperationalReadiness,
    ReadinessFactor,
    evaluate_operational_readiness,
)
from cashinho.pipeline.policy_validation import (  # noqa: E402
    PolicyHoldoutResult,
    PolicyHoldoutRow,
    validate_policy_holdout,
)
from cashinho.pipeline.score_calibration import (  # noqa: E402
    ScoreCalibrationRow,
    calibrate_scores,
    score_calibration_verdict,
)
from cashinho.pipeline.walk_forward import WalkForwardWindow, rolling_walk_forward  # noqa: E402

DEFAULT_SYMBOLS = ("PETR4", "VALE3", "ITUB4", "BOVA11")
DEFAULT_TIMEFRAMES = (Timeframe.M15, Timeframe.H1, Timeframe.D1)
FULL_HISTORY_START = datetime(1900, 1, 1, tzinfo=UTC)
FULL_HISTORY_END = datetime(2100, 1, 1, tzinfo=UTC)
FAST_VALIDATION_DECISION_POINTS = 40


class CachedCsvHistoricalProvider(CsvHistoricalProvider):
    """Carrega cada CSV uma vez e fatia os anos em memoria."""

    def __init__(self, root: Path, clock: FrozenClock, *, name: str = "csv") -> None:
        super().__init__(root, clock, name=name)
        self._full_cache: dict[tuple[str, Timeframe], CandleSeries] = {}

    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        *,
        start: datetime,
        end: datetime,
    ) -> CandleSeries:
        key = (symbol.upper(), timeframe)
        series = self._full_cache.get(key)
        if series is None:
            series = super().get_candles(
                symbol,
                timeframe,
                start=FULL_HISTORY_START,
                end=FULL_HISTORY_END,
            )
            self._full_cache[key] = series
        candles = tuple(
            candle
            for candle in series.candles
            if start <= candle.open_time < end
        )
        return series.model_copy(update={"candles": candles})


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


def _load_universe(
    provider: CsvHistoricalProvider,
    *,
    symbols: tuple[str, ...],
    timeframes: tuple[Timeframe, ...],
    start: datetime,
    end: datetime,
    clock: FrozenClock,
) -> tuple[dict[str, dict[Timeframe, CandleSeries]], tuple[str, ...]]:
    universe: dict[str, dict[Timeframe, CandleSeries]] = {}
    notes = []
    for symbol in symbols:
        loaded, symbol_notes = _load_series(
            provider,
            symbol=symbol,
            timeframes=timeframes,
            start=start,
            end=end,
            clock=clock,
        )
        universe[symbol] = loaded
        notes.extend(symbol_notes)
    return universe, tuple(notes)


def _money(value: Decimal | None) -> str:
    return "-" if value is None else f"R$ {value:,.2f}"


def _value(value: object | None, suffix: str = "") -> str:
    return "-" if value is None else f"{value}{suffix}"


def _md_cell(value: object | None) -> str:
    return _value(value).replace("|", "\\|")


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
        "Score": trade.score,
        "Faixa score": item.score_bucket,
        "Setup": item.setup_type,
        "Regime": item.regime,
        "Volatilidade": item.volatility,
        "Saida": item.close_reason,
        "Resultado": item.result_bucket,
        "P&L": trade.net_pnl,
        "R": trade.result_in_r,
        "Entrada em": trade.entered_at.isoformat(),
        "Saida em": trade.exited_at.isoformat(),
    }


def _cost_row(
    *,
    scenario: CostScenario,
    year: int,
    symbol: str,
    trades: int,
    net_profit: Decimal,
    win_rate: Decimal | None,
    profit_factor: Decimal | None,
    max_drawdown_pct: Decimal | None,
) -> dict[str, object]:
    return {
        "Cenario": scenario.value,
        "Ano": year,
        "Ativo": symbol,
        "Trades": trades,
        "Resultado R$": net_profit,
        "Win rate": win_rate,
        "Profit factor": profit_factor,
        "Drawdown %": max_drawdown_pct,
    }


def _score_row(row: ScoreCalibrationRow) -> dict[str, object]:
    metrics = row.metrics
    return {
        "Faixa score": row.bucket,
        "Trades": metrics.total_trades,
        "Win rate": metrics.win_rate,
        "Expectancy": metrics.expectancy,
        "Resultado R$": metrics.net_profit,
        "Profit factor": metrics.profit_factor,
        "Drawdown %": metrics.max_drawdown_pct,
    }


def _monte_carlo_row(summary: MonteCarloSummary | None) -> dict[str, object]:
    if summary is None:
        return {}
    return {
        "Simulacoes": summary.simulations,
        "Trades por simulacao": summary.trades_per_simulation,
        "Capital final mediano": summary.median_final_equity,
        "Capital final p05": summary.final_equity_p05,
        "Capital final p95": summary.final_equity_p95,
        "Drawdown p50 %": summary.drawdown_p50_pct,
        "Drawdown p95 %": summary.drawdown_p95_pct,
        "Sequencia perda p95": summary.loss_streak_p95,
        "Chance retorno negativo %": summary.probability_negative_return_pct,
        "Risco de ruina %": summary.risk_of_ruin_pct,
    }


def _walk_forward_row(window: WalkForwardWindow) -> dict[str, object]:
    return {
        "Janela": window.index,
        "Treino inicio": window.train_start.isoformat(),
        "Treino fim": window.train_end.isoformat(),
        "Teste inicio": window.test_start.isoformat(),
        "Teste fim": window.test_end.isoformat(),
        "Trades treino": window.train_metrics.total_trades,
        "Resultado treino R$": window.train_metrics.net_profit,
        "Win rate treino": window.train_metrics.win_rate,
        "Trades teste": window.test_metrics.total_trades,
        "Resultado teste R$": window.test_metrics.net_profit,
        "Win rate teste": window.test_metrics.win_rate,
        "Profit factor teste": window.test_metrics.profit_factor,
        "Drawdown teste %": window.test_metrics.max_drawdown_pct,
    }


def _decision_row(decision: BacktestDecisionLog) -> dict[str, object]:
    return {
        "Ativo": decision.symbol,
        "Data": decision.timestamp.isoformat(),
        "Lado": decision.side,
        "Timeframe": decision.timeframe.value if decision.timeframe else "",
        "Score": decision.score,
        "Setup": decision.setup_type,
        "Entrou": decision.should_enter,
        "Motivo principal": decision.primary_reason,
        "Motivos": " | ".join(decision.reasons),
    }


def _decision_reason_rows(decisions: list[BacktestDecisionLog]) -> list[dict[str, object]]:
    counts: dict[str, int] = {}
    for decision in decisions:
        if decision.should_enter:
            continue
        counts[decision.primary_reason] = counts.get(decision.primary_reason, 0) + 1
    return [
        {"Motivo": reason, "Ocorrencias": count}
        for reason, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    ]


def _policy_replay_rows(
    diagnostics: tuple[DiagnosticTrade, ...],
    *,
    policy: OperationalPolicy,
    initial_capital: Decimal,
) -> list[dict[str, object]]:
    allowed = []
    blocked = []
    for item in diagnostics:
        decision = policy.evaluate(
            symbol=item.symbol,
            timestamp=item.trade.entered_at,
            timeframe=item.trade.timeframe,
            side=item.side,
            score=item.trade.score,
            setup_type=item.setup_type,
            regime=item.regime,
            volatility=item.volatility,
        )
        (allowed if decision.approved else blocked).append(item.trade)
    rows = []
    for label, trades in {
        "ANTES_POLITICA": [item.trade for item in diagnostics],
        "APROVADOS": allowed,
        "BLOQUEADOS": blocked,
    }.items():
        metrics = calculate_metrics(trades, initial_capital=initial_capital)[0]
        rows.append(
            {
                "Grupo": label,
                "Trades": metrics.total_trades,
                "Win rate": metrics.win_rate,
                "Profit factor": metrics.profit_factor,
                "Resultado R$": metrics.net_profit,
                "Drawdown %": metrics.max_drawdown_pct,
            }
        )
    return rows


def _policy_holdout_row(row: PolicyHoldoutRow) -> dict[str, object]:
    metrics = row.metrics
    return {
        "Grupo": row.group,
        "Treino ate": row.train_until_year,
        "Teste desde": row.test_start_year,
        "Trades": row.trades,
        "Win rate": metrics.win_rate,
        "Profit factor": metrics.profit_factor,
        "Resultado R$": metrics.net_profit,
        "Drawdown %": metrics.max_drawdown_pct,
    }


def _loss_autopsy_row(row: LossAutopsy) -> dict[str, object]:
    return {
        "Ativo": row.symbol,
        "Entrada": row.entered_at.isoformat(),
        "Setup": row.setup_type,
        "Regime": row.regime,
        "Volatilidade": row.volatility,
        "Hora": row.hour,
        "Resultado R$": row.net_pnl,
        "Custos": row.costs,
        "MAE": row.mae,
        "MFE": row.mfe,
        "Causa principal": row.primary_cause,
        "Explicacao": row.explanation,
        "Hipotese de correcao": row.correction_hypothesis,
        "Erro do modelo": row.is_model_error,
    }


def _error_cause_row(row: ErrorCauseSummary) -> dict[str, object]:
    return {
        "Causa": row.cause,
        "Ocorrencias": row.occurrences,
        "Prejuizo R$": row.net_loss,
        "% perdas": row.pct_of_total_loss,
        "Setups afetados": " | ".join(row.setups),
        "Horarios afetados": " | ".join(row.hours),
        "Regimes afetados": " | ".join(row.regimes),
        "Hipotese de correcao": row.correction_hypothesis,
    }


def _daily_learning_row(row: DailyLearningReport) -> dict[str, object]:
    return {
        "Data": row.day.isoformat(),
        "Ativo": row.symbol,
        "Candles analisados": row.candles_analyzed,
        "Oportunidades encontradas": row.opportunities_found,
        "Entradas": row.entries,
        "Vitorias": row.wins,
        "Perdas": row.losses,
        "Zero": row.flats,
        "Evitadas": row.avoided,
        "Principal motivo nao entrar": row.main_avoidance_reason,
        "Lucro bruto": row.gross_profit,
        "Prejuizo bruto": row.gross_loss,
        "Resultado liquido": row.net_result,
        "Custos": row.costs,
        "Win rate": row.win_rate,
        "Payoff": row.payoff,
        "Profit factor": row.profit_factor,
        "Drawdown intradiario": row.intraday_drawdown,
        "Maior sequencia perdas": row.max_loss_streak,
        "Maior sequencia ganhos": row.max_win_streak,
        "MAE medio": row.average_mae,
        "MFE medio": row.average_mfe,
        "Score medio": row.average_score,
        "Classificacao": row.classification,
        "Principal erro": row.main_error,
        "Principal acerto": row.main_win,
        "Aprendizado": row.learning,
    }


def _annual_learning_row(row: AnnualLearningReport) -> dict[str, object]:
    metrics = row.metrics
    return {
        "Ano": row.year,
        "Ativo": row.symbol,
        "Pregoes analisados": row.days_analyzed,
        "Dias operados": row.days_traded,
        "Dias sem operar": row.days_not_traded,
        "% dias operados": row.traded_days_pct,
        "Total operacoes": row.total_trades,
        "Media operacoes por dia": row.average_trades_per_day,
        "Vitorias": metrics.wins,
        "Perdas": metrics.losses,
        "Win rate": metrics.win_rate,
        "Resultado liquido": metrics.net_profit,
        "Profit factor": metrics.profit_factor,
        "Payoff": metrics.payoff,
        "Expectancy": metrics.expectancy,
        "Drawdown maximo": metrics.max_drawdown_pct,
        "Sharpe": metrics.sharpe,
        "Sortino": metrics.sortino,
        "Melhores condicoes": " | ".join(row.best_conditions),
        "Piores condicoes": " | ".join(row.worst_conditions),
        "Causas perdas": " | ".join(row.most_common_loss_causes),
        "Motivos nao operar": " | ".join(row.most_common_avoidance_reasons),
    }


def _filter_contribution_row(row: FilterContribution) -> dict[str, object]:
    return {
        "Filtro/motivo": row.reason,
        "Ocorrencias": row.occurrences,
        "Score medio": row.average_score,
        "Ativos afetados": " | ".join(row.affected_symbols),
        "Setups afetados": " | ".join(row.affected_setups),
        "Observacao": row.note,
    }


def _missed_opportunity_row(row: MissedOpportunity) -> dict[str, object]:
    return {
        "Ativo": row.symbol,
        "Data": row.timestamp.isoformat(),
        "Lado": row.side,
        "Timeframe": row.timeframe,
        "Score": row.score,
        "Setup": row.setup_type,
        "Motivo bloqueio": row.blocked_reason,
        "Candles futuros avaliados": row.horizon_candles,
        "Movimento favoravel": row.favorable_move,
        "Movimento contra": row.adverse_move,
        "Favoravel/contra": row.favorable_to_adverse,
        "Veredito": row.verdict,
        "Aprendizado": row.learning,
    }


def _simulated_missed_trade_row(row: SimulatedMissedTrade) -> dict[str, object]:
    trade = row.trade
    return {
        "Ativo": trade.symbol,
        "Sinal": trade.signal_at.isoformat(),
        "Entrada simulada": trade.entered_at.isoformat(),
        "Saida simulada": trade.exited_at.isoformat(),
        "Lado": trade.side,
        "Timeframe": trade.timeframe.value,
        "Score": trade.score,
        "Setup": trade.setup_type,
        "Motivo bloqueio": row.blocked_reason,
        "Entrada": trade.planned_entry,
        "Stop": trade.stop,
        "Alvo": trade.target,
        "Quantidade": trade.quantity,
        "Motivo saida": trade.close_reason,
        "Resultado bruto": trade.gross_pnl,
        "Custos": trade.costs,
        "Resultado liquido": trade.net_pnl,
        "Resultado R": trade.result_in_r,
        "Veredito": row.verdict,
        "Aprendizado": row.learning,
    }


def _operational_line_row(row: OperationalLineResult) -> dict[str, object]:
    return {
        "Linha": row.candidate.name,
        "Score minimo": row.candidate.minimum_score,
        "Setups permitidos": " | ".join(row.candidate.allowed_setups),
        "Treino ate": row.train_until_year,
        "Teste desde": row.test_start_year,
        "Trades treino": row.train_trades,
        "Trades teste": row.test_trades,
        "Resultado teste": row.test_metrics.net_profit,
        "Expectancy teste": row.test_metrics.expectancy,
        "Win rate teste": row.test_metrics.win_rate,
        "Profit factor teste": row.test_metrics.profit_factor,
        "Drawdown teste": row.test_metrics.max_drawdown_pct,
        "Estabilidade mensal": row.monthly_stability_pct,
        "Setups dominantes": " | ".join(row.dominant_setups),
        "Aprovada": row.approved,
        "Motivos reprovacao": " | ".join(row.rejection_reasons),
    }


def _readiness_factor_row(row: ReadinessFactor) -> dict[str, object]:
    return {
        "Area": row.area,
        "Criterio": row.name,
        "Pontos": row.points,
        "Maximo": row.max_points,
        "Explicacao": row.explanation,
    }


def _readiness_summary_row(row: OperationalReadiness) -> dict[str, object]:
    return {
        "Confiabilidade tecnica %": row.technical_pct,
        "Confiabilidade operacional %": row.operational_pct,
        "Veredito": row.verdict,
    }


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _timing_row(label: str, seconds: float, **extra: object) -> dict[str, object]:
    return {"component": label, "seconds": round(seconds, 4), **extra}


def render_markdown(
    *,
    diagnostics: tuple[DiagnosticTrade, ...],
    tables: dict[str, tuple[DiagnosticRow, ...]],
    cost_rows: list[dict[str, object]],
    score_rows: tuple[ScoreCalibrationRow, ...],
    score_verdict: str,
    monte_carlo: MonteCarloSummary | None,
    walk_forward: tuple[WalkForwardWindow, ...],
    policy_replay_rows: list[dict[str, object]],
    policy_holdout: PolicyHoldoutResult | None,
    decision_reason_rows: list[dict[str, object]],
    loss_autopsies: tuple[LossAutopsy, ...],
    error_causes: tuple[ErrorCauseSummary, ...],
    daily_reports: tuple[DailyLearningReport, ...],
    annual_reports: tuple[AnnualLearningReport, ...],
    filter_contribution: tuple[FilterContribution, ...],
    missed_opportunities: tuple[MissedOpportunity, ...],
    simulated_missed_trades: tuple[SimulatedMissedTrade, ...],
    operational_lines: tuple[OperationalLineResult, ...],
    simulated_operational_lines: tuple[OperationalLineResult, ...],
    readiness: OperationalReadiness,
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
        f"- CSV de custos: `{output_dir / 'cost_scenarios.csv'}`",
        f"- CSV de score: `{output_dir / 'score_calibration.csv'}`",
        f"- CSV Monte Carlo: `{output_dir / 'monte_carlo.csv'}`",
        f"- CSV walk-forward: `{output_dir / 'walk_forward.csv'}`",
        f"- CSV replay politica: `{output_dir / 'policy_replay.csv'}`",
        f"- CSV holdout politica: `{output_dir / 'policy_holdout.csv'}`",
        f"- CSV decisoes: `{output_dir / 'decision_audit.csv'}`",
        f"- CSV motivos bloqueio: `{output_dir / 'decision_reasons.csv'}`",
        f"- CSV autopsia perdas: `{output_dir / 'loss_autopsy.csv'}`",
        f"- CSV causas prejuizo: `{output_dir / 'error_causes.csv'}`",
        f"- CSV aprendizado diario: `{output_dir / 'daily_learning.csv'}`",
        f"- CSV aprendizado anual: `{output_dir / 'annual_learning.csv'}`",
        f"- CSV contribuicao filtros: `{output_dir / 'filter_contribution.csv'}`",
        f"- CSV oportunidades perdidas: `{output_dir / 'missed_opportunities.csv'}`",
        f"- CSV trades simulados bloqueados: `{output_dir / 'simulated_missed_trades.csv'}`",
        f"- CSV linhas operacionais: `{output_dir / 'operational_lines.csv'}`",
        f"- CSV linhas simuladas: `{output_dir / 'simulated_operational_lines.csv'}`",
        f"- CSV prontidao operacional: `{output_dir / 'operational_readiness.csv'}`",
        "",
    ]
    if notes:
        lines.extend(["## Avisos", ""])
        lines.extend(f"- {note}" for note in notes)
        lines.append("")
    if not diagnostics and not simulated_missed_trades:
        if cost_rows:
            lines.extend(
                [
                    "## Custos operacionais",
                    "",
                    "| Cenario | Ano | Ativo | Trades | Resultado | Win rate | Profit factor | Drawdown |",
                    "|---|---:|---|---:|---:|---:|---:|---:|",
                ]
            )
            for row in cost_rows[:24]:
                lines.append(
                    f"| {row['Cenario']} | {row['Ano']} | {row['Ativo']} | {row['Trades']} | "
                    f"{_money(row['Resultado R$'])} | {_value(row['Win rate'], '%')} | "
                    f"{_value(row['Profit factor'])} | {_value(row['Drawdown %'], '%')} |"
                )
            lines.append("")
        if decision_reason_rows:
            lines.extend(
                [
                    "## Principais bloqueios",
                    "",
                    "| Motivo | Ocorrencias |",
                    "|---|---:|",
                ]
            )
            for row in decision_reason_rows[:12]:
                lines.append(f"| {_md_cell(row['Motivo'])} | {row['Ocorrencias']} |")
            lines.append("")
        lines.append("Nenhuma operação concluída nos filtros informados.")
        return "\n".join(lines)

    if cost_rows:
        lines.extend(
            [
                "## Custos operacionais",
                "",
                "| Cenario | Ano | Ativo | Trades | Resultado | Win rate | Profit factor | Drawdown |",
                "|---|---:|---|---:|---:|---:|---:|---:|",
            ]
        )
        for row in cost_rows[:24]:
            lines.append(
                f"| {row['Cenario']} | {row['Ano']} | {row['Ativo']} | {row['Trades']} | "
                f"{_money(row['Resultado R$'])} | {_value(row['Win rate'], '%')} | "
                f"{_value(row['Profit factor'])} | {_value(row['Drawdown %'], '%')} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Calibracao do score",
            "",
            f"- Score acompanha resultado historico: **{score_verdict}**",
            "",
            "| Faixa | Trades | Win rate | Expectancy | Resultado | Profit factor | Drawdown |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in score_rows:
        metrics = row.metrics
        lines.append(
            f"| {row.bucket} | {metrics.total_trades} | {_value(metrics.win_rate, '%')} | "
            f"{_value(metrics.expectancy)} | {_money(metrics.net_profit)} | "
            f"{_value(metrics.profit_factor)} | {_value(metrics.max_drawdown_pct, '%')} |"
        )
    lines.append("")

    if monte_carlo is not None:
        lines.extend(
            [
                "## Monte Carlo",
                "",
                f"- Simulacoes: **{monte_carlo.simulations}**",
                f"- Capital final mediano: **{_money(monte_carlo.median_final_equity)}**",
                f"- Pior 5% de capital final: **{_money(monte_carlo.final_equity_p05)}**",
                f"- Drawdown p95: **{_value(monte_carlo.drawdown_p95_pct, '%')}**",
                f"- Sequencia de perdas p95: **{monte_carlo.loss_streak_p95}**",
                f"- Chance de retorno negativo: **{_value(monte_carlo.probability_negative_return_pct, '%')}**",
                f"- Risco de ruina: **{_value(monte_carlo.risk_of_ruin_pct, '%')}**",
                "",
            ]
        )

    if error_causes:
        lines.extend(
            [
                "## Aprendizado do Cashinho",
                "",
                "Ranking das causas prováveis de prejuízo. Uma causa só vira correção principal depois de passar por holdout, walk-forward e custos.",
                "",
                "| Causa | Ocorrencias | Prejuizo | % perdas | Setups | Hipotese |",
                "|---|---:|---:|---:|---|---|",
            ]
        )
        for row in error_causes[:12]:
            lines.append(
                f"| {row.cause} | {row.occurrences} | {_money(row.net_loss)} | "
                f"{_value(row.pct_of_total_loss, '%')} | {_md_cell(', '.join(row.setups))} | "
                f"{_md_cell(row.correction_hypothesis)} |"
            )
        lines.append("")

    if annual_reports:
        lines.extend(
            [
                "## Relatorio anual",
                "",
                "| Ano | Ativo | Pregoes | Dias operados | Dias sem operar | Trades | Win rate | Resultado | Expectancy | Profit factor | Drawdown |",
                "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in annual_reports[:24]:
            metrics = row.metrics
            lines.append(
                f"| {row.year} | {row.symbol} | {row.days_analyzed} | {row.days_traded} | "
                f"{row.days_not_traded} | {row.total_trades} | {_value(metrics.win_rate, '%')} | "
                f"{_money(metrics.net_profit)} | {_value(metrics.expectancy)} | "
                f"{_value(metrics.profit_factor)} | {_value(metrics.max_drawdown_pct, '%')} |"
            )
        lines.append("")

    if daily_reports:
        lines.extend(
            [
                "## Amostra do estudo diario",
                "",
                "Cada pregão com candle disponível entra no estudo, inclusive dias sem operação.",
                "",
                "| Data | Ativo | Candles | Oportunidades | Entradas | Evitadas | Resultado | Classificacao | Aprendizado |",
                "|---|---|---:|---:|---:|---:|---:|---|---|",
            ]
        )
        for row in daily_reports[:20]:
            lines.append(
                f"| {row.day.isoformat()} | {row.symbol} | {row.candles_analyzed} | "
                f"{row.opportunities_found} | {row.entries} | {row.avoided} | "
                f"{_money(row.net_result)} | {_md_cell(row.classification)} | "
                f"{_md_cell(row.learning)} |"
            )
        lines.append("")

    if filter_contribution:
        lines.extend(
            [
                "## Contribuicao dos filtros",
                "",
                "| Filtro ou motivo | Ocorrencias | Score medio | Ativos | Setups |",
                "|---|---:|---:|---|---|",
            ]
        )
        for row in filter_contribution[:12]:
            lines.append(
                f"| {_md_cell(row.reason)} | {row.occurrences} | {_value(row.average_score)} | "
                f"{_md_cell(', '.join(row.affected_symbols))} | {_md_cell(', '.join(row.affected_setups))} |"
            )
        lines.append("")

    if missed_opportunities:
        conservative = sum(
            1
            for row in missed_opportunities
            if row.verdict == "BLOQUEIO_POSSIVELMENTE_CONSERVADOR"
        )
        lines.extend(
            [
                "## Oportunidades perdidas",
                "",
                (
                    "Analise contrafactual: usa candles posteriores apenas para aprender "
                    "se um bloqueio pode ter sido conservador demais."
                ),
                f"- Bloqueios possivelmente conservadores: **{conservative}**",
                "",
                "| Data | Ativo | Setup | Score | Motivo bloqueio | Veredito | Aprendizado |",
                "|---|---|---|---:|---|---|---|",
            ]
        )
        for row in missed_opportunities[:20]:
            lines.append(
                f"| {row.timestamp.isoformat()} | {row.symbol} | {row.setup_type} | "
                f"{row.score} | {_md_cell(row.blocked_reason)} | {row.verdict} | "
                f"{_md_cell(row.learning)} |"
            )
        lines.append("")

    if simulated_missed_trades:
        metrics = calculate_metrics(
            [row.trade for row in simulated_missed_trades],
            initial_capital=Decimal("100"),
        )[0]
        winners = sum(1 for row in simulated_missed_trades if row.trade.net_pnl > 0)
        lines.extend(
            [
                "## Simulacao das oportunidades bloqueadas",
                "",
                (
                    "Reproduz entradas que foram bloqueadas, usando o plano técnico que existia "
                    "naquele candle. Isso mede se algum bloqueio parece conservador demais."
                ),
                f"- Entradas simuladas: **{len(simulated_missed_trades)}**",
                f"- Vencedoras simuladas: **{winners}**",
                f"- Resultado líquido simulado: **{_money(metrics.net_profit)}**",
                f"- Expectancy simulada: **{_value(metrics.expectancy)}**",
                f"- Profit factor simulado: **{_value(metrics.profit_factor)}**",
                f"- Drawdown simulado: **{_value(metrics.max_drawdown_pct, '%')}**",
                "",
                "| Sinal | Ativo | Setup | Score | Saida | Resultado | Veredito | Aprendizado |",
                "|---|---|---|---:|---|---:|---|---|",
            ]
        )
        for row in simulated_missed_trades[:20]:
            trade = row.trade
            lines.append(
                f"| {trade.signal_at.isoformat()} | {trade.symbol} | {trade.setup_type} | "
                f"{trade.score} | {trade.close_reason} | {_money(trade.net_pnl)} | "
                f"{row.verdict} | {_md_cell(row.learning)} |"
            )
        lines.append("")

    if operational_lines:
        approved = [row for row in operational_lines if row.approved]
        lines.extend(
            [
                "## Linhas operacionais candidatas",
                "",
                (
                    "Cada linha foi testada com treino no passado e teste nos anos seguintes. "
                    "Uma linha reprovada nao deve virar regra principal."
                ),
                f"- Linhas aprovadas: **{len(approved)}**",
                "",
                "| Linha | Score | Trades teste | Resultado | Expectancy | Profit factor | Drawdown | Veredito | Motivo |",
                "|---|---:|---:|---:|---:|---:|---:|---|---|",
            ]
        )
        for row in operational_lines:
            verdict = "APROVADA" if row.approved else "REPROVADA"
            reason = "Passou nos critérios mínimos." if row.approved else " | ".join(row.rejection_reasons)
            lines.append(
                f"| {row.candidate.name} | {row.candidate.minimum_score} | {row.test_trades} | "
                f"{_money(row.test_metrics.net_profit)} | {_value(row.test_metrics.expectancy)} | "
                f"{_value(row.test_metrics.profit_factor)} | "
                f"{_value(row.test_metrics.max_drawdown_pct, '%')} | {verdict} | "
                f"{_md_cell(reason)} |"
            )
        lines.append("")

    if simulated_operational_lines:
        approved = [row for row in simulated_operational_lines if row.approved]
        lines.extend(
            [
                "## Linhas simuladas das entradas bloqueadas",
                "",
                (
                    "Estas linhas usam apenas entradas hipotéticas bloqueadas. Servem para descobrir "
                    "o que estudar melhor; não aprovam operação real sem novo holdout."
                ),
                f"- Linhas simuladas aprovadas: **{len(approved)}**",
                "",
                "| Linha | Score | Trades teste | Resultado | Expectancy | Profit factor | Drawdown | Veredito | Motivo |",
                "|---|---:|---:|---:|---:|---:|---:|---|---|",
            ]
        )
        for row in simulated_operational_lines:
            verdict = "CANDIDATA FORTE" if row.approved else "REPROVADA"
            reason = "Passou nos critérios mínimos simulados." if row.approved else " | ".join(row.rejection_reasons)
            lines.append(
                f"| {row.candidate.name} | {row.candidate.minimum_score} | {row.test_trades} | "
                f"{_money(row.test_metrics.net_profit)} | {_value(row.test_metrics.expectancy)} | "
                f"{_value(row.test_metrics.profit_factor)} | "
                f"{_value(row.test_metrics.max_drawdown_pct, '%')} | {verdict} | "
                f"{_md_cell(reason)} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Prontidao operacional",
            "",
            (
                "Esta nota resume o quanto o Cashinho esta bem instrumentado para estudar "
                "e o quanto ja existe evidencia para uso operacional."
            ),
            f"- Confiabilidade tecnica: **{_value(readiness.technical_pct, '%')}**",
            f"- Confiabilidade operacional: **{_value(readiness.operational_pct, '%')}**",
            f"- Veredito: **{readiness.verdict}**",
            "",
            "| Area | Criterio | Pontos | Maximo | Explicacao |",
            "|---|---|---:|---:|---|",
        ]
    )
    for factor in readiness.factors:
        lines.append(
            f"| {factor.area} | {factor.name} | {_value(factor.points)} | "
            f"{_value(factor.max_points)} | {_md_cell(factor.explanation)} |"
        )
    lines.append("")

    if walk_forward:
        lines.extend(
            [
                "## Walk-forward",
                "",
                "| Janela | Trades teste | Resultado teste | Win rate teste | Profit factor teste | Drawdown teste |",
                "|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for window in walk_forward[:12]:
            metrics = window.test_metrics
            lines.append(
                f"| {window.index} | {metrics.total_trades} | {_money(metrics.net_profit)} | "
                f"{_value(metrics.win_rate, '%')} | {_value(metrics.profit_factor)} | "
                f"{_value(metrics.max_drawdown_pct, '%')} |"
            )
        lines.append("")

    if policy_replay_rows:
        lines.extend(
            [
                "## Replay da politica",
                "",
                "Leitura in-sample: mede o que a politica teria bloqueado dentro do proprio estudo.",
                "",
                "| Grupo | Trades | Win rate | Profit factor | Resultado | Drawdown |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for row in policy_replay_rows:
            lines.append(
                f"| {row['Grupo']} | {row['Trades']} | {_value(row['Win rate'], '%')} | "
                f"{_value(row['Profit factor'])} | {_money(row['Resultado R$'])} | "
                f"{_value(row['Drawdown %'], '%')} |"
            )
        lines.append("")

    if policy_holdout is not None:
        lines.extend(
            [
                "## Holdout da politica",
                "",
                (
                    "Politica treinada no passado e medida apenas nos anos seguintes. "
                    f"Regras aprendidas: **{len(policy_holdout.policy.rules)}**."
                ),
                "",
                "| Grupo | Treino ate | Teste desde | Trades | Win rate | Profit factor | Resultado | Drawdown |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in policy_holdout.rows:
            metrics = row.metrics
            lines.append(
                f"| {row.group} | {row.train_until_year} | {row.test_start_year} | "
                f"{row.trades} | {_value(metrics.win_rate, '%')} | "
                f"{_value(metrics.profit_factor)} | {_money(metrics.net_profit)} | "
                f"{_value(metrics.max_drawdown_pct, '%')} |"
            )
        lines.append("")

    if decision_reason_rows:
        lines.extend(
            [
                "## Principais bloqueios",
                "",
                "| Motivo | Ocorrencias |",
                "|---|---:|",
            ]
        )
        for row in decision_reason_rows[:12]:
            lines.append(f"| {_md_cell(row['Motivo'])} | {row['Ocorrencias']} |")
        lines.append("")

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


def render_policy_markdown(policy_path: Path, rules_count: int) -> str:
    return (
        "\n".join(
            [
                "## Politica operacional gerada",
                "",
                f"- Arquivo: `{policy_path}`",
                f"- Regras historicas: **{rules_count}**",
                "",
                "O scanner usa essa politica como trava adicional antes de liberar uma entrada.",
                "",
            ]
        )
        if rules_count
        else "\n".join(
            [
                "## Politica operacional gerada",
                "",
                "Nenhuma regra historica foi gerada com os filtros atuais.",
                "",
            ]
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--years", default="2020-2026")
    parser.add_argument("--timeframes", default=",".join(tf.value for tf in DEFAULT_TIMEFRAMES))
    parser.add_argument("--decision-timeframe", default="")
    parser.add_argument("--max-decision-points", type=int, default=0)
    parser.add_argument(
        "--validation-mode",
        choices=("FAST_VALIDATION", "FULL_RESEARCH"),
        default="FULL_RESEARCH",
        help=(
            "FAST_VALIDATION limita pontos de decisao para feedback rapido; "
            "FULL_RESEARCH usa o escopo solicitado."
        ),
    )
    parser.add_argument(
        "--market-context",
        action="store_true",
        help="Inclui leitura do mercado amplo dentro de cada candle do backtest.",
    )
    parser.add_argument("--data-root", type=Path, default=ROOT / "data" / "historical")
    parser.add_argument(
        "--require-real-data",
        action="store_true",
        help="Recusa CSV sem comprovante de exportacao real do MetaTrader 5.",
    )
    parser.add_argument(
        "--cost-scenarios",
        default="SEM_CUSTOS,REALISTA",
        help="Cenarios separados por virgula: SEM_CUSTOS, IDEAL, REALISTA, ESTRESSADO.",
    )
    parser.add_argument("--monte-carlo-simulations", type=int, default=1000)
    parser.add_argument(
        "--quality-gate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Simula a trava profissional de qualidade usada no scanner.",
    )
    parser.add_argument("--minimum-entry-score", type=int, default=80)
    parser.add_argument(
        "--policy-holdout-year",
        type=int,
        default=0,
        help="Ano final de treino para testar politica nos anos seguintes. 0 escolhe automaticamente.",
    )
    parser.add_argument(
        "--input-policy-path",
        type=Path,
        default=None,
        help="Politica historica ja existente para aplicar durante o backtest.",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "reports" / "diagnostics")
    parser.add_argument(
        "--policy-path",
        type=Path,
        default=ROOT / "data" / "reports" / "deep_study" / "operational_policy.json",
    )
    parser.add_argument(
        "--snapshot-policy-path",
        type=Path,
        default=None,
        help="Opcional: salva uma copia versionavel da politica operacional.",
    )
    args = parser.parse_args()

    symbols = _parse_symbols(args.symbols)
    years = _parse_years(args.years)
    timeframes = _parse_timeframes(args.timeframes)
    decision_timeframe = Timeframe(args.decision_timeframe) if args.decision_timeframe else None
    cost_scenarios = parse_cost_scenarios(args.cost_scenarios)
    primary_cost = CostScenario.REALISTA if CostScenario.REALISTA in cost_scenarios else cost_scenarios[0]
    max_decision_points = args.max_decision_points
    if args.validation_mode == "FAST_VALIDATION" and max_decision_points == 0:
        max_decision_points = FAST_VALIDATION_DECISION_POINTS
    required_start = datetime.combine(datetime(min(years), 1, 1).date(), time.min, tzinfo=UTC)
    requested_required_end = (
        datetime.combine(datetime(max(years), 12, 31).date(), time.min, tzinfo=UTC)
        + timedelta(days=1)
    )
    required_end = min(requested_required_end, datetime.now(UTC))
    if args.require_real_data:
        try:
            assert_mt5_provenance(
                data_root=args.data_root,
                symbols=symbols,
                timeframes=timeframes,
                required_start=required_start,
                required_end=required_end,
            )
        except DataProvenanceError as exc:
            print("[falha] Estudo real bloqueado.", flush=True)
            print(str(exc), flush=True)
            print(
                "Abra o MT5 autenticado e rode scripts/export_mt5_history.py "
                "para gerar dados reais antes do diagnostico.",
                flush=True,
            )
            return 2
    profile = RiskProfile()
    clock = FrozenClock(datetime(max(years) + 1, 1, 2, tzinfo=UTC))
    provider = CachedCsvHistoricalProvider(args.data_root, clock, name="diagnostics")
    input_policy = load_operational_policy(args.input_policy_path) if args.input_policy_path else None
    all_diagnostics: list[DiagnosticTrade] = []
    all_decisions: list[BacktestDecisionLog] = []
    all_autopsies: list[LossAutopsy] = []
    all_daily_reports: list[DailyLearningReport] = []
    all_missed_opportunities: list[MissedOpportunity] = []
    all_simulated_missed_trades: list[SimulatedMissedTrade] = []
    all_simulated_missed_diagnostics: list[DiagnosticTrade] = []
    notes: list[str] = []
    timings: list[dict[str, object]] = []
    cost_rows: list[dict[str, object]] = []

    for year in years:
        start = datetime.combine(datetime(year, 1, 1).date(), time.min, tzinfo=UTC)
        end = datetime.combine(datetime(year, 12, 31).date(), time.min, tzinfo=UTC) + timedelta(days=1)
        year_clock = FrozenClock(end + timedelta(days=1))
        print(f"Estudando {year}: carregando dados de {', '.join(symbols)}...", flush=True)
        started = perf_counter()
        universe, universe_notes = _load_universe(
            provider,
            symbols=symbols,
            timeframes=timeframes,
            start=start,
            end=end,
            clock=year_clock,
        )
        timings.append(
            _timing_row(
                "leitura_dados",
                perf_counter() - started,
                year=year,
                symbols=",".join(symbols),
                timeframes=",".join(timeframe.value for timeframe in timeframes),
            )
        )
        notes.extend(f"{year} {note}" for note in universe_notes)
        for symbol in symbols:
            print(f"Estudando {year} {symbol}...", flush=True)
            target = universe.get(symbol, {})
            if len(target) < 2:
                notes.append(f"{year} {symbol}: menos de dois timeframes validos")
                continue
            if decision_timeframe is not None and decision_timeframe not in target:
                notes.append(
                    f"{year} {symbol}: sem {decision_timeframe.value} para relogio de decisao"
                )
                continue
            market_context = (
                {
                    market_symbol: loaded
                    for market_symbol, loaded in universe.items()
                    if market_symbol != symbol and loaded
                }
                if args.market_context
                else {}
            )
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
                operational_policy=input_policy,
                use_opportunity_quality=args.quality_gate,
                minimum_entry_score=args.minimum_entry_score,
            )
            for scenario in cost_scenarios:
                cost_config = cost_scenario_config(scenario)
                started = perf_counter()
                result = run_backtest(
                    target,
                    evaluator,
                    risk_profile=profile,
                    costs=cost_config.model,
                    decision_timeframe=decision_timeframe,
                    max_decision_points=max_decision_points,
                    exit_mode=BacktestExitMode.FIXED,
                )
                timings.append(
                    _timing_row(
                        "backtest",
                        perf_counter() - started,
                        year=year,
                        symbol=symbol,
                        scenario=scenario.value,
                        candles=sum(len(series) for series in target.values()),
                        trades=len(result.trades),
                    )
                )
                cost_rows.append(
                    _cost_row(
                        scenario=scenario,
                        year=year,
                        symbol=symbol,
                        trades=result.metrics.total_trades,
                        net_profit=result.metrics.net_profit,
                        win_rate=result.metrics.win_rate,
                        profit_factor=result.metrics.profit_factor,
                        max_drawdown_pct=result.metrics.max_drawdown_pct,
                    )
                )
                if scenario == primary_cost:
                    result_diagnostics = build_diagnostic_trades(
                        result.trades,
                        series_by_timeframe=target,
                    )
                    result_autopsies = build_loss_autopsies(
                        result_diagnostics,
                        series_by_timeframe=target,
                    )
                    daily_series = target.get(Timeframe.M5) or target[
                        min(target, key=lambda timeframe: timeframe.duration)
                    ]
                    all_diagnostics.extend(result_diagnostics)
                    all_autopsies.extend(result_autopsies)
                    all_daily_reports.extend(
                        build_daily_learning_reports(
                            symbol=symbol,
                            series=daily_series,
                            decisions=result.decisions,
                            trades=result.trades,
                            autopsies=result_autopsies,
                        )
                    )
                    all_missed_opportunities.extend(
                        find_missed_opportunities(
                            result.decisions,
                            series=daily_series,
                        )
                    )
                    simulated_missed = simulate_missed_opportunity_trades(
                        result.decisions,
                        series=daily_series,
                        risk_profile=profile,
                        costs=cost_config.model,
                    )
                    all_simulated_missed_trades.extend(simulated_missed)
                    all_simulated_missed_diagnostics.extend(
                        build_diagnostic_trades(
                            (row.trade for row in simulated_missed),
                            series_by_timeframe=target,
                        )
                    )
                    all_decisions.extend(result.decisions)

    diagnostics = tuple(all_diagnostics)
    tables = diagnostic_tables(diagnostics, initial_capital=profile.capital)
    score_rows = calibrate_scores(tuple(item.trade for item in diagnostics), initial_capital=profile.capital)
    score_verdict = score_calibration_verdict(score_rows)
    monte_carlo = run_monte_carlo(
        tuple(item.trade for item in diagnostics),
        initial_capital=profile.capital,
        simulations=args.monte_carlo_simulations,
    )
    walk_forward = rolling_walk_forward(
        tuple(item.trade for item in diagnostics),
        initial_capital=profile.capital,
    )
    trade_rows = [_trade_dict(item) for item in diagnostics]
    decision_rows = [_decision_row(item) for item in all_decisions]
    decision_reason_rows = _decision_reason_rows(all_decisions)
    loss_autopsies = tuple(all_autopsies)
    error_causes = summarize_error_causes(loss_autopsies)
    daily_reports = tuple(all_daily_reports)
    annual_reports = build_annual_learning_reports(
        daily_reports,
        diagnostics,
        error_causes,
        initial_capital=profile.capital,
    )
    filter_contribution = analyze_filter_contribution(tuple(all_decisions))
    missed_opportunities = tuple(all_missed_opportunities)
    simulated_missed_trades = tuple(all_simulated_missed_trades)
    simulated_missed_diagnostics = tuple(all_simulated_missed_diagnostics)
    holdout_year = args.policy_holdout_year
    if holdout_year == 0 and len(years) >= 3:
        holdout_year = sorted(years)[-3]
    operational_lines = compare_operational_lines(
        diagnostics,
        initial_capital=profile.capital,
        train_until_year=holdout_year if holdout_year else min(years),
    )
    simulated_operational_lines = compare_operational_lines(
        simulated_missed_diagnostics,
        initial_capital=profile.capital,
        train_until_year=holdout_year if holdout_year else min(years),
    )
    simulated_trade_items = tuple(row.trade for row in simulated_missed_trades)
    group_rows = [
        _row_dict(row)
        for rows in tables.values()
        for row in rows
    ]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(args.output_dir / "diagnostic_trades.csv", trade_rows)
    _write_csv(args.output_dir / "diagnostic_groups.csv", group_rows)
    _write_csv(args.output_dir / "performance.csv", timings)
    _write_csv(args.output_dir / "cost_scenarios.csv", cost_rows)
    _write_csv(args.output_dir / "score_calibration.csv", [_score_row(row) for row in score_rows])
    _write_csv(args.output_dir / "monte_carlo.csv", [_monte_carlo_row(monte_carlo)] if monte_carlo else [])
    _write_csv(args.output_dir / "walk_forward.csv", [_walk_forward_row(row) for row in walk_forward])
    _write_csv(args.output_dir / "decision_audit.csv", decision_rows)
    _write_csv(args.output_dir / "decision_reasons.csv", decision_reason_rows)
    _write_csv(args.output_dir / "loss_autopsy.csv", [_loss_autopsy_row(row) for row in loss_autopsies])
    _write_csv(args.output_dir / "error_causes.csv", [_error_cause_row(row) for row in error_causes])
    _write_csv(args.output_dir / "daily_learning.csv", [_daily_learning_row(row) for row in daily_reports])
    _write_csv(args.output_dir / "annual_learning.csv", [_annual_learning_row(row) for row in annual_reports])
    _write_csv(
        args.output_dir / "filter_contribution.csv",
        [_filter_contribution_row(row) for row in filter_contribution],
    )
    _write_csv(
        args.output_dir / "missed_opportunities.csv",
        [_missed_opportunity_row(row) for row in missed_opportunities],
    )
    _write_csv(
        args.output_dir / "simulated_missed_trades.csv",
        [_simulated_missed_trade_row(row) for row in simulated_missed_trades],
    )
    _write_csv(
        args.output_dir / "operational_lines.csv",
        [_operational_line_row(row) for row in operational_lines],
    )
    _write_csv(
        args.output_dir / "simulated_operational_lines.csv",
        [_operational_line_row(row) for row in simulated_operational_lines],
    )
    policy = build_policy_from_diagnostics(
        diagnostics,
        initial_capital=profile.capital,
        generated_at=datetime.now(UTC),
        source=(
            f"symbols={','.join(symbols)} years={','.join(str(year) for year in years)} "
            f"timeframes={','.join(timeframe.value for timeframe in timeframes)} "
            f"decision_timeframe={decision_timeframe.value if decision_timeframe else 'auto'} "
            f"max_decision_points={max_decision_points} "
            f"validation_mode={args.validation_mode} "
            f"market_context={bool(args.market_context)} "
            f"quality_gate={bool(args.quality_gate)} "
            f"minimum_entry_score={args.minimum_entry_score} "
            f"input_policy={args.input_policy_path or 'none'} "
            f"primary_cost={primary_cost.value} "
            f"cost_scenarios={','.join(scenario.value for scenario in cost_scenarios)}"
        ),
    )
    save_operational_policy(policy, args.policy_path)
    policy_replay_rows = _policy_replay_rows(
        diagnostics,
        policy=policy,
        initial_capital=profile.capital,
    )
    _write_csv(args.output_dir / "policy_replay.csv", policy_replay_rows)
    policy_holdout = (
        validate_policy_holdout(
            diagnostics,
            initial_capital=profile.capital,
            train_until_year=holdout_year,
            generated_at=datetime.now(UTC),
            source=f"holdout train_until={holdout_year}",
        )
        if holdout_year
        else None
    )
    _write_csv(
        args.output_dir / "policy_holdout.csv",
        [_policy_holdout_row(row) for row in policy_holdout.rows] if policy_holdout else [],
    )
    readiness = evaluate_operational_readiness(
        diagnostics,
        score_rows=score_rows,
        monte_carlo=monte_carlo,
        policy_holdout=policy_holdout,
        operational_lines=operational_lines,
        simulated_lines=simulated_operational_lines,
        simulated_trades=simulated_trade_items,
    )
    _write_csv(
        args.output_dir / "operational_readiness.csv",
        [
            _readiness_summary_row(readiness),
            *[_readiness_factor_row(row) for row in readiness.factors],
        ],
    )
    if args.snapshot_policy_path is not None:
        save_operational_policy(policy, args.snapshot_policy_path)
    markdown = render_markdown(
        diagnostics=diagnostics,
        tables=tables,
        cost_rows=cost_rows,
        score_rows=score_rows,
        score_verdict=score_verdict,
        monte_carlo=monte_carlo,
        walk_forward=walk_forward,
        policy_replay_rows=policy_replay_rows,
        policy_holdout=policy_holdout,
        decision_reason_rows=decision_reason_rows,
        loss_autopsies=loss_autopsies,
        error_causes=error_causes,
        daily_reports=daily_reports,
        annual_reports=annual_reports,
        filter_contribution=filter_contribution,
        missed_opportunities=missed_opportunities,
        simulated_missed_trades=simulated_missed_trades,
        operational_lines=operational_lines,
        simulated_operational_lines=simulated_operational_lines,
        readiness=readiness,
        notes=tuple(dict.fromkeys(notes)),
        output_dir=args.output_dir,
    )
    slowest = sorted(timings, key=lambda row: float(row["seconds"]), reverse=True)[:10]
    if slowest:
        markdown = f"{markdown}\n\n## Desempenho\n\n"
        markdown += "| Componente | Segundos | Contexto |\n|---|---:|---|\n"
        for row in slowest:
            context = ", ".join(
                f"{key}={value}"
                for key, value in row.items()
                if key not in {"component", "seconds"}
            )
            markdown += f"| {row['component']} | {row['seconds']} | {context} |\n"
    markdown = f"{markdown}\n\n{render_policy_markdown(args.policy_path, len(policy.rules))}"
    report_path = args.output_dir / "diagnostic_report.md"
    report_path.write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
