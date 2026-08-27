"""Backtest cronológico da mesma FinalDecision usada no fluxo PAPER."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from cashinho.domain.enums import DataStatus, Timeframe
from cashinho.domain.errors import LookaheadError
from cashinho.domain.market import Candle, CandleSeries
from cashinho.domain.risk import RiskProfile
from cashinho.pipeline.entry_signal import EntrySignal
from cashinho.pipeline.final_decision import FinalDecision, make_final_decision
from cashinho.pipeline.indicators import IndicatorSelection
from cashinho.pipeline.multi_timeframe import (
    TimeframeAdvice,
    TimeframeAnalysis,
    advise_timeframe,
    analyze_timeframes,
)
from cashinho.pipeline.opportunities import build_opportunity
from cashinho.pipeline.paper_broker import PaperOrder, PaperOrderStatus, PaperOrderType
from cashinho.pipeline.paper_performance import calculate_position_pnl
from cashinho.pipeline.paper_ticket import build_paper_ticket, calculate_ticket_sizing
from cashinho.pipeline.position_manager import (
    PositionExitReason,
    PositionManager,
    PositionRiskState,
)
from cashinho.pipeline.study_mode import build_market_study

ZERO = Decimal("0")
HUNDRED = Decimal("100")


class BacktestExitMode(StrEnum):
    FIXED = "STOP_TARGET"
    DYNAMIC = "POSITION_MANAGER"


@dataclass(frozen=True, slots=True)
class ExecutionCostModel:
    """Custos isolados da estratégia; todos os valores default são zero."""

    spread: Decimal = ZERO
    slippage: Decimal = ZERO
    fixed_fee_per_order: Decimal = ZERO
    variable_fee_pct: Decimal = ZERO

    def __post_init__(self) -> None:
        values = (self.spread, self.slippage, self.fixed_fee_per_order, self.variable_fee_pct)
        if any(value < 0 for value in values):
            raise ValueError("Custos de execução não podem ser negativos.")

    def entry_price(self, price: Decimal, side: str) -> Decimal:
        friction = self.spread / Decimal("2") + self.slippage
        return price + friction if side == "BUY" else price - friction

    def exit_price(self, price: Decimal, side: str) -> Decimal:
        friction = self.spread / Decimal("2") + self.slippage
        return price - friction if side == "BUY" else price + friction

    def fees(self, entry: Decimal, exit_price: Decimal, quantity: int) -> Decimal:
        notional = (abs(entry) + abs(exit_price)) * Decimal(quantity)
        variable = notional * self.variable_fee_pct / HUNDRED
        return self.fixed_fee_per_order * 2 + variable


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    symbol: str
    side: str
    timeframe: Timeframe
    signal_at: datetime
    entered_at: datetime
    exited_at: datetime
    planned_entry: Decimal
    stop: Decimal
    target: Decimal
    entry_price: Decimal
    exit_price: Decimal
    quantity: int
    close_reason: str
    gross_pnl: Decimal
    costs: Decimal
    net_pnl: Decimal
    pnl_pct: Decimal
    result_in_r: Decimal
    duration: timedelta


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    total_trades: int
    wins: int
    losses: int
    win_rate: Decimal | None
    gross_profit: Decimal
    gross_loss: Decimal
    net_profit: Decimal
    payoff: Decimal | None
    expectancy: Decimal | None
    profit_factor: Decimal | None
    total_r: Decimal
    average_r: Decimal | None
    max_drawdown: Decimal
    max_drawdown_pct: Decimal | None
    max_win_streak: int
    max_loss_streak: int
    average_duration: timedelta | None
    return_pct: Decimal | None
    exposure_pct: Decimal | None
    sharpe: Decimal | None = None
    sortino: Decimal | None = None


@dataclass(frozen=True, slots=True)
class BacktestResult:
    trades: tuple[BacktestTrade, ...]
    metrics: BacktestMetrics
    equity_curve: tuple[tuple[datetime, Decimal], ...]
    drawdown_curve: tuple[tuple[datetime, Decimal], ...]
    unfilled_signals: int = 0
    open_positions_at_end: int = 0


@dataclass(frozen=True, slots=True)
class BacktestComparison:
    fixed: BacktestResult
    dynamic: BacktestResult


@dataclass(frozen=True, slots=True)
class HistoricalPositionContext:
    recent_candles: CandleSeries
    technical_signal: EntrySignal
    timeframe_advice: TimeframeAdvice


class HistoricalDecisionEvaluator(Protocol):
    def evaluate(
        self,
        series_by_timeframe: dict[Timeframe, CandleSeries],
        *,
        as_of: datetime,
    ) -> FinalDecision: ...


class HistoricalPositionContextProvider(Protocol):
    def position_context(
        self,
        series_by_timeframe: dict[Timeframe, CandleSeries],
        *,
        as_of: datetime,
        preferred_timeframe: Timeframe,
    ) -> HistoricalPositionContext: ...


@dataclass(slots=True)
class PipelineDecisionEvaluator:
    """Adaptador histórico que termina obrigatoriamente em make_final_decision."""

    selection: IndicatorSelection
    risk_profile: RiskProfile
    data_quality_approved: bool = True
    minimum_confidence: int = 60
    market_series_by_symbol: dict[str, dict[Timeframe, CandleSeries]] | None = None
    max_history_bars: int = 260
    _analysis_cache: dict[
        tuple[str, Timeframe, datetime | None, datetime | None, int], TimeframeAnalysis
    ] = field(default_factory=dict, init=False, repr=False)

    def _analysis_for(self, timeframe: Timeframe, series: CandleSeries) -> TimeframeAnalysis:
        if self.max_history_bars > 0 and len(series.candles) > self.max_history_bars:
            series = series.model_copy(update={"candles": series.candles[-self.max_history_bars:]})
        first_at = series.candles[0].open_time if series.candles else None
        last_at = series.last.close_time if series.last is not None else None
        cache_key = (series.symbol, timeframe, first_at, last_at, len(series))
        analysis = self._analysis_cache.get(cache_key)
        if analysis is None:
            analysis = analyze_timeframes({timeframe: series}, self.selection)[timeframe]
            self._analysis_cache[cache_key] = analysis
        return analysis

    def evaluate(
        self,
        series_by_timeframe: dict[Timeframe, CandleSeries],
        *,
        as_of: datetime,
    ) -> FinalDecision:
        for series in series_by_timeframe.values():
            series.require_closed()
            if series.last is not None and series.last.close_time > as_of:
                raise LookaheadError("O avaliador histórico recebeu candle posterior ao relógio.")

        analyses: dict[Timeframe, TimeframeAnalysis] = {}
        for timeframe, series in series_by_timeframe.items():
            analyses[timeframe] = self._analysis_for(timeframe, series)
        advice = advise_timeframe(analyses)
        selected = analyses.get(advice.recommended_timeframe) if advice.recommended_timeframe else None
        risk_approved = False
        if (
            selected is not None
            and selected.signal.entry is not None
            and selected.signal.stop is not None
            and not self.risk_profile.kill_switch_active
        ):
            try:
                calculate_ticket_sizing(
                    entry=selected.signal.entry,
                    stop=selected.signal.stop,
                    profile=self.risk_profile,
                )
                risk_approved = True
            except ValueError:
                pass
        selected_last = (
            series_by_timeframe[advice.recommended_timeframe].last
            if advice.recommended_timeframe
            else None
        )
        decision_at = selected_last.close_time if selected_last is not None else as_of
        opportunity = build_opportunity(
            symbol=next(iter(series_by_timeframe.values())).symbol,
            advice=advice,
            analyses=analyses,
            data_status=DataStatus.OK if self.data_quality_approved else DataStatus.BLOCKED,
            risk_approved=risk_approved,
            timestamp=decision_at,
        )
        market_approved = True
        market_reason = None
        extra_reasons: tuple[str, ...] = ()
        if self.market_series_by_symbol:
            market_analyses: dict[str, dict[Timeframe, TimeframeAnalysis]] = {
                next(iter(series_by_timeframe.values())).symbol: analyses
            }
            for symbol, raw_series_by_timeframe in self.market_series_by_symbol.items():
                prefixes = {
                    timeframe: truncate_at(series, as_of)
                    for timeframe, series in raw_series_by_timeframe.items()
                }
                prefixes = {timeframe: series for timeframe, series in prefixes.items() if len(series)}
                if prefixes:
                    market_analyses[symbol] = {
                        timeframe: self._analysis_for(timeframe, series)
                        for timeframe, series in prefixes.items()
                    }
            study = build_market_study(market_analyses, side=advice.side)
            market_approved = study.approved
            market_reason = study.reason
            extra_reasons = (f"Modo Estudo Profundo: {study.summary}",)
        return make_final_decision(
            opportunity,
            data_quality_approved=self.data_quality_approved,
            risk_approved=risk_approved,
            candles_closed=True,
            market_approved=market_approved,
            market_reason=market_reason,
            extra_reasons=extra_reasons,
            minimum_confidence=self.minimum_confidence,
            minimum_risk_reward=self.risk_profile.min_risk_reward,
        )

    def position_context(
        self,
        series_by_timeframe: dict[Timeframe, CandleSeries],
        *,
        as_of: datetime,
        preferred_timeframe: Timeframe,
    ) -> HistoricalPositionContext:
        """Expõe o mesmo contexto técnico, sem qualquer candle posterior a ``as_of``."""

        for series in series_by_timeframe.values():
            series.require_closed()
            if series.last is not None and series.last.close_time > as_of:
                raise LookaheadError("Contexto de posição recebeu candle posterior ao relógio.")
        trimmed = {
            timeframe: series.model_copy(update={"candles": series.candles[-self.max_history_bars:]})
            if self.max_history_bars > 0 and len(series.candles) > self.max_history_bars
            else series
            for timeframe, series in series_by_timeframe.items()
        }
        analyses = analyze_timeframes(trimmed, self.selection)
        advice = advise_timeframe(analyses)
        operational = (
            preferred_timeframe
            if preferred_timeframe in analyses
            else advice.recommended_timeframe
            if advice.recommended_timeframe in analyses
            else min(analyses, key=lambda timeframe: timeframe.duration)
        )
        return HistoricalPositionContext(
            recent_candles=trimmed[operational],
            technical_signal=analyses[operational].signal,
            timeframe_advice=advice,
        )


def truncate_at(series: CandleSeries, as_of: datetime) -> CandleSeries:
    """Projeta somente candles já fechados no instante lógico."""
    candles = tuple(
        candle
        for candle in series.candles
        if candle.is_closed and candle.close_time <= as_of
    )
    return series.model_copy(update={"candles": candles})


def _decision_key(decision: FinalDecision) -> tuple[str, Timeframe | None, datetime, str]:
    return decision.symbol, decision.timeframe, decision.timestamp, decision.side


def _close_trade(
    decision: FinalDecision,
    *,
    entered_at: datetime,
    candle: Candle,
    raw_exit: Decimal,
    close_reason: str,
    quantity: int,
    costs: ExecutionCostModel,
) -> BacktestTrade:
    assert decision.timeframe is not None
    assert decision.entry is not None
    assert decision.stop is not None
    assert decision.target is not None
    entry_execution = costs.entry_price(decision.entry, decision.side)
    exit_execution = costs.exit_price(raw_exit, decision.side)
    fees = costs.fees(entry_execution, exit_execution, quantity)
    gross_result = calculate_position_pnl(
        side=decision.side,
        entry_price=decision.entry,
        exit_price=raw_exit,
        stop=decision.stop,
        quantity=quantity,
        entered_at=entered_at,
        exited_at=candle.close_time,
    )
    net_result = calculate_position_pnl(
        side=decision.side,
        entry_price=entry_execution,
        exit_price=exit_execution,
        stop=decision.stop,
        quantity=quantity,
        entered_at=entered_at,
        exited_at=candle.close_time,
        costs=fees,
    )
    gross = gross_result.pnl_value
    net = net_result.pnl_value
    cost_value = (gross - net).quantize(Decimal("0.01"))
    return BacktestTrade(
        symbol=decision.symbol,
        side=decision.side,
        timeframe=decision.timeframe,
        signal_at=decision.timestamp,
        entered_at=entered_at,
        exited_at=candle.close_time,
        planned_entry=decision.entry,
        stop=decision.stop,
        target=decision.target,
        entry_price=entry_execution,
        exit_price=exit_execution,
        quantity=quantity,
        close_reason=close_reason,
        gross_pnl=gross,
        costs=cost_value,
        net_pnl=net,
        pnl_pct=net_result.pnl_pct,
        result_in_r=net_result.result_in_r,
        duration=net_result.duration or timedelta(),
    )


def _quantity_for(decision: FinalDecision, profile: RiskProfile) -> int:
    assert decision.entry is not None and decision.stop is not None
    return calculate_ticket_sizing(
        entry=decision.entry,
        stop=decision.stop,
        profile=profile,
    ).quantity


def _position_for_backtest(
    decision: FinalDecision,
    *,
    quantity: int,
    entered_at: datetime,
) -> PaperOrder:
    assert decision.entry is not None
    assert decision.stop is not None
    assert decision.target is not None
    assert decision.timeframe is not None
    return PaperOrder(
        id=f"backtest:{decision.symbol}:{decision.timestamp.isoformat()}",
        ticket=build_paper_ticket(
            symbol=decision.symbol,
            side=decision.side,
            entry=decision.entry,
            stop=decision.stop,
            target=decision.target,
            quantity=quantity,
            min_risk_reward=ZERO,
            timeframe=decision.timeframe.value,
        ),
        order_type=PaperOrderType.LIMIT,
        status=PaperOrderStatus.OPEN,
        created_at=decision.timestamp,
        filled_at=entered_at,
        fill_price=decision.entry,
    )


def run_backtest(
    series_by_timeframe: dict[Timeframe, CandleSeries],
    evaluator: HistoricalDecisionEvaluator,
    *,
    risk_profile: RiskProfile,
    costs: ExecutionCostModel | None = None,
    decision_timeframe: Timeframe | None = None,
    exit_mode: BacktestExitMode = BacktestExitMode.FIXED,
    position_manager: PositionManager | None = None,
    position_context_provider: HistoricalPositionContextProvider | None = None,
) -> BacktestResult:
    """Executa candle a candle, com uma posição por ativo e STOP conservador."""
    if not series_by_timeframe:
        raise ValueError("Backtest exige ao menos uma série.")
    symbols = {series.symbol for series in series_by_timeframe.values()}
    if len(symbols) != 1:
        raise ValueError("Cada execução do backtest aceita somente um ativo.")
    closed = {timeframe: series.closed_only() for timeframe, series in series_by_timeframe.items()}
    execution_timeframe = min(closed, key=lambda timeframe: timeframe.duration)
    execution_series = closed[execution_timeframe]
    decision_clock = decision_timeframe or (
        Timeframe.M5 if Timeframe.M5 in closed else execution_timeframe
    )
    if decision_clock not in closed:
        raise ValueError("Timeframe do relógio de decisão não está disponível.")
    decision_times = {candle.close_time for candle in closed[decision_clock].candles}
    cost_model = costs or ExecutionCostModel()
    manager = position_manager or PositionManager()
    context_provider = position_context_provider
    if context_provider is None and isinstance(evaluator, PipelineDecisionEvaluator):
        context_provider = evaluator
    if exit_mode is BacktestExitMode.DYNAMIC and context_provider is None:
        raise ValueError("Modo dinâmico exige um provedor de contexto de posição.")

    pending: FinalDecision | None = None
    entered_at: datetime | None = None
    quantity = 0
    trades: list[BacktestTrade] = []
    seen: set[tuple[str, Timeframe | None, datetime, str]] = set()
    unfilled_signals = 0

    for candle in execution_series.candles:
        if pending is not None:
            assert pending.entry is not None
            assert pending.stop is not None
            assert pending.target is not None
            if entered_at is None and candle.low <= pending.entry <= candle.high:
                entered_at = candle.close_time
                quantity = _quantity_for(pending, risk_profile)

            if entered_at is not None:
                stop_hit = (
                    candle.low <= pending.stop
                    if pending.side == "BUY"
                    else candle.high >= pending.stop
                )
                target_hit = (
                    candle.high >= pending.target
                    if pending.side == "BUY"
                    else candle.low <= pending.target
                )
                if stop_hit or target_hit:
                    # Se ambos ocorrerem sem sequência intrabar, STOP é o cenário conservador.
                    reason = "STOP" if stop_hit else "TARGET"
                    raw_exit = pending.stop if stop_hit else pending.target
                    trades.append(
                        _close_trade(
                            pending,
                            entered_at=entered_at,
                            candle=candle,
                            raw_exit=raw_exit,
                            close_reason=reason,
                            quantity=quantity,
                            costs=cost_model,
                        )
                    )
                    pending = None
                    entered_at = None
                    quantity = 0
                elif (
                    exit_mode is BacktestExitMode.DYNAMIC
                    and candle.close_time in decision_times
                    and candle.close_time > entered_at
                    and context_provider is not None
                ):
                    prefixes = {
                        timeframe: truncate_at(series, candle.close_time)
                        for timeframe, series in closed.items()
                    }
                    assert pending.timeframe is not None
                    context = context_provider.position_context(
                        prefixes,
                        as_of=candle.close_time,
                        preferred_timeframe=pending.timeframe,
                    )
                    context_last = context.recent_candles.last
                    if context_last is None or context_last.close_time != candle.close_time:
                        continue
                    position_decision = manager.evaluate(
                        _position_for_backtest(
                            pending,
                            quantity=quantity,
                            entered_at=entered_at,
                        ),
                        recent_candles=context.recent_candles,
                        technical_signal=context.technical_signal,
                        timeframe_advice=context.timeframe_advice,
                        risk=PositionRiskState(
                            risk_profile.kill_switch_active,
                            "Risk Manager exigiu encerramento no backtest.",
                        ),
                        current_price=candle.close,
                        market_exit_price=candle.close,
                    )
                    if (
                        position_decision.exit_reason
                        not in {None, PositionExitReason.STOP, PositionExitReason.TARGET}
                        and position_decision.exit_price is not None
                    ):
                        trades.append(
                            _close_trade(
                                pending,
                                entered_at=entered_at,
                                candle=candle,
                                raw_exit=position_decision.exit_price,
                                close_reason=position_decision.exit_reason.value,
                                quantity=quantity,
                                costs=cost_model,
                            )
                        )
                        pending = None
                        entered_at = None
                        quantity = 0
            continue

        if candle.close_time not in decision_times:
            continue
        prefixes = {
            timeframe: truncate_at(series, candle.close_time)
            for timeframe, series in closed.items()
        }
        decision = evaluator.evaluate(prefixes, as_of=candle.close_time)
        if decision.timestamp > candle.close_time:
            raise LookaheadError("FinalDecision foi produzida com timestamp futuro.")
        key = _decision_key(decision)
        if decision.should_enter and key not in seen:
            if (
                decision.side not in {"BUY", "SELL"}
                or decision.timeframe is None
                or decision.entry is None
                or decision.stop is None
                or decision.target is None
            ):
                raise ValueError("FinalDecision liberada está incompleta.")
            seen.add(key)
            pending = decision

    if pending is not None and entered_at is None:
        unfilled_signals += 1
    metrics, equity, drawdown = calculate_metrics(
        trades,
        initial_capital=risk_profile.capital,
        period_start=(execution_series.candles[0].open_time if execution_series.candles else None),
        period_end=(execution_series.candles[-1].close_time if execution_series.candles else None),
    )
    return BacktestResult(
        tuple(trades),
        metrics,
        equity,
        drawdown,
        unfilled_signals=unfilled_signals,
        open_positions_at_end=int(pending is not None and entered_at is not None),
    )


def compare_exit_modes(
    series_by_timeframe: dict[Timeframe, CandleSeries],
    evaluator: HistoricalDecisionEvaluator,
    *,
    risk_profile: RiskProfile,
    costs: ExecutionCostModel | None = None,
    decision_timeframe: Timeframe | None = None,
    position_manager: PositionManager | None = None,
    position_context_provider: HistoricalPositionContextProvider | None = None,
) -> BacktestComparison:
    """Executa os modos A/B com as mesmas entradas, dados e custos."""

    fixed_evaluator = deepcopy(evaluator)
    dynamic_evaluator = deepcopy(evaluator)
    fixed = run_backtest(
        series_by_timeframe,
        fixed_evaluator,
        risk_profile=risk_profile,
        costs=costs,
        decision_timeframe=decision_timeframe,
        exit_mode=BacktestExitMode.FIXED,
    )
    dynamic = run_backtest(
        series_by_timeframe,
        dynamic_evaluator,
        exit_mode=BacktestExitMode.DYNAMIC,
        position_manager=position_manager,
        position_context_provider=position_context_provider,
        risk_profile=risk_profile,
        costs=costs,
        decision_timeframe=decision_timeframe,
    )
    return BacktestComparison(fixed, dynamic)


def calculate_metrics(
    trades: list[BacktestTrade],
    *,
    initial_capital: Decimal,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> tuple[
    BacktestMetrics,
    tuple[tuple[datetime, Decimal], ...],
    tuple[tuple[datetime, Decimal], ...],
]:
    wins = [trade for trade in trades if trade.net_pnl > 0]
    losses = [trade for trade in trades if trade.net_pnl < 0]
    total = len(trades)
    gross_profit = sum((trade.net_pnl for trade in wins), ZERO)
    gross_loss = abs(sum((trade.net_pnl for trade in losses), ZERO))
    net = sum((trade.net_pnl for trade in trades), ZERO)
    average_win = gross_profit / len(wins) if wins else None
    average_loss = gross_loss / len(losses) if losses else None
    payoff = (
        (average_win / average_loss).quantize(Decimal("0.01"))
        if average_win is not None and average_loss not in {None, ZERO}
        else None
    )
    expectancy = (net / total).quantize(Decimal("0.01")) if total else None
    profit_factor = (
        (gross_profit / gross_loss).quantize(Decimal("0.01")) if gross_loss else None
    )
    total_r = sum((trade.result_in_r for trade in trades), ZERO).quantize(Decimal("0.01"))
    average_r = (total_r / total).quantize(Decimal("0.01")) if total else None

    equity = initial_capital
    peak = initial_capital
    max_drawdown = ZERO
    max_drawdown_pct = ZERO
    equity_curve: list[tuple[datetime, Decimal]] = []
    drawdown_curve: list[tuple[datetime, Decimal]] = []
    win_streak = loss_streak = max_win_streak = max_loss_streak = 0
    for trade in trades:
        equity += trade.net_pnl
        peak = max(peak, equity)
        drawdown = peak - equity
        drawdown_pct = drawdown / peak * HUNDRED if peak else ZERO
        max_drawdown = max(max_drawdown, drawdown)
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)
        equity_curve.append((trade.exited_at, equity.quantize(Decimal("0.01"))))
        drawdown_curve.append((trade.exited_at, drawdown_pct.quantize(Decimal("0.01"))))
        if trade.net_pnl > 0:
            win_streak += 1
            loss_streak = 0
        elif trade.net_pnl < 0:
            loss_streak += 1
            win_streak = 0
        max_win_streak = max(max_win_streak, win_streak)
        max_loss_streak = max(max_loss_streak, loss_streak)

    average_duration = (
        sum((trade.duration for trade in trades), timedelta()) / total if total else None
    )
    return_pct = (
        (net / initial_capital * HUNDRED).quantize(Decimal("0.01"))
        if initial_capital
        else None
    )
    exposure_pct = None
    if period_start is not None and period_end is not None and period_end > period_start:
        invested = sum((trade.duration for trade in trades), timedelta())
        exposure_pct = min(
            HUNDRED,
            Decimal(str(invested.total_seconds()))
            / Decimal(str((period_end - period_start).total_seconds()))
            * HUNDRED,
        ).quantize(Decimal("0.01"))
    metrics = BacktestMetrics(
        total_trades=total,
        wins=len(wins),
        losses=len(losses),
        win_rate=(Decimal(len(wins)) / Decimal(total) * HUNDRED).quantize(Decimal("0.01"))
        if total
        else None,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_profit=net,
        payoff=payoff,
        expectancy=expectancy,
        profit_factor=profit_factor,
        total_r=total_r,
        average_r=average_r,
        max_drawdown=max_drawdown.quantize(Decimal("0.01")),
        max_drawdown_pct=max_drawdown_pct.quantize(Decimal("0.01")) if trades else None,
        max_win_streak=max_win_streak,
        max_loss_streak=max_loss_streak,
        average_duration=average_duration,
        return_pct=return_pct,
        exposure_pct=exposure_pct,
    )
    return metrics, tuple(equity_curve), tuple(drawdown_curve)


def temporal_split(
    series_by_timeframe: dict[Timeframe, CandleSeries],
    *,
    train_pct: int = 60,
    validation_pct: int = 20,
) -> dict[str, dict[Timeframe, CandleSeries]]:
    """Divide cada série em blocos cronológicos contíguos, nunca aleatórios."""
    if train_pct <= 0 or validation_pct <= 0 or train_pct + validation_pct >= 100:
        raise ValueError("Split exige percentuais positivos e TEST maior que zero.")
    closed = {
        timeframe: series.closed_only() for timeframe, series in series_by_timeframe.items()
    }
    if not closed:
        return {"TRAIN": {}, "VALIDATION": {}, "TEST": {}}
    reference = closed[min(closed, key=lambda timeframe: timeframe.duration)]
    first = len(reference) * train_pct // 100
    second = len(reference) * (train_pct + validation_pct) // 100
    if first == 0 or second <= first or second >= len(reference):
        raise ValueError("Séries insuficientes para o split temporal solicitado.")
    train_end = reference.candles[first - 1].close_time
    validation_end = reference.candles[second - 1].close_time

    result: dict[str, dict[Timeframe, CandleSeries]] = {
        "TRAIN": {},
        "VALIDATION": {},
        "TEST": {},
    }
    for timeframe, series in closed.items():
        slices = {
            "TRAIN": tuple(c for c in series.candles if c.close_time <= train_end),
            "VALIDATION": tuple(
                c for c in series.candles if train_end < c.close_time <= validation_end
            ),
            "TEST": tuple(c for c in series.candles if c.close_time > validation_end),
        }
        for label, candles in slices.items():
            result[label][timeframe] = series.model_copy(update={"candles": candles})
    return result


def metrics_by(
    trades: tuple[BacktestTrade, ...],
    *,
    initial_capital: Decimal,
    field: str,
) -> dict[str, BacktestMetrics]:
    """Segmenta por symbol, side ou timeframe sem recalcular regras de entrada."""
    if field not in {"symbol", "side", "timeframe"}:
        raise ValueError("Segmentação inválida.")
    groups: dict[str, list[BacktestTrade]] = {}
    for trade in trades:
        raw = getattr(trade, field)
        key = raw.value if isinstance(raw, Timeframe) else str(raw)
        groups.setdefault(key, []).append(trade)
    return {
        key: calculate_metrics(group, initial_capital=initial_capital)[0]
        for key, group in groups.items()
    }
