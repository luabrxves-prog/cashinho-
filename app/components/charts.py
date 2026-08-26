"""Grafico de candles com indicadores.

Recebe uma `CandleSeries` ja validada e um `IndicatorPanel` ja calculado.
Nao calcula nada e nao decide nada: apenas desenha.
"""

from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.components.theme import CHART_COLORS
from cashinho.domain.market import CandleSeries
from cashinho.pipeline.indicators import IndicatorPanel

UP = CHART_COLORS["up"]
DOWN = CHART_COLORS["down"]
VWAP_COLOR = CHART_COLORS["vwap"]
BAND_COLOR = CHART_COLORS["band"]
OVERLAY_COLORS = CHART_COLORS["overlay"]


def candlestick_figure(
    series: CandleSeries,
    *,
    display_timezone: str,
    panel: IndicatorPanel | None = None,
    show_volume: bool = True,
) -> go.Figure:
    """Candles, volume e indicadores em paineis empilhados.

    Overlays vao sobre o preco; osciladores ganham painel proprio, porque
    RSI (0-100), MACD (em torno de zero) e ATR (em reais) tem escalas
    incompativeis e sobrepo-los tornaria os tres ilegiveis.
    """
    panel = panel or IndicatorPanel()
    frame = series.to_frame().tz_convert(display_timezone)

    rows: list[str] = ["price"]
    if show_volume:
        rows.append("volume")
    rows.extend(panel.oscillators)

    figure = make_subplots(
        rows=len(rows),
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=_row_heights(len(rows), with_volume=show_volume),
    )

    figure.add_trace(
        go.Candlestick(
            x=frame.index,
            open=frame["open"],
            high=frame["high"],
            low=frame["low"],
            close=frame["close"],
            name=series.symbol,
            increasing_line_color=UP,
            decreasing_line_color=DOWN,
        ),
        row=1,
        col=1,
    )

    _add_overlays(figure, panel, display_timezone)

    if show_volume:
        figure.add_trace(
            go.Bar(
                x=frame.index,
                y=frame["volume"],
                name="Volume",
                marker_color=[
                    UP if c >= o else DOWN
                    for c, o in zip(frame["close"], frame["open"], strict=False)
                ],
                opacity=0.55,
            ),
            row=2,
            col=1,
        )
        figure.update_yaxes(title_text="Volume", row=2, col=1)

    _add_oscillators(
        figure,
        panel,
        display_timezone,
        first_row=len(rows) - len(panel.oscillators) + 1,
    )

    figure.update_layout(
        title=f"{series.symbol} · {series.timeframe.value}",
        height=380 + 150 * (len(rows) - 1),
        margin={"l": 45, "r": 20, "t": 60, "b": 30},
        showlegend=True,
        legend={
            "bgcolor": "rgba(0,0,0,0)",
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "x": 0,
        },
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        hoverlabel={
            "bgcolor": CHART_COLORS["hover_bg"],
            "bordercolor": CHART_COLORS["axis"],
            "font": {"color": CHART_COLORS["hover_text"]},
        },
        barmode="overlay",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    figure.update_yaxes(title_text="Preço", row=1, col=1)
    figure.update_xaxes(
        gridcolor=CHART_COLORS["grid"],
        linecolor=CHART_COLORS["axis"],
        zerolinecolor=CHART_COLORS["axis"],
    )
    figure.update_yaxes(
        gridcolor=CHART_COLORS["grid"],
        linecolor=CHART_COLORS["axis"],
        zerolinecolor=CHART_COLORS["axis"],
    )

    # Sem os intervalos entre pregoes, o grafico intradiario fica dominado
    # por vazio noturno e o movimento do dia some.
    breaks: list[dict[str, object]] = [{"bounds": ["sat", "mon"]}]
    if series.timeframe.is_intraday:
        breaks.append({"bounds": [17, 10], "pattern": "hour"})
    figure.update_xaxes(rangebreaks=breaks)

    return figure


def _row_heights(total: int, *, with_volume: bool) -> list[float]:
    """Preco domina; volume fica menor que os osciladores."""
    if total == 1:
        return [1.0]
    price = 0.52 if total > 2 else 0.75
    restante = 1.0 - price
    outros = total - 1
    if with_volume and outros > 1:
        volume = restante * 0.30
        cada = (restante - volume) / (outros - 1)
        return [price, volume, *([cada] * (outros - 1))]
    return [price, *([restante / outros] * outros)]


def _add_overlays(figure: go.Figure, panel: IndicatorPanel, timezone: str) -> None:
    cores = iter(OVERLAY_COLORS * 4)
    for label, resultado in panel.overlays.items():
        valores = resultado.values.tz_convert(timezone)

        if "vwap" in valores.columns:
            figure.add_trace(
                go.Scatter(
                    x=valores.index,
                    y=valores["vwap"],
                    name="VWAP",
                    line={"color": VWAP_COLOR, "width": 2, "dash": "dot"},
                ),
                row=1,
                col=1,
            )
            continue

        if {"upper", "middle", "lower"} <= set(valores.columns):
            for coluna, dash in (("upper", "dash"), ("middle", "solid"), ("lower", "dash")):
                figure.add_trace(
                    go.Scatter(
                        x=valores.index,
                        y=valores[coluna],
                        name=f"{label} {coluna}",
                        line={"color": BAND_COLOR, "width": 1, "dash": dash},
                        showlegend=coluna == "middle",
                    ),
                    row=1,
                    col=1,
                )
            continue

        coluna = str(valores.columns[0])
        figure.add_trace(
            go.Scatter(
                x=valores.index,
                y=valores[coluna],
                name=label,
                line={"color": next(cores), "width": 1.6},
            ),
            row=1,
            col=1,
        )


def _add_oscillators(
    figure: go.Figure, panel: IndicatorPanel, timezone: str, *, first_row: int
) -> None:
    for offset, (label, resultado) in enumerate(panel.oscillators.items()):
        row = first_row + offset
        valores = resultado.values.tz_convert(timezone)

        if "macd" in valores.columns:
            figure.add_trace(
                go.Bar(
                    x=valores.index,
                    y=valores["histogram"],
                    name="Histograma",
                    marker_color=[
                        UP if v >= 0 else DOWN for v in valores["histogram"].fillna(0)
                    ],
                    opacity=0.5,
                ),
                row=row,
                col=1,
            )
            figure.add_trace(
                go.Scatter(
                    x=valores.index,
                    y=valores["macd"],
                    name="MACD",
                    line={"color": OVERLAY_COLORS[0], "width": 1.5},
                ),
                row=row,
                col=1,
            )
            figure.add_trace(
                go.Scatter(
                    x=valores.index,
                    y=valores["signal"],
                    name="Sinal",
                    line={"color": OVERLAY_COLORS[1], "width": 1.3},
                ),
                row=row,
                col=1,
            )
            figure.update_yaxes(title_text="MACD", row=row, col=1)
            continue

        coluna = str(valores.columns[0])
        figure.add_trace(
            go.Scatter(
                x=valores.index,
                y=valores[coluna],
                name=label,
                line={"color": OVERLAY_COLORS[0], "width": 1.5},
            ),
            row=row,
            col=1,
        )

        if coluna.startswith("rsi"):
            # 70 e 30 sao referencias visuais de leitura, nao regras do
            # indicador nem sinais de operacao.
            for nivel in (70, 30):
                figure.add_hline(
                    y=nivel,
                    line={"color": BAND_COLOR, "width": 1, "dash": "dot"},
                    row=row,
                    col=1,
                )
            figure.update_yaxes(range=[0, 100], title_text="RSI", row=row, col=1)
        else:
            figure.update_yaxes(title_text=label, row=row, col=1)
