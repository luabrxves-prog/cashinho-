"""Testes de arquitetura.

Regras que dependeriam de disciplina humana viram teste. Sem isto, a
proibicao de `datetime.now()` no dominio duraria ate o primeiro prazo
apertado.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "cashinho"
APP = Path(__file__).resolve().parents[2] / "app"

CLOCK_EXEMPT = {"clocks.py"}
"""Unico lugar autorizado a ler o relogio do sistema."""


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_dominio_nao_le_o_relogio_do_sistema() -> None:
    """ADR-0002: `datetime.now()` e proibido fora de `core/time/clocks.py`."""
    ofensores: list[str] = []
    for path in _python_files(SRC):
        if path.name in CLOCK_EXEMPT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"now", "utcnow", "today"}
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"datetime", "date"}
            ):
                ofensores.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert not ofensores, (
        "leitura direta do relogio fora de clocks.py — use a porta Clock: "
        f"{ofensores}"
    )


@pytest.mark.parametrize("modulo", ["streamlit", "sqlalchemy", "plotly"])
def test_dominio_nao_importa_infraestrutura(modulo: str) -> None:
    """ADR-0001: o dominio nao conhece interface nem persistencia."""
    ofensores: list[str] = []
    for path in _python_files(SRC / "domain"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(n.split(".")[0] == modulo for n in names):
                ofensores.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert not ofensores, f"dominio importando {modulo}: {ofensores}"


def test_interface_nao_importa_sqlalchemy_diretamente() -> None:
    """A UI usa repositorios, nunca consultas montadas na tela."""
    ofensores: list[str] = []
    for path in _python_files(APP):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "sqlalchemy"
            ):
                ofensores.append(f"{path.relative_to(APP)}:{node.lineno}")
            if isinstance(node, ast.Import) and any(
                a.name.startswith("sqlalchemy") for a in node.names
            ):
                ofensores.append(f"{path.relative_to(APP)}:{node.lineno}")
    assert not ofensores, f"interface acessando o ORM diretamente: {ofensores}"


def test_todas_as_paginas_declaradas_existem() -> None:
    """A navegacao nao pode apontar para arquivo inexistente."""
    main = (APP / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(main)
    declaradas = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Page"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]
    assert len(declaradas) == 10, f"esperadas 10 paginas, encontradas {len(declaradas)}"
    ausentes = [p for p in declaradas if not (APP / p).is_file()]
    assert not ausentes, f"paginas declaradas e ausentes: {ausentes}"


def test_env_example_nao_contem_valores_de_credencial() -> None:
    """Nenhum segredo entra no repositorio, nem por descuido no exemplo."""
    root = Path(__file__).resolve().parents[2]
    linhas = (root / ".env.example").read_text(encoding="utf-8").splitlines()
    sensiveis = ("KEY", "TOKEN", "SECRET", "PASSWORD", "SENHA", "ACCOUNT")
    for linha in linhas:
        limpa = linha.strip()
        if limpa.startswith("#") or "=" not in limpa:
            continue
        nome, _, valor = limpa.partition("=")
        if any(s in nome.upper() for s in sensiveis):
            assert not valor.strip(), f"valor preenchido em campo sensivel: {nome}"


def test_gitignore_cobre_env_e_banco() -> None:
    root = Path(__file__).resolve().parents[2]
    conteudo = (root / ".gitignore").read_text(encoding="utf-8")
    for padrao in (".env", "*.db", "data/"):
        assert padrao in conteudo, f"padrao ausente no .gitignore: {padrao}"
