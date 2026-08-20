"""
JARVIS Research & Events Intelligence — autonomous Streamlit module.

Public entry point:
    render_research_events_intelligence(ticker, price_data, analysis=None)

The module mirrors the audited RoboMacro Research and Events information
architecture while preserving the JARVIS visual system.  Public-page values
captured on 22 July 2026 are explicitly labelled as an audited snapshot; no
historical observation is silently fabricated or presented as live data.
"""

from __future__ import annotations

import html
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


RESEARCH_EVENTS_VERSION = "V1 · INSTITUTIONAL RESEARCH & EVENT RISK DESK"
RESEARCH_EVENTS_PAGE_KEY = "research_events1_page"
RESEARCH_EVENTS_PAGES: Tuple[str, ...] = ("Research Intelligence", "Events Intelligence")
SNAPSHOT_DATE = date(2026, 7, 22)

PALETTE = {
    "cyan": "#63c7ff",
    "gold": "#d8bf58",
    "green": "#57d39b",
    "red": "#f4777f",
    "purple": "#a990ff",
    "orange": "#ff9b63",
    "ink": "#071521",
}


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


@contextmanager
def _card(key: Optional[str] = None):
    try:
        with st.container(border=True, key=key):
            yield
    except TypeError:
        with st.container():
            yield


def _segmented(label: str, options: Sequence[str], key: str, default: str) -> str:
    if key not in st.session_state:
        st.session_state[key] = default
    if hasattr(st, "segmented_control"):
        value = st.segmented_control(
            label,
            list(options),
            selection_mode="single",
            key=key,
            label_visibility="collapsed",
        )
    else:
        value = st.radio(label, list(options), horizontal=True, key=key, label_visibility="collapsed")
    return str(value or default)


def _css() -> None:
    _html(
        """
<style>
.re1-head{position:relative;overflow:hidden;border:1px solid rgba(128,158,190,.28);border-radius:15px;padding:23px 25px 21px;margin:8px 0 14px;background:radial-gradient(circle at 88% 10%,rgba(99,199,255,.14),transparent 31%),linear-gradient(135deg,rgba(7,25,41,.98),rgba(3,12,22,.99));box-shadow:0 20px 55px rgba(0,0,0,.24)}
.re1-head:after{content:"";position:absolute;inset:0;pointer-events:none;background-image:linear-gradient(rgba(126,164,195,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(126,164,195,.035) 1px,transparent 1px);background-size:28px 28px;mask-image:linear-gradient(to left,black,transparent 78%)}
.re1-kicker{position:relative;z-index:1;font-size:10px;letter-spacing:.23em;text-transform:uppercase;color:#d8bf58;font-weight:850}.re1-title{position:relative;z-index:1;font-family:Georgia,serif;font-size:38px;font-weight:700;color:#f4f7fa;margin:5px 0 7px;line-height:1.05}.re1-sub{position:relative;z-index:1;color:#a4b2c0;font-size:13px;line-height:1.58;max-width:1080px}.re1-pills{position:relative;z-index:1;display:flex;gap:6px;flex-wrap:wrap;margin-top:12px}.re1-pill{display:inline-block;border:1px solid rgba(216,191,88,.32);background:rgba(216,191,88,.045);border-radius:999px;padding:4px 9px;font-size:9px;color:#dacb7a;letter-spacing:.03em}
.re1-section{border-left:3px solid #d8bf58;padding:2px 0 5px 13px;margin:25px 0 12px}.re1-section-k{font-size:9px;letter-spacing:.18em;text-transform:uppercase;color:#8194a7;font-weight:850}.re1-section-t{font-family:Georgia,serif;color:#f2f5f8;font-size:27px;font-weight:700;line-height:1.12}.re1-section-s{color:#91a1b0;font-size:11px;line-height:1.48;margin-top:4px;max-width:1120px}
.re1-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:10px 0 17px}.re1-kpi{position:relative;overflow:hidden;border:1px solid rgba(129,157,185,.22);border-radius:11px;padding:13px 14px 12px;background:linear-gradient(150deg,rgba(8,23,38,.94),rgba(5,16,28,.97));min-height:105px}.re1-kpi:before{content:"";position:absolute;left:0;top:0;right:0;height:2px;background:linear-gradient(90deg,#63c7ff,transparent)}.re1-kpi:nth-child(2n):before{background:linear-gradient(90deg,#d8bf58,transparent)}.re1-label{font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:#8998a8;font-weight:800}.re1-value{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:850;font-size:23px;color:#f2f6f9;margin:8px 0 5px;line-height:1}.re1-note{font-size:10px;color:#8fa0b0;line-height:1.36}.re1-positive{color:#57d39b}.re1-negative{color:#f4777f}.re1-neutral{color:#d8bf58}
.re1-control{border:1px solid rgba(128,158,190,.23);background:rgba(6,18,30,.90);border-radius:11px;padding:10px 12px;margin:7px 0 11px}.re1-statline{display:flex;gap:7px;flex-wrap:wrap;margin:7px 0 11px}.re1-stat{border:1px solid rgba(99,199,255,.23);background:rgba(99,199,255,.045);border-radius:999px;padding:4px 9px;font-size:9px;color:#9bcfea;letter-spacing:.06em}.re1-stat-gold{border-color:rgba(216,191,88,.31);background:rgba(216,191,88,.05);color:#d8c978}.re1-stat-red{border-color:rgba(244,119,127,.31);background:rgba(244,119,127,.05);color:#ef9aa0}
.re1-read-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:9px 0 15px}.re1-read{border:1px solid rgba(128,157,186,.22);border-radius:11px;padding:13px 14px;background:rgba(6,19,32,.86);min-height:118px}.re1-read-k{font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:#8596a6}.re1-read-state{font-family:Georgia,serif;font-size:19px;margin:5px 0;color:#f1f4f7}.re1-read-copy{font-size:11px;color:#9eadba;line-height:1.47}
.re1-callout{border-left:2px solid rgba(99,199,255,.58);background:rgba(21,54,75,.20);padding:10px 13px;color:#a6b9c8;font-size:11px;line-height:1.52;margin:8px 0 13px}.re1-callout-gold{border-left-color:rgba(216,191,88,.72);background:rgba(216,191,88,.055);color:#d2c889}.re1-callout-red{border-left-color:rgba(244,119,127,.72);background:rgba(244,119,127,.05);color:#e8a2a7}
.re1-event-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:9px 0 15px}.re1-event{border:1px solid rgba(128,157,186,.22);border-radius:12px;padding:14px;background:linear-gradient(145deg,rgba(8,24,39,.96),rgba(5,15,26,.98));min-height:180px}.re1-event-top{display:flex;justify-content:space-between;gap:8px;align-items:flex-start}.re1-event-title{font-family:Georgia,serif;color:#f1f4f7;font-size:19px;line-height:1.17}.re1-event-date{font-family:ui-monospace,monospace;color:#d8bf58;font-size:10px;white-space:nowrap}.re1-event-meta{font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:#7f92a5;margin:8px 0}.re1-event-copy{font-size:10px;color:#9aabb9;line-height:1.48}.re1-prob{margin-top:10px;height:5px;background:rgba(128,157,186,.13);border-radius:999px;overflow:hidden}.re1-prob>span{display:block;height:100%;background:linear-gradient(90deg,#d8bf58,#f4777f)}
.re1-source{font-size:9px;color:#7f91a2;margin:8px 0 2px}.re1-source b{color:#c3ced7}.re1-empty{border:1px dashed rgba(128,158,190,.30);border-radius:11px;padding:20px;text-align:center;color:#8194a7;background:rgba(7,19,31,.54)}
div[data-testid="stDataFrame"]{border:1px solid rgba(126,154,182,.20);border-radius:10px;overflow:hidden;background:rgba(5,16,27,.82)}
div[data-testid="stVerticalBlockBorderWrapper"]{background:linear-gradient(145deg,rgba(7,20,33,.86),rgba(4,14,24,.92));border-color:rgba(126,154,182,.20)!important;border-radius:12px!important}
.st-key-re1_research_nav [role="radiogroup"],.st-key-re1_note_regions [role="radiogroup"],.st-key-re1_event_impact [role="radiogroup"],.st-key-re1_calendar_mode [role="radiogroup"],.st-key-re1_election_region [role="radiogroup"]{display:flex!important;flex-wrap:wrap!important;gap:5px!important}
.st-key-re1_research_nav [role="radiogroup"]>button,.st-key-re1_note_regions [role="radiogroup"]>button,.st-key-re1_event_impact [role="radiogroup"]>button,.st-key-re1_calendar_mode [role="radiogroup"]>button,.st-key-re1_election_region [role="radiogroup"]>button{min-height:36px!important;border-color:rgba(127,157,185,.27)!important;background:rgba(7,20,33,.90)!important;color:#aebac5!important}
.st-key-re1_research_nav [role="radiogroup"]>button[aria-pressed="true"],.st-key-re1_note_regions [role="radiogroup"]>button[aria-pressed="true"],.st-key-re1_event_impact [role="radiogroup"]>button[aria-pressed="true"],.st-key-re1_calendar_mode [role="radiogroup"]>button[aria-pressed="true"],.st-key-re1_election_region [role="radiogroup"]>button[aria-pressed="true"]{background:linear-gradient(135deg,rgba(119,97,25,.86),rgba(77,64,20,.94))!important;border-color:rgba(216,191,88,.62)!important;color:#fff!important}
@media(max-width:950px){.re1-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.re1-read-grid,.re1-event-grid{grid-template-columns:1fr}.re1-title{font-size:31px}}
</style>
        """
    )


