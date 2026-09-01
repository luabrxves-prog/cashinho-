"""Verificacoes de qualidade de dados.

Cada check e uma funcao pura que recebe a serie e devolve os problemas
encontrados. Nenhum check decide o status final — essa derivacao pertence
a `DataQualityReport.from_issues`, para que a regra de bloqueio exista em
um lugar so.

Nota sobre OHLC invalido, volume negativo e timezone: esses tres casos ja
sao rejeitados na construcao de `Candle` e `CandleSeries`, entao um dado
corrompido nunca chega ate aqui em memoria. Os checks existem mesmo assim
porque a validacao de fronteira acontece na ENTRADA do provider, onde o
dado cru ainda e texto ou linha de CSV. Ver `validate_raw_rows`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from cashinho.domain.enums import Severity, Timeframe
from cashinho.domain.market import CandleSeries
from cashinho.domain.quality import DataQualityIssue

MAX_STALENESS_MULTIPLIER = 3
"""Quantos periodos de atraso toleramos antes de considerar o dado velho."""

MAX_PRICE_JUMP_PCT = Decimal("20")
"""Variacao entre candles consecutivos acima da qual suspeitamos de
desdobramento, grupamento ou erro da fonte, e nao de movimento real."""


def check_empty(series: CandleSeries) -> list[DataQualityIssue]:
    """Serie vazia. Bloqueia: nao ha o que analisar."""
    if series.is_empty:
        return [
            DataQualityIssue(
                code="EMPTY",
                severity=Severity.CRITICAL,
                message="nenhum candle retornado para o periodo solicitado",
                evidence=f"{series.symbol} {series.timeframe} via {series.source}",
            )
        ]
    return []


def check_insufficient(series: CandleSeries, minimum: int) -> list[DataQualityIssue]:
    """Amostra pequena demais para os indicadores previstos."""
    if series.is_empty or len(series) >= minimum:
        return []
    return [
        DataQualityIssue(
            code="INSUFFICIENT",
            severity=Severity.CRITICAL,
            message=f"amostra insuficiente: {len(series)} candles, minimo {minimum}",
            evidence=f"{series.symbol} {series.timeframe}",
        )
    ]


def check_timezone(series: CandleSeries) -> list[DataQualityIssue]:
    """Todos os timestamps devem ser aware.

    Redundante em memoria — `UtcDatetime` ja rejeita naive — e mantido
    como rede de seguranca para dados vindos de fontes futuras.
    """
    naive = [
        c.open_time
        for c in series.candles
        if c.open_time.tzinfo is None or c.open_time.utcoffset() is None
    ]
    if not naive:
        return []
    return [
        DataQualityIssue(
            code="NAIVE_TIMESTAMP",
            severity=Severity.CRITICAL,
            message=f"{len(naive)} timestamps sem fuso horario",
            evidence=str(naive[0]),
        )
    ]


def check_duplicates(series: CandleSeries) -> list[DataQualityIssue]:
    """Timestamps repetidos."""
    seen: set[datetime] = set()
    duplicated: list[datetime] = []
    for candle in series.candles:
        if candle.open_time in seen:
            duplicated.append(candle.open_time)
        seen.add(candle.open_time)
    if not duplicated:
        return []
    return [
        DataQualityIssue(
            code="DUPLICATE",
            severity=Severity.CRITICAL,
            message=f"{len(duplicated)} timestamps duplicados",
            evidence=", ".join(d.isoformat() for d in duplicated[:3]),
        )
    ]


def check_chronological_order(series: CandleSeries) -> list[DataQualityIssue]:
    """Ordem cronologica estritamente crescente."""
    offenders: list[str] = []
    previous: datetime | None = None
    for candle in series.candles:
        if previous is not None and candle.open_time <= previous:
            offenders.append(candle.open_time.isoformat())
        previous = candle.open_time
    if not offenders:
        return []
    return [
        DataQualityIssue(
            code="OUT_OF_ORDER",
            severity=Severity.CRITICAL,
            message=f"{len(offenders)} candles fora de ordem cronologica",
            evidence=", ".join(offenders[:3]),
        )
    ]


def check_ohlc(series: CandleSeries) -> list[DataQualityIssue]:
    """Coerencia entre abertura, maxima, minima e fechamento."""
    offenders: list[str] = []
    for candle in series.candles:
        if (
            candle.high < max(candle.open, candle.close)
            or candle.low > min(candle.open, candle.close)
            or candle.high < candle.low
        ):
            offenders.append(candle.open_time.isoformat())
    if not offenders:
        return []
    return [
        DataQualityIssue(
            code="INVALID_OHLC",
            severity=Severity.CRITICAL,
            message=f"{len(offenders)} candles com OHLC incoerente",
            evidence=", ".join(offenders[:3]),
        )
    ]


def check_volume(series: CandleSeries) -> list[DataQualityIssue]:
    """Volume negativo bloqueia; volume zero e suspeito, nao impossivel."""
    issues: list[DataQualityIssue] = []
    negative = [c.open_time.isoformat() for c in series.candles if c.volume < 0]
    if negative:
        issues.append(
            DataQualityIssue(
                code="NEGATIVE_VOLUME",
                severity=Severity.CRITICAL,
                message=f"{len(negative)} candles com volume negativo",
                evidence=", ".join(negative[:3]),
            )
        )
    zero = [c.open_time.isoformat() for c in series.candles if c.volume == 0]
    if zero:
        issues.append(
            DataQualityIssue(
                code="ZERO_VOLUME",
                severity=Severity.WARNING,
                message=(
                    f"{len(zero)} candles sem negocios; pode indicar baixa liquidez "
                    "ou preenchimento artificial da fonte"
                ),
                evidence=", ".join(zero[:3]),
            )
        )
    return issues


def check_gaps(
    series: CandleSeries,
    *,
    session_bounds: Sequence[tuple[datetime, datetime]] | None = None,
) -> list[DataQualityIssue]:
    """Candles ausentes dentro da sequencia esperada.

    Intervalos entre pregoes NAO sao lacunas. Sem os limites de sessao,
    reportamos apenas as lacunas internas a um mesmo dia — mais estreito,
    porem sem falso positivo diario, que treinaria o operador a ignorar
    o alerta.
    """
    if len(series) < 2 or series.timeframe is Timeframe.D1:
        return []

    step = series.timeframe.duration
    missing: list[str] = []
    for previous, current in zip(series.candles, series.candles[1:], strict=False):
        delta = current.open_time - previous.open_time
        if delta <= step:
            continue
        if _crosses_session_boundary(previous.open_time, current.open_time, session_bounds):
            continue
        faltantes = int(delta / step) - 1
        missing.append(f"{previous.open_time.isoformat()} (+{faltantes})")

    if not missing:
        return []
    return [
        DataQualityIssue(
            code="GAP",
            severity=Severity.WARNING,
            message=f"{len(missing)} lacunas na sequencia de candles",
            evidence=", ".join(missing[:3]),
        )
    ]


def _crosses_session_boundary(
    previous: datetime,
    current: datetime,
    session_bounds: Sequence[tuple[datetime, datetime]] | None,
) -> bool:
    if session_bounds is None:
        return previous.date() != current.date()
    return any(previous < close <= current for _, close in session_bounds)


def check_staleness(
    series: CandleSeries, *, now: datetime, multiplier: int = MAX_STALENESS_MULTIPLIER
) -> list[DataQualityIssue]:
    """Ultimo candle velho demais para o timeframe.

    Aplicado apenas quando o modo exige dado ao vivo; o chamador decide.
    """
    last = series.closed_only().last
    if last is None:
        return []
    tolerance = series.timeframe.duration * multiplier
    age = now - last.close_time
    if age <= tolerance:
        return []
    return [
        DataQualityIssue(
            code="STALE",
            severity=Severity.CRITICAL,
            message=(
                f"ultimo candle fechou ha {age.total_seconds() / 60:.0f} min, "
                f"acima da tolerancia de {tolerance.total_seconds() / 60:.0f} min"
            ),
            evidence=last.close_time.isoformat(),
        )
    ]


def check_price_jumps(series: CandleSeries) -> list[DataQualityIssue]:
    """Saltos de preco compativeis com desdobramento ou erro da fonte."""
    offenders: list[str] = []
    for previous, current in zip(series.candles, series.candles[1:], strict=False):
        if previous.close <= 0:
            continue
        variation = abs(current.close - previous.close) / previous.close * Decimal("100")
        if variation > MAX_PRICE_JUMP_PCT:
            offenders.append(f"{current.open_time.isoformat()} ({variation:.1f}%)")
    if not offenders:
        return []
    return [
        DataQualityIssue(
            code="PRICE_JUMP",
            severity=Severity.WARNING,
            message=(
                f"{len(offenders)} saltos acima de {MAX_PRICE_JUMP_PCT}%; "
                "verificar desdobramento, grupamento ou erro da fonte"
            ),
            evidence=", ".join(offenders[:3]),
        )
    ]


def check_future_closed_candles(
    series: CandleSeries, *, now: datetime
) -> list[DataQualityIssue]:
    """Candle fechado no futuro e look-ahead: bloqueia a decisao."""
    offenders = [
        candle.close_time.isoformat()
        for candle in series.candles
        if candle.is_closed and candle.close_time > now
    ]
    if not offenders:
        return []
    return [
        DataQualityIssue(
            code="FUTURE_CANDLE",
            severity=Severity.CRITICAL,
            message=f"{len(offenders)} candles fechados no futuro do relogio",
            evidence=", ".join(offenders[:3]),
        )
    ]


def check_open_candle_state(
    series: CandleSeries, *, now: datetime
) -> list[DataQualityIssue]:
    """Candle aberto depois do fechamento esperado indica fuso/janela errados."""
    offenders = [
        candle.open_time.isoformat()
        for candle in series.candles
        if not candle.is_closed and candle.close_time <= now
    ]
    if not offenders:
        return []
    return [
        DataQualityIssue(
            code="STALE_OPEN_CANDLE",
            severity=Severity.CRITICAL,
            message=(
                f"{len(offenders)} candles continuam abertos depois do fim "
                "esperado do periodo"
            ),
            evidence=", ".join(offenders[:3]),
        )
    ]


class RawRowError(ValueError):
    """Linha crua invalida na fronteira de entrada do provider."""


def validate_raw_rows(rows: Sequence[dict[str, Any]], *, origin: str) -> None:
    """Valida linhas cruas antes de virarem `Candle`.

    Esta e a fronteira real: aqui o dado ainda e texto e pode conter
    numero mal formado, campo ausente ou volume negativo. Depois desta
    funcao, o dominio garante o resto.
    """
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    for index, row in enumerate(rows, start=1):
        missing = required - row.keys()
        if missing:
            raise RawRowError(
                f"{origin}: linha {index} sem os campos {sorted(missing)}"
            )
        try:
            values = {k: Decimal(str(row[k])) for k in ("open", "high", "low", "close")}
            volume = int(str(row["volume"]))
        except (InvalidOperation, ValueError) as exc:
            raise RawRowError(f"{origin}: linha {index} com numero invalido: {exc}") from exc
        if volume < 0:
            raise RawRowError(f"{origin}: linha {index} com volume negativo ({volume})")
        if values["high"] < max(values["open"], values["close"]) or values["low"] > min(
            values["open"], values["close"]
        ):
            raise RawRowError(
                f"{origin}: linha {index} com OHLC incoerente "
                f"(O={values['open']} H={values['high']} "
                f"L={values['low']} C={values['close']})"
            )


def expected_candle_count(start: datetime, end: datetime, timeframe: Timeframe) -> int:
    """Quantidade nominal de candles no intervalo, ignorando sessoes."""
    span: timedelta = end - start
    if span <= timedelta(0):
        return 0
    return int(span / timeframe.duration)
