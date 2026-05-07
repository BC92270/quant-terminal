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


# ============================================================
# DATA
# ============================================================

@st.cache_data(ttl=300)
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

    required_columns = ["date", "open", "high", "low", "close"]

    for col in required_columns:
        if col not in data.columns:
            raise ValueError(f"Colonne manquante dans les données : {col}")

    return data.dropna(subset=["close"])


# ============================================================
# QUANT HELPERS
# ============================================================

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

    return float(0.6 * perf_20d + 0.4 * perf_60d)


def calculate_max_drawdown(prices: pd.Series) -> float:
    cumulative_max = prices.cummax()
    drawdown = prices / cumulative_max - 1
    return float(drawdown.min())


def calculate_atr(data: pd.DataFrame, window: int = 14) -> float:
    high = data["high"]
    low = data["low"]
    close = data["close"]

    previous_close = close.shift(1)

    tr_1 = high - low
    tr_2 = (high - previous_close).abs()
    tr_3 = (low - previous_close).abs()

    true_range = pd.concat([tr_1, tr_2, tr_3], axis=1).max(axis=1)
    atr = true_range.rolling(window=window).mean().dropna()

    if atr.empty:
        return float(true_range.mean())

    return float(atr.iloc[-1])


def safe_performance(prices: pd.Series, days: int):
    if len(prices) <= days:
        return None

    return float(prices.iloc[-1] / prices.iloc[-days] - 1)


def calculate_performance_table(prices: pd.Series) -> pd.DataFrame:
    perf_map = {
        "5D": safe_performance(prices, 5),
        "1M": safe_performance(prices, 21),
        "3M": safe_performance(prices, 63),
        "6M": safe_performance(prices, 126),
        "1Y": safe_performance(prices, 252),
    }

    rows = []

    for label, value in perf_map.items():
        rows.append({
            "Horizon": label,
            "Performance": value
        })

    return pd.DataFrame(rows)


def calculate_52w_levels(prices: pd.Series) -> dict:
    lookback = min(len(prices), 252)
    recent = prices.tail(lookback)

    high_52w = float(recent.max())
    low_52w = float(recent.min())
    current = float(prices.iloc[-1])

    distance_high = current / high_52w - 1
    distance_low = current / low_52w - 1

    return {
        "high_52w": high_52w,
        "low_52w": low_52w,
        "distance_high": float(distance_high),
        "distance_low": float(distance_low)
    }


def monte_carlo_simulation(
    start_price: float,
    drift: float,
    volatility: float,
    days: int = 30,
    simulations: int = 1000
) -> np.ndarray:
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


# ============================================================
# SIGNAL / PLAN
# ============================================================

def generate_signal(
    momentum: float,
    volatility: float,
    risk_reward: float,
    max_drawdown: float
):
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


def calculate_basic_trade_levels(
    price: float,
    volatility: float,
    momentum: float
) -> dict:
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


def calculate_trading_plan(
    price: float,
    atr: float,
    momentum: float,
    volatility: float
) -> dict:
    if atr <= 0:
        atr = price * 0.02

    if momentum > 0:
        entry_aggressive = price - 0.50 * atr
        entry_prudent = price - 1.00 * atr
        stop_short = price - 1.50 * atr
        stop_structural = price - 2.50 * atr
        target_1 = price + 1.50 * atr
        target_2 = price + 3.00 * atr
    else:
        entry_aggressive = price - 0.75 * atr
        entry_prudent = price - 1.50 * atr
        stop_short = price - 2.00 * atr
        stop_structural = price - 3.00 * atr
        target_1 = price + 1.25 * atr
        target_2 = price + 2.50 * atr

    rr_aggressive = (
        (target_2 - entry_aggressive) / (entry_aggressive - stop_short)
        if entry_aggressive > stop_short else 0
    )

    rr_prudent = (
        (target_2 - entry_prudent) / (entry_prudent - stop_structural)
        if entry_prudent > stop_structural else 0
    )

    if volatility > 0.60:
        risk_regime = "Risque élevé"
    elif volatility > 0.35:
        risk_regime = "Risque modéré"
    else:
        risk_regime = "Risque contenu"

    return {
        "entry_aggressive": float(entry_aggressive),
        "entry_prudent": float(entry_prudent),
        "stop_short": float(stop_short),
        "stop_structural": float(stop_structural),
        "target_1": float(target_1),
        "target_2": float(target_2),
        "rr_aggressive": float(rr_aggressive),
        "rr_prudent": float(rr_prudent),
        "risk_regime": risk_regime
    }