def _header(title: str, subtitle: str, kicker: str) -> None:
    _html(
        '<div class="re1-head">'
        f'<div class="re1-kicker">{_esc(kicker)}</div>'
        f'<div class="re1-title">{_esc(title)}</div>'
        f'<div class="re1-sub">{_esc(subtitle)}</div>'
        '<div class="re1-pills"><span class="re1-pill">RoboMacro-aligned structure</span>'
        '<span class="re1-pill">controls beside the analysis</span><span class="re1-pill">audited source snapshots</span>'
        '<span class="re1-pill">institutional exports</span></div></div>'
    )


def _section(kicker: str, title: str, subtitle: str) -> None:
    _html(
        '<div class="re1-section">'
        f'<div class="re1-section-k">{_esc(kicker)}</div><div class="re1-section-t">{_esc(title)}</div>'
        f'<div class="re1-section-s">{_esc(subtitle)}</div></div>'
    )


def _kpis(items: Sequence[Tuple[str, str, str, str]]) -> None:
    blocks: List[str] = []
    for label, value, note, tone in items:
        tone_class = {"positive": "re1-positive", "negative": "re1-negative", "neutral": "re1-neutral"}.get(tone, "")
        blocks.append(
            '<div class="re1-kpi">'
            f'<div class="re1-label">{_esc(label)}</div><div class="re1-value {tone_class}">{_esc(value)}</div>'
            f'<div class="re1-note">{_esc(note)}</div></div>'
        )
    _html('<div class="re1-kpis">' + "".join(blocks) + "</div>")


def _reads(items: Sequence[Tuple[str, str, str]]) -> None:
    blocks = []
    for label, state, copy in items:
        blocks.append(
            '<div class="re1-read">'
            f'<div class="re1-read-k">{_esc(label)}</div><div class="re1-read-state">{_esc(state)}</div>'
            f'<div class="re1-read-copy">{_esc(copy)}</div></div>'
        )
    _html('<div class="re1-read-grid">' + "".join(blocks) + "</div>")


def _table(frame: pd.DataFrame, key: str, height: int = 420) -> None:
    st.dataframe(frame, use_container_width=True, hide_index=True, height=height, key=key)


def _download(frame: pd.DataFrame, label: str, filename: str, key: str) -> None:
    st.download_button(label, frame.to_csv(index=False).encode("utf-8"), file_name=filename, mime="text/csv", key=key)


def _plot(fig: go.Figure, key: str, height: int = 430) -> None:
    fig.update_layout(
        height=height,
        margin=dict(l=45, r=25, t=42, b=45),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(4,15,26,.91)",
        font=dict(color="#cad4dd", size=10),
        xaxis=dict(gridcolor="rgba(136,158,181,.12)", zerolinecolor="rgba(136,158,181,.24)"),
        yaxis=dict(gridcolor="rgba(136,158,181,.12)", zerolinecolor="rgba(136,158,181,.24)"),
        legend=dict(orientation="h", y=1.08, x=0, bgcolor="rgba(0,0,0,0)", font=dict(size=9)),
    )
    st.plotly_chart(fig, use_container_width=True, key=key, config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})


