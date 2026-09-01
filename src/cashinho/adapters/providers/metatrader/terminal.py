"""Fronteira com a biblioteca `MetaTrader5`.

Este e o **unico** modulo do Cashinho que importa `MetaTrader5`. Tudo o que e
especifico do terminal - constantes de timeframe, tipos de tick, formato dos
retornos - para aqui. Ha teste de arquitetura garantindo que o dominio nunca
ve essa dependencia.

A biblioteca so existe no Windows. O import acontece **dentro** dos metodos,
e a ausencia dela vira estado descrito, nunca `ImportError` no meio de um
backtest em Linux ou na CI.

Somente leitura: nao ha aqui nenhuma chamada capaz de enviar ordem.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cashinho.domain.enums import Timeframe
from cashinho.domain.errors import CashinhoError

TICKS_INFO = "COPY_TICKS_INFO"
"""Ticks de COTACAO: bid e ask."""

TICKS_TRADE = "COPY_TICKS_TRADE"
"""Ticks de NEGOCIO: last e volume."""

TIMEFRAME_CONSTANTS: dict[Timeframe, str] = {
    Timeframe.M1: "TIMEFRAME_M1",
    Timeframe.M2: "TIMEFRAME_M2",
    Timeframe.M5: "TIMEFRAME_M5",
    Timeframe.M10: "TIMEFRAME_M10",
    Timeframe.M15: "TIMEFRAME_M15",
    Timeframe.M30: "TIMEFRAME_M30",
    Timeframe.H1: "TIMEFRAME_H1",
    Timeframe.D1: "TIMEFRAME_D1",
}


class MetaTraderUnavailableError(CashinhoError):
    """A biblioteca MetaTrader5 nao esta instalada ou nao roda neste sistema."""


class MetaTraderError(CashinhoError):
    """Falha do terminal, com o codigo e a mensagem que ele devolveu."""


@dataclass(frozen=True)
class TerminalInfo:
    """O que se pode dizer do terminal **sem expor dado da conta**.

    Nao ha login, saldo nem patrimonio aqui, e nao deve haver: este objeto
    alimenta a pagina System Health.
    """

    connected: bool
    company: str = ""
    server: str = ""
    version: str = ""
    account_mode: str = "DESCONHECIDO"
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "company": self.company,
            "server": self.server,
            "version": self.version,
            "account_mode": self.account_mode,
            "reason": self.reason,
        }


class MetaTraderTerminal:
    """Adaptador fino sobre a biblioteca MetaTrader5.

    Cada metodo devolve estrutura simples (dict, tupla), nunca objeto da
    biblioteca: e o que permite substituir o terminal por um dublê nos testes
    sem nenhum ramo condicional no codigo de producao.
    """

    def __init__(self, terminal_path: str = "", library: Any | None = None) -> None:
        self._terminal_path = terminal_path
        self._library = library
        self._started = False

    # ------------------------------------------------------------------
    @property
    def library(self) -> Any:
        """A biblioteca, ou o erro que explica a ausencia dela."""
        if self._library is not None:
            return self._library
        try:
            import MetaTrader5  # type: ignore[import-untyped]
        except ImportError as exc:
            raise MetaTraderUnavailableError(
                "METATRADER NAO DISPONIVEL: a biblioteca MetaTrader5 nao esta "
                "instalada (ela so existe no Windows). Na maquina do terminal: "
                "pip install 'cashinho[metatrader]'"
            ) from exc
        self._library = MetaTrader5
        return MetaTrader5

    @property
    def available(self) -> bool:
        try:
            _ = self.library
        except MetaTraderUnavailableError:
            return False
        return True

    # ------------------------------------------------------------------
    def connect(self) -> TerminalInfo:
        """Liga no terminal **ja aberto e autenticado**.

        Nao recebe login nem senha de proposito: o Cashinho nao guarda
        credencial da corretora (regra 7). Quem autentica e o operador, no
        proprio terminal.
        """
        try:
            library = self.library
        except MetaTraderUnavailableError as exc:
            return TerminalInfo(False, reason=str(exc))

        started = (
            library.initialize(self._terminal_path)
            if self._terminal_path
            else library.initialize()
        )
        if not started:
            return TerminalInfo(False, reason=self._last_error())

        self._started = True
        return self._describe()

    def _describe(self) -> TerminalInfo:
        library = self.library
        info = library.terminal_info()
        if info is None:
            return TerminalInfo(False, reason="terminal_info() nao respondeu")

        account = library.account_info()
        server = str(getattr(account, "server", "") or "") if account else ""
        account_mode = _account_mode_label(library, getattr(account, "trade_mode", None))
        return TerminalInfo(
            connected=bool(getattr(info, "connected", False)),
            company=str(getattr(info, "company", "") or ""),
            server=server,
            version=str(getattr(library, "__version__", "") or ""),
            account_mode=account_mode,
        )

    def shutdown(self) -> None:
        if self._started and self._library is not None:
            # encerrar o terminal nunca pode derrubar quem chamou
            with contextlib.suppress(Exception):
                self._library.shutdown()
            self._started = False

    # ------------------------------------------------------------------
    def symbols(self) -> tuple[str, ...]:
        found = self.library.symbols_get()
        if not found:
            return ()
        return tuple(str(getattr(s, "name", "")) for s in found if getattr(s, "name", ""))

    def select(self, symbol: str) -> bool:
        """Poe o ativo na Observacao do Mercado - sem isso nao chega tick."""
        return bool(self.library.symbol_select(symbol, True))

    def ticks_range(
        self, symbol: str, start: datetime, end: datetime, kind: str
    ) -> tuple[dict[str, Any], ...]:
        """Ticks do intervalo `[start, end]`, em horario do servidor.

        Usa `copy_ticks_range`, e nao `copy_ticks_from`, por um motivo
        verificado no terminal: `copy_ticks_from(symbol, since, N, ...)`
        devolve os **primeiros** N ticks a partir de `since`. Com mercado
        movimentado, N enche com eventos do inicio da janela e os mais
        recentes ficam de fora - o adapter entregaria preco velho como atual,
        que e exatamente o que a regra 5 proibe.

        Com intervalo explicito ate `end`, o ultimo elemento e o evento mais
        recente de verdade.
        """
        library = self.library
        constant = getattr(library, kind, None)
        if constant is None:
            raise MetaTraderError(f"a biblioteca MetaTrader5 nao expoe {kind}")

        raw = library.copy_ticks_range(symbol, start, end, constant)
        if raw is None:
            raise MetaTraderError(
                f"copy_ticks_range({symbol}, {kind}) falhou: {self._last_error()}"
            )
        return tuple(_as_dict(tick) for tick in raw)

    def rates(
        self, symbol: str, timeframe: Timeframe, count: int
    ) -> tuple[dict[str, Any], ...]:
        """Candles a partir da posicao 0 - inclusive o que esta em formacao."""
        library = self.library
        name = TIMEFRAME_CONSTANTS.get(timeframe)
        if name is None:
            raise MetaTraderError(f"timeframe sem correspondencia no MT5: {timeframe}")
        constant = getattr(library, name, None)
        if constant is None:
            raise MetaTraderError(f"a biblioteca MetaTrader5 nao expoe {name}")

        raw = library.copy_rates_from_pos(symbol, constant, 0, count)
        if raw is None:
            raise MetaTraderError(
                f"copy_rates_from_pos({symbol}, {timeframe}) falhou: {self._last_error()}"
            )
        return tuple(_as_dict(rate) for rate in raw)

    # ------------------------------------------------------------------
    def _last_error(self) -> str:
        try:
            code, message = self.library.last_error()
        except Exception:
            return "erro desconhecido do MT5"
        return f"MT5 [{code}] {message}"


def _account_mode_label(library: Any, value: object) -> str:
    if value is None:
        return "DESCONHECIDO"
    demo = getattr(library, "ACCOUNT_TRADE_MODE_DEMO", 0)
    contest = getattr(library, "ACCOUNT_TRADE_MODE_CONTEST", 1)
    real = getattr(library, "ACCOUNT_TRADE_MODE_REAL", 2)
    if value == demo:
        return "DEMO"
    if value == real:
        return "REAL"
    if value == contest:
        return "CONTEST"
    return "DESCONHECIDO"


def _as_dict(record: Any) -> dict[str, Any]:
    """Converte a linha numpy/namedtuple do MT5 em dicionario simples."""
    if isinstance(record, dict):
        return dict(record)
    dtype = getattr(record, "dtype", None)
    names = getattr(dtype, "names", None) if dtype is not None else None
    if names:
        return {
            name: (record[name].item() if hasattr(record[name], "item") else record[name])
            for name in names
        }
    if hasattr(record, "_asdict"):
        return dict(record._asdict())
    return {k: getattr(record, k) for k in dir(record) if not k.startswith("_")}