def generate_commentary(
    signal: str,
    momentum: float,
    volatility: float,
    max_drawdown: float,
    risk_reward: float
) -> str:
    comments = []

    if signal == "BUY_ZONE":
        comments.append("Le modèle détecte une configuration quantitative favorable.")
    elif signal == "WATCH":
        comments.append("Le titre mérite surveillance, mais le signal n'est pas encore pleinement confirmé.")
    elif signal == "NEUTRAL":
        comments.append("Le signal est neutre : le modèle ne détecte pas d'avantage clair.")
    else:
        comments.append("Le modèle recommande d'éviter pour l'instant selon les critères quantitatifs.")

    if momentum > 0.05:
        comments.append("Le momentum récent est positif.")
    elif momentum > 0:
        comments.append("Le momentum est légèrement positif.")
    else:
        comments.append("Le momentum est faible ou négatif.")

    if volatility > 0.60:
        comments.append("La volatilité est très élevée : la taille de position devrait être réduite.")
    elif volatility > 0.35:
        comments.append("La volatilité est significative : le risque doit être surveillé.")
    else:
        comments.append("La volatilité est relativement contenue.")

    if max_drawdown < -0.35:
        comments.append("Le drawdown historique est important, ce qui signale un risque structurel élevé.")
    elif max_drawdown < -0.20:
        comments.append("Le drawdown est notable, mais pas extrême.")
    else:
        comments.append("Le drawdown reste relativement modéré.")

    if risk_reward >= 2:
        comments.append("Le ratio risk/reward est attractif selon les niveaux théoriques.")
    elif risk_reward >= 1.5:
        comments.append("Le ratio risk/reward est acceptable mais pas exceptionnel.")
    else:
        comments.append("Le ratio risk/reward est faible.")

    return " ".join(comments)


def analyze_ticker(price_data: pd.DataFrame) -> dict:
    close = price_data["close"].dropna()

    if len(close) < 60:
        raise ValueError("Pas assez de données pour analyser ce ticker.")

    latest_price = float(close.iloc[-1])
    returns = calculate_returns(close)

    volatility = calculate_volatility(returns)
    drift = calculate_drift(returns)
    momentum = calculate_momentum(close)
    max_drawdown = calculate_max_drawdown(close)
    atr = calculate_atr(price_data, window=14)

    basic_levels = calculate_basic_trade_levels(
        price=latest_price,
        volatility=volatility,
        momentum=momentum
    )

    global_score, signal = generate_signal(
        momentum=momentum,
        volatility=volatility,
        risk_reward=basic_levels["risk_reward"],
        max_drawdown=max_drawdown
    )

    trading_plan = calculate_trading_plan(
        price=latest_price,
        atr=atr,
        momentum=momentum,
        volatility=volatility
    )

    levels_52w = calculate_52w_levels(close)

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

    commentary = generate_commentary(
        signal=signal,
        momentum=momentum,
        volatility=volatility,
        max_drawdown=max_drawdown,
        risk_reward=basic_levels["risk_reward"]
    )

    return {
        "latest_price": latest_price,
        "volatility": volatility,
        "drift": drift,
        "momentum": momentum,
        "max_drawdown": max_drawdown,
        "atr": atr,
        "global_score": global_score,
        "signal": signal,
        "basic_levels": basic_levels,
        "trading_plan": trading_plan,
        "levels_52w": levels_52w,
        "monte_carlo": mc_summary,
        "monte_carlo_paths": mc_paths,
        "commentary": commentary
    }


# ============================================================
# UI COMPONENTS
# ============================================================

def render_header():
    st.title("📈 Quant Terminal")

    st.markdown(
        """
        Terminal quant V2.2 : analyse quantitative, snapshot, trading plan, risk monitor,
        ATR, niveaux d’entrée/sortie, risk/reward et simulation Monte Carlo.
        
        Les résultats sont des analyses quantitatives mécaniques, pas des conseils d'investissement.
        """
    )