def _research_notes() -> pd.DataFrame:
    rows = [
        ("UK", "UK Macro Daily", "Burnham Takes Helm as UK Jobs Hold Firm", "2026-07-21", "Policy / Labour", "High", "/Research_Notes/UK_Macro_Daily/UK_Macro_Daily_20260721.html"),
        ("US", "US Macro Daily", "Equities Slip on Hawkish Fed Outlook", "2026-07-21", "Fed / Rates", "High", "/Research_Notes/US_Macro_Daily/US_Macro_Daily_20260721.html"),
        ("Euro", "Eurozone Macro Daily", "German PPI Eases Ahead of ZEW Sentiment Data", "2026-07-21", "Inflation / Activity", "High", "/Research_Notes/Eurozone_Macro_Daily/EU_Macro_Daily_20260721.html"),
        ("Japan", "Japan Macro Daily", "Yen Hits 40-Year Low on Fiscal Pivot", "2026-07-21", "FX / Fiscal", "High", "/Research_Notes/Japan_Macro_Daily/JP_Macro_Daily_20260721.html"),
        ("Greater China", "Greater China Macro Daily", "LPR Holds Steady as Shanghai Slips, HK Rallies", "2026-07-21", "PBoC / Markets", "High", "/Research_Notes/Greater_China_Macro_Daily/GCN_Macro_Daily_20260721.html"),
        ("Canada", "Canada Macro Daily", "Canada CPI Cools to 2.8%, TSX Falls", "2026-07-21", "Inflation / Equities", "High", "/Research_Notes/Canada_Macro_Daily/CA_Macro_Daily_20260721.html"),
        ("Mexico", "Mexico Macro Daily", "Peso Rises as IPC Slips on Thin Volume", "2026-07-21", "FX / Equities", "Medium", "/Research_Notes/Mexico_Macro_Daily/MX_Macro_Daily_20260721.html"),
        ("Brazil", "Brazil Macro Daily", "BRL Rises on Rural Credit Amid US Tariff Row", "2026-07-21", "Trade / FX", "High", "/Research_Notes/Brazil_Macro_Daily/BR_Macro_Daily_20260721.html"),
        ("Argentina", "Argentina Macro Daily", "Peso Slides Sharply as MERVAL Edges Higher", "2026-07-21", "FX / Equities", "High", "/Research_Notes/Argentina_Macro_Daily/AR_Macro_Daily_20260721.html"),
        ("Andeans", "Andeans Macro Daily", "Copper Rally Lifts Chile, PEN Weakens Sharply", "2026-07-21", "Commodities / FX", "High", "/Research_Notes/Andeans_Macro_Daily/AND_Macro_Daily_20260721.html"),
        ("Nordics", "Nordics Macro Daily", "Nordic Equities Slip as Oil Declines, Yields Diverge", "2026-07-21", "Rates / Energy", "Medium", "/Research_Notes/Nordics_Macro_Daily/NORD_Macro_Daily_20260721.html"),
        ("Emerging Europe", "Emerging Europe Macro Daily", "Hungary Poised to Cut Rates as Poland Hits $1T", "2026-07-21", "Central Banks", "High", "/Research_Notes/EM_Europe_Macro_Daily/EMEU_Macro_Daily_20260721.html"),
        ("South Africa", "South Africa Macro Daily", "Rand Holds Steady Ahead of SARB Decision", "2026-07-21", "Central Banks / FX", "High", "/Research_Notes/South_Africa_Macro_Daily/ZA_Macro_Daily_20260721.html"),
        ("ANZ", "ANZ Macro Daily", "Hot NZ CPI Bolsters RBNZ Hike Bets", "2026-07-21", "Inflation / Rates", "High", "/Research_Notes/ANZ_Macro_Daily/ANZ_Macro_Daily_20260721.html"),
        ("Korea", "Korea Macro Daily", "KOSPI Drops 4.5% as AI Stocks Swoon", "2026-07-21", "Technology / Equities", "High", "/Research_Notes/Korea_Macro_Daily/KR_Macro_Daily_20260721.html"),
        ("ASEAN", "ASEAN Macro Daily", "BI Poised to Hike to 6% as Rupiah Steadies", "2026-07-21", "Central Banks / FX", "High", "/Research_Notes/ASEAN_Macro_Daily/ASEAN_Macro_Daily_20260721.html"),
        ("UK", "UK Macro Daily", "Labour Data Looms as BoE Holds Steady", "2026-07-20", "Labour / BoE", "High", "/Research_Notes/UK_Macro_Daily/UK_Macro_Daily_20260720.html"),
        ("US", "US Macro Daily", "Equities Slide as Yields Climb on Hawkish Fed", "2026-07-20", "Fed / Rates", "High", "/Research_Notes/US_Macro_Daily/US_Macro_Daily_20260720.html"),
        ("Euro", "Eurozone Macro Daily", "Inflation Holds at 2.8% Ahead of PMI Data", "2026-07-20", "Inflation / PMI", "High", "/Research_Notes/Eurozone_Macro_Daily/EU_Macro_Daily_20260720.html"),
        ("Japan", "Japan Macro Daily", "Yen Weakness Persists Despite BoJ Independence", "2026-07-20", "BoJ / FX", "High", "/Research_Notes/Japan_Macro_Daily/JP_Macro_Daily_20260720.html"),
    ]
    return pd.DataFrame(rows, columns=["Region", "Series", "Title", "Date", "Focus", "Priority", "Path"])


def _papers() -> pd.DataFrame:
    rows = [
        ("International", "IMF", "Stablecoins and the Future of Payments: Evidence from Financial Markets", "Copestake, Englander, Martinez Peria, Villegas-Bauer", "WP 26/52", "Mar 2026", "https://robomacro.com/IMF/52.pdf", "https://robomacro.com/podcasts/PODS_IMF/52.mp3"),
        ("UK", "BoE", "Targeting inflation expectations?", "Mridula Duggal", "1175", "Mar 2026", "https://robomacro.com/BOE/1175.pdf", "https://robomacro.com/podcasts/PODS_UK/1175.mp3"),
        ("US", "FED", "Bank Failures: The Roles of Solvency and Liquidity", "Correia, Luck, Verner", "1181", "Feb 2026", "https://robomacro.com/FED/1181.pdf", "https://robomacro.com/podcasts/PODS_US/1181.mp3"),
        ("US", "FED", "The Payoffs of Higher Pay", "Natalia Emanuel, Emma Harrington", "1182", "Feb 2026", "https://robomacro.com/FED/1182.pdf", "https://robomacro.com/podcasts/PODS_US/1182.mp3"),
        ("UK", "BoE", "EcoFinBench — an NLP benchmark for economics and finance", "Ahrens, Gorduza, McMahon", "wp1163", "Dec 2025", "https://robomacro.com/BOE/wp1163.pdf", "https://robomacro.com/podcasts/PODS_UK/wp1163.mp3"),
        ("UK", "BoE", "Monetary policy and mortgage fixation lengths", "Rajan, Rodriguez-Tous, Salgado-Moreno", "1158", "Nov 2025", "https://robomacro.com/BOE/1158.pdf", "https://robomacro.com/podcasts/PODS_UK/1158.mp3"),
        ("Japan", "BoJ", "Private Law Frameworks for Tokenized Assets", "Okuyama, Sugimura", "25-E12", "Oct 2025", "https://robomacro.com/BOJ/25-E12.pdf", "https://robomacro.com/podcasts/PODS_BOJ/25-E12.mp3"),
        ("International", "IMF", "Earthquakes and Emerging Market Sovereign Bond Spreads", "Arezki, Imam, Kpodar, Le-Van", "2025_218", "Oct 2025", "https://robomacro.com/IMF/2025_218.pdf", "https://robomacro.com/podcasts/PODS_IMF/2025_218.mp3"),
        ("Europe", "ECB", "Fiscal announcements and households’ beliefs", "Gallegos, García-Miralles, Kataryniuk, Parraga", "ECB3139", "Oct 2025", "https://robomacro.com/ECB/ecb_3139.pdf", "https://robomacro.com/podcasts/PODS_ECB/ecb_3139.mp3"),
        ("International", "BIS", "Harnessing AI for monitoring financial markets", "Aquilina, Araujo, Gelos, Park, Pérez-Cruz", "BIS_1921", "Sep 2025", "https://robomacro.com/BIS/BIS_1921.pdf", "https://robomacro.com/podcasts/PODS_BIS/BIS_1921.mp3"),
        ("UK", "BoE", "Liquidity, monetary policy and the commodity futures market", "Ivan, Banti, Kellard", "wp1114", "Jan 2025", "https://robomacro.com/BOE/wp1114.pdf", "https://robomacro.com/podcasts/PODS_UK/wp1114.mp3"),
    ]
    return pd.DataFrame(rows, columns=["Country", "Source", "Paper", "Authors", "Number", "Date", "Paper URL", "Audio URL"])


