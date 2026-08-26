"""Provider de dados de mercado em tempo real via MetaTrader 5.

    B3 -> Genial -> MetaTrader 5 -> este adapter -> dominio do Cashinho

Validado contra o terminal `Genial Investimentos MetaTrader 5`, servidor
`GenialInvestimentos-PRD`, com PETR4.

SOMENTE LEITURA
---------------
Implementa `MarketDataProvider`, cuja interface nao tem nenhum metodo de
envio de ordem. Nao ha aqui `order_send` nem equivalente, e ha teste que
percorre a arvore sintatica do pacote para garantir isso.

DUAS LICOES DO TERMINAL REAL
----------------------------
1. `symbol_info_tick()` **nao serve** como retrato do mercado: ele voltou com
   `bid=0.0`, `ask=0.0` e `last=42.11` existindo historico valido de bid/ask.
   Por isso a cotacao e montada de duas fontes separadas -
   `COPY_TICKS_INFO` para bid/ask e `COPY_TICKS_TRADE` para last/volume.
2. `bid` e `ask` zerados **nao sao preco**: sao ausencia de livro. Viram
   `None` com `FeedStatus.NO_ACTIVE_BOOK`, e o ultimo negocio permanece
   disponivel a parte. Preencher bid com o last seria inventar cotacao
   (regra 5).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from cashinho.adapters.providers.metatrader.broker_time import (
    DEFAULT_SERVER_TIMEZONE,
    BrokerTimeNormalizer,
)
from cashinho.adapters.providers.metatrader.symbols import (
    SymbolResolution,
    resolve_symbol,
)
from cashinho.adapters.providers.metatrader.terminal import (
    TICKS_INFO,
    TICKS_TRADE,
    MetaTraderError,
    MetaTraderTerminal,
    MetaTraderUnavailableError,
    TerminalInfo,
)
from cashinho.core.time.b3_calendar import B3Calendar
from cashinho.domain.enums import FeedStatus, Timeframe
from cashinho.domain.errors import CashinhoError
from cashinho.domain.market import Candle, CandleSeries, Quote
from cashinho.domain.types import ensure_utc
from cashinho.observability.logging import get_logger
from cashinho.ports.clock import Clock
from cashinho.ports.market_data import ProviderCapabilities

logger = get_logger(__name__)

PROVIDER_NAME = "metatrader"

TICK_LOOKBACK_MINUTES = 30
"""Janela de ticks consultada para montar a cotacao."""

DEFAULT_STALE_SECONDS = 60

_CANDLES_PER_DAY: dict[Timeframe, int] = {
    Timeframe.M1: 400,
    Timeframe.M5: 80,
    Timeframe.M15: 28,
    Timeframe.M30: 14,
    Timeframe.H1: 8,
    Timeframe.D1: 1,
}


class MetaTraderProviderError(CashinhoError):
    """Falha ao obter dados do MetaTrader."""


class MetaTraderMarketDataProvider:
    """Cotacao e candles reais do terminal da corretora.

    Recebe `Clock` por injecao: nenhuma leitura de tempo acontece com
    `datetime.now()` (regra 1).
    """

    def __init__(
        self,
        clock: Clock,
        *,
        terminal: MetaTraderTerminal | None = None,
        terminal_path: str = "",
        server_timezone: str = DEFAULT_SERVER_TIMEZONE,
        stale_seconds: int = DEFAULT_STALE_SECONDS,
        allow_prefix_match: bool = False,
        calendar: B3Calendar | None = None,
        name: str = PROVIDER_NAME,
    ) -> None:
        self._clock = clock
        self._terminal = terminal or MetaTraderTerminal(terminal_path)
        self._time = BrokerTimeNormalizer(server_timezone)
        self._stale_seconds = stale_seconds
        self._allow_prefix = allow_prefix_match
        self._calendar = calendar or B3Calendar()
        self._name = name
        self._info: TerminalInfo | None = None
        self._resolved: dict[str, SymbolResolution] = {}

    # ------------------------------------------------------------------
    # capacidades e conexao
    # ------------------------------------------------------------------
    @property
    def capabilities(self) -> ProviderCapabilities:
        """Declaracao do que este provedor entrega.

        `supports_realtime=True` e o que habilita PAPER por D9 - e a primeira
        fonte do projeto capaz disso. O atraso declarado e zero porque o feed
        vem do proprio terminal, nao de uma API com defasagem de plano.
        """
        return ProviderCapabilities(
            name=self._name,
            supports_realtime=True,
            typical_delay_seconds=0,
            min_timeframe=Timeframe.M1,
            intraday_history_days=0,
            supports_quotes=True,
            notes=(
                "MetaTrader 5 da corretora, somente leitura. Exige o terminal "
                "aberto e autenticado manualmente. Nao envia ordens."
            ),
        )

    @property
    def available(self) -> bool:
        """A biblioteca MetaTrader5 existe neste sistema?"""
        return self._terminal.available

    def connect(self) -> TerminalInfo:
        """Liga no terminal ja aberto. Sem credencial: quem autentica e voce."""
        info = self._terminal.connect()
        self._info = info
        if info.connected:
            logger.info(
                "terminal metatrader conectado",
                extra={"company": info.company, "server": info.server},
            )
        else:
            logger.warning("terminal metatrader indisponivel", extra={"reason": info.reason})
        return info

    def terminal_info(self, *, refresh: bool = False) -> TerminalInfo:
        if self._info is None or refresh:
            return self.connect()
        return self._info

    # ------------------------------------------------------------------
    # simbolos
    # ------------------------------------------------------------------
    def resolve(self, symbol: str) -> SymbolResolution:
        """Exata primeiro; ambiguidade e ausencia sao erro, nunca escolha."""
        key = symbol.strip().upper()
        cached = self._resolved.get(key)
        if cached is not None:
            return cached

        self._require_terminal()
        resolution = resolve_symbol(
            key, self._terminal.symbols(), allow_prefix=self._allow_prefix
        )
        self._terminal.select(resolution.resolved)
        self._resolved[key] = resolution
        logger.info(
            "simbolo resolvido",
            extra={"requested": key, "resolved": resolution.resolved,
                   "exact": resolution.exact},
        )
        return resolution

    def list_symbols(self) -> tuple[str, ...]:
        try:
            self._require_terminal()
        except CashinhoError:
            return ()
        return self._terminal.symbols()

    def get_available_timeframes(self, symbol: str) -> tuple[Timeframe, ...]:
        """Todos os timeframes do dominio - o MT5 os cobre por construcao."""
        self.resolve(symbol)
        return tuple(Timeframe)

    # ------------------------------------------------------------------
    # cotacao: duas fontes, nunca symbol_info_tick
    # ------------------------------------------------------------------
    def get_quote(self, symbol: str) -> Quote:
        """Cotacao consolidada, com os dois relogios separados."""
        resolution = self.resolve(symbol)
        now = self._clock.now()

        bid, ask, quote_time = self._latest_book(resolution.resolved, now)
        last, volume, trade_time = self._latest_trade(resolution.resolved, now)

        if last is None and bid is None:
            raise MetaTraderProviderError(
                f"{resolution.resolved}: nenhum tick de cotacao ou negocio na "
                f"janela de {TICK_LOOKBACK_MINUTES} min"
            )

        reference = max(t for t in (quote_time, trade_time) if t is not None)
        price = last if last is not None else _midpoint(bid, ask)
        if price is None:  # pragma: no cover - impossivel pelas guardas acima
            raise MetaTraderProviderError(f"{resolution.resolved}: sem preco utilizavel")

        latency_ms = max(int((now - reference).total_seconds() * 1000), 0)
        return Quote(
            symbol=resolution.resolved,
            price=price,
            timestamp=reference,
            source=f"{self._name}:{resolution.resolved}",
            latency_ms=latency_ms,
            bid=bid,
            ask=ask,
            bid_ask_time=quote_time,
            trade_time=trade_time,
            trade_volume=volume,
        )

    def feed_status(self, symbol: str) -> FeedStatus:
        """Estado do feed. `initialize() == True` nao basta para dizer ONLINE.

        Nao se apoia em `get_quote` de proposito: sem tick na janela a cotacao
        nao existe, e isso significa coisas diferentes conforme a hora. Fora
        do pregao, silencio e o esperado (`MARKET_CLOSED`); com o mercado
        aberto, e a fonte que parou (`STALE`). Chamar os dois de OFFLINE
        misturaria "terminal caido" com "nada a buscar".
        """
        info = self.terminal_info()
        if not info.connected:
            return FeedStatus.OFFLINE

        now = self._clock.now()
        market_open = self._calendar.is_open(now)

        try:
            bid, ask, quote_time = self._latest_book(symbol, now)
            _, _, trade_time = self._latest_trade(symbol, now)
        except CashinhoError:
            return FeedStatus.OFFLINE

        moments = [t for t in (quote_time, trade_time) if t is not None]
        if not moments:
            return FeedStatus.STALE if market_open else FeedStatus.MARKET_CLOSED

        age = (now - max(moments)).total_seconds()
        if age > self._stale_seconds:
            return FeedStatus.STALE if market_open else FeedStatus.MARKET_CLOSED
        if bid is None or ask is None:
            return FeedStatus.NO_ACTIVE_BOOK
        return FeedStatus.ONLINE

    # ------------------------------------------------------------------
    # candles
    # ------------------------------------------------------------------
    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        *,
        start: datetime,
        end: datetime,
    ) -> CandleSeries:
        """Candles com `start <= open_time < end`, em ordem cronologica.

        O candle em formacao chega com `is_closed=False` - o dominio ja modela
        isso, e quem exige fechamento chama `closed_only()` ou
        `require_closed()`. Descartar aqui esconderia do chamador que existe um
        candle em andamento.
        """
        resolution = self.resolve(symbol)
        start_utc = ensure_utc(start)
        end_utc = ensure_utc(end)
        if end_utc <= start_utc:
            raise ValueError(
                f"intervalo invalido: end ({end_utc.isoformat()}) deve ser "
                f"posterior a start ({start_utc.isoformat()})"
            )

        count = self._candle_count(timeframe, start_utc, end_utc)
        try:
            raw = self._terminal.rates(resolution.resolved, timeframe, count)
        except (MetaTraderError, MetaTraderUnavailableError) as exc:
            raise MetaTraderProviderError(str(exc)) from exc

        now = self._clock.now()
        snapshot_time = self._rates_snapshot_time(raw, now)
        candles = tuple(
            candle
            for candle in (
                self._to_candle(row, timeframe, snapshot_time) for row in raw
            )
            if candle is not None and start_utc <= candle.open_time < end_utc
        )

        logger.info(
            "candles carregados",
            extra={
                "symbol": resolution.resolved,
                "timeframe": timeframe.value,
                "candles": len(candles),
                "source": self._name,
            },
        )
        return CandleSeries(
            symbol=resolution.resolved,
            timeframe=timeframe,
            candles=candles,
            source=f"{self._name}:{resolution.resolved}",
            fetched_at=now,
        )

    # ------------------------------------------------------------------
    # internos
    # ------------------------------------------------------------------
    def _require_terminal(self) -> TerminalInfo:
        info = self.terminal_info()
        if not info.connected:
            raise MetaTraderProviderError(
                f"TERMINAL OFFLINE: {info.reason or 'o MetaTrader nao esta conectado'}. "
                "Abra o terminal da corretora e autentique antes de usar esta fonte"
            )
        return info

    def _recent_ticks(
        self, symbol: str, kind: str, now: datetime) -> list[dict[str, Any]]:
        """Ticks da janela recente, em ordem cronologica.

        O intervalo termina em `agora` de proposito: pedir "os N primeiros a
        partir de ha 30 minutos" devolve o comeco da janela quando o mercado
        esta movimentado, e o adapter passaria a entregar preco velho.
        """
        server_wall = self._time.server_now(now)

        # O terminal da Genial indexa os ticks pelo relogio de parede do
        # servidor, mas a API Python do MT5 exige datetime timezone-aware.
        # Mantemos o horario da Genial e o marcamos como UTC somente
        # para montar a consulta ao copy_ticks_range.
        server_now = server_wall.replace(tzinfo=UTC)

        start = server_now - timedelta(minutes=TICK_LOOKBACK_MINUTES)

        try:
            ticks = self._terminal.ticks_range(
                symbol,
                start,
                server_now,
                kind,
            )
        except (MetaTraderError, MetaTraderUnavailableError) as exc:
            logger.warning(
                "falha ao ler ticks",
                extra={"symbol": symbol, "kind": kind, "error": str(exc)},
            )
            return []

        return list(ticks)

    def _latest_book(
        self, symbol: str, now: datetime
    ) -> tuple[Decimal | None, Decimal | None, datetime | None]:
        """O estado ATUAL do livro - o ultimo evento de cotacao, e so ele.

        Nao ha recuo: se o evento mais recente traz bid ou ask zerado, o livro
        **nao esta ativo agora**, e a resposta e ausencia. Procurar para tras
        um tick com precos validos devolveria um livro que ja nao existe, com
        cara de cotacao atual - o erro mais caro que esta camada pode cometer.

        O instante e devolvido mesmo sem livro: ele prova que o feed esta
        vivo, o que separa NO_ACTIVE_BOOK de OFFLINE.
        """
        ticks = self._recent_ticks(symbol, TICKS_INFO, now)
        if not ticks:
            return None, None, None

        latest = ticks[-1]
        moment = self._moment(latest)
        bid = _price(latest.get("bid"))
        ask = _price(latest.get("ask"))
        if bid is None or ask is None:
            # um lado zerado ja e livro inativo: meio book nao e cotacao
            return None, None, moment
        return bid, ask, moment

    def _latest_trade(
        self, symbol: str, now: datetime
    ) -> tuple[Decimal | None, int | None, datetime | None]:
        """Last/volume do ultimo tick de NEGOCIO com preco valido."""
        # negocio e evento, nao estado: o ultimo negocio VALIDO continua sendo
        # o ultimo negocio, mesmo que depois dele venham ticks sem preco
        for tick in reversed(self._recent_ticks(symbol, TICKS_TRADE, now)):
            last = _price(tick.get("last"))
            if last is not None:
                raw_volume = tick.get("volume_real") or tick.get("volume")
                return last, _volume(raw_volume), self._moment(tick)
        return None, None, None

    def _moment(self, tick: dict[str, Any]) -> datetime | None:
        """O relogio do tick, normalizado para UTC. Prefere `time_msc`."""
        if tick.get("time_msc"):
            return self._time.to_utc_msc(tick["time_msc"])
        if tick.get("time"):
            return self._time.to_utc(tick["time"])
        return None

    def _to_candle(
        self, row: dict[str, Any], timeframe: Timeframe, now: datetime
    ) -> Candle | None:
        """Uma linha do MT5 vira `Candle`, ou e descartada com o resto intacto."""
        raw_time = row.get("time")
        if raw_time is None:
            return None
        try:
            open_time = self._time.to_utc(raw_time)
            close_time = open_time + timeframe.duration
            volume = _volume(row.get("real_volume") or row.get("tick_volume")) or 0
            return Candle(
                open_time=open_time,
                close_time=close_time,
                open=_require_price(row["open"]),
                high=_require_price(row["high"]),
                low=_require_price(row["low"]),
                close=_require_price(row["close"]),
                volume=volume,
                is_closed=close_time <= now,
            )
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return None

    def _rates_snapshot_time(
        self, rows: tuple[dict[str, Any], ...], fallback: datetime
    ) -> datetime:
        """Instante minimo da foto dos candles retornados pelo MT5."""
        opened_at: list[datetime] = []
        for row in rows:
            raw_time = row.get("time")
            if raw_time is None:
                continue
            try:
                opened_at.append(self._time.to_utc(raw_time))
            except (TypeError, ValueError, OverflowError):
                continue
        return max((fallback, *opened_at))

    def _candle_count(self, timeframe: Timeframe, start: datetime, end: datetime) -> int:
        """Quantos candles pedir ao terminal para cobrir o intervalo."""
        days = max((end - start).days + 1, 1)
        per_day = _CANDLES_PER_DAY.get(timeframe, 100)
        return min(max(days * per_day + 2, 10), 50_000)


def _price(value: Any) -> Decimal | None:
    """Preco valido, ou `None`. **Zero nunca e preco.**"""
    if value is None:
        return None
    try:
        price = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return price if price > 0 else None


def _require_price(value: Any) -> Decimal:
    price = _price(value)
    if price is None:
        raise ValueError(f"preco invalido: {value!r}")
    return price


def _volume(value: Any) -> int | None:
    if value is None:
        return None
    try:
        volume = int(float(value))
    except (TypeError, ValueError):
        return None
    return volume if volume >= 0 else None


def _midpoint(bid: Decimal | None, ask: Decimal | None) -> Decimal | None:
    """Meio do livro - so quando ha os dois lados e nao ha negocio recente."""
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2