def render_main_metrics(analysis: dict):
    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Prix", round(analysis["latest_price"], 2))
    col2.metric("Signal", analysis["signal"])
    col3.metric("Score", round(analysis["global_score"], 2))
    col4.metric("ATR 14", round(analysis["atr"], 2))

    col5, col6, col7, col8 = st.columns(4)

    col5.metric("Volatilité annualisée", f"{analysis['volatility']:.2%}")
    col6.metric("Drift annualisé", f"{analysis['drift']:.2%}")
    col7.metric("Momentum", f"{analysis['momentum']:.2%}")
    col8.metric("Max Drawdown", f"{analysis['max_drawdown']:.2%}")


def render_price_chart(
    price_data: pd.DataFrame,
    ticker: str,
    analysis: dict,
    use_trading_plan: bool = False
):
    fig = go.Figure()

    fig.add_trace(go.Candlestick(
        x=price_data["date"],
        open=price_data["open"],
        high=price_data["high"],
        low=price_data["low"],
        close=price_data["close"],
        name=ticker
    ))

    if use_trading_plan:
        plan = analysis["trading_plan"]

        lines = [
            ("Entry agressive", plan["entry_aggressive"]),
            ("Entry prudente", plan["entry_prudent"]),
            ("Stop court terme", plan["stop_short"]),
            ("Stop structurel", plan["stop_structural"]),
            ("Target 1", plan["target_1"]),
            ("Target 2", plan["target_2"]),
        ]
    else:
        levels = analysis["basic_levels"]

        lines = [
            ("Entry", levels["entry_price"]),
            ("Stop", levels["stop_loss"]),
            ("Take Profit", levels["take_profit"]),
        ]

    for label, value in lines:
        fig.add_hline(
            y=value,
            line_dash="dash",
            annotation_text=label
        )

    fig.update_layout(
        height=650,
        xaxis_rangeslider_visible=False
    )

    st.plotly_chart(fig, use_container_width=True)


def render_monte_carlo(analysis: dict):
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

    max_paths_to_display = min(50, mc_paths.shape[1])

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


def render_snapshot_mode(ticker: str, price_data: pd.DataFrame, analysis: dict):
    st.subheader(f"Snapshot — {ticker}")

    render_main_metrics(analysis)

    st.info(analysis["commentary"])

    st.divider()

    st.subheader("Performances")

    performance_df = calculate_performance_table(price_data["close"])
    performance_df["Performance"] = performance_df["Performance"].apply(
        lambda x: "N/A" if x is None else f"{x:.2%}"
    )

    st.dataframe(performance_df, use_container_width=True)

    st.subheader("Niveaux 52 semaines")

    levels_52w = analysis["levels_52w"]

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("High 52W", round(levels_52w["high_52w"], 2))
    col2.metric("Low 52W", round(levels_52w["low_52w"], 2))
    col3.metric("Distance High 52W", f"{levels_52w['distance_high']:.2%}")
    col4.metric("Distance Low 52W", f"{levels_52w['distance_low']:.2%}")

    st.divider()

    st.subheader("Niveaux théoriques simples")

    levels = analysis["basic_levels"]

    levels_df = pd.DataFrame([{
        "Prix actuel": analysis["latest_price"],
        "Entry théorique": levels["entry_price"],
        "Stop Loss théorique": levels["stop_loss"],
        "Take Profit théorique": levels["take_profit"],
        "Risk/Reward": levels["risk_reward"]
    }])

    st.dataframe(levels_df, use_container_width=True)

    st.divider()

    st.subheader("Graphique prix")
    render_price_chart(price_data, ticker, analysis, use_trading_plan=False)

    st.divider()

    render_monte_carlo(analysis)

    st.divider()

    with st.expander("Voir les dernières données brutes"):
        st.dataframe(price_data.tail(20), use_container_width=True)