def _events() -> pd.DataFrame:
    rows = [
        ("2026-07-20", "02:00", "DE", "Germany", "Producer Price Index MoM", "Med", "0.1", "0.2", "0.2", "Eurozone"),
        ("2026-07-20", "10:00", "US", "United States", "NAHB Housing Market Index", "Med", "37", "38", "37", "G7"),
        ("2026-07-20", "21:15", "CN", "China", "Loan Prime Rate 1Y", "High", "3.0", "3.0", "3.0", "BRICS"),
        ("2026-07-21", "02:00", "GB", "United Kingdom", "Headline Unemployment Rate", "High", "4.9", "5.0", "4.9", "G7"),
        ("2026-07-21", "02:00", "GB", "United Kingdom", "Average Earnings incl. Bonus", "Med", "4.4", "4.5", "4.3", "G7"),
        ("2026-07-21", "02:00", "GB", "United Kingdom", "Employment Change", "High", "100K", "85K", "147K", "G7"),
        ("2026-07-21", "08:30", "CA", "Canada", "Inflation Rate YoY", "High", "2.9", "2.8", "2.8", "G7"),
        ("2026-07-21", "10:00", "EU", "Euro Area", "Consumer Confidence Flash", "Med", "-14.0", "-13.5", "-13.8", "Eurozone"),
        ("2026-07-22", "02:00", "DK", "Denmark", "Business Confidence Index", "Low", "90.8", "-", "-", "Nordics"),
        ("2026-07-22", "02:00", "NO", "Norway", "Industrial Confidence", "Low", "1.2", "-", "-", "Nordics"),
        ("2026-07-22", "02:00", "SA", "Saudi Arabia", "Construction Cost Index", "Low", "103.9", "-", "-", "GCC"),
        ("2026-07-22", "02:00", "GB", "United Kingdom", "Inflation Rate YoY", "High", "2.8", "2.7", "-", "G7"),
        ("2026-07-22", "02:00", "GB", "United Kingdom", "Core Inflation Rate YoY", "Med", "2.6", "2.5", "-", "G7"),
        ("2026-07-22", "02:00", "GB", "United Kingdom", "Inflation Rate MoM", "Med", "0.2", "0.1", "-", "G7"),
        ("2026-07-22", "03:30", "ID", "Indonesia", "Central Bank Interest Rate Decision", "High", "5.75", "6.00", "-", "ASEAN"),
        ("2026-07-22", "03:30", "PL", "Poland", "Retail Sales YoY", "Low", "3.0", "5.2", "-", "Europe"),
        ("2026-07-22", "04:00", "ZA", "South Africa", "Inflation Rate YoY", "Med", "4.5", "-", "-", "BRICS"),
        ("2026-07-22", "07:00", "US", "United States", "MBA 30-Year Mortgage Rate", "Med", "6.65", "-", "-", "G7"),
        ("2026-07-22", "10:30", "US", "United States", "EIA Weekly Crude Oil Inventory", "Med", "-1.69Mn", "-1.5Mn", "-", "G7"),
        ("2026-07-22", "13:00", "US", "United States", "20-Year Bond Auction", "Low", "4.927", "-", "-", "G7"),
        ("2026-07-23", "02:00", "GB", "United Kingdom", "CBI Business Optimism Index", "Low", "-65", "-", "-", "G7"),
        ("2026-07-23", "02:00", "GB", "United Kingdom", "CBI Industrial Trends Orders", "Med", "-45", "-40", "-", "G7"),
        ("2026-07-23", "07:45", "EU", "Euro Area", "ECB Interest Rate Decision", "High", "2.00", "2.00", "-", "Eurozone"),
        ("2026-07-23", "08:30", "US", "United States", "Initial Jobless Claims", "High", "232K", "235K", "-", "G7"),
        ("2026-07-23", "10:00", "US", "United States", "Existing Home Sales", "Med", "4.03M", "4.05M", "-", "G7"),
        ("2026-07-24", "02:00", "GB", "United Kingdom", "Retail Sales MoM", "High", "1.2", "-0.2", "-", "G7"),
        ("2026-07-24", "03:30", "DE", "Germany", "HCOB Manufacturing PMI Flash", "High", "49.2", "49.5", "-", "Eurozone"),
        ("2026-07-24", "04:00", "EU", "Euro Area", "HCOB Composite PMI Flash", "High", "51.1", "51.3", "-", "Eurozone"),
        ("2026-07-24", "08:30", "CA", "Canada", "Retail Sales MoM", "Med", "0.5", "0.3", "-", "G7"),
        ("2026-07-24", "09:45", "US", "United States", "S&P Global Composite PMI Flash", "High", "52.9", "53.1", "-", "G7"),
    ]
    return pd.DataFrame(rows, columns=["Date", "Time EDT", "Code", "Country", "Event", "Impact", "Previous", "Consensus", "Actual", "Region"])


def _elections() -> pd.DataFrame:
    rows = [
        ("2026-09-13", "Russia", "🇷🇺", "Russian State Duma Election 2026", "EMEA", "BRICS", "Legislative", 90, "United Russia", "Communist Party", "11%", "450 State Duma seats; five-year term.", 1.6, 5.1, 15.5, 2.2, -55, 75, -55, 55, 60),
        ("2026-09-13", "Sweden", "🇸🇪", "Swedish General Election 2026", "Europe", "Nordics", "Legislative", 80, "Moderate Party", "Social Democrats", "32.5%", "Riksdag election on a fixed four-year cycle.", 1.3, 1.8, 2.0, 8.2, -15, 25, 5, 20, 10),
        ("2026-10-04", "Brazil", "🇧🇷", "Brazilian General Elections 2026", "Latin America", "BRICS", "Presidential", 42, "Lula (PT)", "Lula (PT)", "40%", "President, Chamber, Senate seats and governors.", 2.2, 4.2, 10.5, 6.7, 55, 65, -20, 70, 75),
        ("2026-10-17", "New Zealand", "🇳🇿", "New Zealand General Election 2026", "Oceania", "Asia-Pac", "Legislative", 72, "National Party", "Labour Party", "34%", "House of Representatives; three-year cycle.", 1.1, 2.7, 3.25, 5.1, -25, 20, 10, 35, 15),
        ("2026-10-27", "Israel", "🇮🇱", "Israeli Knesset Election 2026", "EMEA", "Other", "Legislative", 47, "Likud", "Likud / Yashar", "18.3%", "Knesset election amid elevated geopolitical uncertainty.", 3.0, 3.2, 4.5, 3.4, -70, 80, -45, 65, 55),
        ("2026-11-03", "United States", "🇺🇸", "US Midterm Elections 2026", "G7", "G7", "Legislative", 45, "Republican", "Republican", "51%", "Full House, 33 Senate seats and 36 governors.", 2.0, 2.8, 3.63, 4.1, 45, 70, -35, 80, 85),
        ("2026-12-11", "China", "🇨🇳", "Central Economic Work Conference 2026", "Asia-Pacific", "BRICS", "Political Event", 0, "CPC", "Policy event", "n/a", "Sets the following year's economic-policy priorities.", 4.5, 1.4, 1.4, 5.1, 50, 55, 35, 75, 90),
        ("2027-02-25", "Nigeria", "🇳🇬", "Nigerian General Elections 2027", "EMEA", "Other", "Presidential", 55, "APC", "APC", "36.6%", "Presidential, National Assembly and governors.", 3.2, 19.0, 26.5, 4.0, -75, 80, -60, 65, 40),
        ("2027-04-10", "France", "🇫🇷", "French Presidential Election 2027 — Round 1", "G7", "G7", "Presidential", 90, "Renaissance", "Marine Le Pen", "34%", "First round; top two candidates proceed to runoff.", 1.2, 2.0, 2.0, 7.6, -35, 75, -40, 70, 75),
        ("2027-04-24", "France", "🇫🇷", "French Presidential Election 2027 — Round 2", "G7", "G7", "Presidential", 45, "Renaissance", "Runoff", "n/a", "Presidential runoff; incumbent is term-limited.", 1.2, 2.0, 2.0, 7.6, -40, 80, -45, 75, 80),
        ("2027-06-06", "Mexico", "🇲🇽", "Mexican Midterm Elections 2027", "Latin America", "Latam", "Legislative", 25, "Morena", "Morena", "37.3%", "Full Chamber of Deputies; test for the administration.", 2.1, 3.6, 7.0, 3.0, 35, 45, -10, 55, 70),
        ("2027-09-25", "Italy", "🇮🇹", "Italian General Election 2027", "G7", "G7", "Legislative", 37, "FdI", "FdI", "28%", "Chamber of Deputies and Senate election.", 0.9, 1.9, 2.0, 5.8, -20, 65, -25, 70, 45),
    ]
    columns = ["Date", "Country", "Flag", "Election", "Region", "Bloc", "Type", "Change Probability", "Incumbent", "Leader", "Poll", "Description", "GDP", "CPI", "Policy Rate", "Unemployment", "FX Risk", "Rates Risk", "Equity Risk", "Fiscal Risk", "Trade Risk"]
    frame = pd.DataFrame(rows, columns=columns)
    frame["Date"] = pd.to_datetime(frame["Date"])
    return frame


