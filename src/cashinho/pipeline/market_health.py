"""Diagnostico operacional da fonte de mercado."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from cashinho.adapters.providers.factory import ProviderChoice
from cashinho.core.data_quality.gate import DEFAULT_MINIMUM_CANDLES, evaluate
from cashinho.domain.enums import DataStatus, FeedStatus, Mode, Timeframe
from cashinho.domain.market import CandleSeries, Quote
from cashinho.domain.quality import DataQualityReport
from cashinho.observability.logging import get_logger
from cashinho.ports.clock import Clock

logger = get_logger(__name__)


class MarketHealthColor(StrEnum):
    GREEN = "VERDE"
    YELLOW = "AMARELO"
    RED = "VERMELHO"


@dataclass(frozen=True, slots=True)
class MarketHealthReport:
    symbol: str
    timeframe: Timeframe
    color: MarketHealthColor
    status: str
    reason: str
    mt5_connected: bool
    account_mode: str
    server: str
    current_time: datetime
    last_tick_at: datetime | None
    last_candle_at: datetime | None
    last_candle_close_at: datetime | None
    data_age_seconds: float | None
    spread: object | None
    candles_loaded: int
    feed_status: FeedStatus | None
    data_quality: DataQualityReport | None
    quote: Quote | None
    series: CandleSeries | None

    @property
    def blocks_signal(self) -> bool:
        return self.color is MarketHealthColor.RED


def assess_market_health(
    choice: ProviderChoice,
    *,
    symbol: str,
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
    clock: Clock,
    mode: Mode = Mode.PAPER,
    minimum_candles: int = DEFAULT_MINIMUM_CANDLES,
) -> MarketHealthReport:
    """Mede se o app pode confiar no dado atual para decisao ao vivo."""
    now = clock.now()
    if not choice.is_metatrader:
        reason = "Fonte ativa nao e MT5 em tempo real."
        logger.warning(
            "saude do mercado reprovada",
            extra={"symbol": symbol, "timeframe": timeframe.value, "reason": reason},
        )
        return _failed(symbol, timeframe, now, reason)

    provider = choice.provider
    try:
        info = provider.terminal_info(refresh=True)  # type: ignore[attr-defined]
    except Exception as exc:
        reason = f"Falha ao consultar terminal MT5: {exc}"
        logger.warning(
            "saude do mercado reprovada",
            extra={"symbol": symbol, "timeframe": timeframe.value, "reason": reason},
        )
        return _failed(symbol, timeframe, now, reason)

    if not info.connected:
        reason = info.reason or "Terminal MT5 offline."
        logger.warning(
            "saude do mercado reprovada",
            extra={"symbol": symbol, "timeframe": timeframe.value, "reason": reason},
        )
        return _failed(
            symbol,
            timeframe,
            now,
            reason,
            account_mode=info.account_mode,
            server=info.server,
        )

    quote: Quote | None = None
    series: CandleSeries | None = None
    data_quality: DataQualityReport | None = None
    feed_status: FeedStatus | None = None
    reasons: list[str] = []
    color = MarketHealthColor.GREEN

    try:
        feed_status = provider.feed_status(symbol)  # type: ignore[attr-defined]
        quote = provider.get_quote(symbol)
    except Exception as exc:
        reasons.append(f"Cotacao indisponivel: {exc}")
        color = MarketHealthColor.RED

    try:
        series = provider.get_candles(symbol, timeframe, start=start, end=end)
        data_quality = evaluate(
            series,
            clock=clock,
            mode=mode,
            minimum_candles=minimum_candles,
        )
    except Exception as exc:
        reasons.append(f"Candles indisponiveis: {exc}")
        color = MarketHealthColor.RED

    if feed_status in {FeedStatus.OFFLINE, FeedStatus.STALE}:
        color = MarketHealthColor.RED
        reasons.append(f"Feed {feed_status.value}.")
    elif feed_status is FeedStatus.NO_ACTIVE_BOOK and color is MarketHealthColor.GREEN:
        color = MarketHealthColor.YELLOW
        reasons.append("Livro ativo incompleto.")

    if data_quality is not None:
        if data_quality.status is DataStatus.BLOCKED:
            color = MarketHealthColor.RED
            reasons.extend(issue.message for issue in data_quality.critical_issues)
        elif data_quality.status is DataStatus.DEGRADED and color is MarketHealthColor.GREEN:
            color = MarketHealthColor.YELLOW
            reasons.extend(issue.message for issue in data_quality.issues)

    last_candle = series.last if series is not None else None
    last_closed_candle = series.closed_only().last if series is not None else None
    last_tick_at = quote.timestamp if quote is not None else None
    last_candle_close_at = (
        last_closed_candle.close_time if last_closed_candle is not None else None
    )
    latest_data = max(
        (moment for moment in (last_tick_at, last_candle_close_at) if moment is not None),
        default=None,
    )
    data_age = max((now - latest_data).total_seconds(), 0) if latest_data is not None else None
    reason = "Dados atuais." if not reasons else " ".join(dict.fromkeys(reasons))
    status = color.value
    if color is MarketHealthColor.RED:
        logger.warning(
            "sinal bloqueado pela saude do mercado",
            extra={
                "symbol": symbol,
                "timeframe": timeframe.value,
                "status": status,
                "reason": reason,
            },
        )
    return MarketHealthReport(
        symbol=symbol,
        timeframe=timeframe,
        color=color,
        status=status,
        reason=reason,
        mt5_connected=True,
        account_mode=info.account_mode,
        server=info.server,
        current_time=now,
        last_tick_at=last_tick_at,
        last_candle_at=last_candle.open_time if last_candle is not None else None,
        last_candle_close_at=last_candle_close_at,
        data_age_seconds=data_age,
        spread=quote.spread if quote is not None else None,
        candles_loaded=len(series) if series is not None else 0,
        feed_status=feed_status,
        data_quality=data_quality,
        quote=quote,
        series=series,
    )


def _failed(
    symbol: str,
    timeframe: Timeframe,
    now: datetime,
    reason: str,
    *,
    account_mode: str = "DESCONHECIDO",
    server: str = "",
) -> MarketHealthReport:
    return MarketHealthReport(
        symbol=symbol,
        timeframe=timeframe,
        color=MarketHealthColor.RED,
        status=MarketHealthColor.RED.value,
        reason=reason,
        mt5_connected=False,
        account_mode=account_mode,
        server=server,
        current_time=now,
        last_tick_at=None,
        last_candle_at=None,
        last_candle_close_at=None,
        data_age_seconds=None,
        spread=None,
        candles_loaded=0,
        feed_status=None,
        data_quality=None,
        quote=None,
        series=None,
    )
