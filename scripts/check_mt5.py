#!/usr/bin/env python3
"""Diagnostico do MetaTrader 5 - independente do Streamlit.

    python scripts/check_mt5.py
    python scripts/check_mt5.py --symbol PETR4 --timeframe 5m

Roda os passos na ordem em que costumam falhar e para no primeiro problema,
com a instrucao do que fazer. Somente leitura: este script nao envia ordem.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:  # permite rodar sem instalar
    sys.path.insert(0, str(ROOT / "src"))

from cashinho.adapters.providers.metatrader import (  # noqa: E402
    AmbiguousSymbolError,
    MetaTraderMarketDataProvider,
    SymbolNotFoundError,
)
from cashinho.config.settings import get_settings  # noqa: E402
from cashinho.core.time.clocks import SystemClock  # noqa: E402
from cashinho.domain.enums import FeedStatus, Timeframe  # noqa: E402
from cashinho.domain.errors import CashinhoError  # noqa: E402

OK = "  [ok]   "
FAIL = "  [FALHA]"
WARN = "  [aviso]"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnostico do MetaTrader 5")
    parser.add_argument("--symbol", default="PETR4")
    parser.add_argument("--timeframe", default="1m", choices=[t.value for t in Timeframe])
    args = parser.parse_args(argv)

    settings = get_settings()
    clock = SystemClock()
    provider = MetaTraderMarketDataProvider(
        clock,
        terminal_path=settings.mt5_terminal_path,
        server_timezone=settings.mt5_server_timezone,
        stale_seconds=settings.mt5_stale_seconds,
    )

    print("\nDIAGNOSTICO METATRADER 5")
    print("=" * 64)

    if not provider.available:
        print(f"{FAIL} biblioteca MetaTrader5 nao encontrada")
        print("         na maquina do terminal: pip install 'cashinho[metatrader]'")
        print("         (a biblioteca so existe no Windows)")
        return 2
    print(f"{OK} biblioteca MetaTrader5 encontrada")

    info = provider.connect()
    if not info.connected:
        print(f"{FAIL} terminal nao conectado")
        print(f"         {info.reason}")
        print("         abra o MetaTrader da corretora e autentique manualmente")
        return 2
    print(f"{OK} terminal conectado    {info.company}")
    print(f"{OK} servidor              {info.server}")
    print(f"{OK} modo da conta         {info.account_mode}")

    try:
        resolution = provider.resolve(args.symbol)
    except AmbiguousSymbolError as exc:
        print(f"{FAIL} {exc}")
        return 2
    except SymbolNotFoundError as exc:
        print(f"{FAIL} {exc}")
        print("         abra a Observacao do Mercado (Ctrl+M), depois Ctrl+U,")
        print("         e adicione o ativo")
        return 2
    marca = "exato" if resolution.exact else "APROXIMADO"
    print(f"{OK} simbolo resolvido     {resolution.resolved} ({marca})")

    try:
        quote = provider.get_quote(args.symbol)
    except CashinhoError as exc:
        print(f"{FAIL} cotacao: {exc}")
        return 2

    status = provider.feed_status(args.symbol)
    print(f"{OK} estado do feed        {status.value}")
    if quote.has_active_book:
        print(f"{OK} bid / ask             {quote.bid} / {quote.ask}  "
              f"(spread {quote.spread})")
    else:
        print(f"{WARN} bid / ask             SEM LIVRO ATIVO (zerados no terminal)")
    print(f"{OK} ultimo negocio        {quote.price}  volume {quote.trade_volume}")
    print(f"{OK} cotacao em            {_local(quote.bid_ask_time, settings)}")
    print(f"{OK} negocio em            {_local(quote.trade_time, settings)}")
    print(f"{OK} latencia              {quote.latency_ms} ms")

    timeframe = Timeframe(args.timeframe)
    now = clock.now()
    try:
        series = provider.get_candles(
            args.symbol, timeframe, start=now - timedelta(days=2), end=now
        )
        fechados = series.closed_only()
        ultimo = fechados.last
        print(f"{OK} candles {timeframe.value:<13} {len(fechados)} fechado(s)"
              + (f", ultimo {_local(ultimo.open_time, settings)} "
                 f"fecha {_local(ultimo.close_time, settings)} "
                 f"close {ultimo.close}" if ultimo else ""))
        if series.has_open_candle:
            print(f"{OK} candle em formacao    marcado como aberto, nao entregue "
                  "a indicadores")
    except CashinhoError as exc:
        print(f"{WARN} candles {timeframe.value}: {exc}")

    print(f"{OK} envio de ordem        NAO IMPLEMENTADO (fonte somente leitura)")
    print("=" * 64)
    print(f"  {resolution.resolved} {status.value} - MetaTrader 5\n")
    return 0 if status in (FeedStatus.ONLINE, FeedStatus.NO_ACTIVE_BOOK,
                           FeedStatus.MARKET_CLOSED) else 1


def _local(moment: object, settings: object) -> str:
    """Horario na apresentacao: UTC internamente, local so aqui."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    if not isinstance(moment, datetime):
        return "-"
    tz = ZoneInfo(getattr(settings, "display_timezone", "America/Sao_Paulo"))
    return moment.astimezone(tz).strftime("%d/%m %H:%M:%S.%f")[:-3]


if __name__ == "__main__":
    raise SystemExit(main())
