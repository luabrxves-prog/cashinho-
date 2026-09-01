"""Escolha do provider de dados de mercado a partir da configuracao.

Existe para que as paginas nao decidam qual fonte usar - elas pedem "o
provider" e recebem o que a configuracao mandou. Sem isto, cada tela repetiria
a mesma cadeia de ifs e as duas divergiriam na primeira mudanca.

**Nao ha fallback silencioso.** Se o MetaTrader estiver habilitado e o
terminal nao responder, a funcao devolve o provider mesmo assim, com o estado
descrito: quem chama mostra `REALTIME OFFLINE`. Trocar por CSV aqui
apresentaria dado historico como se fosse mercado, que e exatamente o que a
regra 5 proibe.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cashinho.adapters.providers.csv_provider import CsvHistoricalProvider
from cashinho.adapters.providers.metatrader import MetaTraderMarketDataProvider
from cashinho.config.settings import Settings
from cashinho.ports.clock import Clock
from cashinho.ports.market_data import MarketDataProvider


@dataclass(frozen=True)
class ProviderChoice:
    """O provider escolhido e por que ele foi escolhido."""

    provider: MarketDataProvider
    kind: str
    realtime: bool
    reason: str
    monitored_symbols: tuple[str, ...] = ()

    @property
    def is_metatrader(self) -> bool:
        return self.kind == "metatrader"

    def offered_symbols(self) -> tuple[str, ...]:
        """Ativos a oferecer na interface.

        O MetaTrader expoe milhares de simbolos da corretora; despejar todos
        num seletor nao ajuda ninguem e ainda convida a escolher o fracionario
        por engano. Em tempo real, usamos a lista liquida configurada.
        """
        if self.is_metatrader:
            return self.monitored_symbols
        lister = getattr(self.provider, "list_symbols", None)
        return tuple(lister()) if lister is not None else ()


def build_market_data_provider(
    settings: Settings,
    clock: Clock,
    *,
    fixtures_root: Path | None = None,
) -> ProviderChoice:
    """O provider da configuracao atual.

    Com `CASHINHO_MT5_ENABLED=true`, o MetaTrader. Caso contrario, os CSVs de
    desenvolvimento - que sao **sinteticos** e se identificam como tal.
    """
    if settings.mt5_enabled:
        provider = MetaTraderMarketDataProvider(
            clock,
            terminal_path=settings.mt5_terminal_path,
            server_timezone=settings.mt5_server_timezone,
            stale_seconds=settings.mt5_stale_seconds,
        )
        return ProviderChoice(
            provider=provider,
            kind="metatrader",
            realtime=True,
            reason="CASHINHO_MT5_ENABLED=true",
            monitored_symbols=settings.monitored_symbols,
        )

    root = fixtures_root or (Path("data") / "fixtures")
    return ProviderChoice(
        provider=CsvHistoricalProvider(root, clock, name="csv-fixtures"),
        kind="csv",
        realtime=False,
        reason="MetaTrader desabilitado; usando CSVs locais (series sinteticas)",
    )
