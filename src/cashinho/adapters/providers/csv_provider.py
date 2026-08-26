"""Provider de dados historicos a partir de arquivos CSV locais.

Escolha deliberada para a fase de desenvolvimento: uma fonte local e
deterministica: o mesmo pedido devolve sempre a mesma serie, sem rede,
sem limite de requisicoes e sem ajuste retroativo de proventos alterando
o historico entre duas execucoes.

Layout esperado:

    <raiz>/<SYMBOL>/<timeframe>.csv

Cabecalho obrigatorio:

    timestamp,open,high,low,close,volume

`timestamp` em ISO-8601 com fuso (ex.: 2026-08-20T13:00:00+00:00) e
refere-se a ABERTURA do candle.

AVISO SOBRE PROCEDENCIA
-----------------------
Este provider nao valida se o conteudo do CSV corresponde a precos reais
negociados. Ele declara `source` como `csv:<nome do arquivo>` justamente
para que a origem apareca na interface e no diario. Series geradas por
`scripts/generate_fixtures.py` sao SINTETICAS e assim se identificam.
"""

from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from cashinho.core.data_quality.checks import RawRowError, validate_raw_rows
from cashinho.domain.enums import Timeframe
from cashinho.domain.errors import CashinhoError
from cashinho.domain.market import Candle, CandleSeries, Quote
from cashinho.domain.types import ensure_utc
from cashinho.observability.logging import get_logger
from cashinho.ports.clock import Clock
from cashinho.ports.market_data import ProviderCapabilities

logger = get_logger(__name__)

REQUIRED_HEADER = ("timestamp", "open", "high", "low", "close", "volume")


class ProviderError(CashinhoError):
    """Falha ao obter dados do provider."""


class SymbolNotAvailableError(ProviderError):
    """Ativo ou timeframe sem dados neste provider."""


