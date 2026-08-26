"""Regressões visuais básicas da camada Streamlit."""

from __future__ import annotations

from app.components.charts import candlestick_figure
from app.components.theme import CHART_COLORS

from cashinho.domain.market import CandleSeries
from cashinho.pipeline.indicators import IndicatorPanel


def test_grafico_usa_layout_compativel_com_tema_escuro(series: CandleSeries) -> None:
    figure = candlestick_figure(
        series,
        display_timezone="America/Sao_Paulo",
        panel=IndicatorPanel(),
    )

    assert figure.layout.paper_bgcolor == "rgba(0,0,0,0)"
    assert figure.layout.plot_bgcolor == "rgba(0,0,0,0)"
    assert figure.layout.hoverlabel.bgcolor == CHART_COLORS["hover_bg"]
    assert figure.layout.hoverlabel.font.color == CHART_COLORS["hover_text"]
    assert figure.layout.xaxis.gridcolor == CHART_COLORS["grid"]
    assert figure.layout.yaxis.gridcolor == CHART_COLORS["grid"]