def render_trading_plan_mode(ticker: str, price_data: pd.DataFrame, analysis: dict):
    st.subheader(f"Trading Plan — {ticker}")

    render_main_metrics(analysis)

    st.info(analysis["commentary"])

    st.divider()

    plan = analysis["trading_plan"]

    st.subheader("Plan d’entrée / sortie")

    plan_df = pd.DataFrame([{
        "Prix actuel": analysis["latest_price"],
        "Entry agressive": plan["entry_aggressive"],
        "Entry prudente": plan["entry_prudent"],
        "Stop court terme": plan["stop_short"],
        "Stop structurel": plan["stop_structural"],
        "Target 1": plan["target_1"],
        "Target 2": plan["target_2"],
        "RR agressif": plan["rr_aggressive"],
        "RR prudent": plan["rr_prudent"],
        "Régime de risque": plan["risk_regime"]
    }])

    st.dataframe(plan_df, use_container_width=True)

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Entry agressive", round(plan["entry_aggressive"], 2))
    col2.metric("Entry prudente", round(plan["entry_prudent"], 2))
    col3.metric("Stop court terme", round(plan["stop_short"], 2))
    col4.metric("Target 2", round(plan["target_2"], 2))

    col5, col6, col7 = st.columns(3)

    col5.metric("RR agressif", round(plan["rr_aggressive"], 2))
    col6.metric("RR prudent", round(plan["rr_prudent"], 2))
    col7.metric("Régime", plan["risk_regime"])

    st.divider()

    st.subheader("Lecture du plan")

    if analysis["signal"] == "BUY_ZONE" and plan["rr_aggressive"] >= 2:
        st.success(
            "Configuration favorable selon le modèle. Le plan agressif présente un risk/reward intéressant, "
            "mais il reste nécessaire de respecter le stop."
        )
    elif analysis["signal"] in ["BUY_ZONE", "WATCH"] and plan["rr_prudent"] >= 1.5:
        st.warning(
            "Configuration surveillable. Le plan prudent est préférable pour éviter une entrée trop haute."
        )
    else:
        st.error(
            "Configuration fragile. Le modèle ne montre pas un avantage suffisant pour une entrée immédiate."
        )

    st.markdown(
        """
        **Règle de lecture :**
        - `Entry agressive` : entrée proche du prix actuel, plus risquée.
        - `Entry prudente` : entrée après repli, meilleur contrôle du risque.
        - `Stop court terme` : invalidation rapide.
        - `Stop structurel` : invalidation plus large.
        - `Target 1` : premier objectif.
        - `Target 2` : objectif principal du plan.
        """
    )

    st.divider()

    st.subheader("Graphique avec plan de trade")
    render_price_chart(price_data, ticker, analysis, use_trading_plan=True)

    st.divider()

    render_monte_carlo(analysis)


