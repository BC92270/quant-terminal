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


def _plot_validation_leaderboard(leaderboard: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if leaderboard is None or leaderboard.empty:
        return fig
    data = leaderboard.sort_values("Governed rank score", ascending=False)
    status_colors = {
        "VALIDATED": GREEN,
        "WARNING": ORANGE,
        "INSUFFICIENT": MUTED_COLOR,
        "REJECTED": RED,
    }
    colors = [status_colors.get(str(value), BLUE) for value in data["Validation status"]]
    fig.add_trace(
        go.Bar(
            x=data["Governed rank score"],
            y=data["Model"],
            orientation="h",
            marker_color=colors,
            text=[f"#{int(rank)} · {status}" for rank, status in zip(data["Validation rank"], data["Validation status"])],
            textposition="auto",
            customdata=np.column_stack(
                [
                    data["Mean CRPS"],
                    data["Mean log score"],
                    data["VaR 5% exception rate"],
                    data["PIT KS p"],
                ]
            ),
            hovertemplate=(
                "%{y}<br>Governed rank score=%{x:.2f}"
                "<br>CRPS=%{customdata[0]:.5f}"
                "<br>Log score=%{customdata[1]:.3f}"
                "<br>VaR exceptions=%{customdata[2]:.2%}"
                "<br>PIT KS p=%{customdata[3]:.3f}<extra></extra>"
            ),
        )
    )
    layout = _plotly_base_layout("Walk-forward model leaderboard", height=max(420, 58 * len(data)))
    layout.update(
        {
            "showlegend": False,
            "xaxis": {"title": "Average metric rank + governance penalty", "gridcolor": GRID_COLOR},
            "yaxis": {"title": "", "automargin": True},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_pit_histogram(pit_histogram: pd.DataFrame, model: str) -> go.Figure:
    fig = go.Figure()
    subset = pit_histogram[pit_histogram["Model"] == model].copy() if not pit_histogram.empty else pd.DataFrame()
    if subset.empty:
        return fig
    fig.add_trace(
        go.Bar(
            x=subset["Bin midpoint"],
            y=subset["Frequency"],
            width=(subset["Bin right"] - subset["Bin left"]) * 0.90,
            marker_color=BLUE,
            name="Observed PIT frequency",
            hovertemplate="PIT bin=%{x:.2f}<br>Frequency=%{y:.2%}<extra></extra>",
        )
    )
    expected = 1.0 / max(len(subset), 1)
    fig.add_hline(y=expected, line_dash="dash", line_color=ORANGE, annotation_text="Uniform benchmark")
    layout = _plotly_base_layout(f"PIT histogram — {model}", height=420)
    layout.update(
        {
            "xaxis": {"title": "Probability integral transform", "range": [0, 1], "gridcolor": GRID_COLOR},
            "yaxis": {"title": "Frequency", "tickformat": ".0%", "gridcolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_quantile_calibration(calibration: pd.DataFrame, model: str) -> go.Figure:
    fig = go.Figure()
    subset = calibration[calibration["Model"] == model].sort_values("Nominal coverage") if not calibration.empty else pd.DataFrame()
    if subset.empty:
        return fig
    fig.add_trace(
        go.Scatter(
            x=subset["Nominal coverage"],
            y=subset["Observed coverage"],
            mode="lines+markers",
            name="Observed",
            line={"color": CYAN, "width": 3},
            hovertemplate="Nominal=%{x:.1%}<br>Observed=%{y:.1%}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[0.0, 1.0],
            y=[0.0, 1.0],
            mode="lines",
            name="Perfect calibration",
            line={"color": MUTED_COLOR, "dash": "dash", "width": 1.5},
            hoverinfo="skip",
        )
    )
    layout = _plotly_base_layout(f"Quantile calibration — {model}", height=420)
    layout.update(
        {
            "xaxis": {"title": "Nominal cumulative probability", "range": [0, 1], "tickformat": ".0%", "gridcolor": GRID_COLOR},
            "yaxis": {"title": "Observed cumulative frequency", "range": [0, 1], "tickformat": ".0%", "gridcolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_var_exception_timeline(forecasts: pd.DataFrame, model: str) -> go.Figure:
    fig = go.Figure()
    subset = forecasts[forecasts["model"] == model].sort_values("realization_date") if not forecasts.empty else pd.DataFrame()
    if subset.empty:
        return fig
    fig.add_trace(
        go.Scatter(
            x=subset["realization_date"],
            y=subset["realized_return"] * 100.0,
            mode="lines+markers",
            name="Realized return",
            line={"color": CYAN, "width": 2},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=subset["realization_date"],
            y=subset["var_5"] * 100.0,
            mode="lines",
            name="Forecast VaR 5%",
            line={"color": ORANGE, "width": 2, "dash": "dash"},
        )
    )
    exceptions = subset[subset["var_5_exception"]]
    if not exceptions.empty:
        fig.add_trace(
            go.Scatter(
                x=exceptions["realization_date"],
                y=exceptions["realized_return"] * 100.0,
                mode="markers",
                name="VaR exception",
                marker={"color": RED, "size": 11, "symbol": "x"},
            )
        )
    layout = _plotly_base_layout(f"VaR exception timeline — {model}", height=430)
    layout.update(
        {
            "xaxis": {"title": "Realization date", "gridcolor": GRID_COLOR},
            "yaxis": {"title": "Return (%)", "gridcolor": GRID_COLOR, "zerolinecolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_reliability(reliability: pd.DataFrame, model: str, event: str) -> go.Figure:
    fig = go.Figure()
    subset = reliability[(reliability["Model"] == model) & (reliability["Event"] == event)].copy() if not reliability.empty else pd.DataFrame()
    if subset.empty:
        return fig
    fig.add_trace(
        go.Scatter(
            x=subset["Forecast probability"],
            y=subset["Observed frequency"],
            mode="lines+markers+text",
            text=[f"n={int(value)}" for value in subset["Count"]],
            textposition="top center",
            name="Observed",
            line={"color": GREEN, "width": 3},
            hovertemplate="Forecast=%{x:.1%}<br>Observed=%{y:.1%}<br>%{text}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[0.0, 1.0],
            y=[0.0, 1.0],
            mode="lines",
            name="Perfect reliability",
            line={"color": MUTED_COLOR, "dash": "dash"},
            hoverinfo="skip",
        )
    )
    layout = _plotly_base_layout(f"Reliability diagram — {event} — {model}", height=420)
    layout.update(
        {
            "xaxis": {"title": "Forecast probability", "range": [0, 1], "tickformat": ".0%", "gridcolor": GRID_COLOR},
            "yaxis": {"title": "Observed frequency", "range": [0, 1], "tickformat": ".0%", "gridcolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_ensemble_weights(weight_table: pd.DataFrame) -> go.Figure:
    table = weight_table.sort_values("Weight", ascending=True).copy()
    labels = table["Model"].astype(str).tolist()
    values = (pd.to_numeric(table["Weight"], errors="coerce").fillna(0.0) * 100.0).tolist()
    low = (pd.to_numeric(table.get("Weight CI low", np.nan), errors="coerce") * 100.0).to_numpy(dtype=float)
    high = (pd.to_numeric(table.get("Weight CI high", np.nan), errors="coerce") * 100.0).to_numpy(dtype=float)
    central = np.asarray(values, dtype=float)
    error_plus = np.where(np.isfinite(high), np.maximum(high - central, 0.0), 0.0)
    error_minus = np.where(np.isfinite(low), np.maximum(central - low, 0.0), 0.0)
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker_color=CYAN,
            text=[f"{value:.1f}%" for value in values],
            textposition="outside",
            error_x={"type": "data", "array": error_plus, "arrayminus": error_minus, "visible": True},
            hovertemplate="%{y}<br>Weight=%{x:.2f}%<extra></extra>",
        )
    )
    layout = _plotly_base_layout("Validated ensemble weights", height=max(380, 80 + 42 * len(table)))
    layout.update(
        {
            "showlegend": False,
            "xaxis": {"title": "Weight (%)", "gridcolor": GRID_COLOR, "range": [0, max(values + [1.0]) * 1.25]},
            "yaxis": {"title": "", "gridcolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_ensemble_member_dispersion(member_summaries: pd.DataFrame, horizon: int) -> go.Figure:
    subset = member_summaries[member_summaries["Horizon"] == int(horizon)].copy()
    subset = subset.sort_values("Expected return", ascending=True)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=subset["Expected return"] * 100.0,
            y=subset["Model"],
            mode="markers",
            name="Expected return",
            marker={"size": 11, "color": CYAN},
            hovertemplate="%{y}<br>Expected return=%{x:.2f}%<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=subset["ES 5%"] * 100.0,
            y=subset["Model"],
            mode="markers",
            name="ES 5%",
            marker={"size": 11, "color": RED, "symbol": "diamond"},
            hovertemplate="%{y}<br>ES 5%%=%{x:.2f}%<extra></extra>",
        )
    )
    layout = _plotly_base_layout(f"Member distribution dispersion — {int(horizon)}D", height=max(400, 90 + 42 * len(subset)))
    layout.update(
        {
            "xaxis": {"title": "Return / tail metric (%)", "gridcolor": GRID_COLOR, "zerolinecolor": GRID_COLOR},
            "yaxis": {"title": "", "gridcolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_evt_threshold_stability(stability: pd.DataFrame) -> go.Figure:
    table = stability.copy()
    q = pd.to_numeric(table.get("Threshold quantile"), errors="coerce") * 100.0
    xi = pd.to_numeric(table.get("Shape xi"), errors="coerce")
    es = pd.to_numeric(table.get("ES 99% loss"), errors="coerce") * 100.0
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=q,
            y=xi,
            mode="lines+markers",
            name="Shape xi",
            marker={"color": CYAN, "size": 9},
            line={"color": CYAN},
            hovertemplate="Threshold=%{x:.1f}%<br>xi=%{y:.4f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=q,
            y=es,
            mode="lines+markers",
            name="EVT ES 99% loss",
            marker={"color": RED, "size": 9, "symbol": "diamond"},
            line={"color": RED},
            yaxis="y2",
            hovertemplate="Threshold=%{x:.1f}%<br>ES99 loss=%{y:.2f}%<extra></extra>",
        )
    )
    layout = _plotly_base_layout("EVT threshold stability", height=420)
    layout.update(
        {
            "xaxis": {"title": "Loss threshold quantile (%)", "gridcolor": GRID_COLOR},
            "yaxis": {"title": "GPD shape xi", "gridcolor": GRID_COLOR, "zerolinecolor": GRID_COLOR},
            "yaxis2": {
                "title": "EVT ES 99% loss (%)",
                "overlaying": "y",
                "side": "right",
                "gridcolor": "rgba(0,0,0,0)",
            },
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_stress_distribution_comparison(stress: Mapping[str, Any], horizon: int) -> go.Figure:
    baseline = np.asarray(stress["baseline_summaries_by_horizon"][int(horizon)]["final_returns"], dtype=float) * 100.0
    stressed = np.asarray(stress["summaries_by_horizon"][int(horizon)]["final_returns"], dtype=float) * 100.0
    combined = np.concatenate([baseline[np.isfinite(baseline)], stressed[np.isfinite(stressed)]])
    if combined.size == 0:
        combined = np.array([-1.0, 1.0])
    lo, hi = np.quantile(combined, [0.005, 0.995])
    bins = np.linspace(float(lo), float(hi), 55)
    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=baseline,
            xbins={"start": float(bins[0]), "end": float(bins[-1]), "size": float(bins[1] - bins[0])},
            histnorm="probability density",
            opacity=0.58,
            name="Baseline",
            marker_color=BLUE,
        )
    )
    fig.add_trace(
        go.Histogram(
            x=stressed,
            xbins={"start": float(bins[0]), "end": float(bins[-1]), "size": float(bins[1] - bins[0])},
            histnorm="probability density",
            opacity=0.58,
            name="Stressed",
            marker_color=RED,
        )
    )
    fig.update_layout(barmode="overlay")
    layout = _plotly_base_layout(f"Baseline vs stressed terminal distribution — {int(horizon)}D", height=460)
    layout.update(
        {
            "xaxis": {"title": "Terminal return (%)", "gridcolor": GRID_COLOR, "zerolinecolor": GRID_COLOR},
            "yaxis": {"title": "Probability density", "gridcolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_stress_delta(delta_table: pd.DataFrame, horizon: int) -> go.Figure:
    subset = delta_table[delta_table["Horizon"] == int(horizon)].copy()
    percent_metrics = {
        "Expected return",
        "VaR 5%",
        "ES 5%",
        "VaR 1%",
        "ES 1%",
        "Expected max drawdown",
    }
    values = []
    for _, row in subset.iterrows():
        value = float(row["Delta"])
        if row["Metric"] in percent_metrics:
            value *= 100.0
        values.append(value)
    colors = [GREEN if value > 0 else RED for value in values]
    fig = go.Figure(
        go.Bar(
            x=values,
            y=subset["Metric"].astype(str),
            orientation="h",
            marker_color=colors,
            text=[f"{value:+.2f}" for value in values],
            textposition="outside",
            hovertemplate="%{y}<br>Delta=%{x:+.3f}<extra></extra>",
        )
    )
    layout = _plotly_base_layout(f"Stress impact versus baseline — {int(horizon)}D", height=500)
    layout.update(
        {
            "showlegend": False,
            "xaxis": {"title": "Delta (percentage points / probability points)", "gridcolor": GRID_COLOR, "zerolinecolor": GRID_COLOR},
            "yaxis": {"title": "", "gridcolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_uncertainty_decomposition(decomposition: pd.DataFrame, horizon: int) -> go.Figure:
    row = decomposition[decomposition["Horizon"] == int(horizon)]
    fig = go.Figure()
    if not row.empty:
        values = [
            float(row.iloc[0]["Aleatory share"]) * 100.0,
            float(row.iloc[0]["Parameter share"]) * 100.0,
            float(row.iloc[0]["Model share"]) * 100.0,
        ]
        fig.add_trace(
            go.Bar(
                x=["Aleatory", "Parameter", "Model"],
                y=values,
                marker_color=[BLUE, ORANGE, PURPLE],
                text=[f"{value:.2f}%" for value in values],
                textposition="outside",
                hovertemplate="%{x}<br>Variance share=%{y:.2f}%<extra></extra>",
            )
        )
    layout = _plotly_base_layout(f"Predictive-variance decomposition — {horizon}D", height=420)
    layout.update(
        {
            "showlegend": False,
            "xaxis": {"title": "Uncertainty source", "gridcolor": GRID_COLOR},
            "yaxis": {"title": "Share of total predictive variance (%)", "gridcolor": GRID_COLOR, "range": [0, 105]},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_uncertainty_distribution(result: Mapping[str, Any], horizon: int) -> go.Figure:
    total = np.asarray(result["summaries_by_horizon"][int(horizon)]["final_returns"], dtype=float) * 100.0
    fixed = np.asarray(result["fixed_summaries_by_horizon"][int(horizon)]["final_returns"], dtype=float) * 100.0
    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=fixed,
            histnorm="probability density",
            nbinsx=55,
            opacity=0.55,
            name="Fixed parameters",
            marker_color=BLUE,
            hovertemplate="Return=%{x:.2f}%<br>Density=%{y:.4f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Histogram(
            x=total,
            histnorm="probability density",
            nbinsx=55,
            opacity=0.52,
            name="Parameter + model uncertainty",
            marker_color=ORANGE,
            hovertemplate="Return=%{x:.2f}%<br>Density=%{y:.4f}<extra></extra>",
        )
    )
    layout = _plotly_base_layout(f"Fixed vs uncertainty-integrated distribution — {horizon}D", height=460)
    layout.update(
        {
            "barmode": "overlay",
            "xaxis": {"title": "Terminal return (%)", "gridcolor": GRID_COLOR, "zerolinecolor": GRID_COLOR},
            "yaxis": {"title": "Probability density", "gridcolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_uncertainty_parameter_intervals(
    interval_table: pd.DataFrame,
    parameter: str,
) -> go.Figure:
    subset = interval_table[interval_table["Parameter"] == parameter].copy()
    fig = go.Figure()
    if not subset.empty:
        unit = str(subset.iloc[0].get("Unit", "number"))
        multiplier = 100.0 if unit == "rate" else 1.0
        median = subset["Median"].to_numpy(float) * multiplier
        low = subset["CI low"].to_numpy(float) * multiplier
        high = subset["CI high"].to_numpy(float) * multiplier
        fig.add_trace(
            go.Scatter(
                x=median,
                y=subset["Model"].astype(str),
                mode="markers",
                marker={"size": 11, "color": CYAN},
                error_x={
                    "type": "data",
                    "symmetric": False,
                    "array": high - median,
                    "arrayminus": median - low,
                    "color": ORANGE,
                    "thickness": 1.8,
                },
                hovertemplate="%{y}<br>Median=%{x:.4f}<extra></extra>",
            )
        )
    suffix = " (%)" if (not subset.empty and str(subset.iloc[0].get("Unit")) == "rate") else ""
    layout = _plotly_base_layout(f"Bootstrap parameter intervals — {parameter}", height=max(360, 75 * max(len(subset), 1)))
    layout.update(
        {
            "showlegend": False,
            "xaxis": {"title": parameter + suffix, "gridcolor": GRID_COLOR, "zerolinecolor": GRID_COLOR},
            "yaxis": {"title": "Model", "gridcolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_uncertainty_convergence(convergence: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if isinstance(convergence, pd.DataFrame) and not convergence.empty:
        fig.add_trace(
            go.Scatter(
                x=convergence["Draws"],
                y=convergence["Expected return CI width"] * 100.0,
                mode="lines+markers",
                name="Expected-return CI width",
                line={"color": CYAN, "width": 2.5},
            )
        )
        fig.add_trace(
            go.Scatter(
                x=convergence["Draws"],
                y=convergence["ES 5% CI width"] * 100.0,
                mode="lines+markers",
                name="ES 5% CI width",
                line={"color": RED, "width": 2.5},
            )
        )
    layout = _plotly_base_layout("Bootstrap-draw convergence", height=420)
    layout.update(
        {
            "xaxis": {"title": "Successful parameter draws", "gridcolor": GRID_COLOR},
            "yaxis": {"title": "Bootstrap interval width (percentage points)", "gridcolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_option_call_projection(result: Mapping[str, Any]) -> go.Figure:
    table = result["synthetic_call_curve"].sort_values("strike")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=table["strike"],
            y=table["observed_call_equivalent"],
            mode="markers",
            name="Observed call-equivalent",
            marker={"color": ORANGE, "size": 7, "opacity": 0.75},
            hovertemplate="Strike=%{x:.2f}<br>Observed=%{y:.4f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=table["strike"],
            y=table["projected_call"],
            mode="lines+markers",
            name="Arbitrage-free projection",
            line={"color": CYAN, "width": 2.5},
            marker={"size": 5},
            hovertemplate="Strike=%{x:.2f}<br>Projected=%{y:.4f}<extra></extra>",
        )
    )
    fig.add_vline(x=float(result["forward"]), line_color=PURPLE, line_dash="dash", annotation_text="Forward")
    layout = _plotly_base_layout("European call-equivalent curve", height=440)
    layout.update(
        {
            "xaxis": {"title": "Strike", "gridcolor": GRID_COLOR},
            "yaxis": {"title": "Discounted option price", "gridcolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_risk_neutral_density(result: Mapping[str, Any]) -> go.Figure:
    table = result.get("display_density_table", result["density_table"]).sort_values("strike")
    metrics = result["risk_neutral_metrics"]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=table["strike"],
            y=table["density"],
            mode="lines",
            fill="tozeroy",
            name="Risk-neutral density Q",
            line={"color": PURPLE, "width": 2.5},
            fillcolor="rgba(156,140,255,0.18)",
            hovertemplate="Terminal price=%{x:.2f}<br>Density=%{y:.6f}<extra></extra>",
        )
    )
    for name, value, color in (
        ("Spot", result["spot"], "#f8fafc"),
        ("Forward", result["forward"], CYAN),
        ("Q median", metrics["median_terminal_price"], GREEN),
        ("Q VaR 5%", result["spot"] * (1.0 + metrics["q_var_5"]), ORANGE),
    ):
        fig.add_vline(x=float(value), line_color=color, line_dash="dash", annotation_text=name)
    layout = _plotly_base_layout(f"Risk-neutral terminal density — {result['calendar_days']} calendar days", height=440)
    layout.update(
        {
            "xaxis": {"title": "Terminal price", "gridcolor": GRID_COLOR},
            "yaxis": {"title": "Probability density", "gridcolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_implied_volatility_smile(result: Mapping[str, Any]) -> go.Figure:
    table = result["clean_chain"].copy()
    if "smile_eligible" in table.columns:
        table = table[table["smile_eligible"].astype(bool)]
    else:
        table = table[np.isfinite(table["effective_iv"]) & (table["effective_iv"] > 0.0)]
    fig = go.Figure()
    for option_type, color in (("call", BLUE), ("put", RED)):
        subset = table[table["option_type"] == option_type]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=subset["strike"],
                y=subset["effective_iv"] * 100.0,
                mode="markers",
                name=option_type.title(),
                marker={
                    "color": color,
                    "size": np.clip(5.0 + np.log1p(subset["open_interest"].to_numpy(dtype=float)), 5.0, 13.0),
                    "opacity": 0.72,
                },
                customdata=np.column_stack(
                    [subset["mid"].to_numpy(dtype=float), subset["relative_spread"].fillna(np.nan).to_numpy(dtype=float)]
                ),
                hovertemplate="Strike=%{x:.2f}<br>IV=%{y:.2f}%<br>Mid=%{customdata[0]:.4f}<br>Rel spread=%{customdata[1]:.2%}<extra></extra>",
            )
        )
    fig.add_vline(x=float(result["forward"]), line_color=PURPLE, line_dash="dash", annotation_text="Forward")
    layout = _plotly_base_layout("Midpoint-recomputed OTM implied-volatility smile", height=440)
    layout.update(
        {
            "xaxis": {"title": "Strike", "gridcolor": GRID_COLOR},
            "yaxis": {"title": "Implied volatility (%)", "gridcolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_physical_vs_risk_neutral(result: Mapping[str, Any]) -> go.Figure:
    physical = result.get("physical_comparison", {})
    density = result.get("display_density_table", result["density_table"]).sort_values("strike")
    spot = float(result["spot"])
    fig = go.Figure()
    if physical.get("available"):
        returns = np.asarray(physical["returns"], dtype=float) * 100.0
        fig.add_trace(
            go.Histogram(
                x=returns,
                histnorm="probability density",
                nbinsx=45,
                name=f"Physical P ({physical['horizon']}D)",
                marker={"color": "rgba(86,168,255,0.46)"},
                opacity=0.65,
                hovertemplate="P return=%{x:.2f}%<br>Density=%{y:.5f}<extra></extra>",
            )
        )
    q_returns = (density["strike"].to_numpy(dtype=float) / spot - 1.0) * 100.0
    q_density_return = density["density"].to_numpy(dtype=float) * spot / 100.0
    fig.add_trace(
        go.Scatter(
            x=q_returns,
            y=q_density_return,
            mode="lines",
            name="Risk-neutral Q",
            line={"color": PURPLE, "width": 2.8},
            hovertemplate="Q return=%{x:.2f}%<br>Density=%{y:.5f}<extra></extra>",
        )
    )
    layout = _plotly_base_layout("Physical P versus option-implied Q", height=440)
    layout.update(
        {
            "barmode": "overlay",
            "xaxis": {"title": "Terminal return (%)", "gridcolor": GRID_COLOR},
            "yaxis": {"title": "Probability density", "gridcolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_volatility_surface(result: Mapping[str, Any]) -> go.Figure:
    table = result["surface_table"].copy()
    piv = table.pivot(index="dte", columns="log_moneyness", values="projected_iv").sort_index()
    x = piv.columns.to_numpy(dtype=float)
    y = piv.index.to_numpy(dtype=float)
    z = piv.to_numpy(dtype=float) * 100.0
    fig = go.Figure(
        data=[
            go.Surface(
                x=x,
                y=y,
                z=z,
                colorscale="Viridis",
                colorbar={"title": "IV (%)"},
                hovertemplate="k=%{x:.3f}<br>DTE=%{y:.0f}<br>IV=%{z:.2f}%<extra></extra>",
            )
        ]
    )
    layout = _plotly_base_layout("Calendar-projected implied-volatility surface", height=600)
    layout.update(
        {
            "scene": {
                "xaxis": {"title": "Log-moneyness log(K/F)", "gridcolor": GRID_COLOR},
                "yaxis": {"title": "Days to expiry", "gridcolor": GRID_COLOR},
                "zaxis": {"title": "Implied volatility (%)", "gridcolor": GRID_COLOR},
                "bgcolor": PLOT_BG,
            },
            "hovermode": "closest",
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_surface_smile_slices(result: Mapping[str, Any]) -> go.Figure:
    table = result["surface_table"].copy()
    points = result.get("smile_points", pd.DataFrame())
    fig = go.Figure()
    palette = [CYAN, BLUE, GREEN, ORANGE, RED, PURPLE, "#f0c75e", "#8bd3dd"]
    for idx, (expiration, group) in enumerate(table.groupby("expiration", sort=False)):
        group = group.sort_values("log_moneyness")
        color = palette[idx % len(palette)]
        dte = int(group["dte"].iloc[0])
        fig.add_trace(
            go.Scatter(
                x=group["log_moneyness"],
                y=group["projected_iv"] * 100.0,
                mode="lines",
                name=f"{dte}D projected",
                line={"color": color, "width": 2.3},
                hovertemplate="k=%{x:.3f}<br>IV=%{y:.2f}%<extra></extra>",
            )
        )
        if isinstance(points, pd.DataFrame) and not points.empty:
            raw = points[points["expiration"] == expiration]
            if not raw.empty:
                fig.add_trace(
                    go.Scatter(
                        x=raw["log_moneyness"],
                        y=raw["effective_iv"] * 100.0,
                        mode="markers",
                        name=f"{dte}D quotes",
                        marker={"color": color, "size": 6, "opacity": 0.45},
                        showlegend=False,
                        hovertemplate="k=%{x:.3f}<br>Quote IV=%{y:.2f}%<extra></extra>",
                    )
                )
    layout = _plotly_base_layout("SVI smile slices — quotes versus calendar-projected surface", height=500)
    layout.update(
        {
            "xaxis": {"title": "Log-moneyness log(K/F)", "gridcolor": GRID_COLOR, "zerolinecolor": GRID_COLOR},
            "yaxis": {"title": "Implied volatility (%)", "gridcolor": GRID_COLOR, "zerolinecolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_surface_term_structure(result: Mapping[str, Any]) -> go.Figure:
    term = result["term_structure"].sort_values("dte")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=term["dte"],
            y=term["atm_iv_projected"] * 100.0,
            mode="lines+markers",
            name="ATM projected IV",
            line={"color": CYAN, "width": 3},
            hovertemplate="DTE=%{x}<br>ATM IV=%{y:.2f}%<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=term["dte"],
            y=term["model_free_vol"] * 100.0,
            mode="lines+markers",
            name="Model-free vol",
            line={"color": ORANGE, "width": 2, "dash": "dash"},
            hovertemplate="DTE=%{x}<br>MF vol=%{y:.2f}%<extra></extra>",
        )
    )
    layout = _plotly_base_layout("ATM volatility term structure", height=430)
    layout.update(
        {
            "xaxis": {"title": "Days to expiry", "gridcolor": GRID_COLOR},
            "yaxis": {"title": "Annualized volatility (%)", "gridcolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_surface_calendar_adjustment(result: Mapping[str, Any]) -> go.Figure:
    table = result["surface_table"].copy()
    piv = table.pivot(index="dte", columns="log_moneyness", values="calendar_adjustment").sort_index()
    fig = go.Figure(
        data=[
            go.Heatmap(
                x=piv.columns.to_numpy(dtype=float),
                y=piv.index.to_numpy(dtype=float),
                z=piv.to_numpy(dtype=float) * 10_000.0,
                colorscale="RdBu",
                zmid=0.0,
                colorbar={"title": "Δ total variance (bp²)"},
                hovertemplate="k=%{x:.3f}<br>DTE=%{y:.0f}<br>Adjustment=%{z:.2f} bp²<extra></extra>",
            )
        ]
    )
    layout = _plotly_base_layout("Calendar-arbitrage projection adjustment", height=430)
    layout.update(
        {
            "xaxis": {"title": "Log-moneyness log(K/F)", "gridcolor": GRID_COLOR},
            "yaxis": {"title": "Days to expiry", "gridcolor": GRID_COLOR},
        }
    )
    fig.update_layout(**layout)
    return fig


def _plot_calibration_weight_matrix(result: Mapping[str, Any]) -> go.Figure:
    table = result.get("weight_matrix")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Calibration-weight allocation", height=380))
        return fig
    frame = table.copy()
    expiries = frame.pop("expiration").astype(str).tolist()
    columns = [str(value) for value in frame.columns]
    z = frame.to_numpy(dtype=float) * 100.0
    fig.add_trace(
        go.Heatmap(
            z=z,
            x=columns,
            y=expiries,
            colorscale="Blues",
            colorbar={"title": "Weight (%)"},
            text=np.round(z, 2),
            texttemplate="%{text:.2f}%",
            hovertemplate="Expiry=%{y}<br>Bucket=%{x}<br>Weight=%{z:.2f}%<extra></extra>",
        )
    )
    layout = _plotly_base_layout("Calibration-weight allocation by expiry and moneyness", height=390)
    layout.update({"xaxis": {"title": "Log-moneyness bucket", "type": "category"}, "yaxis": {"title": "Expiration", "type": "category", "categoryorder": "array", "categoryarray": expiries}})
    fig.update_layout(**layout)
    return fig


def _plot_calibration_dataset_coverage(result: Mapping[str, Any]) -> go.Figure:
    dataset = result.get("dataset")
    fig = go.Figure()
    if not isinstance(dataset, pd.DataFrame) or dataset.empty:
        fig.update_layout(**_plotly_base_layout("Calibration dataset coverage", height=420))
        return fig
    role_style = {
        "TRAIN": (GREEN, "circle"),
        "HOLDOUT": (ORANGE, "diamond"),
        "EXCLUDED": (MUTED_COLOR, "x"),
    }
    for role, group in dataset.groupby("sample_role", sort=False):
        color, symbol = role_style.get(str(role), (MUTED_COLOR, "circle"))
        size = 7 + 35 * np.sqrt(np.maximum(group.get("calibration_weight", 0.0).to_numpy(dtype=float), 0.0))
        fig.add_trace(
            go.Scatter(
                x=group["log_moneyness"],
                y=group["dte"],
                mode="markers",
                name=str(role),
                marker={"color": color, "symbol": symbol, "size": size, "opacity": 0.80, "line": {"width": 0.5, "color": "rgba(255,255,255,0.25)"}},
                customdata=np.column_stack([
                    group["expiration"].astype(str),
                    group["strike"].astype(float),
                    group["target_iv"].astype(float) * 100.0,
                    group.get("calibration_weight", 0.0).astype(float) * 100.0,
                ]),
                hovertemplate="Expiry=%{customdata[0]}<br>DTE=%{y}<br>log(K/F)=%{x:.3f}<br>Strike=%{customdata[1]:.2f}<br>Target IV=%{customdata[2]:.2f}%<br>Weight=%{customdata[3]:.3f}%<extra></extra>",
            )
        )
    layout = _plotly_base_layout("Training, holdout and excluded quote coverage", height=430)
    layout.update({"xaxis": {"title": "Log-moneyness log(K/F)"}, "yaxis": {"title": "Days to expiry"}})
    fig.update_layout(**layout)
    return fig


def _plot_event_variance_adjustments(result: Mapping[str, Any]) -> go.Figure:
    events = result.get("event_adjustments")
    fig = go.Figure()
    if not isinstance(events, pd.DataFrame) or events.empty:
        fig.update_layout(**_plotly_base_layout("Event-variance adjustments", height=360))
        return fig
    frame = events.copy()
    labels = frame["window_start"].astype(str) + " → " + frame["window_end"].astype(str)
    event_variance = frame["estimated_event_variance"].to_numpy(dtype=float) * 10_000.0
    expected = frame["expected_continuous_increment"].to_numpy(dtype=float) * 10_000.0
    fig.add_trace(go.Bar(x=labels, y=expected, name="Continuous variance baseline", marker={"color": BLUE}))
    fig.add_trace(go.Bar(x=labels, y=event_variance, name="Estimated discrete event variance", marker={"color": ORANGE}))
    layout = _plotly_base_layout("Estimated event variance by adjacent maturity window", height=370)
    layout.update({"barmode": "stack", "xaxis": {"title": "Maturity window"}, "yaxis": {"title": "Variance (bp²)"}})
    fig.update_layout(**layout)
    return fig



def _plot_heston_fit_smiles(result: Mapping[str, Any]) -> go.Figure:
    table = result.get("fit_table")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Heston fit — target versus model IV", height=450))
        return fig
    for expiration, group in table.groupby("expiration", sort=True):
        group = group.sort_values("log_moneyness")
        train = group[group["sample_role"] == "TRAIN"]
        holdout = group[group["sample_role"] == "HOLDOUT"]
        if not train.empty:
            fig.add_trace(go.Scatter(
                x=train["log_moneyness"], y=train["target_iv"] * 100.0,
                mode="markers", name=f"{expiration} target",
                marker={"size": 6, "opacity": 0.55},
                legendgroup=str(expiration),
                hovertemplate="Expiry=%{text}<br>log(K/F)=%{x:.3f}<br>Target IV=%{y:.2f}%<extra></extra>",
                text=[str(expiration)] * len(train),
            ))
            fig.add_trace(go.Scatter(
                x=group["log_moneyness"], y=group["heston_iv"] * 100.0,
                mode="lines", name=f"{expiration} Heston",
                line={"width": 2}, legendgroup=str(expiration),
                hovertemplate="Expiry=%{text}<br>log(K/F)=%{x:.3f}<br>Heston IV=%{y:.2f}%<extra></extra>",
                text=[str(expiration)] * len(group),
            ))
        if not holdout.empty:
            fig.add_trace(go.Scatter(
                x=holdout["log_moneyness"], y=holdout["target_iv"] * 100.0,
                mode="markers", name=f"{expiration} holdout",
                marker={"size": 8, "symbol": "diamond-open"},
                legendgroup=str(expiration), showlegend=False,
                hovertemplate="Holdout<br>Expiry=%{text}<br>log(K/F)=%{x:.3f}<br>Target IV=%{y:.2f}%<extra></extra>",
                text=[str(expiration)] * len(holdout),
            ))
    layout = _plotly_base_layout("Heston fit — target versus model IV", height=500)
    layout.update({"xaxis": {"title": "Log-moneyness log(K/F)", "gridcolor": GRID_COLOR}, "yaxis": {"title": "Implied volatility (%)", "gridcolor": GRID_COLOR}, "legend": {"orientation": "h"}})
    fig.update_layout(**layout)
    return fig


def _plot_heston_residual_heatmap(result: Mapping[str, Any]) -> go.Figure:
    table = result.get("fit_table")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Heston IV residuals", height=420))
        return fig
    frame = table.copy()
    if "moneyness_bucket" not in frame:
        frame["moneyness_bucket"] = pd.cut(frame["log_moneyness"], [-np.inf, -0.20, -0.08, 0.08, 0.20, np.inf], labels=["Left wing", "Put shoulder", "ATM", "Call shoulder", "Right wing"])
    pivot = frame.pivot_table(index="expiration", columns="moneyness_bucket", values="iv_error", aggfunc="mean", observed=False)
    order = frame[["expiration", "dte"]].drop_duplicates().sort_values("dte")["expiration"].astype(str).tolist()
    pivot = pivot.reindex(order)
    z = pivot.to_numpy(dtype=float) * 100.0
    fig.add_trace(go.Heatmap(
        z=z, x=[str(value) for value in pivot.columns], y=pivot.index.astype(str),
        colorscale="RdBu", zmid=0.0, colorbar={"title": "IV error (pp)"},
        text=np.round(z, 2), texttemplate="%{text:+.2f}",
        hovertemplate="Expiry=%{y}<br>Bucket=%{x}<br>Mean IV error=%{z:+.2f} pp<extra></extra>",
    ))
    layout = _plotly_base_layout("Heston IV residuals by maturity and moneyness", height=420)
    layout.update({"xaxis": {"title": "Moneyness bucket", "type": "category"}, "yaxis": {"title": "Expiration", "type": "category", "categoryorder": "array", "categoryarray": order}})
    fig.update_layout(**layout)
    return fig


def _plot_heston_multistart(result: Mapping[str, Any]) -> go.Figure:
    table = result.get("multi_start_solutions")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Heston multi-start objective", height=360))
        return fig
    frame = table[np.isfinite(table["cost"])].copy().sort_values("cost")
    if "relative_cost_bps" not in frame:
        best = max(float(frame["cost"].min()), 1e-16)
        frame["relative_cost_bps"] = (frame["cost"] / best - 1.0) * 10_000.0
    y = np.maximum(frame["relative_cost_bps"].to_numpy(dtype=float), 0.0)
    fig.add_trace(go.Bar(
        x=frame["start_id"].astype(str), y=y,
        marker={"color": np.where(frame["success"].astype(bool), GREEN, RED)},
        customdata=np.column_stack([frame["cost"], frame["kappa"], frame["theta"], frame["sigma_v"], frame["rho"], frame["v0"]]),
        hovertemplate="Start=%{x}<br>Relative deterioration=%{y:.3f} bp of best cost<br>Raw cost=%{customdata[0]:.8g}<br>κ=%{customdata[1]:.4f}<br>θ=%{customdata[2]:.4f}<br>σv=%{customdata[3]:.4f}<br>ρ=%{customdata[4]:.4f}<br>v0=%{customdata[5]:.4f}<extra></extra>",
    ))
    layout = _plotly_base_layout("Heston multi-start objective — relative to best", height=360)
    layout.update({"xaxis": {"title": "Start ID", "type": "category"}, "yaxis": {"title": "Objective deterioration (bp of best cost)", "gridcolor": GRID_COLOR, "type": "linear"}})
    fig.update_layout(**layout)
    return fig


def _plot_heston_parameter_position(result: Mapping[str, Any]) -> go.Figure:
    table = result.get("parameter_table")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Heston parameter position within bounds", height=360))
        return fig
    frame = table.copy()
    normalized = (frame["estimate"] - frame["lower_bound"]) / np.maximum(frame["upper_bound"] - frame["lower_bound"], 1e-12)
    fig.add_trace(go.Bar(
        x=frame["parameter"], y=normalized * 100.0,
        marker={"color": np.where(frame["near_bound"].astype(bool), ORANGE, CYAN)},
        customdata=np.column_stack([frame["estimate"], frame["lower_bound"], frame["upper_bound"]]),
        hovertemplate="%{x}<br>Estimate=%{customdata[0]:.6f}<br>Bounds=[%{customdata[1]:.6f}, %{customdata[2]:.6f}]<br>Relative position=%{y:.1f}%<extra></extra>",
    ))
    layout = _plotly_base_layout("Heston parameter position within calibration bounds", height=360)
    layout.update({"xaxis": {"title": "Parameter"}, "yaxis": {"title": "Position inside bound interval (%)", "range": [0, 100], "gridcolor": GRID_COLOR}})
    fig.update_layout(**layout)
    return fig


def _plot_heston_q_spot_fan(result: Mapping[str, Any], selected_dte: int) -> go.Figure:
    table = result.get("path_quantiles")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Heston Q spot distribution", height=460))
        return fig
    frame = table[table["day"] <= float(selected_dte) + 1e-9].copy()
    x = frame["day"]
    fig.add_trace(go.Scatter(x=x, y=frame["spot_p05"], mode="lines", line={"width": 0}, showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=frame["spot_p95"], mode="lines", line={"width": 0}, fill="tonexty", fillcolor="rgba(86,168,255,0.13)", name="P5–P95", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=frame["spot_p25"], mode="lines", line={"width": 0}, showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=frame["spot_p75"], mode="lines", line={"width": 0}, fill="tonexty", fillcolor="rgba(83,214,232,0.22)", name="P25–P75", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=frame["spot_p50"], mode="lines", name="Median", line={"color": CYAN, "width": 2.5}))
    fig.add_trace(go.Scatter(x=x, y=frame["spot_mean"], mode="lines", name="Q mean", line={"color": GREEN, "width": 2}))
    fig.add_trace(go.Scatter(x=x, y=frame["forward_target"], mode="lines", name="Governed forward", line={"color": ORANGE, "width": 2, "dash": "dash"}))
    layout = _plotly_base_layout(f"Heston Q spot cone — {selected_dte} calendar days", height=480)
    layout.update({"xaxis": {"title": "Calendar days", "gridcolor": GRID_COLOR}, "yaxis": {"title": "Spot price", "gridcolor": GRID_COLOR}})
    fig.update_layout(**layout)
    return fig


def _plot_heston_q_variance_fan(result: Mapping[str, Any], selected_dte: int) -> go.Figure:
    table = result.get("variance_diagnostics")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Heston variance process", height=460))
        return fig
    frame = table[table["day"] <= float(selected_dte) + 1e-9].copy()
    x = frame["day"]
    fig.add_trace(go.Scatter(x=x, y=frame["variance_p05"] * 100.0, mode="lines", line={"width": 0}, showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=frame["variance_p95"] * 100.0, mode="lines", line={"width": 0}, fill="tonexty", fillcolor="rgba(156,140,255,0.15)", name="P5–P95", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=frame["variance_p50"] * 100.0, mode="lines", name="Median variance", line={"color": PURPLE, "width": 2.5}))
    fig.add_trace(go.Scatter(x=x, y=frame["mean_variance"] * 100.0, mode="lines", name="Simulated mean", line={"color": CYAN, "width": 2}))
    fig.add_trace(go.Scatter(x=x, y=frame["theoretical_mean_variance"] * 100.0, mode="lines", name="Heston conditional mean", line={"color": ORANGE, "width": 2, "dash": "dash"}))
    layout = _plotly_base_layout(f"Heston variance process — {selected_dte} calendar days", height=480)
    layout.update({"xaxis": {"title": "Calendar days", "gridcolor": GRID_COLOR}, "yaxis": {"title": "Variance × 100", "gridcolor": GRID_COLOR}})
    fig.update_layout(**layout)
    return fig


def _plot_heston_q_terminal_distribution(result: Mapping[str, Any], selected_dte: int) -> go.Figure:
    samples = result.get("terminal_spot_samples")
    distribution = result.get("distribution_summary")
    fig = go.Figure()
    if not isinstance(samples, pd.DataFrame) or str(selected_dte) not in samples:
        fig.update_layout(**_plotly_base_layout("Heston Q terminal distribution", height=430))
        return fig
    values = samples[str(selected_dte)].to_numpy(dtype=float)
    fig.add_trace(go.Histogram(x=values, histnorm="probability density", nbinsx=70, name="Heston Q terminal spot", marker={"color": "rgba(86,168,255,0.58)"}))
    if isinstance(distribution, pd.DataFrame) and not distribution.empty:
        row = distribution.loc[distribution["dte"] == int(selected_dte)]
        if not row.empty:
            row = row.iloc[0]
            for label, value, color, dash in (
                ("Forward", row["forward_target"], ORANGE, "dash"),
                ("Mean", row["terminal_mean"], GREEN, "solid"),
            ):
                fig.add_vline(x=float(value), line_color=color, line_dash=dash, line_width=2, annotation_text=label)
    layout = _plotly_base_layout(f"Risk-neutral terminal spot distribution — {selected_dte}D", height=430)
    layout.update({"xaxis": {"title": "Terminal spot", "gridcolor": GRID_COLOR}, "yaxis": {"title": "Probability density", "gridcolor": GRID_COLOR}, "bargap": 0.02})
    fig.update_layout(**layout)
    return fig


def _plot_heston_mc_fourier_prices(result: Mapping[str, Any]) -> go.Figure:
    table = result.get("pricing_validation")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Monte Carlo versus Fourier prices", height=430))
        return fig
    for role, color in (("TRAIN", BLUE), ("HOLDOUT", ORANGE)):
        subset = table[table["sample_role"].astype(str) == role]
        if subset.empty:
            continue
        fig.add_trace(go.Scatter(
            x=subset["fourier_price"], y=subset["mc_price"], mode="markers", name=role,
            marker={"size": 7, "color": color, "opacity": 0.75},
            customdata=np.column_stack([subset["dte"], subset["strike"], subset["mc_standard_error"], subset["mc_fourier_z_score"]]),
            hovertemplate="DTE=%{customdata[0]}<br>Strike=%{customdata[1]:.2f}<br>Fourier=%{x:.4f}<br>MC=%{y:.4f}<br>MC SE=%{customdata[2]:.5f}<br>z=%{customdata[3]:.2f}<extra></extra>",
        ))
    low = float(np.nanmin(np.concatenate([table["fourier_price"].to_numpy(dtype=float), table["mc_price"].to_numpy(dtype=float)])))
    high = float(np.nanmax(np.concatenate([table["fourier_price"].to_numpy(dtype=float), table["mc_price"].to_numpy(dtype=float)])))
    fig.add_trace(go.Scatter(x=[low, high], y=[low, high], mode="lines", name="45°", line={"color": GREEN, "dash": "dash"}))
    layout = _plotly_base_layout("Heston Monte Carlo versus Fourier prices", height=430)
    layout.update({"xaxis": {"title": "Fourier Heston price", "gridcolor": GRID_COLOR}, "yaxis": {"title": "Monte Carlo price", "gridcolor": GRID_COLOR}})
    fig.update_layout(**layout)
    return fig


def _plot_heston_mc_iv_residuals(result: Mapping[str, Any]) -> go.Figure:
    table = result.get("pricing_validation")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Monte Carlo IV residuals", height=430))
        return fig
    pivot = table.pivot_table(index="expiration", columns="moneyness_bucket", values="mc_fourier_iv_error", aggfunc="mean", observed=False)
    order = table[["expiration", "dte"]].drop_duplicates().sort_values("dte")["expiration"].astype(str).tolist()
    pivot = pivot.reindex(order)
    z = pivot.to_numpy(dtype=float) * 100.0
    fig.add_trace(go.Heatmap(
        z=z, x=[str(value) for value in pivot.columns], y=pivot.index.astype(str), colorscale="RdBu", zmid=0.0,
        colorbar={"title": "MC − Fourier IV (pp)"}, text=np.round(z, 2), texttemplate="%{text:+.2f}",
        hovertemplate="Expiry=%{y}<br>Bucket=%{x}<br>MC − Fourier IV=%{z:+.2f} pp<extra></extra>",
    ))
    layout = _plotly_base_layout("Monte Carlo versus Fourier IV residuals", height=430)
    layout.update({"xaxis": {"title": "Moneyness bucket", "type": "category"}, "yaxis": {"title": "Expiration", "type": "category", "categoryorder": "array", "categoryarray": order}})
    fig.update_layout(**layout)
    return fig


def _plot_heston_simulation_convergence(result: Mapping[str, Any]) -> go.Figure:
    table = result.get("convergence")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Heston simulation convergence", height=380))
        return fig
    x = table["steps_per_year"].to_numpy(dtype=float)
    mean = table["price_rmse_mean"].to_numpy(dtype=float)
    low = table["price_rmse_ci_low"].to_numpy(dtype=float)
    high = table["price_rmse_ci_high"].to_numpy(dtype=float)
    fig.add_trace(go.Scatter(
        x=x,
        y=mean,
        mode="lines+markers",
        name="Replicated MC–Fourier RMSE",
        line={"color": CYAN, "width": 2.4},
        error_y={
            "type": "data",
            "symmetric": False,
            "array": np.maximum(high - mean, 0.0),
            "arrayminus": np.maximum(mean - low, 0.0),
            "color": CYAN,
            "thickness": 1.3,
        },
    ))
    fig.add_trace(go.Scatter(
        x=x,
        y=table["mean_mc_standard_error"],
        mode="lines+markers",
        name="Mean MC standard error",
        line={"color": ORANGE, "width": 2},
        yaxis="y2",
    ))
    status = str(result.get("convergence_diagnostic", {}).get("status", "NOT RUN"))
    layout = _plotly_base_layout(f"Replicated time-step convergence — {status}", height=380)
    layout.update({
        "xaxis": {"title": "Steps per year", "gridcolor": GRID_COLOR},
        "yaxis": {"title": "Price RMSE", "gridcolor": GRID_COLOR},
        "yaxis2": {"title": "Mean MC SE", "overlaying": "y", "side": "right", "showgrid": False},
    })
    fig.update_layout(**layout)
    return fig


def _plot_bates_fit_smiles(result: Mapping[str, Any]) -> go.Figure:
    table = result.get("fit_table")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Bates fit — target versus model IV", height=470))
        return fig
    frame = table.copy()
    expiries = frame[["expiration", "dte"]].drop_duplicates().sort_values("dte")
    palette = [BLUE, ORANGE, GREEN, PURPLE, CYAN, RED, "#f7c66b", "#79d2a6"]
    for index, expiration in enumerate(expiries["expiration"].astype(str)):
        subset = frame[frame["expiration"].astype(str) == expiration].sort_values("log_moneyness")
        color = palette[index % len(palette)]
        fig.add_trace(go.Scatter(
            x=subset["log_moneyness"], y=subset["target_iv"] * 100.0,
            mode="markers", name=f"{expiration} target", legendgroup=expiration,
            marker={"size": 6, "color": color, "opacity": 0.55},
        ))
        fig.add_trace(go.Scatter(
            x=subset["log_moneyness"], y=subset["bates_iv"] * 100.0,
            mode="lines", name=f"{expiration} Bates", legendgroup=expiration,
            line={"width": 2, "color": color},
        ))
    layout = _plotly_base_layout("Bates fit — target versus model IV", height=470)
    layout.update({"xaxis": {"title": "Log-moneyness log(K/F)", "gridcolor": GRID_COLOR}, "yaxis": {"title": "Implied volatility (%)", "gridcolor": GRID_COLOR}})
    fig.update_layout(**layout)
    return fig


def _plot_bates_residual_heatmap(result: Mapping[str, Any]) -> go.Figure:
    table = result.get("fit_table")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Bates IV residuals", height=420))
        return fig
    frame = table.copy()
    if "moneyness_bucket" not in frame:
        frame["moneyness_bucket"] = pd.cut(frame["log_moneyness"], [-np.inf, -0.20, -0.08, 0.08, 0.20, np.inf], labels=["Left wing", "Put shoulder", "ATM", "Call shoulder", "Right wing"])
    pivot = frame.pivot_table(index="expiration", columns="moneyness_bucket", values="iv_error", aggfunc="mean", observed=False)
    order = frame[["expiration", "dte"]].drop_duplicates().sort_values("dte")["expiration"].astype(str).tolist()
    pivot = pivot.reindex(order)
    z = pivot.to_numpy(dtype=float) * 100.0
    fig.add_trace(go.Heatmap(
        z=z, x=[str(value) for value in pivot.columns], y=pivot.index.astype(str),
        colorscale="RdBu", zmid=0.0, colorbar={"title": "IV error (pp)"},
        text=np.round(z, 2), texttemplate="%{text:+.2f}",
        hovertemplate="Expiry=%{y}<br>Bucket=%{x}<br>Mean IV error=%{z:+.2f} pp<extra></extra>",
    ))
    layout = _plotly_base_layout("Bates IV residuals by maturity and moneyness", height=420)
    layout.update({"xaxis": {"title": "Moneyness bucket", "type": "category"}, "yaxis": {"title": "Expiration", "type": "category", "categoryorder": "array", "categoryarray": order}})
    fig.update_layout(**layout)
    return fig


def _plot_bates_multistart(result: Mapping[str, Any]) -> go.Figure:
    table = result.get("multi_start_solutions")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Bates multi-start objective", height=360))
        return fig
    frame = table[np.isfinite(table["cost"])].copy().sort_values("cost")
    y = np.maximum(frame.get("relative_cost_bps", pd.Series(np.zeros(len(frame)))).to_numpy(dtype=float), 0.0)
    fig.add_trace(go.Bar(
        x=frame["start_id"].astype(str), y=y,
        marker={"color": np.where(frame["success"].astype(bool), GREEN, RED)},
        customdata=np.column_stack([frame["cost"], frame["jump_intensity"], frame["jump_mean"], frame["jump_volatility"]]),
        hovertemplate="Start=%{x}<br>Relative deterioration=%{y:.3f} bp<br>Raw cost=%{customdata[0]:.8g}<br>λJ=%{customdata[1]:.4f}<br>μJ=%{customdata[2]:.4f}<br>σJ=%{customdata[3]:.4f}<extra></extra>",
    ))
    layout = _plotly_base_layout("Bates multi-start objective — relative to best", height=360)
    layout.update({"xaxis": {"title": "Start ID", "type": "category"}, "yaxis": {"title": "Objective deterioration (bp of best cost)", "gridcolor": GRID_COLOR}})
    fig.update_layout(**layout)
    return fig


def _plot_bates_champion_comparison(result: Mapping[str, Any]) -> go.Figure:
    table = result.get("comparison_table")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Heston versus Bates validation", height=390))
        return fig
    metrics = ["train_iv_rmse", "holdout_iv_rmse", "front_wing_iv_rmse"]
    labels = ["Train IV RMSE", "Holdout IV RMSE", "Front-wing IV RMSE"]
    for _, row in table.iterrows():
        fig.add_trace(go.Bar(
            name=str(row["model"]),
            x=labels,
            y=[float(row[m]) * 100.0 for m in metrics],
            text=[f"{float(row[m]) * 100.0:.2f}%" for m in metrics],
            textposition="outside",
        ))
    layout = _plotly_base_layout("Heston versus Bates — governed validation metrics", height=390)
    layout.update({"barmode": "group", "yaxis": {"title": "IV error (%)", "gridcolor": GRID_COLOR}, "xaxis": {"type": "category"}})
    fig.update_layout(**layout)
    return fig


def _plot_bates_jump_parameter_position(result: Mapping[str, Any]) -> go.Figure:
    table = result.get("parameter_table")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Bates jump-parameter position", height=360))
        return fig
    frame = table[table["parameter"].isin(["jump_intensity", "jump_mean", "jump_volatility"])].copy()
    normalized = (frame["estimate"] - frame["lower_bound"]) / np.maximum(frame["upper_bound"] - frame["lower_bound"], 1e-12)
    fig.add_trace(go.Bar(
        x=frame["parameter"], y=normalized * 100.0,
        marker={"color": np.where(frame["near_bound"].astype(bool), ORANGE, CYAN)},
        customdata=np.column_stack([frame["estimate"], frame["lower_bound"], frame["upper_bound"]]),
        hovertemplate="%{x}<br>Estimate=%{customdata[0]:.6f}<br>Bounds=[%{customdata[1]:.6f}, %{customdata[2]:.6f}]<br>Relative position=%{y:.1f}%<extra></extra>",
    ))
    layout = _plotly_base_layout("Bates jump-parameter position within bounds", height=360)
    layout.update({"xaxis": {"title": "Jump parameter"}, "yaxis": {"title": "Position inside bound interval (%)", "range": [0, 100], "gridcolor": GRID_COLOR}})
    fig.update_layout(**layout)
    return fig


def _plot_bates_q_spot_fan(result: Mapping[str, Any], selected_dte: int) -> go.Figure:
    table = result.get("path_quantiles")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Bates Q spot distribution", height=470))
        return fig
    frame = table[table["day"] <= float(selected_dte) + 1e-9].copy()
    x = frame["day"]
    fig.add_trace(go.Scatter(x=x, y=frame["spot_p05"], mode="lines", line={"width": 0}, showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=frame["spot_p95"], mode="lines", line={"width": 0}, fill="tonexty", fillcolor="rgba(86,168,255,0.13)", name="P5–P95", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=frame["spot_p25"], mode="lines", line={"width": 0}, showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=frame["spot_p75"], mode="lines", line={"width": 0}, fill="tonexty", fillcolor="rgba(83,214,232,0.22)", name="P25–P75", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=frame["spot_p50"], mode="lines", name="Bates median", line={"color": CYAN, "width": 2.5}))
    fig.add_trace(go.Scatter(x=x, y=frame["spot_mean"], mode="lines", name="Bates Q mean", line={"color": GREEN, "width": 2}))
    if "diffusion_only_mean" in frame:
        fig.add_trace(go.Scatter(x=x, y=frame["diffusion_only_mean"], mode="lines", name="Bates diffusion-only mean", line={"color": PURPLE, "width": 1.8, "dash": "dot"}))
    fig.add_trace(go.Scatter(x=x, y=frame["forward_target"], mode="lines", name="Governed forward", line={"color": ORANGE, "width": 2, "dash": "dash"}))
    layout = _plotly_base_layout(f"Bates Q spot cone — {selected_dte} calendar days", height=480)
    layout.update({"xaxis": {"title": "Calendar days", "gridcolor": GRID_COLOR}, "yaxis": {"title": "Spot price", "gridcolor": GRID_COLOR}})
    fig.update_layout(**layout)
    return fig


def _plot_bates_jump_process(result: Mapping[str, Any], selected_dte: int) -> go.Figure:
    table = result.get("jump_diagnostics")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Bates jump process", height=470))
        return fig
    frame = table[table["day"] <= float(selected_dte) + 1e-9].copy()
    fig.add_trace(go.Scatter(
        x=frame["day"], y=frame["mean_cumulative_jumps"], mode="lines", name="Empirical mean jump count",
        line={"color": CYAN, "width": 2.4},
    ))
    fig.add_trace(go.Scatter(
        x=frame["day"], y=frame["expected_cumulative_jumps"], mode="lines", name="Poisson expectation λT",
        line={"color": ORANGE, "width": 2, "dash": "dash"},
    ))
    fig.add_trace(go.Scatter(
        x=frame["day"], y=frame["probability_at_least_one_jump"] * 100.0, mode="lines", name="P(at least one jump)",
        line={"color": GREEN, "width": 2}, yaxis="y2",
    ))
    layout = _plotly_base_layout(f"Bates compound-Poisson jump diagnostics — {selected_dte}D", height=480)
    layout.update({
        "xaxis": {"title": "Calendar days", "gridcolor": GRID_COLOR},
        "yaxis": {"title": "Cumulative jump count", "gridcolor": GRID_COLOR},
        "yaxis2": {"title": "Jump-path probability (%)", "overlaying": "y", "side": "right", "showgrid": False, "range": [0, max(5.0, float(frame["probability_at_least_one_jump"].max() * 110.0))]},
    })
    fig.update_layout(**layout)
    return fig


def _plot_bates_terminal_comparison(result: Mapping[str, Any], selected_dte: int) -> go.Figure:
    bates = result.get("terminal_spot_samples")
    heston = result.get("heston_terminal_samples")
    diffusion = result.get("diffusion_only_terminal_samples")
    fig = go.Figure()
    if not isinstance(bates, pd.DataFrame) or str(selected_dte) not in bates:
        fig.update_layout(**_plotly_base_layout("Heston versus Bates terminal Q distribution", height=440))
        return fig
    champion_status = str(result.get("bates_champion_status", "UNKNOWN"))
    bates_label = "Bates champion" if champion_status == "BATES_CHAMPION" else (
        "Bates research challenger" if champion_status == "BATES_RESEARCH_ONLY" else "Bates challenger"
    )
    fig.add_trace(go.Histogram(x=bates[str(selected_dte)], histnorm="probability density", nbinsx=70, name=bates_label, marker={"color": "rgba(83,214,232,0.50)"}, opacity=0.72))
    if isinstance(heston, pd.DataFrame) and str(selected_dte) in heston:
        fig.add_trace(go.Histogram(x=heston[str(selected_dte)], histnorm="probability density", nbinsx=70, name="Heston benchmark", marker={"color": "rgba(156,140,255,0.42)"}, opacity=0.62))
    if isinstance(diffusion, pd.DataFrame) and str(selected_dte) in diffusion:
        fig.add_trace(go.Histogram(x=diffusion[str(selected_dte)], histnorm="probability density", nbinsx=70, name="Bates diffusion-only", marker={"color": "rgba(247,198,107,0.28)"}, opacity=0.45))
    fig.update_layout(barmode="overlay")
    layout = _plotly_base_layout(f"Heston/Bates risk-neutral terminal distributions — {selected_dte}D", height=440)
    layout.update({"xaxis": {"title": "Terminal spot", "gridcolor": GRID_COLOR}, "yaxis": {"title": "Probability density", "gridcolor": GRID_COLOR}, "bargap": 0.02})
    fig.update_layout(**layout)
    return fig


def _plot_bates_mc_fourier_prices(result: Mapping[str, Any]) -> go.Figure:
    table = result.get("pricing_validation")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Bates Monte Carlo versus Fourier prices", height=430))
        return fig
    for role, color in (("TRAIN", BLUE), ("HOLDOUT", ORANGE)):
        subset = table[table["sample_role"].astype(str) == role]
        if subset.empty:
            continue
        fig.add_trace(go.Scatter(
            x=subset["fourier_price"], y=subset["mc_price"], mode="markers", name=role,
            marker={"size": 7, "color": color, "opacity": 0.75},
            customdata=np.column_stack([subset["dte"], subset["strike"], subset["mc_standard_error"], subset["mc_fourier_z_score"]]),
            hovertemplate="DTE=%{customdata[0]}<br>Strike=%{customdata[1]:.2f}<br>Fourier=%{x:.4f}<br>MC=%{y:.4f}<br>MC SE=%{customdata[2]:.5f}<br>z=%{customdata[3]:.2f}<extra></extra>",
        ))
    values = np.concatenate([table["fourier_price"].to_numpy(dtype=float), table["mc_price"].to_numpy(dtype=float)])
    low, high = float(np.nanmin(values)), float(np.nanmax(values))
    fig.add_trace(go.Scatter(x=[low, high], y=[low, high], mode="lines", name="45°", line={"color": GREEN, "dash": "dash"}))
    layout = _plotly_base_layout("Bates Monte Carlo versus Fourier prices", height=430)
    layout.update({"xaxis": {"title": "Fourier Bates price", "gridcolor": GRID_COLOR}, "yaxis": {"title": "Monte Carlo price", "gridcolor": GRID_COLOR}})
    fig.update_layout(**layout)
    return fig


def _plot_bates_mc_iv_residuals(result: Mapping[str, Any]) -> go.Figure:
    table = result.get("pricing_validation")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Bates Monte Carlo IV residuals", height=430))
        return fig
    pivot = table.pivot_table(index="expiration", columns="moneyness_bucket", values="mc_fourier_iv_error", aggfunc="mean", observed=False)
    order = table[["expiration", "dte"]].drop_duplicates().sort_values("dte")["expiration"].astype(str).tolist()
    pivot = pivot.reindex(order)
    z = pivot.to_numpy(dtype=float) * 100.0
    if "iv_residual_diagnostic" in table:
        flagged = table.assign(
            _low_vega=table["iv_residual_diagnostic"].astype(str).eq("LOW_VEGA_IV_AMPLIFICATION").astype(int)
        ).pivot_table(index="expiration", columns="moneyness_bucket", values="_low_vega", aggfunc="sum", observed=False)
        flagged = flagged.reindex(index=pivot.index, columns=pivot.columns).fillna(0).to_numpy(dtype=int)
    else:
        flagged = np.zeros_like(z, dtype=int)
    text = np.empty(z.shape, dtype=object)
    for row_index in range(z.shape[0]):
        for column_index in range(z.shape[1]):
            value = z[row_index, column_index]
            suffix = "*" if flagged[row_index, column_index] > 0 else ""
            text[row_index, column_index] = f"{value:+.2f}{suffix}" if np.isfinite(value) else ""
    total_low_vega = int(np.sum(flagged))
    fig.add_trace(go.Heatmap(
        z=z, x=[str(value) for value in pivot.columns], y=pivot.index.astype(str), colorscale="RdBu", zmid=0.0,
        colorbar={"title": "MC − Fourier IV (pp)"}, text=text, texttemplate="%{text}", customdata=flagged,
        hovertemplate="Expiry=%{y}<br>Bucket=%{x}<br>MC − Fourier IV=%{z:+.2f} pp<br>Low-vega flags=%{customdata}<extra></extra>",
    ))
    title = "Bates Monte Carlo versus Fourier IV residuals"
    if total_low_vega:
        title += f" · {total_low_vega} low-vega flag(s)"
    layout = _plotly_base_layout(title, height=430)
    layout.update({"xaxis": {"title": "Moneyness bucket", "type": "category"}, "yaxis": {"title": "Expiration", "type": "category", "categoryorder": "array", "categoryarray": order}})
    fig.update_layout(**layout)
    return fig


def _plot_bates_risk_comparison(result: Mapping[str, Any]) -> go.Figure:
    table = result.get("heston_bates_comparison")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Heston versus Bates Q risk comparison", height=420))
        return fig
    x = table["dte"].astype(str)
    fig.add_trace(go.Bar(x=x, y=table["heston_es_5"] * 100.0, name="Heston ES 5%", marker={"color": PURPLE}))
    fig.add_trace(go.Bar(x=x, y=table["bates_es_5"] * 100.0, name="Bates ES 5%", marker={"color": CYAN}))
    fig.add_trace(go.Scatter(x=x, y=table["delta_skewness"], mode="lines+markers", name="Δ skewness Bates−Heston", line={"color": ORANGE, "width": 2}, yaxis="y2"))
    layout = _plotly_base_layout("Heston versus Bates — Q tail-risk comparison", height=420)
    layout.update({
        "barmode": "group",
        "xaxis": {"title": "Days to expiry", "type": "category"},
        "yaxis": {"title": "Expected Shortfall 5% (%)", "gridcolor": GRID_COLOR},
        "yaxis2": {"title": "Δ skewness", "overlaying": "y", "side": "right", "showgrid": False},
    })
    fig.update_layout(**layout)
    return fig


def _plot_bates_convergence(result: Mapping[str, Any], kind: str = "time") -> go.Figure:
    is_time = str(kind).lower() == "time"
    table = result.get("time_convergence" if is_time else "path_convergence")
    diagnostic = result.get("time_convergence_diagnostic" if is_time else "path_convergence_diagnostic", {})
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Bates simulation convergence", height=380))
        return fig
    x_col = "steps_per_year" if is_time else "path_count"
    x = table[x_col].to_numpy(dtype=float)
    mean = table["price_rmse_mean"].to_numpy(dtype=float)
    low = table["price_rmse_ci_low"].to_numpy(dtype=float)
    high = table["price_rmse_ci_high"].to_numpy(dtype=float)
    fig.add_trace(go.Scatter(
        x=x, y=mean, mode="lines+markers", name="Replicated MC–Fourier RMSE", line={"color": CYAN, "width": 2.4},
        error_y={"type": "data", "symmetric": False, "array": np.maximum(high - mean, 0.0), "arrayminus": np.maximum(mean - low, 0.0), "color": CYAN, "thickness": 1.3},
    ))
    fig.add_trace(go.Scatter(
        x=x, y=table["mean_mc_standard_error"], mode="lines+markers", name="Mean MC standard error",
        line={"color": ORANGE, "width": 2}, yaxis="y2",
    ))
    status = str(diagnostic.get("status", "NOT RUN"))
    title = ("Replicated Bates time-step convergence" if is_time else "Replicated Bates path-count convergence") + f" — {status}"
    layout = _plotly_base_layout(title, height=380)
    layout.update({
        "xaxis": {"title": "Steps per year" if is_time else "Path count", "gridcolor": GRID_COLOR},
        "yaxis": {"title": "Price RMSE", "gridcolor": GRID_COLOR},
        "yaxis2": {"title": "Mean MC SE", "overlaying": "y", "side": "right", "showgrid": False},
    })
    fig.update_layout(**layout)
    return fig


def _plot_model_risk_parameter_intervals(result: Mapping[str, Any], model: str = "Bates") -> go.Figure:
    table = result.get("parameter_intervals")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout(f"{model} parameter uncertainty", height=430))
        return fig
    frame = table[table["model"].astype(str) == str(model)].copy()
    if frame.empty:
        fig.update_layout(**_plotly_base_layout(f"{model} parameter uncertainty", height=430))
        return fig
    x = frame["parameter"].astype(str)
    median = frame["bootstrap_median"].to_numpy(dtype=float)
    low = frame["ci_low"].to_numpy(dtype=float)
    high = frame["ci_high"].to_numpy(dtype=float)
    base = frame["base_estimate"].to_numpy(dtype=float)
    fig.add_trace(go.Scatter(
        x=x,
        y=median,
        mode="markers",
        name="Bootstrap median",
        marker={"size": 10, "color": CYAN},
        error_y={
            "type": "data",
            "symmetric": False,
            "array": np.maximum(high - median, 0.0),
            "arrayminus": np.maximum(median - low, 0.0),
            "color": CYAN,
            "thickness": 1.5,
        },
        customdata=np.column_stack([low, high, frame["normalized_interval_width"].to_numpy(dtype=float)]),
        hovertemplate="%{x}<br>Median=%{y:.6f}<br>CI=[%{customdata[0]:.6f}, %{customdata[1]:.6f}]<br>Normalized width=%{customdata[2]:.3f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=x,
        y=base,
        mode="markers",
        name="Source calibration",
        marker={"size": 9, "symbol": "diamond-open", "color": ORANGE, "line": {"width": 2}},
    ))
    layout = _plotly_base_layout(f"{model} parameter bootstrap intervals", height=430)
    layout.update({"xaxis": {"title": "Parameter", "type": "category"}, "yaxis": {"title": "Parameter value", "gridcolor": GRID_COLOR}})
    fig.update_layout(**layout)
    return fig


def _plot_model_risk_correlation(result: Mapping[str, Any], model: str = "Bates") -> go.Figure:
    table = result.get("parameter_correlations")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout(f"{model} local parameter correlation", height=450))
        return fig
    frame = table[table["model"].astype(str) == str(model)].copy()
    if frame.empty:
        fig.update_layout(**_plotly_base_layout(f"{model} local parameter correlation", height=450))
        return fig
    pivot = frame.pivot(index="parameter_1", columns="parameter_2", values="correlation")
    order = list(dict.fromkeys(frame["parameter_1"].astype(str).tolist()))
    pivot = pivot.reindex(index=order, columns=order)
    fig.add_trace(go.Heatmap(
        z=pivot.to_numpy(dtype=float),
        x=pivot.columns.astype(str),
        y=pivot.index.astype(str),
        zmin=-1.0,
        zmax=1.0,
        zmid=0.0,
        colorscale="RdBu",
        text=np.vectorize(lambda value: f"{value:+.2f}" if np.isfinite(value) else "")(pivot.to_numpy(dtype=float)),
        texttemplate="%{text}",
        colorbar={"title": "Local corr."},
        hovertemplate="%{y} / %{x}<br>Correlation=%{z:+.4f}<extra></extra>",
    ))
    layout = _plotly_base_layout(f"{model} local identifiability correlation", height=450)
    layout.update({"xaxis": {"type": "category"}, "yaxis": {"type": "category", "autorange": "reversed"}})
    fig.update_layout(**layout)
    return fig


def _plot_model_risk_cost_profiles(result: Mapping[str, Any], model: str = "Bates") -> go.Figure:
    table = result.get("cost_profiles")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout(f"{model} conditional cost profiles", height=450))
        return fig
    frame = table[table["model"].astype(str) == str(model)].copy()
    if frame.empty:
        fig.update_layout(**_plotly_base_layout(f"{model} conditional cost profiles", height=450))
        return fig
    palette = [CYAN, ORANGE, GREEN, PURPLE, BLUE, RED, "#f59e0b", "#94a3b8"]
    for idx, (parameter, group) in enumerate(frame.groupby("parameter", sort=False)):
        ordered = group.sort_values("parameter_value")
        span = float(ordered["parameter_value"].max() - ordered["parameter_value"].min())
        x = (ordered["parameter_value"] - float(ordered["base_value"].iloc[0])) / max(span, 1e-12)
        fig.add_trace(go.Scatter(
            x=x,
            y=np.minimum(ordered["cost_deterioration_bps"].to_numpy(dtype=float), 1e5),
            mode="lines+markers",
            name=str(parameter),
            line={"width": 2, "color": palette[idx % len(palette)]},
            customdata=ordered[["parameter_value", "relative_cost"]].to_numpy(dtype=float),
            hovertemplate="%{fullData.name}<br>Relative grid displacement=%{x:+.3f}<br>Parameter=%{customdata[0]:.6f}<br>Cost ratio=%{customdata[1]:.3f}<extra></extra>",
        ))
    layout = _plotly_base_layout(f"{model} conditional cost sensitivity", height=450)
    layout.update({
        "xaxis": {"title": "Displacement around calibrated value (normalized within local grid)", "gridcolor": GRID_COLOR},
        "yaxis": {"title": "Objective deterioration (bp of base cost)", "gridcolor": GRID_COLOR, "rangemode": "tozero"},
    })
    fig.update_layout(**layout)
    return fig


def _plot_model_risk_maturity_sensitivity(result: Mapping[str, Any]) -> go.Figure:
    table = result.get("maturity_sensitivity")
    fig = go.Figure()
    if not isinstance(table, pd.DataFrame) or table.empty:
        fig.update_layout(**_plotly_base_layout("Leave-one-maturity parameter sensitivity", height=400))
        return fig
    frame = table[table.get("success", False).astype(bool)].copy() if "success" in table else table.copy()
    for model, color in (("Heston", PURPLE), ("Bates", CYAN)):
        subset = frame[frame["model"].astype(str) == model].sort_values("excluded_expiration")
        if subset.empty:
            continue
        fig.add_trace(go.Bar(
            x=subset["excluded_expiration"].astype(str),
            y=subset["maximum_normalized_parameter_shift"].to_numpy(dtype=float),
            name=model,
            marker={"color": color},
            customdata=np.column_stack([subset.get("holdout_linearized_iv_rmse", pd.Series(np.nan, index=subset.index)).to_numpy(dtype=float)]),
            hovertemplate="Excluded=%{x}<br>Max normalized parameter shift=%{y:.3f}<br>Holdout linearized IV RMSE=%{customdata[0]:.3%}<extra></extra>",
        ))
    layout = _plotly_base_layout("Leave-one-maturity calibration sensitivity", height=400)
    layout.update({"barmode": "group", "xaxis": {"title": "Excluded expiry", "type": "category"}, "yaxis": {"title": "Maximum normalized parameter shift", "gridcolor": GRID_COLOR}})
    fig.update_layout(**layout)
    return fig


def _plot_model_risk_bootstrap_selection(result: Mapping[str, Any]) -> go.Figure:
    summary = result.get("bootstrap_summary", {})
    values = [
        float(summary.get("heston_success_rate", 0.0)) * 100.0,
        float(summary.get("bates_success_rate", 0.0)) * 100.0,
        float(summary.get("bates_selection_probability", 0.0)) * 100.0,
    ]
    labels = ["Heston recalibration success", "Bates recalibration success", "Bates preferred across bootstrap draws"]
    fig = go.Figure(go.Bar(x=labels, y=values, marker={"color": [PURPLE, CYAN, ORANGE]}, text=[f"{value:.1f}%" for value in values], textposition="outside"))
    layout = _plotly_base_layout("Quote-resample model-risk outcomes", height=390)
    layout.update({"xaxis": {"type": "category"}, "yaxis": {"title": "Frequency (%)", "range": [0, 105], "gridcolor": GRID_COLOR}})
    fig.update_layout(**layout)
    return fig
