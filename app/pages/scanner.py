"""Ranking PAPER de oportunidades com contexto multi-timeframe."""

from __future__ import annotations

from datetime import timedelta

import streamlit as st

from app.components.chrome import page_header, sidebar
from app.runtime import journal_audit_service
from cashinho.adapters.providers.factory import build_market_data_provider
from cashinho.config.settings import get_settings
from cashinho.core.time.clocks import SystemClock
from cashinho.domain.enums import DataStatus, Mode
from cashinho.pipeline.final_decision import make_final_decision
from cashinho.pipeline.indicators import IndicatorSelection
from cashinho.pipeline.market_data import load_market_data
from cashinho.pipeline.multi_timeframe import advise_timeframe, analyze_timeframes
from cashinho.pipeline.operational_policy import load_operational_policy
from cashinho.pipeline.opportunities import build_opportunity
from cashinho.pipeline.paper_ticket import calculate_ticket_sizing
from cashinho.pipeline.study_mode import build_market_study

settings = get_settings()
sidebar(settings)
page_header("Ranking de oportunidades", "Contexto, timeframe e priorização em modo PAPER")
clock = SystemClock()
choice = build_market_data_provider(settings, clock, fixtures_root=settings.data_dir / "fixtures")
provider = choice.provider
operational_policy_path = (
    settings.operational_policy_path
    if settings.operational_policy_path.is_file()
    else settings.default_operational_policy_path
)
operational_policy = load_operational_policy(operational_policy_path)
selection = IndicatorSelection(
    ema_periods=(9, 21), vwap=True, rsi_period=14, macd=True, atr_period=14
)

st.caption(
    "Somente candles fechados participam das decisões. O ranking não envia ordens ao mercado."
)
lookback = st.number_input(
    "Janela de análise (dias)",
    5,
    365,
    60,
    help="Quantidade de dias que o scanner olha para trás ao avaliar todos os ativos.",
)

if st.button(
    "Atualizar ranking",
    type="primary",
    help="Recalcula o ranking usando os candles fechados mais recentes da fonte ativa.",
):
    end = clock.now()
    start = end - timedelta(days=int(lookback))
    prepared = []
    study_meta = {}
    analyses_by_symbol = {}
    for symbol in choice.offered_symbols():
        analyses_series = {}
        statuses = []
        timestamps = []
        ignored = []
        for timeframe in provider.get_available_timeframes(symbol):
            result = load_market_data(
                provider,
                symbol=symbol,
                timeframe=timeframe,
                start=start,
                end=end,
                clock=clock,
                mode=Mode.RESEARCH,
            )
            if result.usable_series is not None:
                statuses.append(result.report.status)
                closed = result.usable_series.closed_only()
                analyses_series[timeframe] = closed
                if closed.last is not None:
                    timestamps.append(closed.last.close_time)
            else:
                ignored.append(f"{timeframe.value}: {result.report.status.value}")
        if not analyses_series:
            continue
        analyses = analyze_timeframes(analyses_series, selection)
        analyses_by_symbol[symbol] = analyses
        advice = advise_timeframe(analyses)
        risk_approved = False
        risk_note = "Sem entrada e stop calculados para dimensionar a posição."
        selected = (
            analyses.get(advice.recommended_timeframe) if advice.recommended_timeframe else None
        )
        strongest = max(analyses.values(), key=lambda item: item.signal.score)
        if selected and selected.signal.entry is not None and selected.signal.stop is not None:
            try:
                sizing = calculate_ticket_sizing(
                    entry=selected.signal.entry,
                    stop=selected.signal.stop,
                    profile=settings.risk_profile(),
                )
                risk_approved = True
                risk_note = (
                    f"Com R$ {settings.risk_profile().capital:,.2f}, cabem até "
                    f"{sizing.quantity} ação(ões); risco estimado R$ {sizing.estimated_risk:,.2f}."
                )
            except ValueError as exc:
                risk_note = f"Bloqueado pelo tamanho da conta: {exc}"
        data_status = (
            max(statuses, key=lambda item: list(type(item)).index(item))
            if statuses
            else DataStatus.BLOCKED
        )
        selected_series = (
            analyses_series.get(advice.recommended_timeframe)
            if advice.recommended_timeframe
            else None
        )
        decision_timestamp = (
            selected_series.last.close_time
            if selected_series is not None and selected_series.last is not None
            else max(timestamps)
        )
        prepared.append(
            {
                "symbol": symbol,
                "analyses": analyses,
                "advice": advice,
                "data_status": data_status,
                "risk_approved": risk_approved,
                "risk_note": risk_note,
                "decision_timestamp": decision_timestamp,
                "selected": selected,
                "strongest": strongest,
                "ignored": ignored,
            }
        )

    decisions = []
    for item in prepared:
        symbol = item["symbol"]
        analyses = item["analyses"]
        advice = item["advice"]
        data_status = item["data_status"]
        risk_approved = bool(item["risk_approved"])
        market_study = build_market_study(analyses_by_symbol, side=advice.side)
        selected = item["selected"]
        policy_decision = operational_policy.evaluate(
            symbol=symbol,
            timestamp=item["decision_timestamp"],
            timeframe=advice.recommended_timeframe,
            side=advice.side,
            regime=selected.regime.regime.value if selected is not None else None,
            volatility=selected.regime.volatility if selected is not None else None,
            display_timezone=settings.display_timezone,
        )
        opportunity = build_opportunity(
            symbol=symbol,
            advice=advice,
            analyses=analyses,
            data_status=data_status,
            risk_approved=risk_approved,
            timestamp=item["decision_timestamp"],
        )
        decision = make_final_decision(
            opportunity,
            data_quality_approved=data_status is not DataStatus.BLOCKED,
            risk_approved=risk_approved,
            candles_closed=True,
            market_approved=market_study.approved,
            market_reason=market_study.reason,
            operational_policy_approved=policy_decision.approved,
            operational_policy_reason=policy_decision.summary,
            extra_reasons=(
                f"Modo Estudo Profundo: {market_study.summary}",
                f"Conta de estudo: {item['risk_note']}",
                f"Base historica: {policy_decision.summary}",
            ),
            minimum_risk_reward=settings.risk_profile().min_risk_reward,
        )
        strongest = item["strongest"]
        study_status = (
            selected.signal.status
            if selected is not None
            else strongest.signal.status
            or decision.primary_reason
        )
        study_side = (
            selected.signal.side
            if selected is not None and selected.signal.side != "NONE"
            else strongest.signal.side
        )
        study_meta[symbol] = {
            "status": study_status,
            "note": " · ".join(ignored) if ignored else "Todos os timeframes carregados.",
            "side": study_side,
            "score": selected.signal.score if selected is not None else strongest.signal.score,
            "timeframe": (
                selected.timeframe.value if selected is not None else strongest.timeframe.value
            ),
            "market": market_study.summary,
            "market_reason": market_study.reason,
            "risk": item["risk_note"],
            "policy": policy_decision.summary,
        }
        journal_audit_service().record_decision(decision, mode=Mode.RESEARCH)
        decisions.append(decision)
    st.session_state["final_decision_ranking"] = sorted(
        decisions,
        key=lambda item: (
            item.should_enter,
            study_meta.get(item.symbol, {}).get("score", item.confidence),
        ),
        reverse=True,
    )
    st.session_state["final_decision_study_meta"] = study_meta