def render_risk_monitor_mode(ticker: str, price_data: pd.DataFrame, analysis: dict):
    st.subheader(f"Risk Monitor — {ticker}")

    render_main_metrics(analysis)

    st.info(analysis["commentary"])

    st.divider()

    price = analysis["latest_price"]
    atr = analysis["atr"]
    volatility = analysis["volatility"]
    daily_vol = volatility / np.sqrt(252)
    atr_pct = atr / price if price > 0 else 0

    plan = analysis["trading_plan"]
    levels_52w = analysis["levels_52w"]
    mc_paths = analysis["monte_carlo_paths"]

    final_prices = mc_paths[-1, :]
    min_prices = mc_paths.min(axis=0)
    max_prices = mc_paths.max(axis=0)

    prob_finish_negative = float(np.mean(final_prices < price))
    prob_loss_5 = float(np.mean(final_prices <= price * 0.95))

    prob_touch_stop_short = float(np.mean(min_prices <= plan["stop_short"]))
    prob_touch_stop_structural = float(np.mean(min_prices <= plan["stop_structural"]))

    prob_touch_target_1 = float(np.mean(max_prices >= plan["target_1"]))
    prob_touch_target_2 = float(np.mean(max_prices >= plan["target_2"]))

    expected_return_mc = float(np.mean(final_prices / price - 1))
    median_return_mc = float(np.median(final_prices / price - 1))

    risk_table = pd.DataFrame([{
        "Prix actuel": price,
        "Volatilité annualisée": volatility,
        "Volatilité quotidienne estimée": daily_vol,
        "ATR 14": atr,
        "ATR % prix": atr_pct,
        "Max Drawdown": analysis["max_drawdown"],
        "Distance High 52W": levels_52w["distance_high"],
        "Distance Low 52W": levels_52w["distance_low"],
        "Régime de risque": plan["risk_regime"]
    }])

    st.subheader("Tableau de risque")

    display_risk_table = risk_table.copy()

    percent_cols = [
        "Volatilité annualisée",
        "Volatilité quotidienne estimée",
        "ATR % prix",
        "Max Drawdown",
        "Distance High 52W",
        "Distance Low 52W"
    ]

    for col in percent_cols:
        display_risk_table[col] = display_risk_table[col].apply(lambda x: f"{x:.2%}")

    st.dataframe(display_risk_table, use_container_width=True)

    st.divider()

    st.subheader("Probabilités Monte Carlo à 30 jours")

    prob_df = pd.DataFrame([{
        "Finir en perte": prob_finish_negative,
        "Finir sous -5%": prob_loss_5,
        "Toucher Stop court terme": prob_touch_stop_short,
        "Toucher Stop structurel": prob_touch_stop_structural,
        "Toucher Target 1": prob_touch_target_1,
        "Toucher Target 2": prob_touch_target_2,
        "Expected Return MC": expected_return_mc,
        "Median Return MC": median_return_mc
    }])

    display_prob_df = prob_df.copy()

    for col in display_prob_df.columns:
        display_prob_df[col] = display_prob_df[col].apply(lambda x: f"{x:.2%}")

    st.dataframe(display_prob_df, use_container_width=True)

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Prob. toucher stop court", f"{prob_touch_stop_short:.2%}")
    col2.metric("Prob. toucher target 1", f"{prob_touch_target_1:.2%}")
    col3.metric("Finir en perte", f"{prob_finish_negative:.2%}")
    col4.metric("Expected Return MC", f"{expected_return_mc:.2%}")

    st.divider()

    st.subheader("Diagnostic risque")

    if volatility > 0.60 or prob_touch_stop_short > 0.45:
        st.error(
            "Risque élevé. Le titre est très volatil ou la probabilité de toucher le stop court terme est importante. "
            "Une entrée agressive serait fragile."
        )
    elif volatility > 0.35 or prob_touch_stop_short > 0.30:
        st.warning(
            "Risque modéré à élevé. Le trade peut être intéressant, mais il nécessite une taille de position réduite "
            "et un stop strict."
        )
    else:
        st.success(
            "Risque relativement contenu selon les métriques actuelles. Le trade reste à valider avec le momentum "
            "et le contexte de marché."
        )

    if prob_touch_target_1 > prob_touch_stop_short:
        st.success(
            "Le modèle Monte Carlo donne une probabilité d'atteindre Target 1 supérieure à celle de toucher le stop court terme."
        )
    else:
        st.warning(
            "Le modèle Monte Carlo donne une probabilité de toucher le stop court terme supérieure ou proche de celle d'atteindre Target 1."
        )

    st.divider()

    st.subheader("Graphique avec niveaux de risque")
    render_price_chart(price_data, ticker, analysis, use_trading_plan=True)

    st.divider()

    render_monte_carlo(analysis)


# ============================================================
# APP
# ============================================================

render_header()

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

    mode = st.selectbox(
        "Mode d'analyse",
        ["Snapshot", "Trading Plan", "Risk Monitor"],
        index=0
    )

    run_analysis = st.button("Analyser")


if run_analysis:
    try:
        with st.spinner(f"Analyse de {ticker} en cours..."):
            price_data = get_price_history(ticker, period=period, interval=interval)
            analysis = analyze_ticker(price_data)

        if mode == "Snapshot":
            render_snapshot_mode(ticker, price_data, analysis)

        elif mode == "Trading Plan":
            render_trading_plan_mode(ticker, price_data, analysis)

        elif mode == "Risk Monitor":
            render_risk_monitor_mode(ticker, price_data, analysis)

    except Exception as e:
        st.error(f"Erreur : {e}")

else:
    st.info("Entre un ticker dans la barre latérale, choisis un mode, puis clique sur Analyser.")