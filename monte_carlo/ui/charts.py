from __future__ import annotations

from typing import Any, Dict, Mapping

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ..config import BLUE, CYAN, GREEN, GRID_COLOR, MUTED_COLOR, ORANGE, PLOT_BG, PURPLE, RED, TEXT_COLOR, MODELS, SCENARIOS

def _plotly_base_layout(title: str, height: int = 480) -> Dict[str, Any]:
    return {
        "title": {"text": title, "font": {"size": 16, "color": TEXT_COLOR}},
        "height": height,
        "template": "plotly_dark",
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": PLOT_BG,
        "font": {"color": TEXT_COLOR, "size": 12},
        "margin": {"l": 55, "r": 35, "t": 70, "b": 55},
        "hovermode": "x unified",
        "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0.0},
    }

def _plot_fan_chart(lab: Mapping[str, Any], horizon: int, show_sample_paths: bool, visible_paths: int) -> go.Figure:
    paths = lab["paths_by_horizon"][horizon]
    levels = lab["levels"]
    base = lab["base"]
    days = np.arange(horizon + 1)
    q5, q25, q50, q75, q95 = np.percentile(paths, [5, 25, 50, 75, 95], axis=0)

    fig = go.Figure()

    history = base["df"]["close"].tail(min(60, len(base["df"]))).to_numpy(dtype=float)
    history_x = np.arange(-len(history) + 1, 1)
    fig.add_trace(
        go.Scatter(
            x=history_x,
            y=history,
            mode="lines",
            name="Observed history",
            line={"color": "#cbd5e1", "width": 2},
            hovertemplate="t=%{x}<br>Price=%{y:.2f}<extra></extra>",
        )
    )

    if show_sample_paths and visible_paths > 0:
        visible_paths = min(int(visible_paths), paths.shape[0], 20)
        indices = np.linspace(0, paths.shape[0] - 1, visible_paths, dtype=int)
        for idx in indices:
            fig.add_trace(
                go.Scatter(
                    x=days,
                    y=paths[idx],
                    mode="lines",
                    line={"color": "rgba(148,163,184,0.18)", "width": 0.8},
                    showlegend=False,
                    hoverinfo="skip",
                )
            )

    # Outer band P5-P95.
    fig.add_trace(go.Scatter(x=days, y=q5, mode="lines", line={"width": 0}, showlegend=False, hoverinfo="skip"))
    fig.add_trace(
        go.Scatter(
            x=days,
            y=q95,
            mode="lines",
            line={"width": 0},
            fill="tonexty",
            fillcolor="rgba(86,168,255,0.12)",
            name="P5–P95",
            hoverinfo="skip",
        )
    )

    # Inner band P25-P75.
    fig.add_trace(go.Scatter(x=days, y=q25, mode="lines", line={"width": 0}, showlegend=False, hoverinfo="skip"))
    fig.add_trace(
        go.Scatter(
            x=days,
            y=q75,
            mode="lines",
            line={"width": 0},
            fill="tonexty",
            fillcolor="rgba(83,214,232,0.22)",
            name="P25–P75",
            hoverinfo="skip",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=days,
            y=q50,
            mode="lines",
            name="Median P50",
            line={"color": CYAN, "width": 3},
            hovertemplate="Day %{x}<br>P50=%{y:.2f}<extra></extra>",
        )
    )

    for name, value, color, dash in (
        ("Structural stop", levels["stop_structural"], RED, "dash"),
        ("Short stop", levels["stop_short"], ORANGE, "dash"),
        ("Current", levels["current"], "#f8fafc", "dot"),
        ("Target 1", levels["target_1"], GREEN, "dash"),
        ("Target 2", levels["target_2"], PURPLE, "dash"),
    ):
        fig.add_hline(y=value, line_color=color, line_dash=dash, line_width=1.2, annotation_text=name)

    layout = _plotly_base_layout(f"Forward risk cone — {horizon}D", height=560)
    layout.update(
        {
            "xaxis": {"title": "Observed periods ← 0 → simulated periods", "gridcolor": GRID_COLOR, "zerolinecolor": GRID_COLOR},
            "yaxis": {"title": "Price", "gridcolor": GRID_COLOR, "zerolinecolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_terminal_distribution(summary: Mapping[str, Any], levels: Mapping[str, float]) -> go.Figure:
    returns = np.asarray(summary["final_returns"], dtype=float)
    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=returns * 100.0,
            nbinsx=50,
            name="Terminal return",
            marker={"color": "rgba(86,168,255,0.66)", "line": {"color": "rgba(255,255,255,0.10)", "width": 0.5}},
            hovertemplate="Return=%{x:.2f}%<br>Count=%{y}<extra></extra>",
        )
    )

    for name, value, color, dash in (
        ("VaR 5%", summary["var_5"] * 100.0, ORANGE, "dash"),
        ("ES 5%", summary["es_5"] * 100.0, RED, "dot"),
        ("Median", summary["median_return"] * 100.0, CYAN, "solid"),
    ):
        fig.add_vline(x=value, line_color=color, line_dash=dash, line_width=2, annotation_text=name)

    layout = _plotly_base_layout(f"Terminal return distribution — {summary['horizon']}D", height=460)
    layout.update(
        {
            "bargap": 0.03,
            "xaxis": {"title": "Terminal return (%)", "gridcolor": GRID_COLOR, "zerolinecolor": GRID_COLOR},
            "yaxis": {"title": "Frequency", "gridcolor": GRID_COLOR, "zerolinecolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_exceedance_curve(summary: Mapping[str, Any]) -> go.Figure:
    returns = np.asarray(summary["final_returns"], dtype=float)
    losses = np.maximum(-returns, 0.0)
    losses = np.sort(losses[losses > 0.0])

    fig = go.Figure()
    if losses.size:
        exceedance = (losses.size - np.arange(losses.size)) / losses.size
        fig.add_trace(
            go.Scatter(
                x=losses * 100.0,
                y=exceedance * 100.0,
                mode="lines",
                name="Loss exceedance",
                line={"color": RED, "width": 2.5},
                hovertemplate="Loss > %{x:.2f}%<br>Probability=%{y:.2f}%<extra></extra>",
            )
        )

    layout = _plotly_base_layout("Loss exceedance curve", height=460)
    layout.update(
        {
            "xaxis": {"title": "Loss threshold (%)", "gridcolor": GRID_COLOR},
            "yaxis": {"title": "Probability of exceeding threshold (%)", "type": "log", "gridcolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_barrier_race(summary: Mapping[str, Any]) -> go.Figure:
    labels = ("Target before stop", "Stop before target", "Same-step ambiguous", "Neither")
    values = (
        summary["prob_target_before_stop"],
        summary["prob_stop_before_target"],
        summary["prob_same_day_ambiguous"],
        summary["prob_neither"],
    )
    colors = (GREEN, RED, ORANGE, MUTED_COLOR)

    fig = go.Figure(
        go.Bar(
            x=list(labels),
            y=list(values),
            marker_color=list(colors),
            text=[f"{value:.1f}%" for value in values],
            textposition="outside",
            hovertemplate="%{x}<br>%{y:.2f}%<extra></extra>",
        )
    )
    layout = _plotly_base_layout(f"First-passage race — {summary['horizon']}D", height=420)
    layout.update(
        {
            "showlegend": False,
            "xaxis": {"title": "", "gridcolor": GRID_COLOR},
            "yaxis": {"title": "Probability (%)", "gridcolor": GRID_COLOR, "range": [0, max(values) * 1.25 + 1]},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_time_to_hit(summary: Mapping[str, Any]) -> go.Figure:
    stop_days = np.asarray(summary["stop_first_day_array"], dtype=float)
    target_days = np.asarray(summary["target_first_day_array"], dtype=float)
    stop_days = stop_days[np.isfinite(stop_days)]
    target_days = target_days[np.isfinite(target_days)]

    fig = go.Figure()
    if target_days.size:
        fig.add_trace(
            go.Histogram(
                x=target_days,
                name="Target first touch",
                opacity=0.65,
                marker_color=GREEN,
                nbinsx=max(10, summary["horizon"] // 2),
            )
        )
    if stop_days.size:
        fig.add_trace(
            go.Histogram(
                x=stop_days,
                name="Stop first touch",
                opacity=0.60,
                marker_color=RED,
                nbinsx=max(10, summary["horizon"] // 2),
            )
        )

    layout = _plotly_base_layout("First-touch time distribution", height=420)
    layout.update(
        {
            "barmode": "overlay",
            "xaxis": {"title": "Simulation step", "gridcolor": GRID_COLOR},
            "yaxis": {"title": "Frequency", "gridcolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_matrix_heatmap(matrix_df: pd.DataFrame, horizon: int, metric: str) -> go.Figure:
    metric_map = {
        "Expected return": ("expected_return", 100.0, "%"),
        "ES 5%": ("es_5", 100.0, "%"),
        "Barrier asymmetry": ("barrier_asymmetry_pp", 1.0, " pp"),
        "P(Target before stop)": ("prob_target_before_stop", 1.0, "%"),
        "Expected max drawdown": ("expected_max_drawdown", 100.0, "%"),
        "P(Ruin threshold)": ("prob_ruin", 1.0, "%"),
    }
    column, multiplier, suffix = metric_map[metric]
    subset = matrix_df[matrix_df["horizon"] == horizon].copy()
    pivot = subset.pivot(index="model", columns="scenario", values=column).reindex(index=list(MODELS), columns=list(SCENARIOS))
    z = pivot.to_numpy(dtype=float) * multiplier

    text = np.empty_like(z, dtype=object)
    for row in range(z.shape[0]):
        for col in range(z.shape[1]):
            value = z[row, col]
            text[row, col] = "N/A" if not np.isfinite(value) else f"{value:.2f}{suffix}"

    if metric in {"ES 5%", "Expected max drawdown"}:
        colorscale = "RdYlGn"
        reversescale = False
    elif metric in {"P(Ruin threshold)"}:
        colorscale = "RdYlGn"
        reversescale = True
    else:
        colorscale = "RdYlGn"
        reversescale = False

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=list(pivot.columns),
            y=list(pivot.index),
            colorscale=colorscale,
            reversescale=reversescale,
            text=text,
            texttemplate="%{text}",
            hovertemplate="Model=%{y}<br>Scenario=%{x}<br>Value=%{text}<extra></extra>",
            colorbar={"title": metric},
        )
    )
    layout = _plotly_base_layout(f"Model × scenario heatmap — {metric} — {horizon}D", height=560)
    layout.update(
        {
            "xaxis": {"title": "Scenario", "side": "top"},
            "yaxis": {"title": "Model", "automargin": True},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_convergence(convergence: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if convergence.empty:
        return fig

    fig.add_trace(
        go.Scatter(
            x=convergence["Simulations"],
            y=convergence["ES 5%"] * 100.0,
            mode="lines+markers",
            name="ES 5%",
            line={"color": RED, "width": 2.5},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=convergence["Simulations"],
            y=convergence["Target before stop"],
            mode="lines+markers",
            name="Target before stop",
            line={"color": GREEN, "width": 2.5},
            yaxis="y2",
        )
    )

    layout = _plotly_base_layout("Monte Carlo convergence", height=440)
    layout.update(
        {
            "xaxis": {"title": "Number of simulations", "type": "log", "gridcolor": GRID_COLOR},
            "yaxis": {"title": "ES 5% (%)", "gridcolor": GRID_COLOR},
            "yaxis2": {
                "title": "Target before stop (%)",
                "overlaying": "y",
                "side": "right",
                "showgrid": False,
            },
        }
    )
    fig.update_layout(**layout)
    return fig