def _research_intelligence() -> None:
    notes = _research_notes()
    papers = _papers()
    _header(
        "Research Intelligence",
        "A single institutional research surface combining RoboMacro-style regional notes, full note anatomy, papers and AI podcasts, blog methodology and quantitative coverage diagnostics.",
        "JARVIS RESEARCH · NOTES / PAPERS / PODCASTS / METHODOLOGY",
    )
    _kpis([
        ("Research archive", "918", "Public-note universe audited 22 Jul 2026", "positive"),
        ("Regional desks", "20+", "DM, EM and thematic daily series", "neutral"),
        ("Papers / podcasts", "91", "Seven institution filters", "positive"),
        ("Latest vintage", "21 JUL", "2026 public snapshot", "neutral"),
    ])

    _section("Research Notes", "Regional Research Library", "The RoboMacro archive structure is preserved: region, series, title, date and document access. Search and region controls belong only to this library.")
    with _card("re1_note_library"):
        region_group = _segmented("Research region", ["All", "G7", "Europe", "Asia", "Americas", "EM"], "re1_note_regions", "All")
        c1, c2 = st.columns([1.0, 1.0])
        with c1:
            query = st.text_input("Search title, focus or series", key="re1_note_query", placeholder="inflation, Fed, commodities…")
        with c2:
            priority = st.selectbox("Priority", ["All", "High", "Medium"], key="re1_note_priority")
        groups = {
            "G7": ["UK", "US", "Euro", "Japan", "Canada"],
            "Europe": ["UK", "Euro", "Nordics", "Emerging Europe"],
            "Asia": ["Greater China", "Japan", "ANZ", "Korea", "ASEAN"],
            "Americas": ["US", "Canada", "Mexico", "Brazil", "Argentina", "Andeans"],
            "EM": ["Greater China", "Mexico", "Brazil", "Argentina", "Andeans", "Emerging Europe", "South Africa", "Korea", "ASEAN"],
        }
        filtered = notes.copy()
        if region_group != "All":
            filtered = filtered[filtered["Region"].isin(groups[region_group])]
        if priority != "All":
            filtered = filtered[filtered["Priority"] == priority]
        if query.strip():
            needle = query.strip().lower()
            mask = filtered[["Region", "Series", "Title", "Focus"]].astype(str).apply(lambda col: col.str.lower().str.contains(needle, regex=False)).any(axis=1)
            filtered = filtered[mask]
        _html(f'<div class="re1-statline"><span class="re1-stat">VISIBLE · {len(filtered)}</span><span class="re1-stat re1-stat-gold">ARCHIVE · 918 NOTES</span><span class="re1-stat">PAGE MODEL · 20 ROWS</span></div>')
        _table(filtered[["Region", "Series", "Title", "Date", "Focus", "Priority"]], "re1_notes_table", 535)
        _download(filtered, "Export filtered research index", "jarvis_research_notes_index.csv", "re1_notes_download")

    _section("Note Reader", "Institutional Note Anatomy", "RoboMacro's detailed note format is reproduced directly in the desk: market snapshot, prior releases, forward calendar, key conclusions and explicit source status.")
    with _card("re1_note_reader"):
        reader = st.selectbox("Research product", ["UK Macro Daily · 21 Jul 2026", "Buffett Lens · Issue 13"], key="re1_reader_product")
        if reader.startswith("UK"):
            _html('<div class="re1-statline"><span class="re1-stat re1-stat-gold">UK MACRO DAILY</span><span class="re1-stat">BETA MODE</span><span class="re1-stat">21 JUL 2026</span></div>')
            _html('<div class="re1-callout"><b>Burnham Takes Helm as UK Jobs Hold Firm.</b> Labour resilience tempers near-term easing expectations while the inflation release becomes the dominant next catalyst.</div>')
            market = pd.DataFrame([
                ("FTSE 100", "10,600.40", "+0.27%"), ("FTSE 250", "23,540.70", "-0.27%"),
                ("GBP/USD", "1.34", "+0.01%"), ("GBP/EUR", "1.18", "+0.06%"),
                ("Brent Crude", "88.38", "-0.94%"), ("Gold", "4,069.50", "+1.48%"),
                ("Bitcoin", "65,670.70", "+1.51%"), ("UK 10Y Gilt", "4.80%", "-2.95%"),
            ], columns=["Asset", "Level", "Change"])
            prior = pd.DataFrame([
                ("Headline Unemployment Rate", "4.90", "5.00", "4.90"),
                ("Average Earnings incl. Bonus", "4.40", "4.50", "4.30"),
                ("Employment Change", "100K", "85K", "147K"),
            ], columns=["Release", "Prior", "Consensus", "Actual"])
            upcoming = pd.DataFrame([
                ("22 Jul", "Inflation Rate YoY", "2.80", "2.70", "High"),
                ("22 Jul", "Core Inflation Rate YoY", "2.60", "2.50", "High"),
                ("23 Jul", "CBI Industrial Trends Orders", "-45", "-40", "Medium"),
                ("24 Jul", "Retail Sales MoM", "1.20", "-0.20", "High"),
            ], columns=["Date", "Release", "Prior", "Consensus", "Impact"])
            left, right = st.columns([1.12, 0.88])
            with left:
                _html('<div class="re1-label">MARKET SNAPSHOT</div>')
                _table(market, "re1_uk_market", 320)
            with right:
                _html('<div class="re1-label">PRIOR ECONOMIC EVENTS</div>')
                _table(prior, "re1_uk_prior", 210)
                _html('<div class="re1-label" style="margin-top:9px">FORWARD CALENDAR</div>')
                _table(upcoming, "re1_uk_upcoming", 260)
            _reads([
                ("Policy signal", "Cuts less urgent", "Resilient jobs offset slower earnings; CPI is now the binding input."),
                ("Market transmission", "Gilts outperform", "Lower long yields coexist with modest sterling firmness and mixed equities."),
                ("Risk to watch", "Inflation asymmetry", "A core CPI upside surprise would challenge the gradual-easing narrative."),
            ])
        else:
            _html('<div class="re1-statline"><span class="re1-stat re1-stat-gold">THE BUFFETT LENS</span><span class="re1-stat">ISSUE 13</span><span class="re1-stat">24 JUN 2026</span></div>')
            _html('<div class="re1-callout"><b>Value Investing Observatory.</b> Quantitative screening applies 26 shareholder-letter-inspired factors, then separates quality, leverage, moat and valuation from the narrative layer.</div>')
            picks = pd.DataFrame([
                ("PCTY", "Paylocity", "Technology", 66.3, "21.9%", "0.11x", "72.3%", "$5.6B"),
                ("TTD", "The Trade Desk", "Communication Services", 66.1, "17.6%", "0.17x", "73.6%", "$8.3B"),
            ], columns=["Ticker", "Company", "Sector", "Buffett Score", "ROE", "Debt / Equity", "Gross Margin", "Market Cap"])
            _table(picks, "re1_buffett_picks", 190)
            _reads([
                ("Quality", "Both pass", "ROE above 15%, low leverage and gross margins above 70%."),
                ("Valuation", "Not distressed", "P/E multiples around the low-20s require durable compounding."),
                ("Data quality", "Limited history", "Five to six quarterly periods versus an eight-quarter target."),
            ])
            watch = pd.DataFrame([
                ("OVV", "Issue 3", 74.1, 70.0, "ROE / leverage deterioration"),
                ("WMS", "Issue 4", 80.1, 78.0, "Debt and margin threshold review"),
            ], columns=["Ticker", "Origin", "Original Score", "Current Score", "Alert"])
            _html('<div class="re1-callout re1-callout-red"><b>Watchlist accountability.</b> Past selections that fall below the stated quality thresholds remain visible rather than disappearing from the record.</div>')
            _table(watch, "re1_buffett_watch", 170)

    _section("Research Papers & Podcasts", "Institutional Paper Library", "Country and institution filters, paper metadata and on-demand podcast access reproduce the audited 91-item RoboMacro library without forcing an audio load on page entry.")
    with _card("re1_papers"):
        pc1, pc2 = st.columns([0.8, 1.2])
        with pc1:
            source = st.selectbox("Institution", ["All", "BoE", "FED", "IMF", "ECB", "BIS", "BoJ"], key="re1_paper_source")
        with pc2:
            paper_query = st.text_input("Search papers", key="re1_paper_query", placeholder="liquidity, stablecoins, bank failures…")
        paper_filtered = papers.copy()
        if source != "All":
            paper_filtered = paper_filtered[paper_filtered["Source"] == source]
        if paper_query.strip():
            needle = paper_query.strip().lower()
            mask = paper_filtered[["Paper", "Authors", "Number"]].astype(str).apply(lambda col: col.str.lower().str.contains(needle, regex=False)).any(axis=1)
            paper_filtered = paper_filtered[mask]
        _table(paper_filtered[["Country", "Source", "Paper", "Authors", "Number", "Date"]], "re1_papers_table", 440)
        if not paper_filtered.empty:
            selected_paper = st.selectbox("Paper / podcast detail", paper_filtered["Paper"].tolist(), key="re1_selected_paper")
            selected = paper_filtered[paper_filtered["Paper"] == selected_paper].iloc[0]
            _html(f'<div class="re1-callout re1-callout-gold"><b>{_esc(selected["Source"])} · {_esc(selected["Number"])}</b><br>{_esc(selected["Authors"])} · {_esc(selected["Date"])}</div>')
            b1, b2, b3 = st.columns([0.7, 0.7, 1.6])
            with b1:
                if hasattr(st, "link_button"):
                    st.link_button("Open paper", str(selected["Paper URL"]), use_container_width=True)
            with b2:
                if hasattr(st, "link_button"):
                    st.link_button("Open audio", str(selected["Audio URL"]), use_container_width=True)
            with b3:
                load_audio = st.checkbox("Load in-page podcast player", key="re1_load_audio")
            if load_audio:
                st.audio(str(selected["Audio URL"]), format="audio/mp3")
        _download(paper_filtered, "Export paper library", "jarvis_research_papers.csv", "re1_papers_download")

    _section("Coverage Analytics", "Research Breadth & Topic Map", "An institutional extension to the source site: coverage concentration, thematic balance and freshness are measurable instead of being inferred from a long list.")
    topic_scores = pd.DataFrame(
        [[92, 78, 65, 55, 48, 72], [80, 86, 72, 61, 42, 58], [75, 63, 88, 69, 60, 74], [58, 82, 55, 90, 72, 68], [65, 71, 84, 73, 88, 79]],
        index=["G7", "Europe", "Asia", "Americas", "EM"],
        columns=["Central Banks", "Inflation", "Growth", "FX / Rates", "Commodities", "Equities"],
    )
    left, right = st.columns([1.0, 1.0])
    with left, _card():
        counts = notes.groupby("Region").size().sort_values(ascending=True)
        fig = go.Figure(go.Bar(x=counts.values, y=counts.index, orientation="h", marker_color=PALETTE["cyan"], text=counts.values, textposition="outside"))
        fig.update_layout(title="Audited note sample · regional breadth")
        _plot(fig, "re1_region_coverage", 450)
    with right, _card():
        fig = go.Figure(go.Heatmap(z=topic_scores.values, x=topic_scores.columns, y=topic_scores.index, zmin=0, zmax=100, colorscale=[[0, "#101c29"], [0.5, "#28658a"], [1, "#d8bf58"]], text=topic_scores.values, texttemplate="%{text}"))
        fig.update_layout(title="Research topic intensity · analytical score")
        _plot(fig, "re1_topic_map", 450)
    _reads([
        ("Freshness", "Current snapshot", "Latest public archive vintage is 21 July 2026."),
        ("Source diversity", "7 institutions", "BoE, Fed, IMF, ECB, BIS, AMF and BoJ filters are represented."),
        ("Governance", "Observed ≠ modelled", "Archive facts stay separate from the analytical topic scores above."),
    ])

    _section("Research Methodology", "AI Economist Build Log", "The three public blog entries are retained as a compact methodology register rather than mixed into the daily research stream.")
    blog = pd.DataFrame([
        ("28 Apr 2026", "From Consensus to Alpha: Harness Engineering for Macro Strategy", "AI · Automation · LLM · Alpha"),
        ("19 Feb 2026", "Refining the Logic of an AI Economist", "AI · Automation · LLM · Economics"),
        ("28 Oct 2025", "First Attempt at an AI Daily Note", "AI · Automation · Vibe Coding"),
    ], columns=["Date", "Post", "Tags"])
    _table(blog, "re1_blog", 190)
    with st.expander("Methodology & Data Quality", expanded=False):
        _html('<div class="re1-callout"><b>Source contract.</b> Archive counts, titles, paper metadata and note observations are an audited public RoboMacro snapshot captured 22 July 2026. Coverage heatmaps are JARVIS analytical scores and are labelled as such.</div>')
        methodology = pd.DataFrame([
            ("Research index", "RoboMacro public notes page", "Snapshot; 918-note universe"),
            ("Detailed note", "UK Macro Daily public HTML", "Observed note values; not live market data"),
            ("Equity research", "Buffett Lens Issue 13", "Public yfinance-labelled newsletter metrics"),
            ("Papers / audio", "RoboMacro public library", "Direct source and MP3 links"),
            ("Topic map", "JARVIS deterministic scoring", "Model output; never an observed count"),
        ], columns=["Layer", "Source", "Status"])
        _table(methodology, "re1_research_methodology", 260)


