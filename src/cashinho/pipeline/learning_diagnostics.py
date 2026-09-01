"""Aprendizado operacional a partir de trades, rejeições e pregões inteiros."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TypeVar
from zoneinfo import ZoneInfo

from cashinho.domain.enums import Timeframe
from cashinho.domain.market import Candle, CandleSeries
from cashinho.domain.risk import RiskProfile
from cashinho.pipeline.backtest import (
    BacktestDecisionLog,
    BacktestMetrics,
    BacktestTrade,
    ExecutionCostModel,
    calculate_metrics,
)
from cashinho.pipeline.backtest_diagnostics import DiagnosticTrade
from cashinho.pipeline.paper_performance import calculate_position_pnl
from cashinho.pipeline.paper_ticket import calculate_ticket_sizing

ZERO = Decimal("0")
HUNDRED = Decimal("100")
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class LossAutopsy:
    symbol: str
    entered_at: datetime
    setup_type: str
    regime: str
    volatility: str
    hour: str
    net_pnl: Decimal
    costs: Decimal
    mae: Decimal
    mfe: Decimal
    primary_cause: str
    explanation: str
    correction_hypothesis: str
    is_model_error: bool


@dataclass(frozen=True, slots=True)
class ErrorCauseSummary:
    cause: str
    occurrences: int
    net_loss: Decimal
    pct_of_total_loss: Decimal
    setups: tuple[str, ...]
    hours: tuple[str, ...]
    regimes: tuple[str, ...]
    correction_hypothesis: str


@dataclass(frozen=True, slots=True)
class DailyLearningReport:
    day: date
    symbol: str
    candles_analyzed: int
    opportunities_found: int
    entries: int
    wins: int
    losses: int
    flats: int
    avoided: int
    main_avoidance_reason: str
    gross_profit: Decimal
    gross_loss: Decimal
    net_result: Decimal
    costs: Decimal
    win_rate: Decimal | None
    payoff: Decimal | None
    profit_factor: Decimal | None
    intraday_drawdown: Decimal | None
    max_loss_streak: int
    max_win_streak: int
    average_mae: Decimal | None
    average_mfe: Decimal | None
    average_score: Decimal | None
    classification: str
    main_error: str
    main_win: str
    learning: str


@dataclass(frozen=True, slots=True)
class AnnualLearningReport:
    year: int
    symbol: str
    days_analyzed: int
    days_traded: int
    days_not_traded: int
    traded_days_pct: Decimal | None
    total_trades: int
    average_trades_per_day: Decimal | None
    metrics: BacktestMetrics
    best_conditions: tuple[str, ...]
    worst_conditions: tuple[str, ...]
    most_common_loss_causes: tuple[str, ...]
    most_common_avoidance_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FilterContribution:
    reason: str
    occurrences: int
    average_score: Decimal | None
    affected_symbols: tuple[str, ...]
    affected_setups: tuple[str, ...]
    note: str


@dataclass(frozen=True, slots=True)
class MissedOpportunity:
    symbol: str
    timestamp: datetime
    side: str
    timeframe: str
    score: int
    setup_type: str
    blocked_reason: str
    horizon_candles: int
    favorable_move: Decimal
    adverse_move: Decimal
    favorable_to_adverse: Decimal | None
    verdict: str
    learning: str


@dataclass(frozen=True, slots=True)
class SimulatedMissedTrade:
    trade: BacktestTrade
    blocked_reason: str
    verdict: str
    learning: str


def build_loss_autopsies(
    diagnostics: tuple[DiagnosticTrade, ...],
    *,
    series_by_timeframe: dict[Timeframe, CandleSeries],
) -> tuple[LossAutopsy, ...]:
    rows = []
    for item in diagnostics:
        if item.trade.net_pnl >= 0:
            continue
        mae, mfe = excursion(item.trade, series_by_timeframe.get(item.trade.timeframe))
        cause, explanation, correction, model_error = _loss_cause(item, mae=mae, mfe=mfe)
        rows.append(
            LossAutopsy(
                symbol=item.symbol,
                entered_at=item.trade.entered_at,
                setup_type=item.setup_type,
                regime=item.regime,
                volatility=item.volatility,
                hour=item.hour,
                net_pnl=item.trade.net_pnl,
                costs=item.trade.costs,
                mae=mae,
                mfe=mfe,
                primary_cause=cause,
                explanation=explanation,
                correction_hypothesis=correction,
                is_model_error=model_error,
            )
        )
    return tuple(rows)


def summarize_error_causes(autopsies: tuple[LossAutopsy, ...]) -> tuple[ErrorCauseSummary, ...]:
    total_loss = abs(sum((row.net_pnl for row in autopsies), ZERO))
    rows = []
    for cause in sorted({row.primary_cause for row in autopsies}):
        group = [row for row in autopsies if row.primary_cause == cause]
        net_loss = abs(sum((row.net_pnl for row in group), ZERO))
        pct = (net_loss / total_loss * HUNDRED).quantize(Decimal("0.01")) if total_loss else ZERO
        rows.append(
            ErrorCauseSummary(
                cause=cause,
                occurrences=len(group),
                net_loss=net_loss.quantize(Decimal("0.01")),
                pct_of_total_loss=pct,
                setups=_top_values(row.setup_type for row in group),
                hours=_top_values(row.hour for row in group),
                regimes=_top_values(row.regime for row in group),
                correction_hypothesis=group[0].correction_hypothesis,
            )
        )
    return tuple(sorted(rows, key=lambda row: (row.net_loss, row.occurrences), reverse=True))


def build_daily_learning_reports(
    *,
    symbol: str,
    series: CandleSeries,
    decisions: tuple[BacktestDecisionLog, ...],
    trades: tuple[BacktestTrade, ...],
    autopsies: tuple[LossAutopsy, ...] = (),
    display_timezone: str = "America/Sao_Paulo",
) -> tuple[DailyLearningReport, ...]:
    timezone = ZoneInfo(display_timezone)
    candles_by_day: dict[date, list[Candle]] = {}
    for candle in series.closed_only().candles:
        candles_by_day.setdefault(candle.close_time.astimezone(timezone).date(), []).append(candle)
    decisions_by_day = _group_by_day(decisions, timezone, lambda item: item.timestamp)
    trades_by_day = _group_by_day(trades, timezone, lambda item: item.entered_at)
    autopsies_by_day = _group_by_day(autopsies, timezone, lambda item: item.entered_at)

    rows = []
    for day in sorted(candles_by_day):
        day_decisions = tuple(decisions_by_day.get(day, ()))
        day_trades = tuple(trades_by_day.get(day, ()))
        day_autopsies = tuple(autopsies_by_day.get(day, ()))
        metrics = calculate_metrics(list(day_trades), initial_capital=Decimal("100"))[0]
        avoided_decisions = [item for item in day_decisions if not item.should_enter]
        main_avoidance = _common_reason(avoided_decisions)
        average_score = _average_decimal(Decimal(item.score) for item in day_decisions if item.score > 0)
        average_mae = _average_decimal(row.mae for row in day_autopsies)
        average_mfe = _average_decimal(row.mfe for row in day_autopsies)
        wins = [trade for trade in day_trades if trade.net_pnl > 0]
        losses = [trade for trade in day_trades if trade.net_pnl < 0]
        rows.append(
            DailyLearningReport(
                day=day,
                symbol=symbol,
                candles_analyzed=len(candles_by_day[day]),
                opportunities_found=sum(1 for item in day_decisions if item.score > 0),
                entries=len(day_trades),
                wins=len(wins),
                losses=len(losses),
                flats=sum(1 for trade in day_trades if trade.net_pnl == 0),
                avoided=len(avoided_decisions),
                main_avoidance_reason=main_avoidance,
                gross_profit=sum((trade.net_pnl for trade in wins), ZERO).quantize(Decimal("0.01")),
                gross_loss=abs(sum((trade.net_pnl for trade in losses), ZERO)).quantize(Decimal("0.01")),
                net_result=metrics.net_profit.quantize(Decimal("0.01")),
                costs=sum((trade.costs for trade in day_trades), ZERO).quantize(Decimal("0.01")),
                win_rate=metrics.win_rate,
                payoff=metrics.payoff,
                profit_factor=metrics.profit_factor,
                intraday_drawdown=metrics.max_drawdown_pct,
                max_loss_streak=metrics.max_loss_streak,
                max_win_streak=metrics.max_win_streak,
                average_mae=average_mae,
                average_mfe=average_mfe,
                average_score=average_score,
                classification=_classify_day(day_decisions),
                main_error=day_autopsies[0].primary_cause if day_autopsies else "Nenhum erro operacional registrado.",
                main_win=_main_win_reason(wins),
                learning=_daily_learning(day_trades, day_autopsies, main_avoidance),
            )
        )
    return tuple(rows)


def build_annual_learning_reports(
    daily_reports: tuple[DailyLearningReport, ...],
    diagnostics: tuple[DiagnosticTrade, ...],
    error_causes: tuple[ErrorCauseSummary, ...],
    *,
    initial_capital: Decimal,
) -> tuple[AnnualLearningReport, ...]:
    rows = []
    for (symbol, year), days in sorted(_daily_year_groups(daily_reports).items()):
        trades = [
            item.trade
            for item in diagnostics
            if item.symbol == symbol and item.year == str(year)
        ]
        metrics = calculate_metrics(trades, initial_capital=initial_capital)[0]
        days_traded = sum(1 for day in days if day.entries > 0)
        days_analyzed = len(days)
        traded_pct = (
            Decimal(days_traded) / Decimal(days_analyzed) * HUNDRED
            if days_analyzed
            else None
        )
        rows.append(
            AnnualLearningReport(
                year=year,
                symbol=symbol,
                days_analyzed=days_analyzed,
                days_traded=days_traded,
                days_not_traded=days_analyzed - days_traded,
                traded_days_pct=traded_pct.quantize(Decimal("0.01")) if traded_pct else None,
                total_trades=len(trades),
                average_trades_per_day=(
                    Decimal(len(trades)) / Decimal(days_analyzed)
                ).quantize(Decimal("0.01")) if days_analyzed else None,
                metrics=metrics,
                best_conditions=_best_condition_labels(diagnostics, symbol=symbol, year=year),
                worst_conditions=_worst_condition_labels(diagnostics, symbol=symbol, year=year),
                most_common_loss_causes=tuple(row.cause for row in error_causes[:5]),
                most_common_avoidance_reasons=_top_values(
                    day.main_avoidance_reason for day in days if day.avoided
                ),
            )
        )
    return tuple(rows)


def analyze_filter_contribution(
    decisions: tuple[BacktestDecisionLog, ...],
) -> tuple[FilterContribution, ...]:
    rejected = [item for item in decisions if not item.should_enter]
    rows = []
    for reason in sorted({item.primary_reason for item in rejected}):
        group = [item for item in rejected if item.primary_reason == reason]
        rows.append(
            FilterContribution(
                reason=reason,
                occurrences=len(group),
                average_score=_average_decimal(Decimal(item.score) for item in group),
                affected_symbols=_top_values(item.symbol for item in group),
                affected_setups=_top_values(item.setup_type for item in group if item.setup_type),
                note=(
                    "Este filtro bloqueia muitas leituras; comparar com movimentos posteriores "
                    "em análise contrafactual antes de afrouxar."
                ),
            )
        )
    return tuple(sorted(rows, key=lambda row: row.occurrences, reverse=True))


def find_missed_opportunities(
    decisions: tuple[BacktestDecisionLog, ...],
    *,
    series: CandleSeries,
    minimum_score: int = 65,
    horizon_candles: int = 12,
    minimum_favorable_move_pct: Decimal = Decimal("0.40"),
) -> tuple[MissedOpportunity, ...]:
    """Analise contrafactual: mede rejeicoes que poderiam ter virado movimento.

    Esta funcao usa candles posteriores apenas para aprender depois do pregão.
    Ela nunca deve ser usada para liberar uma entrada no mesmo instante historico.
    """

    candles = series.closed_only().candles
    rows = []
    for decision in decisions:
        if (
            decision.should_enter
            or decision.score < minimum_score
        ):
            continue
        index = _first_candle_after(candles, decision.timestamp)
        if index is None or index + 1 >= len(candles):
            continue
        entry_candle = candles[index]
        future = candles[index + 1:index + 1 + horizon_candles]
        if not future or entry_candle.close <= 0:
            continue
        side = (
            decision.side
            if decision.side in {"BUY", "SELL"}
            else _retrospective_side(entry_candle.close, future)
        )
        favorable, adverse = _future_excursion(side, entry_candle.close, future)
        favorable_pct = favorable / entry_candle.close * HUNDRED
        adverse_pct = adverse / entry_candle.close * HUNDRED
        ratio = (
            (favorable / adverse).quantize(Decimal("0.01"))
            if adverse > 0
            else None
        )
        verdict = _missed_verdict(
            favorable_pct=favorable_pct,
            adverse_pct=adverse_pct,
            ratio=ratio,
            minimum_favorable_move_pct=minimum_favorable_move_pct,
        )
        rows.append(
            MissedOpportunity(
                symbol=decision.symbol,
                timestamp=decision.timestamp,
                side=side,
                timeframe=decision.timeframe.value if decision.timeframe else "",
                score=decision.score,
                setup_type=decision.setup_type,
                blocked_reason=decision.primary_reason,
                horizon_candles=len(future),
                favorable_move=favorable.quantize(Decimal("0.01")),
                adverse_move=adverse.quantize(Decimal("0.01")),
                favorable_to_adverse=ratio,
                verdict=verdict,
                learning=_missed_learning(verdict, decision.primary_reason),
            )
        )
    return tuple(rows)


def simulate_missed_opportunity_trades(
    decisions: tuple[BacktestDecisionLog, ...],
    *,
    series: CandleSeries,
    risk_profile: RiskProfile,
    costs: ExecutionCostModel | None = None,
    minimum_score: int = 70,
    horizon_candles: int = 12,
) -> tuple[SimulatedMissedTrade, ...]:
    """Reproduz entradas bloqueadas com o plano técnico que existia no candle.

    Esta é uma simulação contrafactual para aprendizado. Ela só usa candles
    futuros depois da decisão histórica e não participa da decisão ao vivo.
    """

    cost_model = costs or ExecutionCostModel()
    candles = series.closed_only().candles
    rows: list[SimulatedMissedTrade] = []
    for decision in decisions:
        if decision.should_enter or decision.score < minimum_score:
            continue
        plan = _planned_operation(decision)
        if plan is None:
            continue
        side, entry, stop, target = plan
        index = _first_candle_after(candles, decision.timestamp)
        if index is None or index + 1 >= len(candles):
            continue
        future = candles[index + 1:index + 1 + horizon_candles]
        fill_index, entered_at = _first_fill(entry, future)
        if fill_index is None or entered_at is None:
            continue
        quantity = _simulated_quantity(
            entry=entry,
            stop=stop,
            side=side,
            risk_profile=risk_profile,
            costs=cost_model,
        )
        if quantity <= 0:
            continue
        exit_candle, raw_exit, close_reason = _fixed_exit(
            side=side,
            stop=stop,
            target=target,
            candles=future[fill_index:],
        )
        entry_execution = cost_model.entry_price(entry, side)
        exit_execution = cost_model.exit_price(raw_exit, side)
        fees = cost_model.fees(entry_execution, exit_execution, quantity)
        gross_result = calculate_position_pnl(
            side=side,
            entry_price=entry,
            exit_price=raw_exit,
            stop=stop,
            quantity=quantity,
            entered_at=entered_at,
            exited_at=exit_candle.close_time,
        )
        net_result = calculate_position_pnl(
            side=side,
            entry_price=entry_execution,
            exit_price=exit_execution,
            stop=stop,
            quantity=quantity,
            entered_at=entered_at,
            exited_at=exit_candle.close_time,
            costs=fees,
        )
        trade = BacktestTrade(
            symbol=decision.symbol,
            side=side,
            timeframe=decision.timeframe or series.timeframe,
            score=decision.score,
            signal_at=decision.timestamp,
            entered_at=entered_at,
            exited_at=exit_candle.close_time,
            planned_entry=entry,
            stop=stop,
            target=target,
            entry_price=entry_execution,
            exit_price=exit_execution,
            quantity=quantity,
            close_reason=close_reason,
            gross_pnl=gross_result.pnl_value,
            costs=(gross_result.pnl_value - net_result.pnl_value).quantize(Decimal("0.01")),
            net_pnl=net_result.pnl_value,
            pnl_pct=net_result.pnl_pct,
            result_in_r=net_result.result_in_r,
            duration=net_result.duration or (exit_candle.close_time - entered_at),
            setup_type=decision.setup_type,
        )
        rows.append(
            SimulatedMissedTrade(
                trade=trade,
                blocked_reason=decision.primary_reason,
                verdict=_simulated_trade_verdict(trade),
                learning=_simulated_trade_learning(trade, decision.primary_reason),
            )
        )
    return tuple(rows)


def excursion(
    trade: BacktestTrade,
    series: CandleSeries | None,
) -> tuple[Decimal, Decimal]:
    if series is None:
        return ZERO, ZERO
    candles = [
        candle
        for candle in series.closed_only().candles
        if trade.entered_at <= candle.close_time <= trade.exited_at
    ]
    if not candles:
        return ZERO, ZERO
    if trade.side == "BUY":
        adverse = max((trade.entry_price - candle.low for candle in candles), default=ZERO)
        favorable = max((candle.high - trade.entry_price for candle in candles), default=ZERO)
    else:
        adverse = max((candle.high - trade.entry_price for candle in candles), default=ZERO)
        favorable = max((trade.entry_price - candle.low for candle in candles), default=ZERO)
    return max(adverse, ZERO).quantize(Decimal("0.01")), max(favorable, ZERO).quantize(Decimal("0.01"))


def _planned_operation(
    decision: BacktestDecisionLog,
) -> tuple[str, Decimal, Decimal, Decimal] | None:
    side = decision.planned_side if decision.planned_side in {"BUY", "SELL"} else decision.side
    entry = decision.planned_entry
    stop = decision.planned_stop
    target = decision.planned_target
    if side not in {"BUY", "SELL"} or entry is None or stop is None or target is None:
        return None
    valid_geometry = (
        stop < entry < target
        if side == "BUY"
        else target < entry < stop
    )
    if not valid_geometry:
        return None
    return side, entry, stop, target


def _first_fill(
    entry: Decimal,
    future: tuple[Candle, ...],
) -> tuple[int | None, datetime | None]:
    for index, candle in enumerate(future):
        if candle.low <= entry <= candle.high:
            return index, candle.close_time
    return None, None


def _fixed_exit(
    *,
    side: str,
    stop: Decimal,
    target: Decimal,
    candles: tuple[Candle, ...],
) -> tuple[Candle, Decimal, str]:
    for candle in candles:
        stop_hit = candle.low <= stop if side == "BUY" else candle.high >= stop
        target_hit = candle.high >= target if side == "BUY" else candle.low <= target
        if stop_hit or target_hit:
            return candle, stop if stop_hit else target, "STOP" if stop_hit else "TARGET"
    last = candles[-1]
    return last, last.close, "HORIZON_END"


def _simulated_quantity(
    *,
    entry: Decimal,
    stop: Decimal,
    side: str,
    risk_profile: RiskProfile,
    costs: ExecutionCostModel,
) -> int:
    try:
        quantity = calculate_ticket_sizing(
            entry=entry,
            stop=stop,
            profile=risk_profile,
        ).quantity
    except ValueError:
        return 0
    max_loss = risk_profile.monetary_risk_per_trade
    for adjusted_quantity in range(quantity, 0, -1):
        entry_execution = costs.entry_price(entry, side)
        stop_execution = costs.exit_price(stop, side)
        fees = costs.fees(entry_execution, stop_execution, adjusted_quantity)
        stop_result = calculate_position_pnl(
            side=side,
            entry_price=entry_execution,
            exit_price=stop_execution,
            stop=stop,
            quantity=adjusted_quantity,
            entered_at=datetime.min,
            exited_at=datetime.min,
            costs=fees,
        )
        if abs(min(stop_result.pnl_value, ZERO)) <= max_loss:
            return adjusted_quantity
    return 0


def _simulated_trade_verdict(trade: BacktestTrade) -> str:
    if trade.net_pnl > 0 and trade.close_reason == "TARGET":
        return "BLOQUEIO_PERDEU_ALVO"
    if trade.net_pnl > 0:
        return "BLOQUEIO_PERDEU_GANHO_PARCIAL"
    if trade.net_pnl < 0:
        return "BLOQUEIO_EVITOU_PREJUIZO"
    return "BLOQUEIO_NEUTRO"


def _simulated_trade_learning(trade: BacktestTrade, blocked_reason: str) -> str:
    if trade.net_pnl > 0:
        return (
            "Estudar relaxamento controlado deste bloqueio quando setup, score, horário e regime "
            f"também forem robustos. Bloqueio original: {blocked_reason}"
        )
    if trade.net_pnl < 0:
        return f"Manter cautela: o bloqueio teria evitado prejuízo. Bloqueio original: {blocked_reason}"
    return f"Sem vantagem líquida clara para mudar a regra. Bloqueio original: {blocked_reason}"


def _loss_cause(
    item: DiagnosticTrade,
    *,
    mae: Decimal,
    mfe: Decimal,
) -> tuple[str, str, str, bool]:
    trade = item.trade
    planned_risk = abs(trade.entry_price - trade.stop)
    cost_pressure = abs(trade.costs) >= max(abs(trade.gross_pnl), Decimal("0.01")) * Decimal("0.30")
    weak_favorable_move = planned_risk > 0 and mfe < planned_risk * Decimal("0.35")
    high_adverse_move = planned_risk > 0 and mae > planned_risk * Decimal("1.20")
    against_trend = (
        (item.regime == "TREND_DOWN" and trade.side == "BUY")
        or (item.regime == "TREND_UP" and trade.side == "SELL")
    )
    if cost_pressure:
        return (
            "CUSTO_INCOMPATIVEL",
            "Custos, spread ou slippage consumiram uma parte grande do resultado bruto.",
            "Bloquear setups cujo alvo esperado não paga o custo operacional realista.",
            True,
        )
    if item.setup_type == "NO_CLEAR_SETUP":
        return (
            "SETUP_INDEFINIDO",
            "A operação entrou sem um tipo de setup técnico claramente classificado.",
            "Exigir setup nomeado e estatística própria antes de liberar entrada.",
            True,
        )
    if against_trend:
        return (
            "CONTRA_TENDENCIA_MAIOR",
            "A direção da operação contrariou a tendência principal detectada no momento.",
            "Separar reversão real de tentativa de antecipar topo ou fundo.",
            True,
        )
    if item.volatility == "HIGH" and item.setup_type != "EXPANSION_BREAKOUT":
        return (
            "VOLATILIDADE_INCOMPATIVEL",
            "A volatilidade estava alta para um setup que não era de expansão.",
            "Em alta volatilidade, exigir rompimento/expansão com confirmação de volume.",
            True,
        )
    if item.regime == "RANGE" and item.setup_type != "RANGE_REVERSION":
        return (
            "SETUP_CONTRA_REGIME",
            "O mercado estava lateral, mas o setup usado não era próprio para range.",
            "Usar retorno à média/VWAP em range e bloquear continuação sem tendência.",
            True,
        )
    if weak_favorable_move and high_adverse_move:
        return (
            "ENTRADA_ATRASADA_OU_EXAUSTAO",
            "Depois da entrada houve pouca excursão favorável e muito movimento contra.",
            "Exigir melhor localização em suporte, resistência, VWAP ou Fibonacci.",
            True,
        )
    if trade.close_reason == "STOP" and planned_risk > 0 and mae <= planned_risk * Decimal("1.05"):
        return (
            "PERDA_NORMAL_DA_ESTRATEGIA",
            "O stop foi atingido dentro do risco planejado, sem evidência forte de erro estrutural.",
            "Manter no estudo estatístico; não ajustar regra só por uma perda isolada.",
            False,
        )
    return (
        "INTERPRETACAO_INCONCLUSIVA",
        "A perda exige comparação com operações vencedoras parecidas antes de mudar regra.",
        "Agrupar por setup, regime, horário, score e ativo para validar a hipótese.",
        False,
    )


def _first_candle_after(candles: tuple[Candle, ...], timestamp: datetime) -> int | None:
    for index, candle in enumerate(candles):
        if candle.close_time >= timestamp:
            return index
    return None


def _future_excursion(
    side: str,
    entry: Decimal,
    future: tuple[Candle, ...],
) -> tuple[Decimal, Decimal]:
    if side == "BUY":
        favorable = max((candle.high - entry for candle in future), default=ZERO)
        adverse = max((entry - candle.low for candle in future), default=ZERO)
    else:
        favorable = max((entry - candle.low for candle in future), default=ZERO)
        adverse = max((candle.high - entry for candle in future), default=ZERO)
    return max(favorable, ZERO), max(adverse, ZERO)


def _retrospective_side(entry: Decimal, future: tuple[Candle, ...]) -> str:
    buy_favorable, buy_adverse = _future_excursion("BUY", entry, future)
    sell_favorable, sell_adverse = _future_excursion("SELL", entry, future)
    buy_quality = buy_favorable - buy_adverse
    sell_quality = sell_favorable - sell_adverse
    return "BUY" if buy_quality >= sell_quality else "SELL"


def _missed_verdict(
    *,
    favorable_pct: Decimal,
    adverse_pct: Decimal,
    ratio: Decimal | None,
    minimum_favorable_move_pct: Decimal,
) -> str:
    if favorable_pct < minimum_favorable_move_pct:
        return "SEM_MOVIMENTO_RELEVANTE"
    if ratio is None and adverse_pct == 0:
        return "BLOQUEIO_POSSIVELMENTE_CONSERVADOR"
    if ratio is not None and ratio >= Decimal("1.50"):
        return "BLOQUEIO_POSSIVELMENTE_CONSERVADOR"
    if adverse_pct > favorable_pct:
        return "BLOQUEIO_PROVAVELMENTE_CORRETO"
    return "MOVIMENTO_AMBIGUO"


def _missed_learning(verdict: str, reason: str) -> str:
    if verdict == "BLOQUEIO_POSSIVELMENTE_CONSERVADOR":
        return f"Investigar se o filtro foi conservador demais: {reason}"
    if verdict == "BLOQUEIO_PROVAVELMENTE_CORRETO":
        return f"O bloqueio evitou risco maior antes do movimento: {reason}"
    return f"Movimento posterior existiu, mas sem vantagem clara: {reason}"


def _group_by_day(
    items: Iterable[T],
    timezone: ZoneInfo,
    timestamp_getter: Callable[[T], datetime],
) -> dict[date, list[T]]:
    grouped: dict[date, list[T]] = {}
    for item in items:
        timestamp = timestamp_getter(item)
        grouped.setdefault(timestamp.astimezone(timezone).date(), []).append(item)
    return grouped


def _common_reason(decisions: list[BacktestDecisionLog] | tuple[BacktestDecisionLog, ...]) -> str:
    if not decisions:
        return "Nenhuma rejeição registrada."
    return Counter(item.primary_reason for item in decisions).most_common(1)[0][0]


def _top_values(values: Iterable[object]) -> tuple[str, ...]:
    counter = Counter(str(value) for value in values if str(value))
    return tuple(value for value, _count in counter.most_common(5))


def _average_decimal(values: Iterable[Decimal]) -> Decimal | None:
    collected = tuple(values)
    if not collected:
        return None
    return (sum(collected, ZERO) / Decimal(len(collected))).quantize(Decimal("0.01"))


def _classify_day(decisions: tuple[BacktestDecisionLog, ...]) -> str:
    if not decisions:
        return "NEUTRO"
    scores = [item.score for item in decisions if item.score > 0]
    if not scores:
        return "NÃO OPERÁVEL"
    average = sum(scores) / len(scores)
    approved = sum(1 for item in decisions if item.should_enter)
    if average >= 85 and approved:
        return "ÓTIMO PARA OPERAR"
    if average >= 75:
        return "BOM PARA OPERAR"
    if average >= 60:
        return "NEUTRO"
    return "RUIM"


def _main_win_reason(trades: list[BacktestTrade]) -> str:
    if not trades:
        return "Nenhuma operação vencedora registrada."
    best = max(trades, key=lambda trade: trade.net_pnl)
    return f"Melhor trade: {best.setup_type} {best.side} encerrou por {best.close_reason}."


def _daily_learning(
    trades: tuple[BacktestTrade, ...],
    autopsies: tuple[LossAutopsy, ...],
    main_avoidance: str,
) -> str:
    if autopsies:
        return f"Principal aprendizado: investigar {autopsies[0].primary_cause} antes de repetir setup."
    if trades:
        return "Dia com operação sem erro negativo registrado; manter comparação fora da amostra."
    return f"Não operei hoje porque: {main_avoidance}"


def _daily_year_groups(
    daily_reports: tuple[DailyLearningReport, ...],
) -> dict[tuple[str, int], list[DailyLearningReport]]:
    groups: dict[tuple[str, int], list[DailyLearningReport]] = {}
    for row in daily_reports:
        groups.setdefault((row.symbol, row.day.year), []).append(row)
    return groups


def _best_condition_labels(
    diagnostics: tuple[DiagnosticTrade, ...],
    *,
    symbol: str,
    year: int,
) -> tuple[str, ...]:
    return _condition_labels(diagnostics, symbol=symbol, year=year, best=True)


def _worst_condition_labels(
    diagnostics: tuple[DiagnosticTrade, ...],
    *,
    symbol: str,
    year: int,
) -> tuple[str, ...]:
    return _condition_labels(diagnostics, symbol=symbol, year=year, best=False)


def _condition_labels(
    diagnostics: tuple[DiagnosticTrade, ...],
    *,
    symbol: str,
    year: int,
    best: bool,
) -> tuple[str, ...]:
    matching = [
        item
        for item in diagnostics
        if item.symbol == symbol and item.year == str(year)
    ]
    by_condition: dict[str, Decimal] = {}
    for item in matching:
        label = f"{item.setup_type} / {item.regime} / {item.hour}"
        by_condition[label] = by_condition.get(label, ZERO) + item.trade.net_pnl
    ranked = sorted(by_condition.items(), key=lambda item: item[1], reverse=best)
    return tuple(f"{label}: R$ {value.quantize(Decimal('0.01'))}" for label, value in ranked[:5])
