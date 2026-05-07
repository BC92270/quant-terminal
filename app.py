import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go


st.set_page_config(
    page_title="Quant Terminal",
    page_icon="📈",
    layout="wide"
)


def get_price_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    data = yf.download(
        ticker,
        period=period,
        interval=interval,
        progress=False,
        auto_adjust=False
    )

    if data.empty:
        raise ValueError(f"Aucune donnée trouvée pour le ticker : {ticker}")

    data = data.reset_index()

    data.columns = [
        col[0].lower() if isinstance(col, tuple) else str(col).lower()
        for col in data.columns
    ]

    data = data.rename(columns={
        "date": "date",
        "datetime": "date",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "adj close": "adj_close",
        "volume": "volume"
    })

    return data


def calculate_returns(prices: pd.Series) -> pd.Series:
    return prices.pct_change().dropna()


def calculate_volatility(returns: pd.Series) -> float:
    return float(returns.std() * np.sqrt(252))


def calculate_drift(returns: pd.Series) -> float:
    return float(returns.mean() * 252)


def calculate_momentum(prices: pd.Series) -> float:
    if len(prices) < 60:
        return 0.0

    perf_20d = prices.iloc[-1] / prices.iloc[-20] - 1
    perf_60d = prices.iloc[-1] / prices.iloc[-60] - 1

    momentum = 0.6 * perf_20d + 0.4 * perf_60d
    return float(momentum)


def calculate_max_drawdown(prices: pd.Series) -> float:
    cumulative_max = prices.cummax()
    drawdown = prices / cumulative_max - 1
    return float(drawdown.min())


def monte_carlo_simulation(
    start_price: float,
    drift: float,
    volatility: float,
    days: int = 30,
    simulations: int = 1000
):
    dt = 1 / 252
    paths = np.zeros((days, simulations))
    paths[0] = start_price

    for t in range(1, days):
        random_shocks = np.random.normal(0, 1, simulations)
        paths[t] = paths[t - 1] * np.exp(
            (drift - 0.5 * volatility ** 2) * dt
            + volatility * np.sqrt(dt) * random_shocks
        )

    return paths


def calculate_trade_levels(price: float, volatility: float, momentum: float):
    daily_vol = volatility / np.sqrt(252)

    if momentum > 0:
        entry_price = price * 0.98
        stop_loss = price * (1 - 2.5 * daily_vol)
        take_profit = price * (1 + 5 * daily_vol)
    else:
        entry_price = price * 0.95
        stop_loss = price * (1 - 2.0 * daily_vol)
        take_profit = price * (1 + 3.0 * daily_vol)

    downside = entry_price - stop_loss
    upside = take_profit - entry_price

    risk_reward = upside / downside if downside > 0 else 0

    return {
        "entry_price": float(entry_price),
        "stop_loss": float(stop_loss),
        "take_profit": float(take_profit),
        "risk_reward": float(risk_reward)
    }


def generate_signal(momentum: float, volatility: float, risk_reward: float, max_drawdown: float):
    score = 0

    if momentum > 0.05:
        score += 30
    elif momentum > 0:
        score += 15
    else:
        score -= 10

    if volatility < 0.35:
        score += 20
    elif volatility < 0.60:
        score += 5
    else:
        score -= 15

    if risk_reward >= 2:
        score += 25
    elif risk_reward >= 1.5:
        score += 10
    else:
        score -= 10

    if max_drawdown > -0.20:
        score += 15
    elif max_drawdown > -0.35:
        score += 5
    else:
        score -= 10

    if score >= 60:
        signal = "BUY_ZONE"
    elif score >= 30:
        signal = "WATCH"
    elif score >= 0:
        signal = "NEUTRAL"
    else:
        signal = "AVOID"

    return score, signal


def analyze_ticker(price_data: pd.DataFrame):
    close = price_data["close"].dropna()

    if len(close) < 60:
        raise ValueError("Pas assez de données pour analyser ce ticker.")

    latest_price = float(close.iloc[-1])
    returns = calculate_returns(close)

    volatility = calculate_volatility(returns)
    drift = calculate_drift(returns)
    momentum = calculate_momentum(close)
    max_drawdown = calculate_max_drawdown(close)

    levels = calculate_trade_levels(
        price=latest_price,
        volatility=volatility,
        momentum=momentum
    )

    global_score, signal = generate_signal(
        momentum=momentum,
        volatility=volatility,
        risk_reward=levels["risk_reward"],
        max_drawdown=max_drawdown
    )

    mc_paths = monte_carlo_simulation(
        start_price=latest_price,
        drift=drift,
        volatility=volatility,
        days=30,
        simulations=1000
    )

    mc_summary = {
        "p05": float(np.percentile(mc_paths[-1], 5)),
        "p25": float(np.percentile(mc_paths[-1], 25)),
        "p50": float(np.percentile(mc_paths[-1], 50)),
        "p75": float(np.percentile(mc_paths[-1], 75)),
        "p95": float(np.percentile(mc_paths[-1], 95)),
    }

    return {
        "latest_price": latest_price,
        "volatility": volatility,
        "drift": drift,
        "momentum": momentum,
        "max_drawdown": max_drawdown,
        "risk_reward": levels["risk_reward"],
        "entry_price": levels["entry_price"],
        "stop_loss": levels["stop_loss"],
        "take_profit": levels["take_profit"],
        "global_score": global_score,
        "signal": signal,
        "monte_carlo": mc_summary,
        "monte_carlo_paths": mc_paths
    }