ranking = st.session_state.get("final_decision_ranking", [])
study_meta = st.session_state.get("final_decision_study_meta", {})
if ranking:
    rows = [
        {
            "Ativo": item.symbol,
            "Decisão": "ENTRADA" if item.should_enter else "NÃO ENTRAR",
            "Leitura de estudo": study_meta.get(item.symbol, {}).get(
                "status", item.primary_reason
            ),
            "Lado": (
                "COMPRA"
                if study_meta.get(item.symbol, {}).get("side", item.side) == "BUY"
                else "VENDA"
                if study_meta.get(item.symbol, {}).get("side", item.side) == "SELL"
                else "—"
            ),
            "Timeframe": study_meta.get(item.symbol, {}).get(
                "timeframe", item.timeframe.value if item.timeframe else "—"
            ),
            "Confiança": study_meta.get(item.symbol, {}).get("score", item.confidence),
            "R:R": item.risk_reward if item.risk_reward is not None else "—",
            "Observação": item.primary_reason,
            "Mercado amplo": study_meta.get(item.symbol, {}).get("market_reason", "—"),
            "Conta R$100": study_meta.get(item.symbol, {}).get("risk", "—"),
            "Base histórica": study_meta.get(item.symbol, {}).get("policy", "—"),
        }
        for item in ranking
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption(
        "O primeiro item tende a ser o mais forte pelo critério atual, mas cada linha ainda precisa ser lida."
    )
    selected_symbol = st.selectbox(
        "Abrir oportunidade",
        [item.symbol for item in ranking],
        help="Escolha uma linha do ranking para ver o motivo detalhado da decisão.",
    )
    selected = next(item for item in ranking if item.symbol == selected_symbol)
    st.markdown(f"### {selected.symbol} · {selected.state}")
    st.write(selected.primary_reason)
    if selected.symbol in study_meta:
        meta = study_meta[selected.symbol]
        side_label = "compra" if meta.get("side") == "BUY" else "venda" if meta.get("side") == "SELL" else "neutra"
        st.info(
            f"Leitura de estudo: **{meta.get('status')}** no timeframe "
            f"**{meta.get('timeframe')}**, lado **{side_label}**, "
            f"confiança **{meta.get('score')}/100**. Isso ainda não é entrada liberada.",
            icon="🔎",
        )
        st.warning(
            f"Modo Estudo Profundo: {meta.get('market_reason')} {meta.get('risk')}",
            icon="❔",
        )
        st.warning(
            f"Base histórica: {meta.get('policy')}",
            icon="❔",
        )
    st.caption(study_meta.get(selected.symbol, {}).get("note", ""))
    with st.expander("Por que essa decisão?"):
        st.caption(
            "Lista dos fatores que pesaram na decisão. Ela ajuda a conferir se o sinal faz sentido."
        )
        for reason in selected.reasons:
            st.write(f"• {reason}")
else:
    st.info("Atualize o ranking para avaliar os ativos disponíveis no provider.")
