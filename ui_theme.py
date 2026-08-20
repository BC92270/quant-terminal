import streamlit as st


def inject_global_theme():
    st.markdown(
        """
        <style>
        :root {
            --qt-bg: #050B14;
            --qt-bg-2: #07111F;
            --qt-panel: #0D1726;
            --qt-panel-2: #101D30;
            --qt-border: rgba(100, 140, 190, 0.28);
            --qt-border-strong: rgba(110, 170, 230, 0.40);
            --qt-text: #F2F6FC;
            --qt-muted: #9CB0C3;
            --qt-accent: #4DA3FF;
            --qt-accent-2: #18D2FF;
            --qt-warning: #A7A322;
            --qt-danger: #F05A6E;
            --qt-success: #24C78A;
        }

        .stApp {
            background:
                radial-gradient(circle at 50% -10%, rgba(24, 210, 255, 0.11), transparent 34%),
                radial-gradient(circle at 100% 0%, rgba(77, 163, 255, 0.07), transparent 25%),
                linear-gradient(180deg, var(--qt-bg), var(--qt-bg-2) 28%, #050B14 100%);
            color: var(--qt-text);
        }

        section.main > div {
            max-width: 1720px;
            padding-top: 1.2rem;
            padding-bottom: 2.5rem;
        }

        h1, h2, h3, h4, h5, h6 {
            color: var(--qt-text) !important;
            letter-spacing: -0.025em;
        }

        p, span, label, div {
            color: inherit;
        }

        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #07111F, #091423);
            border-right: 1px solid rgba(100, 140, 190, 0.18);
        }

        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3,
        section[data-testid="stSidebar"] label {
            color: var(--qt-text) !important;
        }

        div[data-testid="stMetric"],
        div[data-testid="stExpander"],
        div[data-testid="stForm"] {
            border-radius: 16px;
        }

        div[data-testid="stDataFrame"] {
            border: 1px solid rgba(100, 140, 190, 0.22);
            border-radius: 14px;
            overflow: hidden;
        }

        div[data-baseweb="input"] > div,
        div[data-baseweb="select"] > div,
        textarea {
            background: rgba(13, 23, 38, 0.96) !important;
            border: 1px solid rgba(100, 140, 190, 0.30) !important;
            border-radius: 12px !important;
            color: var(--qt-text) !important;
        }

        input, textarea {
            color: var(--qt-text) !important;
        }

        div.stButton > button {
            background: linear-gradient(90deg, #0F6FFF, #18D2FF);
            color: white;
            border: 0;
            border-radius: 12px;
            font-weight: 800;
            padding: 0.65rem 1.2rem;
            box-shadow: 0 0 22px rgba(24, 210, 255, 0.16);
        }

        div.stButton > button:hover {
            filter: brightness(1.08);
            border: 0;
            color: white;
        }

        button[data-baseweb="tab"] {
            color: var(--qt-muted) !important;
            background: transparent !important;
        }

        button[data-baseweb="tab"][aria-selected="true"] {
            color: var(--qt-text) !important;
            border-bottom: 2px solid var(--qt-accent) !important;
        }

        .qt-topbar {
            display: grid;
            grid-template-columns: 1.3fr 1fr;
            gap: 18px;
            align-items: stretch;
            margin-bottom: 22px;
        }

        .qt-terminal-title {
            border: 1px solid var(--qt-border);
            background: linear-gradient(180deg, rgba(16,29,48,0.92), rgba(8,17,31,0.96));
            border-radius: 20px;
            padding: 20px 24px;
            box-shadow: 0 18px 40px rgba(0,0,0,0.20);
        }

        .qt-terminal-title-main {
            font-size: 34px;
            line-height: 1.05;
            font-weight: 900;
            color: var(--qt-text);
            margin-bottom: 8px;
        }

        .qt-terminal-title-sub {
            font-size: 14px;
            color: var(--qt-muted);
        }

        .qt-terminal-status {
            border: 1px solid var(--qt-border);
            background: linear-gradient(180deg, rgba(13,23,38,0.94), rgba(6,14,27,0.96));
            border-radius: 20px;
            padding: 20px 24px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            box-shadow: 0 18px 40px rgba(0,0,0,0.20);
        }

        .qt-terminal-status-label {
            color: var(--qt-muted);
            font-size: 13px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 8px;
        }

        .qt-terminal-status-value {
            color: var(--qt-accent-2);
            font-size: 26px;
            font-weight: 900;
        }

        .qt-banner {
            background: rgba(77, 163, 255, 0.16);
            border: 1px solid rgba(77, 163, 255, 0.26);
            color: #DDEBFF;
            border-radius: 14px;
            padding: 14px 16px;
            font-size: 17px;
            margin: 12px 0 18px 0;
        }

        .qt-banner-warning {
            background: rgba(167, 163, 34, 0.22);
            border: 1px solid rgba(167, 163, 34, 0.36);
            color: #F2F0C2;
        }

        @media (max-width: 900px) {
            .qt-topbar {
                grid-template-columns: 1fr;
            }

            .qt-terminal-title-main {
                font-size: 28px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_terminal_header(ticker: str | None = None):
    ticker_text = str(ticker or "No active ticker").upper()

    st.markdown(
        f"""
        <div class="qt-topbar">
            <div class="qt-terminal-title">
                <div class="qt-terminal-title-main">JARVIS Quant Terminal</div>
                <div class="qt-terminal-title-sub">
                    Options intelligence • Futures tape • Macro regime • Execution support
                </div>
            </div>
            <div class="qt-terminal-status">
                <div class="qt-terminal-status-label">Active workspace</div>
                <div class="qt-terminal-status-value">{ticker_text}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_qt_banner(text: str, kind: str = "info"):
    cls = "qt-banner"
    if kind == "warning":
        cls += " qt-banner-warning"

    st.markdown(
        f'<div class="{cls}">{text}</div>',
        unsafe_allow_html=True,
    )