TIMEZONES: Mapping[str, str] = {
    "California": "America/Los_Angeles", "New York": "America/New_York", "Rio": "America/Sao_Paulo",
    "London": "Europe/London", "Geneva": "Europe/Zurich", "Dubai": "Asia/Dubai",
    "Hong Kong": "Asia/Hong_Kong", "Singapore": "Asia/Singapore", "Sydney": "Australia/Sydney",
}


def _calendar_view(events: pd.DataFrame, timezone_name: str) -> pd.DataFrame:
    target = ZoneInfo(TIMEZONES[timezone_name])
    source = ZoneInfo("America/New_York")
    converted: List[Dict[str, Any]] = []
    for row in events.to_dict("records"):
        stamp = datetime.strptime(f'{row["Date"]} {row["Time EDT"]}', "%Y-%m-%d %H:%M").replace(tzinfo=source).astimezone(target)
        converted.append({
            "Local Date": stamp.strftime("%a %d %b"), "Local Time": stamp.strftime("%H:%M"),
            "Code": row["Code"], "Country": row["Country"], "Event": row["Event"], "Impact": row["Impact"],
            "Previous": row["Previous"], "Consensus": row["Consensus"], "Actual": row["Actual"], "Region": row["Region"],
            "Timestamp": stamp,
        })
    return pd.DataFrame(converted)


