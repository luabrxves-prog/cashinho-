"""Enumeracoes centrais do dominio.

Toda a semantica de modo, timeframe e estado de oportunidade vive aqui.
Nenhum outro modulo deve declarar strings livres para estes conceitos.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum


class Mode(StrEnum):
    """Modos de operacao do Cashinho.

    A separacao e rigida: cada modo tem exigencias distintas de dados,
    de latencia e de autorizacao. O modo padrao do sistema e PAPER.
    """

    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    REPLAY = "REPLAY"
    PAPER = "PAPER"
    ASSISTED = "ASSISTED"
    LIVE = "LIVE"

    @property
    def touches_real_money(self) -> bool:
        """Modos que podem resultar em ordem real enviada ao mercado."""
        return self in {Mode.ASSISTED, Mode.LIVE}

    @property
    def requires_realtime_data(self) -> bool:
        """Modos que exigem dado ao vivo, nao historico."""
        return self in {Mode.PAPER, Mode.ASSISTED, Mode.LIVE}


class Timeframe(StrEnum):
    """Timeframes suportados."""

    M1 = "1m"
    M2 = "2m"
    M5 = "5m"
    M10 = "10m"
    M15 = "15m"
    M30 = "30m"
    H1 = "60m"
    D1 = "1D"

    @property
    def duration(self) -> timedelta:
        """Duracao nominal de um candle deste timeframe."""
        return _TIMEFRAME_DURATION[self]

    @property
    def is_intraday(self) -> bool:
        return self is not Timeframe.D1

    @property
    def pandas_freq(self) -> str:
        """Alias de frequencia usado em resample do pandas."""
        return _TIMEFRAME_FREQ[self]


_TIMEFRAME_DURATION: dict[Timeframe, timedelta] = {
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M2: timedelta(minutes=2),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M10: timedelta(minutes=10),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.M30: timedelta(minutes=30),
    Timeframe.H1: timedelta(hours=1),
    Timeframe.D1: timedelta(days=1),
}

_TIMEFRAME_FREQ: dict[Timeframe, str] = {
    Timeframe.M1: "1min",
    Timeframe.M2: "2min",
    Timeframe.M5: "5min",
    Timeframe.M10: "10min",
    Timeframe.M15: "15min",
    Timeframe.M30: "30min",
    Timeframe.H1: "60min",
    Timeframe.D1: "1D",
}


class TimeframeRole(StrEnum):
    """Papel de um timeframe dentro do modelo multi-timeframe.

    Modelo preferencial inicial: 60m contexto, 15m tendencia,
    5m setup, 1m gatilho. A associacao concreta e configuravel.
    """

    CONTEXT = "CONTEXTO"
    TREND = "TENDENCIA"
    SETUP = "SETUP"
    TRIGGER = "GATILHO"


class Side(StrEnum):
    """Direcao da operacao."""

    LONG = "COMPRA"
    SHORT = "VENDA"


class OpportunityState(StrEnum):
    """Estados validos de uma oportunidade.

    NAO_OPERAR e uma decisao perfeitamente valida e terminal.
    """

    APROVADO = "SETUP APROVADO"
    AGUARDANDO_GATILHO = "AGUARDANDO GATILHO"
    REJEITADO = "SETUP REJEITADO"
    NAO_OPERAR = "NAO OPERAR"
    EXPIRADO = "EXPIRADO"

    @property
    def is_terminal(self) -> bool:
        return self in {
            OpportunityState.REJEITADO,
            OpportunityState.NAO_OPERAR,
            OpportunityState.EXPIRADO,
        }

    @property
    def allows_execution(self) -> bool:
        """Apenas SETUP APROVADO habilita geracao de boleta."""
        return self is OpportunityState.APROVADO


class DataStatus(StrEnum):
    """Resultado do portao de qualidade de dados.

    BLOCKED interrompe o pipeline. Nao e aviso, e parada.
    """

    OK = "OK"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"

    @property
    def allows_analysis(self) -> bool:
        return self is not DataStatus.BLOCKED


class FeedStatus(StrEnum):
    """Estado de uma fonte de dados ao vivo.

    Distinto de `DataStatus`, que e o veredito do portao de qualidade sobre
    uma serie ja carregada: aqui o assunto e a **liveness do feed**.

    A separacao entre `MARKET_CLOSED` e `STALE` veio do terminal real: as 20h
    o ultimo tick e das 17h55 e isso esta correto, enquanto o mesmo atraso as
    14h significa que a fonte parou. Tratar os dois como um estado so faria o
    sistema gritar todo fim de tarde e calar quando importasse.

    `NO_ACTIVE_BOOK` idem: o MT5 devolve `bid=0.0` e `ask=0.0` no fim do
    pregao. Isso e ausencia de livro, nao preco zero.
    """

    ONLINE = "ONLINE"
    STALE = "STALE"
    MARKET_CLOSED = "MARKET_CLOSED"
    NO_ACTIVE_BOOK = "NO_ACTIVE_BOOK"
    OFFLINE = "OFFLINE"

    @property
    def has_data(self) -> bool:
        """Chegou numero? OFFLINE e o unico que nao trouxe nada."""
        return self is not FeedStatus.OFFLINE

    @property
    def allows_live_decision(self) -> bool:
        """So ONLINE sustenta decisao ao vivo."""
        return self is FeedStatus.ONLINE

    @property
    def market_is_idle(self) -> bool:
        """O dado nao muda porque nao ha o que mudar - nao e defeito."""
        return self in (FeedStatus.MARKET_CLOSED, FeedStatus.NO_ACTIVE_BOOK)


class Severity(StrEnum):
    """Gravidade de um problema de qualidade de dados."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class FactorDirection(StrEnum):
    """Direcao da contribuicao de um fator no score."""

    FAVORAVEL = "FAVORAVEL"
    CONTRARIO = "CONTRARIO"
    NEUTRO = "NEUTRO"
