"""Gera series SINTETICAS e deterministicas para desenvolvimento.

    python scripts/generate_fixtures.py

AVISO EXPLICITO
---------------
Os dados gerados NAO sao precos reais da B3. Sao um passeio aleatorio com
semente fixa, produzido para exercitar o pipeline sem depender de rede.

Consequencia que precisa ficar clara: qualquer backtest sobre estes
arquivos mede se o CODIGO funciona, nunca se uma estrategia funciona.
Resultado obtido sobre serie sintetica nao diz absolutamente nada sobre
comportamento de mercado.

Os tickers usados sao reais apenas como rotulo, para que a interface
exercite a validacao de formato da B3.
"""

from __future__ import annotations

import csv
import random
import sys
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cashinho.core.time.b3_calendar import B3Calendar  # noqa: E402
from cashinho.domain.enums import Timeframe  # noqa: E402

SEED = 20260820
ANCHOR_DATE = date(2026, 8, 26)
"""Ultimo pregao gerado.

Data FIXA, e nao "ontem": ancorar no relogio faria o mesmo comando
produzir arquivos diferentes a cada dia, e a reprodutibilidade das
fixtures e justamente o motivo de existirem.
"""

OUTPUT = ROOT / "data" / "fixtures"

SYMBOLS: dict[str, Decimal] = {
    "PETR4": Decimal("38.50"),
    "VALE3": Decimal("61.20"),
    "ITUB4": Decimal("34.80"),
}

TIMEFRAMES = (Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.D1)
SESSION_DAYS = 20
VOLATILITY = Decimal("0.0012")
"""Desvio por periodo de 1m. Escalado pela raiz do numero de periodos."""


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _trading_days(calendar: B3Calendar, count: int, last: date) -> list[date]:
    days: list[date] = []
    cursor = last
    while len(days) < count:
        if calendar.is_trading_day(cursor):
            days.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(days)


def _generate(
    rng: random.Random,
    *,
    start_price: Decimal,
    slots: list[datetime],
    scale: Decimal,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    price = start_price
    for slot in slots:
        drift = Decimal(str(rng.gauss(0, float(VOLATILITY * scale))))
        close = _quantize(price * (Decimal("1") + drift))
        if close <= Decimal("0.05"):
            close = Decimal("0.05")
        high = _quantize(max(price, close) * (Decimal("1") + abs(drift) / 2))
        low = _quantize(min(price, close) * (Decimal("1") - abs(drift) / 2))
        rows.append(
            {
                "timestamp": slot.isoformat(),
                "open": price,
                "high": max(high, price, close),
                "low": min(low, price, close),
                "close": close,
                "volume": rng.randint(20_000, 400_000),
            }
        )
        price = close
    return rows


def _intraday_slots(
    calendar: B3Calendar, days: list[date], timeframe: Timeframe
) -> list[datetime]:
    slots: list[datetime] = []
    for day in days:
        bounds = calendar.session_bounds(day)
        if bounds is None:
            continue
        cursor, close = bounds
        while cursor < close:
            slots.append(cursor)
            cursor += timeframe.duration
    return slots


def _daily_slots(calendar: B3Calendar, days: list[date]) -> list[datetime]:
    slots = []
    for day in days:
        bounds = calendar.session_bounds(day)
        if bounds is not None:
            slots.append(bounds[0])
    return slots


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"]
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    calendar = B3Calendar()
    days = _trading_days(calendar, SESSION_DAYS, ANCHOR_DATE)

    for symbol, start_price in SYMBOLS.items():
        for timeframe in TIMEFRAMES:
            # Semente derivada do par ativo/timeframe: reproduzivel entre
            # execucoes e independente da ordem de geracao.
            rng = random.Random(f"{SEED}-{symbol}-{timeframe.value}")
            if timeframe is Timeframe.D1:
                slots = _daily_slots(calendar, days)
                scale = Decimal("20")
            else:
                intraday_days = days[-5:] if timeframe is Timeframe.M1 else days
                slots = _intraday_slots(calendar, intraday_days, timeframe)
                periods = int(timeframe.duration.total_seconds() / 60)
                scale = Decimal(str(periods)).sqrt()

            rows = _generate(rng, start_price=start_price, slots=slots, scale=scale)
            path = OUTPUT / symbol / f"{timeframe.value}.csv"
            _write(path, rows)
            print(f"{path.relative_to(ROOT)}: {len(rows)} candles")

    marker = OUTPUT / "AVISO.txt"
    marker.write_text(
        "Dados SINTETICOS gerados por scripts/generate_fixtures.py.\n"
        "NAO sao precos reais da B3.\n"
        "Servem apenas para exercitar o pipeline durante o desenvolvimento.\n"
        "Backtest sobre estes arquivos mede o codigo, nunca a estrategia.\n",
        encoding="utf-8",
    )
    print(f"\n{len(SYMBOLS)} ativos gerados em {OUTPUT.relative_to(ROOT)}")
    print("ATENCAO: dados sinteticos, nao reais.")


if __name__ == "__main__":
    main()
