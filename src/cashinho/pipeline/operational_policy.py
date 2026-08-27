"""Politica operacional derivada de estudos historicos.

A politica nao transforma passado em promessa. Ela apenas impede que a
FinalDecision ignore contextos historicamente ruins ou pouco robustos.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from cashinho.domain.enums import Timeframe
from cashinho.pipeline.backtest_diagnostics import DiagnosticTrade, diagnostic_table

PolicyAction = Literal["BLOCK", "WARN"]

DEFAULT_DIMENSIONS = ("symbol", "hour", "side", "timeframe", "regime", "volatility")
DEFAULT_MIN_TRADES = {
    "symbol": 12,
    "hour": 8,
    "side": 12,
    "timeframe": 12,
    "regime": 8,
    "volatility": 8,
}


@dataclass(frozen=True, slots=True)
class OperationalPolicyRule:
    dimension: str
    bucket: str
    action: PolicyAction
    reason: str
    total_trades: int
    win_rate: Decimal | None
    profit_factor: Decimal | None
    net_profit: Decimal
    max_drawdown_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class OperationalPolicyDecision:
    approved: bool
    blocking_rules: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        if self.blocking_rules:
            return "Base historica bloqueou: " + " | ".join(self.blocking_rules)
        if self.warnings:
            return "Base historica alerta: " + " | ".join(self.warnings)
        return "Base historica nao encontrou bloqueio para este contexto."


@dataclass(frozen=True, slots=True)
class OperationalPolicy:
    generated_at: str
    source: str
    rules: tuple[OperationalPolicyRule, ...] = ()

    def evaluate(
        self,
        *,
        symbol: str,
        timestamp: datetime,
        timeframe: Timeframe | None,
        side: str,
        regime: str | None = None,
        volatility: str | None = None,
        display_timezone: str = "America/Sao_Paulo",
    ) -> OperationalPolicyDecision:
        values = _context_values(
            symbol=symbol,
            timestamp=timestamp,
            timeframe=timeframe,
            side=side,
            regime=regime,
            volatility=volatility,
            display_timezone=display_timezone,
        )
        blocking = []
        warnings = []
        for rule in self.rules:
            if values.get(rule.dimension) != rule.bucket:
                continue
            message = rule.reason
            if rule.action == "BLOCK":
                blocking.append(message)
            else:
                warnings.append(message)
        return OperationalPolicyDecision(
            approved=not blocking,
            blocking_rules=tuple(dict.fromkeys(blocking)),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def to_json(self) -> str:
        payload = {
            "generated_at": self.generated_at,
            "source": self.source,
            "rules": [_rule_to_dict(rule) for rule in self.rules],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def empty_policy(source: str = "sem estudo historico carregado") -> OperationalPolicy:
    return OperationalPolicy(generated_at="", source=source, rules=())


def load_operational_policy(path: Path) -> OperationalPolicy:
    if not path.is_file():
        return empty_policy(f"arquivo ausente: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rules = tuple(_rule_from_dict(item) for item in payload.get("rules", ()))
    return OperationalPolicy(
        generated_at=str(payload.get("generated_at", "")),
        source=str(payload.get("source", path.as_posix())),
        rules=rules,
    )


def save_operational_policy(policy: OperationalPolicy, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(policy.to_json() + "\n", encoding="utf-8")


def build_policy_from_diagnostics(
    diagnostics: tuple[DiagnosticTrade, ...],
    *,
    initial_capital: Decimal,
    generated_at: datetime,
    source: str,
    dimensions: tuple[str, ...] = DEFAULT_DIMENSIONS,
    min_trades_by_dimension: dict[str, int] | None = None,
) -> OperationalPolicy:
    min_trades = min_trades_by_dimension or DEFAULT_MIN_TRADES
    rules: list[OperationalPolicyRule] = []
    for dimension in dimensions:
        rows = diagnostic_table(diagnostics, initial_capital=initial_capital, dimension=dimension)
        for row in rows:
            metrics = row.metrics
            minimum = min_trades.get(dimension, 10)
            if metrics.total_trades < minimum:
                continue
            action = _classify_rule_action(
                net_profit=metrics.net_profit,
                profit_factor=metrics.profit_factor,
                win_rate=metrics.win_rate,
                max_drawdown_pct=metrics.max_drawdown_pct,
            )
            if action is None:
                continue
            rules.append(
                OperationalPolicyRule(
                    dimension=dimension,
                    bucket=row.bucket,
                    action=action,
                    reason=_rule_reason(dimension, row.bucket, action, metrics.total_trades),
                    total_trades=metrics.total_trades,
                    win_rate=metrics.win_rate,
                    profit_factor=metrics.profit_factor,
                    net_profit=metrics.net_profit,
                    max_drawdown_pct=metrics.max_drawdown_pct,
                )
            )
    return OperationalPolicy(
        generated_at=generated_at.isoformat(),
        source=source,
        rules=tuple(rules),
    )


def _context_values(
    *,
    symbol: str,
    timestamp: datetime,
    timeframe: Timeframe | None,
    side: str,
    regime: str | None,
    volatility: str | None,
    display_timezone: str,
) -> dict[str, str]:
    local = timestamp.astimezone(ZoneInfo(display_timezone))
    return {
        "symbol": symbol.upper(),
        "hour": f"{local.hour:02d}:00",
        "side": side,
        "timeframe": timeframe.value if timeframe else "",
        "regime": regime or "",
        "volatility": volatility or "",
    }


def _classify_rule_action(
    *,
    net_profit: Decimal,
    profit_factor: Decimal | None,
    win_rate: Decimal | None,
    max_drawdown_pct: Decimal | None,
) -> PolicyAction | None:
    weak_profit_factor = profit_factor is not None and profit_factor < Decimal("0.90")
    weak_win_rate = win_rate is not None and win_rate < Decimal("35")
    heavy_drawdown = max_drawdown_pct is not None and max_drawdown_pct >= Decimal("8")
    if net_profit < 0 and (weak_profit_factor or weak_win_rate or heavy_drawdown):
        return "BLOCK"
    if net_profit < 0 or (profit_factor is not None and profit_factor < Decimal("1.10")):
        return "WARN"
    return None


def _rule_reason(
    dimension: str,
    bucket: str,
    action: PolicyAction,
    total_trades: int,
) -> str:
    prefix = "Bloqueio" if action == "BLOCK" else "Alerta"
    label = {
        "symbol": "ativo",
        "hour": "horario",
        "side": "lado",
        "timeframe": "timeframe",
        "regime": "regime",
        "volatility": "volatilidade",
    }.get(dimension, dimension)
    return f"{prefix}: {label} {bucket} foi ruim no estudo historico ({total_trades} trades)."


def _rule_to_dict(rule: OperationalPolicyRule) -> dict[str, object]:
    return {
        "dimension": rule.dimension,
        "bucket": rule.bucket,
        "action": rule.action,
        "reason": rule.reason,
        "total_trades": rule.total_trades,
        "win_rate": str(rule.win_rate) if rule.win_rate is not None else None,
        "profit_factor": str(rule.profit_factor) if rule.profit_factor is not None else None,
        "net_profit": str(rule.net_profit),
        "max_drawdown_pct": (
            str(rule.max_drawdown_pct) if rule.max_drawdown_pct is not None else None
        ),
    }


def _rule_from_dict(payload: dict[str, object]) -> OperationalPolicyRule:
    action = str(payload["action"])
    if action not in {"BLOCK", "WARN"}:
        raise ValueError(f"acao de politica invalida: {action}")
    return OperationalPolicyRule(
        dimension=str(payload["dimension"]),
        bucket=str(payload["bucket"]),
        action=action,  # type: ignore[arg-type]
        reason=str(payload["reason"]),
        total_trades=int(str(payload["total_trades"])),
        win_rate=_decimal_or_none(payload.get("win_rate")),
        profit_factor=_decimal_or_none(payload.get("profit_factor")),
        net_profit=Decimal(str(payload["net_profit"])),
        max_drawdown_pct=_decimal_or_none(payload.get("max_drawdown_pct")),
    )


def _decimal_or_none(value: object | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))