st.title("📈 Quant Terminal")

st.markdown(
    """
    Terminal quant V1 : prix historiques, volatilité, drift, momentum, drawdown,
    niveaux théoriques, risk/reward et simulation Monte Carlo.
    
    Les résultats sont des analyses quantitatives mécaniques, pas des conseils d'investissement.
    """
)

with st.sidebar:
    st.header("Paramètres")

    ticker = st.text_input("Ticker", value="NVDA").upper().strip()

    period = st.selectbox(
        "Période",
        ["3mo", "6mo", "1y", "2y", "5y"],
        index=2
    )

    interval = st.selectbox(
        "Intervalle",
        ["1d", "1wk", "1mo"],
        index=0
    )

    run_analysis = st.button("Analyser")


if run_analysis:
    try:
        with st.spinner(f"Analyse de {ticker} en cours..."):
            price_data = get_price_history(ticker, period=period, interval=interval)
            analysis = analyze_ticker(price_data)

        st.subheader(f"Analyse de {ticker}")

        col1, col2, col3, col4 = st.columns(4)

        col1.metric("Prix", round(analysis["latest_price"], 2))
        col2.metric("Signal", analysis["signal"])
        col3.metric("Score", round(analysis["global_score"], 2))
        col4.metric("Risk/Reward", round(analysis["risk_reward"], 2))

        col5, col6, col7, col8 = st.columns(4)

        col5.metric("Volatilité annualisée", f"{analysis['volatility']:.2%}")
        col6.metric("Drift annualisé", f"{analysis['drift']:.2%}")
        col7.metric("Momentum", f"{analysis['momentum']:.2%}")
        col8.metric("Max Drawdown", f"{analysis['max_drawdown']:.2%}")

        st.divider()

        st.subheader("Niveaux théoriques")

        levels_df = pd.DataFrame([{
            "Prix actuel": analysis["latest_price"],
            "Entry théorique": analysis["entry_price"],
            "Stop Loss théorique": analysis["stop_loss"],
            "Take Profit théorique": analysis["take_profit"],
            "Risk/Reward": analysis["risk_reward"]
        }])

        st.dataframe(levels_df, use_container_width=True)

        st.divider()

        st.subheader("Graphique prix")

        fig = go.Figure()

        fig.add_trace(go.Candlestick(
            x=price_data["date"],
            open=price_data["open"],
            high=price_data["high"],
            low=price_data["low"],
            close=price_data["close"],
            name=ticker
        ))

        fig.add_hline(
            y=analysis["entry_price"],
            line_dash="dash",
            annotation_text="Entry"
        )

        fig.add_hline(
            y=analysis["stop_loss"],
            line_dash="dash",
            annotation_text="Stop"
        )

        fig.add_hline(
            y=analysis["take_profit"],
            line_dash="dash",
            annotation_text="Take Profit"
        )

        fig.update_layout(
            height=650,
            xaxis_rangeslider_visible=False
        )

        st.plotly_chart(fig, use_container_width=True)

        st.divider()

        st.subheader("Monte Carlo — distribution à 30 jours")

        mc = analysis["monte_carlo"]

        mc_df = pd.DataFrame([{
            "P5": mc["p05"],
            "P25": mc["p25"],
            "P50": mc["p50"],
            "P75": mc["p75"],
            "P95": mc["p95"]
        }])

        st.dataframe(mc_df, use_container_width=True)

        mc_paths = analysis["monte_carlo_paths"]

        mc_fig = go.Figure()

        max_paths_to_display = 50

        for i in range(max_paths_to_display):
            mc_fig.add_trace(go.Scatter(
                y=mc_paths[:, i],
                mode="lines",
                showlegend=False
            ))

        mc_fig.update_layout(
            height=500,
            title="Exemples de scénarios Monte Carlo sur 30 jours",
            xaxis_title="Jours",
            yaxis_title="Prix simulé"
        )

        st.plotly_chart(mc_fig, use_container_width=True)

        st.divider()

        with st.expander("Voir les dernières données brutes"):
            st.dataframe(price_data.tail(20), use_container_width=True)

    except Exception as e:
        st.error(f"Erreur : {e}")
else:
    st.info("Entre un ticker dans la barre latérale puis clique sur Analyser.")