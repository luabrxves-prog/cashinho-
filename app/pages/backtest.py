"""Backtest cronológico da FinalDecision de produção."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import streamlit as st

from app.components.backtest_results import render_backtest_comparison
from app.components.chrome import page_header, sidebar
from cashinho.adapters.providers.factory import build_market_data_provider
from cashinho.config.settings import get_settings
from cashinho.core.time.clocks import SystemClock
from cashinho.domain.enums import Mode
from cashinho.domain.errors import CashinhoError
from cashinho.pipeline.backtest import (
    ExecutionCostModel,
    PipelineDecisionEvaluator,
    compare_exit_modes,
    temporal_split,
)
from cashinho.pipeline.indicators import IndicatorSelection
from cashinho.pipeline.market_data import load_market_data

settings = get_settings()
clock = SystemClock()
sidebar(settings)
page_header("Backtest", "Validação histórica candle a candle da FinalDecision")
st.caption(
    "Use esta tela para testar como a regra teria se comportado em candles passados. "
    "É uma simulação técnica, não uma promessa de resultado."
)

st.warning(
    "Resultados históricos não garantem resultados futuros. O backtest é somente analítico e "
    "não envia ordens.",
    icon="⚠️",
)

choice = build_market_data_provider(
    settings, clock, fixtures_root=settings.data_dir / "fixtures"
)
symbols = choice.offered_symbols()
if not symbols:
    st.error("Nenhum ativo histórico está disponível para backtest.")
    st.stop()

input_row = st.columns(3)
default_symbol = "PETR4" if "PETR4" in symbols else symbols[0]
symbol = input_row[0].selectbox(
    "Ativo",
    symbols,
    index=symbols.index(default_symbol),
    help="Papel que será usado no teste histórico.",
)
today = clock.now().date()
start_date = input_row[1].date_input(
    "Início",
    value=today - timedelta(days=90),
    format="DD/MM/YYYY",
    help="Primeiro dia do histórico usado no backtest.",
)
end_date = input_row[2].date_input(
    "Fim",
    value=today,
    format="DD/MM/YYYY",
    help="Último dia do histórico usado no backtest.",
)
if start_date > end_date:
    st.error("A data inicial não pode ser posterior à final.")
    st.stop()

capital_row = st.columns(4)
capital = Decimal(
    str(
        capital_row[0].number_input(
            "Capital inicial (R$)",
            min_value=1.0,
            value=float(settings.capital),
            step=100.0,
            help="Valor inicial usado para calcular risco, tamanho das posições e curva de capital.",
        )
    )
)
spread = Decimal(
    str(
        capital_row[1].number_input(
            "Spread por unidade",
            min_value=0.0,
            value=0.0,
            step=0.01,
            help="Custo estimado entre compra e venda de cada unidade negociada.",
        )
    )
)
slippage = Decimal(
    str(
        capital_row[2].number_input(
            "Slippage por unidade",
            min_value=0.0,
            value=0.0,
            step=0.01,
            help="Diferença simulada entre o preço esperado e o preço executado.",
        )
    )
)
fixed_fee = Decimal(
    str(
        capital_row[3].number_input(
            "Taxa fixa por ordem",
            min_value=0.0,
            value=0.0,
            step=0.01,
            help="Custo fixo simulado cobrado a cada ordem do backtest.",
        )
    )
)

split_row = st.columns(3)
train_pct = int(
    split_row[0].number_input(
        "TRAIN (%)",
        10,
        80,
        60,
        5,
        help="Primeira parte do histórico. Serve para observar o comportamento inicial da regra.",
    )
)
validation_pct = int(
    split_row[1].number_input(
        "VALIDATION (%)",
        10,
        40,
        20,
        5,
        help="Parte intermediária do histórico. Ajuda a verificar se o resultado se mantém fora do treino.",
    )
)
test_pct = 100 - train_pct - validation_pct
split_row[2].metric(
    "TEST (%)",
    test_pct,
    help="Parte final do histórico. Fica reservada para avaliação fora das amostras anteriores.",
)
if test_pct <= 0:
    st.error("TRAIN + VALIDATION deve deixar uma amostra TEST positiva.")
    st.stop()

st.caption(
    "A divisão é temporal e contígua. TEST serve apenas para avaliação; não há otimização "
    "de parâmetros nesta versão."
)

if st.button(
    "EXECUTAR BACKTEST",
    type="primary",
    use_container_width=True,
    help="Roda a simulação candle a candle usando os filtros e custos definidos acima.",
):
    start = datetime.combine(start_date, time.min, tzinfo=UTC)
    end = datetime.combine(end_date, time.min, tzinfo=UTC) + timedelta(days=1)
    series_by_timeframe = {}
    blocked: list[str] = []
    with st.spinner("Processando candles fechados cronologicamente..."):
        try:
            available = choice.provider.get_available_timeframes(symbol)
            for timeframe in available:
                loaded = load_market_data(
                    choice.provider,
                    symbol=symbol,
                    timeframe=timeframe,
                    start=start,
                    end=end,
                    clock=clock,
                    mode=Mode.BACKTEST,
                )
                if loaded.usable_series is None:
                    blocked.append(f"{timeframe.value}: {loaded.rejection_reason or 'Data Quality'}")
                else:
                    series_by_timeframe[timeframe] = loaded.usable_series
        except CashinhoError as exc:
            st.error(f"Falha ao carregar histórico: {exc}")
            st.stop()

        if len(series_by_timeframe) < 2:
            st.error(
                "O backtest da FinalDecision exige ao menos dois timeframes aprovados pelo "
                "Data Quality."
            )
            if blocked:
                st.caption(" · ".join(blocked))
            st.stop()

        profile = settings.risk_profile().model_copy(update={"capital": capital})
        selection = IndicatorSelection(
            ema_periods=(9, 21),
            vwap=True,
            rsi_period=14,
            macd=True,
            atr_period=14,
        )
        evaluator = PipelineDecisionEvaluator(
            selection,
            profile,
            data_quality_approved=not blocked,
        )
        cost_model = ExecutionCostModel(
            spread=spread,
            slippage=slippage,
            fixed_fee_per_order=fixed_fee,
        )
        overall = compare_exit_modes(
            series_by_timeframe,
            evaluator,
            risk_profile=profile,
            costs=cost_model,
        )
        samples = temporal_split(
            series_by_timeframe,
            train_pct=train_pct,
            validation_pct=validation_pct,
        )
        segmented = {
            label: compare_exit_modes(
                sample,
                evaluator,
                risk_profile=profile,
                costs=cost_model,
            )
            for label, sample in samples.items()
            if any(len(series) for series in sample.values())
        }
    st.session_state["backtest_results"] = {
        "capital": capital,
        "overall": overall,
        "segments": segmented,
    }

saved = st.session_state.get("backtest_results")
if saved:
    tabs = st.tabs(["GERAL", "TRAIN", "VALIDATION", "TEST"])
    with tabs[0]:
        st.caption("Resultado considerando todo o período escolhido.")
        render_backtest_comparison(saved["overall"], initial_capital=saved["capital"])
    for tab, label in zip(tabs[1:], ("TRAIN", "VALIDATION", "TEST"), strict=True):
        with tab:
            st.caption(
                f"Resultado apenas da amostra {label}. Compare com as outras abas antes de confiar no padrão."
            )
            result = saved["segments"].get(label)
            if result is None:
                st.info("Amostra sem candles suficientes.")
            else:
                render_backtest_comparison(result, initial_capital=saved["capital"])
