"""Dublê da biblioteca MetaTrader5, fiel ao terminal real da Genial.

Os valores vem do teste executado na maquina do operador:

    17:32:41.596 | QUOTE | BID 42.06 | ASK 42.07
    17:32:41.601 | TRADE | LAST 42.07 | VOL 400

Inclusive o comportamento que motivou separar cotacao de negocio: os ticks de
`COPY_TICKS_TRADE` chegam com `bid=0.0` e `ask=0.0`, e vice-versa.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

SAO_PAULO = ZoneInfo("America/Sao_Paulo")

NOW = datetime(2026, 8, 20, 17, 32, 45, tzinfo=UTC)
"""Quinta-feira, 14:32:45 em Sao Paulo - dentro do pregao regular.

O tick real observado foi as 17:32:41, ja no leilao de fechamento. O
`B3Calendar` desta base modela o pregao regular ate as 17:00, entao os testes
de feed usam um instante intradiario para nao confundir 'mercado fechado' com
'feed parado' - a distincao que estes testes existem para verificar.
"""

GENIAL_SYMBOLS: tuple[str, ...] = (
    "PETR4", "PETR4F", "PETR4T", "PETR4M", "PETR4Q", "PETR4R", "VALE3", "ITUB4",
)


def server_epoch(moment: datetime) -> float:
    """O inteiro que o MT5 devolveria para esse instante."""
    wall = moment.astimezone(SAO_PAULO).replace(tzinfo=None)
    return wall.replace(tzinfo=UTC).timestamp()


def quote_tick(
    bid: float = 42.06, ask: float = 42.07, moment: datetime | None = None
) -> dict[str, Any]:
    when = moment or (NOW - timedelta(seconds=4))
    return {
        "time": int(server_epoch(when)),
        "time_msc": int(server_epoch(when) * 1000) + 596,
        "bid": bid,
        "ask": ask,
        "last": 0.0,
        "volume": 0,
    }


def trade_tick(
    last: float = 42.07, volume: int = 400, moment: datetime | None = None
) -> dict[str, Any]:
    when = moment or (NOW - timedelta(seconds=4))
    return {
        "time": int(server_epoch(when)),
        "time_msc": int(server_epoch(when) * 1000) + 601,
        "bid": 0.0,
        "ask": 0.0,
        "last": last,
        "volume": volume,
    }


def rate(minutes_ago: int, price: float = 42.0) -> dict[str, Any]:
    """Um candle do MT5, marcado pela ABERTURA do periodo."""
    when = NOW - timedelta(minutes=minutes_ago)
    return {
        "time": int(server_epoch(when)),
        "open": price,
        "high": price * 1.002,
        "low": price * 0.998,
        "close": price * 1.001,
        "tick_volume": 1200,
        "real_volume": 340_000,
        "spread": 1,
    }


class FakeMetaTrader5:
    """Implementa apenas o que o adapter usa - nada de envio de ordem."""

    COPY_TICKS_INFO = 1
    COPY_TICKS_TRADE = 2
    TIMEFRAME_M1 = 1
    TIMEFRAME_M2 = 2
    TIMEFRAME_M5 = 5
    TIMEFRAME_M10 = 10
    TIMEFRAME_M15 = 15
    TIMEFRAME_M30 = 30
    TIMEFRAME_H1 = 16385
    TIMEFRAME_D1 = 16408
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_CONTEST = 1
    ACCOUNT_TRADE_MODE_REAL = 2
    __version__ = "5.0.45"

    def __init__(
        self,
        *,
        connected: bool = True,
        initialize_ok: bool = True,
        symbols: Sequence[str] = GENIAL_SYMBOLS,
        quote_ticks: Sequence[dict[str, Any]] | None = None,
        trade_ticks: Sequence[dict[str, Any]] | None = None,
        rates: Sequence[dict[str, Any]] | None = None,
        error: tuple[int, str] = (0, "sem erro"),
    ) -> None:
        self._connected = connected
        self._initialize_ok = initialize_ok
        self._symbols = list(symbols)
        self._quote_ticks = sorted(
            quote_ticks if quote_ticks is not None else [quote_tick()],
            key=lambda t: t["time"],
        )
        self._trade_ticks = sorted(
            trade_ticks if trade_ticks is not None else [trade_tick()],
            key=lambda t: t["time"],
        )
        self._rates = list(rates if rates is not None else [rate(m) for m in (3, 2, 1)])
        self._error = error
        self.selected: list[str] = []
        self.calls: list[str] = []

    def initialize(self, path: str = "") -> bool:
        self.calls.append(f"initialize({path})")
        return self._initialize_ok

    def shutdown(self) -> None:
        self.calls.append("shutdown")

    def last_error(self) -> tuple[int, str]:
        return self._error

    def terminal_info(self) -> Any:
        if not self._initialize_ok:
            return None
        return type(
            "Info",
            (),
            {"connected": self._connected, "company": "Genial Investimentos",
             "path": r"C:\\Program Files\\Genial Investimentos MetaTrader 5"},
        )()

    def account_info(self) -> Any:
        """Traz login e saldo - que o adapter NAO pode expor."""
        return type(
            "Account",
            (),
            {"server": "GenialInvestimentos-PRD", "login": 123456,
             "balance": 98765.43, "trade_mode": self.ACCOUNT_TRADE_MODE_REAL},
        )()

    def symbols_get(self) -> list[Any]:
        return [type("Symbol", (), {"name": name})() for name in self._symbols]

    def symbol_select(self, symbol: str, enable: bool) -> bool:
        self.selected.append(symbol)
        return symbol in self._symbols

    def copy_ticks_from(
        self, symbol: str, since: datetime, count: int, kind: int
    ) -> list[dict[str, Any]]:
        """Os **primeiros** `count` ticks a partir de `since`.

        E o comportamento real da biblioteca, e a razao de o adapter nao usar
        esta funcao: com mercado movimentado, `count` enche com o comeco da
        janela e os eventos recentes ficam de fora.
        """
        self.calls.append(f"copy_ticks_from({symbol}, {kind})")
        stream = self._quote_ticks if kind == self.COPY_TICKS_INFO else self._trade_ticks
        dentro = [t for t in stream if t["time"] >= since.replace(tzinfo=UTC).timestamp()]
        return dentro[:count]

    def copy_ticks_range(
        self, symbol: str, start: datetime, end: datetime, kind: int
    ) -> list[dict[str, Any]]:
        """Todos os ticks de `[start, end]`, em ordem cronologica."""
        self.calls.append(f"copy_ticks_range({symbol}, {kind})")
        stream = self._quote_ticks if kind == self.COPY_TICKS_INFO else self._trade_ticks
        inicio = start.replace(tzinfo=UTC).timestamp()
        fim = end.replace(tzinfo=UTC).timestamp()
        return [t for t in stream if inicio <= t["time"] <= fim]

    def copy_rates_from_pos(
        self, symbol: str, timeframe: int, start: int, count: int
    ) -> list[dict[str, Any]]:
        self.calls.append(f"copy_rates_from_pos({symbol}, {timeframe})")
        return list(self._rates)[:count]