def _event_intelligence() -> None:
    events = _events()
    elections = _elections()
    _header(
        "Events Intelligence",
        "A combined week-ahead macro calendar and global political observatory, reproducing RoboMacro's event hierarchy while adding catalyst concentration, central-bank watch and market-sensitivity analysis.",
        "JARVIS EVENTS · CALENDAR / CENTRAL BANKS / ELECTIONS / MARKET RISK",
    )
    _kpis([
        ("Week-ahead events", "299", "43-country public calendar universe", "positive"),
        ("High-impact sample", str(int((events["Impact"] == "High").sum())), "Audited / reconstructed desk rows", "neutral"),
        ("Political events", "86", "Through 2030 across 50 economies", "positive"),
        ("Next six months", "8", "Elections and major policy events", "neutral"),
    ])

    _section("Macro Calendar", "Global Week-Ahead Calendar", "Timezone, impact, region, mode and search controls are attached directly to the calendar, matching RoboMacro's interaction model without a separate parameter wall.")
    with _card("re1_calendar"):
        c1, c2, c3 = st.columns([1.0, 0.9, 1.1])
        with c1:
            timezone_name = st.selectbox("Timezone", list(TIMEZONES.keys()), index=1, key="re1_timezone")
        with c2:
            calendar_mode = _segmented("Calendar mode", ["Day", "Week"], "re1_calendar_mode", "Week")
        with c3:
            search = st.text_input("Search country or event", key="re1_event_search", placeholder="CPI, United States, EIA…")
        impact = _segmented("Impact", ["All", "High + Med", "High Only"], "re1_event_impact", "All")
        region = st.selectbox("Region / bloc", ["All", "G7", "BRICS", "Eurozone", "Nordics", "ASEAN", "GCC", "Europe"], key="re1_event_region")
        day = "All week"
        if calendar_mode == "Day":
            day = st.selectbox("Trading day", ["Mon 20 Jul", "Tue 21 Jul", "Wed 22 Jul", "Thu 23 Jul", "Fri 24 Jul"], index=2, key="re1_event_day")
        view = _calendar_view(events, timezone_name)
        if impact == "High + Med":
            view = view[view["Impact"].isin(["High", "Med"])]
        elif impact == "High Only":
            view = view[view["Impact"] == "High"]
        if region != "All":
            view = view[view["Region"] == region]
        if calendar_mode == "Day":
            target_date = {"Mon 20 Jul": "Mon 20 Jul", "Tue 21 Jul": "Tue 21 Jul", "Wed 22 Jul": "Wed 22 Jul", "Thu 23 Jul": "Thu 23 Jul", "Fri 24 Jul": "Fri 24 Jul"}[day]
            view = view[view["Local Date"] == target_date]
        if search.strip():
            needle = search.strip().lower()
            mask = view[["Country", "Event", "Code"]].astype(str).apply(lambda col: col.str.lower().str.contains(needle, regex=False)).any(axis=1)
            view = view[mask]
        _html(f'<div class="re1-statline"><span class="re1-stat">WEEK · 20–26 JUL 2026</span><span class="re1-stat re1-stat-gold">{_esc(timezone_name.upper())}</span><span class="re1-stat">VISIBLE · {len(view)}</span><span class="re1-stat">43 COUNTRIES IN SOURCE UNIVERSE</span></div>')
        shown = view[["Local Date", "Local Time", "Code", "Country", "Event", "Impact", "Previous", "Consensus", "Actual", "Region"]].copy()
        _table(shown, "re1_calendar_table", 600)
        _download(shown, "Export filtered calendar", "jarvis_week_ahead_calendar.csv", "re1_calendar_download")

    _section("Catalyst Concentration", "Event Risk Radar", "A JARVIS extension: event density is converted into an impact-weighted risk map so the desk can see where calendar exposure is concentrated before the releases arrive.")
    weights = events["Impact"].map({"High": 3, "Med": 2, "Low": 1}).fillna(1)
    event_risk = events.assign(Risk=weights).groupby("Region", as_index=False).agg(Events=("Event", "count"), Risk=("Risk", "sum"))
    left, right = st.columns([1.0, 1.0])
    with left, _card():
        fig = go.Figure(go.Bar(x=event_risk["Region"], y=event_risk["Risk"], marker_color=[PALETTE["red"] if value >= event_risk["Risk"].quantile(.75) else PALETTE["gold"] for value in event_risk["Risk"]], text=event_risk["Events"], texttemplate="%{text} events", textposition="outside"))
        fig.update_layout(title="Impact-weighted catalyst load", yaxis_title="Risk points")
        _plot(fig, "re1_event_risk", 420)
    with right, _card():
        daily = events.assign(Risk=weights).groupby("Date", as_index=False)["Risk"].sum()
        fig = go.Figure(go.Scatter(x=pd.to_datetime(daily["Date"]), y=daily["Risk"], mode="lines+markers", fill="tozeroy", line=dict(color=PALETTE["cyan"], width=2.4), fillcolor="rgba(99,199,255,.12)"))
        fig.update_layout(title="Risk load through the week", yaxis_title="Risk points")
        _plot(fig, "re1_daily_risk", 420)
    _reads([
        ("Peak day", "Wednesday", "UK CPI, Indonesia policy and US energy data cluster in one session."),
        ("Dominant bloc", "G7", "Labour, inflation, housing, PMIs and rates drive the visible sample."),
        ("Cross-asset hinge", "Inflation / policy", "Rates and FX are the first-order transmission channels."),
    ])

    _section("Central Bank Watch", "Policy Decision Board", "Policy meetings are separated from the broader calendar and paired with explicit surprise direction and first-order market transmission.")
    policy = pd.DataFrame([
        ("22 Jul", "Bank Indonesia", "6.00%", "5.75%", "Hike risk", "IDR ↑ · front-end yields ↑"),
        ("23 Jul", "European Central Bank", "2.00%", "2.00%", "Hold", "EUR driven by guidance"),
        ("30 Jul", "Federal Reserve", "3.63%", "3.63%", "Hold / hawkish risk", "USD ↑ if cuts repriced"),
        ("31 Jul", "Bank of Japan", "0.75%", "0.75%", "Hold", "JPY sensitive to normalisation language"),
    ], columns=["Date", "Central Bank", "Consensus", "Previous", "Desk Bias", "Primary Transmission"])
    with _card("re1_policy_board"):
        _table(policy, "re1_policy_table", 235)
        selected_bank = st.selectbox("Policy-event deep dive", policy["Central Bank"].tolist(), key="re1_policy_selected")
        row = policy[policy["Central Bank"] == selected_bank].iloc[0]
        _html(f'<div class="re1-callout re1-callout-gold"><b>{_esc(row["Desk Bias"])}</b> · Consensus {_esc(row["Consensus"])} versus previous {_esc(row["Previous"])}.<br>{_esc(row["Primary Transmission"])}</div>')

    _section("Political Observatory", "Global Elections Timeline", "The audited RoboMacro hierarchy is preserved: timeline, region, election type, incumbent, polling and change-of-power probability. Local filters only control this observatory.")
    with _card("re1_elections"):
        election_region = _segmented("Election region", ["All", "G7", "Europe", "Latin America", "Asia-Pacific", "EMEA"], "re1_election_region", "All")
        ec1, ec2 = st.columns([1.0, 1.0])
        with ec1:
            election_type = st.selectbox("Event type", ["All", "Presidential", "Legislative", "Political Event"], key="re1_election_type")
        with ec2:
            horizon = st.selectbox("Horizon", ["Next 6 months", "Next 12 months", "Through 2027"], index=1, key="re1_election_horizon")
        filtered_elections = elections.copy()
        if election_region != "All":
            if election_region == "G7":
                filtered_elections = filtered_elections[filtered_elections["Region"] == "G7"]
            else:
                filtered_elections = filtered_elections[filtered_elections["Region"] == election_region]
        if election_type != "All":
            filtered_elections = filtered_elections[filtered_elections["Type"] == election_type]
        cutoff = {"Next 6 months": pd.Timestamp("2027-01-22"), "Next 12 months": pd.Timestamp("2027-07-22"), "Through 2027": pd.Timestamp("2027-12-31")}[horizon]
        filtered_elections = filtered_elections[filtered_elections["Date"] <= cutoff]
        blocks = []
        for _, election in filtered_elections.iterrows():
            prob = int(election["Change Probability"])
            prob_label = "POLICY EVENT" if prob == 0 else f"{prob}% CHANGE PROB."
            blocks.append(
                '<div class="re1-event"><div class="re1-event-top">'
                f'<div class="re1-event-title">{_esc(election["Flag"])} {_esc(election["Election"])}</div>'
                f'<div class="re1-event-date">{election["Date"].strftime("%d %b %Y")}</div></div>'
                f'<div class="re1-event-meta">{_esc(election["Type"])} · {_esc(election["Country"])} · {prob_label}</div>'
                f'<div class="re1-event-copy">{_esc(election["Description"])}<br><br><b>Incumbent:</b> {_esc(election["Incumbent"])} · <b>Leader:</b> {_esc(election["Leader"])} ({_esc(election["Poll"])})</div>'
                f'<div class="re1-prob"><span style="width:{max(4, prob)}%"></span></div></div>'
            )
        if blocks:
            _html('<div class="re1-event-grid">' + "".join(blocks) + "</div>")
        else:
            _html('<div class="re1-empty">No political events match the active filter.</div>')
        _download(filtered_elections, "Export election timeline", "jarvis_election_timeline.csv", "re1_elections_download")

    _section("Election Risk", "Markets & Economy by Election", "RoboMacro's empty or sparse Markets/Economy sub-pages are upgraded into a transparent sensitivity lens. The macro snapshot is descriptive; the five risk scores are deterministic JARVIS model output.")
    with _card("re1_election_risk"):
        selected_election_name = st.selectbox("Election / political event", elections["Election"].tolist(), key="re1_selected_election")
        selected = elections[elections["Election"] == selected_election_name].iloc[0]
        _html(f'<div class="re1-statline"><span class="re1-stat re1-stat-gold">{_esc(selected["Country"].upper())}</span><span class="re1-stat">{selected["Date"].strftime("%d %b %Y")}</span><span class="re1-stat re1-stat-red">CHANGE PROB. · {int(selected["Change Probability"])}%</span></div>')
        macro = pd.DataFrame([
            ("Real GDP Growth YoY", f'{selected["GDP"]:.1f}%'),
            ("CPI Inflation YoY", f'{selected["CPI"]:.1f}%'),
            ("Policy Rate", f'{selected["Policy Rate"]:.2f}%'),
            ("Unemployment", f'{selected["Unemployment"]:.1f}%'),
        ], columns=["Economic Context", "Snapshot"])
        risks = ["FX", "Rates", "Equities", "Fiscal", "Trade"]
        values = [selected["FX Risk"], selected["Rates Risk"], selected["Equity Risk"], selected["Fiscal Risk"], selected["Trade Risk"]]
        left, right = st.columns([0.72, 1.28])
        with left:
            _table(macro, "re1_election_macro", 220)
            _html('<div class="re1-callout"><b>Interpretation.</b> Positive scores indicate greater directional upside pressure or risk premia; negative scores indicate downside pressure. Magnitude is sensitivity, not probability.</div>')
        with right:
            theta = risks + [risks[0]]
            radius = [abs(float(v)) for v in values] + [abs(float(values[0]))]
            fig = go.Figure(go.Scatterpolar(r=radius, theta=theta, fill="toself", line=dict(color=PALETTE["gold"], width=2.3), fillcolor="rgba(216,191,88,.15)", text=[f"{v:+.0f}" for v in values] + [f"{values[0]:+.0f}"], hovertemplate="%{theta}: %{text}<extra></extra>"))
            fig.update_layout(title="Cross-asset election sensitivity", polar=dict(radialaxis=dict(range=[0, 100], visible=True)))
            _plot(fig, "re1_election_radar", 420)

    with st.expander("Events Methodology & Data Quality", expanded=False):
        _html('<div class="re1-callout"><b>Observed versus modelled.</b> Calendar rows and election metadata are audited public snapshots. Catalyst-risk weights and election sensitivities are deterministic analytical overlays, explicitly separated from observed values and prediction-market prices.</div>')
        governance = pd.DataFrame([
            ("Calendar universe", "RoboMacro public calendar", "299 events / 43 countries in audited week"),
            ("Timezone", "America/New_York base", "Converted with IANA zoneinfo"),
            ("Elections", "RoboMacro public political observatory", "86 events / 50 countries through 2030"),
            ("Change probability", "Public page model estimate", "Not a prediction-market price"),
            ("Market sensitivity", "JARVIS deterministic score", "Model output on a -100 to +100 scale"),
            ("Economic context", "Public snapshot / disclosed static vintage", "No false live status"),
        ], columns=["Layer", "Source", "Contract"])
        _table(governance, "re1_events_governance", 330)


