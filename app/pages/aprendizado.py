"""Dashboard de aprendizado operacional do Cashinho."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from app.components.chrome import page_header, sidebar
from cashinho.config.settings import get_settings

settings = get_settings()
sidebar(settings)
page_header(
    "Aprendizado do Cashinho",
    "Erros, dias estudados, filtros e hipóteses validadas nos estudos históricos",
)
st.caption(
    "Esta tela mostra o que o Cashinho aprendeu nos relatórios de diagnóstico. "
    "Ela não promete resultado futuro e não libera dinheiro real sozinha."
)


@st.cache_data(show_spinner=False)
def _load_csv(path: str) -> pd.DataFrame:
    file_path = Path(path)
    if not file_path.is_file() or file_path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(file_path)


def _report_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    candidates = [
        path
        for path in root.rglob("*")
        if path.is_dir() and (path / "diagnostic_report.md").is_file()
    ]
    return sorted(candidates, key=lambda path: (path / "diagnostic_report.md").stat().st_mtime, reverse=True)


def _metric_value(frame: pd.DataFrame, column: str, default: str = "-") -> str:
    if frame.empty or column not in frame.columns:
        return default
    value = frame[column].iloc[0]
    return default if pd.isna(value) else str(value)


def _show_frame(frame: pd.DataFrame, empty_message: str) -> None:
    if frame.empty:
        st.info(empty_message)
        return
    st.dataframe(frame, use_container_width=True, hide_index=True)


reports_root = settings.data_dir / "reports"
report_dirs = _report_dirs(reports_root)
if not report_dirs:
    st.info(
        "Nenhum relatório de aprendizado foi encontrado. Rode o diagnóstico histórico para gerar os CSVs.",
    )
    st.code(
        "python scripts/run_backtest_diagnostics.py --require-real-data --years 2020-2026 --timeframes 5m,15m,60m,1D --decision-timeframe 5m",
        language="powershell",
    )
    st.stop()

selected_dir = st.selectbox(
    "Relatório estudado",
    report_dirs,
    format_func=lambda path: str(path.relative_to(reports_root)),
    help=(
        "Escolha qual estudo histórico o Cashinho deve mostrar. "
        "O mais recente aparece primeiro."
    ),
)

loss_autopsy = _load_csv(str(selected_dir / "loss_autopsy.csv"))
error_causes = _load_csv(str(selected_dir / "error_causes.csv"))
daily_learning = _load_csv(str(selected_dir / "daily_learning.csv"))
annual_learning = _load_csv(str(selected_dir / "annual_learning.csv"))
filter_contribution = _load_csv(str(selected_dir / "filter_contribution.csv"))
missed_opportunities = _load_csv(str(selected_dir / "missed_opportunities.csv"))
simulated_missed_trades = _load_csv(str(selected_dir / "simulated_missed_trades.csv"))
operational_lines = _load_csv(str(selected_dir / "operational_lines.csv"))
simulated_operational_lines = _load_csv(str(selected_dir / "simulated_operational_lines.csv"))
operational_readiness = _load_csv(str(selected_dir / "operational_readiness.csv"))
policy_holdout = _load_csv(str(selected_dir / "policy_holdout.csv"))
score_calibration = _load_csv(str(selected_dir / "score_calibration.csv"))

summary = st.columns(4)
summary[0].metric(
    "Pregões estudados",
    str(len(daily_learning)) if not daily_learning.empty else "0",
    help="Quantidade de dias com candles analisados, incluindo dias sem entrada.",
)
summary[1].metric(
    "Operações",
    str(int(annual_learning["Total operacoes"].sum())) if "Total operacoes" in annual_learning else "0",
    help="Total de operações geradas no estudo selecionado.",
)
summary[2].metric(
    "Principal causa",
    _metric_value(error_causes, "Causa"),
    help="Causa provável que mais pesou no prejuízo das operações negativas.",
)
summary[3].metric(
    "Prontidão operacional",
    _metric_value(operational_readiness, "Confiabilidade operacional %"),
    help="Nota calculada pelo estudo para uso operacional com dinheiro real.",
)

tabs = st.tabs(
    [
        "Causas de perda",
        "Dia a dia",
        "Ano a ano",
        "Filtros",
        "Oportunidades perdidas",
        "Entradas simuladas",
        "Linha operacional",
        "Linhas simuladas",
        "Prontidão",
        "Validação",
        "Arquivos",
    ]
)

with tabs[0]:
    st.caption(
        "Mostra por que o Cashinho perdeu dinheiro. A causa é uma hipótese técnica, não uma certeza."
    )
    _show_frame(error_causes, "Nenhuma causa de perda registrada neste relatório.")
    with st.expander("Operações negativas analisadas", expanded=False):
        st.caption("Cada linha é uma autópsia de uma operação negativa específica.")
        _show_frame(loss_autopsy, "Nenhuma operação negativa para detalhar.")

with tabs[1]:
    st.caption(
        "Cada pregão aparece aqui, inclusive quando o Cashinho não entrou. "
        "A coluna Aprendizado explica o motivo principal do dia."
    )
    _show_frame(daily_learning, "Nenhum resumo diário encontrado.")

with tabs[2]:
    st.caption(
        "Resume cada ano por ativo: dias estudados, dias operados, resultado, expectativa e drawdown."
    )
    _show_frame(annual_learning, "Nenhum resumo anual encontrado.")

with tabs[3]:
    st.caption(
        "Mostra quais filtros bloquearam mais decisões. Muitos bloqueios não significam erro automático; "
        "eles indicam onde investigar excesso de conservadorismo."
    )
    _show_frame(filter_contribution, "Nenhuma contribuição de filtro encontrada.")

with tabs[4]:
    st.caption(
        "Mostra rejeições que, depois do fato, tiveram movimento a favor. "
        "Isso serve para estudar filtros conservadores, não para justificar entrada com dado futuro."
    )
    _show_frame(missed_opportunities, "Nenhuma oportunidade perdida relevante encontrada.")

with tabs[5]:
    st.caption(
        "Reproduz, no passado, entradas fortes que foram bloqueadas. "
        "Serve para aprender se algum bloqueio foi conservador demais; não usa dado futuro ao vivo."
    )
    _show_frame(simulated_missed_trades, "Nenhuma entrada bloqueada pôde ser simulada com plano completo.")

with tabs[6]:
    st.caption(
        "Compara linhas operacionais candidatas. Uma linha só é aceitável se passar fora da amostra, "
        "com custos, expectativa positiva, drawdown controlado e amostra mínima."
    )
    _show_frame(operational_lines, "Nenhuma linha operacional candidata foi avaliada.")

with tabs[7]:
    st.caption(
        "Compara linhas usando apenas entradas simuladas que tinham sido bloqueadas. "
        "Quando algo passa aqui, vira hipótese para novo teste, não autorização automática."
    )
    _show_frame(simulated_operational_lines, "Nenhuma linha simulada foi avaliada.")

with tabs[8]:
    st.caption(
        "Resume o percentual técnico e operacional do Cashinho. "
        "A nota operacional só sobe quando há amostra, holdout, Monte Carlo e linhas aprovadas."
    )
    _show_frame(operational_readiness, "Nenhuma nota de prontidão foi calculada.")

with tabs[9]:
    st.caption(
        "Valida se a evolução funcionou fora da amostra e se o score conversa com resultado líquido."
    )
    st.subheader("Holdout", help="Treina no passado e mede apenas depois, reduzindo vazamento de futuro.")
    _show_frame(policy_holdout, "Nenhum holdout encontrado.")
    st.subheader("Score", help="Compara faixas de score com resultado, custos e drawdown.")
    _show_frame(score_calibration, "Nenhuma calibração de score encontrada.")

with tabs[10]:
    st.caption("Arquivos gerados pelo estudo selecionado.")
    files = sorted(path.name for path in selected_dir.glob("*") if path.is_file())
    st.dataframe(pd.DataFrame({"Arquivo": files}), use_container_width=True, hide_index=True)
    st.caption(f"Pasta: `{selected_dir}`")
