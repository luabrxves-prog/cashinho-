"""Configuracao central.

Toda leitura de ambiente acontece aqui. `os.getenv` espalhado pelo codigo
e proibido: sem um ponto unico, nao ha como hashear a configuracao para
registrar no AnalysisRun.

O modo padrao e PAPER. LIVE e recusado em runtime enquanto os mecanismos
de seguranca nao estiverem implementados e testados.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from cashinho.domain.enums import Mode
from cashinho.domain.errors import ModeNotAllowedError
from cashinho.domain.risk import RiskProfile

PROJECT_ROOT = Path(__file__).resolve().parents[3]
"""Raiz do repositorio (src/cashinho/config/settings.py -> tres niveis acima)."""

IMPLEMENTED_MODES: frozenset[Mode] = frozenset(
    {Mode.RESEARCH, Mode.BACKTEST, Mode.REPLAY, Mode.PAPER}
)
"""Modos habilitados nesta fase.

ASSISTED e LIVE dependem de provedor em tempo real, do Risk Manager
completo e do gerador de boleta validado. Ate la, sao recusados.
"""


class Settings(BaseSettings):
    """Configuracao da aplicacao, carregada de variaveis de ambiente."""

    model_config = SettingsConfigDict(
        env_prefix="CASHINHO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    mode: Mode = Mode.PAPER
    database_url: str = "sqlite:///data/cashinho.db"
    log_level: str = "INFO"
    log_format: str = Field(default="console", pattern="^(console|json)$")
    display_timezone: str = "America/Sao_Paulo"
    capital: Decimal = Decimal("100.00")

    # --- MetaTrader 5 (somente Market Data) -------------------------------
    # Nenhuma credencial da corretora aqui, e nao deve haver (regra 7): quem
    # autentica e o operador, no proprio terminal.
    mt5_enabled: bool = False
    mt5_terminal_path: str = ""
    """Caminho do terminal. Vazio deixa o MT5 localizar sozinho; preencher
    so quando houver mais de um MetaTrader instalado na maquina."""

    mt5_server_timezone: str = "America/Sao_Paulo"
    """Fuso em que o servidor da corretora marca as horas.

    E o que impede o deslocamento de tres horas: o inteiro devolvido pelo MT5
    e relogio de parede do servidor, nao epoch UTC.
    """

    mt5_stale_seconds: int = Field(default=60, ge=1)
    """Segundos sem tick novo, com o mercado aberto, para o feed virar STALE."""

    mt5_refresh_seconds: int = Field(default=5, ge=1)
    """Intervalo de atualizacao das telas em tempo real."""

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        upper = value.upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if upper not in allowed:
            raise ValueError(f"log_level invalido: {value!r}; use um de {sorted(allowed)}")
        return upper

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def data_dir(self) -> Path:
        return PROJECT_ROOT / "data"

    @property
    def operational_policy_path(self) -> Path:
        return self.data_dir / "reports" / "deep_study" / "operational_policy.json"

    @property
    def default_operational_policy_path(self) -> Path:
        return PROJECT_ROOT / "src" / "cashinho" / "config" / "operational_policy.default.json"

    @property
    def mode_is_implemented(self) -> bool:
        return self.mode in IMPLEMENTED_MODES

    def ensure_mode_allowed(self) -> Mode:
        """Recusa modos ainda nao implementados.

        Chamado no arranque da aplicacao. Falhar aqui e barato; descobrir
        no envio de uma ordem, nao.
        """
        if self.mode not in IMPLEMENTED_MODES:
            raise ModeNotAllowedError(
                f"modo {self.mode} nao esta implementado nesta versao. "
                f"Modos disponiveis: {sorted(m.value for m in IMPLEMENTED_MODES)}. "
                "Execucao real de ordens nao esta implementada."
            )
        return self.mode

    def risk_profile(self) -> RiskProfile:
        """Perfil de risco derivado da configuracao.

        Nesta fase apenas o capital vem do ambiente; os demais limites
        usam os padroes do modelo. A Fase 4 move isso para arquivo
        versionado e hasheado.
        """
        return RiskProfile(capital=self.capital)

    def config_hash(self) -> str:
        """Hash estavel da configuracao efetiva.

        Registrado em cada AnalysisRun. Sem ele, uma analise antiga nao
        pode ser reconstruida com os mesmos parametros.
        """
        payload = json.dumps(
            {
                "mode": self.mode.value,
                "capital": str(self.capital),
                "display_timezone": self.display_timezone,
                "risk_profile": self.risk_profile().model_dump(mode="json"),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Configuracao unica do processo.

    Em cache porque o Streamlit reexecuta o script a cada interacao;
    reler o ambiente a cada rerun geraria hashes de configuracao
    instaveis dentro da mesma sessao.
    """
    return Settings()


def reset_settings_cache() -> None:
    """Limpa o cache. Uso restrito a testes."""
    get_settings.cache_clear()