class CsvHistoricalProvider:
    """Le candles historicos de arquivos CSV em disco."""

    def __init__(self, root: Path, clock: Clock, *, name: str = "csv") -> None:
        self._root = Path(root)
        self._clock = clock
        self._name = name

    @property
    def root(self) -> Path:
        return self._root

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Declaracao conservadora.

        `supports_realtime=False` e o ponto central: por D9, este provider
        nao habilita PAPER, ASSISTED nem LIVE. Arquivo em disco nao e
        cotacao ao vivo, e tratar como se fosse seria exatamente o erro
        que a checagem de capacidade existe para impedir.
        """
        return ProviderCapabilities(
            name=self._name,
            supports_realtime=False,
            typical_delay_seconds=0,
            min_timeframe=Timeframe.M1,
            intraday_history_days=0,
            supports_quotes=False,
            notes=(
                "Arquivos CSV locais. Deterministico e sem rede. "
                "Adequado a RESEARCH, BACKTEST e REPLAY."
            ),
        )

    def list_symbols(self) -> tuple[str, ...]:
        """Ativos com dados disponiveis."""
        if not self._root.is_dir():
            return ()
        return tuple(sorted(p.name for p in self._root.iterdir() if p.is_dir()))

    def get_available_timeframes(self, symbol: str) -> tuple[Timeframe, ...]:
        """Timeframes disponiveis para o ativo."""
        directory = self._root / symbol.upper()
        if not directory.is_dir():
            return ()
        available = []
        for timeframe in Timeframe:
            if (directory / f"{timeframe.value}.csv").is_file():
                available.append(timeframe)
        return tuple(available)

    def available_range(self, symbol: str, timeframe: Timeframe) -> tuple[datetime, datetime] | None:
        """Primeiro e ultimo instante disponiveis no arquivo local."""
        path = self._path_for(symbol.upper(), timeframe)
        rows = self._read_rows(path)
        if not rows:
            return None
        candles = [
            self._to_candle(row, timeframe, path.name)
            for row in (rows[0], rows[-1])
        ]
        return candles[0].open_time, candles[-1].close_time

    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        *,
        start: datetime,
        end: datetime,
    ) -> CandleSeries:
        """Candles com `start <= open_time < end` e fechamento ja conhecido.

        Uma serie vazia e retorno valido, nao excecao: cabe ao portao de
        qualidade classificar o vazio e bloquear a analise. Excecao aqui
        seria confundir "sem dado no periodo" com "fonte indisponivel".
        """
        symbol = symbol.upper()
        start_utc = ensure_utc(start)
        end_utc = ensure_utc(end)
        if end_utc <= start_utc:
            raise ValueError(
                f"intervalo invalido: end ({end_utc.isoformat()}) deve ser "
                f"posterior a start ({start_utc.isoformat()})"
            )

        path = self._path_for(symbol, timeframe)
        rows = self._read_rows(path)
        try:
            validate_raw_rows(rows, origin=path.name)
        except RawRowError as exc:
            raise ProviderError(str(exc)) from exc

        logical_now = self._clock.now()
        candles = tuple(
            candle
            for candle in (self._to_candle(row, timeframe, path.name) for row in rows)
            if start_utc <= candle.open_time < end_utc and candle.close_time <= logical_now
        )

        logger.info(
            "candles carregados",
            extra={
                "symbol": symbol,
                "timeframe": timeframe.value,
                "candles": len(candles),
                "source": f"csv:{path.name}",
            },
        )
        return CandleSeries(
            symbol=symbol,
            timeframe=timeframe,
            candles=candles,
            source=f"csv:{symbol}/{path.name}",
            fetched_at=self._clock.now(),
        )

    def get_quote(self, symbol: str) -> Quote:
        """Nao suportado.

        Devolver o ultimo fechamento historico como se fosse cotacao
        atual violaria a regra de nunca apresentar preco antigo como
        atual. Preferimos falhar.
        """
        raise SymbolNotAvailableError(
            f"{self._name} nao fornece cotacao ao vivo para {symbol.upper()}: "
            "e uma fonte historica. Usar o ultimo fechamento como cotacao "
            "atual apresentaria preco antigo como se fosse atual."
        )

    def _path_for(self, symbol: str, timeframe: Timeframe) -> Path:
        path = self._root / symbol / f"{timeframe.value}.csv"
        if not path.is_file():
            disponiveis = self.get_available_timeframes(symbol)
            if not disponiveis:
                raise SymbolNotAvailableError(
                    f"sem dados para {symbol} em {self._root}. "
                    f"Ativos disponiveis: {', '.join(self.list_symbols()) or 'nenhum'}"
                )
            raise SymbolNotAvailableError(
                f"{symbol} nao tem dados em {timeframe}. "
                f"Timeframes disponiveis: {', '.join(t.value for t in disponiveis)}"
            )
        return path

    @staticmethod
    def _read_rows(path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            header = tuple(reader.fieldnames or ())
            missing = set(REQUIRED_HEADER) - set(header)
            if missing:
                raise ProviderError(
                    f"{path.name}: cabecalho sem as colunas {sorted(missing)}; "
                    f"esperado {list(REQUIRED_HEADER)}"
                )
            return list(reader)

    @staticmethod
    def _to_candle(row: dict[str, str], timeframe: Timeframe, origin: str) -> Candle:
        raw = row["timestamp"]
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ProviderError(
                f"{origin}: timestamp mal formado {raw!r} — esperado ISO-8601"
            ) from exc
        # Dois erros distintos, duas mensagens distintas: "2026-08-20" mal
        # escrito e "2026-08-20T13:00:00" sem fuso exigem correcoes
        # diferentes no arquivo de origem.
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ProviderError(
                f"{origin}: timestamp {raw!r} sem fuso horario (naive). "
                "Informe o offset, ex.: 2026-08-20T13:00:00+00:00"
            )
        open_time = ensure_utc(parsed)
        return Candle(
            open_time=open_time,
            close_time=open_time + timeframe.duration,
            open=Decimal(row["open"]),
            high=Decimal(row["high"]),
            low=Decimal(row["low"]),
            close=Decimal(row["close"]),
            volume=int(row["volume"]),
            is_closed=True,
        )