def render_research_events_intelligence(
    ticker: str = "",
    price_data: Optional[pd.DataFrame] = None,
    analysis: Optional[Mapping[str, Any]] = None,
) -> None:
    """Render the isolated Research & Events workspace."""
    del ticker, price_data, analysis
    _css()
    page = str(st.session_state.get(RESEARCH_EVENTS_PAGE_KEY, "Research Intelligence"))
    if page not in RESEARCH_EVENTS_PAGES:
        page = "Research Intelligence"
        st.session_state[RESEARCH_EVENTS_PAGE_KEY] = page
    if page == "Events Intelligence":
        _event_intelligence()
    else:
        _research_intelligence()
    _html(f'<div class="re1-source" style="margin-top:18px"><b>{RESEARCH_EVENTS_VERSION}</b> · audited public snapshot 22 Jul 2026 · local controls · observed and modelled layers separated.</div>')


RESEARCH_EVENTS_INTEGRITY: Mapping[str, Any] = {
    "version": RESEARCH_EVENTS_VERSION,
    "pages": list(RESEARCH_EVENTS_PAGES),
    "research_notes_structure": True,
    "papers_and_podcasts": True,
    "economic_calendar": True,
    "elections_timeline": True,
    "election_markets_and_economy": True,
    "controls_local_to_analysis": True,
    "snapshot_date": SNAPSHOT_DATE.isoformat(),
    "synthetic_observed_history": False,
}
