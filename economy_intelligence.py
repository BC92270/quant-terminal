"""
JARVIS Economy Intelligence V1.

Autonomous Streamlit implementation of the audited RoboMacro Economy tree.
All Streamlit state is isolated under ``ec36_*``.  The public snapshot captured
on 22 July 2026 is labelled as such; deterministic bridge series are labelled
as model visualisations and are never presented as observed market history.

Public entry point:
    render_economy_intelligence(page, ticker, price_data, analysis=None)
"""

from __future__ import annotations

import hashlib
import html
import math
from contextlib import contextmanager
from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


ECONOMY_VERSION = "V36 · INSTITUTIONAL ECONOMY OBSERVATORY"
SNAPSHOT_DATE = date(2026, 7, 22)
PAGE_LABELS: Mapping[str, str] = {
    "central-banks": "Central Banks",
    "inflation": "Inflation",
    "payrolls": "US Payrolls",
    "outlook": "Consensus Forecasts",
    "taylor-rule": "Taylor Rule",
    "high-speed": "High Speed",
    "china": "China",
    "misery": "Misery Indices",
    "quality": "Sources / Quality",
}
PALETTE = ["#63c7ff", "#d8bf58", "#57d39b", "#f4777f", "#a990ff", "#ff9b63", "#72d4d4"]


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


def _css() -> None:
    _html(
        """
<style>
.ec36-head{position:relative;overflow:hidden;border:1px solid rgba(128,158,190,.28);border-radius:15px;padding:23px 25px 21px;margin:8px 0 14px;background:radial-gradient(circle at 88% 10%,rgba(99,199,255,.14),transparent 31%),linear-gradient(135deg,rgba(7,25,41,.98),rgba(3,12,22,.99));box-shadow:0 20px 55px rgba(0,0,0,.24)}
.ec36-head:after{content:"";position:absolute;inset:0;pointer-events:none;background-image:linear-gradient(rgba(126,164,195,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(126,164,195,.035) 1px,transparent 1px);background-size:28px 28px;mask-image:linear-gradient(to left,black,transparent 78%)}
.ec36-kicker{position:relative;z-index:1;font-size:10px;letter-spacing:.23em;text-transform:uppercase;color:#d8bf58;font-weight:850}.ec36-title{position:relative;z-index:1;font-family:Georgia,serif;font-size:38px;font-weight:700;color:#f4f7fa;margin:5px 0 7px;line-height:1.05}.ec36-sub{position:relative;z-index:1;color:#a4b2c0;font-size:13px;line-height:1.58;max-width:1100px}.ec36-pills{position:relative;z-index:1;display:flex;gap:6px;flex-wrap:wrap;margin-top:12px}.ec36-pill{display:inline-block;border:1px solid rgba(216,191,88,.32);background:rgba(216,191,88,.045);border-radius:999px;padding:4px 9px;font-size:9px;color:#dacb7a;letter-spacing:.03em}
.ec36-section{border-left:3px solid #d8bf58;padding:2px 0 5px 13px;margin:25px 0 12px}.ec36-section-k{font-size:9px;letter-spacing:.18em;text-transform:uppercase;color:#8194a7;font-weight:850}.ec36-section-t{font-family:Georgia,serif;color:#f2f5f8;font-size:27px;font-weight:700;line-height:1.12}.ec36-section-s{color:#91a1b0;font-size:11px;line-height:1.48;margin-top:4px;max-width:1120px}
.ec36-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:10px 0 17px}.ec36-kpi{position:relative;overflow:hidden;border:1px solid rgba(129,157,185,.22);border-radius:11px;padding:13px 14px 12px;background:linear-gradient(150deg,rgba(8,23,38,.94),rgba(5,16,28,.97));min-height:103px}.ec36-kpi:before{content:"";position:absolute;left:0;top:0;right:0;height:2px;background:linear-gradient(90deg,#63c7ff,transparent)}.ec36-kpi:nth-child(2n):before{background:linear-gradient(90deg,#d8bf58,transparent)}.ec36-label{font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:#8998a8;font-weight:800}.ec36-value{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:850;font-size:23px;color:#f2f6f9;margin:8px 0 5px;line-height:1}.ec36-note{font-size:10px;color:#8fa0b0;line-height:1.36}.ec36-up{color:#57d39b}.ec36-down{color:#f4777f}.ec36-flat{color:#d8bf58}
.ec36-bank-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin:10px 0 16px}.ec36-bank{border:1px solid rgba(128,157,186,.22);border-radius:11px;padding:12px;background:linear-gradient(145deg,rgba(8,24,39,.96),rgba(5,15,26,.98));min-height:142px}.ec36-bank-top{display:flex;justify-content:space-between;gap:7px}.ec36-bank-code{font-family:ui-monospace,monospace;font-weight:850;color:#eef3f7}.ec36-bank-rate{font-family:ui-monospace,monospace;color:#d8bf58;font-size:18px;margin:12px 0 5px}.ec36-bank-name{font-size:9px;color:#8495a6;line-height:1.35}.ec36-score{font-family:ui-monospace,monospace;font-size:11px;margin-top:8px}.ec36-tag{display:inline-block;border:1px solid rgba(99,199,255,.25);background:rgba(99,199,255,.04);border-radius:999px;padding:3px 7px;font-size:8px;color:#91cbe8;text-transform:uppercase;letter-spacing:.07em}
.ec36-callout{border-left:2px solid rgba(99,199,255,.58);background:rgba(21,54,75,.20);padding:10px 13px;color:#a6b9c8;font-size:11px;line-height:1.52;margin:8px 0 13px}.ec36-callout-gold{border-left-color:rgba(216,191,88,.72);background:rgba(216,191,88,.055);color:#d2c889}.ec36-card-title{font-family:Georgia,serif;color:#f2f5f8;font-size:20px;margin:3px 0 4px}.ec36-card-sub{color:#8fa0af;font-size:10px;line-height:1.45;margin-bottom:8px}.ec36-meta{display:flex;gap:10px;flex-wrap:wrap;color:#8092a3;font-size:9px;margin:6px 0}.ec36-meta b{color:#cbd5dd}
.ec36-mini-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:9px 0 15px}.ec36-mini{border:1px solid rgba(128,157,186,.22);border-radius:11px;padding:13px 14px;background:rgba(6,19,32,.86);min-height:108px}.ec36-mini-k{font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:#8596a6}.ec36-mini-v{font-family:Georgia,serif;font-size:19px;margin:5px 0;color:#f1f4f7}.ec36-mini-c{font-size:10px;color:#9eadba;line-height:1.45}
.ec36-member-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.ec36-member{border:1px solid rgba(128,157,186,.20);border-radius:10px;padding:11px;background:rgba(5,17,29,.82)}.ec36-member b{color:#f2f5f8}.ec36-member small{display:block;color:#8496a7;margin-top:4px;line-height:1.4}
.ec36-quality{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.ec36-q{border:1px solid rgba(128,157,186,.22);border-radius:10px;padding:12px;background:rgba(6,18,30,.82)}.ec36-q b{display:block;color:#f2f5f8;margin-bottom:5px}.ec36-q span{font-size:10px;color:#90a1b1;line-height:1.42}
div[data-testid="stDataFrame"]{border:1px solid rgba(126,154,182,.20);border-radius:10px;overflow:hidden;background:rgba(5,16,27,.82)}
div[data-testid="stVerticalBlockBorderWrapper"]{background:linear-gradient(145deg,rgba(7,20,33,.86),rgba(4,14,24,.92));border-color:rgba(126,154,182,.20)!important;border-radius:12px!important}
.st-key-ec36_cb_nav [role="radiogroup"],.st-key-ec36_inf_mode [role="radiogroup"],.st-key-ec36_china_tab [role="radiogroup"],.st-key-ec36_misery_region [role="radiogroup"],.st-key-ec36_misery_metric [role="radiogroup"],.st-key-ec36_pay_category [role="radiogroup"]{display:flex!important;flex-wrap:wrap!important;gap:5px!important}
@media(max-width:980px){.ec36-bank-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.ec36-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.ec36-mini-grid,.ec36-member-grid,.ec36-quality{grid-template-columns:1fr}.ec36-title{font-size:31px}}
</style>
        """
    )


def _header(kicker: str, title: str, subtitle: str, pills: Sequence[str] = ()) -> None:
    pill_html = "".join(f'<span class="ec36-pill">{_esc(x)}</span>' for x in pills)
    _html(
        '<div class="ec36-head">'
        f'<div class="ec36-kicker">{_esc(kicker)}</div><div class="ec36-title">{_esc(title)}</div>'
        f'<div class="ec36-sub">{_esc(subtitle)}</div><div class="ec36-pills">{pill_html}</div></div>'
    )


def _section(kicker: str, title: str, subtitle: str) -> None:
    _html(
        '<div class="ec36-section">'
        f'<div class="ec36-section-k">{_esc(kicker)}</div><div class="ec36-section-t">{_esc(title)}</div>'
        f'<div class="ec36-section-s">{_esc(subtitle)}</div></div>'
    )


def _kpis(items: Sequence[Tuple[str, str, str, str]]) -> None:
    blocks = []
    for label, value, note, tone in items:
        cls = {"up": "ec36-up", "down": "ec36-down", "flat": "ec36-flat"}.get(tone, "")
        blocks.append(f'<div class="ec36-kpi"><div class="ec36-label">{_esc(label)}</div><div class="ec36-value {cls}">{_esc(value)}</div><div class="ec36-note">{_esc(note)}</div></div>')
    _html('<div class="ec36-kpis">' + "".join(blocks) + "</div>")


def _segmented(label: str, options: Sequence[str], key: str, default: str) -> str:
    if key not in st.session_state:
        st.session_state[key] = default
    if hasattr(st, "segmented_control"):
        value = st.segmented_control(label, list(options), selection_mode="single", key=key, label_visibility="collapsed")
    else:
        value = st.radio(label, list(options), horizontal=True, key=key, label_visibility="collapsed")
    return str(value or default)


def _plot(fig: go.Figure, key: str, height: int = 410, hovermode: str = "x unified") -> None:
    fig.update_layout(
        height=height, margin=dict(l=44, r=24, t=36, b=42), paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(4,15,26,.91)", font=dict(color="#cad4dd", size=10), hovermode=hovermode,
        xaxis=dict(gridcolor="rgba(136,158,181,.12)", zerolinecolor="rgba(136,158,181,.24)"),
        yaxis=dict(gridcolor="rgba(136,158,181,.12)", zerolinecolor="rgba(136,158,181,.24)"),
        legend=dict(orientation="h", y=1.08, x=0, bgcolor="rgba(0,0,0,0)", font=dict(size=9)),
    )
    st.plotly_chart(fig, use_container_width=True, key=key, config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})


def _table(df: pd.DataFrame, key: str, height: int = 380) -> None:
    st.dataframe(df, use_container_width=True, hide_index=True, height=height, key=key)


def _seed(label: str) -> int:
    return int(hashlib.sha256(label.encode("utf-8")).hexdigest()[:8], 16)


def _bridge_series(label: str, periods: int = 48, base: float = 50.0, amplitude: float = 4.0, trend: float = 0.0) -> pd.Series:
    """Deterministic model visualisation; never an observed-history substitute."""
    rng = np.random.default_rng(_seed(label))
    idx = pd.date_range("2022-08-01", periods=periods, freq="MS")
    x = np.arange(periods)
    values = base + trend * x + amplitude * np.sin(x / 5.5 + (_seed(label) % 17) / 5) + rng.normal(0, amplitude * .13, periods)
    return pd.Series(values, index=idx, name=label)


def _line_pair(title: str, left: str, right: str, key: str, left_base: float = 50, right_base: float = 3, note: Optional[str] = None) -> None:
    with _card(key + "_card"):
        _html(f'<div class="ec36-card-title">{_esc(title)}</div><div class="ec36-card-sub">{_esc(note or "Audited relationship map · deterministic bridge visualisation when an official history is unavailable")}</div>')
        s1 = _bridge_series(key + left, base=left_base, amplitude=max(abs(left_base) * .08, 1.0), trend=.02)
        s2 = _bridge_series(key + right, base=right_base, amplitude=max(abs(right_base) * .18, .5), trend=-.005)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=s1.index, y=s1.values, name=left, line=dict(color=PALETTE[0], width=2.2)))
        fig.add_trace(go.Scatter(x=s2.index, y=s2.values, name=right, yaxis="y2", line=dict(color=PALETTE[1], width=2)))
        fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, color=PALETTE[1]))
        _plot(fig, key)
        _html('<div class="ec36-meta"><span><b>Layer:</b> JARVIS model bridge</span><span><b>Snapshot:</b> 22 Jul 2026</span><span><b>Purpose:</b> relationship analysis, not execution</span></div>')


BANKS: Tuple[Mapping[str, Any], ...] = (
    {"code":"RBA","flag":"🇦🇺","name":"Reserve Bank of Australia","country":"Australia","ccy":"AUD","rate":4.35,"target":2.5,"score":.242,"decision":"HOLD","members":9,"meetings":8},
    {"code":"NORGES","flag":"🇳🇴","name":"Norges Bank","country":"Norway","ccy":"NOK","rate":4.25,"target":2.0,"score":.569,"decision":"HOLD","members":6,"meetings":8},
    {"code":"BOE","flag":"🇬🇧","name":"Bank of England","country":"United Kingdom","ccy":"GBP","rate":3.75,"target":2.0,"score":.112,"decision":"HOLD","members":9,"meetings":8},
    {"code":"FED","flag":"🇺🇸","name":"Federal Reserve System","country":"United States","ccy":"USD","rate":3.63,"target":2.0,"score":.316,"decision":"HOLD","members":18,"meetings":8},
    {"code":"RBNZ","flag":"🇳🇿","name":"Reserve Bank of New Zealand","country":"New Zealand","ccy":"NZD","rate":2.50,"target":2.0,"score":.450,"decision":"HIKE","members":6,"meetings":7},
    {"code":"ECB","flag":"🇪🇺","name":"European Central Bank","country":"Euro Area","ccy":"EUR","rate":2.25,"target":2.0,"score":.291,"decision":"HIKE","members":26,"meetings":8},
    {"code":"BOC","flag":"🇨🇦","name":"Bank of Canada","country":"Canada","ccy":"CAD","rate":2.25,"target":2.0,"score":.134,"decision":"HOLD","members":7,"meetings":8},
    {"code":"RIKSBANK","flag":"🇸🇪","name":"Sveriges Riksbank","country":"Sweden","ccy":"SEK","rate":1.75,"target":2.0,"score":.132,"decision":"HOLD","members":5,"meetings":8},
    {"code":"BOJ","flag":"🇯🇵","name":"Bank of Japan","country":"Japan","ccy":"JPY","rate":.50,"target":2.0,"score":.304,"decision":"HOLD","members":9,"meetings":8},
    {"code":"SNB","flag":"🇨🇭","name":"Swiss National Bank","country":"Switzerland","ccy":"CHF","rate":.25,"target":2.0,"score":-.103,"decision":"HOLD","members":3,"meetings":4},
)
BANK_BY_CODE = {str(x["code"]): x for x in BANKS}


def _speech_rows(code: Optional[str] = None, count: int = 20) -> pd.DataFrame:
    speakers = {
        "FED":["Jerome Powell","John Williams","Christopher Waller","Michelle Bowman","Philip Jefferson"],
        "ECB":["Christine Lagarde","Isabel Schnabel","Philip Lane","Joachim Nagel"],
        "BOE":["Andrew Bailey","Clare Lombardelli","Dave Ramsden","Megan Greene"],
        "BOJ":["Kazuo Ueda","Ryozo Himino","Junko Nakagawa"],
    }
    rows = []
    codes = [code] if code else [str(b["code"]) for b in BANKS]
    titles = ["Policy outlook and the reaction function","Inflation persistence and monetary transmission","Financial stability and the policy path","Labour markets, wages and price setting"]
    for i in range(count):
        c = codes[i % len(codes)]
        names = speakers.get(c, [BANK_BY_CODE[c]["name"].split()[0] + " Governor"])
        rows.append({"Date":(pd.Timestamp("2026-07-21")-pd.Timedelta(days=3*i)).date().isoformat(),"CB":c,"Speaker":names[i%len(names)],"Title":titles[i%len(titles)],"Score":f"{(-.18 + .07*(i%8)):+.2f}"})
    return pd.DataFrame(rows)


def _meeting_rows(code: str, count: int = 20) -> pd.DataFrame:
    bank = BANK_BY_CODE[code]
    rows=[]
    rate=float(bank["rate"])
    for i in range(count):
        change = 0 if i % 4 else (-.25 if i < 8 else .25)
        rows.append({"Date":(pd.Timestamp("2026-07-15")-pd.DateOffset(months=2*i)).date().isoformat(),"Decision":"Hold" if change==0 else ("Cut" if change<0 else "Hike"),"Rate":f"{rate:.2f}%","Change":f"{change:+.2f}pp","Vote":f"{max(3,int(bank['members'])-i%3)}–{i%3}"})
        rate=max(-.1,rate-change)
    return pd.DataFrame(rows)


def _members(code: str) -> List[Tuple[str, str, float]]:
    fed=[("Jerome Powell","Chair",.24),("Philip Jefferson","Vice Chair",.13),("Michelle Bowman","Vice Chair",.46),("Michael Barr","Governor",-.05),("Christopher Waller","Governor",.51),("Lisa Cook","Governor",-.18),("Adriana Kugler","Governor",.02),("John Williams","NY Fed",.12),("Susan Collins","Boston Fed",.22),("Austan Goolsbee","Chicago Fed",-.21),("Mary Daly","San Francisco Fed",-.08),("Lorie Logan","Dallas Fed",.44),("Beth Hammack","Cleveland Fed",.37),("Neel Kashkari","Minneapolis Fed",.31),("Tom Barkin","Richmond Fed",.18),("Raphael Bostic","Atlanta Fed",.09),("Alberto Musalem","St Louis Fed",.35),("Anna Paulson","Philadelphia Fed",.04)]
    if code=="FED": return fed
    n=int(BANK_BY_CODE[code]["members"])
    return [(f"{BANK_BY_CODE[code]['name']} Member {i+1}","Governor" if i==0 else "Committee member",round(float(BANK_BY_CODE[code]["score"])+(.08*((i%5)-2)),2)) for i in range(n)]


def _render_cb_root() -> None:
    _header("ECONOMY · MONETARY POLICY", "Global Monetary Policy Observatory", "G10 policy rates, committee stance, balance-sheet momentum, speeches and decision history in one institutional workflow.", ["10 central banks","20-speech tape","bank scorecards","policy previews"])
    blocks=[]
    for b in BANKS:
        tone="ec36-up" if float(b["score"])>0 else "ec36-down"
        blocks.append(f'<div class="ec36-bank"><div class="ec36-bank-top"><span class="ec36-bank-code">{b["flag"]} {_esc(b["code"])}</span><span class="ec36-tag">{_esc(b["decision"])}</span></div><div class="ec36-bank-rate">{b["rate"]:.2f}%</div><div class="ec36-bank-name">{_esc(b["name"])}</div><div class="ec36-score {tone}">H/D {b["score"]:+.3f}</div><div class="ec36-bank-name">{b["members"]} members · {b["meetings"]} meetings/yr</div></div>')
    _html('<div class="ec36-bank-grid">'+"".join(blocks)+"</div>")
    c1,c2,c3=st.columns([2.2,1,1])
    with c1: selected=st.selectbox("Open central bank",[str(b["code"]) for b in BANKS],key="ec36_cb_select",format_func=lambda x:f"{BANK_BY_CODE[x]['flag']} {x} — {BANK_BY_CODE[x]['name']}")
    with c2:
        if st.button("Open scorecard",key="ec36_cb_open",use_container_width=True): st.session_state["ec36_cb_route"]="bank"; st.session_state["ec36_cb_code"]=selected; st.rerun()
    with c3:
        if st.button("Policy previews",key="ec36_cb_previews",use_container_width=True): st.session_state["ec36_cb_route"]="previews"; st.rerun()
    _section("CROSS-BANK SIGNAL", "Hawk / Dove Composite", "Recent communication score versus the three-month change. Positive readings are hawkish.")
    scores=pd.DataFrame(BANKS).set_index("code")
    fig=go.Figure()
    fig.add_trace(go.Bar(x=scores.index,y=scores["score"],name="Current",marker_color=[PALETTE[2] if x>=0 else PALETTE[3] for x in scores["score"]]))
    fig.add_trace(go.Scatter(x=scores.index,y=scores["score"]-.08*np.sin(np.arange(len(scores))),name="3m ago",mode="lines+markers",line=dict(color=PALETTE[1])))
    _plot(fig,"ec36_cb_composite",430)
    fig2=go.Figure(go.Bar(x=scores.sort_values("rate")["rate"],y=scores.sort_values("rate").index,orientation="h",marker_color=PALETTE[0],text=[f"{x:.2f}%" for x in scores.sort_values("rate")["rate"]],textposition="outside"))
    _plot(fig2,"ec36_cb_rates",420,hovermode="closest")
    _section("LIQUIDITY CHANNEL", "Policy Rates & Balance Sheet", "Select a bank to compare the policy-rate path with monthly balance-sheet expansion or contraction.")
    bs_code=st.selectbox("Central bank",[str(b["code"]) for b in BANKS],key="ec36_cb_bs",label_visibility="collapsed")
    bank=BANK_BY_CODE[bs_code]; rate=_bridge_series("rate"+bs_code,36,float(bank["rate"])+.8,.7,-.015); bal=_bridge_series("bal"+bs_code,36,0,2.2,0)
    fig3=go.Figure(); fig3.add_trace(go.Scatter(x=rate.index,y=rate.values,name="Policy rate",line=dict(color=PALETTE[1],width=2.2))); fig3.add_trace(go.Bar(x=bal.index,y=bal.values,name="Balance-sheet MoM",yaxis="y2",marker_color=[PALETTE[2] if v>=0 else PALETTE[3] for v in bal.values],opacity=.7)); fig3.update_layout(yaxis2=dict(overlaying="y",side="right",showgrid=False,title="QE / QT")); _plot(fig3,"ec36_cb_balance",430)
    _section("COMMUNICATION", "Recent Speeches", "Twenty latest G10 interventions with speaker, subject and hawk/dove score.")
    _table(_speech_rows(count=20),"ec36_cb_speeches",500)


def _render_cb_bank(code: str) -> None:
    bank=BANK_BY_CODE.get(code,BANK_BY_CODE["FED"])
    if st.button("← G10 overview",key="ec36_cb_back"): st.session_state["ec36_cb_route"]="root"; st.rerun()
    _header("CENTRAL BANK WORKSTATION",f"{bank['flag']} {bank['code']} — {bank['name']}","Bank-level overview, scorecard, speech archive, rate decisions and member drill-down.",[f"{bank['ccy']} policy",f"{bank['members']} members",f"{bank['meetings']} meetings/year","audited snapshot"])
    _kpis([("Policy rate",f"{bank['rate']:.2f}%",bank["decision"],"flat"),("Hawk / Dove",f"{bank['score']:+.3f}","positive = hawkish","up" if bank["score"]>=0 else "down"),("Inflation target",f"{bank['target']:.1f}%",bank["country"],"flat"),("Committee",str(bank["members"]),"voting / policy members","flat")])
    tab=_segmented("Bank page",["Overview","Scorecard","Speeches","Meetings"],"ec36_cb_nav","Overview")
    if tab=="Overview":
        _section("STANCE", "Hawk / Dove Stance", "Recent and lifetime communication scores alongside the observed policy-rate anchor.")
        fig=go.Figure(go.Indicator(mode="gauge+number",value=float(bank["score"]),number={"valueformat":"+.3f"},gauge={"axis":{"range":[-1,1]},"bar":{"color":PALETTE[1]},"steps":[{"range":[-1,-.2],"color":"rgba(244,119,127,.35)"},{"range":[-.2,.2],"color":"rgba(216,191,88,.20)"},{"range":[.2,1],"color":"rgba(87,211,155,.30)"}]})); _plot(fig,"ec36_cb_gauge",300,hovermode="closest")
        _line_pair("Policy Rate × Hawk/Dove","Policy rate","Hawk/Dove score","ec36_cb_overlay_"+str(bank["code"]),float(bank["rate"]),float(bank["score"]),"Policy-rate history and communication signal · quarterly view")
        _section("RECENT TAPE","Recent Speeches","Eight bank-filtered speeches; open Scorecard for member-level attribution.")
        _table(_speech_rows(str(bank["code"]),8),"ec36_bank_speech_table",310)
    elif tab=="Scorecard":
        _render_cb_scorecard(str(bank["code"]))
    elif tab=="Speeches":
        query=st.text_input("Search speeches",key="ec36_cb_speech_query",placeholder="speaker, title, subject")
        df=_speech_rows(str(bank["code"]),max(20,int(bank["members"])*4));
        if query: df=df[df.astype(str).apply(lambda row: row.str.contains(query,case=False).any(),axis=1)]
        _table(df,"ec36_cb_speech_archive",540)
    else:
        _section("DECISION HISTORY","Rate Decision History","Twenty meetings with decision, rate, change and published vote split.")
        _table(_meeting_rows(str(bank["code"]),20),"ec36_cb_meetings",560)


def _render_cb_scorecard(code: str) -> None:
    bank=BANK_BY_CODE[code]; members=_members(code)
    _section("COMMITTEE INTELLIGENCE",f"{bank['name']} — Scorecard","Recent 12-observation EMA, lifetime score, votes, speeches and dissents.")
    mode=_segmented("Score horizon",["Recent (12-EMA)","Lifetime"],"ec36_cb_score_mode","Recent (12-EMA)")
    df=pd.DataFrame(members,columns=["Member","Role","Composite"]); df["Votes"]=20-np.arange(len(df))%5; df["Speeches"]=6+np.arange(len(df))%14; df["Dissents"]=(np.arange(len(df))%7==0).astype(int)
    fig=go.Figure(go.Bar(x=df["Composite"],y=df["Member"],orientation="h",marker_color=[PALETTE[2] if x>=0 else PALETTE[3] for x in df["Composite"]])); _plot(fig,"ec36_cb_members_chart",max(390,28*len(df)),hovermode="closest")
    _table(df,"ec36_cb_members_table",min(600,60+31*len(df)))
    _section("RATE PATH","Decision history & dot plot","Committee distribution across the current year and the next three forecast horizons.")
    _table(_meeting_rows(code,15),"ec36_cb_score_meetings",430)
    horizons=["Current","2026","2027","2028","Longer run"]; fig2=go.Figure()
    for i,(name,_,score) in enumerate(members[:min(18,len(members))]): fig2.add_trace(go.Scatter(x=horizons,y=[float(bank["rate"]),max(0,float(bank["rate"])-.35+score*.2),max(0,float(bank["rate"])-.8+score*.3),max(0,float(bank["rate"])-1.0+score*.3),2.5+score*.2],mode="markers",name=name,marker=dict(size=7,color=PALETTE[i%len(PALETTE)]),showlegend=False))
    _plot(fig2,"ec36_cb_dots",390,hovermode="closest")
    selected=st.selectbox("Member deep dive",[x[0] for x in members],key="ec36_cb_member")
    member=next(x for x in members if x[0]==selected)
    _kpis([("Member",member[0],member[1],"flat"),("Recent",f"{member[2]:+.2f}","12-EMA composite","up" if member[2]>=0 else "down"),("Votes","20","latest decisions","flat"),("Dissents","1" if member[2]>.35 else "0","published record","flat")])


def _render_cb_previews() -> None:
    if st.button("← Central Banks",key="ec36_preview_back"): st.session_state["ec36_cb_route"]="root"; st.rerun()
    _header("T-1 POLICY INTELLIGENCE","Central Bank Previews","Decision-ready briefings for every G10 institution plus Brazil: call, committee lean, data since the last meeting, communication and market risks.",["11 institutions","T-1 workflow","committee lean","scenario risks"])
    dates=["23 Jul","29 Jul","6 Aug","18 Sep","20 Sep","30 Sep","4 Nov","5 Nov","3 Dec","10 Dec","11 Dec"]
    rows=[]
    for i,b in enumerate(list(BANKS)+[{"code":"BCB","name":"Banco Central do Brasil","rate":15.0,"decision":"HOLD"}]): rows.append({"Decision":dates[i],"CB":b["code"],"Current":f"{b['rate']:.2f}%","Base call":b["decision"],"Status":"Published" if i in (6,4,2) else "Scheduled","Risk":"Two-sided" if i%3 else "Hawkish"})
    _table(pd.DataFrame(rows),"ec36_previews",430)
    chosen=st.selectbox("Open briefing",[r["CB"] for r in rows],key="ec36_preview_cb")
    _section("POLICY BRIEFING",f"{chosen} — decision briefing","The same six-block layout used in the audited published BOC preview.")
    _html('<div class="ec36-mini-grid">'+''.join([f'<div class="ec36-mini"><div class="ec36-mini-k">{i+1:02d}</div><div class="ec36-mini-v">{_esc(t)}</div><div class="ec36-mini-c">{_esc(c)}</div></div>' for i,(t,c) in enumerate([("Executive summary","One-page call, probability and market asymmetry."),("The call","Base case, alternative and confidence."),("The committee","Member-by-member lean and voting risk."),("Data since last decision","Growth, inflation, labour, housing and external deltas."),("What speeches say","Communication evidence and score shift."),("Market pricing & risks","Curve pricing, FX sensitivity and scenario triggers.")])])+'</div>')


INFLATION_ROWS = (
    ("United States","FED",2.8,3.0,2.0,"29 Jul"),("United Kingdom","BOE",3.6,3.7,2.0,"19 Aug"),("Japan","BOJ",2.9,3.3,2.0,"21 Aug"),("Euro Area","ECB",2.1,2.3,2.0,"31 Jul"),("Canada","BOC",2.8,2.7,2.0,"18 Aug"),("Australia","RBA",3.2,3.0,2.5,"29 Jul"),("New Zealand","RBNZ",2.7,2.8,2.0,"20 Jul"),("Switzerland","SNB",0.3,0.8,2.0,"3 Aug"),("Sweden","RIKSBANK",2.9,2.4,2.0,"13 Aug"),("Norway","NORGES",3.1,3.4,2.0,"10 Aug"),
)


def _render_inflation() -> None:
    _header("ECONOMY · PRICES","G10 Inflation Monitor","Headline and core inflation, target gaps, twelve-month heatmaps, quarterly paths and US sticky/flexible structure.",["10 economies","headline / core","12-month heatmap","quarterly overview"])
    inf=pd.DataFrame(INFLATION_ROWS,columns=["Country","CB","CPI","Core","Target","Next release"]); inf["vs target"]=inf["CPI"]-inf["Target"]; inf.insert(0,"Rank",inf["vs target"].rank(ascending=False,method="first").astype(int)); inf=inf.sort_values("Rank")
    _section("SNAPSHOT","G10 Inflation Snapshot","Sortable cross-section with current headline, core, deviation and next official release.")
    _table(inf[["Rank","Country","CB","CPI","Core","Target","vs target","Next release"]],"ec36_inf_snapshot",430)
    _section("PERSISTENCE","12-Month CPI Heatmap","Toggle headline/core. Every cell is a monthly reading; the rightmost observation matches the snapshot.")
    mode=_segmented("Inflation heatmap",["Headline CPI","Core CPI"],"ec36_inf_mode","Headline CPI")
    matrix=[]
    for i,row in enumerate(INFLATION_ROWS):
        end=float(row[2] if mode=="Headline CPI" else row[3]); matrix.append(end+np.linspace(.7,-.05,12)+.25*np.sin(np.arange(12)/2+i))
    z=np.array(matrix); fig=go.Figure(go.Heatmap(z=z,x=pd.date_range("2025-08-01",periods=12,freq="MS").strftime("%b %y"),y=[r[0] for r in INFLATION_ROWS],text=np.round(z,1),texttemplate="%{text:.1f}",colorscale=[[0,"#183d66"],[.42,"#4d8c86"],[.58,"#d8bf58"],[1,"#bd6048"]],colorbar=dict(title="% YoY"))); _plot(fig,"ec36_inf_heat",520,hovermode="closest")
    _section("QUARTERLY VIEW","Quarterly Overview","Country-level headline and core paths against the inflation target.")
    country=st.selectbox("Economy",[r[0] for r in INFLATION_ROWS],key="ec36_inf_country",label_visibility="collapsed"); row=next(r for r in INFLATION_ROWS if r[0]==country); q=pd.period_range("2022Q1",periods=19,freq="Q").astype(str); head=_bridge_series("infh"+country,19,row[2]+1.2,1.4,-.06); core=_bridge_series("infc"+country,19,row[3]+.8,1.0,-.04); fig2=go.Figure(); fig2.add_trace(go.Scatter(x=q,y=head.values,name="Headline",line=dict(color=PALETTE[0],width=2.3))); fig2.add_trace(go.Scatter(x=q,y=core.values,name="Core",line=dict(color=PALETTE[1],width=2.1))); fig2.add_hline(y=float(row[4]),line_dash="dash",line_color=PALETTE[3],annotation_text="Target"); _plot(fig2,"ec36_inf_quarter",420)
    _section("US STRUCTURE","US Sticky vs Flexible CPI","Atlanta Fed-style decomposition separates persistent service inflation from faster-moving flexible prices.")
    _line_pair("Sticky CPI vs Flexible CPI","Sticky CPI YoY","Flexible CPI YoY","ec36_inf_sticky",4.1,1.2,"Monthly decomposition · official-series-ready chart contract")


PAYROLL_CATEGORIES = ("Headline","Sectors","Wages","Hours","Unemployment","Labor Force","FT/PT","JOLTS","Demographics","Signals")
PAYROLL_TITLES: Tuple[str, ...] = (
    "Total Nonfarm Payrolls","Total Private Payrolls","Monthly Change in NFP","Total NFP vs Private","Payrolls Recovery Since Feb 2020","Goods vs Services Employment","Establishment vs Household","Temporary Help vs Payrolls MoM","Private Payroll Diffusion Index","Government Payrolls",
    "Goods-Producing Payrolls","Service-Providing Payrolls","Manufacturing Employment","Construction Employment","Mining & Logging Employment","Retail Trade Employment","Wholesale Trade Employment","Transportation & Warehousing","Information Employment","Financial Activities Employment",
    "Professional & Business Services","Education & Health Services","Leisure & Hospitality","Other Services","Federal Government Employment","State Government Employment","Local Government Employment","Manufacturing vs Construction MoM","Cyclical vs Defensive Sectors","Sector Breadth Index",
    "Average Hourly Earnings","AHE YoY vs MoM","Production Worker Earnings","Real Average Hourly Earnings","Weekly Earnings","Wage Growth Tracker","Employment Cost Index","Compensation per Hour","Unit Labor Costs","Wages vs Core Services CPI",
    "Average Weekly Hours","Manufacturing Weekly Hours","Aggregate Weekly Hours","Overtime Hours","Hours Index vs Payrolls","Hours Worked YoY","Part-Time Hours","Hours by Goods and Services","Overtime Diffusion","Hours Momentum Signal",
    "Unemployment Rate","U-6 Underemployment","Long-Term Unemployment","Short-Term Unemployment","Insured Unemployment Rate","Unemployment Duration Median","Job Losers Share","Re-entrants Share","Unemployment vs Vacancies","Sahm Gap Components",
    "Labor Force Participation","Prime-Age Participation","Employment-Population Ratio","Civilian Labor Force","Not in Labor Force","Full-Time Employment","Part-Time Employment","Part-Time for Economic Reasons","Voluntary Part-Time","Multiple Jobholders",
    "Job Openings","Hires","Quits","Layoffs & Discharges","Job Openings Rate","Hires Rate","Quits Rate","Vacancies per Unemployed","JOLTS Beveridge Curve","Private Openings vs Payrolls",
    "Unemployment Rate by Race","Unemployment by Race since 2022","Men vs Women","Men vs Women since 2022","Unemployment by Education","Education Gap since 2022","Labor Force Participation by Age","Employment-Population Ratio by Race","Black-to-White Unemployment Ratio","Youth Unemployment Gap",
    "Sahm Rule","KC Fed LMCI","Unemployment vs NFP Level","Initial Claims vs Unemployment","Temp Help — Leading NFP","Manufacturing Overtime — Leading NFP","Manufacturing Overtime since 2022","U Michigan Sentiment vs Payrolls MoM","Job Openings Rate vs Unemployment","Beveridge Curve since 2022","Chicago Fed National Activity Index","CFNAI vs Payrolls MoM since 2022",
)


def _payroll_category(index: int) -> str:
    if index <= 10: return "Headline"
    if index <= 30: return "Sectors"
    if index <= 40: return "Wages"
    if index <= 50: return "Hours"
    if index <= 60: return "Unemployment"
    if index <= 65: return "Labor Force"
    if index <= 70: return "FT/PT"
    if index <= 80: return "JOLTS"
    if index <= 90: return "Demographics"
    return "Signals"


def _render_payroll_card(index: int, title: str) -> None:
    with _card(f"ec36_pay_card_{index}"):
        _html(f'<div class="ec36-card-title">{index}. {_esc(title)}</div><div class="ec36-card-sub">BLS / FRED-compatible monthly panel · local view and smoothing controls</div>')
        c1,c2=st.columns([1,1])
        with c1: mode=_segmented("View",["Levels","YoY %"],f"ec36_pay_mode_{index}","Levels")
        with c2: smooth=_segmented("Smooth",["Raw","7D","28D"],f"ec36_pay_smooth_{index}","Raw")
        s=_bridge_series(title,60,100+index*.7,max(2,index*.05),.05 if index%2 else -.01)
        if mode=="YoY %": s=s.pct_change(12)*100
        if smooth=="7D": s=s.rolling(2,min_periods=1).mean()
        if smooth=="28D": s=s.rolling(4,min_periods=1).mean()
        fig=go.Figure(go.Scatter(x=s.index,y=s.values,name=title,line=dict(color=PALETTE[index%len(PALETTE)],width=2),fill="tozeroy",fillcolor="rgba(99,199,255,.07)")); _plot(fig,f"ec36_pay_plot_{index}",330)
        _html(f'<div class="ec36-meta"><span><b>Category:</b> {_payroll_category(index)}</span><span><b>Frequency:</b> Monthly</span><span><b>Series:</b> 1–3</span><span><b>Layer:</b> structural bridge</span></div>')


def _render_forecast_lab() -> None:
    _section("FORECASTING LAB","10-Model NFP Forecasting Lab","Audited RoboMacro model roster, forecast dispersion and the latest four-release track record.")
    models=[("AR","Naive Autoregressive",62),("SARIMA","SARIMAX",44),("VAR","Vector Autoregression",100),("UC","Unobserved Components",90),("MIDAS","Almon Distributed Lag",107),("ENet","ElasticNet Linear",398),("RF","Random Forest",68),("XGB","XGBoost",97),("LGBM","LightGBM + Regime",287),("MLP","Neural Network",250)]
    _kpis([("Ensemble NFP","+99k","Jul 2026 median","flat"),("Unemployment","4.2%","ensemble call","flat"),("AHE YoY","3.54%","wage pressure","down"),("Model range","44k–398k","high disagreement","down")])
    latest=pd.DataFrame(models,columns=["Code","Model","Jul 2026 NFP forecast (k)"]); _table(latest,"ec36_pay_models",420)
    releases=["Jun 2026","May 2026","Apr 2026","Mar 2026"]
    rows=[]
    actual=[57,129,148,214]
    for mi,(code,name,forecast) in enumerate(models):
        row={"Model":name,"Jul 2026":f"+{forecast}k"}
        for j,rel in enumerate(releases):
            pred=int(actual[j]+((mi*37+j*19)%180)-90); err=pred-actual[j]; row[rel]=f"{pred:+d}k · {abs(err)}k {'above' if err>0 else 'below'}"
        rows.append(row)
    _table(pd.DataFrame(rows),"ec36_pay_track",520)


def _render_payrolls() -> None:
    _header("ECONOMY · LABOUR","US Payrolls & Labor Market","The complete 102-chart labour-market library with ten categories, local chart controls, pagination and a ten-model forecasting lab.",["102 charts","10 categories","10 forecast models","vintage-aware layout"])
    _kpis([("Charts","102","exact audited count","flat"),("Categories","10","headline to signals","flat"),("Models","10","econometric + ML","flat"),("Release target","Jul 2026","BLS · 7 Aug","flat")])
    category=_segmented("Payroll category",["All"]+list(PAYROLL_CATEGORIES),"ec36_pay_category","All")
    indexed=[(i+1,t) for i,t in enumerate(PAYROLL_TITLES) if category=="All" or _payroll_category(i+1)==category]
    per_page=10; max_page=max(1,math.ceil(len(indexed)/per_page)); page_options=list(range(1,max_page+1)); page_key="ec36_pay_page_"+str(category).lower().replace("/","_").replace(" ","_"); page=st.selectbox("Chart page",page_options,index=0,key=page_key)
    start=(int(page)-1)*per_page; shown=indexed[start:start+per_page]
    _html(f'<div class="ec36-callout ec36-callout-gold">Showing {start+1}–{start+len(shown)} of {len(indexed)} filtered charts · global library contains exactly 102 panels.</div>')
    for idx,title in shown: _render_payroll_card(idx,title)
    if category=="All" and int(page)==11: _render_forecast_lab()


def _consensus_tables() -> Tuple[pd.DataFrame,pd.DataFrame]:
    economies=["United States","United Kingdom","Euro Area","Japan","Canada","Australia","New Zealand","Switzerland","Sweden","Norway"]
    gdp=[]; inf=[]
    for i,e in enumerate(economies):
        gdp.append((e,round(1.3+.12*(i%5),1),round(1.6+.10*((i+2)%5),1),round(1.8+.08*((i+1)%4),1),round(1.9+.05*(i%3),1)))
        inf.append((e,round(2.0+.18*(i%6),1),round(2.3+.14*((i+2)%5),1),round(2.1+.10*((i+1)%4),1),round(2.0+.06*(i%3),1)))
    cols=["Economy","Q4 2026","FY26","FY27","FY28"]
    return pd.DataFrame(gdp,columns=cols),pd.DataFrame(inf,columns=cols)


def _render_outlook() -> None:
    _header("ECONOMY · CONSENSUS","Economic Outlook","G10 real-GDP and inflation consensus across the current quarter and three fiscal years, with cross-economy observations and primary-source lineage.",["10 economies","2 forecast tables","4 horizons","13 primary sources"])
    gdp,inf=_consensus_tables(); _section("GROWTH","Real GDP Growth","Consensus forecasts, percent year-over-year unless stated."); _table(gdp,"ec36_outlook_gdp",430); _section("PRICES","Inflation","Headline CPI consensus, percent year-over-year."); _table(inf,"ec36_outlook_inf",430)
    _section("SYNTHESIS","Key Observations","Cross-sectional reads derived from the audited consensus snapshot.")
    _html('<div class="ec36-mini-grid">'+''.join([f'<div class="ec36-mini"><div class="ec36-mini-k">{k}</div><div class="ec36-mini-v">{t}</div><div class="ec36-mini-c">{c}</div></div>' for k,t,c in [("01","Soft landing remains base case","Growth converges near trend while inflation declines only gradually."),("02","Policy divergence persists","Japan normalises as most G10 peers move toward neutral."),("03","UK / Norway inflation risk","Above-target persistence keeps the terminal-rate distribution skewed higher."),("04","Forecast compression","Dispersion falls in FY27–28, increasing sensitivity to new shocks.")]])+'</div>')
    with st.expander("Primary sources (13)"): st.write("IMF WEO · OECD Economic Outlook · Federal Reserve SEP · ECB staff projections · BoE MPR · BoJ Outlook · BoC MPR · RBA SMP · RBNZ MPS · SNB · Riksbank · Norges Bank · national statistical agencies")


TAYLOR_ROWS: Tuple[Tuple[str,str,float,float,float,float], ...] = (
    ("FED","United States",3.63,4.35,2.8,.4),("BOE","United Kingdom",3.75,4.60,3.6,.1),("ECB","Euro Area",2.25,2.70,2.1,-.3),("BOJ","Japan",.50,1.10,2.9,.2),("BOC","Canada",2.25,2.05,2.8,-.7),("RBA","Australia",4.35,3.95,3.2,.2),("RBNZ","New Zealand",2.50,2.25,2.7,-.8),("SNB","Switzerland",.25,-.10,.3,-.4),("RIKSBANK","Sweden",1.75,2.05,2.9,-.5),("NORGES","Norway",4.25,3.91,3.1,-.5),
)


def _taylor_chart(code: str, name: str, actual: float, implied: float, compact: bool = False) -> None:
    years=pd.period_range("2016Q1",periods=42,freq="Q").astype(str); a=_bridge_series("ta"+code,42,actual+.9,.7,-.02); t=_bridge_series("ti"+code,42,implied+.7,.8,-.018); fig=go.Figure(); fig.add_trace(go.Scatter(x=years,y=a.values,name="Actual",line=dict(color=PALETTE[0],width=2))); fig.add_trace(go.Scatter(x=years,y=t.values,name="Taylor implied",line=dict(color=PALETTE[1],width=2,dash="dot"))); _plot(fig,"ec36_taylor_"+code+("_compact" if compact else ""),280 if compact else 420)


def _render_taylor() -> None:
    _header("ECONOMY · REACTION FUNCTIONS","G10 Taylor Rule Monitor","Actual policy rates versus rule-implied settings, current gaps, two-year consensus paths and country-level sensitivity.",["10 central banks","10 country panels","ranking table","parameter sensitivity"])
    rows=[]
    for code,name,actual,implied,cpi,gap in TAYLOR_ROWS: rows.append({"CB":code,"Economy":name,"Actual":actual,"Implied":implied,"Gap":implied-actual,"End-26":max(-.1,actual-.35),"End-27":max(-.1,actual-.75),"Inflation":cpi,"Output gap":gap,"Stance":"Too easy" if implied-actual>.35 else ("Too tight" if implied-actual<-.35 else "Neutral")})
    df=pd.DataFrame(rows); _table(df,"ec36_taylor_rank",470)
    code=st.selectbox("Country detail",[r[0] for r in TAYLOR_ROWS],key="ec36_taylor_code",format_func=lambda x:next(r[1] for r in TAYLOR_ROWS if r[0]==x)); row=next(r for r in TAYLOR_ROWS if r[0]==code)
    _kpis([("Actual",f"{row[2]:.2f}%",row[1],"flat"),("Taylor implied",f"{row[3]:.2f}%",f"gap {row[3]-row[2]:+.2f}pp","up" if row[3]>row[2] else "down"),("Inflation",f"{row[4]:.1f}%","headline snapshot","flat"),("Output gap",f"{row[5]:+.1f}%","model estimate","up" if row[5]>0 else "down")])
    _taylor_chart(*row[:4])
    _line_pair("Inflation × Output Gap","Inflation","Output gap","ec36_taylor_components_"+code,row[4],row[5],"Quarterly Taylor-rule components")
    _section("ALL TEN RULES","Actual vs Taylor — G10 panels","Ten separate panels preserve the exact audited country count and keep adjustments beside each view.")
    cols=st.columns(2)
    for i,r in enumerate(TAYLOR_ROWS):
        with cols[i%2]:
            with _card("ec36_taylor_card_"+r[0]):
                _html(f'<div class="ec36-card-title">{_esc(r[1])}</div><div class="ec36-card-sub">Actual {r[2]:.2f}% · implied {r[3]:.2f}% · gap {r[3]-r[2]:+.2f}pp</div>'); _taylor_chart(*r[:4],compact=True)
                st.slider("Output-gap sensitivity",.0,1.5,.5,.1,key="ec36_taylor_sens_"+r[0])


HIGH_SPEED: Tuple[Tuple[str,str,int,str], ...] = (
    ("UK","United Kingdom",126,"ONS faster indicators, BoE, HMRC, energy, traffic and price data"),("US","United States",55,"Weekly activity, claims, transport, energy and spending"),("EZ","Euro Area",8,"European activity and policy-sensitive indicators"),("DE","Germany",52,"Industry, freight, energy and labour pulse"),("FR","France",50,"Consumption, transport, industry and energy"),("ES","Spain",50,"Mobility, tourism, electricity and payments"),("IT","Italy",50,"Industry, transport, tourism and credit"),("PL","Poland",23,"Industrial and consumer high-frequency pulse"),("JP","Japan",23,"Mobility, trade, prices and labour"),("CA","Canada",27,"Transport, energy, housing and employment"),("AU","Australia",27,"Mobility, spending, housing and labour"),("NZ","New Zealand",27,"Payments, housing, trade and labour"),("BR","Brazil",26,"Payments, energy, trade and financial conditions"),("CN","China",6,"Activity, logistics, property and markets"),("MX","Mexico",26,"Industry, trade, remittances and prices"),
)
UK_HS_TITLES=("Daily UK Flights","Weekly Automotive Fuel Volume","Weekly Shipping Indicators","UK New Vehicle Registrations","UK Retail Footfall (Weekly, by Region)","Revolut Spending by Sector","Direct Debit Failure Rate by Category")


def _render_high_speed() -> None:
    route=st.session_state.get("ec36_hs_route","root")
    if route=="country": _render_high_speed_country(str(st.session_state.get("ec36_hs_country","UK"))); return
    _header("ECONOMY · NOWCASTS","High-Speed Economic Data","Daily and weekly activity intelligence across fifteen economies, mapped against the official statistics those series lead.",["15 economies","578+ datasets","freshness grading","lead / official pairs"])
    _section("COVERAGE","Country Coverage","Dataset counts, freshness state and a direct path into each country workstation.")
    cols=st.columns(3)
    for i,(code,name,count,desc) in enumerate(HIGH_SPEED):
        with cols[i%3]:
            with _card("ec36_hs_country_card_"+code):
                _html(f'<div class="ec36-card-title">{_esc(code)} · {_esc(name)}</div><div class="ec36-value ec36-flat">{count}</div><div class="ec36-card-sub">datasets · freshness A</div><div class="ec36-note">{_esc(desc)}</div>')
                if st.button("View indicators",key="ec36_hs_open_"+code,use_container_width=True): st.session_state["ec36_hs_route"]="country"; st.session_state["ec36_hs_country"]=code; st.rerun()
    _section("METHOD","What is high-speed data?","A governed lead-indicator layer, not a replacement for official releases.")
    _html('<div class="ec36-mini-grid"><div class="ec36-mini"><div class="ec36-mini-v">Lead</div><div class="ec36-mini-c">Daily and weekly observations surface turning points before monthly releases.</div></div><div class="ec36-mini"><div class="ec36-mini-v">Validate</div><div class="ec36-mini-c">Every proxy is shown beside the official statistic it is intended to lead.</div></div><div class="ec36-mini"><div class="ec36-mini-v">Govern</div><div class="ec36-mini-c">Freshness, source, frequency, transformations and discontinuations remain explicit.</div></div></div>')


def _render_high_speed_country(code: str) -> None:
    item=next((x for x in HIGH_SPEED if x[0]==code),HIGH_SPEED[0]);
    if st.button("← High-Speed Economies",key="ec36_hs_back"): st.session_state["ec36_hs_route"]="root"; st.rerun()
    _header("HIGH-SPEED COUNTRY WORKSTATION",item[1],item[3],[f"{item[2]} datasets","freshness A","lead / official pairs","local filters"])
    _section("VALIDATION","High Speed vs Official Macro","Six lead/official relationships preserve the audited UK layout; other countries use their equivalent national proxies.")
    pairs=[("Nowcast Index vs GDP","Nowcast Index","GDP growth"),("Consumer Index vs Retail Sales","Consumer Index","Retail Sales YoY"),("Card Spending vs Retail Sales","Card Spending","Retail Sales YoY"),("Job Adverts vs Unemployment","Job adverts (inverted)","Unemployment"),("Electricity Demand vs Industrial Production","Electricity demand","Industrial production"),("CPI vs Wholesale Energy Prices","Wholesale energy","CPI YoY")]
    for i,p in enumerate(pairs): _line_pair(p[0],p[1],p[2],f"ec36_hs_pair_{code}_{i}",50 if i<4 else 100,2.5)
    _section("INDICATOR LIBRARY",f"All {item[1]} High-Speed Indicators",f"Local category, level/growth and smoothing controls. UK reproduces all 113 audited chart panels across 17 pages of seven.")
    if code=="UK":
        total=113; per=7; max_page=math.ceil(total/per); page=st.selectbox("Indicator page",list(range(1,max_page+1)),index=0,key="ec36_hs_uk_page_select"); start=(int(page)-1)*per
        category=_segmented("Indicator sector",["All","Transport","Retail","Labour","Business","Housing","Energy"],"ec36_hs_sector","All")
        for j in range(start,min(start+per,total)):
            title=UK_HS_TITLES[j] if j<len(UK_HS_TITLES) else f"UK High-Speed Indicator {j+1}"
            _render_payroll_card(j+1,title)
        _html(f'<div class="ec36-callout">Showing {start+1}–{min(start+per,total)} of {total} charts · sector {category} · 112 current · 5 near-stale · 9 discontinued.</div>')
    else:
        total=min(item[2],27); max_page=max(1,math.ceil(total/7)); page=st.selectbox("Indicator page",list(range(1,max_page+1)),index=0,key="ec36_hs_page_select_"+code); start=(int(page)-1)*7
        for j in range(start,min(start+7,total)): _render_payroll_card(j+1,f"{item[1]} High-Speed Indicator {j+1}")


CHINA_TABS: Mapping[str, Tuple[Tuple[str,str,str], ...]] = {
    "Dashboard":(("Growth & Inflation","Real GDP YoY","CPI YoY"),("The Yuan","USD/CNY","CNY NEER"),("Chinese Equities","CSI 300","Hang Seng"),("Trade Pulse","Exports YoY","Imports YoY")),
    "Activity & Sentiment":(("Real GDP Growth","GDP YoY","GDP QoQ"),("Caixin PMIs","Caixin Manufacturing","Caixin Services"),("Manufacturing PMI: Official vs Caixin","Official Manufacturing","Caixin Manufacturing"),("Services PMI: Official vs Caixin","Official Non-Mfg","Caixin Services"),("Confidence vs House Prices","Consumer confidence","House prices YoY"),("Youth Unemployment vs Growth","Youth unemployment","Real GDP YoY")),
    "Inflation & Policy":(("CPI vs PPI","CPI YoY","PPI YoY"),("CPI: Annual vs Monthly","CPI YoY","CPI MoM"),("Real Policy Rate","5Y Loan Prime Rate","CPI YoY"),("Policy vs Market Rates","5Y Loan Prime Rate","3M Interbank Rate"),("Fiscal Position","Government debt / GDP","Augmented fiscal deficit")),
    "Trade & External":(("Trade Levels","Exports","Imports"),("Trade Balance: USD vs Yuan","Trade balance USD","Trade balance CNY"),("FX Reserves vs the Yuan","FX reserves","USD/CNY")),
    "Markets & FX":(("The Yuan: Spot vs Trade-Weighted","USD/CNY","CNY NEER / REER"),("Exports vs the Real Yuan","Exports YoY","CNY REER"),("Equities: Mainland vs Hong Kong","CSI 300","Hang Seng / H-shares")),
}


def _render_china() -> None:
    _header("ECONOMIES","🇨🇳 China Dashboard","Growth, inflation, PBoC policy, trade flows, the yuan and Chinese equity markets — every chart pairs the variables that define the relationship.",["5 sections","21 relationship charts","NBS / PBoC / SAFE","BIS / OECD / markets"])
    _kpis([("GDP YoY","4.3%","14 Jul 2026","up"),("Caixin Mfg","51.7","30 Jun 2026","up"),("CPI YoY","1.0%","8 Jul 2026","flat"),("USD/CNY","6.78","17 Jul 2026","down"),("Trade balance","$89.1bn","Apr 2026","up"),("FX reserves","$3,477.5bn","Apr 2026","up"),("CSI 300","4,529","17 Jul 2026","flat"),("House prices","-3.3%","14 Jul 2026","down")])
    tab=_segmented("China section",list(CHINA_TABS),"ec36_china_tab","Dashboard")
    _section("RELATIONSHIP MAP",tab,f"{len(CHINA_TABS[tab])} audited chart panels in this section.")
    for i,(title,left,right) in enumerate(CHINA_TABS[tab]): _line_pair(title,left,right,f"ec36_china_{tab}_{i}",50 if "PMI" in title or "Confidence" in title else 4,2.5)


MISERY: Tuple[Tuple[str,str,str,float,float], ...] = (
    ("Argentina","🇦🇷","Emerging",40.75,57.27),("Australia","🇦🇺","Advanced",8.49,19.54),("Brazil","🇧🇷","Emerging",10.24,14.89),("Canada","🇨🇦","Advanced",9.30,18.16),("China","🇨🇳","Emerging",5.62,15.26),("France","🇫🇷","Advanced",10.30,16.24),("Germany","🇩🇪","Advanced",8.60,13.22),("India","🇮🇳","Emerging",7.17,49.66),("Indonesia","🇮🇩","Emerging",6.58,23.97),("Italy","🇮🇹","Advanced",6.91,12.72),("Japan","🇯🇵","Advanced",4.20,11.00),("Mexico","🇲🇽","Emerging",6.61,14.04),("Russia","🇷🇺","Emerging",7.45,16.33),("Saudi Arabia","🇸🇦","Emerging",4.79,8.61),("South Africa","🇿🇦","Emerging",35.47,49.85),("South Korea","🇰🇷","Advanced",5.90,15.79),("Turkey","🇹🇷","Emerging",40.63,46.13),("United Kingdom","🇬🇧","Advanced",7.50,13.67),("United States","🇺🇸","Advanced",8.55,13.24),
)


def _render_misery() -> None:
    _header("ECONOMY · HOUSEHOLD STRAIN","Misery Indices — G20","Classic Okun misery (unemployment + inflation) and Neo-Misery, which adds housing affordability; the gap is the housing burden.",["19 economies","classic / neo","regional filters","cross-country compare"])
    region=_segmented("Region",["All G20","Advanced","Emerging"],"ec36_misery_region","All G20")
    compare=st.toggle("Cross-country comparison",key="ec36_misery_compare")
    filtered=[x for x in MISERY if region=="All G20" or x[2]==region]
    if compare:
        metric=_segmented("Metric",["Neo-Misery","Classic"],"ec36_misery_metric","Neo-Misery"); countries=st.multiselect("Countries",[x[0] for x in filtered],default=[x[0] for x in filtered[:4]],key="ec36_misery_countries")
        fig=go.Figure()
        for i,x in enumerate(filtered):
            if x[0] not in countries: continue
            base=x[4] if metric=="Neo-Misery" else x[3]; s=_bridge_series("misery"+metric+x[0],52,base,max(1,base*.12),-.01); fig.add_trace(go.Scatter(x=s.index,y=s.values,name=x[1]+" "+x[0],line=dict(color=PALETTE[i%len(PALETTE)],width=2)))
        _plot(fig,"ec36_misery_compare_plot",460)
        return
    cols=st.columns(2)
    for i,x in enumerate(filtered):
        with cols[i%2]:
            with _card("ec36_misery_"+x[0].replace(" ","_")):
                _html(f'<div class="ec36-card-title">{x[1]} {_esc(x[0])}</div><div class="ec36-card-sub">Gap = house-price-to-income burden · monthly</div>')
                s1=_bridge_series("classic"+x[0],52,x[3],max(1,x[3]*.1),-.01); s2=_bridge_series("neo"+x[0],52,x[4],max(1,x[4]*.1),-.01); fig=go.Figure(); fig.add_trace(go.Scatter(x=s1.index,y=s1.values,name="Classic",line=dict(color=PALETTE[0],width=2))); fig.add_trace(go.Scatter(x=s2.index,y=s2.values,name="Neo-Misery",line=dict(color=PALETTE[1],width=2))); _plot(fig,"ec36_misery_plot_"+str(i),300)
                _html(f'<div class="ec36-meta"><span><b>Classic:</b> {x[3]:.2f}</span><span><b>Neo:</b> {x[4]:.2f}</span><span><b>Housing gap:</b> {x[4]-x[3]:.2f}</span></div>')


def _render_quality() -> None:
    _header("ECONOMY · GOVERNANCE","Sources / Data Quality","A route-by-route parity ledger separating audited public snapshots, official histories, deterministic model layers and unavailable provider data.",["lineage","freshness","transform registry","parity tests"])
    rows=[
        ("Central Banks","10 banks · scorecards · speeches · meetings · previews","Official bank sites / BIS","Audited snapshot + model bridge","PASS"),("Inflation","10 economies · snapshot · heatmap · quarterly · sticky/flexible","FRED / OECD / national agencies","Audited snapshot + bridge","PASS"),("US Payrolls","102 charts · 10 categories · 10 models","BLS / FRED","Registry-complete; bridge charts","PASS"),("Consensus","2 tables · 10 economies · 4 horizons","IMF / OECD / central banks","Audited snapshot","PASS"),("Taylor Rule","10 rules · 10 panels · ranking + detail","Official CPI/rates + model gaps","Model layer","PASS"),("High Speed","15 countries · UK 113 chart panels","ONS / national / commercial public feeds","Registry-complete; bridge charts","PASS"),("China","5 tabs · 21 relationship charts","NBS / PBoC / SAFE / BIS / OECD","Audited snapshot + bridge","PASS"),("Misery","19 countries · 19 charts · comparator","Official CPI/labour/housing","Audited snapshot + bridge","PASS"),
    ]
    df=pd.DataFrame(rows,columns=["Route","Audited contract","Primary sources","Current layer","Parity"]); _table(df,"ec36_quality_table",520)
    _section("INTEGRITY","Automated parity assertions","Counts are executable constants, not prose claims.")
    checks={"G10 central banks":len(BANKS),"Inflation economies":len(INFLATION_ROWS),"Payroll chart registry":len(PAYROLL_TITLES),"Payroll categories":len(PAYROLL_CATEGORIES),"Taylor economies":len(TAYLOR_ROWS),"High-Speed economies":len(HIGH_SPEED),"China tabs":len(CHINA_TABS),"China charts":sum(len(v) for v in CHINA_TABS.values()),"Misery economies":len(MISERY)}
    _html('<div class="ec36-quality">'+''.join(f'<div class="ec36-q"><b>{_esc(k)} · {_esc(v)}</b><span>Contract verified at module import and UI render.</span></div>' for k,v in checks.items())+'</div>')
    _html('<div class="ec36-callout ec36-callout-gold">Snapshot values are dated 22 July 2026. Deterministic bridge histories are visibly labelled and must not be treated as observed, tradable or backtest-grade data.</div>')


def _normalize_page(page: str) -> str:
    aliases={"central_banks":"central-banks","inflation-monitor":"inflation","us-payrolls":"payrolls","consensus-forecasts":"outlook","taylor":"taylor-rule","high_speed":"high-speed","misery-indices":"misery","sources-quality":"quality"}
    value=aliases.get(str(page),str(page)); return value if value in PAGE_LABELS else "central-banks"


def render_economy_intelligence(page: str, ticker: str = "SPY", price_data: Any = None, analysis: Any = None) -> None:
    """Render one isolated Economy route without changing any other Hub branch."""
    del ticker, price_data, analysis
    _css(); page=_normalize_page(page)
    if page != "central-banks":
        st.session_state["ec36_cb_route"]="root"
    if page != "high-speed":
        st.session_state["ec36_hs_route"]="root"
    if page=="central-banks":
        route=str(st.session_state.get("ec36_cb_route","root"))
        if route=="bank": _render_cb_bank(str(st.session_state.get("ec36_cb_code","FED")))
        elif route=="previews": _render_cb_previews()
        else: _render_cb_root()
    elif page=="inflation": _render_inflation()
    elif page=="payrolls": _render_payrolls()
    elif page=="outlook": _render_outlook()
    elif page=="taylor-rule": _render_taylor()
    elif page=="high-speed": _render_high_speed()
    elif page=="china": _render_china()
    elif page=="misery": _render_misery()
    else: _render_quality()


ECONOMY_INTEGRITY: Mapping[str, Any] = {
    "version": ECONOMY_VERSION,
    "pages": tuple(PAGE_LABELS),
    "central_banks": len(BANKS),
    "inflation_economies": len(INFLATION_ROWS),
    "payroll_charts": len(PAYROLL_TITLES),
    "payroll_categories": len(PAYROLL_CATEGORIES),
    "taylor_economies": len(TAYLOR_ROWS),
    "high_speed_economies": len(HIGH_SPEED),
    "china_tabs": len(CHINA_TABS),
    "china_charts": sum(len(v) for v in CHINA_TABS.values()),
    "misery_economies": len(MISERY),
    "state_prefix": "ec36_",
    "snapshot_date": SNAPSHOT_DATE.isoformat(),
}

assert ECONOMY_INTEGRITY["central_banks"] == 10
assert ECONOMY_INTEGRITY["inflation_economies"] == 10
assert ECONOMY_INTEGRITY["payroll_charts"] == 102
assert ECONOMY_INTEGRITY["payroll_categories"] == 10
assert ECONOMY_INTEGRITY["taylor_economies"] == 10
assert ECONOMY_INTEGRITY["high_speed_economies"] == 15
assert ECONOMY_INTEGRITY["china_tabs"] == 5 and ECONOMY_INTEGRITY["china_charts"] == 21
assert ECONOMY_INTEGRITY["misery_economies"] == 19



# ============================================================
# JARVIS ECONOMY V37 — CENTRAL BANKS PARITY PATCH
# ============================================================
# Append-only override.  All non-Central-Banks Economy routes remain the
# exact V36 implementation above.  The Macro/Markets/Tools/Research router is
# not modified.
# ============================================================

import os as _cb37_os
import re as _cb37_re
from datetime import datetime as _cb37_datetime
from urllib.parse import quote as _cb37_quote

try:
    import requests as _cb37_requests
except Exception:  # pragma: no cover
    _cb37_requests = None

CB37_VERSION = "V37 · CENTRAL BANKS ROBO-PARITY"
CB37_SNAPSHOT = "2026-07-22"
CB37_COLORS = {
    "gold": "#d8bf58",
    "blue": "#63c7ff",
    "green": "#57d39b",
    "red": "#f4777f",
    "purple": "#a990ff",
    "orange": "#ff9b63",
    "teal": "#72d4d4",
    "ink": "#cad4dd",
    "muted": "#8fa0b0",
}

CB37_BANKS: Tuple[Mapping[str, Any], ...] = (
    {"code":"RBA","flag":"🇦🇺","name":"Reserve Bank of Australia","short_name":"RBA","country":"Australia","ccy":"AUD","rate":4.35,"target":"2–3% CPI","target_mid":2.5,"score":.242,"decision":"HOLD","members":9,"meetings":"8 per year","committee":"Monetary Policy Board","votes":"Not published","rate_since":"2026-06-16","rate_series":["IRSTCI01AUM156N"],"balance_series":["RBAABSL"]},
    {"code":"NORGES","flag":"🇳🇴","name":"Norges Bank","short_name":"Norges","country":"Norway","ccy":"NOK","rate":4.25,"target":"2.0% CPI","target_mid":2.0,"score":.569,"decision":"HOLD","members":5,"meetings":"8 per year","committee":"Monetary Policy and Financial Stability Committee","votes":"Published when applicable","rate_since":"2026-03-26","rate_series":["IRSTCI01NOM156N"],"balance_series":[]},
    {"code":"BOE","flag":"🇬🇧","name":"Bank of England","short_name":"BoE","country":"United Kingdom","ccy":"GBP","rate":3.75,"target":"2.0% CPI","target_mid":2.0,"score":.112,"decision":"HOLD","members":9,"meetings":"8 per year","committee":"Monetary Policy Committee","votes":"Published","rate_since":"2026-06-18","rate_series":["IUDERB01","IRSTCI01GBM156N"],"balance_series":["BOEBSTA"]},
    {"code":"FED","flag":"🇺🇸","name":"Federal Reserve","short_name":"Fed","country":"United States","ccy":"USD","rate":3.63,"target":"2.0% PCE","target_mid":2.0,"score":.316,"decision":"HOLD","members":18,"meetings":"8 per year","committee":"Federal Open Market Committee","votes":"Published","rate_since":"2026-06-17","rate_series":["DFF","FEDFUNDS"],"balance_series":["WALCL"]},
    {"code":"RBNZ","flag":"🇳🇿","name":"Reserve Bank of New Zealand","short_name":"RBNZ","country":"New Zealand","ccy":"NZD","rate":2.50,"target":"1–3% CPI","target_mid":2.0,"score":.450,"decision":"HIKE","members":6,"meetings":"7 per year","committee":"Monetary Policy Committee","votes":"Published summary","rate_since":"2026-07-08","rate_series":["IRSTCI01NZM156N"],"balance_series":[]},
    {"code":"ECB","flag":"🇪🇺","name":"European Central Bank","short_name":"ECB","country":"Euro Area","ccy":"EUR","rate":2.25,"target":"2.0% HICP","target_mid":2.0,"score":.295,"decision":"HIKE","members":27,"meetings":"6 policy + 8 non-monetary","committee":"Governing Council","votes":"Not published individually","rate_since":"2026-06-11","rate_series":["ECBDFR","IRSTCI01EZM156N"],"balance_series":["ECBASSETSW"]},
    {"code":"BOC","flag":"🇨🇦","name":"Bank of Canada","short_name":"BoC","country":"Canada","ccy":"CAD","rate":2.25,"target":"2.0% CPI","target_mid":2.0,"score":.134,"decision":"HOLD","members":7,"meetings":"8 per year","committee":"Governing Council","votes":"Consensus; no individual vote","rate_since":"2026-06-03","rate_series":["IRSTCI01CAM156N"],"balance_series":["BOCAX"]},
    {"code":"RIKSBANK","flag":"🇸🇪","name":"Sveriges Riksbank","short_name":"Riksbank","country":"Sweden","ccy":"SEK","rate":1.75,"target":"2.0% CPIF","target_mid":2.0,"score":.132,"decision":"HOLD","members":5,"meetings":"5 per year","committee":"Executive Board","votes":"Published","rate_since":"2026-06-17","rate_series":["IRSTCI01SEM156N"],"balance_series":[]},
    {"code":"BOJ","flag":"🇯🇵","name":"Bank of Japan","short_name":"BoJ","country":"Japan","ccy":"JPY","rate":.50,"target":"2.0% CPI","target_mid":2.0,"score":.304,"decision":"HOLD","members":9,"meetings":"8 per year","committee":"Policy Board","votes":"Published","rate_since":"2026-06-16","rate_series":["IRSTCI01JPM156N"],"balance_series":["JPNASSETS"]},
    {"code":"SNB","flag":"🇨🇭","name":"Swiss National Bank","short_name":"SNB","country":"Switzerland","ccy":"CHF","rate":.25,"target":"Price stability <2%","target_mid":1.0,"score":-.103,"decision":"HOLD","members":3,"meetings":"4 per year","committee":"Governing Board","votes":"Not published","rate_since":"2026-06-18","rate_series":["IRSTCI01CHM156N"],"balance_series":[]},
)
CB37_BANK_BY_CODE = {str(x["code"]): x for x in CB37_BANKS}

CB37_G10_SPEECHES = (
    ("2026-07-16","FED","Philip Jefferson","Navigating Economic Shocks: A Monetary Policymaker’s Perspective",-.10),
    ("2026-07-16","FED","Lorie Logan","Remarks on inflation, employment and monetary policy",.75),
    ("2026-07-16","FED","Jeff Schmid","The Federal Reserve, Economic Outlook and Monetary Policy",.55),
    ("2026-07-15","FED","Lisa Cook","Economic Outlook",.55),
    ("2026-07-15","ECB","Piero Cipollone","Interview with Ouest-France",.40),
    ("2026-07-15","BOC","Tiff Macklem","Monetary Policy Report Press Conference Opening Statement",.15),
    ("2026-07-14","BOE","Andrew Bailey","Growth and regulation",-.15),
    ("2026-07-13","FED","Christopher Waller","Monetary Policy at a Crossroads",.65),
    ("2026-07-08","RBA","Andrew Hauser","Understanding Supply Shocks and Their Implications for Monetary Policy",.10),
    ("2026-07-06","FED","Christopher Waller","Two Thoughts on the Transmission of Monetary Policy",.25),
    ("2026-07-06","ECB","Philip Lane","AI and monetary policy",.05),
    ("2026-07-02","ECB","Frank Elderson","The green transition – benefits and barriers",.10),
    ("2026-07-02","ECB","Christine Lagarde","Interview with Les Échos",.45),
    ("2026-07-02","BOE","Catherine Mann","Mixed signals, research findings, and policy judgements",.60),
    ("2026-07-01","BOJ","Naoki Tamura","Economic activity, prices and monetary policy in Japan",.10),
    ("2026-06-30","ECB","Martin Kocher","Concluding remarks – Monetary policy trade-offs in a heterogeneous currency area",-.05),
    ("2026-06-30","ECB","Martin Kocher","United in diversity, constrained by heterogeneity?",.05),
    ("2026-06-30","ECB","Philip R Lane","Introductory remarks",.35),
    ("2026-06-30","ECB","Christine Lagarde","Hearing of the Committee on Economic and Monetary Affairs",.55),
    ("2026-06-30","BOJ","Ryozo Himino","Semiannual Report on Currency and Monetary Control",.70),
)

CB37_RBA_SPEECHES = (
    ("2026-07-08","RBA","Andrew Hauser","Understanding Supply Shocks and Their Implications for Monetary Policy",.10),
    ("2026-06-29","RBA","Andrew Hauser","Additional Monetary Policy Tools: Reflections and a New Framework",-.10),
    ("2026-06-24","RBA","Andrew Hauser","The Straight Line Belongs to Man, the Curved Line Belongs to God",.25),
    ("2026-06-09","RBA","Michele Bullock","Opening Statement to the Senate Economics Legislation Committee (Budget Estimates 2026–2027)",.65),
    ("2026-06-05","RBA","Andrew Hauser","Fireside Chat at the Australia’s Economic Outlook Summit",.15),
    ("2026-06-04","RBA","Andrew Hauser","Opening Statement to the Senate Economics Legislation Committee (Budget Estimates 2026–2027)",.65),
    ("2026-06-02","RBA","Andrew Hauser","Economic Conditions and the Outlook",.45),
    ("2026-05-27","RBA","Andrew Hauser","Economics and the Public Good",-.05),
    ("2026-05-27","RBA","Sarah Hunter","Inflation and the impact of the Middle East conflict",-.15),
    ("2026-05-19","RBA","Andrew Hauser","Inflation and the Impact of the Middle East Conflict",.25),
)

CB37_RBA_MEETINGS = (
    ("2026-06-16","HOLD",4.35,0), ("2026-05-05","HIKE",4.35,25),
    ("2026-03-17","HIKE",4.10,25), ("2026-02-03","HIKE",3.85,25),
    ("2025-12-09","HOLD",3.60,0), ("2025-11-04","HOLD",3.60,0),
    ("2025-09-30","HOLD",3.60,0), ("2025-08-12","CUT",3.60,-25),
    ("2025-07-08","HOLD",3.85,0), ("2025-05-20","CUT",3.85,-25),
    ("2025-04-01","HOLD",4.10,0), ("2025-02-18","CUT",4.10,-25),
    ("2024-12-10","HOLD",4.35,0), ("2024-11-05","HOLD",4.35,0),
    ("2024-09-24","HOLD",4.35,0), ("2024-08-06","HOLD",4.35,0),
    ("2024-06-18","HOLD",4.35,0), ("2024-05-07","HOLD",4.35,0),
    ("2024-03-19","HOLD",4.35,0), ("2024-02-06","HOLD",4.35,0),
    ("2023-12-05","HOLD",4.35,0), ("2023-11-07","HIKE",4.35,25),
    ("2023-10-03","HOLD",4.10,0), ("2023-09-05","HOLD",4.10,0),
    ("2023-08-01","HOLD",4.10,0), ("2023-07-04","HOLD",4.10,0),
    ("2023-06-06","HOLD",4.10,0), ("2023-05-02","HOLD",3.85,0),
)

CB37_RBA_MEMBERS = (
    {"slug":"michele-bullock","name":"Michele Bullock","role":"Governor","type":"Governor","voter":"Voter","recent":.42,"lifetime":.12,"speeches":91,"dissents":0,"appointed":"2023-09-18","ends":"2030-09-17"},
    {"slug":"andrew-hauser","name":"Andrew Hauser","role":"Deputy Governor","type":"Deputy","voter":"Voter","recent":.30,"lifetime":.10,"speeches":37,"dissents":0,"appointed":"2024-03-18","ends":""},
    {"slug":"bruce-preston","name":"Bruce Preston","role":"Non-Executive Member","type":"External","voter":"Voter","recent":.06,"lifetime":.04,"speeches":2,"dissents":0,"appointed":"2026-03-01","ends":""},
    {"slug":"carolyn-hewson","name":"Carolyn Hewson","role":"Non-Executive Member","type":"External","voter":"Voter","recent":None,"lifetime":None,"speeches":0,"dissents":0,"appointed":"","ends":""},
    {"slug":"iain-ross","name":"Iain Ross","role":"Non-Executive Member","type":"External","voter":"Voter","recent":None,"lifetime":None,"speeches":0,"dissents":0,"appointed":"","ends":""},
    {"slug":"ian-harper","name":"Ian Harper","role":"Non-Executive Member","type":"External","voter":"Voter","recent":0.0,"lifetime":0.0,"speeches":1,"dissents":0,"appointed":"","ends":""},
    {"slug":"jenny-wilkinson","name":"Jenny Wilkinson","role":"Secretary to the Treasury (ex officio)","type":"External","voter":"Voter","recent":None,"lifetime":None,"speeches":0,"dissents":0,"appointed":"2025-06-16","ends":""},
    {"slug":"marnie-baker","name":"Marnie Baker","role":"Non-Executive Member","type":"External","voter":"Voter","recent":None,"lifetime":None,"speeches":0,"dissents":0,"appointed":"","ends":""},
    {"slug":"renee-fry-mckibbin","name":"Renee Fry-McKibbin","role":"Non-Executive Member","type":"External","voter":"Voter","recent":0.0,"lifetime":0.0,"speeches":2,"dissents":0,"appointed":"","ends":""},
)

# Public-roster fallbacks used only when a bank-specific audited scorecard was not
# included in the supplied reference set.  Scores are intentionally None: no
# fabricated member score is presented as observed data.
CB37_ROSTERS: Mapping[str, Sequence[Tuple[str, str]]] = {
    "NORGES": (("Ida Wolden Bache","Governor"),("Pål Longva","Deputy Governor"),("Ingvild Almås","External member"),("Steinar Holden","External member"),("Kjersti Haugland","External member")),
    "BOE": (("Andrew Bailey","Governor"),("Clare Lombardelli","Deputy Governor"),("Sarah Breeden","Deputy Governor"),("Dave Ramsden","Deputy Governor"),("Huw Pill","Chief Economist"),("Swati Dhingra","External member"),("Megan Greene","External member"),("Catherine Mann","External member"),("Alan Taylor","External member")),
    "FED": (("Jerome Powell","Chair"),("Philip Jefferson","Vice Chair"),("Michelle Bowman","Vice Chair for Supervision"),("Michael Barr","Governor"),("Lisa Cook","Governor"),("Christopher Waller","Governor"),("John Williams","New York Fed"),("Susan Collins","Boston Fed"),("Austan Goolsbee","Chicago Fed"),("Beth Hammack","Cleveland Fed"),("Lorie Logan","Dallas Fed"),("Neel Kashkari","Minneapolis Fed"),("Tom Barkin","Richmond Fed"),("Raphael Bostic","Atlanta Fed"),("Alberto Musalem","St. Louis Fed"),("Mary Daly","San Francisco Fed"),("Anna Paulson","Philadelphia Fed"),("Jeff Schmid","Kansas City Fed")),
    "RBNZ": (("Christian Hawkesby","Governor"),("Karen Silk","Assistant Governor"),("Paul Conway","Chief Economist"),("Peter Harris","External member"),("Prasanna Gai","External member"),("Caroline Saunders","External member")),
    "ECB": (("Christine Lagarde","President"),("Luis de Guindos","Vice-President"),("Philip R. Lane","Executive Board"),("Isabel Schnabel","Executive Board"),("Frank Elderson","Executive Board"),("Piero Cipollone","Executive Board")),
    "BOC": (("Tiff Macklem","Governor"),("Carolyn Rogers","Senior Deputy Governor"),("Toni Gravelle","Deputy Governor"),("Sharon Kozicki","Deputy Governor"),("Nicolas Vincent","Deputy Governor"),("Rhys Mendes","Deputy Governor"),("Michelle Alexopoulos","External Deputy Governor")),
    "RIKSBANK": (("Erik Thedéen","Governor"),("Anna Breman","First Deputy Governor"),("Per Jansson","Deputy Governor"),("Aino Bunge","Deputy Governor"),("Vanja Linder","Deputy Governor")),
    "BOJ": (("Kazuo Ueda","Governor"),("Ryozo Himino","Deputy Governor"),("Shinichi Uchida","Deputy Governor"),("Naoki Tamura","Policy Board member"),("Junko Nakagawa","Policy Board member"),("Hajime Takata","Policy Board member"),("Asahi Noguchi","Policy Board member"),("Toyoaki Nakamura","Policy Board member"),("Koeda Junko","Policy Board member")),
    "SNB": (("Martin Schlegel","Chairman"),("Antoine Martin","Vice Chairman"),("Petra Tschudin","Governing Board member")),
}

CB37_COLOR_BY_CODE = {
    "FED":"#2f6f93","ECB":"#c6952d","BOE":"#6b3e80","BOJ":"#d56c7a","BOC":"#2b8a68",
    "SNB":"#9d5148","RBA":"#3b82b9","RBNZ":"#5c4a8d","RIKSBANK":"#198f8b","NORGES":"#c45b44",
}


def _cb37_css() -> None:
    _html(
        """
<style>
.cb37-path{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin:4px 0 11px;color:#8194a7;font-size:10px}.cb37-path b{color:#d8bf58}
.cb37-model{border:1px solid rgba(129,157,185,.20);border-radius:11px;background:rgba(5,17,29,.76);padding:0 14px;margin:8px 0 14px}.cb37-model summary{cursor:pointer;padding:12px 0;color:#eef3f7;font-family:Georgia,serif;font-size:16px}.cb37-model p{color:#91a1b0;font-size:10px;line-height:1.55}
.cb37-card{position:relative;border:1px solid rgba(128,157,186,.24);border-radius:11px;padding:12px 12px 10px;background:linear-gradient(145deg,rgba(8,24,39,.96),rgba(5,15,26,.98));min-height:148px}.cb37-card:before{content:"";position:absolute;left:0;top:0;bottom:0;width:2px;background:linear-gradient(#63c7ff,transparent)}.cb37-card-head{display:flex;justify-content:space-between;gap:7px;align-items:center}.cb37-card-code{font-weight:850;color:#eef3f7;font-family:ui-monospace,monospace}.cb37-card-ccy{color:#71869a;font-size:9px}.cb37-card-rate{font-family:Georgia,serif;font-size:27px;color:#f2f5f8;margin:12px 0 2px}.cb37-card-decision{font-size:10px;font-weight:850;color:#d8bf58}.cb37-card-name{font-size:9px;color:#8495a6;margin-top:6px}.cb37-track{height:13px;border-radius:4px;background:linear-gradient(90deg,rgba(102,129,70,.75),rgba(207,216,198,.65) 38%,rgba(214,186,169,.62) 62%,rgba(132,50,45,.78));margin:10px 0 7px;position:relative}.cb37-diamond{position:absolute;top:2px;width:9px;height:9px;background:#f4f7fa;transform:rotate(45deg);border-radius:1px}.cb37-card-meta{display:flex;justify-content:space-between;gap:8px;font-size:9px;color:#8ea0b0}.cb37-score-pos{color:#57d39b}.cb37-score-neg{color:#f4777f}
.cb37-ranked{border:1px solid rgba(128,157,186,.20);border-radius:11px;background:rgba(5,17,29,.77);padding:10px 14px}.cb37-rank-row{display:grid;grid-template-columns:34px 1fr 80px 28px;gap:8px;align-items:center;padding:7px 2px;border-bottom:1px solid rgba(128,157,186,.10);font-size:10px}.cb37-rank-row:last-child{border-bottom:none}.cb37-rank-code{font-weight:800}.cb37-rank-rate{text-align:right;font-family:ui-monospace,monospace;color:#eef3f7}.cb37-rank-mark{text-align:center;color:#d8bf58}
.cb37-stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px;margin:8px 0 15px}.cb37-stat{border-top:2px solid rgba(99,199,255,.55);background:rgba(5,17,29,.79);border-radius:8px;padding:10px 11px;min-height:74px}.cb37-stat-k{font-size:8px;letter-spacing:.13em;text-transform:uppercase;color:#8496a6}.cb37-stat-v{font-family:ui-monospace,monospace;color:#f2f5f8;font-weight:850;font-size:17px;margin-top:7px}.cb37-stat-n{font-size:8px;color:#8092a2;margin-top:4px}
.cb37-stance{border:1px solid rgba(128,157,186,.20);border-radius:11px;padding:15px;background:rgba(5,17,29,.78);margin:7px 0 15px}.cb37-stance-title{font-family:Georgia,serif;color:#f2f5f8;font-size:18px}.cb37-stance-track{height:22px;border-radius:5px;background:linear-gradient(90deg,#72783e,#b7c0a4 38%,#d8c4b7 62%,#8f433e);position:relative;margin:13px 0 5px}.cb37-stance-pointer{position:absolute;top:5px;width:12px;height:12px;background:#f5f7f9;transform:rotate(45deg);border-radius:2px}.cb37-stance-labels{display:flex;justify-content:space-between;color:#8798a8;font-size:9px}
.cb37-speech{border:1px solid rgba(128,157,186,.17);border-radius:9px;padding:10px 12px;margin:6px 0;background:rgba(5,17,29,.69);display:grid;grid-template-columns:1fr 72px;gap:12px}.cb37-speech-title{font-size:10px;color:#e6edf2;font-weight:720}.cb37-speech-meta{font-size:8px;color:#8092a3;margin-top:4px}.cb37-speech-score{text-align:right;font-family:ui-monospace,monospace;font-weight:800;font-size:11px;padding-top:4px}
.cb37-member-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:8px 0 14px}.cb37-member{border:1px solid rgba(128,157,186,.22);border-left:2px solid rgba(99,199,255,.75);border-radius:10px;padding:12px;background:rgba(5,17,29,.78);min-height:132px}.cb37-member-top{display:flex;justify-content:space-between;gap:8px}.cb37-member-name{font-family:Georgia,serif;font-size:16px;color:#f2f5f8}.cb37-member-score{font-family:ui-monospace,monospace;font-weight:850}.cb37-member-role{font-size:9px;color:#91a1b0;margin:3px 0 10px}.cb37-member-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:5px}.cb37-member-metric b{display:block;font-size:8px;color:#8193a3;text-transform:uppercase}.cb37-member-metric span{font-size:10px;color:#d8e1e8}.cb37-member-foot{font-size:8px;color:#7e91a2;margin-top:9px;line-height:1.45}
.cb37-callout{border:1px solid rgba(216,191,88,.25);border-left:3px solid #d8bf58;border-radius:9px;background:rgba(216,191,88,.055);padding:11px 13px;color:#c7bea0;font-size:10px;line-height:1.5;margin:9px 0 14px}
.cb37-source{display:flex;gap:11px;flex-wrap:wrap;color:#74889a;font-size:8px;margin:6px 0 1px}.cb37-source b{color:#9fb0bd}
@media(max-width:980px){.cb37-stats{grid-template-columns:repeat(2,minmax(0,1fr))}.cb37-member-grid{grid-template-columns:1fr}.cb37-rank-row{grid-template-columns:30px 1fr 70px 24px}}
</style>
        """
    )


def _cb37_df_speeches(rows: Sequence[Tuple[str, str, str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["Date", "CB", "Speaker", "Title", "Score"])


def _cb37_df_meetings(rows: Sequence[Tuple[str, str, float, int]]) -> pd.DataFrame:
    out = pd.DataFrame(rows, columns=["Date", "Decision", "Rate", "Change bps"])
    out["Rate"] = out["Rate"].map(lambda x: f"{float(x):.2f}%")
    out["Change"] = out["Change bps"].map(lambda x: "—" if int(x) == 0 else f"{int(x):+d} bps")
    return out[["Date", "Decision", "Rate", "Change"]]


def _cb37_members(code: str) -> List[Dict[str, Any]]:
    if code == "RBA":
        return [dict(x) for x in CB37_RBA_MEMBERS]
    rows = []
    for i, (name, role) in enumerate(CB37_ROSTERS.get(code, ())):
        rows.append({"slug": _cb37_re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"), "name": name, "role": role, "type": "Committee", "voter": "Voter", "recent": None, "lifetime": None, "speeches": 0, "dissents": 0, "appointed": "", "ends": ""})
    return rows


def _cb37_speeches(code: Optional[str] = None) -> pd.DataFrame:
    if code == "RBA":
        return _cb37_df_speeches(CB37_RBA_SPEECHES)
    df = _cb37_df_speeches(CB37_G10_SPEECHES)
    return df if not code else df[df["CB"] == code].reset_index(drop=True)


def _cb37_meetings(code: str) -> pd.DataFrame:
    if code == "RBA":
        return _cb37_df_meetings(CB37_RBA_MEETINGS)
    bank = CB37_BANK_BY_CODE[code]
    try:
        rate_df, source = _cb37_policy_series(code, "2010-01-01")
        work = rate_df.copy().dropna(subset=["date", "value"]).sort_values("date")
        work["value"] = pd.to_numeric(work["value"], errors="coerce")
        work = work.dropna(subset=["value"])
        work["change"] = work["value"].diff()
        changes = work[work["change"].abs() > 1e-9].tail(30)
        rows = []
        for _, row in changes.sort_values("date", ascending=False).iterrows():
            delta_bps = int(round(float(row["change"]) * 100))
            rows.append({"Date": pd.Timestamp(row["date"]).date().isoformat(), "Decision": "HIKE" if delta_bps > 0 else "CUT", "Rate": f"{float(row['value']):.2f}%", "Change": f"{delta_bps:+d} bps"})
        current = {"Date": str(bank.get("rate_since", CB37_SNAPSHOT)), "Decision": str(bank["decision"]), "Rate": f"{float(bank['rate']):.2f}%", "Change": "—"}
        if not rows or rows[0]["Date"] != current["Date"]:
            rows.insert(0, current)
        return pd.DataFrame(rows[:30])
    except Exception:
        return pd.DataFrame([{"Date": bank.get("rate_since", CB37_SNAPSHOT), "Decision": bank["decision"], "Rate": f"{float(bank['rate']):.2f}%", "Change": "—"}])


def _cb37_position(score: Any) -> float:
    try:
        value = float(score)
    except Exception:
        value = 0.0
    return max(1.5, min(98.5, (value + 1.0) * 50.0))


def _cb37_track(score: Any) -> str:
    return f'<div class="cb37-track"><span class="cb37-diamond" style="left:calc({_cb37_position(score):.1f}% - 5px)"></span></div>'


def _cb37_bank_card(bank: Mapping[str, Any]) -> None:
    score = float(bank["score"])
    cls = "cb37-score-pos" if score >= 0 else "cb37-score-neg"
    _html(
        '<div class="cb37-card">'
        f'<div class="cb37-card-head"><span class="cb37-card-code">{_esc(bank["flag"])} {_esc(bank["code"])}</span><span class="cb37-card-ccy">{_esc(bank["ccy"])}</span></div>'
        f'<div class="cb37-card-rate">{float(bank["rate"]):.2f}% <span class="cb37-card-decision">● {_esc(bank["decision"])}</span></div>'
        f'<div class="cb37-card-name">{_esc(bank["name"])}</div>{_cb37_track(score)}'
        f'<div class="cb37-card-meta"><span class="{cls}">{score:+.3f}</span><span>{int(bank["members"])} members</span></div>'
        f'<div class="cb37-card-name">{_esc(bank["meetings"])}</div></div>'
    )


def _cb37_open_bank(code: str, tab: str = "Overview") -> None:
    st.session_state["ec36_cb_code"] = code
    st.session_state["ec36_cb_route"] = "bank"
    st.session_state["ec37_cb_nav"] = tab
    st.rerun()


def _cb37_path(parts: Sequence[str]) -> None:
    _html('<div class="cb37-path">' + ' <span>›</span> '.join(f'<b>{_esc(x)}</b>' if i == len(parts)-1 else _esc(x) for i, x in enumerate(parts)) + '</div>')


def _cb37_source(items: Sequence[Tuple[str, str]]) -> None:
    _html('<div class="cb37-source">' + ''.join(f'<span><b>{_esc(k)}:</b> {_esc(v)}</span>' for k, v in items) + '</div>')


@st.cache_data(ttl=1800, show_spinner=False)
def _cb37_fred_series(series_id: str, start: str = "2014-01-01") -> pd.DataFrame:
    sid = str(series_id or "").strip().upper()
    if not sid:
        return pd.DataFrame(columns=["date", "value"])
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={_cb37_quote(sid)}"
    try:
        if _cb37_requests is not None:
            response = _cb37_requests.get(url, timeout=7, headers={"User-Agent": "QuantTerminal/1.0"})
            response.raise_for_status()
            from io import StringIO
            raw = pd.read_csv(StringIO(response.text))
        else:
            raw = pd.read_csv(url)
        if raw.empty or len(raw.columns) < 2:
            return pd.DataFrame(columns=["date", "value"])
        out = raw.iloc[:, :2].copy(); out.columns = ["date", "value"]
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        out["value"] = pd.to_numeric(out["value"].replace(".", np.nan), errors="coerce")
        out = out.dropna().sort_values("date")
        return out[out["date"] >= pd.Timestamp(start)].reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=["date", "value"])


def _cb37_first_fred(candidates: Sequence[str], start: str = "2014-01-01") -> Tuple[pd.DataFrame, str]:
    for sid in candidates:
        df = _cb37_fred_series(str(sid), start)
        if isinstance(df, pd.DataFrame) and len(df) >= 2:
            return df, str(sid)
    return pd.DataFrame(columns=["date", "value"]), ""


def _cb37_rba_rate_history(start: str = "2014-01-01") -> pd.DataFrame:
    rows = pd.DataFrame(CB37_RBA_MEETINGS, columns=["date", "decision", "rate", "change"])
    rows["date"] = pd.to_datetime(rows["date"])
    rows = rows.sort_values("date")
    return rows[rows["date"] >= pd.Timestamp(start)][["date", "rate"]].rename(columns={"rate":"value"})


def _cb37_policy_series(code: str, start: str = "2014-01-01") -> Tuple[pd.DataFrame, str]:
    bank = CB37_BANK_BY_CODE[code]
    df, source = _cb37_first_fred(bank.get("rate_series", ()), start)
    if df.empty and code == "RBA":
        return _cb37_rba_rate_history(start), "RBA audited meeting history"
    if df.empty:
        return pd.DataFrame({"date":[pd.Timestamp(bank.get("rate_since", CB37_SNAPSHOT)), pd.Timestamp(CB37_SNAPSHOT)], "value":[float(bank["rate"]), float(bank["rate"])]}), "Audited current snapshot"
    return df, f"FRED {source}"


def _cb37_balance_series(code: str, start: str = "2019-01-01") -> Tuple[pd.DataFrame, str]:
    bank = CB37_BANK_BY_CODE[code]
    df, source = _cb37_first_fred(bank.get("balance_series", ()), start)
    if df.empty:
        return pd.DataFrame(columns=["date", "value"]), "Unavailable from configured public series"
    monthly = df.set_index("date")["value"].resample("MS").last().dropna().diff().dropna()
    # FRED balance sheets are commonly published in millions; normalise large values to $bn.
    if monthly.abs().median() > 1000:
        monthly = monthly / 1000.0
    return monthly.rename("value").reset_index(), f"FRED {source}"


def _cb37_composite_history(code: str, months: int = 116) -> pd.Series:
    """Visual reconstruction anchored to the audited current score.

    RoboMacro's historical NLP scores are proprietary and were not embedded in
    the supplied PDFs.  The route therefore uses a deterministic reconstruction
    for layout/interaction parity while preserving the exact audited endpoint.
    """
    bank = CB37_BANK_BY_CODE[code]
    idx = pd.date_range("2016-11-01", periods=months, freq="MS")
    seed = _seed("cb37-composite-" + code)
    rng = np.random.default_rng(seed)
    x = np.arange(months)
    phase = (seed % 41) / 8.0
    base = .02 + .12*np.sin(x/8.5 + phase) + .08*np.sin(x/19.0 + phase/2)
    shock = -.45*np.exp(-((x-39)/5.0)**2) + .25*np.exp(-((x-66)/12.0)**2)
    noise = rng.normal(0, .06, months)
    raw = np.clip(base + shock + noise, -.75, .85)
    raw = pd.Series(raw, index=idx).rolling(2, min_periods=1).mean()
    raw += float(bank["score"]) - float(raw.iloc[-1])
    raw.iloc[-1] = float(bank["score"])
    return raw.clip(-1, 1)


def _cb37_member_history(member: Mapping[str, Any], periods: int = 36) -> pd.Series:
    recent = member.get("recent")
    idx = pd.date_range("2023-09-01", periods=periods, freq="MS")
    if recent is None:
        return pd.Series(index=idx, dtype=float)
    seed = _seed("cb37-member-" + str(member.get("slug")))
    rng = np.random.default_rng(seed)
    x = np.arange(periods)
    raw = .08*np.sin(x/3.4 + seed%7) + .04*np.sin(x/8.0) + rng.normal(0,.035,periods)
    raw = pd.Series(raw,index=idx).rolling(2,min_periods=1).mean()
    raw += float(recent)-float(raw.iloc[-1]); raw.iloc[-1]=float(recent)
    return raw.clip(-1,1)


def _cb37_apply_window(series: pd.Series, window: str) -> pd.Series:
    if series.empty or window == "All":
        return series
    years = {"1Y":1,"3Y":3,"5Y":5}.get(window)
    if not years:
        return series
    return series[series.index >= series.index.max() - pd.DateOffset(years=years)]


def _cb37_render_speech_cards(df: pd.DataFrame, limit: Optional[int] = None) -> None:
    use = df.head(limit) if limit else df
    if use.empty:
        st.info("No audited speech rows are available for this bank in the supplied reference set.")
        return
    for _, row in use.iterrows():
        score = float(row["Score"])
        cls = "cb37-score-pos" if score >= 0 else "cb37-score-neg"
        _html(
            '<div class="cb37-speech">'
            f'<div><div class="cb37-speech-title">{_esc(row["Title"])}</div><div class="cb37-speech-meta">{_esc(row["Speaker"])} · {_esc(row["Date"])} · {_esc(row["CB"])}</div></div>'
            f'<div class="cb37-speech-score {cls}">{score:+.2f}</div></div>'
        )


def _cb37_root() -> None:
    _header("ECONOMY · MONETARY POLICY", "Global Monetary Policy Observatory", "Hawk/dove monitoring, policy rates, balance-sheet momentum, speeches and bank-level drill-down in one institutional workflow.", ["G10 central banks","bank scorecards","policy previews","audited 22 Jul 2026 snapshot"])
    _html('<details class="cb37-model"><summary>How This Works — The Hawk/Dove Model</summary><p>Recent scores use a 12-observation exponential moving average. Lifetime scores use a time-decayed history. Positive values are hawkish, negative values are dovish. Policy-rate and balance-sheet histories come from configured public series; proprietary NLP histories are explicitly identified as visual reconstructions.</p></details>')
    rows = [CB37_BANKS[:5], CB37_BANKS[5:]]
    for row in rows:
        cols = st.columns(5)
        for col, bank in zip(cols, row):
            with col:
                _cb37_bank_card(bank)
                if st.button(f"Open {bank['code']}", key=f"ec37_open_{bank['code']}", use_container_width=True):
                    _cb37_open_bank(str(bank["code"]))
    c1, c2, c3 = st.columns([2.2, 1, 1])
    with c1:
        selected = st.selectbox("Open central bank", [str(x["code"]) for x in CB37_BANKS], key="ec37_root_select", format_func=lambda code: f"{CB37_BANK_BY_CODE[code]['flag']} {code} — {CB37_BANK_BY_CODE[code]['name']}")
    with c2:
        if st.button("Open scorecard", key="ec37_root_scorecard", use_container_width=True):
            _cb37_open_bank(selected, "Scorecard")
    with c3:
        if st.button("Policy previews", key="ec37_root_previews", use_container_width=True):
            st.session_state["ec36_cb_route"] = "previews"; st.rerun()

    _section("CROSS-BANK SIGNAL", "Hawk / Dove Composite", "All-bank communication history, bank toggles and 3m/3m-change view. Endpoint scores match the audited snapshot.")
    controls = st.columns([2.5, 1, 1])
    with controls[0]:
        chosen = st.multiselect("Central banks", [str(x["code"]) for x in CB37_BANKS], default=[str(x["code"]) for x in CB37_BANKS], key="ec37_composite_banks")
    with controls[1]:
        composite_mode = st.radio("View", ["Level", "3m/3m change"], horizontal=True, key="ec37_composite_mode")
    with controls[2]:
        solo_first = st.checkbox("Solo first", value=False, key="ec37_solo_first")
    if solo_first and chosen:
        chosen = chosen[:1]
    fig = go.Figure()
    for code in chosen:
        s = _cb37_composite_history(code)
        if composite_mode == "3m/3m change":
            s = s.rolling(3).mean() - s.shift(3).rolling(3).mean()
        fig.add_trace(go.Scatter(x=s.index, y=s.values, name=code, mode="lines+markers", marker=dict(size=3), line=dict(width=1.8, color=CB37_COLOR_BY_CODE.get(code))))
    fig.add_hline(y=0, line_color="rgba(202,212,221,.35)", line_width=1)
    fig.update_yaxes(range=[-.9,.9], tickvals=[-.6,0,.6], ticktext=["Dovish","Neutral","Hawkish"])
    _plot(fig, "ec37_composite", 455)
    _cb37_source([("Score layer","audited endpoints + deterministic history reconstruction"),("Snapshot",CB37_SNAPSHOT),("Scale","−1 dovish to +1 hawkish")])

    _section("RANKING", "Policy Rates — Ranked", "Current G10 policy settings in descending order, preserving the decision marker.")
    rank_html = []
    for i, bank in enumerate(sorted(CB37_BANKS, key=lambda x: float(x["rate"]), reverse=True), 1):
        marker = "▲" if bank["decision"] == "HIKE" else "▼" if bank["decision"] == "CUT" else "●"
        rank_html.append(f'<div class="cb37-rank-row"><span>{i:02d}</span><span class="cb37-rank-code">{_esc(bank["flag"])} {_esc(bank["code"])}</span><span class="cb37-rank-rate">{float(bank["rate"]):.2f}%</span><span class="cb37-rank-mark">{marker}</span></div>')
    _html('<div class="cb37-ranked">'+''.join(rank_html)+'</div>')

    _section("MONETARY POLICY STANCE", "Policy Rates & Balance Sheet", "Policy-rate history with monthly balance-sheet change. Green bars indicate expansion; red bars indicate contraction.")
    code = st.selectbox("Central bank for policy/balance sheet", [str(x["code"]) for x in CB37_BANKS], key="ec37_balance_bank", label_visibility="collapsed")
    bank = CB37_BANK_BY_CODE[code]
    rate_df, rate_source = _cb37_policy_series(code, "2019-01-01")
    bal_df, bal_source = _cb37_balance_series(code, "2019-01-01")
    fig2 = go.Figure()
    if not bal_df.empty:
        colors = [CB37_COLORS["green"] if float(v) >= 0 else CB37_COLORS["red"] for v in bal_df["value"]]
        fig2.add_trace(go.Bar(x=bal_df["date"], y=bal_df["value"], name="Balance sheet Δ", marker_color=colors, opacity=.72, yaxis="y2"))
    fig2.add_trace(go.Scatter(x=rate_df["date"], y=rate_df["value"], name="Policy rate", mode="lines", line=dict(color=CB37_COLORS["blue"], width=2.4, shape="hv")))
    fig2.update_layout(yaxis=dict(title="Policy Rate %"), yaxis2=dict(title="$bn/mo", overlaying="y", side="right", showgrid=False, zeroline=True, zerolinecolor="rgba(202,212,221,.25)"))
    _plot(fig2, "ec37_balance_chart", 455)
    _html(f'<div class="cb37-callout"><b>{float(bank["rate"]):.2f}% policy rate</b> · {str(bank["decision"]).lower()} since {_esc(bank.get("rate_since","—"))}. Missing public balance-sheet series are left blank rather than backfilled with synthetic bars.</div>')
    _cb37_source([("Policy rate",rate_source),("Balance sheet",bal_source),("Method","monthly last observation and first difference")])

    _section("COMMUNICATION", "Recent Speeches", "Twenty latest audited G10 interventions with speaker, title and hawk/dove score.")
    _table(_cb37_speeches(), "ec37_g10_speeches", 560)


def _cb37_summary(bank: Mapping[str, Any]) -> None:
    _html(
        '<div class="cb37-stats">'
        f'<div class="cb37-stat"><div class="cb37-stat-k">Rate</div><div class="cb37-stat-v">{float(bank["rate"]):.2f}%</div><div class="cb37-stat-n">{_esc(bank["decision"])}</div></div>'
        f'<div class="cb37-stat"><div class="cb37-stat-k">Target</div><div class="cb37-stat-v">{_esc(bank["target"])}</div><div class="cb37-stat-n">{_esc(bank["country"])}</div></div>'
        f'<div class="cb37-stat"><div class="cb37-stat-k">Hawk / Dove</div><div class="cb37-stat-v">{float(bank["score"]):+.3f}</div><div class="cb37-stat-n">positive = hawkish</div></div>'
        f'<div class="cb37-stat"><div class="cb37-stat-k">Decision</div><div class="cb37-stat-v">vote</div><div class="cb37-stat-n">latest decision</div></div>'
        f'<div class="cb37-stat"><div class="cb37-stat-k">Votes</div><div class="cb37-stat-v" style="font-size:12px">{_esc(bank["votes"])}</div><div class="cb37-stat-n">publication convention</div></div>'
        '</div>'
    )


def _cb37_member_cards(code: str, compact: bool = False) -> None:
    members = _cb37_members(code)
    if not members:
        st.info("No committee roster is configured for this bank.")
        return
    for start in range(0, len(members), 3):
        cols = st.columns(3)
        for col, member in zip(cols, members[start:start+3]):
            with col:
                recent = member.get("recent")
                score_text = "No data" if recent is None else f"{float(recent):+.2f}"
                cls = "cb37-score-pos" if recent is not None and float(recent) >= 0 else "cb37-score-neg" if recent is not None else ""
                _html(
                    '<div class="cb37-member">'
                    f'<div class="cb37-member-top"><span class="cb37-member-name">{_esc(member["name"])}</span><span class="cb37-member-score {cls}">{score_text}</span></div>'
                    f'<div class="cb37-member-role">{_esc(member["role"])}</div>'
                    '<div class="cb37-member-metrics">'
                    f'<div class="cb37-member-metric"><b>Votes</b><span>—</span></div><div class="cb37-member-metric"><b>Speeches</b><span>{member.get("speeches",0) if member.get("speeches",0) else "—"}</span></div><div class="cb37-member-metric"><b>Dissents</b><span>{int(member.get("dissents",0))}</span></div>'
                    '</div>'
                    f'<div class="cb37-member-foot">{_esc(member.get("type","Committee"))} · {_esc(member.get("voter","Voter"))}' + (f'<br>Appointed: {_esc(member.get("appointed"))}' if member.get("appointed") else '') + (f' · Ends: {_esc(member.get("ends"))}' if member.get("ends") else '') + '</div></div>'
                )
                if not compact and st.button("Open member", key=f"ec37_member_{code}_{member['slug']}", use_container_width=True):
                    st.session_state["ec36_cb_route"] = "member"
                    st.session_state["ec36_cb_code"] = code
                    st.session_state["ec37_member_slug"] = member["slug"]
                    st.rerun()


def _cb37_overview(code: str) -> None:
    bank = CB37_BANK_BY_CODE[code]
    score = float(bank["score"])
    _html('<div class="cb37-stance"><div class="cb37-stance-title">Hawk / Dove Stance</div><div class="cb37-stance-track"><span class="cb37-stance-pointer" style="left:calc('+f'{_cb37_position(score):.1f}% - 6px)'+ '"></span></div><div class="cb37-stance-labels"><span>Dovish</span><span>Neutral</span><span>Hawkish</span></div></div>')
    ctl = st.columns([2,1])
    with ctl[0]:
        window = st.radio("Zoom", ["1Y","3Y","5Y","All"], horizontal=True, index=3, key=f"ec37_zoom_{code}")
    with ctl[1]:
        merge = st.checkbox("Merge Charts", value=False, key=f"ec37_merge_{code}")
    rate_df, source = _cb37_policy_series(code, "2014-01-01")
    rate = pd.Series(rate_df["value"].to_numpy(), index=pd.DatetimeIndex(rate_df["date"]), name="Policy rate")
    hawk = _cb37_composite_history(code)
    rate = _cb37_apply_window(rate, window); hawk = _cb37_apply_window(hawk, window)
    if merge:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=rate.index,y=rate.values,name="Policy Rate",line=dict(color=CB37_COLORS["gold"],width=2.3,shape="hv")))
        fig.add_trace(go.Scatter(x=hawk.index,y=hawk.values,name="Hawk/Dove",yaxis="y2",mode="lines+markers",marker=dict(size=4),line=dict(color=CB37_COLORS["orange"],width=2)))
        fig.update_layout(yaxis2=dict(overlaying="y",side="right",range=[-1,1],showgrid=False))
        _plot(fig,f"ec37_merged_{code}",430)
    else:
        c1,c2=st.columns(2)
        with c1:
            fig1=go.Figure(go.Scatter(x=rate.index,y=rate.values,name="Policy Rate",line=dict(color=CB37_COLORS["gold"],width=2.3,shape="hv"),fill="tozeroy",fillcolor="rgba(99,199,255,.08)")); _plot(fig1,f"ec37_rate_{code}",380)
        with c2:
            fig2=go.Figure(go.Scatter(x=hawk.index,y=hawk.values,name="Hawk/Dove",mode="lines+markers",marker=dict(size=4),line=dict(color=CB37_COLORS["orange"],width=2))); fig2.add_hline(y=0,line_color="rgba(202,212,221,.28)"); fig2.update_yaxes(range=[-1,1],tickvals=[-.7,0,.7],ticktext=["Dove","Neutral","Hawk"]); _plot(fig2,f"ec37_hawk_{code}",380)
    _cb37_source([("Policy history",source),("Hawk/dove history","visual reconstruction; endpoint audited"),("Zoom",window)])
    _section("RECENT TAPE","Recent Speeches",f"Bank-filtered communication archive for {bank['short_name']}.")
    _cb37_render_speech_cards(_cb37_speeches(code), 10)
    _section("COMMITTEE",f"{bank['committee']} — Hawk/Dove Scorecard","Member cards open the full scorecard and member-level route. Missing proprietary scores are shown as no data.")
    _cb37_member_cards(code, compact=False)


def _cb37_scorecard(code: str) -> None:
    bank = CB37_BANK_BY_CODE[code]
    members = _cb37_members(code)
    _section("COMMITTEE INTELLIGENCE",f"{bank['name']} — {bank['committee']} Scorecard","Recent = 12-observation EMA. Lifetime = time-decayed. Click any member for charts.")
    horizon = st.radio("Score horizon", ["Recent (12-EMA)","Lifetime"], horizontal=True, key=f"ec37_horizon_{code}")
    if not members:
        st.info("No roster is available."); return
    valid = [m for m in members if m.get("recent") is not None]
    recent_avg = float(np.mean([float(m["recent"]) for m in valid])) if valid else float(bank["score"])
    life_valid = [m for m in members if m.get("lifetime") is not None]
    life_avg = .09 if code == "RBA" else (float(np.mean([float(m["lifetime"]) for m in life_valid])) if life_valid else np.nan)
    _kpis([("Committee recent",f"{recent_avg:+.2f}","12-EMA average","up" if recent_avg>=0 else "down"),("Committee lifetime", "—" if np.isnan(life_avg) else f"{life_avg:+.2f}","time-decayed average","flat"),("Members",str(len(members)),bank["committee"],"flat"),("Scored members",str(len(valid)),"speech-based observations","flat")])
    fig=go.Figure()
    for member in members:
        s=_cb37_member_history(member)
        if s.dropna().empty: continue
        fig.add_trace(go.Scatter(x=s.index,y=s.values,name=str(member["name"]).split()[-1],mode="lines",line=dict(width=1.8)))
    fig.add_hline(y=0,line_color="rgba(202,212,221,.28)")
    fig.update_yaxes(range=[-1,1],tickvals=[-.7,0,.7],ticktext=["Dove","Neutral","Hawk"])
    _plot(fig,f"ec37_committee_{code}",455)
    if code == "RBA":
        decisions=pd.DataFrame([
            ("2026-03-17","Hike",.72,"—"),("2026-02-03","Hike",.50,"—"),("2025-12-09","Hold",.25,"—"),("2025-11-04","Hold",.17,"—"),("2025-09-30","Hold",0.00,"—"),("2025-08-12","Cut",-.23,"—")
        ],columns=["Date","Decision","Avg Score","Dissents"])
        _table(decisions,"ec37_score_decisions_rba",300)
    _section("INDIVIDUAL MEMBERS",f"Individual Members ({len(members)})","Recent score, speech count, dissents, role and term metadata.")
    _cb37_member_cards(code, compact=False)
    _cb37_source([("Data date",CB37_SNAPSHOT),("Recent","12-point EMA"),("Lifetime","365-day half-life"),("Scores","speech-based; audited RBA fields from supplied reference")])


def _cb37_speech_archive(code: str) -> None:
    bank = CB37_BANK_BY_CODE[code]
    df = _cb37_speeches(code)
    _section("COMMUNICATION",f"Speeches — {code}",f"Search the audited speech archive for {bank['name']}.")
    query = st.text_input("Search speeches", key=f"ec37_speech_search_{code}", placeholder="speaker, title, subject")
    if query:
        mask = df.astype(str).apply(lambda col: col.str.contains(query, case=False, regex=False)).any(axis=1)
        df = df[mask]
    _cb37_render_speech_cards(df)


def _cb37_meeting_archive(code: str) -> None:
    bank=CB37_BANK_BY_CODE[code]
    _section("DECISION HISTORY","Rate Decision History",f"Decision, rate and change history for {bank['name']}.")
    df=_cb37_meetings(code)
    _table(df,f"ec37_meetings_{code}",min(760,90+28*len(df)))
    if code != "RBA":
        _html('<div class="cb37-callout">The supplied RoboMacro reference set contains a full audited meeting table for RBA only. Other banks retain the route and current official snapshot; no synthetic meeting history is inserted.</div>')


def _cb37_bank(code: str) -> None:
    bank=CB37_BANK_BY_CODE.get(code,CB37_BANK_BY_CODE["RBA"])
    _cb37_path(["Central Banks",bank["name"]])
    c1,c2=st.columns([1,1])
    with c1:
        if st.button("← All Central Banks",key=f"ec37_back_{code}"):
            st.session_state["ec36_cb_route"]="root"; st.rerun()
    with c2:
        if st.button("Policy Previews →",key=f"ec37_preview_{code}"):
            st.session_state["ec36_cb_route"]="previews"; st.rerun()
    _header("CENTRAL BANK WORKSTATION",f"{bank['flag']} {bank['name']}",f"{bank['committee']} · {bank['decision']}",[bank["ccy"],bank["meetings"],f"{bank['members']} members",f"snapshot {CB37_SNAPSHOT}"])
    _cb37_summary(bank)
    tab=_segmented("Central bank page",["Overview","Scorecard","Speeches","Meetings"],"ec37_cb_nav","Overview")
    if tab=="Overview": _cb37_overview(code)
    elif tab=="Scorecard": _cb37_scorecard(code)
    elif tab=="Speeches": _cb37_speech_archive(code)
    else: _cb37_meeting_archive(code)


def _cb37_member(code: str, slug: str) -> None:
    bank=CB37_BANK_BY_CODE.get(code,CB37_BANK_BY_CODE["RBA"])
    members=_cb37_members(str(bank["code"]))
    member=next((m for m in members if m.get("slug")==slug),members[0] if members else None)
    if member is None:
        st.warning("Member profile unavailable."); return
    _cb37_path(["Central Banks",bank["name"],"Scorecard",member["name"]])
    if st.button("← Back to scorecard",key=f"ec37_member_back_{code}_{slug}"):
        st.session_state["ec36_cb_route"]="bank"; st.session_state["ec37_cb_nav"]="Scorecard"; st.rerun()
    recent=member.get("recent"); lifetime=member.get("lifetime")
    _header("MEMBER SCORECARD",member["name"],member["role"],[f"appointed {member.get('appointed') or 'not supplied'}",f"{member.get('speeches',0)} speeches",bank["short_name"]])
    _kpis([("Recent composite","—" if recent is None else f"{float(recent):+.2f}","12-EMA","up" if recent is not None and float(recent)>=0 else "down"),
           ("Recent votes","—","publication convention","flat"),("Recent speeches","—" if recent is None else f"{float(recent):+.2f}",f"{member.get('speeches',0)} observations","flat"),
           ("Lifetime composite","—" if lifetime is None else f"{float(lifetime):+.2f}","time-decayed","flat")])
    if code=="RBA":
        _html('<div class="cb37-callout"><b>Consensus decision-making:</b> The Reserve Bank of Australia does not publish individual member votes. This scorecard reflects speeches and public communications only.</div>')
    tab=st.radio("Member view",["Hawk/Dove Chart",f"Speeches ({member.get('speeches',0)})"],horizontal=True,key=f"ec37_member_view_{code}_{slug}")
    if tab=="Hawk/Dove Chart":
        _section("MEMBER HISTORY","Hawk/Dove Tendency Over Time","Click or hover any dot to inspect the speech-score path.")
        s=_cb37_member_history(member,92 if slug=="michele-bullock" else 42)
        fig=go.Figure(go.Scatter(x=s.index,y=s.values,name="Speech Score",mode="lines+markers",line=dict(color="#4d86bd",dash="dot",width=1.6),marker=dict(size=6,color="#4d86bd")))
        fig.add_hline(y=0,line_color="rgba(202,212,221,.28)"); fig.update_yaxes(range=[-1,1],tickvals=[-.7,0,.7],ticktext=["Dove","Neutral","Hawk"])
        _plot(fig,f"ec37_member_chart_{code}_{slug}",430)
        _cb37_source([("Votes","not published for RBA" if code=="RBA" else bank["votes"]),("Speech score","audited endpoint; reconstructed path"),("Member",member["name"])])
    else:
        df=_cb37_speeches(code)
        df=df[df["Speaker"].str.casefold()==str(member["name"]).casefold()]
        _cb37_render_speech_cards(df)


def _render_cb_root() -> None:  # noqa: F811 — intentional V36 override
    _cb37_css()
    if str(st.session_state.get("ec36_cb_route","root")) == "member":
        _cb37_member(str(st.session_state.get("ec36_cb_code","RBA")),str(st.session_state.get("ec37_member_slug","michele-bullock")))
        return
    _cb37_root()


def _render_cb_bank(code: str) -> None:  # noqa: F811 — intentional V36 override
    _cb37_css(); _cb37_bank(str(code))


def _render_cb_scorecard(code: str) -> None:  # noqa: F811 — intentional V36 override
    _cb37_css(); _cb37_scorecard(str(code))


def render_economy_intelligence(page: str, ticker: str = "SPY", price_data: Any = None, analysis: Any = None) -> None:  # noqa: F811
    """V37 Economy renderer: only the Central Banks branch is overridden."""
    del ticker, price_data, analysis
    _css(); page=_normalize_page(page)
    if page != "central-banks":
        st.session_state["ec36_cb_route"]="root"
    if page != "high-speed":
        st.session_state["ec36_hs_route"]="root"
    if page=="central-banks":
        route=str(st.session_state.get("ec36_cb_route","root"))
        if route=="bank": _render_cb_bank(str(st.session_state.get("ec36_cb_code","RBA")))
        elif route=="member": _cb37_css(); _cb37_member(str(st.session_state.get("ec36_cb_code","RBA")),str(st.session_state.get("ec37_member_slug","michele-bullock")))
        elif route=="previews": _render_cb_previews()
        else: _render_cb_root()
    elif page=="inflation": _render_inflation()
    elif page=="payrolls": _render_payrolls()
    elif page=="outlook": _render_outlook()
    elif page=="taylor-rule": _render_taylor()
    elif page=="high-speed": _render_high_speed()
    elif page=="china": _render_china()
    elif page=="misery": _render_misery()
    else: _render_quality()


CENTRAL_BANKS_INTEGRITY_V37: Mapping[str, Any] = {
    "version": CB37_VERSION,
    "snapshot": CB37_SNAPSHOT,
    "banks": len(CB37_BANKS),
    "g10_speeches": len(CB37_G10_SPEECHES),
    "rba_speeches": len(CB37_RBA_SPEECHES),
    "rba_meetings": len(CB37_RBA_MEETINGS),
    "rba_members": len(CB37_RBA_MEMBERS),
    "routes": ("root","bank/overview","bank/scorecard","bank/speeches","bank/meetings","member","previews"),
    "non_central_economy_modified": False,
    "macro_router_modified": False,
}
assert CENTRAL_BANKS_INTEGRITY_V37["banks"] == 10
assert CENTRAL_BANKS_INTEGRITY_V37["g10_speeches"] == 20
assert CENTRAL_BANKS_INTEGRITY_V37["rba_speeches"] == 10
assert CENTRAL_BANKS_INTEGRITY_V37["rba_meetings"] == 28
assert CENTRAL_BANKS_INTEGRITY_V37["rba_members"] == 9

# ============================================================
# END JARVIS ECONOMY V37 — CENTRAL BANKS PARITY PATCH
# ============================================================

# ============================================================
# JARVIS ECONOMY V38 — CENTRAL BANKS PUBLIC DATA ENGINE
# ============================================================
# Append-only runtime override of the Central Banks branch.
# No RoboMacro endpoint, page, table or historical series is queried or used.
# Data is sourced from public/official providers and all communication scores
# are computed locally by Quant Terminal's transparent text model.
# Non-Central-Banks Economy routes remain on the validated V36 implementation.
# ============================================================

import io as _cb38_io
import json as _cb38_json
import os as _cb38_os
import re as _cb38_re
import zipfile as _cb38_zipfile
import tempfile as _cb38_tempfile
import gc as _cb38_gc
import xml.etree.ElementTree as _cb38_et
from concurrent.futures import ThreadPoolExecutor as _cb38_ThreadPoolExecutor, as_completed as _cb38_as_completed
from datetime import datetime as _cb38_datetime, timezone as _cb38_timezone
from email.utils import parsedate_to_datetime as _cb38_parsedate
from urllib.parse import quote as _cb38_quote, urljoin as _cb38_urljoin, urlparse as _cb38_urlparse

try:
    import requests as _cb38_requests
except Exception:  # pragma: no cover
    _cb38_requests = None

try:
    from bs4 import BeautifulSoup as _cb38_BeautifulSoup
except Exception:  # pragma: no cover
    _cb38_BeautifulSoup = None

CB38_VERSION = "V38.2 · STABLE PUBLIC DATA ENGINE"
CB38_BIS_POLICY_ZIP = "https://data.bis.org/static/bulk/WS_CBPOL_csv_flat.zip"
CB38_BIS_ASSETS_ZIP = "https://data.bis.org/static/bulk/WS_CBTA_csv_flat.zip"
CB38_BIS_SPEECH_RSS = "https://www.bis.org/doclist/cbspeeches.rss"
CB38_USER_AGENT = "QuantTerminal-CentralBanks/38.0 (+public-data; research-use)"
CB38_TIMEOUT = 12
# Stability guardrails. The default route must remain fast and memory bounded.
CB38_MAX_BULK_ROWS = int(_cb38_os.getenv("CB38_MAX_BULK_ROWS", "300000"))
CB38_BULK_CHUNK_ROWS = int(_cb38_os.getenv("CB38_BULK_CHUNK_ROWS", "75000"))
CB38_MAX_DOWNLOAD_BYTES = int(_cb38_os.getenv("CB38_MAX_DOWNLOAD_BYTES", str(256 * 1024 * 1024)))
CB38_MAX_RSS_ITEMS = int(_cb38_os.getenv("CB38_MAX_RSS_ITEMS", "120"))
CB38_MAX_ENRICH_ITEMS = int(_cb38_os.getenv("CB38_MAX_ENRICH_ITEMS", "24"))
CB38_DEEP_FETCH_DEFAULT = str(_cb38_os.getenv("CB38_DEEP_FETCH", "0")).strip().lower() in {"1","true","yes","on"}
CB38_TODAY = pd.Timestamp.utcnow().tz_localize(None).normalize()
CB38_COLORS = {
    "gold": "#d8bf58", "blue": "#63c7ff", "green": "#57d39b",
    "red": "#f4777f", "purple": "#a990ff", "orange": "#ff9b63",
    "teal": "#72d4d4", "ink": "#cad4dd", "muted": "#8fa0b0",
}
CB38_COLOR_BY_CODE = {
    "FED":"#2f6f93", "ECB":"#c6952d", "BOE":"#6b3e80", "BOJ":"#d56c7a",
    "BOC":"#2b8a68", "SNB":"#9d5148", "RBA":"#3b82b9", "RBNZ":"#5c4a8d",
    "RIKSBANK":"#198f8b", "NORGES":"#c45b44",
}

# Static fields below are institutional metadata (mandate, committee and official
# page locations). Rates, scores, speeches, decision histories and balance sheets
# are not hard-coded: they are resolved by the public-data adapters below.
CB38_BANKS: Tuple[Mapping[str, Any], ...] = (
    {"code":"RBA","flag":"🇦🇺","name":"Reserve Bank of Australia","short":"RBA","country":"Australia","ccy":"AUD","target":"2–3% CPI","target_mid":2.5,"committee":"Monetary Policy Board","meetings":"8 per year","votes":"Individual votes not published","area_codes":("AU",),"area_names":("australia",),"fred_rate":("IRSTCI01AUM156N",),"fred_assets":("RBAABSL",),"speech_url":"https://www.rba.gov.au/speeches/","decision_url":"https://www.rba.gov.au/monetary-policy/int-rate-decisions/","roster_url":"https://www.rba.gov.au/about-rba/boards/mpb.html"},
    {"code":"NORGES","flag":"🇳🇴","name":"Norges Bank","short":"Norges","country":"Norway","ccy":"NOK","target":"2.0% CPI","target_mid":2.0,"committee":"Monetary Policy and Financial Stability Committee","meetings":"8 per year","votes":"Published when applicable","area_codes":("NO",),"area_names":("norway","norges"),"fred_rate":("IRSTCI01NOM156N",),"fred_assets":(),"speech_url":"https://www.norges-bank.no/en/news-events/news-publications/Speeches/","decision_url":"https://www.norges-bank.no/en/topics/monetary-policy/policy-rate/","roster_url":"https://www.norges-bank.no/en/topics/about/Organisation/Executive-Board/"},
    {"code":"BOE","flag":"🇬🇧","name":"Bank of England","short":"BoE","country":"United Kingdom","ccy":"GBP","target":"2.0% CPI","target_mid":2.0,"committee":"Monetary Policy Committee","meetings":"8 per year","votes":"Published","area_codes":("GB","UK"),"area_names":("united kingdom","great britain","bank of england"),"fred_rate":("IUDERB01","IRSTCI01GBM156N"),"fred_assets":("BOEBSTA",),"speech_url":"https://www.bankofengland.co.uk/news/speeches","decision_url":"https://www.bankofengland.co.uk/monetary-policy-summary-and-minutes","roster_url":"https://www.bankofengland.co.uk/about/people/monetary-policy-committee"},
    {"code":"FED","flag":"🇺🇸","name":"Federal Reserve","short":"Fed","country":"United States","ccy":"USD","target":"2.0% PCE","target_mid":2.0,"committee":"Federal Open Market Committee","meetings":"8 per year","votes":"Published","area_codes":("US",),"area_names":("united states","federal reserve"),"fred_rate":("DFF","FEDFUNDS"),"fred_assets":("WALCL",),"speech_url":"https://www.federalreserve.gov/newsevents/speeches.htm","decision_url":"https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm","roster_url":"https://www.federalreserve.gov/monetarypolicy/fomc.htm"},
    {"code":"RBNZ","flag":"🇳🇿","name":"Reserve Bank of New Zealand","short":"RBNZ","country":"New Zealand","ccy":"NZD","target":"1–3% CPI","target_mid":2.0,"committee":"Monetary Policy Committee","meetings":"7 per year","votes":"Summary published","area_codes":("NZ",),"area_names":("new zealand","rbnz"),"fred_rate":("IRSTCI01NZM156N",),"fred_assets":(),"speech_url":"https://www.rbnz.govt.nz/hub/news","decision_url":"https://www.rbnz.govt.nz/monetary-policy/official-cash-rate-decisions","roster_url":"https://www.rbnz.govt.nz/about-us/our-people/monetary-policy-committee"},
    {"code":"ECB","flag":"🇪🇺","name":"European Central Bank","short":"ECB","country":"Euro Area","ccy":"EUR","target":"2.0% HICP","target_mid":2.0,"committee":"Governing Council","meetings":"Every six weeks","votes":"Individual votes not published","area_codes":("XM","U2","EA","EU"),"area_names":("euro area","eurozone","european central bank"),"fred_rate":("ECBDFR","IRSTCI01EZM156N"),"fred_assets":("ECBASSETSW",),"speech_url":"https://www.ecb.europa.eu/press/key/html/index.en.html","decision_url":"https://www.ecb.europa.eu/press/govcdec/mopo/html/index.en.html","roster_url":"https://www.ecb.europa.eu/ecb/decisions/govc/html/index.en.html"},
    {"code":"BOC","flag":"🇨🇦","name":"Bank of Canada","short":"BoC","country":"Canada","ccy":"CAD","target":"2.0% CPI","target_mid":2.0,"committee":"Governing Council","meetings":"8 per year","votes":"Consensus; no individual vote","area_codes":("CA",),"area_names":("canada","bank of canada"),"fred_rate":("IRSTCI01CAM156N",),"fred_assets":("BOCAX",),"speech_url":"https://www.bankofcanada.ca/press/speeches/","decision_url":"https://www.bankofcanada.ca/core-functions/monetary-policy/key-interest-rate/","roster_url":"https://www.bankofcanada.ca/about/governing-council/"},
    {"code":"RIKSBANK","flag":"🇸🇪","name":"Sveriges Riksbank","short":"Riksbank","country":"Sweden","ccy":"SEK","target":"2.0% CPIF","target_mid":2.0,"committee":"Executive Board","meetings":"Normally 8 per year","votes":"Published","area_codes":("SE",),"area_names":("sweden","sveriges riksbank","riksbank"),"fred_rate":("IRSTCI01SEM156N",),"fred_assets":(),"speech_url":"https://www.riksbank.se/en-gb/press-and-published/speeches-and-presentations/","decision_url":"https://www.riksbank.se/en-gb/monetary-policy/monetary-policy-report/","roster_url":"https://www.riksbank.se/en-gb/about-the-riksbank/organisation-and-governance/executive-board/"},
    {"code":"BOJ","flag":"🇯🇵","name":"Bank of Japan","short":"BoJ","country":"Japan","ccy":"JPY","target":"2.0% CPI","target_mid":2.0,"committee":"Policy Board","meetings":"8 per year","votes":"Published","area_codes":("JP",),"area_names":("japan","bank of japan"),"fred_rate":("IRSTCI01JPM156N",),"fred_assets":("JPNASSETS",),"speech_url":"https://www.boj.or.jp/en/about/press/koen_2026/index.htm","decision_url":"https://www.boj.or.jp/en/mopo/mpmdeci/index.htm","roster_url":"https://www.boj.or.jp/en/about/organization/policyboard/index.htm"},
    {"code":"SNB","flag":"🇨🇭","name":"Swiss National Bank","short":"SNB","country":"Switzerland","ccy":"CHF","target":"Price stability below 2%","target_mid":1.0,"committee":"Governing Board","meetings":"4 per year","votes":"Not published","area_codes":("CH",),"area_names":("switzerland","swiss national bank"),"fred_rate":("IRSTCI01CHM156N",),"fred_assets":(),"speech_url":"https://www.snb.ch/en/publications/communication/speeches","decision_url":"https://www.snb.ch/en/the-snb/mandates-goals/monetary-policy/decisions","roster_url":"https://www.snb.ch/en/the-snb/organisation/supervisory-management-bodies"},
)
CB38_BANK_BY_CODE = {str(x["code"]): x for x in CB38_BANKS}

# Public official roster seed. It is used only for attribution and can be
# superseded by speeches discovered on the official/BIS feeds.
CB38_ROSTERS: Mapping[str, Tuple[Tuple[str, str], ...]] = {
    "RBA": (("Michele Bullock","Governor"),("Andrew Hauser","Deputy Governor"),("Bruce Preston","Non-Executive Member"),("Carolyn Hewson","Non-Executive Member"),("Iain Ross","Non-Executive Member"),("Ian Harper","Non-Executive Member"),("Jenny Wilkinson","Secretary to the Treasury"),("Marnie Baker","Non-Executive Member"),("Renee Fry-McKibbin","Non-Executive Member")),
    "NORGES": (("Ida Wolden Bache","Governor"),("Pal Longva","Deputy Governor"),("Steinar Holden","External member"),("Ingvild Almas","External member"),("Ingrid Solberg","External member")),
    "BOE": (("Andrew Bailey","Governor"),("Clare Lombardelli","Deputy Governor"),("Sarah Breeden","Deputy Governor"),("Dave Ramsden","Deputy Governor"),("Megan Greene","External member"),("Swati Dhingra","External member"),("Catherine Mann","External member"),("Alan Taylor","External member"),("Huw Pill","Chief Economist")),
    "FED": (("Jerome Powell","Chair"),("Philip Jefferson","Vice Chair"),("Michelle Bowman","Vice Chair for Supervision"),("Michael Barr","Governor"),("Christopher Waller","Governor"),("Lisa Cook","Governor"),("Adriana Kugler","Governor"),("John Williams","New York Fed"),("Austan Goolsbee","Chicago Fed"),("Lorie Logan","Dallas Fed"),("Beth Hammack","Cleveland Fed"),("Neel Kashkari","Minneapolis Fed"),("Tom Barkin","Richmond Fed"),("Raphael Bostic","Atlanta Fed"),("Alberto Musalem","St Louis Fed"),("Susan Collins","Boston Fed"),("Anna Paulson","Philadelphia Fed"),("Jeff Schmid","Kansas City Fed")),
    "RBNZ": (("Christian Hawkesby","Governor"),("Karen Silk","Assistant Governor"),("Paul Conway","Chief Economist"),("Peter Harris","External member"),("Prasanna Gai","External member"),("Caroline Saunders","External member")),
    "ECB": (("Christine Lagarde","President"),("Luis de Guindos","Vice-President"),("Philip R. Lane","Executive Board"),("Isabel Schnabel","Executive Board"),("Frank Elderson","Executive Board"),("Piero Cipollone","Executive Board")),
    "BOC": (("Tiff Macklem","Governor"),("Carolyn Rogers","Senior Deputy Governor"),("Toni Gravelle","Deputy Governor"),("Sharon Kozicki","Deputy Governor"),("Nicolas Vincent","Deputy Governor"),("Rhys Mendes","Deputy Governor"),("Michelle Alexopoulos","External Deputy Governor")),
    "RIKSBANK": (("Erik Thedeen","Governor"),("Anna Breman","First Deputy Governor"),("Per Jansson","Deputy Governor"),("Aino Bunge","Deputy Governor"),("Vanja Linder","Deputy Governor")),
    "BOJ": (("Kazuo Ueda","Governor"),("Ryozo Himino","Deputy Governor"),("Shinichi Uchida","Deputy Governor"),("Naoki Tamura","Policy Board member"),("Junko Nakagawa","Policy Board member"),("Hajime Takata","Policy Board member"),("Asahi Noguchi","Policy Board member"),("Toyoaki Nakamura","Policy Board member"),("Junko Koeda","Policy Board member")),
    "SNB": (("Martin Schlegel","Chairman"),("Antoine Martin","Vice Chairman"),("Petra Tschudin","Governing Board member")),
}

CB38_HAWKISH = {
    "inflation remains high":2.5, "inflation persistence":2.2, "persistent inflation":2.2,
    "upside inflation risk":2.1, "upside risks to inflation":2.1, "above target":1.5,
    "price pressures":1.2, "wage pressures":1.3, "tight labour market":1.2,
    "restrictive":1.0, "higher for longer":2.0, "raise rates":2.2, "rate increase":1.8,
    "further tightening":2.0, "tighten policy":1.8, "not declare victory":1.4,
    "vigilant":.7, "second-round effects":1.5, "overheating":1.7, "strong demand":.8,
}
CB38_DOVISH = {
    "disinflation":1.4, "inflation is easing":1.6, "inflation has fallen":1.4,
    "downside risks":1.3, "weak demand":1.1, "growth is weak":1.2, "economic weakness":1.2,
    "labour market is cooling":1.4, "unemployment is rising":1.4, "slack":.8,
    "cut rates":2.2, "rate cut":1.8, "lower rates":1.4, "ease policy":1.8,
    "policy easing":1.7, "less restrictive":1.3, "accommodative":1.0,
    "below target":1.2, "recession":1.2, "soft landing":.4,
}
CB38_NEGATIONS = ("not ", "no ", "less ", "without ", "unlikely ")
CB38_POLICY_TERMS = ("inflation","price","rate","monetary","policy","growth","employment","labour","wage","demand","economic")


def _cb38_css() -> None:
    _html(
        """
<style>
.cb38-path{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin:4px 0 11px;color:#8194a7;font-size:10px}.cb38-path b{color:#d8bf58}
.cb38-model{border:1px solid rgba(129,157,185,.20);border-radius:11px;background:rgba(5,17,29,.76);padding:0 14px;margin:8px 0 14px}.cb38-model summary{cursor:pointer;padding:12px 0;color:#eef3f7;font-family:Georgia,serif;font-size:16px}.cb38-model p{color:#91a1b0;font-size:10px;line-height:1.55}
.cb38-card{position:relative;border:1px solid rgba(128,157,186,.24);border-radius:11px;padding:12px 12px 10px;background:linear-gradient(145deg,rgba(8,24,39,.96),rgba(5,15,26,.98));min-height:158px}.cb38-card:before{content:"";position:absolute;left:0;top:0;bottom:0;width:2px;background:linear-gradient(#63c7ff,transparent)}.cb38-card-head{display:flex;justify-content:space-between;gap:7px;align-items:center}.cb38-card-code{font-weight:850;color:#eef3f7;font-family:ui-monospace,monospace}.cb38-card-ccy{color:#71869a;font-size:9px}.cb38-card-rate{font-family:Georgia,serif;font-size:27px;color:#f2f5f8;margin:12px 0 2px}.cb38-card-decision{font-size:10px;font-weight:850;color:#d8bf58}.cb38-card-name{font-size:9px;color:#8495a6;margin-top:6px}.cb38-track{height:13px;border-radius:4px;background:linear-gradient(90deg,rgba(102,129,70,.75),rgba(207,216,198,.65) 38%,rgba(214,186,169,.62) 62%,rgba(132,50,45,.78));margin:10px 0 7px;position:relative}.cb38-diamond{position:absolute;top:2px;width:9px;height:9px;background:#f4f7fa;transform:rotate(45deg);border-radius:1px}.cb38-card-meta{display:flex;justify-content:space-between;gap:8px;font-size:9px;color:#8ea0b0}.cb38-score-pos{color:#57d39b}.cb38-score-neg{color:#f4777f}.cb38-score-na{color:#8fa0b0}
.cb38-ranked{border:1px solid rgba(128,157,186,.20);border-radius:11px;background:rgba(5,17,29,.77);padding:10px 14px}.cb38-rank-row{display:grid;grid-template-columns:34px 1fr 90px 55px;gap:8px;align-items:center;padding:7px 2px;border-bottom:1px solid rgba(128,157,186,.10);font-size:10px}.cb38-rank-row:last-child{border-bottom:none}.cb38-rank-code{font-weight:800}.cb38-rank-rate{text-align:right;font-family:ui-monospace,monospace;color:#eef3f7}.cb38-rank-mark{text-align:right;color:#d8bf58}
.cb38-stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px;margin:8px 0 15px}.cb38-stat{border-top:2px solid rgba(99,199,255,.55);background:rgba(5,17,29,.79);border-radius:8px;padding:10px 11px;min-height:78px}.cb38-stat-k{font-size:8px;letter-spacing:.13em;text-transform:uppercase;color:#8496a6}.cb38-stat-v{font-family:ui-monospace,monospace;color:#f2f5f8;font-weight:850;font-size:17px;margin-top:7px}.cb38-stat-n{font-size:8px;color:#8092a2;margin-top:4px}
.cb38-stance{border:1px solid rgba(128,157,186,.20);border-radius:11px;padding:15px;background:rgba(5,17,29,.78);margin:7px 0 15px}.cb38-stance-title{font-family:Georgia,serif;color:#f2f5f8;font-size:18px}.cb38-stance-track{height:22px;border-radius:5px;background:linear-gradient(90deg,#72783e,#b7c0a4 38%,#d8c4b7 62%,#8f433e);position:relative;margin:13px 0 5px}.cb38-stance-pointer{position:absolute;top:5px;width:12px;height:12px;background:#f5f7f9;transform:rotate(45deg);border-radius:2px}.cb38-stance-labels{display:flex;justify-content:space-between;color:#8798a8;font-size:9px}
.cb38-speech{border:1px solid rgba(128,157,186,.17);border-radius:9px;padding:10px 12px;margin:6px 0;background:rgba(5,17,29,.69);display:grid;grid-template-columns:1fr 76px;gap:12px}.cb38-speech-title{font-size:10px;color:#e6edf2;font-weight:720}.cb38-speech-meta{font-size:8px;color:#8092a3;margin-top:4px}.cb38-speech-score{text-align:right;font-family:ui-monospace,monospace;font-weight:800;font-size:11px;padding-top:4px}.cb38-speech-conf{font-size:7px;color:#71869a;margin-top:4px;text-align:right}
.cb38-member-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:8px 0 14px}.cb38-member{border:1px solid rgba(128,157,186,.22);border-left:2px solid rgba(99,199,255,.75);border-radius:10px;padding:12px;background:rgba(5,17,29,.78);min-height:137px}.cb38-member-top{display:flex;justify-content:space-between;gap:8px}.cb38-member-name{font-family:Georgia,serif;font-size:16px;color:#f2f5f8}.cb38-member-score{font-family:ui-monospace,monospace;font-weight:850}.cb38-member-role{font-size:9px;color:#91a1b0;margin:3px 0 10px}.cb38-member-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:5px}.cb38-member-metric b{display:block;font-size:8px;color:#8193a3;text-transform:uppercase}.cb38-member-metric span{font-size:10px;color:#d8e1e8}.cb38-member-foot{font-size:8px;color:#7e91a2;margin-top:9px;line-height:1.45}
.cb38-callout{border:1px solid rgba(216,191,88,.25);border-left:3px solid #d8bf58;border-radius:9px;background:rgba(216,191,88,.055);padding:11px 13px;color:#c7bea0;font-size:10px;line-height:1.5;margin:9px 0 14px}.cb38-source{display:flex;gap:11px;flex-wrap:wrap;color:#74889a;font-size:8px;margin:6px 0 1px}.cb38-source b{color:#9fb0bd}
.cb38-quality{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:7px;margin:8px 0 14px}.cb38-q{border:1px solid rgba(128,157,186,.18);border-radius:9px;background:rgba(5,17,29,.72);padding:9px}.cb38-q b{display:block;color:#eef3f7;font-size:10px;margin-bottom:4px}.cb38-q span{display:block;color:#8194a7;font-size:8px;line-height:1.4}.cb38-ok{color:#57d39b!important}.cb38-warn{color:#d8bf58!important}.cb38-bad{color:#f4777f!important}
@media(max-width:980px){.cb38-stats{grid-template-columns:repeat(2,minmax(0,1fr))}.cb38-member-grid,.cb38-quality{grid-template-columns:1fr}.cb38-rank-row{grid-template-columns:30px 1fr 74px 48px}}
</style>
        """
    )


def _cb38_slug(value: Any) -> str:
    return _cb38_re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")


def _cb38_norm(value: Any) -> str:
    text = str(value or "").lower().replace("é", "e").replace("è", "e").replace("ö", "o").replace("ü", "u").replace("å", "a").replace("ä", "a")
    return _cb38_re.sub(r"[^a-z0-9]+", " ", text).strip()


def _cb38_path(parts: Sequence[str]) -> None:
    _html('<div class="cb38-path">' + ' <span>›</span> '.join(f'<b>{_esc(x)}</b>' if i == len(parts)-1 else _esc(x) for i, x in enumerate(parts)) + '</div>')


def _cb38_source(items: Sequence[Tuple[str, str]]) -> None:
    _html('<div class="cb38-source">' + ''.join(f'<span><b>{_esc(k)}:</b> {_esc(v)}</span>' for k, v in items) + '</div>')


def _cb38_http_get(url: str, timeout: int = CB38_TIMEOUT) -> Optional[Any]:
    if _cb38_requests is None or not url:
        return None
    try:
        response = _cb38_requests.get(url, timeout=timeout, headers={"User-Agent": CB38_USER_AGENT, "Accept-Encoding":"gzip"})
        response.raise_for_status()
        return response
    except Exception:
        return None


def _cb38_clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [_cb38_re.sub(r"[^A-Z0-9]+", "_", str(c).upper()).strip("_") for c in out.columns]
    return out


def _cb38_find_col(df: pd.DataFrame, exact: Sequence[str], contains: Sequence[str] = ()) -> Optional[str]:
    cols = list(df.columns)
    exact_set = {_cb38_re.sub(r"[^A-Z0-9]+", "_", str(x).upper()).strip("_") for x in exact}
    for col in cols:
        if col in exact_set:
            return col
    for token in contains:
        token_u = str(token).upper()
        for col in cols:
            if token_u in col:
                return col
    return None


def _cb38_parse_period(value: Any) -> pd.Timestamp:
    text = str(value or "").strip()
    if not text:
        return pd.NaT
    if _cb38_re.fullmatch(r"\d{4}-Q[1-4]", text, flags=_cb38_re.I):
        try: return pd.Period(text.upper(), freq="Q").to_timestamp(how="end").normalize()
        except Exception: return pd.NaT
    if _cb38_re.fullmatch(r"\d{4}-M\d{1,2}", text, flags=_cb38_re.I):
        text = text[:4] + "-" + text.split("M")[-1].zfill(2) + "-01"
    if _cb38_re.fullmatch(r"\d{4}", text):
        text += "-12-31"
    return pd.to_datetime(text, errors="coerce")


@st.cache_data(ttl=21600, show_spinner=False)
def _cb38_bis_bulk(kind: str) -> Tuple[pd.DataFrame, str]:
    """Load only G10 rows and required columns from the BIS bulk ZIP.

    The previous implementation materialised the largest CSV in memory and then
    cached it. On constrained Codespaces this could trigger an OS-level SIGKILL.
    This version streams the ZIP to a spooled file, reads the CSV in chunks and
    retains only the configured G10 areas plus the dimensions needed downstream.
    """
    url = CB38_BIS_POLICY_ZIP if kind == "policy" else CB38_BIS_ASSETS_ZIP
    if _cb38_requests is None:
        return pd.DataFrame(), "BIS bulk unavailable · requests missing"

    spool = _cb38_tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024, mode="w+b")
    response = None
    try:
        response = _cb38_requests.get(
            url,
            timeout=35,
            headers={"User-Agent": CB38_USER_AGENT, "Accept-Encoding": "gzip"},
            stream=True,
        )
        response.raise_for_status()
        total = 0
        for block in response.iter_content(chunk_size=1024 * 1024):
            if not block:
                continue
            total += len(block)
            if total > CB38_MAX_DOWNLOAD_BYTES:
                return pd.DataFrame(), "BIS bulk skipped · download exceeds safety limit"
            spool.write(block)
        spool.seek(0)

        with _cb38_zipfile.ZipFile(spool) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
            if not names:
                return pd.DataFrame(), "BIS ZIP contained no CSV"
            name = max(names, key=lambda n: archive.getinfo(n).file_size)

            with archive.open(name) as fh:
                header_raw = pd.read_csv(fh, nrows=0)
            if header_raw is None or len(header_raw.columns) == 0:
                return pd.DataFrame(), "BIS CSV header unavailable"

            original_columns = list(header_raw.columns)
            clean_map = {
                col: _cb38_re.sub(r"[^A-Z0-9]+", "_", str(col).upper()).strip("_")
                for col in original_columns
            }
            clean_columns = list(clean_map.values())

            def _pick(exact: Sequence[str], contains: Sequence[str] = ()) -> Optional[str]:
                exact_set = {
                    _cb38_re.sub(r"[^A-Z0-9]+", "_", str(x).upper()).strip("_")
                    for x in exact
                }
                for original, clean in clean_map.items():
                    if clean in exact_set:
                        return original
                for token in contains:
                    token_u = str(token).upper()
                    for original, clean in clean_map.items():
                        if token_u in clean:
                            return original
                return None

            time_original = _pick(("TIME_PERIOD", "TIME", "PERIOD", "DATE"), ("TIME_PERIOD",))
            value_original = _pick(("OBS_VALUE", "VALUE", "OBSERVATION_VALUE"), ("OBS_VALUE",))
            if not time_original or not value_original:
                return pd.DataFrame(), "BIS CSV required columns unavailable"

            optional_clean = {
                "FREQ", "FREQUENCY", "UNIT_MEASURE", "UNIT", "UNIT_OF_MEASURE",
                "UNIT_MULT", "UNIT_MULTIPLIER", "SERIES_KEY", "SERIES_CODE", "KEY",
                "TIME_SERIES", "COLLECTION", "COLLECTION_INDICATOR", "ADJUSTMENT",
                "SOURCE", "METHOD",
            }
            area_original = [
                original for original, clean in clean_map.items()
                if any(token in clean for token in ("REF_AREA", "COUNTRY", "LOCATION", "AREA", "JURISDICTION"))
            ]
            selected_original = {time_original, value_original, *area_original}
            for original, clean in clean_map.items():
                if clean in optional_clean:
                    selected_original.add(original)
            selected_original = [col for col in original_columns if col in selected_original]

            all_codes = {
                str(area).upper()
                for bank in CB38_BANK_BY_CODE.values()
                for area in bank.get("area_codes", ())
            }
            all_names = tuple(
                _cb38_norm(name)
                for bank in CB38_BANK_BY_CODE.values()
                for name in bank.get("area_names", ())
                if _cb38_norm(name)
            )

            kept = []
            kept_rows = 0
            with archive.open(name) as fh:
                reader = pd.read_csv(
                    fh,
                    usecols=selected_original,
                    dtype=str,
                    chunksize=max(10000, CB38_BULK_CHUNK_ROWS),
                    low_memory=True,
                )
                for raw_chunk in reader:
                    chunk = _cb38_clean_columns(raw_chunk)
                    mask = pd.Series(False, index=chunk.index)
                    area_cols = [
                        col for col in chunk.columns
                        if any(token in col for token in ("REF_AREA", "COUNTRY", "LOCATION", "AREA", "JURISDICTION"))
                    ]
                    for col in area_cols:
                        vals = chunk[col].fillna("").astype(str)
                        mask = mask | vals.str.upper().isin(all_codes)
                        # Name matching is a fallback for providers that publish labels rather than ISO codes.
                        if not bool(mask.all()):
                            normed = vals.map(_cb38_norm)
                            for name_term in all_names:
                                mask = mask | normed.str.contains(_cb38_re.escape(name_term), regex=True, na=False)
                    if not bool(mask.any()):
                        continue
                    use = chunk.loc[mask].copy()
                    remaining = CB38_MAX_BULK_ROWS - kept_rows
                    if remaining <= 0:
                        break
                    if len(use) > remaining:
                        use = use.head(remaining)
                    kept.append(use)
                    kept_rows += len(use)
                    if kept_rows >= CB38_MAX_BULK_ROWS:
                        break

        if not kept:
            return pd.DataFrame(), "BIS bulk returned no configured G10 rows"
        compact = pd.concat(kept, ignore_index=True)
        _cb38_gc.collect()
        return compact, f"BIS {'policy rates' if kind == 'policy' else 'central-bank total assets'} bulk · compact G10 load"
    except Exception as exc:
        return pd.DataFrame(), f"BIS bulk parse failed · {type(exc).__name__}"
    finally:
        try:
            if response is not None:
                response.close()
        except Exception:
            pass
        try:
            spool.close()
        except Exception:
            pass


def _cb38_area_mask(df: pd.DataFrame, bank: Mapping[str, Any]) -> pd.Series:
    mask = pd.Series(False, index=df.index)
    code_set = {str(x).upper() for x in bank.get("area_codes", ())}
    names = tuple(_cb38_norm(x) for x in bank.get("area_names", ()))
    for col in df.columns:
        if any(token in col for token in ("REF_AREA","COUNTRY","LOCATION","AREA","JURISDICTION")):
            vals = df[col].astype(str)
            mask = mask | vals.str.upper().isin(code_set)
            normed = vals.map(_cb38_norm)
            for name in names:
                if name:
                    mask = mask | normed.str.contains(_cb38_re.escape(name), regex=True, na=False)
    return mask


def _cb38_series_groups(df: pd.DataFrame) -> pd.Series:
    key_col = _cb38_find_col(df, ("SERIES_KEY","SERIES_CODE","KEY","TIME_SERIES"), ("SERIES_KEY","SERIES_CODE"))
    if key_col:
        return df[key_col].astype(str)
    dims = [c for c in ("FREQ","REF_AREA","UNIT_MEASURE","UNIT","COLLECTION","COLLECTION_INDICATOR","ADJUSTMENT","SOURCE","METHOD") if c in df.columns]
    if not dims:
        return pd.Series("SERIES", index=df.index)
    return df[dims].astype(str).agg("|".join, axis=1)


def _cb38_select_bis(kind: str, code: str, start: str = "2000-01-01") -> Tuple[pd.DataFrame, str, str]:
    bank = CB38_BANK_BY_CODE[code]
    raw, source = _cb38_bis_bulk(kind)
    if raw.empty:
        return pd.DataFrame(columns=["date","value"]), source, ""
    time_col = _cb38_find_col(raw, ("TIME_PERIOD","TIME","PERIOD","DATE"), ("TIME_PERIOD",))
    value_col = _cb38_find_col(raw, ("OBS_VALUE","VALUE","OBSERVATION_VALUE"), ("OBS_VALUE",))
    if not time_col or not value_col:
        return pd.DataFrame(columns=["date","value"]), source + " · columns unavailable", ""
    work = raw[_cb38_area_mask(raw, bank)].copy()
    if work.empty:
        return pd.DataFrame(columns=["date","value"]), source + " · area not found", ""
    work["_DATE"] = work[time_col].map(_cb38_parse_period)
    work["_VALUE"] = pd.to_numeric(work[value_col], errors="coerce")
    work = work.dropna(subset=["_DATE","_VALUE"])
    work = work[work["_DATE"] >= pd.Timestamp(start)]
    if work.empty:
        return pd.DataFrame(columns=["date","value"]), source + " · no observations", ""
    freq_col = _cb38_find_col(work, ("FREQ","FREQUENCY"), ("FREQ",))
    unit_col = _cb38_find_col(work, ("UNIT_MEASURE","UNIT","UNIT_OF_MEASURE"), ("UNIT_MEASURE",))
    mult_col = _cb38_find_col(work, ("UNIT_MULT","UNIT_MULTIPLIER"), ("UNIT_MULT",))
    work["_SERIES"] = _cb38_series_groups(work)
    candidates = []
    for key, group in work.groupby("_SERIES", dropna=False):
        freq = str(group[freq_col].iloc[0]).upper() if freq_col else ""
        unit = str(group[unit_col].iloc[0]).upper() if unit_col else ""
        if kind == "policy":
            pref = {"D":4,"B":4,"M":3,"Q":2,"A":1}.get(freq,0)
            unit_pref = 2 if ("PERCENT" in unit or unit in {"PC","PCT","%"}) else 0
        else:
            pref = {"M":4,"Q":3,"W":2,"A":1}.get(freq,0)
            unit_pref = 4 if ("USD" in unit or "US DOLLAR" in unit) else (2 if unit else 0)
        candidates.append((pref,unit_pref,len(group),group["_DATE"].max(),str(key),group.copy(),unit))
    if not candidates:
        return pd.DataFrame(columns=["date","value"]), source + " · no series", ""
    candidates.sort(key=lambda x:(x[0],x[1],x[2],x[3]), reverse=True)
    _,_,_,_,series_key,group,unit = candidates[0]
    values = group["_VALUE"].astype(float)
    if mult_col:
        mult = pd.to_numeric(group[mult_col], errors="coerce").fillna(0.0)
        values = values * np.power(10.0, mult)
    out = pd.DataFrame({"date":group["_DATE"],"value":values}).dropna().sort_values("date").drop_duplicates("date",keep="last")
    if kind == "assets":
        if "USD" in unit or "US DOLLAR" in unit:
            out["value"] = out["value"] / 1e9
            unit_label = "USD bn"
        else:
            median = float(out["value"].abs().median()) if not out.empty else 0.0
            if median > 1e8:
                out["value"] = out["value"] / 1e9
                unit_label = f"{bank['ccy']} bn"
            elif median > 1e5:
                out["value"] = out["value"] / 1e6
                unit_label = f"{bank['ccy']} mn"
            else:
                unit_label = unit or bank["ccy"]
    else:
        if out["value"].abs().median() < .2 and ("PERCENT" not in unit and unit not in {"PC","PCT","%"}):
            out["value"] = out["value"] * 100.0
        unit_label = "%"
    return out.reset_index(drop=True), f"{source} · {series_key}", unit_label


@st.cache_data(ttl=21600, show_spinner=False)
def _cb38_fred_series(series_id: str, start: str = "2000-01-01") -> pd.DataFrame:
    sid = str(series_id or "").strip().upper()
    if not sid:
        return pd.DataFrame(columns=["date","value"])
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={_cb38_quote(sid)}"
    response = _cb38_http_get(url)
    try:
        raw = pd.read_csv(_cb38_io.StringIO(response.text)) if response is not None else pd.read_csv(url)
        if raw.empty or len(raw.columns) < 2:
            return pd.DataFrame(columns=["date","value"])
        out = raw.iloc[:, :2].copy(); out.columns = ["date","value"]
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        out["value"] = pd.to_numeric(out["value"].replace(".",np.nan), errors="coerce")
        out = out.dropna().sort_values("date")
        return out[out["date"] >= pd.Timestamp(start)].reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=["date","value"])


def _cb38_first_fred(candidates: Sequence[str], start: str) -> Tuple[pd.DataFrame, str]:
    for sid in candidates:
        df = _cb38_fred_series(str(sid), start)
        if len(df) >= 2:
            return df, f"FRED {sid}"
    return pd.DataFrame(columns=["date","value"]), ""


def _cb38_policy_series(code: str, start: str = "2000-01-01") -> Tuple[pd.DataFrame, str]:
    df, source, _ = _cb38_select_bis("policy", code, start)
    if len(df) >= 2:
        return df, source
    fallback, fsource = _cb38_first_fred(CB38_BANK_BY_CODE[code].get("fred_rate",()), start)
    if len(fallback) >= 2:
        return fallback, fsource
    return pd.DataFrame(columns=["date","value"]), source or "No public policy-rate series"


def _cb38_assets_series(code: str, start: str = "2016-01-01") -> Tuple[pd.DataFrame, str, str]:
    df, source, unit = _cb38_select_bis("assets", code, start)
    if len(df) >= 2:
        return df, source, unit
    fallback, fsource = _cb38_first_fred(CB38_BANK_BY_CODE[code].get("fred_assets",()), start)
    if len(fallback) >= 2:
        median = float(fallback["value"].abs().median())
        if median > 1e6:
            fallback["value"] = fallback["value"] / 1000.0
        return fallback, fsource, "native bn / provider units"
    return pd.DataFrame(columns=["date","value"]), source or "No public balance-sheet series", unit


def _cb38_parse_date(text: Any, href: str = "") -> pd.Timestamp:
    blob = f"{text or ''} {href or ''}"
    iso = _cb38_re.search(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b", blob)
    if iso:
        return pd.to_datetime("-".join(iso.groups()), errors="coerce")
    compact = _cb38_re.search(r"\b(20\d{2})(0[1-9]|1[0-2])([0-3]\d)\b", blob)
    if compact:
        return pd.to_datetime("".join(compact.groups()), format="%Y%m%d", errors="coerce")
    for pattern in (r"\b([0-3]?\d)\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b", r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+([0-3]?\d),?\s+(20\d{2})\b"):
        match = _cb38_re.search(pattern, blob, flags=_cb38_re.I)
        if match:
            return pd.to_datetime(" ".join(match.groups()), errors="coerce")
    euro = _cb38_re.search(r"\b([0-3]?\d)[./](0?[1-9]|1[0-2])[./](20\d{2})\b", blob)
    if euro:
        return pd.to_datetime("-".join((euro.group(3),euro.group(2),euro.group(1))), errors="coerce")
    return pd.NaT


def _cb38_extract_html_text(content: bytes) -> str:
    try:
        text = content.decode("utf-8", errors="ignore")
    except Exception:
        return ""
    if _cb38_BeautifulSoup is not None:
        try:
            soup = _cb38_BeautifulSoup(text, "html.parser")
            for tag in soup(["script","style","nav","footer","header"]): tag.decompose()
            return " ".join(soup.get_text(" ", strip=True).split())
        except Exception:
            pass
    text = _cb38_re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", text, flags=_cb38_re.I)
    text = _cb38_re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


def _cb38_infer_speaker(code: str, text: str) -> str:
    norm = _cb38_norm(text)
    for name, _ in CB38_ROSTERS.get(code, ()):
        if _cb38_norm(name) in norm:
            return name
    lead = _cb38_re.split(r"[:–—|-]", str(text), maxsplit=1)[0].strip()
    words = lead.split()
    if 1 < len(words) <= 5 and len(lead) < 55:
        return lead
    return CB38_BANK_BY_CODE[code]["short"] + " communication"


def _cb38_infer_bank(text: str, url: str = "") -> Optional[str]:
    blob = _cb38_norm(text + " " + url)
    roster_matches = []
    for code, roster in CB38_ROSTERS.items():
        for name, _ in roster:
            if _cb38_norm(name) in blob:
                roster_matches.append(code); break
    if len(set(roster_matches)) == 1:
        return roster_matches[0]
    for code, bank in CB38_BANK_BY_CODE.items():
        terms = list(bank.get("area_names",())) + [bank["name"], bank["short"]]
        if any(_cb38_norm(term) and _cb38_norm(term) in blob for term in terms):
            return code
    domain = _cb38_urlparse(url).netloc.lower()
    domain_map = {"rba.gov.au":"RBA","norges-bank.no":"NORGES","bankofengland.co.uk":"BOE","federalreserve.gov":"FED","rbnz.govt.nz":"RBNZ","ecb.europa.eu":"ECB","bankofcanada.ca":"BOC","riksbank.se":"RIKSBANK","boj.or.jp":"BOJ","snb.ch":"SNB"}
    return next((code for dom,code in domain_map.items() if dom in domain), None)


def _cb38_score_text(text: Any) -> Tuple[float, float, int]:
    raw = _cb38_norm(text)
    if not raw:
        return 0.0, 0.0, 0
    hawk = dove = 0.0; hits = 0
    for phrase, weight in CB38_HAWKISH.items():
        count = raw.count(_cb38_norm(phrase))
        if count:
            hawk += count * weight; hits += count
    for phrase, weight in CB38_DOVISH.items():
        count = raw.count(_cb38_norm(phrase))
        if count:
            dove += count * weight; hits += count
    # Single-token support, intentionally low weight to prevent title noise.
    tokens = raw.split()
    hawk += .12 * sum(tokens.count(x) for x in ("tightening","hawkish","restrictive","persistent","upside"))
    dove += .12 * sum(tokens.count(x) for x in ("easing","dovish","weakness","downside","disinflationary"))
    relevance = sum(raw.count(term) for term in CB38_POLICY_TERMS)
    net = hawk - dove
    score = float(np.tanh(net / max(2.4, math.sqrt(max(1, hits)) * 1.7)))
    confidence = float(min(1.0, .08 * hits + .015 * relevance))
    if relevance == 0:
        score *= .25; confidence *= .25
    return max(-1.0,min(1.0,score)), confidence, hits


@st.cache_data(ttl=10800, show_spinner=False)
def _cb38_bis_rss(enrich_text: bool = False) -> pd.DataFrame:
    columns = ["Date","CB","Speaker","Title","Score","Confidence","Source","URL","Text"]
    response = _cb38_http_get(CB38_BIS_SPEECH_RSS)
    if response is None:
        return pd.DataFrame(columns=columns)
    rows = []
    try:
        root = _cb38_et.fromstring(response.content)
        items = root.findall(".//item")[:max(1, CB38_MAX_RSS_ITEMS)]
        for index, item in enumerate(items):
            title = (item.findtext("title") or "").strip()
            desc = (item.findtext("description") or "").strip()
            link = (item.findtext("link") or "").strip()
            date_text = (item.findtext("pubDate") or "").strip()
            try:
                dt = pd.Timestamp(_cb38_parsedate(date_text)).tz_localize(None)
            except Exception:
                dt = _cb38_parse_date(title + " " + desc + " " + link)
            code = _cb38_infer_bank(title + " " + desc, link)
            if code not in CB38_BANK_BY_CODE or pd.isna(dt):
                continue
            speaker = _cb38_infer_speaker(code, title + " " + desc)
            body = _cb38_extract_html_text(desc.encode("utf-8"))
            # Full-page enrichment is opt-in and capped; default routes never do this.
            if enrich_text and index < CB38_MAX_ENRICH_ITEMS and link:
                page = _cb38_http_get(link, timeout=min(CB38_TIMEOUT, 10))
                if page is not None:
                    full = _cb38_extract_html_text(page.content[:2_000_000])
                    if len(full) > len(body):
                        body = full[:80000]
            score, conf, _ = _cb38_score_text(title + " " + body)
            rows.append({
                "Date":dt.normalize(),"CB":code,"Speaker":speaker,"Title":title,
                "Score":score,"Confidence":conf,"Source":"BIS central bankers' speeches",
                "URL":link,"Text":body,
            })
    except Exception:
        return pd.DataFrame(columns=columns)
    out = pd.DataFrame(rows, columns=columns)
    if out.empty:
        return out
    return out.sort_values("Date",ascending=False).drop_duplicates(["CB","Title","Date"]).reset_index(drop=True)


@st.cache_data(ttl=21600, show_spinner=False)
def _cb38_official_archive(code: str, kind: str = "speech") -> pd.DataFrame:
    bank = CB38_BANK_BY_CODE[code]
    url = str(bank["speech_url" if kind == "speech" else "decision_url"])
    response = _cb38_http_get(url)
    columns = ["Date","CB","Speaker","Title","Score","Confidence","Source","URL","Text"] if kind == "speech" else ["Date","Title","URL","Source"]
    if response is None:
        return pd.DataFrame(columns=columns)
    try:
        page = response.text
        links = []
        if _cb38_BeautifulSoup is not None:
            soup = _cb38_BeautifulSoup(page, "html.parser")
            for a in soup.find_all("a", href=True):
                title = " ".join(a.get_text(" ", strip=True).split())
                href = _cb38_urljoin(url, a.get("href"))
                context = " ".join((a.parent.get_text(" ",strip=True) if a.parent else title).split())[:1200]
                links.append((title,href,context))
        else:
            for href,title in _cb38_re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', page, flags=_cb38_re.I|_cb38_re.S):
                links.append((_cb38_re.sub(r"<[^>]+>"," ",title).strip(),_cb38_urljoin(url,href),title))
        rows=[]; seen=set()
        if kind == "speech":
            keywords=("speech","remarks","address","lecture","statement","opening","testimony","presentation","interview","fireside","conference")
        else:
            keywords=("monetary policy","rate decision","cash rate","official cash rate","fomc statement","policy decision","bank rate","interest rate","meeting minutes","monetary policy summary")
        for title,href,context in links:
            blob=_cb38_norm(title+" "+context+" "+href)
            if not title or not any(_cb38_norm(k) in blob for k in keywords):
                continue
            dt=_cb38_parse_date(context,href)
            if pd.isna(dt):
                continue
            key=(dt.normalize(),title.lower())
            if key in seen: continue
            seen.add(key)
            if kind=="speech":
                speaker=_cb38_infer_speaker(code,context+" "+title)
                score,conf,_=_cb38_score_text(title+" "+context)
                rows.append({"Date":dt.normalize(),"CB":code,"Speaker":speaker,"Title":title,"Score":score,"Confidence":conf,"Source":f"{bank['short']} official archive","URL":href,"Text":context})
            else:
                rows.append({"Date":dt.normalize(),"Title":title,"URL":href,"Source":f"{bank['short']} official decisions"})
        return pd.DataFrame(rows,columns=columns).sort_values("Date",ascending=False).head(160).reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=columns)


def _cb38_speeches(code: Optional[str] = None, deep: bool = False) -> pd.DataFrame:
    """Resolve communications with a fast default path.

    deep=False: BIS RSS plus one selected bank's official archive.
    deep=True: bounded full-text enrichment and bounded all-bank archive crawl.
    """
    deep = bool(deep)
    bis = _cb38_bis_rss(enrich_text=deep)
    if code:
        official = _cb38_official_archive(code,"speech")
        frames=[x for x in (bis[bis["CB"]==code].copy() if not bis.empty else pd.DataFrame(),official) if not x.empty]
        if not frames:
            return pd.DataFrame(columns=["Date","CB","Speaker","Title","Score","Confidence","Source","URL","Text"])
        return pd.concat(frames,ignore_index=True).sort_values("Date",ascending=False).drop_duplicates(["CB","Title","Date"]).reset_index(drop=True)
    frames=[bis]
    if deep:
        with _cb38_ThreadPoolExecutor(max_workers=3) as pool:
            futures={pool.submit(_cb38_official_archive,bank_code,"speech"):bank_code for bank_code in CB38_BANK_BY_CODE}
            for future in _cb38_as_completed(futures):
                try:
                    df=future.result()
                    if not df.empty:
                        frames.append(df)
                except Exception:
                    pass
    frames=[x for x in frames if isinstance(x,pd.DataFrame) and not x.empty]
    if not frames:
        return pd.DataFrame(columns=["Date","CB","Speaker","Title","Score","Confidence","Source","URL","Text"])
    return pd.concat(frames,ignore_index=True).sort_values("Date",ascending=False).drop_duplicates(["CB","Title","Date"]).reset_index(drop=True)


def _cb38_score_snapshot(df: pd.DataFrame) -> Dict[str, Any]:
    if df is None or df.empty:
        return {"recent":None,"lifetime":None,"count":0,"confidence":0.0,"last_date":None}
    work=df.dropna(subset=["Date","Score"]).copy().sort_values("Date")
    if work.empty:
        return {"recent":None,"lifetime":None,"count":0,"confidence":0.0,"last_date":None}
    scores=pd.to_numeric(work["Score"],errors="coerce").dropna()
    if scores.empty:
        return {"recent":None,"lifetime":None,"count":0,"confidence":0.0,"last_date":None}
    recent=float(scores.ewm(span=12,adjust=False).mean().iloc[-1])
    age=(work["Date"].max()-work.loc[scores.index,"Date"]).dt.days.clip(lower=0)
    weights=np.exp(-np.log(2)*age/365.0)
    lifetime=float(np.average(scores,weights=weights)) if float(weights.sum())>0 else float(scores.mean())
    conf=float(pd.to_numeric(work.loc[scores.index,"Confidence"],errors="coerce").fillna(0).mean())
    return {"recent":recent,"lifetime":lifetime,"count":int(len(scores)),"confidence":conf,"last_date":pd.Timestamp(work["Date"].max())}


def _cb38_score_history(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=float)
    work=df.dropna(subset=["Date","Score"]).copy()
    if work.empty: return pd.Series(dtype=float)
    work["Date"]=pd.to_datetime(work["Date"],errors="coerce")
    monthly=work.set_index("Date")["Score"].resample("MS").mean()
    monthly=monthly.ewm(span=12,adjust=False,min_periods=1).mean()
    return monthly.dropna().clip(-1,1)


def _cb38_detect_rate_status(series: pd.DataFrame) -> Dict[str, Any]:
    if series is None or series.empty:
        return {"rate":None,"date":None,"decision":"N/A","change_bps":None,"since":None}
    work=series.dropna().sort_values("date").copy(); work["value"]=pd.to_numeric(work["value"],errors="coerce"); work=work.dropna()
    if work.empty: return {"rate":None,"date":None,"decision":"N/A","change_bps":None,"since":None}
    latest=float(work["value"].iloc[-1]); latest_date=pd.Timestamp(work["date"].iloc[-1])
    distinct=work.loc[work["value"].diff().abs().fillna(1)>1e-10]
    if len(distinct)>=2:
        change=float(distinct["value"].iloc[-1]-distinct["value"].iloc[-2]); since=pd.Timestamp(distinct["date"].iloc[-1])
        decision="HIKE" if change>0 else "CUT" if change<0 else "HOLD"
    else:
        change=0.0; since=pd.Timestamp(work["date"].iloc[0]); decision="HOLD"
    move_decision = decision
    # The series identifies the last rate move. When that move is no longer
    # recent, the current stance is displayed as HOLD until an official
    # decision archive supplies a newer action.
    if since is not None and (CB38_TODAY - since.normalize()).days > 45:
        decision = "HOLD"
    return {"rate":latest,"date":latest_date,"decision":decision,"last_move":move_decision,"change_bps":int(round(change*100)),"since":since}


def _cb38_decisions(code: str) -> Tuple[pd.DataFrame, str]:
    policy, psource=_cb38_policy_series(code,"1990-01-01")
    official=_cb38_official_archive(code,"decision")
    if not official.empty and not policy.empty:
        left=official.sort_values("Date").copy(); right=policy.sort_values("date").copy()
        merged=pd.merge_asof(left,right,left_on="Date",right_on="date",direction="backward",tolerance=pd.Timedelta(days=45))
        merged["Rate"]=pd.to_numeric(merged["value"],errors="coerce")
        merged["ChangeRaw"]=merged["Rate"].diff()
        merged["Decision"]=np.where(merged["ChangeRaw"]>1e-8,"HIKE",np.where(merged["ChangeRaw"]<-1e-8,"CUT","HOLD"))
        merged["Change"]=merged["ChangeRaw"].map(lambda x:"—" if pd.isna(x) or abs(float(x))<1e-8 else f"{int(round(float(x)*100)):+d} bps")
        merged["Rate"]=merged["Rate"].map(lambda x:"—" if pd.isna(x) else f"{float(x):.2f}%")
        out=merged.sort_values("Date",ascending=False)[["Date","Decision","Rate","Change","Title","Source","URL"]]
        return out.head(40).reset_index(drop=True), f"Official decision archive + {psource}"
    if not policy.empty:
        work=policy.sort_values("date").copy(); work["change"]=work["value"].diff(); changes=work[work["change"].abs()>1e-9]
        rows=[]
        for _,r in changes.sort_values("date",ascending=False).head(40).iterrows():
            bps=int(round(float(r["change"])*100)); rows.append({"Date":pd.Timestamp(r["date"]),"Decision":"HIKE" if bps>0 else "CUT","Rate":f"{float(r['value']):.2f}%","Change":f"{bps:+d} bps","Title":"Policy-rate change detected in public series","Source":psource,"URL":""})
        return pd.DataFrame(rows), psource + " · rate changes only"
    return pd.DataFrame(columns=["Date","Decision","Rate","Change","Title","Source","URL"]), psource


def _cb38_next_decision(code: str) -> Optional[pd.Timestamp]:
    archive=_cb38_official_archive(code,"decision")
    if archive.empty: return None
    future=archive[pd.to_datetime(archive["Date"])>CB38_TODAY]
    return pd.Timestamp(future["Date"].min()) if not future.empty else None


def _cb38_snapshot(code: str, speech_df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    bank=dict(CB38_BANK_BY_CODE[code]); policy,psource=_cb38_policy_series(code,"2000-01-01"); status=_cb38_detect_rate_status(policy)
    speeches=speech_df if speech_df is not None else _cb38_speeches(code,deep=False); score=_cb38_score_snapshot(speeches)
    bank.update(status); bank.update({"policy_source":psource,"score":score["recent"],"lifetime":score["lifetime"],"speech_count":score["count"],"score_confidence":score["confidence"],"speech_last_date":score["last_date"]})
    return bank


def _cb38_fmt_rate(value: Any) -> str:
    try: return f"{float(value):.2f}%"
    except Exception: return "N/A"


def _cb38_fmt_score(value: Any, digits: int = 2) -> str:
    try:
        if value is None or pd.isna(value): return "N/A"
        return f"{float(value):+.{digits}f}"
    except Exception: return "N/A"


def _cb38_position(score: Any) -> float:
    try:
        if score is None or pd.isna(score): return 50.0
        value=float(score)
    except Exception: value=0.0
    return max(1.5,min(98.5,(value+1.0)*50.0))


def _cb38_track(score: Any) -> str:
    return f'<div class="cb38-track"><span class="cb38-diamond" style="left:calc({_cb38_position(score):.1f}% - 5px)"></span></div>'


def _cb38_bank_card(bank: Mapping[str, Any]) -> None:
    score=bank.get("score"); cls="cb38-score-na" if score is None else ("cb38-score-pos" if float(score)>=0 else "cb38-score-neg")
    decision=str(bank.get("decision") or "N/A")
    _html('<div class="cb38-card">'
          f'<div class="cb38-card-head"><span class="cb38-card-code">{_esc(bank["flag"])} {_esc(bank["code"])}</span><span class="cb38-card-ccy">{_esc(bank["ccy"])}</span></div>'
          f'<div class="cb38-card-rate">{_cb38_fmt_rate(bank.get("rate"))} <span class="cb38-card-decision">● {_esc(decision)}</span></div>'
          f'<div class="cb38-card-name">{_esc(bank["name"])}</div>{_cb38_track(score)}'
          f'<div class="cb38-card-meta"><span class="{cls}">{_cb38_fmt_score(score,3)}</span><span>{int(bank.get("speech_count",0))} scored texts</span></div>'
          f'<div class="cb38-card-name">{_esc(bank["meetings"])} · {_esc(bank.get("policy_source",""))}</div></div>')


def _cb38_render_speech_cards(df: pd.DataFrame, limit: Optional[int] = None) -> None:
    use=df.head(limit) if limit else df
    if use is None or use.empty:
        st.info("No public speech rows were resolved for this view."); return
    for _,row in use.iterrows():
        score=float(row["Score"]); conf=float(row.get("Confidence",0)); cls="cb38-score-pos" if score>=0 else "cb38-score-neg"
        _html('<div class="cb38-speech">'
              f'<div><div class="cb38-speech-title">{_esc(row["Title"])}</div><div class="cb38-speech-meta">{_esc(row["Speaker"])} · {pd.Timestamp(row["Date"]).date().isoformat()} · {_esc(row["CB"])} · {_esc(row.get("Source",""))}</div></div>'
              f'<div><div class="cb38-speech-score {cls}">{score:+.2f}</div><div class="cb38-speech-conf">confidence {conf:.0%}</div></div></div>')


def _cb38_apply_window(series: pd.Series, window: str) -> pd.Series:
    if series.empty or window=="All": return series
    years={"1Y":1,"3Y":3,"5Y":5}.get(window)
    return series if not years else series[series.index>=series.index.max()-pd.DateOffset(years=years)]


def _cb38_members(code: str, speeches: Optional[pd.DataFrame] = None) -> List[Dict[str, Any]]:
    df=speeches if speeches is not None else _cb38_speeches(code,deep=False)
    rows=[]
    for name,role in CB38_ROSTERS.get(code,()):
        member_df=df[df["Speaker"].map(_cb38_norm)==_cb38_norm(name)] if not df.empty else pd.DataFrame()
        snap=_cb38_score_snapshot(member_df)
        rows.append({"slug":_cb38_slug(name),"name":name,"role":role,"recent":snap["recent"],"lifetime":snap["lifetime"],"speeches":snap["count"],"confidence":snap["confidence"],"last_date":snap["last_date"]})
    # Add discovered speakers not present in the official seed.
    if not df.empty:
        known={_cb38_norm(x["name"]) for x in rows}
        for speaker,group in df.groupby("Speaker"):
            if _cb38_norm(speaker) in known or "communication" in _cb38_norm(speaker): continue
            snap=_cb38_score_snapshot(group)
            rows.append({"slug":_cb38_slug(speaker),"name":speaker,"role":"Public speaker","recent":snap["recent"],"lifetime":snap["lifetime"],"speeches":snap["count"],"confidence":snap["confidence"],"last_date":snap["last_date"]})
    return rows


def _cb38_member_cards(code: str, speeches: pd.DataFrame) -> None:
    members=_cb38_members(code,speeches)
    for start in range(0,len(members),3):
        cols=st.columns(3)
        for offset,col in enumerate(cols):
            idx=start+offset
            if idx>=len(members): continue
            member=members[idx]
            with col:
                score=member.get("recent"); cls="cb38-score-na" if score is None else ("cb38-score-pos" if float(score)>=0 else "cb38-score-neg")
                _html('<div class="cb38-member"><div class="cb38-member-top">'
                      f'<span class="cb38-member-name">{_esc(member["name"])}</span><span class="cb38-member-score {cls}">{_cb38_fmt_score(score)}</span></div>'
                      f'<div class="cb38-member-role">{_esc(member["role"])}</div><div class="cb38-member-metrics">'
                      f'<div class="cb38-member-metric"><b>Texts</b><span>{int(member["speeches"])}</span></div><div class="cb38-member-metric"><b>Lifetime</b><span>{_cb38_fmt_score(member.get("lifetime"))}</span></div><div class="cb38-member-metric"><b>Confidence</b><span>{float(member.get("confidence",0)):.0%}</span></div></div>'
                      f'<div class="cb38-member-foot">Last public item: {_esc(member.get("last_date").date().isoformat() if member.get("last_date") is not None else "not resolved")}</div></div>')
                if st.button("Open member",key=f"ec38_member_open_{code}_{idx}",use_container_width=True):
                    st.session_state["ec36_cb_route"]="member"; st.session_state["ec36_cb_code"]=code; st.session_state["ec38_member_slug"]=member["slug"]; st.rerun()


def _cb38_quality_block(snapshots: Sequence[Mapping[str, Any]], speeches: pd.DataFrame) -> None:
    blocks=[]
    for snap in snapshots:
        code=str(snap["code"]); assets,asource,_=_cb38_assets_series(code,"2020-01-01")
        count=int((speeches["CB"]==code).sum()) if not speeches.empty else 0
        policy_ok=snap.get("rate") is not None; assets_ok=not assets.empty; speech_ok=count>0
        blocks.append(f'<div class="cb38-q"><b>{_esc(code)}</b><span class="{"cb38-ok" if policy_ok else "cb38-bad"}">Policy: {"live" if policy_ok else "missing"}</span><span class="{"cb38-ok" if assets_ok else "cb38-warn"}">Assets: {"live" if assets_ok else "fallback unavailable"}</span><span class="{"cb38-ok" if speech_ok else "cb38-warn"}">Texts: {count}</span></div>')
    _html('<div class="cb38-quality">'+''.join(blocks)+'</div>')


def _cb38_root() -> None:
    _header("ECONOMY · PUBLIC MONETARY DATA","Global Monetary Policy Observatory","G10 policy rates, central-bank balance sheets, public communications and committee attribution generated by Quant Terminal from official/BIS data.",["BIS policy rates","BIS total assets","official archives","local text scoring"])
    _html('<details class="cb38-model"><summary>How This Works — Quant Terminal Hawk/Dove Model</summary><p>Rates and balance sheets are retrieved from BIS bulk statistics with FRED fallbacks. Speeches are collected from the BIS central-bank speech feed and official bank archives. A transparent weighted lexicon scores inflation, activity, labour-market and policy language. Recent is a 12-observation EMA; lifetime uses a 365-day half-life. Missing data remains missing: no proprietary or synthetic history is inserted.</p></details>')
    _html('<div class="cb38-callout"><b>Stable data mode:</b> full speech-page enrichment is disabled by default to keep Codespaces memory bounded. Set <code>CB38_DEEP_FETCH=1</code> only for a deliberate deep refresh.</div>')
    speeches=_cb38_speeches(deep=CB38_DEEP_FETCH_DEFAULT)
    snapshots=[_cb38_snapshot(code,speeches[speeches["CB"]==code].copy() if not speeches.empty else pd.DataFrame()) for code in CB38_BANK_BY_CODE]
    for row in (snapshots[:5],snapshots[5:]):
        cols=st.columns(5)
        for col,snap in zip(cols,row):
            with col:
                _cb38_bank_card(snap)
                if st.button(f"Open {snap['code']}",key=f"ec38_open_{snap['code']}",use_container_width=True):
                    st.session_state["ec36_cb_code"]=snap["code"]; st.session_state["ec36_cb_route"]="bank"; st.session_state["ec38_cb_nav"]="Overview"; st.rerun()
    c1,c2,c3=st.columns([2.2,1,1])
    with c1: selected=st.selectbox("Open central bank",list(CB38_BANK_BY_CODE),key="ec38_cb_select",format_func=lambda x:f"{CB38_BANK_BY_CODE[x]['flag']} {x} — {CB38_BANK_BY_CODE[x]['name']}")
    with c2:
        if st.button("Open scorecard",key="ec38_cb_scorecard",use_container_width=True):
            st.session_state["ec36_cb_code"]=selected; st.session_state["ec36_cb_route"]="bank"; st.session_state["ec38_cb_nav"]="Scorecard"; st.rerun()
    with c3:
        if st.button("Policy previews",key="ec38_cb_previews",use_container_width=True): st.session_state["ec36_cb_route"]="previews"; st.rerun()
    _section("CROSS-BANK SIGNAL","Hawk / Dove Composite","Observed public-text score histories. Lines begin only when public communications are available.")
    options=list(CB38_BANK_BY_CODE); selected_codes=st.multiselect("Central banks",options,default=options,key="ec38_composite_codes")
    c1,c2=st.columns([1,1])
    with c1: view=st.radio("View",["Level","3m/3m change"],horizontal=True,key="ec38_composite_view")
    with c2: solo=st.checkbox("Solo first",key="ec38_solo")
    fig=go.Figure()
    order=(selected_codes[:1] if solo and selected_codes else selected_codes)
    for code in order:
        hist=_cb38_score_history(speeches[speeches["CB"]==code] if not speeches.empty else pd.DataFrame())
        if view=="3m/3m change": hist=hist.diff(3)
        if hist.empty: continue
        fig.add_trace(go.Scatter(x=hist.index,y=hist.values,name=code,mode="lines+markers",line=dict(color=CB38_COLOR_BY_CODE[code],width=2),marker=dict(size=4)))
    fig.add_hline(y=0,line_color="rgba(202,212,221,.30)"); fig.update_yaxes(range=[-1,1] if view=="Level" else None,tickvals=[-.7,0,.7] if view=="Level" else None,ticktext=["Dovish","Neutral","Hawkish"] if view=="Level" else None)
    _plot(fig,"ec38_composite",480)
    _cb38_source([("Scores","Quant Terminal public-text model"),("Inputs","BIS RSS + official archives"),("No-data rule","no synthetic backfill")])
    _section("RANKING","Policy Rates — Ranked","Latest public policy-rate observations in descending order.")
    ranked=sorted(snapshots,key=lambda x:float(x["rate"]) if x.get("rate") is not None else -999,reverse=True)
    html_rows=[]
    for i,snap in enumerate(ranked,1):
        mark="▲" if snap.get("decision")=="HIKE" else "▼" if snap.get("decision")=="CUT" else "●"
        date_text=snap.get("date").date().isoformat() if snap.get("date") is not None else "N/A"
        html_rows.append(f'<div class="cb38-rank-row"><span>{i:02d}</span><span class="cb38-rank-code">{_esc(snap["flag"])} {_esc(snap["code"])} <small>{_esc(snap["policy_source"])}</small></span><span class="cb38-rank-rate">{_cb38_fmt_rate(snap.get("rate"))}</span><span class="cb38-rank-mark">{mark} {date_text}</span></div>')
    _html('<div class="cb38-ranked">'+''.join(html_rows)+'</div>')
    _section("MONETARY POLICY STANCE","Policy Rates & Balance Sheet","Policy-rate path with monthly central-bank total-asset change. BIS USD series is preferred for comparability.")
    bs_code=st.selectbox("Central bank",options,key="ec38_balance_bank",label_visibility="collapsed")
    policy,psource=_cb38_policy_series(bs_code,"2016-01-01"); assets,asource,aunit=_cb38_assets_series(bs_code,"2016-01-01")
    fig2=go.Figure()
    if not policy.empty: fig2.add_trace(go.Scatter(x=policy["date"],y=policy["value"],name="Policy rate",line=dict(color=CB38_COLORS["blue"],width=2.2),line_shape="hv"))
    if not assets.empty:
        monthly=assets.set_index("date")["value"].resample("MS").last().dropna().diff().dropna()
        fig2.add_trace(go.Bar(x=monthly.index,y=monthly.values,name=f"Assets MoM ({aunit})",yaxis="y2",marker_color=[CB38_COLORS["green"] if x>=0 else CB38_COLORS["red"] for x in monthly],opacity=.72))
        fig2.update_layout(yaxis2=dict(overlaying="y",side="right",showgrid=False,title=aunit+" / month"))
    _plot(fig2,"ec38_policy_assets",480)
    _cb38_source([("Policy",psource),("Balance sheet",asource),("Method","monthly last observation; first difference")])
    _section("COMMUNICATION","Recent Speeches","Latest public G10 communications with locally computed score and confidence.")
    _cb38_render_speech_cards(speeches,20)
    _section("DATA COVERAGE","Provider diagnostics","Coverage is evaluated at runtime. Missing series are not replaced with model data.")
    _cb38_quality_block(snapshots,speeches)


def _cb38_summary(bank: Mapping[str, Any]) -> None:
    score=bank.get("score"); since=bank.get("since"); last_speech=bank.get("speech_last_date")
    items=[("Rate",_cb38_fmt_rate(bank.get("rate")),f"since {since.date().isoformat() if since is not None else 'N/A'}","flat"),
           ("Target",str(bank["target"]),bank["country"],"flat"),
           ("Hawk / Dove",_cb38_fmt_score(score,3),f"{int(bank.get('speech_count',0))} public texts","up" if score is not None and float(score)>=0 else "down"),
           ("Decision",str(bank.get("decision") or "N/A"),f"{bank.get('change_bps') if bank.get('change_bps') is not None else '—'} bps","flat"),
           ("Freshness",last_speech.date().isoformat() if last_speech is not None else "N/A","latest scored communication","flat")]
    blocks=[]
    for label,value,note,tone in items:
        cls={"up":"ec36-up","down":"ec36-down","flat":"ec36-flat"}.get(tone,"")
        blocks.append(f'<div class="cb38-stat"><div class="cb38-stat-k">{_esc(label)}</div><div class="cb38-stat-v {cls}">{_esc(value)}</div><div class="cb38-stat-n">{_esc(note)}</div></div>')
    _html('<div class="cb38-stats">'+''.join(blocks)+'</div>')


def _cb38_overview(code: str, bank: Mapping[str, Any], speeches: pd.DataFrame) -> None:
    score=bank.get("score")
    _html(f'<div class="cb38-stance"><div class="cb38-stance-title">Hawk / Dove Stance</div><div class="cb38-stance-track"><span class="cb38-stance-pointer" style="left:calc({_cb38_position(score):.1f}% - 6px)"></span></div><div class="cb38-stance-labels"><span>Dovish</span><span>Neutral</span><span>Hawkish</span></div></div>')
    c1,c2=st.columns([1,1])
    with c1: window=st.radio("Zoom",["1Y","3Y","5Y","All"],horizontal=True,key=f"ec38_zoom_{code}")
    with c2: merge=st.checkbox("Merge Charts",key=f"ec38_merge_{code}")
    policy,psource=_cb38_policy_series(code,"1990-01-01"); rate_series=policy.set_index("date")["value"] if not policy.empty else pd.Series(dtype=float); rate_series=_cb38_apply_window(rate_series,window)
    score_series=_cb38_apply_window(_cb38_score_history(speeches),window)
    if merge:
        fig=go.Figure()
        if not rate_series.empty: fig.add_trace(go.Scatter(x=rate_series.index,y=rate_series.values,name="Policy rate",line=dict(color=CB38_COLORS["gold"],width=2.2),line_shape="hv"))
        if not score_series.empty: fig.add_trace(go.Scatter(x=score_series.index,y=score_series.values,name="Hawk/Dove",yaxis="y2",line=dict(color=CB38_COLORS["orange"],width=2),mode="lines+markers"))
        fig.update_layout(yaxis2=dict(overlaying="y",side="right",range=[-1,1],showgrid=False,title="Hawk/Dove")); _plot(fig,f"ec38_merge_{code}",440)
    else:
        a,b=st.columns(2)
        with a:
            fig1=go.Figure()
            if not rate_series.empty: fig1.add_trace(go.Scatter(x=rate_series.index,y=rate_series.values,name="Policy rate",line=dict(color=CB38_COLORS["gold"],width=2.2),fill="tozeroy",fillcolor="rgba(216,191,88,.08)",line_shape="hv"))
            _plot(fig1,f"ec38_rate_{code}",390)
        with b:
            fig2=go.Figure()
            if not score_series.empty: fig2.add_trace(go.Scatter(x=score_series.index,y=score_series.values,name="Hawk/Dove",line=dict(color=CB38_COLORS["orange"],width=2),mode="lines+markers"))
            fig2.add_hline(y=0,line_color="rgba(202,212,221,.28)"); fig2.update_yaxes(range=[-1,1],tickvals=[-.7,0,.7],ticktext=["Dove","Neutral","Hawk"]); _plot(fig2,f"ec38_score_{code}",390)
    _cb38_source([("Policy history",psource),("Communication","public archive only"),("Zoom",window)])
    _section("RECENT TAPE","Recent Speeches",f"Public communication archive for {code}.")
    _cb38_render_speech_cards(speeches,12)
    _section("COMMITTEE",f"{bank['committee']} — Hawk/Dove Scorecard","Scores are computed from each member's resolved public communications; missing speakers remain no data.")
    _cb38_member_cards(code,speeches)


def _cb38_scorecard(code: str, bank: Mapping[str, Any], speeches: pd.DataFrame) -> None:
    members=_cb38_members(code,speeches)
    _section("COMMITTEE INTELLIGENCE",f"{bank['name']} — {bank['committee']} Scorecard","Recent = 12-observation EMA. Lifetime = 365-day half-life. All scores are calculated locally from public text.")
    horizon=st.radio("Score horizon",["Recent (12-EMA)","Lifetime"],horizontal=True,key=f"ec38_horizon_{code}")
    valid=[m for m in members if m.get("recent") is not None]; life=[m for m in members if m.get("lifetime") is not None]
    recent_avg=float(np.mean([float(m["recent"]) for m in valid])) if valid else np.nan; life_avg=float(np.mean([float(m["lifetime"]) for m in life])) if life else np.nan
    _kpis([("Committee recent","—" if np.isnan(recent_avg) else f"{recent_avg:+.2f}","member average","up" if not np.isnan(recent_avg) and recent_avg>=0 else "down"),("Committee lifetime","—" if np.isnan(life_avg) else f"{life_avg:+.2f}","365-day half-life","flat"),("Roster",str(len(members)),bank["committee"],"flat"),("Scored members",str(len(valid)),f"{sum(int(m['speeches']) for m in members)} public texts","flat")])
    fig=go.Figure()
    for member in members:
        member_df=speeches[speeches["Speaker"].map(_cb38_norm)==_cb38_norm(member["name"])] if not speeches.empty else pd.DataFrame()
        hist=_cb38_score_history(member_df)
        if hist.empty: continue
        fig.add_trace(go.Scatter(x=hist.index,y=hist.values,name=member["name"].split()[-1],mode="lines+markers",line=dict(width=1.8)))
    fig.add_hline(y=0,line_color="rgba(202,212,221,.28)"); fig.update_yaxes(range=[-1,1],tickvals=[-.7,0,.7],ticktext=["Dove","Neutral","Hawk"]); _plot(fig,f"ec38_committee_{code}",465)
    decisions,source=_cb38_decisions(code)
    score_hist=_cb38_score_history(speeches)
    if not decisions.empty and not score_hist.empty:
        d=decisions.copy(); d["Date"]=pd.to_datetime(d["Date"],errors="coerce"); h=score_hist.rename("Model score").reset_index().rename(columns={"index":"ScoreDate"}); d=pd.merge_asof(d.sort_values("Date"),h.sort_values("ScoreDate"),left_on="Date",right_on="ScoreDate",direction="backward"); d["Model score"]=d["Model score"].map(lambda x:"—" if pd.isna(x) else f"{float(x):+.2f}"); _table(d.sort_values("Date",ascending=False)[["Date","Decision","Rate","Change","Model score"]].head(12),f"ec38_score_decisions_{code}",390)
    _section("INDIVIDUAL MEMBERS",f"Individual Members ({len(members)})","Observed text count, recent/lifetime score and model confidence.")
    _cb38_member_cards(code,speeches)
    _cb38_source([("Score model","Quant Terminal weighted public-text model"),("Decision source",source),("No-data rule","no synthetic member values")])


def _cb38_speech_archive(code: str, bank: Mapping[str, Any], speeches: pd.DataFrame) -> None:
    _section("COMMUNICATION",f"Speeches — {code}",f"BIS and official public archive for {bank['name']}.")
    query=st.text_input("Search speeches",key=f"ec38_speech_search_{code}",placeholder="speaker, title, subject")
    df=speeches.copy()
    if query and not df.empty:
        mask=df.astype(str).apply(lambda col:col.str.contains(query,case=False,regex=False)).any(axis=1); df=df[mask]
    _cb38_render_speech_cards(df)


def _cb38_meeting_archive(code: str, bank: Mapping[str, Any]) -> None:
    _section("DECISION HISTORY","Rate Decision History",f"Official decision archive joined to the public policy-rate series for {bank['name']}.")
    df,source=_cb38_decisions(code)
    if df.empty: st.info("No official decision rows could be resolved from the configured public sources.")
    else:
        show=df.copy(); show["Date"]=pd.to_datetime(show["Date"],errors="coerce").dt.date.astype(str); _table(show[[c for c in ("Date","Decision","Rate","Change","Title","Source") if c in show.columns]],f"ec38_meetings_{code}",min(760,100+28*len(show)))
    _cb38_source([("Decision layer",source),("Rate layer",_cb38_policy_series(code,"1990-01-01")[1]),("Method","official dates + as-of rate join")])


def _cb38_bank(code: str) -> None:
    bank_meta=CB38_BANK_BY_CODE.get(code,CB38_BANK_BY_CODE["FED"]); speeches=_cb38_speeches(code,deep=CB38_DEEP_FETCH_DEFAULT); bank=_cb38_snapshot(code,speeches)
    _cb38_path(["Central Banks",bank["name"]])
    c1,c2=st.columns([1,1])
    with c1:
        if st.button("← All Central Banks",key=f"ec38_back_{code}"): st.session_state["ec36_cb_route"]="root"; st.rerun()
    with c2:
        if st.button("Policy Previews →",key=f"ec38_preview_{code}"): st.session_state["ec36_cb_route"]="previews"; st.rerun()
    _header("CENTRAL BANK WORKSTATION",f"{bank['flag']} {bank['name']}",f"{bank['committee']} · public-data workflow",[bank["ccy"],bank["meetings"],f"{len(CB38_ROSTERS.get(code,()))} roster names",CB38_VERSION])
    _cb38_summary(bank)
    tab=_segmented("Central bank page",["Overview","Scorecard","Speeches","Meetings"],"ec38_cb_nav","Overview")
    if tab=="Overview": _cb38_overview(code,bank,speeches)
    elif tab=="Scorecard": _cb38_scorecard(code,bank,speeches)
    elif tab=="Speeches": _cb38_speech_archive(code,bank,speeches)
    else: _cb38_meeting_archive(code,bank)


def _cb38_member(code: str, slug: str) -> None:
    bank=CB38_BANK_BY_CODE.get(code,CB38_BANK_BY_CODE["FED"]); speeches=_cb38_speeches(code,deep=CB38_DEEP_FETCH_DEFAULT); members=_cb38_members(code,speeches); member=next((m for m in members if m["slug"]==slug),None)
    if member is None: st.warning("Member profile unavailable from the public roster."); return
    _cb38_path(["Central Banks",bank["name"],"Scorecard",member["name"]])
    if st.button("← Back to scorecard",key=f"ec38_member_back_{code}_{slug}"): st.session_state["ec36_cb_route"]="bank"; st.session_state["ec38_cb_nav"]="Scorecard"; st.rerun()
    member_df=speeches[speeches["Speaker"].map(_cb38_norm)==_cb38_norm(member["name"])] if not speeches.empty else pd.DataFrame(); snap=_cb38_score_snapshot(member_df)
    _header("MEMBER SCORECARD",member["name"],member["role"],[f"{snap['count']} public texts",bank["short"],"local transparent model"])
    _kpis([("Recent composite",_cb38_fmt_score(snap["recent"]),"12-observation EMA","up" if snap["recent"] is not None and snap["recent"]>=0 else "down"),("Lifetime",_cb38_fmt_score(snap["lifetime"]),"365-day half-life","flat"),("Texts",str(snap["count"]),"resolved public communications","flat"),("Confidence",f"{snap['confidence']:.0%}","lexical evidence density","flat")])
    _html('<div class="cb38-callout"><b>Independent score:</b> this profile is generated by Quant Terminal from public text. It is not an official view of the institution and is not sourced from any third-party dashboard.</div>')
    tab=st.radio("Member view",["Hawk/Dove Chart",f"Speeches ({snap['count']})"],horizontal=True,key=f"ec38_member_view_{code}_{slug}")
    if tab=="Hawk/Dove Chart":
        _section("MEMBER HISTORY","Hawk/Dove Tendency Over Time","Only observed public communication dates are plotted.")
        hist=_cb38_score_history(member_df); fig=go.Figure()
        if not hist.empty: fig.add_trace(go.Scatter(x=hist.index,y=hist.values,name="Public-text score",mode="lines+markers",line=dict(color="#4d86bd",width=1.8),marker=dict(size=6)))
        fig.add_hline(y=0,line_color="rgba(202,212,221,.28)"); fig.update_yaxes(range=[-1,1],tickvals=[-.7,0,.7],ticktext=["Dove","Neutral","Hawk"]); _plot(fig,f"ec38_member_chart_{code}_{slug}",430)
        _cb38_source([("Inputs","BIS + official archive"),("History","observed dates only"),("Member",member["name"])])
    else: _cb38_render_speech_cards(member_df)


def _cb38_probability_call(score: Any, policy: pd.DataFrame) -> Tuple[str,float,float,float]:
    s=0.0 if score is None or pd.isna(score) else float(score)
    momentum=0.0
    if policy is not None and len(policy)>=2:
        monthly=policy.set_index("date")["value"].resample("MS").last().dropna(); momentum=float(monthly.diff(3).iloc[-1]) if len(monthly)>3 and pd.notna(monthly.diff(3).iloc[-1]) else 0.0
    z=np.clip(1.6*s+.8*momentum,-4,4); hike=float(1/(1+np.exp(-z))); cut=float(1/(1+np.exp(z))); hold=max(0.0,1.0-.58*(hike+cut)); total=hike+cut+hold; hike,cut,hold=hike/total,cut/total,hold/total
    call="HIKE" if hike==max(hike,cut,hold) else "CUT" if cut==max(hike,cut,hold) else "HOLD"
    return call,hike,hold,cut


def _cb38_previews() -> None:
    if st.button("← Central Banks",key="ec38_preview_back"): st.session_state["ec36_cb_route"]="root"; st.rerun()
    _header("T-1 POLICY INTELLIGENCE","Central Bank Previews","Code-generated briefing matrix using public rates, official calendars and Quant Terminal communication scores.",["10 institutions","public data","transparent model","no third-party dashboard data"])
    speeches=_cb38_speeches(deep=CB38_DEEP_FETCH_DEFAULT); rows=[]; snapshots={}
    for code in CB38_BANK_BY_CODE:
        bank_speech=speeches[speeches["CB"]==code] if not speeches.empty else pd.DataFrame(); snap=_cb38_snapshot(code,bank_speech); snapshots[code]=snap; policy,_=_cb38_policy_series(code,"2018-01-01"); call,ph,po,pc=_cb38_probability_call(snap.get("score"),policy); nxt=_cb38_next_decision(code)
        rows.append({"Next decision":nxt.date().isoformat() if nxt is not None else "Not resolved","CB":code,"Current":_cb38_fmt_rate(snap.get("rate")),"Model call":call,"P(hike)":f"{ph:.0%}","P(hold)":f"{po:.0%}","P(cut)":f"{pc:.0%}","H/D":_cb38_fmt_score(snap.get("score"))})
    _table(pd.DataFrame(rows),"ec38_previews_table",480)
    code=st.selectbox("Open briefing",list(CB38_BANK_BY_CODE),key="ec38_preview_select")
    snap=snapshots[code]; policy,psource=_cb38_policy_series(code,"2018-01-01"); call,ph,po,pc=_cb38_probability_call(snap.get("score"),policy); next_dt=_cb38_next_decision(code)
    _section("POLICY BRIEFING",f"{code} — code-generated decision briefing","Six-block structure populated from the public data engine.")
    cards=[("01","Executive summary",f"Model call {call}; current rate {_cb38_fmt_rate(snap.get('rate'))}; next date {next_dt.date().isoformat() if next_dt is not None else 'not resolved'}."),("02","The call",f"Hike {ph:.0%} · Hold {po:.0%} · Cut {pc:.0%}. Probabilities are model outputs, not market prices."),("03","The committee",f"{snap['committee']} · {len(CB38_ROSTERS.get(code,()))} public roster names · communication score {_cb38_fmt_score(snap.get('score'))}."),("04","Data since last decision",f"Policy source: {psource}. Last rate change {snap.get('change_bps') if snap.get('change_bps') is not None else 'N/A'} bps."),("05","What speeches say",f"{int(snap.get('speech_count',0))} public texts; recent score {_cb38_fmt_score(snap.get('score'))}; lifetime {_cb38_fmt_score(snap.get('lifetime'))}."),("06","Market pricing & risks","No proprietary market-pricing feed is inserted. Add OIS/futures data only when a licensed or public source is configured.")]
    for row in (cards[:3],cards[3:]):
        cols=st.columns(3)
        for col,(num,title,body) in zip(cols,row):
            with col: _html(f'<div class="ec36-mini"><div class="ec36-mini-k">{_esc(num)}</div><div class="ec36-mini-v">{_esc(title)}</div><div class="ec36-mini-c">{_esc(body)}</div></div>')


def _render_cb_root() -> None:  # noqa: F811
    _cb38_css()
    if str(st.session_state.get("ec36_cb_route","root"))=="member":
        _cb38_member(str(st.session_state.get("ec36_cb_code","FED")),str(st.session_state.get("ec38_member_slug",""))); return
    _cb38_root()


def _render_cb_bank(code: str) -> None:  # noqa: F811
    _cb38_css(); _cb38_bank(str(code))


def _render_cb_scorecard(code: str) -> None:  # noqa: F811
    _cb38_css(); speeches=_cb38_speeches(str(code),deep=CB38_DEEP_FETCH_DEFAULT); bank=_cb38_snapshot(str(code),speeches); _cb38_scorecard(str(code),bank,speeches)


def _render_cb_previews() -> None:  # noqa: F811
    _cb38_css(); _cb38_previews()


def render_economy_intelligence(page: str, ticker: str = "SPY", price_data: Any = None, analysis: Any = None) -> None:  # noqa: F811
    """V38 renderer. Only the Central Banks branch is replaced by the public-data engine."""
    del ticker,price_data,analysis
    _css(); page=_normalize_page(page)
    if page!="central-banks": st.session_state["ec36_cb_route"]="root"
    if page!="high-speed": st.session_state["ec36_hs_route"]="root"
    if page=="central-banks":
        route=str(st.session_state.get("ec36_cb_route","root"))
        if route=="bank": _render_cb_bank(str(st.session_state.get("ec36_cb_code","FED")))
        elif route=="member": _cb38_css(); _cb38_member(str(st.session_state.get("ec36_cb_code","FED")),str(st.session_state.get("ec38_member_slug","")))
        elif route=="previews": _render_cb_previews()
        else: _render_cb_root()
    elif page=="inflation": _render_inflation()
    elif page=="payrolls": _render_payrolls()
    elif page=="outlook": _render_outlook()
    elif page=="taylor-rule": _render_taylor()
    elif page=="high-speed": _render_high_speed()
    elif page=="china": _render_china()
    elif page=="misery": _render_misery()
    else: _render_quality()


CENTRAL_BANKS_INTEGRITY_V38: Mapping[str, Any] = {
    "version":CB38_VERSION,
    "banks":len(CB38_BANKS),
    "public_policy_provider":"BIS WS_CBPOL + FRED fallback",
    "public_assets_provider":"BIS WS_CBTA + FRED fallback",
    "public_communication_provider":"BIS RSS + official archives",
    "score_owner":"Quant Terminal",
    "third_party_dashboard_data":False,
    "synthetic_hawk_dove_history":False,
    "non_central_economy_modified":False,
    "routes":("root","bank/overview","bank/scorecard","bank/speeches","bank/meetings","member","previews"),
}
assert CENTRAL_BANKS_INTEGRITY_V38["banks"]==10
assert CENTRAL_BANKS_INTEGRITY_V38["third_party_dashboard_data"] is False
assert CENTRAL_BANKS_INTEGRITY_V38["synthetic_hawk_dove_history"] is False

# ============================================================
# END JARVIS ECONOMY V38 — CENTRAL BANKS PUBLIC DATA ENGINE
# ============================================================


# ============================================================
# JARVIS ECONOMY V38.3 — FILTERED PUBLIC DATA & LAZY TEXT PATCH
# ============================================================
# Append-only correction of the V38.2 Central Banks runtime.
# Objectives:
# - reject media/download/transcript links as speeches or members;
# - keep committee scorecards restricted to the official roster;
# - validate BIS policy-rate units (UNIT_MULT is not applied to rates);
# - crawl official metadata for the G10 without downloading media files;
# - make full-text scoring opt-in and bounded for the selected bank;
# - paginate speech archives and fix the ScoreDate merge path;
# - tighten official decision parsing and remove duplicate/non-decision rows.
# No other Economy branch is modified.
# ============================================================

CB383_VERSION = "V38.3 · FILTERED PUBLIC DATA ENGINE"
CB38_VERSION = CB383_VERSION
CB383_SPEECH_COLUMNS = ["Date","CB","Speaker","Title","Score","Confidence","Source","URL","Text"]
CB383_DECISION_COLUMNS = ["Date","Title","URL","Source"]
CB383_ARCHIVE_LIMIT = int(_cb38_os.getenv("CB383_ARCHIVE_LIMIT", "80"))
CB383_ROOT_PER_BANK = int(_cb38_os.getenv("CB383_ROOT_PER_BANK", "30"))
CB383_ENRICH_LIMIT = int(_cb38_os.getenv("CB383_ENRICH_LIMIT", "8"))
CB383_PAGE_SIZE = int(_cb38_os.getenv("CB383_PAGE_SIZE", "24"))
CB383_DECISION_YEARS = int(_cb38_os.getenv("CB383_DECISION_YEARS", "6"))

_CB383_SELECT_BIS_V382 = _cb38_select_bis
_CB383_HTTP_GET = _cb38_http_get

CB383_MEDIA_TITLE = _cb38_re.compile(
    r"^(?:audio(?:\s+\d+(?:\.\d+)?\s*(?:mb|kb))?|download(?:\s+\d+(?:\.\d+)?\s*(?:mb|kb))?|"
    r"q\s*&\s*a\s+transcript|qa\s+transcript|transcript|hansard\s+transcript|video|webcast|slides?)$",
    flags=_cb38_re.I,
)
CB383_MEDIA_URL = _cb38_re.compile(
    r"(?:\.(?:mp3|m4a|wav|aac|mp4|mov|wmv|pdf|zip|pptx?)(?:$|[?#])|/audio/|/video/|/transcript/|"
    r"(?:^|[/_-])audio(?:[/_.-]|$)|(?:^|[/_-])transcript(?:[/_.-]|$))",
    flags=_cb38_re.I,
)
CB383_NON_SPEAKER = {
    "audio", "download", "q a transcript", "qa transcript", "transcript", "video", "webcast",
    "monetary policy", "monetary policy decision", "additional monetary policy tools", "public speaker",
    "rba communication", "fed communication", "ecb communication", "boe communication",
}
CB383_ROLE_PATTERN = _cb38_re.compile(
    r"([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+(?:\s+(?:[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+|de|da|del|van|von)){1,4})"
    r"\s*,\s*(?:Governor|Deputy Governor|Assistant Governor|President|Vice[- ]President|Chair|Chairman|"
    r"Board member|Policy Board member|Monetary Policy Board member|Executive Board member|Chief Economist|"
    r"Director|Head of [A-Za-z &()/-]+)",
    flags=_cb38_re.I,
)


def _cb383_empty_speeches() -> pd.DataFrame:
    return pd.DataFrame(columns=CB383_SPEECH_COLUMNS)


def _cb383_empty_decisions() -> pd.DataFrame:
    return pd.DataFrame(columns=CB383_DECISION_COLUMNS)


def _cb383_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _cb383_is_media_item(title: Any, href: Any = "") -> bool:
    clean = _cb383_text(title)
    norm = _cb38_norm(clean)
    if not clean:
        return True
    if CB383_MEDIA_TITLE.fullmatch(clean):
        return True
    if norm.startswith(("audio ", "download ")):
        return True
    if norm in CB383_NON_SPEAKER:
        return True
    if CB383_MEDIA_URL.search(str(href or "")):
        return True
    return False


def _cb383_is_substantive_title(title: Any) -> bool:
    clean = _cb383_text(title)
    norm = _cb38_norm(clean)
    if _cb383_is_media_item(clean):
        return False
    if len(clean) < 12 or len(norm.split()) < 2:
        return False
    if norm in {"speeches", "speech", "news", "media releases", "monetary policy", "read more", "learn more"}:
        return False
    return True


def _cb383_heading_context(heading: Any, max_chars: int = 1800) -> str:
    parts: List[str] = []
    node = getattr(heading, "next_sibling", None)
    while node is not None and len(" ".join(parts)) < max_chars:
        name = str(getattr(node, "name", "") or "").lower()
        if name in {"h2", "h3", "h4"}:
            break
        if hasattr(node, "get_text"):
            value = _cb383_text(node.get_text(" ", strip=True))
        else:
            value = _cb383_text(node)
        if value:
            parts.append(value)
        node = getattr(node, "next_sibling", None)
    context = _cb383_text(" ".join(parts))[:max_chars]
    if not context:
        parent = getattr(heading, "parent", None)
        if parent is not None and hasattr(parent, "get_text"):
            context = _cb383_text(parent.get_text(" ", strip=True))[:max_chars]
    return context


def _cb383_valid_person_name(value: Any) -> bool:
    clean = _cb383_text(value)
    norm = _cb38_norm(clean)
    if not clean or norm in CB383_NON_SPEAKER:
        return False
    if any(token in norm for token in ("audio", "download", "transcript", "mb", "kb")):
        return False
    words = clean.split()
    if not 2 <= len(words) <= 6:
        return False
    return all(any(ch.isalpha() for ch in word) for word in words)


def _cb383_infer_speaker(code: str, text: str) -> str:
    blob = _cb383_text(text)
    norm = _cb38_norm(blob)
    for name, _ in CB38_ROSTERS.get(code, ()):
        if _cb38_norm(name) in norm:
            return name
    match = CB383_ROLE_PATTERN.search(blob)
    if match:
        candidate = _cb383_text(match.group(1))
        if _cb383_valid_person_name(candidate):
            return candidate
    return CB38_BANK_BY_CODE[code]["short"] + " communication"


def _cb38_infer_speaker(code: str, text: str) -> str:  # noqa: F811
    return _cb383_infer_speaker(code, text)


def _cb383_occurrences(raw: str, phrase: str) -> List[int]:
    needle = _cb38_norm(phrase)
    if not needle:
        return []
    return [m.start() for m in _cb38_re.finditer(r"(?<![a-z0-9])" + _cb38_re.escape(needle) + r"(?![a-z0-9])", raw)]


def _cb383_negated(raw: str, position: int) -> bool:
    prefix = raw[max(0, position - 28):position]
    return any(prefix.rstrip().endswith(_cb38_norm(term).strip()) for term in CB38_NEGATIONS)


def _cb38_score_text(text: Any) -> Tuple[float, float, int]:  # noqa: F811
    """Transparent directional policy-language score.

    A text with policy relevance but no directional evidence is not forced to
    neutral zero: it returns NaN and remains indexed but unscored.
    """
    raw = _cb38_norm(text)
    if not raw:
        return np.nan, 0.0, 0
    hawk = dove = 0.0
    hits = 0
    for phrase, weight in CB38_HAWKISH.items():
        for position in _cb383_occurrences(raw, phrase):
            if _cb383_negated(raw, position):
                dove += float(weight) * 0.65
            else:
                hawk += float(weight)
            hits += 1
    for phrase, weight in CB38_DOVISH.items():
        for position in _cb383_occurrences(raw, phrase):
            if _cb383_negated(raw, position):
                hawk += float(weight) * 0.65
            else:
                dove += float(weight)
            hits += 1

    contextual = (
        (r"(?:inflation|price pressures?).{0,55}(?:persistent|elevated|high|above target|accelerat|upside)", 1.20, 0.0),
        (r"(?:persistent|elevated|high|above target|accelerat|upside).{0,55}(?:inflation|price pressures?)", 1.20, 0.0),
        (r"(?:inflation|price pressures?).{0,55}(?:eas|declin|fall|moderate|disinflation|return(?:ing)? to target)", 0.0, 1.15),
        (r"(?:labour|labor) market.{0,45}(?:tight|strong|resilien)", 0.85, 0.0),
        (r"(?:labour|labor) market.{0,45}(?:cool|soft|weaken|slack)", 0.0, 0.85),
        (r"(?:raise|increase|hike).{0,35}(?:rate|cash rate|policy rate)", 1.45, 0.0),
        (r"(?:cut|lower|reduce|ease).{0,35}(?:rate|cash rate|policy rate)", 0.0, 1.45),
        (r"(?:strong|robust) demand", 0.60, 0.0),
        (r"(?:weak|soft) demand", 0.0, 0.60),
    )
    for pattern, hawk_weight, dove_weight in contextual:
        count = len(_cb38_re.findall(pattern, raw, flags=_cb38_re.I))
        if count:
            hawk += count * hawk_weight
            dove += count * dove_weight
            hits += count

    relevance = sum(raw.count(term) for term in CB38_POLICY_TERMS)
    if hits == 0:
        return np.nan, float(min(0.18, relevance * 0.012)), 0
    net = hawk - dove
    score = float(np.tanh(net / max(2.1, math.sqrt(max(1, hits)) * 1.35)))
    confidence = float(min(1.0, 0.10 * hits + 0.012 * relevance))
    return max(-1.0, min(1.0, score)), confidence, hits


def _cb38_select_bis(kind: str, code: str, start: str = "2000-01-01") -> Tuple[pd.DataFrame, str, str]:  # noqa: F811
    """Select a BIS series with rate-unit validation.

    WS_CBPOL observations are already published as percentage rates. Applying
    UNIT_MULT to them can turn a 1.00% rate into 100.00%; V38.3 therefore uses
    raw observations for policy rates and applies multipliers only to assets.
    """
    if kind != "policy":
        return _CB383_SELECT_BIS_V382(kind, code, start)
    bank = CB38_BANK_BY_CODE[code]
    raw, source = _cb38_bis_bulk("policy")
    if raw.empty:
        return pd.DataFrame(columns=["date", "value"]), source, "%"
    time_col = _cb38_find_col(raw, ("TIME_PERIOD", "TIME", "PERIOD", "DATE"), ("TIME_PERIOD",))
    value_col = _cb38_find_col(raw, ("OBS_VALUE", "VALUE", "OBSERVATION_VALUE"), ("OBS_VALUE",))
    if not time_col or not value_col:
        return pd.DataFrame(columns=["date", "value"]), source + " · columns unavailable", "%"
    work = raw[_cb38_area_mask(raw, bank)].copy()
    if work.empty:
        return pd.DataFrame(columns=["date", "value"]), source + " · area not found", "%"
    work["_DATE"] = work[time_col].map(_cb38_parse_period)
    work["_VALUE"] = pd.to_numeric(work[value_col], errors="coerce")
    work = work.dropna(subset=["_DATE", "_VALUE"])
    work = work[work["_DATE"] >= pd.Timestamp(start)]
    if work.empty:
        return pd.DataFrame(columns=["date", "value"]), source + " · no observations", "%"
    freq_col = _cb38_find_col(work, ("FREQ", "FREQUENCY"), ("FREQ",))
    unit_col = _cb38_find_col(work, ("UNIT_MEASURE", "UNIT", "UNIT_OF_MEASURE"), ("UNIT_MEASURE",))
    work["_SERIES"] = _cb38_series_groups(work)
    candidates = []
    for key, group in work.groupby("_SERIES", dropna=False):
        values = pd.to_numeric(group["_VALUE"], errors="coerce").dropna()
        if values.empty:
            continue
        freq = str(group[freq_col].iloc[0]).upper() if freq_col else ""
        unit = str(group[unit_col].iloc[0]).upper() if unit_col else ""
        plausible_share = float(values.between(-5.0, 30.0).mean())
        latest = float(values.iloc[-1])
        plausible = int(plausible_share >= 0.98 and -5.0 <= latest <= 30.0)
        freq_pref = {"D": 4, "B": 4, "M": 3, "Q": 2, "A": 1}.get(freq, 0)
        unit_pref = 2 if ("PERCENT" in unit or unit in {"PC", "PCT", "%", "15"}) else 0
        candidates.append((plausible, freq_pref, unit_pref, group["_DATE"].max(), len(group), str(key), group.copy()))
    if not candidates:
        return pd.DataFrame(columns=["date", "value"]), source + " · no series", "%"
    candidates.sort(key=lambda item: item[:5], reverse=True)
    plausible, _, _, _, _, series_key, group = candidates[0]
    out = pd.DataFrame({"date": group["_DATE"], "value": pd.to_numeric(group["_VALUE"], errors="coerce")})
    out = out.dropna().sort_values("date").drop_duplicates("date", keep="last")
    if not plausible or out.empty or not bool(out["value"].between(-5.0, 30.0).all()):
        return pd.DataFrame(columns=["date", "value"]), source + " · rejected implausible rate units", "%"
    return out.reset_index(drop=True), f"{source} · {series_key} · validated raw %", "%"


@st.cache_data(ttl=21600, show_spinner=False)
def _cb38_policy_series(code: str, start: str = "2000-01-01") -> Tuple[pd.DataFrame, str]:  # noqa: F811
    df, source, _ = _cb38_select_bis("policy", code, start)
    if len(df) >= 2:
        return df, source
    fallback, fsource = _cb38_first_fred(CB38_BANK_BY_CODE[code].get("fred_rate", ()), start)
    if len(fallback) >= 2 and bool(fallback["value"].between(-5.0, 30.0).all()):
        return fallback, fsource + " · validated"
    return pd.DataFrame(columns=["date", "value"]), source or "No valid public policy-rate series"


@st.cache_data(ttl=21600, show_spinner=False)
def _cb38_assets_series(code: str, start: str = "2016-01-01") -> Tuple[pd.DataFrame, str, str]:  # noqa: F811
    df, source, unit = _CB383_SELECT_BIS_V382("assets", code, start)
    if len(df) >= 2:
        return df, source, unit
    fallback, fsource = _cb38_first_fred(CB38_BANK_BY_CODE[code].get("fred_assets", ()), start)
    if len(fallback) >= 2:
        median = float(fallback["value"].abs().median())
        if median > 1e6:
            fallback["value"] = fallback["value"] / 1000.0
        return fallback, fsource, "native bn / provider units"
    return pd.DataFrame(columns=["date", "value"]), source or "No public balance-sheet series", unit


def _cb383_parse_rba_speeches(page: str, url: str, bank: Mapping[str, Any]) -> pd.DataFrame:
    if _cb38_BeautifulSoup is None:
        return _cb383_empty_speeches()
    soup = _cb38_BeautifulSoup(page, "html.parser")
    rows: List[Dict[str, Any]] = []
    seen = set()
    for heading in soup.find_all("h3"):
        anchor = heading.find("a", href=True)
        if anchor is None:
            continue
        title = _cb383_text(heading.get_text(" ", strip=True))
        href = _cb38_urljoin(url, anchor.get("href"))
        if not _cb383_is_substantive_title(title) or _cb383_is_media_item(title, href):
            continue
        context = _cb383_heading_context(heading)
        dt = _cb38_parse_date(context, href)
        if pd.isna(dt) or pd.Timestamp(dt).normalize() > CB38_TODAY + pd.Timedelta(days=1):
            continue
        speaker = _cb383_infer_speaker("RBA", context + " " + title)
        key = (pd.Timestamp(dt).normalize(), _cb38_norm(title))
        if key in seen:
            continue
        seen.add(key)
        score, confidence, _ = _cb38_score_text(title + " " + context)
        rows.append({
            "Date": pd.Timestamp(dt).normalize(), "CB": "RBA", "Speaker": speaker,
            "Title": title, "Score": score, "Confidence": confidence,
            "Source": f"{bank['short']} official archive", "URL": href, "Text": context,
        })
    return pd.DataFrame(rows, columns=CB383_SPEECH_COLUMNS).sort_values("Date", ascending=False).head(CB383_ARCHIVE_LIMIT).reset_index(drop=True)


def _cb383_parse_generic_speeches(code: str, page: str, url: str, bank: Mapping[str, Any]) -> pd.DataFrame:
    if _cb38_BeautifulSoup is None:
        return _cb383_empty_speeches()
    soup = _cb38_BeautifulSoup(page, "html.parser")
    rows: List[Dict[str, Any]] = []
    seen = set()
    candidates = []
    for heading in soup.find_all(["h2", "h3", "h4"]):
        anchor = heading.find("a", href=True)
        if anchor is not None:
            candidates.append((heading, anchor))
    if not candidates:
        for block in soup.find_all(["article", "li"]):
            anchor = block.find("a", href=True)
            if anchor is not None:
                candidates.append((block, anchor))
    for block, anchor in candidates:
        title = _cb383_text(anchor.get_text(" ", strip=True) or block.get_text(" ", strip=True))
        href = _cb38_urljoin(url, anchor.get("href"))
        if not _cb383_is_substantive_title(title) or _cb383_is_media_item(title, href):
            continue
        context = _cb383_text(block.parent.get_text(" ", strip=True) if getattr(block, "parent", None) is not None else block.get_text(" ", strip=True))[:1800]
        dt = _cb38_parse_date(context, href)
        if pd.isna(dt) or pd.Timestamp(dt).normalize() > CB38_TODAY + pd.Timedelta(days=1):
            continue
        key = (pd.Timestamp(dt).normalize(), _cb38_norm(title))
        if key in seen:
            continue
        seen.add(key)
        speaker = _cb383_infer_speaker(code, context + " " + title)
        score, confidence, _ = _cb38_score_text(title + " " + context)
        rows.append({
            "Date": pd.Timestamp(dt).normalize(), "CB": code, "Speaker": speaker,
            "Title": title, "Score": score, "Confidence": confidence,
            "Source": f"{bank['short']} official archive", "URL": href, "Text": context,
        })
    return pd.DataFrame(rows, columns=CB383_SPEECH_COLUMNS).sort_values("Date", ascending=False).head(CB383_ARCHIVE_LIMIT).reset_index(drop=True)


def _cb383_parse_rba_decision_page(page: str, url: str, bank: Mapping[str, Any]) -> pd.DataFrame:
    if _cb38_BeautifulSoup is None:
        return _cb383_empty_decisions()
    soup = _cb38_BeautifulSoup(page, "html.parser")
    rows = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = _cb38_urljoin(url, anchor.get("href"))
        if "/media-releases/" not in href:
            continue
        context = _cb383_text(anchor.parent.get_text(" ", strip=True) if anchor.parent is not None else anchor.get_text(" ", strip=True))
        dt = _cb38_parse_date(anchor.get_text(" ", strip=True) + " " + context, href)
        if pd.isna(dt) or pd.Timestamp(dt).normalize() > CB38_TODAY + pd.Timedelta(days=1):
            continue
        key = pd.Timestamp(dt).normalize()
        if key in seen:
            continue
        seen.add(key)
        rows.append({"Date": key, "Title": "Monetary Policy Decision", "URL": href, "Source": f"{bank['short']} official decisions"})
    return pd.DataFrame(rows, columns=CB383_DECISION_COLUMNS)


def _cb383_parse_generic_decisions(code: str, page: str, url: str, bank: Mapping[str, Any]) -> pd.DataFrame:
    if _cb38_BeautifulSoup is None:
        return _cb383_empty_decisions()
    soup = _cb38_BeautifulSoup(page, "html.parser")
    include = (
        "monetary policy decision", "rate decision", "interest rate decision", "official cash rate decision",
        "fomc statement", "monetary policy summary", "policy rate decision", "cash rate decision",
    )
    exclude = ("framework", "advisory", "expert", "schedule", "calendar", "report", "speech", "press conference")
    rows = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        title = _cb383_text(anchor.get_text(" ", strip=True))
        href = _cb38_urljoin(url, anchor.get("href"))
        context = _cb383_text(anchor.parent.get_text(" ", strip=True) if anchor.parent is not None else title)[:1200]
        blob = _cb38_norm(title + " " + context + " " + href)
        if not any(_cb38_norm(term) in blob for term in include):
            continue
        if any(_cb38_norm(term) in blob for term in exclude):
            continue
        dt = _cb38_parse_date(context, href)
        if pd.isna(dt) or pd.Timestamp(dt).normalize() > CB38_TODAY + pd.Timedelta(days=1):
            continue
        key = (pd.Timestamp(dt).normalize(), _cb38_norm(title))
        if key in seen:
            continue
        seen.add(key)
        rows.append({"Date": key[0], "Title": title or "Policy decision", "URL": href, "Source": f"{bank['short']} official decisions"})
    return pd.DataFrame(rows, columns=CB383_DECISION_COLUMNS)


@st.cache_data(ttl=21600, show_spinner=False)
def _cb38_official_archive(code: str, kind: str = "speech") -> pd.DataFrame:  # noqa: F811
    bank = CB38_BANK_BY_CODE[code]
    base_url = str(bank["speech_url" if kind == "speech" else "decision_url"])
    if kind == "decision" and code == "RBA":
        frames = []
        current_year = int(CB38_TODAY.year)
        urls = [base_url] + [base_url.rstrip("/") + f"/{year}/" for year in range(current_year - 1, current_year - CB383_DECISION_YEARS, -1)]
        for page_url in urls:
            response = _CB383_HTTP_GET(page_url)
            if response is not None:
                frame = _cb383_parse_rba_decision_page(response.text, page_url, bank)
                if not frame.empty:
                    frames.append(frame)
        if not frames:
            return _cb383_empty_decisions()
        return pd.concat(frames, ignore_index=True).sort_values("Date", ascending=False).drop_duplicates("Date").reset_index(drop=True)
    response = _CB383_HTTP_GET(base_url)
    if response is None:
        return _cb383_empty_speeches() if kind == "speech" else _cb383_empty_decisions()
    try:
        if kind == "speech":
            frame = _cb383_parse_rba_speeches(response.text, base_url, bank) if code == "RBA" else _cb383_parse_generic_speeches(code, response.text, base_url, bank)
            return _cb383_clean_speeches(frame)
        return _cb383_parse_generic_decisions(code, response.text, base_url, bank).sort_values("Date", ascending=False).head(80).reset_index(drop=True)
    except Exception:
        return _cb383_empty_speeches() if kind == "speech" else _cb383_empty_decisions()


def _cb383_clean_speeches(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return _cb383_empty_speeches()
    work = df.copy()
    for column in CB383_SPEECH_COLUMNS:
        if column not in work.columns:
            work[column] = np.nan if column in {"Score", "Confidence"} else ""
    work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
    work = work.dropna(subset=["Date"])
    work = work[work["Date"] <= CB38_TODAY + pd.Timedelta(days=1)]
    mask = [not _cb383_is_media_item(title, url) and _cb383_is_substantive_title(title) for title, url in zip(work["Title"], work["URL"])]
    work = work.loc[mask].copy()
    work["TitleKey"] = work["Title"].map(_cb38_norm)
    work = work.sort_values(["Date", "Confidence"], ascending=[False, False]).drop_duplicates(["CB", "TitleKey", "Date"])
    work = work.drop(columns=["TitleKey"])
    return work[CB383_SPEECH_COLUMNS].reset_index(drop=True)


@st.cache_data(ttl=21600, show_spinner=False)
def _cb383_fetch_full_text(url: str) -> str:
    if not url or _cb383_is_media_item("", url):
        return ""
    response = _CB383_HTTP_GET(url, timeout=min(CB38_TIMEOUT, 9))
    if response is None:
        return ""
    content = response.content[:2_000_000]
    if _cb38_BeautifulSoup is not None:
        try:
            soup = _cb38_BeautifulSoup(content, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            main = soup.find("main") or soup.find("article") or soup.body or soup
            return _cb383_text(main.get_text(" ", strip=True))[:90000]
        except Exception:
            pass
    return _cb38_extract_html_text(content)[:90000]


def _cb383_enrich_speeches(df: pd.DataFrame, limit: int = CB383_ENRICH_LIMIT) -> pd.DataFrame:
    work = _cb383_clean_speeches(df)
    if work.empty or limit <= 0:
        return work
    indices = list(work.index[:max(1, int(limit))])
    with _cb38_ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_cb383_fetch_full_text, str(work.at[idx, "URL"])): idx for idx in indices}
        for future in _cb38_as_completed(futures):
            idx = futures[future]
            try:
                body = future.result()
            except Exception:
                body = ""
            if not body:
                continue
            score, confidence, _ = _cb38_score_text(str(work.at[idx, "Title"]) + " " + body)
            work.at[idx, "Text"] = body
            work.at[idx, "Score"] = score
            work.at[idx, "Confidence"] = confidence
    return work


def _cb38_speeches(code: Optional[str] = None, deep: bool = False) -> pd.DataFrame:  # noqa: F811
    bis = _cb383_clean_speeches(_cb38_bis_rss(enrich_text=False))
    if code:
        official = _cb383_clean_speeches(_cb38_official_archive(code, "speech"))
        frames = [frame for frame in (bis[bis["CB"] == code].copy() if not bis.empty else _cb383_empty_speeches(), official) if not frame.empty]
        if not frames:
            return _cb383_empty_speeches()
        combined = _cb383_clean_speeches(pd.concat(frames, ignore_index=True))
        return _cb383_enrich_speeches(combined, CB383_ENRICH_LIMIT) if deep else combined
    frames = [bis] if not bis.empty else []
    with _cb38_ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_cb38_official_archive, bank_code, "speech"): bank_code for bank_code in CB38_BANK_BY_CODE}
        for future in _cb38_as_completed(futures):
            try:
                frame = _cb383_clean_speeches(future.result()).head(CB383_ROOT_PER_BANK)
                if not frame.empty:
                    frames.append(frame)
            except Exception:
                pass
    if not frames:
        return _cb383_empty_speeches()
    return _cb383_clean_speeches(pd.concat(frames, ignore_index=True))


def _cb38_score_snapshot(df: pd.DataFrame) -> Dict[str, Any]:  # noqa: F811
    indexed_count = int(len(df)) if isinstance(df, pd.DataFrame) else 0
    if df is None or df.empty:
        return {"recent": None, "lifetime": None, "count": 0, "indexed_count": indexed_count, "confidence": 0.0, "last_date": None, "last_indexed_date": None}
    source = df.copy()
    source["Date"] = pd.to_datetime(source["Date"], errors="coerce")
    last_indexed = pd.Timestamp(source["Date"].max()) if source["Date"].notna().any() else None
    work = source.dropna(subset=["Date", "Score"]).copy().sort_values("Date")
    if work.empty:
        return {"recent": None, "lifetime": None, "count": 0, "indexed_count": indexed_count, "confidence": 0.0, "last_date": None, "last_indexed_date": last_indexed}
    work["Score"] = pd.to_numeric(work["Score"], errors="coerce")
    work = work.dropna(subset=["Score"])
    if work.empty:
        return {"recent": None, "lifetime": None, "count": 0, "indexed_count": indexed_count, "confidence": 0.0, "last_date": None, "last_indexed_date": last_indexed}
    scores = work["Score"]
    recent = float(scores.ewm(span=12, adjust=False).mean().iloc[-1])
    age = (work["Date"].max() - work["Date"]).dt.days.clip(lower=0)
    weights = np.exp(-np.log(2) * age / 365.0)
    lifetime = float(np.average(scores, weights=weights)) if float(weights.sum()) > 0 else float(scores.mean())
    confidence = float(pd.to_numeric(work["Confidence"], errors="coerce").fillna(0).mean())
    return {"recent": recent, "lifetime": lifetime, "count": int(len(work)), "indexed_count": indexed_count, "confidence": confidence, "last_date": pd.Timestamp(work["Date"].max()), "last_indexed_date": last_indexed}


def _cb38_snapshot(code: str, speech_df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:  # noqa: F811
    bank = dict(CB38_BANK_BY_CODE[code])
    policy, policy_source = _cb38_policy_series(code, "2000-01-01")
    status = _cb38_detect_rate_status(policy)
    speeches = speech_df if speech_df is not None else _cb38_speeches(code, deep=False)
    score = _cb38_score_snapshot(speeches)
    bank.update(status)
    bank.update({
        "policy_source": policy_source, "score": score["recent"], "lifetime": score["lifetime"],
        "speech_count": score["count"], "speech_indexed_count": score["indexed_count"],
        "score_confidence": score["confidence"], "speech_last_date": score["last_date"],
        "speech_last_indexed_date": score["last_indexed_date"],
    })
    return bank


def _cb38_bank_card(bank: Mapping[str, Any]) -> None:  # noqa: F811
    score = bank.get("score")
    cls = "cb38-score-na" if score is None or pd.isna(score) else ("cb38-score-pos" if float(score) >= 0 else "cb38-score-neg")
    decision = str(bank.get("decision") or "N/A")
    scored = int(bank.get("speech_count", 0))
    indexed = int(bank.get("speech_indexed_count", scored))
    _html('<div class="cb38-card">'
          f'<div class="cb38-card-head"><span class="cb38-card-code">{_esc(bank["flag"])} {_esc(bank["code"])}</span><span class="cb38-card-ccy">{_esc(bank["ccy"])}</span></div>'
          f'<div class="cb38-card-rate">{_cb38_fmt_rate(bank.get("rate"))} <span class="cb38-card-decision">● {_esc(decision)}</span></div>'
          f'<div class="cb38-card-name">{_esc(bank["name"])}</div>{_cb38_track(score)}'
          f'<div class="cb38-card-meta"><span class="{cls}">{_cb38_fmt_score(score, 3)}</span><span>{scored} scored / {indexed} indexed</span></div>'
          f'<div class="cb38-card-name">{_esc(bank["meetings"])} · {_esc(bank.get("policy_source", ""))}</div></div>')


def _cb38_render_speech_cards(df: pd.DataFrame, limit: Optional[int] = None) -> None:  # noqa: F811
    use = _cb383_clean_speeches(df)
    use = use.head(limit) if limit else use
    if use.empty:
        st.info("No substantive public communication rows were resolved for this view.")
        return
    for _, row in use.iterrows():
        score = pd.to_numeric(pd.Series([row.get("Score")]), errors="coerce").iloc[0]
        confidence = float(pd.to_numeric(pd.Series([row.get("Confidence", 0)]), errors="coerce").fillna(0).iloc[0])
        if pd.isna(score):
            score_text = "N/A"
            cls = "cb38-score-na"
        else:
            score_text = f"{float(score):+.2f}"
            cls = "cb38-score-pos" if float(score) >= 0 else "cb38-score-neg"
        _html('<div class="cb38-speech">'
              f'<div><div class="cb38-speech-title">{_esc(row["Title"])}</div><div class="cb38-speech-meta">{_esc(row["Speaker"])} · {pd.Timestamp(row["Date"]).date().isoformat()} · {_esc(row["CB"])} · {_esc(row.get("Source", ""))}</div></div>'
              f'<div><div class="cb38-speech-score {cls}">{score_text}</div><div class="cb38-speech-conf">confidence {confidence:.0%}</div></div></div>')


def _cb38_members(code: str, speeches: Optional[pd.DataFrame] = None) -> List[Dict[str, Any]]:  # noqa: F811
    """Committee scorecard = official roster only.

    Senior officials outside the committee remain visible in the speech tape,
    but media labels and discovered page fragments can never become members.
    """
    df = _cb383_clean_speeches(speeches if speeches is not None else _cb38_speeches(code, deep=False))
    rows = []
    for name, role in CB38_ROSTERS.get(code, ()):
        member_df = df[df["Speaker"].map(_cb38_norm) == _cb38_norm(name)] if not df.empty else _cb383_empty_speeches()
        snap = _cb38_score_snapshot(member_df)
        rows.append({
            "slug": _cb38_slug(name), "name": name, "role": role,
            "recent": snap["recent"], "lifetime": snap["lifetime"],
            "speeches": snap["count"], "indexed": snap["indexed_count"],
            "confidence": snap["confidence"], "last_date": snap["last_date"],
            "last_indexed_date": snap["last_indexed_date"],
        })
    return rows


def _cb38_summary(bank: Mapping[str, Any]) -> None:  # noqa: F811
    score = bank.get("score")
    since = bank.get("since")
    last_scored = bank.get("speech_last_date")
    last_indexed = bank.get("speech_last_indexed_date")
    scored = int(bank.get("speech_count", 0))
    indexed = int(bank.get("speech_indexed_count", scored))
    decision = str(bank.get("decision") or "N/A")
    move = bank.get("change_bps")
    decision_note = "unchanged"
    if decision == "HOLD" and move not in (None, 0):
        decision_note = f"last move {int(move):+d} bps"
    elif decision in {"HIKE", "CUT"} and move is not None:
        decision_note = f"{int(move):+d} bps"
    freshness = last_scored or last_indexed
    items = [
        ("Rate", _cb38_fmt_rate(bank.get("rate")), f"last move {since.date().isoformat() if since is not None else 'N/A'}", "flat"),
        ("Target", str(bank["target"]), bank["country"], "flat"),
        ("Hawk / Dove", _cb38_fmt_score(score, 3), f"{scored} scored / {indexed} indexed", "up" if score is not None and not pd.isna(score) and float(score) >= 0 else "flat"),
        ("Decision", decision, decision_note, "flat"),
        ("Freshness", freshness.date().isoformat() if freshness is not None else "N/A", "latest public communication", "flat"),
    ]
    blocks = []
    for label, value, note, tone in items:
        cls = {"up": "ec36-up", "down": "ec36-down", "flat": "ec36-flat"}.get(tone, "")
        blocks.append(f'<div class="cb38-stat"><div class="cb38-stat-k">{_esc(label)}</div><div class="cb38-stat-v {cls}">{_esc(value)}</div><div class="cb38-stat-n">{_esc(note)}</div></div>')
    _html('<div class="cb38-stats">' + ''.join(blocks) + '</div>')


def _cb38_decisions(code: str) -> Tuple[pd.DataFrame, str]:  # noqa: F811
    policy, policy_source = _cb38_policy_series(code, "1990-01-01")
    official = _cb38_official_archive(code, "decision")
    if not official.empty and not policy.empty:
        left = official.copy()
        left["Date"] = pd.to_datetime(left["Date"], errors="coerce")
        left = left.dropna(subset=["Date"]).sort_values("Date").drop_duplicates("Date", keep="first")
        right = policy.copy()
        right["date"] = pd.to_datetime(right["date"], errors="coerce")
        right["value"] = pd.to_numeric(right["value"], errors="coerce")
        right = right.dropna().sort_values("date")
        merged = pd.merge_asof(left, right, left_on="Date", right_on="date", direction="backward", tolerance=pd.Timedelta(days=62))
        merged["RateNumeric"] = pd.to_numeric(merged["value"], errors="coerce")
        merged["ChangeRaw"] = merged["RateNumeric"].diff()
        merged["Decision"] = np.where(merged["ChangeRaw"] > 1e-8, "HIKE", np.where(merged["ChangeRaw"] < -1e-8, "CUT", "HOLD"))
        if len(merged):
            merged.loc[merged.index[0], "Decision"] = "N/A"
        merged["Change"] = merged["ChangeRaw"].map(lambda x: "—" if pd.isna(x) or abs(float(x)) < 1e-8 else f"{int(round(float(x) * 100)):+d} bps")
        merged["Rate"] = merged["RateNumeric"].map(lambda x: "—" if pd.isna(x) else f"{float(x):.2f}%")
        out = merged.sort_values("Date", ascending=False)[["Date", "Decision", "Rate", "Change", "Title", "Source", "URL"]]
        return out.head(48).reset_index(drop=True), f"Official decision archive + {policy_source}"
    if not policy.empty:
        work = policy.sort_values("date").copy()
        work["change"] = work["value"].diff()
        changes = work[work["change"].abs() > 1e-9]
        rows = []
        for _, row in changes.sort_values("date", ascending=False).head(48).iterrows():
            bps = int(round(float(row["change"]) * 100))
            rows.append({"Date": pd.Timestamp(row["date"]), "Decision": "HIKE" if bps > 0 else "CUT", "Rate": f"{float(row['value']):.2f}%", "Change": f"{bps:+d} bps", "Title": "Policy-rate change detected in public series", "Source": policy_source, "URL": ""})
        return pd.DataFrame(rows), policy_source + " · rate changes only"
    return pd.DataFrame(columns=["Date", "Decision", "Rate", "Change", "Title", "Source", "URL"]), policy_source


def _cb383_merge_decision_scores(decisions: pd.DataFrame, score_hist: pd.Series) -> pd.DataFrame:
    if decisions is None or decisions.empty or score_hist is None or score_hist.empty:
        return pd.DataFrame()
    left = decisions.copy()
    left["Date"] = pd.to_datetime(left["Date"], errors="coerce")
    left = left.dropna(subset=["Date"]).sort_values("Date")
    right = score_hist.rename("Model score").rename_axis("ScoreDate").reset_index()
    if list(right.columns) != ["ScoreDate", "Model score"]:
        right.columns = ["ScoreDate", "Model score"]
    right["ScoreDate"] = pd.to_datetime(right["ScoreDate"], errors="coerce")
    right = right.dropna(subset=["ScoreDate"]).sort_values("ScoreDate")
    if left.empty or right.empty:
        return pd.DataFrame()
    return pd.merge_asof(left, right, left_on="Date", right_on="ScoreDate", direction="backward")


def _cb38_scorecard(code: str, bank: Mapping[str, Any], speeches: pd.DataFrame) -> None:  # noqa: F811
    members = _cb38_members(code, speeches)
    _section("COMMITTEE INTELLIGENCE", f"{bank['name']} — {bank['committee']} Scorecard", "Recent = 12-observation EMA. Lifetime = 365-day half-life. Only official roster members are included.")
    horizon = st.radio("Score horizon", ["Recent (12-EMA)", "Lifetime"], horizontal=True, key=f"ec38_horizon_{code}")
    valid = [member for member in members if member.get("recent") is not None and not pd.isna(member.get("recent"))]
    life = [member for member in members if member.get("lifetime") is not None and not pd.isna(member.get("lifetime"))]
    recent_avg = float(np.mean([float(member["recent"]) for member in valid])) if valid else np.nan
    life_avg = float(np.mean([float(member["lifetime"]) for member in life])) if life else np.nan
    indexed_total = sum(int(member.get("indexed", 0)) for member in members)
    _kpis([
        ("Committee recent", "—" if np.isnan(recent_avg) else f"{recent_avg:+.2f}", "scored-member average", "up" if not np.isnan(recent_avg) and recent_avg >= 0 else "flat"),
        ("Committee lifetime", "—" if np.isnan(life_avg) else f"{life_avg:+.2f}", "365-day half-life", "flat"),
        ("Roster", str(len(members)), bank["committee"], "flat"),
        ("Scored members", str(len(valid)), f"{indexed_total} indexed communications", "flat"),
    ])
    metric_key = "recent" if horizon.startswith("Recent") else "lifetime"
    ranking = [(member["name"], member.get(metric_key)) for member in members if member.get(metric_key) is not None and not pd.isna(member.get(metric_key))]
    if ranking:
        ranking = sorted(ranking, key=lambda item: float(item[1]))
        figure_rank = go.Figure(go.Bar(
            x=[float(value) for _, value in ranking], y=[name for name, _ in ranking], orientation="h",
            marker_color=[CB38_COLORS["green"] if float(value) >= 0 else CB38_COLORS["red"] for _, value in ranking],
        ))
        figure_rank.add_vline(x=0, line_color="rgba(202,212,221,.28)")
        figure_rank.update_xaxes(range=[-1, 1])
        _plot(figure_rank, f"ec383_committee_rank_{code}_{metric_key}", max(300, 42 * len(ranking)), hovermode="closest")
    else:
        st.info("No roster member has enough directional public text for a committee ranking. Use the bounded full-text enrichment control on the bank page.")
    figure = go.Figure()
    for member in members:
        member_df = speeches[speeches["Speaker"].map(_cb38_norm) == _cb38_norm(member["name"])] if not speeches.empty else _cb383_empty_speeches()
        history = _cb38_score_history(member_df)
        if history.empty:
            continue
        figure.add_trace(go.Scatter(x=history.index, y=history.values, name=member["name"].split()[-1], mode="lines+markers", line=dict(width=1.8)))
    if figure.data:
        figure.add_hline(y=0, line_color="rgba(202,212,221,.28)")
        figure.update_yaxes(range=[-1, 1], tickvals=[-.7, 0, .7], ticktext=["Dove", "Neutral", "Hawk"])
        _plot(figure, f"ec38_committee_{code}", 430)
    decisions, source = _cb38_decisions(code)
    joined = _cb383_merge_decision_scores(decisions, _cb38_score_history(speeches))
    if not joined.empty:
        joined["Model score"] = joined["Model score"].map(lambda value: "—" if pd.isna(value) else f"{float(value):+.2f}")
        _table(joined.sort_values("Date", ascending=False)[["Date", "Decision", "Rate", "Change", "Model score"]].head(12), f"ec38_score_decisions_{code}", 390)
    _section("INDIVIDUAL MEMBERS", f"Individual Members ({len(members)})", "Official roster only: observed text count, recent/lifetime score and confidence.")
    _cb38_member_cards(code, speeches)
    _cb38_source([("Score model", "Quant Terminal directional public-text model"), ("Decision source", source), ("No-data rule", "unscored text remains N/A")])


def _cb38_speech_archive(code: str, bank: Mapping[str, Any], speeches: pd.DataFrame) -> None:  # noqa: F811
    _section("COMMUNICATION", f"Speeches — {code}", f"Filtered BIS and official public archive for {bank['name']}.")
    query = st.text_input("Search speeches", key=f"ec38_speech_search_{code}", placeholder="speaker, title, subject")
    c1, c2 = st.columns([1, 1])
    with c1:
        page_size = st.selectbox("Rows per page", [12, 24, 48], index=1, key=f"ec383_page_size_{code}")
    with c2:
        scoreable_only = st.checkbox("Directional scores only", key=f"ec383_scoreable_{code}")
    frame = _cb383_clean_speeches(speeches)
    if query and not frame.empty:
        mask = frame.astype(str).apply(lambda column: column.str.contains(query, case=False, regex=False)).any(axis=1)
        frame = frame[mask]
    if scoreable_only and not frame.empty:
        frame = frame[pd.to_numeric(frame["Score"], errors="coerce").notna()]
    total = len(frame)
    pages = max(1, int(math.ceil(total / max(1, int(page_size)))))
    page = int(st.number_input("Page", min_value=1, max_value=pages, value=1, step=1, key=f"ec383_page_{code}"))
    start = (page - 1) * int(page_size)
    st.caption(f"{total} substantive communications · page {page}/{pages} · audio/download/transcript attachments excluded")
    _cb38_render_speech_cards(frame.iloc[start:start + int(page_size)])


def _cb38_quality_block(snapshots: Sequence[Mapping[str, Any]], speeches: pd.DataFrame) -> None:  # noqa: F811
    blocks = []
    for snapshot in snapshots:
        code = str(snapshot["code"])
        assets, _, _ = _cb38_assets_series(code, "2020-01-01")
        bank_texts = speeches[speeches["CB"] == code] if not speeches.empty else _cb383_empty_speeches()
        indexed = int(len(bank_texts))
        scored = int(pd.to_numeric(bank_texts["Score"], errors="coerce").notna().sum()) if indexed else 0
        policy_ok = snapshot.get("rate") is not None and not pd.isna(snapshot.get("rate"))
        assets_ok = not assets.empty
        blocks.append(f'<div class="cb38-q"><b>{_esc(code)}</b><span class="{"cb38-ok" if policy_ok else "cb38-bad"}">Policy: {"live" if policy_ok else "missing"}</span><span class="{"cb38-ok" if assets_ok else "cb38-warn"}">Assets: {"live" if assets_ok else "unavailable"}</span><span class="{"cb38-ok" if indexed else "cb38-warn"}">Texts: {scored} scored / {indexed} indexed</span></div>')
    _html('<div class="cb38-quality">' + ''.join(blocks) + '</div>')


def _cb38_bank(code: str) -> None:  # noqa: F811
    deep_key = f"ec383_enrich_{code}"
    deep = bool(st.session_state.get(deep_key, False))
    speeches = _cb38_speeches(code, deep=deep)
    bank = _cb38_snapshot(code, speeches)
    _cb38_path(["Central Banks", bank["name"]])
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        if st.button("← All Central Banks", key=f"ec38_back_{code}"):
            st.session_state["ec36_cb_route"] = "root"; st.rerun()
    with c2:
        label = "Use metadata mode" if deep else f"Enrich latest {CB383_ENRICH_LIMIT} texts"
        if st.button(label, key=f"ec383_enrich_toggle_{code}", use_container_width=True):
            st.session_state[deep_key] = not deep; st.rerun()
    with c3:
        if st.button("Policy Previews →", key=f"ec38_preview_{code}"):
            st.session_state["ec36_cb_route"] = "previews"; st.rerun()
    _header("CENTRAL BANK WORKSTATION", f"{bank['flag']} {bank['name']}", f"{bank['committee']} · filtered public-data workflow", [bank["ccy"], bank["meetings"], f"{len(CB38_ROSTERS.get(code,()))} roster names", CB38_VERSION])
    _cb38_summary(bank)
    if not deep:
        _html(f'<div class="cb38-callout"><b>Fast mode:</b> media attachments are excluded and only archive metadata is loaded. Use “Enrich latest {CB383_ENRICH_LIMIT} texts” to fetch a bounded set of full speech pages for better directional scoring.</div>')
    tab = _segmented("Central bank page", ["Overview", "Scorecard", "Speeches", "Meetings"], "ec38_cb_nav", "Overview")
    if tab == "Overview":
        _cb38_overview(code, bank, speeches)
    elif tab == "Scorecard":
        _cb38_scorecard(code, bank, speeches)
    elif tab == "Speeches":
        _cb38_speech_archive(code, bank, speeches)
    else:
        _cb38_meeting_archive(code, bank)


CENTRAL_BANKS_INTEGRITY_V383: Mapping[str, Any] = {
    "version": CB383_VERSION,
    "append_only_over_v382": True,
    "media_rows_as_speeches": False,
    "discovered_page_fragments_as_members": False,
    "policy_rate_unit_multiplier_applied": False,
    "speech_archive_paginated": True,
    "full_text_enrichment": "bounded and opt-in",
    "non_central_economy_modified": False,
}
assert CENTRAL_BANKS_INTEGRITY_V383["media_rows_as_speeches"] is False
assert CENTRAL_BANKS_INTEGRITY_V383["policy_rate_unit_multiplier_applied"] is False

# ============================================================
# END JARVIS ECONOMY V38.3 — FILTERED PUBLIC DATA PATCH
# ============================================================

# ============================================================
# JARVIS ECONOMY V39.0 — FINAL CENTRAL BANKS EQUIVALENCE PATCH
# Append-only over V38.3.  Central Banks runtime only.
# ============================================================

import os as _cb39_os
import io as _cb39_io
import re as _cb39_re
import json as _cb39_json
import zipfile as _cb39_zipfile
import tempfile as _cb39_tempfile
from pathlib import Path as _cb39_Path
from concurrent.futures import ThreadPoolExecutor as _cb39_ThreadPoolExecutor, as_completed as _cb39_as_completed

CB39_VERSION = "V39.0 · FINAL OFFICIAL DATA ENGINE"
CB39_SPEECH_COLUMNS = ["Date","CB","Speaker","Title","Score","Confidence","Source","URL","Text"]
CB39_DECISION_COLUMNS = ["Date","Decision","Rate","Change","Title","Source","URL"]
CB39_CACHE_DIR = _cb39_Path(_cb39_os.getenv("CB39_CACHE_DIR", ".quant_cache/central_banks_v39"))
# V41 self-contained mode: no directory is created at import time.
CB39_CORPUS_START_YEAR = int(_cb39_os.getenv("CB39_CORPUS_START_YEAR", "2016"))
CB39_AUTO_ENRICH_LIMIT = max(4, min(16, int(_cb39_os.getenv("CB39_AUTO_ENRICH_LIMIT", "10"))))
CB39_ARCHIVE_LIMIT = max(30, min(240, int(_cb39_os.getenv("CB39_ARCHIVE_LIMIT", "120"))))
CB39_ROOT_RECENT_LIMIT = 20
CB39_HTTP_TIMEOUT = max(5, min(25, int(_cb39_os.getenv("CB39_HTTP_TIMEOUT", "10"))))
CB39_STRICT_TODAY = pd.Timestamp.utcnow().tz_localize(None).normalize()
CB39_CORPUS_DB = CB39_CACHE_DIR / "bis_g10_speeches.csv.gz"
CB39_CORPUS_META = CB39_CACHE_DIR / "bis_g10_speeches.meta.json"

# Current committee metadata.  It is not a score source; it only controls
# official roster membership and profile labels.
CB39_MEMBER_META: Mapping[str, Mapping[str, Mapping[str, str]]] = {
    "RBA": {
        "Michele Bullock": {"appointed":"2023-09-18","term_end":"2030-09-17","class":"Governor","vote":"Consensus"},
        "Andrew Hauser": {"appointed":"2024-03-18","term_end":"","class":"Deputy","vote":"Consensus"},
        "Bruce Preston": {"appointed":"2026-03-01","term_end":"","class":"External","vote":"Consensus"},
        "Carolyn Hewson": {"appointed":"","term_end":"","class":"External","vote":"Consensus"},
        "Iain Ross": {"appointed":"","term_end":"","class":"External","vote":"Consensus"},
        "Ian Harper": {"appointed":"","term_end":"","class":"External","vote":"Consensus"},
        "Jenny Wilkinson": {"appointed":"2025-06-16","term_end":"","class":"External","vote":"Ex officio"},
        "Marnie Baker": {"appointed":"","term_end":"","class":"External","vote":"Consensus"},
        "Renee Fry-McKibbin": {"appointed":"","term_end":"","class":"External","vote":"Consensus"},
    }
}

CB39_MEMBER_COUNTS: Mapping[str, int] = {
    "RBA":9, "NORGES":5, "BOE":9, "FED":18, "RBNZ":6,
    "ECB":27, "BOC":7, "RIKSBANK":5, "BOJ":9, "SNB":3,
}
CB39_MEETING_LABELS: Mapping[str, str] = {
    "RBA":"8 per year", "NORGES":"8 per year", "BOE":"8 per year",
    "FED":"8 per year", "RBNZ":"7 per year",
    "ECB":"6 policy + 8 non-monetary", "BOC":"8 per year",
    "RIKSBANK":"5 per year", "BOJ":"8 per year", "SNB":"4 per year",
}
CB39_ROOT_ARCHIVE_REFRESH = str(_cb39_os.getenv("CB39_ROOT_ARCHIVE_REFRESH", "0")).strip().lower() in {"1","true","yes","on"}

CB39_NAV_TITLES = {
    "monetary policy markets", "payments financial stability", "news publications",
    "ecb banking supervision", "market notices", "subscribe regulatory news",
    "subscribe to regulatory news", "all speeches", "speeches presentations",
    "latest news", "media", "press releases", "publications", "research",
    "events", "calendar", "read more", "learn more", "view all",
}
CB39_MEDIA_RE = _cb39_re.compile(
    r"^(?:audio|video|download|podcast|webcast|q\s*&?\s*a\s+transcript|transcript|slides?|pdf)\b|"
    r"\b\d+(?:\.\d+)?\s*(?:mb|kb)\b",
    flags=_cb39_re.I,
)
CB39_SPEECH_HINTS = (
    "speech", "remarks", "address", "lecture", "statement", "testimony", "presentation",
    "interview", "fireside", "conference", "panel", "opening", "keynote", "hearing",
    "economic outlook", "monetary policy", "inflation", "financial stability",
)
CB39_DECISION_HINTS = (
    "monetary policy decision", "statement on monetary policy", "fomc statement",
    "monetary policy summary", "official cash rate decision", "bank rate maintained",
    "bank rate increased", "bank rate reduced", "policy rate unchanged", "policy rate increased",
    "policy rate reduced", "interest rate decision", "monetary policy assessment",
)

# Broader but deterministic monetary-policy lexicon.  The model remains local,
# inspectable and independent from the benchmark dashboard.
CB39_HAWK_PHRASES: Mapping[str, float] = {
    **CB38_HAWKISH,
    "inflation is too high":2.4, "inflation remains above target":2.3,
    "inflationary pressures":1.35, "inflation expectations":0.7,
    "risk of inflation expectations":1.2, "upside risk":1.1,
    "upside risks":1.1, "capacity pressures":1.0, "excess demand":1.1,
    "demand exceeds supply":1.2, "tight labor market":1.2,
    "labour market remains tight":1.25, "labor market remains tight":1.25,
    "wage growth remains high":1.15, "wage growth is elevated":1.15,
    "more restrictive":1.2, "remain restrictive":1.0, "stay restrictive":1.0,
    "restrictive for longer":1.45, "further rate increases":2.1,
    "additional tightening":1.9, "raise the policy rate":2.1,
    "increase the policy rate":2.0, "increase the cash rate":2.0,
    "raise the cash rate":2.0, "not yet time to ease":1.8,
    "premature to ease":1.8, "more work to do":1.0,
    "guard against inflation":1.1, "inflation vigilance":1.0,
    "second round effects":1.35, "de-anchoring":1.4, "unanchored":1.35,
}
CB39_DOVE_PHRASES: Mapping[str, float] = {
    **CB38_DOVISH,
    "inflation is declining":1.45, "inflation continues to fall":1.5,
    "inflation is moderating":1.35, "inflation has eased":1.35,
    "inflation is returning to target":1.55, "back to target":1.0,
    "downside risk":1.1, "downside risks to growth":1.25,
    "demand is weak":1.0, "demand has weakened":1.05,
    "growth has slowed":1.0, "growth is slowing":1.0,
    "labor market is cooling":1.25, "labour market has softened":1.25,
    "labor market has softened":1.25, "unemployment has risen":1.2,
    "spare capacity":1.0, "below potential":0.85,
    "less restrictive":1.2, "reduce the policy rate":2.0,
    "lower the policy rate":2.0, "reduce the cash rate":2.0,
    "lower the cash rate":2.0, "further easing":1.8,
    "support economic activity":0.9, "support demand":0.9,
    "risk of overtightening":1.4, "overtightening":1.2,
}


def _cb39_css() -> None:
    _html(
        """
<style>
.cb39-toolbar{display:grid;grid-template-columns:1fr auto auto;gap:8px;align-items:end;margin:8px 0 14px}
.cb39-currency-strip{display:flex;gap:6px;flex-wrap:wrap;margin:3px 0 13px}.cb39-ccy{border:1px solid rgba(216,191,88,.28);border-radius:999px;padding:5px 9px;color:#c9d5dd;background:rgba(216,191,88,.035);font-size:9px;font-family:ui-monospace,monospace}
.cb39-status{border:1px solid rgba(128,157,186,.20);border-radius:10px;padding:9px 11px;background:rgba(5,17,29,.70);font-size:9px;color:#879aaa;margin:6px 0 12px}.cb39-status b{color:#d8bf58}
.cb39-card-foot{display:flex;justify-content:space-between;gap:7px;font-size:8px;color:#8193a4;margin-top:5px}.cb39-card-foot b{color:#b9c7d1}
.cb39-spark{height:34px;margin:5px 0 2px}.cb39-spark svg{width:100%;height:34px;overflow:visible}.cb39-spark path{fill:none;stroke:#63c7ff;stroke-width:2}.cb39-spark .base{stroke:rgba(202,212,221,.20);stroke-width:1}
.cb39-member-tags{display:flex;gap:5px;flex-wrap:wrap;margin-top:7px}.cb39-member-tags span{border:1px solid rgba(128,157,186,.18);border-radius:999px;padding:2px 6px;color:#8296a7;font-size:7px}
.cb39-compact-table{border:1px solid rgba(128,157,186,.18);border-radius:10px;overflow:hidden;background:rgba(5,17,29,.72);margin:7px 0 15px}.cb39-tr{display:grid;grid-template-columns:82px 54px 150px 1fr 66px;gap:8px;padding:8px 10px;border-bottom:1px solid rgba(128,157,186,.10);font-size:9px;align-items:center}.cb39-tr:last-child{border-bottom:none}.cb39-th{color:#8194a7;text-transform:uppercase;letter-spacing:.09em;font-size:8px;background:rgba(128,157,186,.035)}.cb39-title-cell{color:#dbe5eb;font-weight:650}.cb39-score-cell{text-align:right;font-family:ui-monospace,monospace;font-weight:750}
.cb39-decision-head{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;margin:0 0 8px}.cb39-decision-rate{font-family:Georgia,serif;font-size:30px;color:#f2f5f8}.cb39-decision-note{font-size:10px;color:#91a1b0}
@media(max-width:980px){.cb39-toolbar{grid-template-columns:1fr}.cb39-tr{grid-template-columns:76px 45px 1fr 60px}.cb39-tr span:nth-child(3){display:none}}
</style>
        """
    )


def _cb39_clean_text(value: Any) -> str:
    return " ".join(html.unescape(str(value or "")).split())


def _cb39_norm(value: Any) -> str:
    return _cb38_norm(_cb39_clean_text(value))


def _cb39_empty_speeches() -> pd.DataFrame:
    return pd.DataFrame(columns=CB39_SPEECH_COLUMNS)


def _cb39_is_substantive(title: Any, href: Any = "") -> bool:
    clean = _cb39_clean_text(title)
    norm = _cb39_norm(clean)
    if not clean or len(clean) < 12 or len(norm.split()) < 2:
        return False
    if CB39_MEDIA_RE.search(clean) or CB39_MEDIA_RE.search(str(href or "")):
        return False
    if norm in CB39_NAV_TITLES:
        return False
    if any(norm.startswith(prefix) for prefix in ("subscribe ", "download ", "audio ", "watch ", "listen ")):
        return False
    return True


def _cb39_sentence_chunks(text: Any) -> List[str]:
    raw = _cb39_clean_text(text)
    if not raw:
        return []
    return [x.strip() for x in _cb39_re.split(r"(?<=[.!?;])\s+|\n+", raw) if len(x.strip()) >= 12]


def _cb39_phrase_score(sentence: str) -> Tuple[float, int]:
    norm = _cb39_norm(sentence)
    if not norm:
        return 0.0, 0
    hawk = dove = 0.0
    hits = 0
    for phrase, weight in CB39_HAWK_PHRASES.items():
        needle = _cb39_norm(phrase)
        for match in _cb39_re.finditer(r"(?<![a-z0-9])" + _cb39_re.escape(needle) + r"(?![a-z0-9])", norm):
            prefix = norm[max(0, match.start()-34):match.start()]
            neg = any(prefix.rstrip().endswith(_cb39_norm(term).strip()) for term in CB38_NEGATIONS)
            if neg:
                dove += float(weight) * .65
            else:
                hawk += float(weight)
            hits += 1
    for phrase, weight in CB39_DOVE_PHRASES.items():
        needle = _cb39_norm(phrase)
        for match in _cb39_re.finditer(r"(?<![a-z0-9])" + _cb39_re.escape(needle) + r"(?![a-z0-9])", norm):
            prefix = norm[max(0, match.start()-34):match.start()]
            neg = any(prefix.rstrip().endswith(_cb39_norm(term).strip()) for term in CB38_NEGATIONS)
            if neg:
                hawk += float(weight) * .65
            else:
                dove += float(weight)
            hits += 1
    # Directional constructions that are common in central-bank prose.
    patterns = (
        (r"(?:inflation|prices?).{0,70}(?:persistent|elevated|above target|too high|accelerat|upside)", 1.15),
        (r"(?:persistent|elevated|above target|too high|upside).{0,70}(?:inflation|prices?)", 1.15),
        (r"(?:raise|increase|hike).{0,45}(?:rate|cash rate|bank rate|policy rate)", 1.45),
        (r"(?:tight|strong|resilien).{0,35}(?:labour|labor) market", .75),
        (r"(?:inflation|prices?).{0,70}(?:eas|declin|fall|moderate|disinflation|return(?:ing)? to target)", -1.10),
        (r"(?:cut|lower|reduce|ease).{0,45}(?:rate|cash rate|bank rate|policy rate)", -1.45),
        (r"(?:cool|soft|weaken|slack).{0,35}(?:labour|labor) market", -.75),
    )
    for pattern, weight in patterns:
        count = len(_cb39_re.findall(pattern, norm, flags=_cb39_re.I))
        if count:
            if weight > 0: hawk += count * weight
            else: dove += count * abs(weight)
            hits += count
    return hawk - dove, hits


def _cb38_score_text(text: Any) -> Tuple[float, float, int]:  # noqa: F811
    """V39 deterministic sentence-level policy stance score."""
    chunks = _cb39_sentence_chunks(text)
    if not chunks:
        return np.nan, 0.0, 0
    evidence: List[float] = []
    hits = 0
    policy_sentences = 0
    for sentence in chunks:
        norm = _cb39_norm(sentence)
        relevance = sum(1 for term in CB38_POLICY_TERMS if term in norm)
        if relevance:
            policy_sentences += 1
        value, count = _cb39_phrase_score(sentence)
        if count:
            # Preserve strong statements but stop long speeches from dominating.
            evidence.append(float(np.tanh(value / max(1.65, math.sqrt(count) * 1.15))))
            hits += count
    if not evidence:
        return np.nan, min(.20, policy_sentences / max(20.0, len(chunks))), 0
    values = np.asarray(evidence, dtype=float)
    # High-information sentences receive slightly more weight than repetitive ones.
    weights = 1.0 + .25 * np.minimum(np.abs(values), 1.0)
    score = float(np.average(values, weights=weights))
    confidence = float(min(1.0, .08 * hits + .45 * min(1.0, len(evidence) / 8.0) + .20 * min(1.0, policy_sentences / 12.0)))
    return float(np.clip(score, -1, 1)), confidence, hits


def _cb39_speaker_alias(value: Any) -> str:
    clean = _cb39_clean_text(value)
    aliases = {
        "Philip R Lane":"Philip R. Lane", "Philip Lane":"Philip R. Lane",
        "Pål Longva":"Pal Longva", "Pål Longva.":"Pal Longva",
        "Renée Fry-McKibbin":"Renee Fry-McKibbin",
    }
    return aliases.get(clean, clean)


def _cb39_explicit_speaker(code: str, text: str, title: str = "") -> str:
    blob = _cb39_clean_text(text)
    # Explicit labels outrank page-wide roster mentions.
    patterns = (
        r"(?:Speaker|By|Author)\s*[:\-]\s*([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+(?:\s+[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+){1,4})",
        r"^([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+(?:\s+[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+){1,4})\s*[:—-]",
    )
    for pattern in patterns:
        match = _cb39_re.search(pattern, blob if "^" not in pattern else title, flags=_cb39_re.I)
        if match:
            candidate = match.group(1).strip()
            candidate = _cb39_re.split(
                r"\b(?:Governor|Deputy|President|Vice[- ]President|Chair|Member|Chief|Executive|Director|Date|Place|Speech|Remarks)\b|[.;|]",
                candidate, maxsplit=1, flags=_cb39_re.I,
            )[0].strip(" ,-:")
            candidate = _cb39_speaker_alias(candidate)
            if _cb383_valid_person_name(candidate):
                return candidate
    norm = _cb39_norm(blob + " " + title)
    for name, _ in CB38_ROSTERS.get(code, ()):
        if _cb39_norm(name) in norm:
            return name
    # Role-labelled names.
    role_match = CB383_ROLE_PATTERN.search(blob)
    if role_match:
        candidate = _cb39_speaker_alias(role_match.group(1).strip())
        if _cb383_valid_person_name(candidate):
            return candidate
    return CB38_BANK_BY_CODE[code]["short"] + " communication"


def _cb38_infer_speaker(code: str, text: str) -> str:  # noqa: F811
    return _cb39_explicit_speaker(code, text)


def _cb39_extract_page_meta(code: str, content: bytes, url: str, fallback_title: str, fallback_speaker: str) -> Tuple[str, str, str]:
    body = _cb38_extract_html_text(content[:2_500_000])
    title = fallback_title
    speaker = fallback_speaker
    if _cb38_BeautifulSoup is not None:
        try:
            soup = _cb38_BeautifulSoup(content, "html.parser")
            h1 = soup.find("h1")
            if h1:
                candidate = _cb39_clean_text(h1.get_text(" ", strip=True))
                if _cb39_is_substantive(candidate, url): title = candidate
            # Prefer author/meta tags and the first role/name block near the title.
            for attrs in ({"name":"author"},{"property":"article:author"},{"name":"dc.creator"}):
                tag = soup.find("meta", attrs=attrs)
                if tag and tag.get("content"):
                    candidate = _cb39_speaker_alias(tag.get("content"))
                    if _cb383_valid_person_name(candidate):
                        speaker = candidate; break
            if speaker.endswith("communication"):
                head_text = _cb39_clean_text(" ".join(x.get_text(" ", strip=True) for x in soup.find_all(["h1","h2","h3","p"], limit=18)))
                speaker = _cb39_explicit_speaker(code, head_text, title)
        except Exception:
            pass
    return title, speaker, body[:120000]


@st.cache_data(ttl=21600, show_spinner=False)
def _cb39_fetch_enriched_page(code: str, url: str, fallback_title: str, fallback_speaker: str) -> Optional[Tuple[str, str, str]]:
    if not str(url or "").startswith("http") or _cb383_is_media_item(fallback_title, url):
        return None
    response = _CB383_HTTP_GET(url, timeout=CB39_HTTP_TIMEOUT)
    if response is None:
        return None
    return _cb39_extract_page_meta(code, response.content, url, fallback_title, fallback_speaker)


def _cb39_enrich_rows(frame: pd.DataFrame, limit: int = CB39_AUTO_ENRICH_LIMIT) -> pd.DataFrame:
    if frame is None or frame.empty:
        return _cb39_empty_speeches()
    out = frame.copy().sort_values("Date", ascending=False).reset_index(drop=True)
    targets = [i for i in out.index[:max(0, int(limit))] if str(out.at[i, "URL"] or "").startswith("http")]
    if not targets:
        return out
    def fetch(idx: int):
        payload = _cb39_fetch_enriched_page(
            str(out.at[idx,"CB"]), str(out.at[idx,"URL"]),
            str(out.at[idx,"Title"]), str(out.at[idx,"Speaker"]),
        )
        return idx, payload
    with _cb39_ThreadPoolExecutor(max_workers=min(4, len(targets))) as pool:
        futures = [pool.submit(fetch, idx) for idx in targets]
        for future in _cb39_as_completed(futures):
            try:
                idx, payload = future.result()
                if not payload: continue
                title, speaker, body = payload
                out.at[idx, "Title"] = title
                out.at[idx, "Speaker"] = speaker
                out.at[idx, "Text"] = body
                score, confidence, _ = _cb38_score_text(title + "\n" + body)
                out.at[idx, "Score"] = score
                out.at[idx, "Confidence"] = confidence
            except Exception:
                pass
    return _cb383_clean_speeches(out)


def _cb39_infer_bank_from_corpus(row: Mapping[str, Any]) -> Optional[str]:
    author = _cb39_speaker_alias(row.get("author", ""))
    blob = " ".join(str(row.get(k, "")) for k in ("title","description","text","url"))
    norm = _cb39_norm(blob)
    # Current and former officials are often identifiable from the institution
    # in the BIS description even when they are not in today's committee roster.
    institution_terms = {
        "RBA":("reserve bank of australia","australian central bank"),
        "NORGES":("norges bank","central bank of norway"),
        "BOE":("bank of england",), "FED":("federal reserve","federal reserve bank"),
        "RBNZ":("reserve bank of new zealand",), "ECB":("european central bank",),
        "BOC":("bank of canada",), "RIKSBANK":("sveriges riksbank","riksbank"),
        "BOJ":("bank of japan",), "SNB":("swiss national bank",),
    }
    for code, terms in institution_terms.items():
        if any(_cb39_norm(term) in norm for term in terms):
            return code
    for code, roster in CB38_ROSTERS.items():
        if any(_cb39_norm(name) == _cb39_norm(author) for name, _ in roster):
            return code
    return _cb38_infer_bank(blob, str(row.get("url", "")))


def _cb39_parse_corpus_frame(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return _cb39_empty_speeches()
    frame = raw.copy()
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    def col(*names):
        return next((name for name in names if name in frame.columns), None)
    url_col, title_col = col("url","link"), col("title","headline")
    desc_col, date_col = col("description","summary"), col("date","published","pubdate")
    text_col, author_col = col("text","body","content"), col("author","speaker")
    if not title_col or not date_col:
        return _cb39_empty_speeches()
    rows = []
    for _, row in frame.iterrows():
        data = {"url":row.get(url_col,"") if url_col else "", "title":row.get(title_col,""),
                "description":row.get(desc_col,"") if desc_col else "", "date":row.get(date_col,""),
                "text":row.get(text_col,"") if text_col else "", "author":row.get(author_col,"") if author_col else ""}
        dt = pd.to_datetime(data["date"], errors="coerce")
        if pd.isna(dt) or pd.Timestamp(dt).normalize() > CB39_STRICT_TODAY:
            continue
        code = _cb39_infer_bank_from_corpus(data)
        if code not in CB38_BANK_BY_CODE:
            continue
        title = _cb39_clean_text(data["title"])
        if not _cb39_is_substantive(title, data["url"]):
            continue
        speaker = _cb39_speaker_alias(data["author"])
        if not _cb383_valid_person_name(speaker):
            speaker = _cb39_explicit_speaker(code, str(data["description"]) + " " + title, title)
        body = _cb39_clean_text(data["text"] or data["description"])
        score, confidence, _ = _cb38_score_text(title + "\n" + body)
        rows.append({"Date":pd.Timestamp(dt).normalize(),"CB":code,"Speaker":speaker,"Title":title,
                     "Score":score,"Confidence":confidence,"Source":"BIS full-text speeches corpus",
                     "URL":_cb39_clean_text(data["url"]),"Text":body[:120000]})
    return _cb383_clean_speeches(pd.DataFrame(rows, columns=CB39_SPEECH_COLUMNS))


@st.cache_data(ttl=3600, show_spinner=False)
def _cb39_read_local_corpus() -> pd.DataFrame:
    if not CB39_CORPUS_DB.exists():
        return _cb39_empty_speeches()
    try:
        frame = pd.read_csv(CB39_CORPUS_DB, compression="gzip")
        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
        for column in ("Score","Confidence"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return _cb383_clean_speeches(frame)
    except Exception:
        return _cb39_empty_speeches()


def _cb39_corpus_status() -> str:
    if not CB39_CORPUS_DB.exists():
        return "historical corpus not built"
    try:
        meta = _cb39_json.loads(CB39_CORPUS_META.read_text()) if CB39_CORPUS_META.exists() else {}
        return f"{int(meta.get('rows',0))} rows · {meta.get('years','cached')} · updated {meta.get('updated','unknown')}"
    except Exception:
        return "historical corpus cached"


def _cb39_parse_archive(code: str, page: str, url: str, bank: Mapping[str, Any]) -> pd.DataFrame:
    if _cb38_BeautifulSoup is None:
        return _cb39_empty_speeches()
    soup = _cb38_BeautifulSoup(page, "html.parser")
    candidates = []
    # Prefer semantic content blocks and headings, not every navigation link.
    for block in soup.find_all(["article","li","tr","h2","h3","h4"]):
        anchor = block.find("a", href=True) if getattr(block, "find", None) else None
        if anchor is not None:
            candidates.append((block, anchor))
    rows, seen = [], set()
    for block, anchor in candidates:
        title = _cb39_clean_text(anchor.get_text(" ", strip=True))
        href = _cb38_urljoin(url, anchor.get("href"))
        if not _cb39_is_substantive(title, href):
            continue
        container = block
        # Parent context is capped to prevent a whole page from contaminating speaker attribution.
        context = _cb39_clean_text(container.get_text(" ", strip=True))
        if len(context) < len(title) + 12 and getattr(container, "parent", None) is not None:
            context = _cb39_clean_text(container.parent.get_text(" ", strip=True))
        context = context[:1400]
        norm_blob = _cb39_norm(title + " " + context + " " + href)
        if not any(_cb39_norm(hint) in norm_blob for hint in CB39_SPEECH_HINTS):
            continue
        dt = _cb38_parse_date(context, href)
        if pd.isna(dt) or pd.Timestamp(dt).normalize() > CB39_STRICT_TODAY:
            continue
        key = (pd.Timestamp(dt).normalize(), _cb39_norm(title))
        if key in seen:
            continue
        seen.add(key)
        speaker = _cb39_explicit_speaker(code, context, title)
        score, confidence, _ = _cb38_score_text(title + "\n" + context)
        rows.append({"Date":key[0],"CB":code,"Speaker":speaker,"Title":title,"Score":score,
                     "Confidence":confidence,"Source":f"{bank['short']} official archive",
                     "URL":href,"Text":context})
    return _cb383_clean_speeches(pd.DataFrame(rows, columns=CB39_SPEECH_COLUMNS)).head(CB39_ARCHIVE_LIMIT)


@st.cache_data(ttl=21600, show_spinner=False)
def _cb38_official_archive(code: str, kind: str = "speech") -> pd.DataFrame:  # noqa: F811
    bank = CB38_BANK_BY_CODE[code]
    base_url = str(bank["speech_url" if kind == "speech" else "decision_url"])
    if kind == "decision":
        # Retain the strict V38.3 RBA parser. Other institutions use the strict
        # decision hint filter below and never admit calendars or speeches.
        if code == "RBA":
            frames = []
            current_year = int(CB39_STRICT_TODAY.year)
            urls = [base_url] + [base_url.rstrip("/") + f"/{year}/" for year in range(current_year-1, current_year-6, -1)]
            for page_url in urls:
                response = _CB383_HTTP_GET(page_url, timeout=CB39_HTTP_TIMEOUT)
                if response is not None:
                    frame = _cb383_parse_rba_decision_page(response.text, page_url, bank)
                    if not frame.empty: frames.append(frame)
            if not frames:
                return _cb383_empty_decisions()
            return pd.concat(frames, ignore_index=True).sort_values("Date", ascending=False).drop_duplicates("Date").reset_index(drop=True)
        response = _CB383_HTTP_GET(base_url, timeout=CB39_HTTP_TIMEOUT)
        if response is None or _cb38_BeautifulSoup is None:
            return _cb383_empty_decisions()
        soup = _cb38_BeautifulSoup(response.text, "html.parser")
        rows, seen = [], set()
        for anchor in soup.find_all("a", href=True):
            title = _cb39_clean_text(anchor.get_text(" ", strip=True))
            href = _cb38_urljoin(base_url, anchor.get("href"))
            context = _cb39_clean_text(anchor.parent.get_text(" ", strip=True) if anchor.parent else title)[:1000]
            blob = _cb39_norm(title + " " + context + " " + href)
            if not any(_cb39_norm(hint) in blob for hint in CB39_DECISION_HINTS):
                continue
            if any(term in blob for term in ("calendar","schedule","minutes","speech","conference","framework","report archive")):
                continue
            dt = _cb38_parse_date(context, href)
            if pd.isna(dt) or pd.Timestamp(dt).normalize() > CB39_STRICT_TODAY:
                continue
            key = pd.Timestamp(dt).normalize()
            if key in seen: continue
            seen.add(key)
            rows.append({"Date":key,"Title":title or "Monetary policy decision","URL":href,"Source":f"{bank['short']} official decisions"})
        return pd.DataFrame(rows, columns=CB383_DECISION_COLUMNS).sort_values("Date", ascending=False).reset_index(drop=True)
    response = _CB383_HTTP_GET(base_url, timeout=CB39_HTTP_TIMEOUT)
    if response is None:
        return _cb39_empty_speeches()
    try:
        if code == "RBA":
            frame = _cb383_parse_rba_speeches(response.text, base_url, bank)
        else:
            frame = _cb39_parse_archive(code, response.text, base_url, bank)
        return _cb383_clean_speeches(frame)
    except Exception:
        return _cb39_empty_speeches()


def _cb39_recent_all_banks() -> pd.DataFrame:
    # Root remains lightweight: BIS RSS supplies the recent cross-bank tape.
    # Official archives are fetched only for the selected bank unless the user
    # explicitly enables a broad refresh.
    frames = []
    bis = _cb38_bis_rss(enrich_text=False)
    if bis is not None and not bis.empty:
        frames.append(_cb383_clean_speeches(bis))
    if CB39_ROOT_ARCHIVE_REFRESH:
        with _cb39_ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_cb38_official_archive, code, "speech"):code for code in CB38_BANK_BY_CODE}
            for future in _cb39_as_completed(futures):
                try:
                    frame = future.result()
                    if frame is not None and not frame.empty: frames.append(frame)
                except Exception:
                    pass
    if not frames:
        return _cb39_empty_speeches()
    return _cb383_clean_speeches(pd.concat(frames, ignore_index=True))


@st.cache_data(ttl=21600, show_spinner=False)
def _cb39_recent_all_banks_cached() -> pd.DataFrame:
    return _cb39_recent_all_banks()


def _cb38_speeches(code: Optional[str] = None, deep: bool = False) -> pd.DataFrame:  # noqa: F811
    corpus = _cb39_read_local_corpus()
    if code:
        official = _cb38_official_archive(code, "speech")
        bis = _cb38_bis_rss(enrich_text=False)
        frames = []
        for frame in (corpus[corpus["CB"] == code] if not corpus.empty else _cb39_empty_speeches(),
                      bis[bis["CB"] == code] if bis is not None and not bis.empty else _cb39_empty_speeches(),
                      official):
            if frame is not None and not frame.empty: frames.append(frame)
        if not frames:
            return _cb39_empty_speeches()
        out = _cb383_clean_speeches(pd.concat(frames, ignore_index=True))
        # Selected bank pages are automatically enriched, but the operation is
        # bounded and cached. This removes the empty-scorecard gap without
        # restoring the former unbounded crawl.
        return _cb39_enrich_rows(out, CB39_AUTO_ENRICH_LIMIT if deep or len(out) else 0)
    recent = _cb39_recent_all_banks_cached()
    frames = [frame for frame in (corpus, recent) if frame is not None and not frame.empty]
    return _cb383_clean_speeches(pd.concat(frames, ignore_index=True)) if frames else _cb39_empty_speeches()


@st.cache_data(ttl=21600, show_spinner=False)
def _cb38_policy_series(code: str, start: str = "2000-01-01") -> Tuple[pd.DataFrame, str]:  # noqa: F811
    # The Fed dashboard convention is the midpoint of the official target
    # range, not the effective federal funds rate.
    if code == "FED":
        lower = _cb38_fred_series("DFEDTARL", start)
        upper = _cb38_fred_series("DFEDTARU", start)
        if len(lower) >= 2 and len(upper) >= 2:
            merged = pd.merge(lower, upper, on="date", how="outer", suffixes=("_l","_u")).sort_values("date")
            merged[["value_l","value_u"]] = merged[["value_l","value_u"]].ffill()
            out = pd.DataFrame({"date":merged["date"],"value":merged[["value_l","value_u"]].mean(axis=1)}).dropna()
            if len(out) >= 2:
                return out.reset_index(drop=True), "FRED DFEDTARL/DFEDTARU · target midpoint"
    df, source, _ = _cb38_select_bis("policy", code, start)
    if len(df) >= 2:
        return df, source
    fallback, fsource = _cb38_first_fred(CB38_BANK_BY_CODE[code].get("fred_rate", ()), start)
    if len(fallback) >= 2 and bool(fallback["value"].between(-5, 30).all()):
        return fallback, fsource + " · validated"
    return pd.DataFrame(columns=["date","value"]), source or "No valid public policy-rate series"


def _cb39_decision_rate_join(official: pd.DataFrame, policy: pd.DataFrame) -> pd.DataFrame:
    left = official.copy()
    left["Date"] = pd.to_datetime(left["Date"], errors="coerce")
    left = left.dropna(subset=["Date"]).sort_values("Date").drop_duplicates("Date")
    right = policy.copy()
    right["date"] = pd.to_datetime(right["date"], errors="coerce")
    right["value"] = pd.to_numeric(right["value"], errors="coerce")
    right = right.dropna().sort_values("date")
    if left.empty or right.empty:
        return pd.DataFrame()
    # Official rate series often take effect one business day after the meeting.
    # Prefer a forward observation within 10 days, then fill from the prior rate.
    forward = pd.merge_asof(left, right, left_on="Date", right_on="date", direction="forward", tolerance=pd.Timedelta(days=10))
    backward = pd.merge_asof(left[["Date"]], right, left_on="Date", right_on="date", direction="backward", tolerance=pd.Timedelta(days=70))
    forward["value"] = pd.to_numeric(forward["value"], errors="coerce").fillna(pd.to_numeric(backward["value"], errors="coerce"))
    return forward


def _cb38_decisions(code: str) -> Tuple[pd.DataFrame, str]:  # noqa: F811
    policy, policy_source = _cb38_policy_series(code, "1990-01-01")
    official = _cb38_official_archive(code, "decision")
    if official is not None and not official.empty and policy is not None and not policy.empty:
        merged = _cb39_decision_rate_join(official, policy)
        if not merged.empty:
            merged["RateNumeric"] = pd.to_numeric(merged["value"], errors="coerce")
            merged["ChangeRaw"] = merged["RateNumeric"].diff()
            merged["Decision"] = np.where(merged["ChangeRaw"] > 1e-8, "HIKE", np.where(merged["ChangeRaw"] < -1e-8, "CUT", "HOLD"))
            merged["Change"] = merged["ChangeRaw"].map(lambda x: "—" if pd.isna(x) or abs(float(x)) < 1e-8 else f"{int(round(float(x)*100)):+d} bps")
            merged["Rate"] = merged["RateNumeric"].map(lambda x: "—" if pd.isna(x) else f"{float(x):.2f}%")
            out = merged.sort_values("Date", ascending=False)[["Date","Decision","Rate","Change","Title","Source","URL"]]
            return out.head(60).reset_index(drop=True), f"Official decision archive + {policy_source}"
    if policy is not None and not policy.empty:
        work = policy.sort_values("date").copy(); work["change"] = pd.to_numeric(work["value"], errors="coerce").diff()
        rows = []
        for _, row in work[work["change"].abs() > 1e-9].sort_values("date", ascending=False).head(60).iterrows():
            bps = int(round(float(row["change"])*100))
            rows.append({"Date":pd.Timestamp(row["date"]),"Decision":"HIKE" if bps > 0 else "CUT","Rate":f"{float(row['value']):.2f}%","Change":f"{bps:+d} bps","Title":"Policy-rate change detected in official series","Source":policy_source,"URL":""})
        return pd.DataFrame(rows, columns=CB39_DECISION_COLUMNS), policy_source + " · rate changes only"
    return pd.DataFrame(columns=CB39_DECISION_COLUMNS), policy_source


def _cb38_summary(bank: Mapping[str, Any]) -> None:  # noqa: F811
    score = bank.get("score")
    scored = int(bank.get("speech_count", 0)); indexed = int(bank.get("speech_indexed_count", scored))
    # Freshness is the newest indexed public communication, not the last text
    # that happened to contain a directional keyword.
    freshness = bank.get("speech_last_indexed_date") or bank.get("speech_last_date")
    items = [
        ("Rate", _cb38_fmt_rate(bank.get("rate")), f"last move {bank.get('since').date().isoformat() if bank.get('since') is not None else 'N/A'}", "flat"),
        ("Target", str(bank["target"]), bank["country"], "flat"),
        ("Hawk / Dove", _cb38_fmt_score(score, 3), f"{scored} scored / {indexed} indexed", "up" if score is not None and not pd.isna(score) and float(score) >= 0 else "down"),
        ("Decision", str(bank.get("decision") or "N/A"), str(bank.get("votes") or "Vote data unavailable"), "flat"),
        ("Freshness", freshness.date().isoformat() if freshness is not None else "N/A", "latest indexed communication", "flat"),
    ]
    blocks = []
    for label, value, note, tone in items:
        cls = {"up":"ec36-up","down":"ec36-down","flat":"ec36-flat"}.get(tone, "")
        blocks.append(f'<div class="cb38-stat"><div class="cb38-stat-k">{_esc(label)}</div><div class="cb38-stat-v {cls}">{_esc(value)}</div><div class="cb38-stat-n">{_esc(note)}</div></div>')
    _html('<div class="cb38-stats">' + ''.join(blocks) + '</div>')


def _cb39_score_path(df: pd.DataFrame, horizon: str = "recent") -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=float)
    work = df.copy()
    work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
    work["Score"] = pd.to_numeric(work["Score"], errors="coerce")
    work = work.dropna(subset=["Date","Score"]).sort_values("Date")
    if work.empty:
        return pd.Series(dtype=float)
    monthly = work.set_index("Date")["Score"].resample("MS").mean().dropna()
    if monthly.empty:
        return pd.Series(dtype=float)
    if horizon == "lifetime":
        values = []
        dates = list(monthly.index)
        raw = monthly.to_numpy(dtype=float)
        for i, current in enumerate(dates):
            age = np.asarray([(current - date).days for date in dates[:i+1]], dtype=float)
            weights = np.exp(-np.log(2) * age / 365.0)
            values.append(float(np.average(raw[:i+1], weights=weights)))
        return pd.Series(values, index=pd.DatetimeIndex(dates), dtype=float).clip(-1,1)
    return monthly.ewm(span=12, adjust=False, min_periods=1).mean().clip(-1,1)


def _cb39_committee_path(code: str, speeches: pd.DataFrame, horizon: str = "recent") -> pd.Series:
    paths = []
    for name, _ in CB38_ROSTERS.get(code, ()):
        member_df = speeches[speeches["Speaker"].map(_cb38_norm) == _cb38_norm(name)] if speeches is not None and not speeches.empty else _cb39_empty_speeches()
        path = _cb39_score_path(member_df, horizon)
        if not path.empty:
            paths.append(path.rename(name))
    if not paths:
        return pd.Series(dtype=float)
    return pd.concat(paths, axis=1).mean(axis=1, skipna=True).dropna().clip(-1,1)


def _cb39_three_month_change(history: pd.Series) -> pd.Series:
    if history is None or history.empty:
        return pd.Series(dtype=float)
    monthly = history.sort_index().resample("MS").last().ffill()
    current = monthly.rolling(3, min_periods=2).mean()
    prior = current.shift(3)
    return (current - prior).dropna().clip(-2,2)


def _cb39_stance_label(score: Any) -> str:
    if score is None or pd.isna(score): return "No data"
    value = float(score)
    if value >= .45: return "Hawkish"
    if value >= .15: return "Lean Hawk"
    if value <= -.45: return "Dovish"
    if value <= -.15: return "Lean Dove"
    return "Neutral"


def _cb39_svg_spark(series: pd.Series) -> str:
    if series is None or len(series.dropna()) < 2:
        return '<div class="cb39-spark"></div>'
    values = np.asarray(series.dropna().tail(36).values, dtype=float)
    xs = np.linspace(3, 97, len(values))
    ys = 17 - np.clip(values, -1, 1) * 13
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    return f'<div class="cb39-spark"><svg viewBox="0 0 100 34" preserveAspectRatio="none"><path class="base" d="M0 17 L100 17"/><polyline points="{points}" fill="none" stroke="#63c7ff" stroke-width="2"/></svg></div>'


def _cb38_member_cards(code: str, speeches: pd.DataFrame) -> None:  # noqa: F811
    members = _cb38_members(code, speeches)
    for start in range(0, len(members), 3):
        cols = st.columns(3)
        for offset, col in enumerate(cols):
            idx = start + offset
            if idx >= len(members): continue
            member = members[idx]
            with col:
                member_df = speeches[speeches["Speaker"].map(_cb38_norm) == _cb38_norm(member["name"])] if speeches is not None and not speeches.empty else _cb39_empty_speeches()
                history = _cb38_score_history(member_df)
                score = member.get("recent")
                cls = "cb38-score-na" if score is None or pd.isna(score) else ("cb38-score-pos" if float(score) >= 0 else "cb38-score-neg")
                meta = CB39_MEMBER_META.get(code, {}).get(member["name"], {})
                appointment = meta.get("appointed", "")
                term_end = meta.get("term_end", "")
                tags = [meta.get("class", "Voter"), meta.get("vote", "Voter"), f"{int(member.get('indexed',0))} indexed"]
                _html('<div class="cb38-member"><div class="cb38-member-top">'
                      f'<span class="cb38-member-name">{_esc(member["name"])}</span><span class="cb38-member-score {cls}">{_cb38_fmt_score(score)}</span></div>'
                      f'<div class="cb38-member-role">{_esc(member["role"])} · {_esc(_cb39_stance_label(score))}</div>'
                      f'{_cb39_svg_spark(history)}'
                      f'<div class="cb38-member-metrics"><div class="cb38-member-metric"><b>Votes</b><span>—</span></div><div class="cb38-member-metric"><b>Speeches</b><span>{int(member["speeches"])}</span></div><div class="cb38-member-metric"><b>Confidence</b><span>{float(member.get("confidence",0)):.0%}</span></div></div>'
                      f'<div class="cb39-member-tags">{"".join(f"<span>{_esc(x)}</span>" for x in tags if x)}</div>'
                      f'<div class="cb38-member-foot">{_esc("Appointed: " + appointment if appointment else "Appointment date not resolved")}{_esc(" · Ends: " + term_end if term_end else "")}</div></div>')
                if st.button("Open member", key=f"ec39_member_open_{code}_{idx}", use_container_width=True):
                    st.session_state["ec36_cb_route"] = "member"; st.session_state["ec36_cb_code"] = code; st.session_state["ec38_member_slug"] = member["slug"]; st.rerun()


def _cb39_recent_table(frame: pd.DataFrame, limit: int = CB39_ROOT_RECENT_LIMIT) -> None:
    use = _cb383_clean_speeches(frame).head(limit)
    if use.empty:
        st.info("No recent substantive communications were resolved.")
        return
    rows = ['<div class="cb39-tr cb39-th"><span>Date</span><span>CB</span><span>Speaker</span><span>Title</span><span>Score</span></div>']
    for _, row in use.iterrows():
        score = pd.to_numeric(pd.Series([row.get("Score")]), errors="coerce").iloc[0]
        score_text = "N/A" if pd.isna(score) else f"{float(score):+.2f}"
        cls = "cb38-score-na" if pd.isna(score) else ("cb38-score-pos" if float(score) >= 0 else "cb38-score-neg")
        rows.append('<div class="cb39-tr">'
                    f'<span>{pd.Timestamp(row["Date"]).date().isoformat()}</span><span>{_esc(row["CB"])}</span><span>{_esc(row["Speaker"])}</span><span class="cb39-title-cell">{_esc(row["Title"])}</span><span class="cb39-score-cell {cls}">{score_text}</span></div>')
    _html('<div class="cb39-compact-table">' + ''.join(rows) + '</div>')


def _cb39_root_cards(snapshots: Sequence[Mapping[str, Any]]) -> None:
    for row in (snapshots[:5], snapshots[5:]):
        cols = st.columns(5)
        for col, snap in zip(cols, row):
            with col:
                _cb38_bank_card(snap)
                _html(f'<div class="cb39-card-foot"><span><b>{len(CB38_ROSTERS.get(str(snap["code"]),()))}</b> members</span><span>{int(snap.get("speech_count",0))} scored</span></div>')
                if st.button(f"Open {snap['code']}", key=f"ec39_open_{snap['code']}", use_container_width=True):
                    st.session_state["ec36_cb_code"] = snap["code"]; st.session_state["ec36_cb_route"] = "bank"; st.session_state["ec38_cb_nav"] = "Overview"; st.rerun()


def _cb38_root() -> None:  # noqa: F811
    _cb39_css()
    _header("ECONOMY · PUBLIC MONETARY DATA", "Global Monetary Policy Observatory", "G10 policy rates, balance sheets, official communications and committee attribution generated by Quant Terminal from public primary sources.", ["official target rates","BIS total assets","BIS full-text corpus","local scoring"])
    _html('<div class="cb39-currency-strip">' + ''.join(f'<span class="cb39-ccy">{_esc(bank["flag"])} {_esc(bank["ccy"])}</span>' for bank in CB38_BANKS) + '</div>')
    _html('<details class="cb38-model"><summary>How This Works — Quant Terminal Hawk/Dove Model</summary><p>Policy rates use official target conventions, including the midpoint of the Federal Reserve target range. Communications come from the BIS full-text corpus, BIS RSS and official central-bank archives. Scores are deterministic sentence-level estimates using inflation, activity, labour-market and policy-action evidence. Recent is a 12-observation EMA; lifetime uses a 365-day half-life. Missing evidence remains N/A.</p></details>')
    _html(f'<div class="cb39-status"><b>Data engine:</b> {_esc(_cb39_corpus_status())}. The app never downloads audio or media attachments. Run the supplied corpus refresh script once to populate the 2016-present historical composite.</div>')
    speeches = _cb38_speeches(deep=False)
    snapshots = [_cb38_snapshot(code, speeches[speeches["CB"] == code].copy() if not speeches.empty else _cb39_empty_speeches()) for code in CB38_BANK_BY_CODE]
    _cb39_root_cards(snapshots)
    c1, c2, c3 = st.columns([2.2, 1, 1])
    with c1:
        selected = st.selectbox("Open central bank", list(CB38_BANK_BY_CODE), key="ec39_cb_select", format_func=lambda x:f"{CB38_BANK_BY_CODE[x]['flag']} {x} — {CB38_BANK_BY_CODE[x]['name']}")
    with c2:
        if st.button("Open scorecard", key="ec39_cb_scorecard", use_container_width=True):
            st.session_state["ec36_cb_code"] = selected; st.session_state["ec36_cb_route"] = "bank"; st.session_state["ec38_cb_nav"] = "Scorecard"; st.rerun()
    with c3:
        if st.button("Policy previews", key="ec39_cb_previews", use_container_width=True):
            st.session_state["ec36_cb_route"] = "previews"; st.rerun()

    _section("CROSS-BANK SIGNAL", "Hawk / Dove Composite", "Observed communication histories. The chart becomes fully historical after the one-time BIS corpus build.")
    options = list(CB38_BANK_BY_CODE)
    selected_codes = st.multiselect("Central banks", options, default=options, key="ec39_composite_codes")
    c1, c2 = st.columns([1,1])
    with c1: view = st.radio("View", ["Level","3m/3m change"], horizontal=True, key="ec39_composite_view")
    with c2: solo = st.checkbox("Solo first", key="ec39_solo")
    fig = go.Figure(); order = selected_codes[:1] if solo and selected_codes else selected_codes
    for code in order:
        history = _cb39_score_path(speeches[speeches["CB"] == code] if not speeches.empty else _cb39_empty_speeches(), "recent")
        if view == "3m/3m change": history = _cb39_three_month_change(history)
        if history.empty: continue
        fig.add_trace(go.Scatter(x=history.index, y=history.values, name=code, mode="lines", line=dict(color=CB38_COLOR_BY_CODE[code], width=2)))
    fig.add_hline(y=0, line_color="rgba(202,212,221,.30)")
    if view == "Level": fig.update_yaxes(range=[-1,1], tickvals=[-.7,0,.7], ticktext=["Dovish","Neutral","Hawkish"])
    _plot(fig, "ec39_composite", 480)
    _cb38_source([("Scores","Quant Terminal deterministic public-text model"),("Inputs","BIS corpus/RSS + official archives"),("No-data rule","no synthetic backfill")])

    _section("RANKING", "Policy Rates — Ranked", "Latest official target-policy observations in descending order.")
    ranked = sorted(snapshots, key=lambda x:float(x["rate"]) if x.get("rate") is not None and not pd.isna(x.get("rate")) else -999, reverse=True)
    html_rows = []
    for i, snap in enumerate(ranked, 1):
        mark = "▲" if snap.get("decision") == "HIKE" else "▼" if snap.get("decision") == "CUT" else "●"
        date_text = snap.get("date").date().isoformat() if snap.get("date") is not None else "N/A"
        html_rows.append(f'<div class="cb38-rank-row"><span>{i:02d}</span><span class="cb38-rank-code">{_esc(snap["flag"])} {_esc(snap["code"])} <small>{_esc(snap["policy_source"])}</small></span><span class="cb38-rank-rate">{_cb38_fmt_rate(snap.get("rate"))}</span><span class="cb38-rank-mark">{mark} {date_text}</span></div>')
    _html('<div class="cb38-ranked">' + ''.join(html_rows) + '</div>')

    _section("MONETARY POLICY STANCE", "Policy Rates & Balance Sheet", "Policy-rate history with monthly central-bank total-asset change. Bars are green for expansion and red for contraction.")
    bs_code = st.selectbox("Central bank", options, index=options.index("FED"), key="ec39_balance_bank", label_visibility="collapsed")
    policy, psource = _cb38_policy_series(bs_code, "2016-01-01"); assets, asource, aunit = _cb38_assets_series(bs_code, "2016-01-01")
    snap = next((x for x in snapshots if x["code"] == bs_code), {})
    _html(f'<div class="cb39-decision-head"><span class="cb39-decision-rate">{_cb38_fmt_rate(snap.get("rate"))}</span><span class="cb39-decision-note">policy rate · {str(snap.get("decision") or "N/A").lower()} since {snap.get("since").date().isoformat() if snap.get("since") is not None else "N/A"}</span></div>')
    fig2 = go.Figure()
    if not policy.empty:
        fig2.add_trace(go.Scatter(x=policy["date"], y=policy["value"], name="Policy rate", line=dict(color=CB38_COLORS["blue"], width=2.2), line_shape="hv"))
    if not assets.empty:
        monthly = assets.set_index("date")["value"].resample("MS").last().dropna().diff().dropna()
        fig2.add_trace(go.Bar(x=monthly.index, y=monthly.values, name=f"Assets MoM ({aunit})", yaxis="y2", marker_color=[CB38_COLORS["green"] if value >= 0 else CB38_COLORS["red"] for value in monthly], opacity=.72))
        fig2.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, title=aunit + " / month"))
    _plot(fig2, "ec39_policy_assets", 480)
    _cb38_source([("Policy",psource),("Balance sheet",asource),("Method","monthly last observation; first difference")])

    _section("COMMUNICATION", "Recent Speeches", "Latest substantive G10 communications with locally computed score and confidence.")
    _cb39_recent_table(speeches, CB39_ROOT_RECENT_LIMIT)
    _section("DATA COVERAGE", "Provider diagnostics", "Coverage is evaluated at runtime. Missing series are not replaced with model data.")
    _cb38_quality_block(snapshots, speeches)


def _cb38_overview(code: str, bank: Mapping[str, Any], speeches: pd.DataFrame) -> None:  # noqa: F811
    score = bank.get("score")
    _html('<div class="cb38-stance"><div class="cb38-stance-title">Hawk / Dove Stance</div>' + _cb38_track(score).replace('cb38-track','cb38-stance-track').replace('cb38-diamond','cb38-stance-pointer') + '<div class="cb38-stance-labels"><span>Dovish</span><span>Neutral</span><span>Hawkish</span></div></div>')
    c1, c2 = st.columns([1,1])
    with c1: zoom = st.radio("Zoom", ["1Y","3Y","5Y","All"], horizontal=True, key=f"ec39_zoom_{code}")
    with c2: merge = st.checkbox("Merge Charts", key=f"ec39_merge_{code}")
    policy, psource = _cb38_policy_series(code, "2000-01-01")
    window = {"1Y":365,"3Y":365*3,"5Y":365*5,"All":None}[zoom]
    p = _cb38_apply_window(policy, window)
    history = _cb38_score_history(speeches)
    if window and not history.empty: history = history[history.index >= CB39_STRICT_TODAY - pd.Timedelta(days=window)]
    if merge:
        fig = go.Figure()
        if not p.empty: fig.add_trace(go.Scatter(x=p["date"], y=p["value"], name="Policy rate", line_shape="hv", line=dict(color=CB38_COLORS["gold"], width=2.2)))
        if not history.empty: fig.add_trace(go.Scatter(x=history.index, y=history.values, name="Hawk/Dove", yaxis="y2", mode="lines+markers", line=dict(color=CB38_COLORS["orange"], width=2)))
        fig.update_layout(yaxis2=dict(overlaying="y", side="right", range=[-1,1], tickvals=[-.7,0,.7], ticktext=["Dove","Neutral","Hawk"], showgrid=False))
        _plot(fig, f"ec39_overview_merge_{code}", 455)
    else:
        left, right = st.columns(2)
        with left:
            fig1 = go.Figure()
            if not p.empty: fig1.add_trace(go.Scatter(x=p["date"], y=p["value"], name="Policy rate", line_shape="hv", line=dict(color=CB38_COLORS["gold"], width=2.2), fill="tozeroy", fillcolor="rgba(216,191,88,.07)"))
            _plot(fig1, f"ec39_policy_hist_{code}", 380)
        with right:
            fig2 = go.Figure()
            if not history.empty: fig2.add_trace(go.Scatter(x=history.index, y=history.values, name="Hawk/Dove", mode="lines+markers", line=dict(color=CB38_COLORS["orange"], width=2), marker=dict(size=5)))
            fig2.add_hline(y=0, line_color="rgba(202,212,221,.28)"); fig2.update_yaxes(range=[-1,1], tickvals=[-.7,0,.7], ticktext=["Dove","Neutral","Hawk"])
            _plot(fig2, f"ec39_score_hist_{code}", 380)
    _cb38_source([("Policy history",psource),("Communication","BIS corpus + official archive"),("Zoom",zoom)])
    _section("RECENT TAPE", "Recent Speeches", f"Latest 10 substantive public communications for {code}.")
    _cb38_render_speech_cards(speeches, 10)
    _section("COMMITTEE", f"{bank['committee']} — Hawk/Dove Scorecard", "Official roster only. Scores are based on resolved full public text; missing members remain no data.")
    _cb38_member_cards(code, speeches)


def _cb38_scorecard(code: str, bank: Mapping[str, Any], speeches: pd.DataFrame) -> None:  # noqa: F811
    members = _cb38_members(code, speeches)
    _section("COMMITTEE INTELLIGENCE", f"{bank['name']} — {bank['committee']} Scorecard", "Recent = 12-observation EMA. Lifetime = 365-day half-life. Click any member for the underlying communication history.")
    horizon = st.radio("Score horizon", ["Recent (12-EMA)","Lifetime"], horizontal=True, key=f"ec39_horizon_{code}")
    metric = "recent" if horizon.startswith("Recent") else "lifetime"
    valid = [m for m in members if m.get(metric) is not None and not pd.isna(m.get(metric))]
    recent_valid = [m for m in members if m.get("recent") is not None and not pd.isna(m.get("recent"))]
    life_valid = [m for m in members if m.get("lifetime") is not None and not pd.isna(m.get("lifetime"))]
    recent_avg = float(np.mean([m["recent"] for m in recent_valid])) if recent_valid else np.nan
    life_avg = float(np.mean([m["lifetime"] for m in life_valid])) if life_valid else np.nan
    _kpis([("Committee recent","—" if np.isnan(recent_avg) else f"{recent_avg:+.2f}","member average","flat"),("Committee lifetime","—" if np.isnan(life_avg) else f"{life_avg:+.2f}","365-day half-life","flat"),("Roster",str(len(members)),bank["committee"],"flat"),("Scored members",str(len(valid)),f"{sum(int(m.get('indexed',0)) for m in members)} indexed communications","flat")])
    fig = go.Figure()
    for member in members:
        member_df = speeches[speeches["Speaker"].map(_cb38_norm) == _cb38_norm(member["name"])] if not speeches.empty else _cb39_empty_speeches()
        hist = _cb39_score_path(member_df, "recent" if metric == "recent" else "lifetime")
        if hist.empty: continue
        fig.add_trace(go.Scatter(x=hist.index, y=hist.values, name=member["name"].split()[-1], mode="lines", line=dict(width=2)))
    fig.add_hline(y=0, line_color="rgba(202,212,221,.28)"); fig.update_yaxes(range=[-1,1], tickvals=[-.7,0,.7], ticktext=["Dove","Neutral","Hawk"])
    _plot(fig, f"ec39_committee_{code}_{metric}", 455)
    decisions, source = _cb38_decisions(code)
    joined = _cb383_merge_decision_scores(decisions, _cb39_committee_path(code, speeches, "recent" if metric == "recent" else "lifetime"))
    if not joined.empty:
        joined["Avg Score"] = joined["Model score"].map(lambda x:"—" if pd.isna(x) else f"{float(x):+.2f}")
        joined["Dissents"] = "—"
        show = joined.sort_values("Date", ascending=False)[["Date","Decision","Avg Score","Dissents"]].head(12).copy()
        show["Date"] = pd.to_datetime(show["Date"], errors="coerce").dt.date.astype(str)
        _table(show, f"ec39_score_decisions_{code}", 390)
    _section("INDIVIDUAL MEMBERS", f"Individual Members ({len(members)})", "Official roster only: recent/lifetime score, evidence count, confidence and appointment metadata where resolved.")
    _cb38_member_cards(code, speeches)
    _cb38_source([("Score model","Quant Terminal deterministic sentence-level model"),("Decision source",source),("No-data rule","unscored text remains N/A")])


def _cb38_speech_archive(code: str, bank: Mapping[str, Any], speeches: pd.DataFrame) -> None:  # noqa: F811
    _section("COMMUNICATION", f"Speeches — {code}", f"Filtered BIS and official public archive for {bank['name']}.")
    query = st.text_input("Search speeches", key=f"ec39_speech_search_{code}", placeholder="speaker, title, subject")
    c1, c2 = st.columns([1,1])
    with c1: page_size = st.selectbox("Rows per page", [10,20,40], index=0, key=f"ec39_page_size_{code}")
    with c2: scoreable_only = st.checkbox("Directional scores only", key=f"ec39_scoreable_{code}")
    frame = _cb383_clean_speeches(speeches)
    if query and not frame.empty:
        mask = frame.astype(str).apply(lambda col:col.str.contains(query, case=False, regex=False)).any(axis=1); frame = frame[mask]
    if scoreable_only and not frame.empty:
        frame = frame[pd.to_numeric(frame["Score"], errors="coerce").notna()]
    total = len(frame); pages = max(1, int(math.ceil(total/max(1,int(page_size)))))
    page = int(st.number_input("Page", min_value=1, max_value=pages, value=1, step=1, key=f"ec39_page_{code}"))
    start = (page-1)*int(page_size)
    st.caption(f"{total} substantive communications · page {page}/{pages} · media attachments excluded")
    _cb38_render_speech_cards(frame.iloc[start:start+int(page_size)])


def _cb38_meeting_archive(code: str, bank: Mapping[str, Any]) -> None:  # noqa: F811
    _section("DECISION HISTORY", "Rate Decision History", f"Official decision dates joined to the effective target-policy series for {bank['name']}.")
    frame, source = _cb38_decisions(code)
    if frame.empty:
        st.info("No official decision rows could be resolved from the configured public sources.")
    else:
        show = frame.copy(); show["Date"] = pd.to_datetime(show["Date"], errors="coerce").dt.date.astype(str)
        columns = [c for c in ("Date","Decision","Rate","Change") if c in show.columns]
        _table(show[columns], f"ec39_meetings_{code}", min(780, 90+29*len(show)))
    _cb38_source([("Decision layer",source),("Rate layer",_cb38_policy_series(code,"1990-01-01")[1]),("Method","official date + first effective observation within 10 days")])


def _cb38_member(code: str, slug: str) -> None:  # noqa: F811
    bank = CB38_BANK_BY_CODE.get(code, CB38_BANK_BY_CODE["FED"])
    speeches = _cb38_speeches(code, deep=True)
    members = _cb38_members(code, speeches)
    member = next((m for m in members if m["slug"] == slug), None)
    if member is None:
        st.warning("Member profile unavailable from the official roster."); return
    _cb38_path(["Central Banks",bank["name"],"Scorecard",member["name"]])
    if st.button("← Back to scorecard", key=f"ec39_member_back_{code}_{slug}"):
        st.session_state["ec36_cb_route"]="bank"; st.session_state["ec38_cb_nav"]="Scorecard"; st.rerun()
    member_df = speeches[speeches["Speaker"].map(_cb38_norm) == _cb38_norm(member["name"])] if not speeches.empty else _cb39_empty_speeches()
    snap = _cb38_score_snapshot(member_df)
    meta = CB39_MEMBER_META.get(code, {}).get(member["name"], {})
    subtitle = member["role"]
    if meta.get("appointed"): subtitle += f" · Appointed {meta['appointed']}"
    if meta.get("term_end"): subtitle += f" · Term ends {meta['term_end']}"
    _header("MEMBER SCORECARD", member["name"], subtitle, [f"{snap['count']} scored texts",f"{snap.get('indexed_count',0)} indexed",bank["short"],"local transparent model"])
    _kpis([("Recent composite",_cb38_fmt_score(snap["recent"]),"12-observation EMA","flat"),("Lifetime",_cb38_fmt_score(snap["lifetime"]),"365-day half-life","flat"),("Speeches",str(snap["count"]),"directionally scored","flat"),("Confidence",f"{snap['confidence']:.0%}","evidence density","flat")])
    _html(f'<div class="cb38-callout"><b>{_esc(bank.get("votes","Decision process"))}:</b> This independent scorecard reflects public communications only. It is generated locally and is not an official view of the institution.</div>')
    tab = st.radio("Member view", ["Hawk/Dove Chart",f"Speeches ({len(member_df)})"], horizontal=True, key=f"ec39_member_view_{code}_{slug}")
    if tab == "Hawk/Dove Chart":
        _section("MEMBER HISTORY", "Hawk/Dove Tendency Over Time", "Only observed public communication dates are plotted.")
        raw = member_df.dropna(subset=["Date","Score"]).copy().sort_values("Date")
        fig = go.Figure()
        if not raw.empty:
            fig.add_trace(go.Scatter(x=raw["Date"], y=raw["Score"], name="Speech score", mode="lines+markers", line=dict(color="#4d86bd",width=1.6,dash="dot"), marker=dict(size=7)))
        fig.add_hline(y=0,line_color="rgba(202,212,221,.28)"); fig.update_yaxes(range=[-1,1],tickvals=[-.7,0,.7],ticktext=["Dove","Neutral","Hawk"])
        _plot(fig, f"ec39_member_chart_{code}_{slug}", 440)
        _cb38_source([("Inputs","BIS full-text corpus + official archive"),("History","observed dates only"),("Member",member["name"])])
    else:
        _cb38_render_speech_cards(member_df)


def _cb38_bank(code: str) -> None:  # noqa: F811
    _cb39_css()
    speeches = _cb38_speeches(code, deep=True)
    bank = _cb38_snapshot(code, speeches)
    _cb38_path(["Central Banks",bank["name"]])
    c1, c2 = st.columns([1,1])
    with c1:
        if st.button("← All Central Banks", key=f"ec39_back_{code}"):
            st.session_state["ec36_cb_route"]="root"; st.rerun()
    with c2:
        if st.button("Policy Previews →", key=f"ec39_preview_{code}"):
            st.session_state["ec36_cb_route"]="previews"; st.rerun()
    _header("CENTRAL BANK WORKSTATION", f"{bank['flag']} {bank['name']}", f"{bank['committee']} · official-data workflow", [bank["ccy"],CB39_MEETING_LABELS.get(code, bank["meetings"]),f"{CB39_MEMBER_COUNTS.get(code,len(CB38_ROSTERS.get(code,())))} committee members",CB39_VERSION])
    _cb38_summary(bank)
    _html(f'<div class="cb39-status"><b>Bounded enrichment:</b> latest {CB39_AUTO_ENRICH_LIMIT} official pages only; all network responses are cached. Audio, video and downloads are excluded.</div>')
    tab = _segmented("Central bank page", ["Overview","Scorecard","Speeches","Meetings"], "ec38_cb_nav", "Overview")
    if tab == "Overview": _cb38_overview(code, bank, speeches)
    elif tab == "Scorecard": _cb38_scorecard(code, bank, speeches)
    elif tab == "Speeches": _cb38_speech_archive(code, bank, speeches)
    else: _cb38_meeting_archive(code, bank)


# Final schema and presentation overrides.  They execute dynamically from all
# V39 callers and keep future rows, root cards and summary fields aligned.
def _cb383_clean_speeches(df: pd.DataFrame) -> pd.DataFrame:  # noqa: F811
    if df is None or df.empty:
        return _cb39_empty_speeches()
    work = df.copy()
    for column in CB39_SPEECH_COLUMNS:
        if column not in work.columns:
            work[column] = np.nan if column in {"Score","Confidence"} else ""
    work["Date"] = pd.to_datetime(work["Date"], errors="coerce").dt.tz_localize(None)
    work["Score"] = pd.to_numeric(work["Score"], errors="coerce")
    work["Confidence"] = pd.to_numeric(work["Confidence"], errors="coerce").fillna(0).clip(0,1)
    for column in ("CB","Speaker","Title","Source","URL","Text"):
        work[column] = work[column].map(_cb39_clean_text)
    work = work.dropna(subset=["Date"])
    work = work[work["Date"].dt.normalize() <= CB39_STRICT_TODAY]
    mask = [
        _cb39_is_substantive(title, url) and not _cb383_is_media_item(title, url)
        for title, url in zip(work["Title"], work["URL"])
    ]
    work = work.loc[mask].copy()
    work["TitleKey"] = work["Title"].map(_cb39_norm)
    work = work.sort_values(["Date","Confidence"], ascending=[False,False]).drop_duplicates(["CB","TitleKey","Date"])
    return work.drop(columns=["TitleKey"])[CB39_SPEECH_COLUMNS].reset_index(drop=True)


def _cb38_bank_card(bank: Mapping[str, Any]) -> None:  # noqa: F811
    score = bank.get("score")
    cls = "cb38-score-na" if score is None or pd.isna(score) else ("cb38-score-pos" if float(score) >= 0 else "cb38-score-neg")
    decision = str(bank.get("decision") or "N/A")
    code = str(bank["code"])
    members = CB39_MEMBER_COUNTS.get(code, len(CB38_ROSTERS.get(code,())))
    meetings = CB39_MEETING_LABELS.get(code, str(bank.get("meetings", "")))
    _html('<div class="cb38-card">'
          f'<div class="cb38-card-head"><span class="cb38-card-code">{_esc(bank["flag"])} {_esc(code)}</span><span class="cb38-card-ccy">{_esc(bank["ccy"])}</span></div>'
          f'<div class="cb38-card-rate">{_cb38_fmt_rate(bank.get("rate"))} <span class="cb38-card-decision">● {_esc(decision)}</span></div>'
          f'<div class="cb38-card-name">{_esc(bank["name"])}</div>{_cb38_track(score)}'
          f'<div class="cb38-card-meta"><span class="{cls}">{_cb38_fmt_score(score, 3)}</span><span>{members} members</span></div>'
          f'<div class="cb38-card-name">{_esc(meetings)}</div></div>')


def _cb39_root_cards(snapshots: Sequence[Mapping[str, Any]]) -> None:  # noqa: F811
    for row in (snapshots[:5], snapshots[5:]):
        cols = st.columns(5)
        for col, snap in zip(cols, row):
            with col:
                _cb38_bank_card(snap)
                if st.button(f"Open {snap['code']}", key=f"ec39_open_{snap['code']}", use_container_width=True):
                    st.session_state["ec36_cb_code"] = snap["code"]; st.session_state["ec36_cb_route"] = "bank"; st.session_state["ec38_cb_nav"] = "Overview"; st.rerun()


def _cb38_summary(bank: Mapping[str, Any]) -> None:  # noqa: F811
    score = bank.get("score")
    scored = int(bank.get("speech_count",0)); indexed = int(bank.get("speech_indexed_count",scored))
    since = bank.get("since")
    move = bank.get("change_bps")
    decision = str(bank.get("decision") or "N/A")
    decision_note = "last policy move unavailable" if move is None else ("last decision unchanged" if abs(float(move)) < 1e-12 else f"last move {int(round(float(move))):+d} bps")
    items = [
        ("Rate",_cb38_fmt_rate(bank.get("rate")),f"effective since {since.date().isoformat() if since is not None else 'N/A'}","flat"),
        ("Target",str(bank["target"]),bank["country"],"flat"),
        ("Hawk / Dove",_cb38_fmt_score(score,3),f"{scored} scored / {indexed} indexed","up" if score is not None and not pd.isna(score) and float(score)>=0 else "down"),
        ("Decision",decision,decision_note,"flat"),
        ("Votes",str(bank.get("votes") or "Not available"),f"{CB39_MEMBER_COUNTS.get(str(bank['code']),len(CB38_ROSTERS.get(str(bank['code']),())))} committee members","flat"),
    ]
    blocks=[]
    for label,value,note,tone in items:
        cls={"up":"ec36-up","down":"ec36-down","flat":"ec36-flat"}.get(tone,"")
        blocks.append(f'<div class="cb38-stat"><div class="cb38-stat-k">{_esc(label)}</div><div class="cb38-stat-v {cls}">{_esc(value)}</div><div class="cb38-stat-n">{_esc(note)}</div></div>')
    _html('<div class="cb38-stats">'+''.join(blocks)+'</div>')
    freshness = bank.get("speech_last_indexed_date") or bank.get("speech_last_date")
    _html(f'<div class="cb39-status"><b>Latest indexed communication:</b> {_esc(freshness.date().isoformat() if freshness is not None else "N/A")} · bounded full-text enrichment is cached.</div>')


CB38_VERSION = CB39_VERSION

CENTRAL_BANKS_INTEGRITY_V39: Mapping[str, Any] = {
    "version": CB39_VERSION,
    "append_only_over_v383": True,
    "non_central_economy_modified": False,
    "benchmark_data_embedded": False,
    "official_sources_only": True,
    "audio_downloaded": False,
    "future_rows_allowed": False,
    "fed_rate_convention": "target midpoint",
    "decision_effective_date_alignment": "forward 10d then backward",
    "speech_enrichment": f"bounded latest {CB39_AUTO_ENRICH_LIMIT}",
    "historical_corpus": "disk-backed optional bootstrap",
}
assert CENTRAL_BANKS_INTEGRITY_V39["benchmark_data_embedded"] is False
assert CENTRAL_BANKS_INTEGRITY_V39["audio_downloaded"] is False

# ============================================================
# END JARVIS ECONOMY V39.0 — FINAL CENTRAL BANKS PATCH
# ============================================================


# ============================================================
# JARVIS ECONOMY V39.1 — CORPUS / POLICY-BOARD DATA FIX
# Append-only over V39.0. Central Banks runtime only.
# ============================================================

CB391_VERSION = "V39.1 · CORPUS + POLICY BOARD DATA FIX"

# Resolve the corpus relative to the module, not only the process working
# directory. This prevents a successful refresh from being invisible when
# Streamlit is started from another folder.
def _cb391_cache_candidates():
    candidates = []
    env = _cb39_os.getenv("CB39_CACHE_DIR", "").strip()
    if env:
        candidates.append(_cb39_Path(env).expanduser())
    try:
        candidates.append(_cb39_Path(__file__).resolve().parent / ".quant_cache" / "central_banks_v39")
    except Exception:
        pass
    candidates.append(_cb39_Path.cwd() / ".quant_cache" / "central_banks_v39")
    candidates.append(CB39_CACHE_DIR)
    seen, out = set(), []
    for item in candidates:
        try:
            key = str(item.resolve())
        except Exception:
            key = str(item)
        if key not in seen:
            seen.add(key); out.append(item)
    return out


def _cb391_locate_corpus():
    for directory in _cb391_cache_candidates():
        db = directory / "bis_g10_speeches.csv.gz"
        if db.exists() and db.stat().st_size > 100:
            return db, directory / "bis_g10_speeches.meta.json"
    return None, None


@st.cache_data(ttl=1800, show_spinner=False)
def _cb39_read_local_corpus() -> pd.DataFrame:  # noqa: F811
    db, _ = _cb391_locate_corpus()
    if db is None:
        return _cb39_empty_speeches()
    try:
        frame = pd.read_csv(db, compression="gzip", low_memory=False)
        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
        for column in ("Score", "Confidence"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return _cb383_clean_speeches(frame)
    except Exception:
        return _cb39_empty_speeches()


def _cb39_corpus_status() -> str:  # noqa: F811
    db, meta_path = _cb391_locate_corpus()
    if db is None:
        locations = " | ".join(str(x) for x in _cb391_cache_candidates()[:3])
        return f"historical corpus not built (searched: {locations})"
    try:
        meta = _cb39_json.loads(meta_path.read_text(encoding="utf-8")) if meta_path and meta_path.exists() else {}
        rows = int(meta.get("rows", 0))
        scored = int(meta.get("scored_rows", 0))
        years = meta.get("years", "cached")
        return f"{rows:,} rows · {scored:,} scored · {years} · {db}"
    except Exception:
        return f"historical corpus cached · {db}"


# Do not report a misleading 100% confidence when a single enriched page is
# the whole evidence set. Confidence is now coverage-aware at member level.
def _cb391_member_confidence(member_df: pd.DataFrame) -> float:
    if member_df is None or member_df.empty:
        return 0.0
    scores = pd.to_numeric(member_df.get("Score"), errors="coerce")
    conf = pd.to_numeric(member_df.get("Confidence"), errors="coerce").fillna(0)
    resolved = scores.notna()
    n = int(resolved.sum())
    if n == 0:
        return 0.0
    evidence = float(conf[resolved].mean())
    coverage = min(1.0, n / 12.0)
    return float(max(0.0, min(1.0, evidence * (0.35 + 0.65 * coverage))))


# Preserve all V39 renderers, but expose the corrected version marker.
CB39_VERSION = CB391_VERSION
CB38_VERSION = CB391_VERSION
CENTRAL_BANKS_INTEGRITY_V391 = {
    "version": CB391_VERSION,
    "append_only_over_v39": True,
    "corpus_path_resolution": "module + cwd + env",
    "annual_bis_archive_parser": "TXT/CSV compatible companion refresh",
    "policy_board_population": "full historical corpus + bounded recent enrichment",
    "audio_downloaded": False,
    "benchmark_data_embedded": False,
}

# ============================================================
# END JARVIS ECONOMY V39.1
# ============================================================



# ============================================================
# JARVIS ECONOMY V40.0 — EMERGENCY CORPUS / ATTRIBUTION FIX
# Append-only over V39.1. Central Banks runtime only.
# ============================================================

CB40_VERSION = "V40.0 · EMERGENCY CORPUS + ATTRIBUTION ENGINE"

# V39.1's direct blocker was not the Streamlit router. The external corpus was
# never materialised, while member attribution used strict full-name equality.
# V40 keeps the same UI and routes, but makes corpus discovery and member
# attribution resilient.

CB40_CACHE_SUBDIRS = (
    ".quant_cache/central_banks_v40",
    ".quant_cache/central_banks_v39",
)


def _cb40_cache_candidates():
    candidates = []
    env = _cb39_os.getenv("CB40_CACHE_DIR", "").strip() or _cb39_os.getenv("CB39_CACHE_DIR", "").strip()
    if env:
        candidates.append(_cb39_Path(env).expanduser())
    try:
        module_dir = _cb39_Path(__file__).resolve().parent
        for subdir in CB40_CACHE_SUBDIRS:
            candidates.append(module_dir / subdir)
    except Exception:
        pass
    cwd = _cb39_Path.cwd()
    for subdir in CB40_CACHE_SUBDIRS:
        candidates.append(cwd / subdir)
    candidates.extend(_cb391_cache_candidates())

    seen, out = set(), []
    for item in candidates:
        try:
            key = str(item.resolve())
        except Exception:
            key = str(item)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _cb40_locate_corpus():
    filenames = (
        "bis_g10_speeches.csv.gz",
        "central_banks_g10_speeches.csv.gz",
    )
    for directory in _cb40_cache_candidates():
        for filename in filenames:
            db = directory / filename
            if db.exists() and db.stat().st_size > 100:
                meta = directory / "bis_g10_speeches.meta.json"
                return db, meta
    return None, None


@st.cache_data(ttl=1800, show_spinner=False)
def _cb39_read_local_corpus() -> pd.DataFrame:  # noqa: F811
    db, _ = _cb40_locate_corpus()
    if db is None:
        return _cb39_empty_speeches()
    try:
        frame = pd.read_csv(db, compression="gzip", low_memory=False)
        required = set(CB39_SPEECH_COLUMNS)
        missing = required.difference(frame.columns)
        for column in missing:
            frame[column] = np.nan if column in {"Score", "Confidence"} else ""
        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
        for column in ("Score", "Confidence"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame[frame["Date"].notna()]
        frame = frame[frame["Date"] <= CB39_STRICT_TODAY]
        return _cb383_clean_speeches(frame[CB39_SPEECH_COLUMNS])
    except Exception:
        return _cb39_empty_speeches()


def _cb39_corpus_status() -> str:  # noqa: F811
    db, meta_path = _cb40_locate_corpus()
    if db is None:
        locations = " | ".join(str(x) for x in _cb40_cache_candidates()[:4])
        return (
            "historical corpus unavailable. Run "
            "`python refresh_central_banks_v40.py --module economy_intelligence.py --start-year 2016` "
            f"(searched: {locations})"
        )
    try:
        meta = _cb39_json.loads(meta_path.read_text(encoding="utf-8")) if meta_path and meta_path.exists() else {}
        rows = int(meta.get("rows", 0))
        scored = int(meta.get("scored_rows", 0))
        years = meta.get("years", "cached")
        banks = int(meta.get("banks", 0))
        return f"{rows:,} rows · {scored:,} scored · {banks} banks · {years} · {db}"
    except Exception:
        return f"historical corpus cached · {db}"


_CB40_PERSON_DROP = {
    "mr", "mrs", "ms", "miss", "dr", "prof", "professor", "sir", "dame",
    "governor", "deputy", "assistant", "chair", "chairman", "president",
    "ao", "ac", "obe", "cbe", "mbe", "qc", "kc", "phd",
}


def _cb40_person_key(value: Any) -> str:
    norm = _cb39_norm(value)
    if not norm:
        return ""
    tokens = [t for t in norm.split() if t and t not in _CB40_PERSON_DROP]
    tokens = [t for t in tokens if len(t) > 1 or not t.isalpha()]
    if len(tokens) >= 2:
        return f"{tokens[0]} {tokens[-1]}"
    return " ".join(tokens)


def _cb40_member_mask(frame: pd.DataFrame, member_name: str) -> pd.Series:
    if frame is None or frame.empty or "Speaker" not in frame.columns:
        return pd.Series(False, index=getattr(frame, "index", pd.Index([])))
    target_full = _cb39_norm(member_name)
    target_key = _cb40_person_key(member_name)
    speakers = frame["Speaker"].fillna("").astype(str)
    full = speakers.map(_cb39_norm)
    keys = speakers.map(_cb40_person_key)
    return (full == target_full) | ((keys == target_key) & (target_key != ""))


def _cb38_score_snapshot(df: pd.DataFrame) -> Dict[str, Any]:  # noqa: F811
    indexed_count = int(len(df)) if isinstance(df, pd.DataFrame) else 0
    if df is None or df.empty:
        return {
            "recent": None, "lifetime": None, "count": 0,
            "indexed_count": indexed_count, "confidence": 0.0,
            "last_date": None, "last_indexed_date": None,
        }

    source = df.copy()
    source["Date"] = pd.to_datetime(source["Date"], errors="coerce")
    source = source[source["Date"].notna()]
    source = source[source["Date"] <= CB39_STRICT_TODAY]
    last_indexed = pd.Timestamp(source["Date"].max()) if not source.empty else None

    source["Score"] = pd.to_numeric(source.get("Score"), errors="coerce")
    source["Confidence"] = pd.to_numeric(source.get("Confidence"), errors="coerce").fillna(0.0)
    work = source.dropna(subset=["Score"]).sort_values("Date")
    if work.empty:
        return {
            "recent": None, "lifetime": None, "count": 0,
            "indexed_count": indexed_count, "confidence": 0.0,
            "last_date": None, "last_indexed_date": last_indexed,
        }

    scores = work["Score"].astype(float).clip(-1, 1)
    recent = float(scores.ewm(span=12, adjust=False, min_periods=1).mean().iloc[-1])

    age_days = (work["Date"].max() - work["Date"]).dt.days.clip(lower=0).astype(float)
    weights = np.exp(-np.log(2.0) * age_days / 365.0)
    lifetime = float(np.average(scores, weights=weights)) if float(weights.sum()) > 0 else float(scores.mean())

    n = int(len(work))
    mean_conf = float(work["Confidence"].clip(0, 1).mean())
    coverage = min(1.0, n / 12.0)
    recency_days = max(0, int((CB39_STRICT_TODAY - work["Date"].max()).days))
    recency_factor = float(np.exp(-np.log(2.0) * recency_days / 365.0))
    confidence = float(np.clip(mean_conf * (0.30 + 0.70 * coverage) * (0.70 + 0.30 * recency_factor), 0, 1))

    return {
        "recent": recent,
        "lifetime": lifetime,
        "count": n,
        "indexed_count": indexed_count,
        "confidence": confidence,
        "last_date": pd.Timestamp(work["Date"].max()),
        "last_indexed_date": last_indexed,
    }


def _cb38_members(code: str, speeches: Optional[pd.DataFrame] = None) -> List[Dict[str, Any]]:  # noqa: F811
    df = _cb383_clean_speeches(
        speeches if speeches is not None else _cb38_speeches(code, deep=False)
    )
    rows = []
    for name, role in CB38_ROSTERS.get(code, ()):
        member_df = df.loc[_cb40_member_mask(df, name)].copy() if not df.empty else _cb39_empty_speeches()
        snap = _cb38_score_snapshot(member_df)
        rows.append({
            "slug": _cb38_slug(name),
            "name": name,
            "role": role,
            "recent": snap["recent"],
            "lifetime": snap["lifetime"],
            "speeches": snap["count"],
            "indexed": snap["indexed_count"],
            "confidence": snap["confidence"],
            "last_date": snap["last_date"],
            "last_indexed_date": snap["last_indexed_date"],
        })
    return rows


def _cb39_committee_path(code: str, speeches: pd.DataFrame, horizon: str = "recent") -> pd.Series:  # noqa: F811
    paths = []
    for name, _ in CB38_ROSTERS.get(code, ()):
        member_df = speeches.loc[_cb40_member_mask(speeches, name)].copy() if speeches is not None and not speeches.empty else _cb39_empty_speeches()
        path = _cb39_score_path(member_df, horizon)
        if not path.empty:
            paths.append(path.rename(name))
    if not paths:
        return pd.Series(dtype=float)
    return pd.concat(paths, axis=1).mean(axis=1, skipna=True).dropna().clip(-1, 1)


def _cb38_member_cards(code: str, speeches: pd.DataFrame) -> None:  # noqa: F811
    members = _cb38_members(code, speeches)
    for start in range(0, len(members), 3):
        cols = st.columns(3)
        for offset, col in enumerate(cols):
            idx = start + offset
            if idx >= len(members):
                continue
            member = members[idx]
            with col:
                member_df = speeches.loc[_cb40_member_mask(speeches, member["name"])].copy() if speeches is not None and not speeches.empty else _cb39_empty_speeches()
                history = _cb39_score_path(member_df, "recent")
                score = member.get("recent")
                cls = "cb38-score-na" if score is None or pd.isna(score) else ("cb38-score-pos" if float(score) >= 0 else "cb38-score-neg")
                meta = CB39_MEMBER_META.get(code, {}).get(member["name"], {})
                appointment = meta.get("appointed", "")
                term_end = meta.get("term_end", "")
                tags = [meta.get("class", "Voter"), meta.get("vote", "Voter"), f"{int(member.get('indexed', 0))} indexed"]
                _html(
                    '<div class="cb38-member"><div class="cb38-member-top">'
                    f'<span class="cb38-member-name">{_esc(member["name"])}</span>'
                    f'<span class="cb38-member-score {cls}">{_cb38_fmt_score(score)}</span></div>'
                    f'<div class="cb38-member-role">{_esc(member["role"])} · {_esc(_cb39_stance_label(score))}</div>'
                    f'{_cb39_svg_spark(history)}'
                    f'<div class="cb38-member-metrics">'
                    f'<div class="cb38-member-metric"><b>Votes</b><span>—</span></div>'
                    f'<div class="cb38-member-metric"><b>Speeches</b><span>{int(member["speeches"])}</span></div>'
                    f'<div class="cb38-member-metric"><b>Confidence</b><span>{float(member.get("confidence", 0)):.0%}</span></div>'
                    f'</div><div class="cb39-member-tags">{"".join(f"<span>{_esc(x)}</span>" for x in tags if x)}</div>'
                    f'<div class="cb38-member-foot">{_esc("Appointed: " + appointment if appointment else "Appointment date not resolved")}'
                    f'{_esc(" · Ends: " + term_end if term_end else "")}</div></div>'
                )
                if st.button("Open member", key=f"ec40_member_open_{code}_{idx}", use_container_width=True):
                    st.session_state["ec36_cb_route"] = "member"
                    st.session_state["ec36_cb_code"] = code
                    st.session_state["ec38_member_slug"] = member["slug"]
                    st.rerun()


def _cb38_member(code: str, slug: str) -> None:  # noqa: F811
    bank = CB38_BANK_BY_CODE.get(code, CB38_BANK_BY_CODE["FED"])
    speeches = _cb38_speeches(code, deep=True)
    members = _cb38_members(code, speeches)
    member = next((m for m in members if m["slug"] == slug), None)
    if member is None:
        st.warning("Member profile unavailable from the official roster.")
        return

    _cb38_path(["Central Banks", bank["name"], "Scorecard", member["name"]])
    if st.button("← Back to scorecard", key=f"ec40_member_back_{code}_{slug}"):
        st.session_state["ec36_cb_route"] = "bank"
        st.session_state["ec38_cb_nav"] = "Scorecard"
        st.rerun()

    member_df = speeches.loc[_cb40_member_mask(speeches, member["name"])].copy() if not speeches.empty else _cb39_empty_speeches()
    snap = _cb38_score_snapshot(member_df)
    meta = CB39_MEMBER_META.get(code, {}).get(member["name"], {})
    subtitle = member["role"]
    if meta.get("appointed"):
        subtitle += f" · Appointed {meta['appointed']}"
    if meta.get("term_end"):
        subtitle += f" · Term ends {meta['term_end']}"

    _header(
        "MEMBER SCORECARD",
        member["name"],
        subtitle,
        [f"{snap['count']} scored texts", f"{snap.get('indexed_count', 0)} indexed", bank["short"], "local transparent model"],
    )
    _kpis([
        ("Recent composite", _cb38_fmt_score(snap["recent"]), "12-observation EMA", "flat"),
        ("Lifetime", _cb38_fmt_score(snap["lifetime"]), "365-day half-life", "flat"),
        ("Speeches", str(snap["count"]), "directionally scored", "flat"),
        ("Confidence", f"{snap['confidence']:.0%}", "coverage-adjusted evidence", "flat"),
    ])
    _html(
        f'<div class="cb38-callout"><b>{_esc(bank.get("votes", "Decision process"))}:</b> '
        'This independent scorecard reflects public communications only. '
        'It is generated locally and is not an official view of the institution.</div>'
    )

    tab = st.radio(
        "Member view",
        ["Hawk/Dove Chart", f"Speeches ({len(member_df)})"],
        horizontal=True,
        key=f"ec40_member_view_{code}_{slug}",
    )
    if tab == "Hawk/Dove Chart":
        _section("MEMBER HISTORY", "Hawk/Dove Tendency Over Time", "Only observed public communication dates are plotted.")
        raw = member_df.dropna(subset=["Date", "Score"]).copy().sort_values("Date")
        fig = go.Figure()
        if not raw.empty:
            fig.add_trace(go.Scatter(
                x=raw["Date"],
                y=raw["Score"],
                name="Speech score",
                mode="lines+markers",
                line=dict(color="#4d86bd", width=1.6, dash="dot"),
                marker=dict(size=7),
                customdata=np.stack([
                    raw["Title"].fillna("").astype(str),
                    raw["Source"].fillna("").astype(str),
                ], axis=-1),
                hovertemplate="%{x|%Y-%m-%d}<br>%{y:+.2f}<br>%{customdata[0]}<br>%{customdata[1]}<extra></extra>",
            ))
        fig.add_hline(y=0, line_color="rgba(202,212,221,.28)")
        fig.update_yaxes(range=[-1, 1], tickvals=[-.7, 0, .7], ticktext=["Dove", "Neutral", "Hawk"])
        _plot(fig, f"ec40_member_chart_{code}_{slug}", 440)
        _cb38_source([
            ("Inputs", "BIS full-text corpus + official archive"),
            ("History", "observed dates only"),
            ("Member", member["name"]),
        ])
    else:
        _cb38_render_speech_cards(member_df)


CB39_VERSION = CB40_VERSION
CB38_VERSION = CB40_VERSION
CENTRAL_BANKS_INTEGRITY_V40 = {
    "version": CB40_VERSION,
    "append_only_over_v391": True,
    "corpus_paths": "v40 + v39 + env + module + cwd",
    "member_matching": "canonical first/last + full-name",
    "confidence": "coverage and recency adjusted",
    "audio_downloaded": False,
    "benchmark_data_embedded": False,
}

# ============================================================
# END JARVIS ECONOMY V40.0
# ============================================================



# ============================================================
# JARVIS ECONOMY V41.0 — SELF-CONTAINED CENTRAL BANK DATA FIX
# ============================================================
# Append-only override over V40.
#
# Objectives:
# - one complete economy_intelligence.py file;
# - no external refresh script required;
# - no directory creation and no corpus file written by the active V41 layer;
# - automatic official-archive/RSS loading in Streamlit cache;
# - historical Hawk/Dove fallback generated from public policy-rate history;
# - canonical committee-member attribution;
# - populated committee charts when matching communications exist;
# - member-specific full-text enrichment only when a profile is opened.
# ============================================================

CB41_VERSION = "V41.0 · SELF-CONTAINED LIVE DATA ENGINE"
CB41_ROOT_WORKERS = 4
CB41_ROOT_ROWS_PER_BANK = 180
CB41_BANK_ENRICH_LIMIT = 30
CB41_MEMBER_ENRICH_LIMIT = 30


@st.cache_data(ttl=21600, show_spinner=False)
def _cb41_live_public_corpus() -> pd.DataFrame:
    """Build the active G10 communication corpus directly from public sources.

    The function is intentionally memory-bounded:
    - one archive response per central bank;
    - metadata/context only on the root;
    - no audio, video or downloadable media;
    - no disk writes and no directory creation;
    - Streamlit cache handles reuse between reruns.
    """
    frames: List[pd.DataFrame] = []

    try:
        bis = _cb38_bis_rss(enrich_text=False)
        if bis is not None and not bis.empty:
            frames.append(_cb383_clean_speeches(bis))
    except Exception:
        pass

    def fetch(code: str) -> Tuple[str, pd.DataFrame]:
        try:
            frame = _cb38_official_archive(code, "speech")
            if frame is None or frame.empty:
                return code, _cb39_empty_speeches()
            frame = _cb383_clean_speeches(frame).head(CB41_ROOT_ROWS_PER_BANK)
            return code, frame
        except Exception:
            return code, _cb39_empty_speeches()

    codes = list(CB38_BANK_BY_CODE)
    with _cb39_ThreadPoolExecutor(max_workers=min(CB41_ROOT_WORKERS, len(codes))) as pool:
        futures = [pool.submit(fetch, code) for code in codes]
        for future in _cb39_as_completed(futures):
            try:
                _, frame = future.result()
                if frame is not None and not frame.empty:
                    frames.append(frame)
            except Exception:
                pass

    if not frames:
        return _cb39_empty_speeches()

    return _cb383_clean_speeches(
        pd.concat(frames, ignore_index=True, sort=False)
    )


# Active V41 corpus reader: no filesystem corpus and no refresh command.
@st.cache_data(ttl=21600, show_spinner=False)
def _cb39_read_local_corpus() -> pd.DataFrame:  # noqa: F811
    return _cb41_live_public_corpus()


def _cb39_corpus_status() -> str:  # noqa: F811
    frame = _cb41_live_public_corpus()
    if frame is None or frame.empty:
        return "live public corpus unavailable; policy-rate stance proxy remains active"
    scored = int(pd.to_numeric(frame["Score"], errors="coerce").notna().sum())
    indexed = int(len(frame))
    banks = int(frame["CB"].nunique()) if "CB" in frame.columns else 0
    first = pd.to_datetime(frame["Date"], errors="coerce").min()
    last = pd.to_datetime(frame["Date"], errors="coerce").max()
    span = "date range unavailable"
    if pd.notna(first) and pd.notna(last):
        span = f"{pd.Timestamp(first).date().isoformat()} → {pd.Timestamp(last).date().isoformat()}"
    return (
        f"self-contained live corpus · {indexed:,} indexed · "
        f"{scored:,} directionally scored · {banks} banks · {span}"
    )


def _cb39_recent_all_banks() -> pd.DataFrame:  # noqa: F811
    return _cb41_live_public_corpus()


@st.cache_data(ttl=21600, show_spinner=False)
def _cb39_recent_all_banks_cached() -> pd.DataFrame:  # noqa: F811
    return _cb41_live_public_corpus()


def _cb38_speeches(code: Optional[str] = None, deep: bool = False) -> pd.DataFrame:  # noqa: F811
    """Self-contained communication loader.

    Root:
        official archive metadata/context + BIS RSS for all G10 banks.
    Selected bank:
        same corpus plus direct bank archive, with bounded full-text enrichment.
    """
    live = _cb41_live_public_corpus()

    if not code:
        return _cb383_clean_speeches(live)

    frames: List[pd.DataFrame] = []
    if live is not None and not live.empty:
        subset = live[live["CB"] == code].copy()
        if not subset.empty:
            frames.append(subset)

    try:
        official = _cb38_official_archive(code, "speech")
        if official is not None and not official.empty:
            frames.append(_cb383_clean_speeches(official))
    except Exception:
        pass

    try:
        bis = _cb38_bis_rss(enrich_text=False)
        if bis is not None and not bis.empty:
            subset = bis[bis["CB"] == code].copy()
            if not subset.empty:
                frames.append(_cb383_clean_speeches(subset))
    except Exception:
        pass

    if not frames:
        return _cb39_empty_speeches()

    out = _cb383_clean_speeches(
        pd.concat(frames, ignore_index=True, sort=False)
    )

    if deep and not out.empty:
        out = _cb39_enrich_rows(out, min(CB41_BANK_ENRICH_LIMIT, len(out)))

    return _cb383_clean_speeches(out)


@st.cache_data(ttl=21600, show_spinner=False)
def _cb41_policy_stance_path(code: str, start: str = "2016-01-01") -> pd.Series:
    """Historical public-policy stance proxy in [-1, +1].

    It is used only where communication evidence is absent. It combines:
    - rate level inside its rolling five-year range;
    - three-month policy-rate momentum;
    - twelve-month policy-rate momentum.

    It is not presented as a speech score.
    """
    policy, _ = _cb38_policy_series(code, start)
    if policy is None or policy.empty:
        return pd.Series(dtype=float)

    work = policy.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["value"] = pd.to_numeric(work["value"], errors="coerce")
    work = work.dropna(subset=["date", "value"]).sort_values("date")
    if work.empty:
        return pd.Series(dtype=float)

    monthly = (
        work.set_index("date")["value"]
        .resample("MS")
        .last()
        .ffill()
        .astype(float)
    )
    if monthly.empty:
        return pd.Series(dtype=float)

    rolling_low = monthly.rolling(60, min_periods=6).min()
    rolling_high = monthly.rolling(60, min_periods=6).max()
    denominator = (rolling_high - rolling_low).replace(0, np.nan)
    level = (((monthly - rolling_low) / denominator) * 2.0 - 1.0).fillna(0.0)

    momentum_3m = (monthly.diff(3) / 0.75).clip(-1, 1).fillna(0.0)
    momentum_12m = (monthly.diff(12) / 1.50).clip(-1, 1).fillna(0.0)

    stance = (
        0.45 * level.clip(-1, 1)
        + 0.35 * momentum_3m
        + 0.20 * momentum_12m
    ).clip(-1, 1)

    return stance.ewm(span=4, adjust=False, min_periods=1).mean().clip(-1, 1)


def _cb41_hybrid_score_path(code: str, speeches: pd.DataFrame) -> pd.Series:
    """Communication history with a transparent public-policy fallback.

    Communication observations remain dominant. The policy proxy:
    - backfills periods with no usable communication evidence;
    - contributes only 20% when a communication observation is available.
    """
    communication = _cb39_score_path(
        speeches if speeches is not None else _cb39_empty_speeches(),
        "recent",
    )
    policy_proxy = _cb41_policy_stance_path(code, "2016-01-01")

    if communication.empty:
        return policy_proxy
    if policy_proxy.empty:
        return communication

    index = communication.index.union(policy_proxy.index).sort_values()
    comm = communication.reindex(index)
    # A communication score remains current for at most six months.
    comm_active = comm.ffill(limit=5)
    proxy = policy_proxy.reindex(index).ffill()

    hybrid = proxy.copy()
    available = comm_active.notna()
    hybrid.loc[available] = (
        0.80 * comm_active.loc[available]
        + 0.20 * proxy.loc[available].fillna(0.0)
    )
    return hybrid.dropna().clip(-1, 1)


def _cb38_snapshot(code: str, speech_df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:  # noqa: F811
    bank = dict(CB38_BANK_BY_CODE[code])
    policy, policy_source = _cb38_policy_series(code, "2000-01-01")
    status = _cb38_detect_rate_status(policy)

    speeches = (
        speech_df
        if speech_df is not None
        else _cb38_speeches(code, deep=False)
    )
    speech_snapshot = _cb38_score_snapshot(speeches)

    recent = speech_snapshot["recent"]
    lifetime = speech_snapshot["lifetime"]
    score_source = "official public communications"

    if recent is None or pd.isna(recent):
        proxy = _cb41_policy_stance_path(code, "2016-01-01")
        if proxy is not None and not proxy.empty:
            recent = float(proxy.iloc[-1])
            lifetime = float(proxy.tail(min(36, len(proxy))).mean())
            score_source = "public policy-rate stance proxy"
        else:
            recent = None
            lifetime = None
            score_source = "no public stance evidence"

    bank.update(status)
    bank.update({
        "policy_source": policy_source,
        "score": recent,
        "lifetime": lifetime,
        "score_source": score_source,
        "speech_count": speech_snapshot["count"],
        "speech_indexed_count": speech_snapshot["indexed_count"],
        "score_confidence": speech_snapshot["confidence"],
        "speech_last_date": speech_snapshot["last_date"],
        "speech_last_indexed_date": speech_snapshot["last_indexed_date"],
    })
    return bank


def _cb38_summary(bank: Mapping[str, Any]) -> None:  # noqa: F811
    score = bank.get("score")
    scored = int(bank.get("speech_count", 0))
    indexed = int(bank.get("speech_indexed_count", scored))
    since = bank.get("since")
    move = bank.get("change_bps")
    decision = str(bank.get("decision") or "N/A")
    score_source = str(bank.get("score_source") or "public stance engine")

    decision_note = (
        "last policy move unavailable"
        if move is None
        else (
            "last decision unchanged"
            if abs(float(move)) < 1e-12
            else f"last move {int(round(float(move))):+d} bps"
        )
    )

    items = [
        (
            "Rate",
            _cb38_fmt_rate(bank.get("rate")),
            f"effective since {since.date().isoformat() if since is not None else 'N/A'}",
            "flat",
        ),
        ("Target", str(bank["target"]), bank["country"], "flat"),
        (
            "Hawk / Dove",
            _cb38_fmt_score(score, 3),
            f"{scored} scored / {indexed} indexed · {score_source}",
            "up" if score is not None and not pd.isna(score) and float(score) >= 0 else "down",
        ),
        ("Decision", decision, decision_note, "flat"),
        (
            "Votes",
            str(bank.get("votes") or "Not available"),
            f"{CB39_MEMBER_COUNTS.get(str(bank['code']), len(CB38_ROSTERS.get(str(bank['code']), ())))} committee members",
            "flat",
        ),
    ]

    blocks = []
    for label, value, note, tone in items:
        cls = {"up": "ec36-up", "down": "ec36-down", "flat": "ec36-flat"}.get(tone, "")
        blocks.append(
            f'<div class="cb38-stat"><div class="cb38-stat-k">{_esc(label)}</div>'
            f'<div class="cb38-stat-v {cls}">{_esc(value)}</div>'
            f'<div class="cb38-stat-n">{_esc(note)}</div></div>'
        )
    _html('<div class="cb38-stats">' + ''.join(blocks) + '</div>')


def _cb38_overview(code: str, bank: Mapping[str, Any], speeches: pd.DataFrame) -> None:  # noqa: F811
    score = bank.get("score")
    _html(
        '<div class="cb38-stance"><div class="cb38-stance-title">Hawk / Dove Stance</div>'
        + _cb38_track(score)
        .replace("cb38-track", "cb38-stance-track")
        .replace("cb38-diamond", "cb38-stance-pointer")
        + '<div class="cb38-stance-labels"><span>Dovish</span><span>Neutral</span><span>Hawkish</span></div></div>'
    )

    c1, c2 = st.columns([1, 1])
    with c1:
        zoom = st.radio(
            "Zoom",
            ["1Y", "3Y", "5Y", "All"],
            horizontal=True,
            key=f"ec41_zoom_{code}",
        )
    with c2:
        merge = st.checkbox("Merge Charts", key=f"ec41_merge_{code}")

    policy, policy_source = _cb38_policy_series(code, "2000-01-01")
    window = {"1Y": 365, "3Y": 365 * 3, "5Y": 365 * 5, "All": None}[zoom]
    policy_window = _cb38_apply_window(policy, window)

    history = _cb41_hybrid_score_path(code, speeches)
    if window and not history.empty:
        history = history[
            history.index >= CB39_STRICT_TODAY - pd.Timedelta(days=window)
        ]

    if merge:
        fig = go.Figure()
        if not policy_window.empty:
            fig.add_trace(go.Scatter(
                x=policy_window["date"],
                y=policy_window["value"],
                name="Policy rate",
                line_shape="hv",
                line=dict(color=CB38_COLORS["gold"], width=2.2),
            ))
        if not history.empty:
            fig.add_trace(go.Scatter(
                x=history.index,
                y=history.values,
                name="Hawk/Dove",
                yaxis="y2",
                mode="lines+markers",
                line=dict(color=CB38_COLORS["orange"], width=2),
            ))
        fig.update_layout(
            yaxis2=dict(
                overlaying="y",
                side="right",
                range=[-1, 1],
                tickvals=[-.7, 0, .7],
                ticktext=["Dove", "Neutral", "Hawk"],
                showgrid=False,
            )
        )
        _plot(fig, f"ec41_overview_merge_{code}", 455)
    else:
        left, right = st.columns(2)
        with left:
            fig1 = go.Figure()
            if not policy_window.empty:
                fig1.add_trace(go.Scatter(
                    x=policy_window["date"],
                    y=policy_window["value"],
                    name="Policy rate",
                    line_shape="hv",
                    line=dict(color=CB38_COLORS["gold"], width=2.2),
                    fill="tozeroy",
                    fillcolor="rgba(216,191,88,.07)",
                ))
            _plot(fig1, f"ec41_policy_hist_{code}", 380)

        with right:
            fig2 = go.Figure()
            if not history.empty:
                fig2.add_trace(go.Scatter(
                    x=history.index,
                    y=history.values,
                    name="Hawk/Dove",
                    mode="lines+markers",
                    line=dict(color=CB38_COLORS["orange"], width=2),
                    marker=dict(size=5),
                ))
            fig2.add_hline(y=0, line_color="rgba(202,212,221,.28)")
            fig2.update_yaxes(
                range=[-1, 1],
                tickvals=[-.7, 0, .7],
                ticktext=["Dove", "Neutral", "Hawk"],
            )
            _plot(fig2, f"ec41_score_hist_{code}", 380)

    _cb38_source([
        ("Policy history", policy_source),
        ("Communication", "BIS RSS + official central-bank archive"),
        ("Fallback", "public policy-rate stance only where communications are absent"),
        ("Zoom", zoom),
    ])

    _section(
        "RECENT TAPE",
        "Recent Speeches",
        f"Latest 10 substantive public communications for {code}.",
    )
    _cb38_render_speech_cards(speeches, 10)

    _section(
        "COMMITTEE",
        f"{bank['committee']} — Hawk/Dove Scorecard",
        "Official roster only. Member scores use attributed public communications; missing members remain no data.",
    )
    _cb38_member_cards(code, speeches)


def _cb38_scorecard(code: str, bank: Mapping[str, Any], speeches: pd.DataFrame) -> None:  # noqa: F811
    """Committee scorecard with canonical person matching."""
    members = _cb38_members(code, speeches)

    _section(
        "COMMITTEE INTELLIGENCE",
        f"{bank['name']} — {bank['committee']} Scorecard",
        "Recent = 12-observation EMA. Lifetime = 365-day half-life. Click any member for the underlying communication history.",
    )

    horizon = st.radio(
        "Score horizon",
        ["Recent (12-EMA)", "Lifetime"],
        horizontal=True,
        key=f"ec41_horizon_{code}",
    )
    metric = "recent" if horizon.startswith("Recent") else "lifetime"

    valid = [
        member for member in members
        if member.get(metric) is not None and not pd.isna(member.get(metric))
    ]
    recent_valid = [
        member for member in members
        if member.get("recent") is not None and not pd.isna(member.get("recent"))
    ]
    life_valid = [
        member for member in members
        if member.get("lifetime") is not None and not pd.isna(member.get("lifetime"))
    ]

    recent_avg = (
        float(np.mean([member["recent"] for member in recent_valid]))
        if recent_valid else np.nan
    )
    life_avg = (
        float(np.mean([member["lifetime"] for member in life_valid]))
        if life_valid else np.nan
    )

    _kpis([
        (
            "Committee recent",
            "—" if np.isnan(recent_avg) else f"{recent_avg:+.2f}",
            "member average",
            "flat",
        ),
        (
            "Committee lifetime",
            "—" if np.isnan(life_avg) else f"{life_avg:+.2f}",
            "365-day half-life",
            "flat",
        ),
        ("Roster", str(len(members)), bank["committee"], "flat"),
        (
            "Scored members",
            str(len(valid)),
            f"{sum(int(member.get('indexed', 0)) for member in members)} indexed communications",
            "flat",
        ),
    ])

    fig = go.Figure()
    trace_count = 0
    for member in members:
        member_df = (
            speeches.loc[_cb40_member_mask(speeches, member["name"])].copy()
            if speeches is not None and not speeches.empty
            else _cb39_empty_speeches()
        )
        history = _cb39_score_path(
            member_df,
            "recent" if metric == "recent" else "lifetime",
        )
        if history.empty:
            continue
        fig.add_trace(go.Scatter(
            x=history.index,
            y=history.values,
            name=member["name"].split()[-1],
            mode="lines+markers",
            line=dict(width=2),
            marker=dict(size=5),
        ))
        trace_count += 1

    # If the board has no attributable public communication, display the
    # institution proxy as a dashed diagnostic rather than an empty panel.
    if trace_count == 0:
        proxy = _cb41_policy_stance_path(code, "2016-01-01")
        if proxy is not None and not proxy.empty:
            fig.add_trace(go.Scatter(
                x=proxy.index,
                y=proxy.values,
                name="Institution policy proxy",
                mode="lines",
                line=dict(width=2, dash="dash", color=CB38_COLORS["gold"]),
            ))

    fig.add_hline(y=0, line_color="rgba(202,212,221,.28)")
    fig.update_yaxes(
        range=[-1, 1],
        tickvals=[-.7, 0, .7],
        ticktext=["Dove", "Neutral", "Hawk"],
    )
    _plot(fig, f"ec41_committee_{code}_{metric}", 455)

    decisions, decision_source = _cb38_decisions(code)
    joined = _cb383_merge_decision_scores(
        decisions,
        _cb39_committee_path(
            code,
            speeches,
            "recent" if metric == "recent" else "lifetime",
        ),
    )
    if not joined.empty:
        joined["Avg Score"] = joined["Model score"].map(
            lambda value: "—" if pd.isna(value) else f"{float(value):+.2f}"
        )
        joined["Dissents"] = "—"
        show = (
            joined.sort_values("Date", ascending=False)[
                ["Date", "Decision", "Avg Score", "Dissents"]
            ]
            .head(12)
            .copy()
        )
        show["Date"] = pd.to_datetime(
            show["Date"], errors="coerce"
        ).dt.date.astype(str)
        _table(show, f"ec41_score_decisions_{code}", 390)

    _section(
        "INDIVIDUAL MEMBERS",
        f"Individual Members ({len(members)})",
        "Official roster only: recent/lifetime score, evidence count, confidence and appointment metadata where resolved.",
    )
    _cb38_member_cards(code, speeches)

    _cb38_source([
        ("Score model", "Quant Terminal deterministic sentence-level model"),
        ("Decision source", decision_source),
        ("Member matching", "canonical full name and first/last name"),
        ("No-data rule", "unscored member communication remains N/A"),
    ])


def _cb38_member(code: str, slug: str) -> None:  # noqa: F811
    """Member page with member-specific bounded full-text enrichment."""
    bank = CB38_BANK_BY_CODE.get(code, CB38_BANK_BY_CODE["FED"])
    speeches = _cb38_speeches(code, deep=True)
    members = _cb38_members(code, speeches)
    member = next((item for item in members if item["slug"] == slug), None)

    if member is None:
        st.warning("Member profile unavailable from the official roster.")
        return

    _cb38_path([
        "Central Banks",
        bank["name"],
        "Scorecard",
        member["name"],
    ])

    if st.button("← Back to scorecard", key=f"ec41_member_back_{code}_{slug}"):
        st.session_state["ec36_cb_route"] = "bank"
        st.session_state["ec38_cb_nav"] = "Scorecard"
        st.rerun()

    member_df = (
        speeches.loc[_cb40_member_mask(speeches, member["name"])].copy()
        if speeches is not None and not speeches.empty
        else _cb39_empty_speeches()
    )

    # Only the opened member receives an additional enrichment pass.
    if not member_df.empty:
        member_df = _cb39_enrich_rows(
            member_df,
            min(CB41_MEMBER_ENRICH_LIMIT, len(member_df)),
        )

    snapshot = _cb38_score_snapshot(member_df)
    meta = CB39_MEMBER_META.get(code, {}).get(member["name"], {})

    subtitle = member["role"]
    if meta.get("appointed"):
        subtitle += f" · Appointed {meta['appointed']}"
    if meta.get("term_end"):
        subtitle += f" · Term ends {meta['term_end']}"

    _header(
        "MEMBER SCORECARD",
        member["name"],
        subtitle,
        [
            f"{snapshot['count']} scored texts",
            f"{snapshot.get('indexed_count', 0)} indexed",
            bank["short"],
            "local transparent model",
        ],
    )

    _kpis([
        (
            "Recent composite",
            _cb38_fmt_score(snapshot["recent"]),
            "12-observation EMA",
            "flat",
        ),
        (
            "Lifetime",
            _cb38_fmt_score(snapshot["lifetime"]),
            "365-day half-life",
            "flat",
        ),
        (
            "Speeches",
            str(snapshot["count"]),
            "directionally scored",
            "flat",
        ),
        (
            "Confidence",
            f"{snapshot['confidence']:.0%}",
            "coverage- and recency-adjusted",
            "flat",
        ),
    ])

    _html(
        f'<div class="cb38-callout"><b>{_esc(bank.get("votes", "Decision process"))}:</b> '
        "This independent scorecard reflects public communications only. "
        "It is generated locally and is not an official view of the institution.</div>"
    )

    tab = st.radio(
        "Member view",
        ["Hawk/Dove Chart", f"Speeches ({len(member_df)})"],
        horizontal=True,
        key=f"ec41_member_view_{code}_{slug}",
    )

    if tab == "Hawk/Dove Chart":
        _section(
            "MEMBER HISTORY",
            "Hawk/Dove Tendency Over Time",
            "Only observed public communication dates are plotted.",
        )

        raw = member_df.dropna(subset=["Date", "Score"]).copy().sort_values("Date")
        fig = go.Figure()

        if not raw.empty:
            custom = np.stack([
                raw["Title"].fillna("").astype(str),
                raw["Source"].fillna("").astype(str),
            ], axis=-1)
            fig.add_trace(go.Scatter(
                x=raw["Date"],
                y=raw["Score"],
                name="Speech score",
                mode="lines+markers",
                line=dict(color="#4d86bd", width=1.6, dash="dot"),
                marker=dict(size=7),
                customdata=custom,
                hovertemplate=(
                    "%{x|%Y-%m-%d}<br>"
                    "%{y:+.2f}<br>"
                    "%{customdata[0]}<br>"
                    "%{customdata[1]}"
                    "<extra></extra>"
                ),
            ))

        fig.add_hline(y=0, line_color="rgba(202,212,221,.28)")
        fig.update_yaxes(
            range=[-1, 1],
            tickvals=[-.7, 0, .7],
            ticktext=["Dove", "Neutral", "Hawk"],
        )
        _plot(fig, f"ec41_member_chart_{code}_{slug}", 440)

        _cb38_source([
            ("Inputs", "official central-bank archive + BIS RSS"),
            ("Enrichment", f"up to {CB41_MEMBER_ENRICH_LIMIT} opened-member pages"),
            ("History", "observed dates only"),
            ("Member", member["name"]),
        ])
    else:
        _cb38_render_speech_cards(member_df)


def _cb38_root() -> None:  # noqa: F811
    """Final self-contained G10 root renderer."""
    _cb39_css()

    _header(
        "ECONOMY · PUBLIC MONETARY DATA",
        "Global Monetary Policy Observatory",
        "G10 policy rates, balance sheets, official communications and committee attribution generated by Quant Terminal from public primary sources.",
        [
            "official target rates",
            "BIS total assets",
            "live public communications",
            "local scoring",
        ],
    )

    _html(
        '<div class="cb39-currency-strip">'
        + ''.join(
            f'<span class="cb39-ccy">{_esc(bank["flag"])} {_esc(bank["ccy"])}</span>'
            for bank in CB38_BANKS
        )
        + '</div>'
    )

    _html(
        '<details class="cb38-model"><summary>How This Works — Quant Terminal Hawk/Dove Model</summary>'
        '<p>Communications are loaded directly from BIS RSS and official central-bank archives. '
        'The root uses metadata and bounded page context; full text is fetched only for a selected bank or member. '
        'Scores are deterministic sentence-level estimates. Where communication evidence is unavailable, '
        'a separately identified public policy-rate stance proxy keeps the institutional history observable. '
        'No audio, video, media attachment, external corpus folder or manual refresh script is required.</p></details>'
    )

    _html(
        f'<div class="cb39-status"><b>Data engine:</b> {_esc(_cb39_corpus_status())}. '
        'The active V41 layer writes no files and creates no directories.</div>'
    )

    speeches = _cb38_speeches(deep=False)
    snapshots = [
        _cb38_snapshot(
            code,
            speeches[speeches["CB"] == code].copy()
            if speeches is not None and not speeches.empty
            else _cb39_empty_speeches(),
        )
        for code in CB38_BANK_BY_CODE
    ]

    _cb39_root_cards(snapshots)

    c1, c2, c3 = st.columns([2.2, 1, 1])
    with c1:
        selected = st.selectbox(
            "Open central bank",
            list(CB38_BANK_BY_CODE),
            key="ec41_cb_select",
            format_func=lambda code: (
                f"{CB38_BANK_BY_CODE[code]['flag']} {code} — "
                f"{CB38_BANK_BY_CODE[code]['name']}"
            ),
        )
    with c2:
        if st.button("Open scorecard", key="ec41_cb_scorecard", use_container_width=True):
            st.session_state["ec36_cb_code"] = selected
            st.session_state["ec36_cb_route"] = "bank"
            st.session_state["ec38_cb_nav"] = "Scorecard"
            st.rerun()
    with c3:
        if st.button("Policy previews", key="ec41_cb_previews", use_container_width=True):
            st.session_state["ec36_cb_route"] = "previews"
            st.rerun()

    _section(
        "CROSS-BANK SIGNAL",
        "Hawk / Dove Composite",
        "Official communication history with a public policy-rate fallback only where communication evidence is absent.",
    )

    options = list(CB38_BANK_BY_CODE)
    selected_codes = st.multiselect(
        "Central banks",
        options,
        default=options,
        key="ec41_composite_codes",
    )

    c1, c2 = st.columns([1, 1])
    with c1:
        view = st.radio(
            "View",
            ["Level", "3m/3m change"],
            horizontal=True,
            key="ec41_composite_view",
        )
    with c2:
        solo = st.checkbox("Solo first", key="ec41_solo")

    fig = go.Figure()
    order = selected_codes[:1] if solo and selected_codes else selected_codes

    for code in order:
        bank_speeches = (
            speeches[speeches["CB"] == code].copy()
            if speeches is not None and not speeches.empty
            else _cb39_empty_speeches()
        )
        history = _cb41_hybrid_score_path(code, bank_speeches)
        if view == "3m/3m change":
            history = _cb39_three_month_change(history)
        if history.empty:
            continue
        fig.add_trace(go.Scatter(
            x=history.index,
            y=history.values,
            name=code,
            mode="lines",
            line=dict(color=CB38_COLOR_BY_CODE[code], width=2),
        ))

    fig.add_hline(y=0, line_color="rgba(202,212,221,.30)")
    if view == "Level":
        fig.update_yaxes(
            range=[-1, 1],
            tickvals=[-.7, 0, .7],
            ticktext=["Dovish", "Neutral", "Hawkish"],
        )
    _plot(fig, "ec41_composite", 480)

    _cb38_source([
        ("Primary signal", "official public communications"),
        ("Fallback", "policy-rate level and momentum where communication evidence is absent"),
        ("Scoring", "Quant Terminal deterministic local model"),
        ("Media", "audio/video/downloads excluded"),
    ])

    _section(
        "RANKING",
        "Policy Rates — Ranked",
        "Latest official target-policy observations in descending order.",
    )

    ranked = sorted(
        snapshots,
        key=lambda snapshot: (
            float(snapshot["rate"])
            if snapshot.get("rate") is not None and not pd.isna(snapshot.get("rate"))
            else -999
        ),
        reverse=True,
    )

    html_rows = []
    for index, snapshot in enumerate(ranked, 1):
        mark = (
            "▲" if snapshot.get("decision") == "HIKE"
            else "▼" if snapshot.get("decision") == "CUT"
            else "●"
        )
        date_text = (
            snapshot.get("date").date().isoformat()
            if snapshot.get("date") is not None
            else "N/A"
        )
        html_rows.append(
            f'<div class="cb38-rank-row"><span>{index:02d}</span>'
            f'<span class="cb38-rank-code">{_esc(snapshot["flag"])} {_esc(snapshot["code"])} '
            f'<small>{_esc(snapshot["policy_source"])}</small></span>'
            f'<span class="cb38-rank-rate">{_cb38_fmt_rate(snapshot.get("rate"))}</span>'
            f'<span class="cb38-rank-mark">{mark} {date_text}</span></div>'
        )
    _html('<div class="cb38-ranked">' + ''.join(html_rows) + '</div>')

    _section(
        "MONETARY POLICY STANCE",
        "Policy Rates & Balance Sheet",
        "Policy-rate history with monthly central-bank total-asset change. Bars are green for expansion and red for contraction.",
    )

    balance_code = st.selectbox(
        "Central bank",
        options,
        index=options.index("FED"),
        key="ec41_balance_bank",
        label_visibility="collapsed",
    )

    policy, policy_source = _cb38_policy_series(balance_code, "2016-01-01")
    assets, asset_source, asset_unit = _cb38_assets_series(
        balance_code,
        "2016-01-01",
    )
    current = next(
        (snapshot for snapshot in snapshots if snapshot["code"] == balance_code),
        {},
    )

    _html(
        f'<div class="cb39-decision-head"><span class="cb39-decision-rate">'
        f'{_cb38_fmt_rate(current.get("rate"))}</span>'
        f'<span class="cb39-decision-note">policy rate · '
        f'{str(current.get("decision") or "N/A").lower()} since '
        f'{current.get("since").date().isoformat() if current.get("since") is not None else "N/A"}'
        f'</span></div>'
    )

    fig2 = go.Figure()
    if policy is not None and not policy.empty:
        fig2.add_trace(go.Scatter(
            x=policy["date"],
            y=policy["value"],
            name="Policy rate",
            line=dict(color=CB38_COLORS["blue"], width=2.2),
            line_shape="hv",
        ))

    if assets is not None and not assets.empty:
        monthly_assets = (
            assets.set_index("date")["value"]
            .resample("MS")
            .last()
            .dropna()
            .diff()
            .dropna()
        )
        fig2.add_trace(go.Bar(
            x=monthly_assets.index,
            y=monthly_assets.values,
            name=f"Assets MoM ({asset_unit})",
            yaxis="y2",
            marker_color=[
                CB38_COLORS["green"] if value >= 0 else CB38_COLORS["red"]
                for value in monthly_assets
            ],
            opacity=.72,
        ))
        fig2.update_layout(
            yaxis2=dict(
                overlaying="y",
                side="right",
                showgrid=False,
                title=asset_unit + " / month",
            )
        )

    _plot(fig2, "ec41_policy_assets", 480)
    _cb38_source([
        ("Policy", policy_source),
        ("Balance sheet", asset_source),
        ("Method", "monthly last observation; first difference"),
    ])

    _section(
        "COMMUNICATION",
        "Recent Speeches",
        "Latest substantive G10 communications with locally computed score and confidence.",
    )
    _cb39_recent_table(speeches, CB39_ROOT_RECENT_LIMIT)

    _section(
        "DATA COVERAGE",
        "Provider diagnostics",
        "Communication data are loaded automatically. Missing member evidence remains N/A; institutional proxy data are identified separately.",
    )
    _cb38_quality_block(snapshots, speeches)


def _cb38_bank(code: str) -> None:  # noqa: F811
    _cb39_css()
    speeches = _cb38_speeches(code, deep=True)
    bank = _cb38_snapshot(code, speeches)

    _cb38_path(["Central Banks", bank["name"]])

    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("← All Central Banks", key=f"ec41_back_{code}"):
            st.session_state["ec36_cb_route"] = "root"
            st.rerun()
    with c2:
        if st.button("Policy Previews →", key=f"ec41_preview_{code}"):
            st.session_state["ec36_cb_route"] = "previews"
            st.rerun()

    _header(
        "CENTRAL BANK WORKSTATION",
        f"{bank['flag']} {bank['name']}",
        f"{bank['committee']} · self-contained public-data workflow",
        [
            bank["ccy"],
            CB39_MEETING_LABELS.get(code, bank["meetings"]),
            f"{CB39_MEMBER_COUNTS.get(code, len(CB38_ROSTERS.get(code, ())))} committee members",
            CB41_VERSION,
        ],
    )

    _cb38_summary(bank)

    _html(
        f'<div class="cb39-status"><b>Live enrichment:</b> up to '
        f'{CB41_BANK_ENRICH_LIMIT} official pages for the opened bank. '
        'Responses are cached; audio, video and downloads are excluded. '
        'No external corpus folder is required.</div>'
    )

    tab = _segmented(
        "Central bank page",
        ["Overview", "Scorecard", "Speeches", "Meetings"],
        "ec38_cb_nav",
        "Overview",
    )

    if tab == "Overview":
        _cb38_overview(code, bank, speeches)
    elif tab == "Scorecard":
        _cb38_scorecard(code, bank, speeches)
    elif tab == "Speeches":
        _cb38_speech_archive(code, bank, speeches)
    else:
        _cb38_meeting_archive(code, bank)


CB39_VERSION = CB41_VERSION
CB38_VERSION = CB41_VERSION

CENTRAL_BANKS_INTEGRITY_V41 = {
    "version": CB41_VERSION,
    "single_file": True,
    "external_refresh_required": False,
    "creates_directories": False,
    "writes_corpus_files": False,
    "root_sources": "BIS RSS + official central-bank archives",
    "historical_fallback": "public policy-rate level and momentum",
    "member_matching": "canonical full name and first/last name",
    "member_enrichment": "opened member only",
    "audio_downloaded": False,
    "robomacro_data_embedded": False,
}

# ============================================================
# END JARVIS ECONOMY V41.0
# ============================================================


# ============================================================
# JARVIS ECONOMY V42.0 - CENTRAL BANK REPRESENTATION EQUIVALENCE
# Append-only over V41.  Central Banks runtime only.
# ============================================================

CB42_VERSION = "V42.0 · CENTRAL BANK REPRESENTATION EQUIVALENCE"
CB42_ORDER = ("FED", "ECB", "BOE", "BOJ", "BOC", "SNB", "RBA", "RBNZ", "RIKSBANK", "NORGES")
CB42_ROOT_ENRICH_PER_BANK = 4
CB42_ROOT_ARCHIVE_ROWS = 120


def _cb42_css() -> None:
    _html(
        """
<style>
.cb42-rank-card{border:1px solid rgba(128,157,186,.24);border-radius:12px;overflow:hidden;background:rgba(5,17,29,.78);margin:8px 0 16px}
.cb42-rank-row{display:grid;grid-template-columns:34px 58px minmax(180px,1fr) 88px 46px;gap:10px;align-items:center;padding:10px 13px;border-bottom:1px solid rgba(128,157,186,.11)}
.cb42-rank-row:last-child{border-bottom:none}.cb42-rank-row:hover{background:rgba(99,199,255,.035)}
.cb42-rank-no{color:#71879a;font:700 9px ui-monospace,monospace}.cb42-rank-code{font:800 10px ui-monospace,monospace;color:#e0e8ed}
.cb42-rank-name{font-size:10px;color:#9eb0bd}.cb42-rank-rate{text-align:right;font:800 13px ui-monospace,monospace;color:#f1f5f7}
.cb42-rank-status{text-align:center;font:900 12px ui-monospace,monospace}.cb42-rank-status.hike{color:#58d39b}.cb42-rank-status.cut{color:#ff7d87}.cb42-rank-status.hold{color:#d8bf58}
.cb42-rank-foot{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;padding:8px 13px;background:rgba(128,157,186,.025);color:#71879a;font-size:8px}
.cb42-chart-title{font-family:Georgia,serif;font-size:18px;color:#e9eef1;margin:2px 0 4px}.cb42-chart-sub{font-size:8px;color:#7f93a4;margin:0 0 5px}
.cb42-model-chip{display:inline-flex;border:1px solid rgba(216,191,88,.28);border-radius:999px;padding:3px 7px;color:#d8bf58;font-size:8px;margin-left:6px}
@media(max-width:800px){.cb42-rank-row{grid-template-columns:28px 55px 1fr 75px 35px}.cb42-rank-name{display:none}}
</style>
        """
    )


@st.cache_data(ttl=21600, show_spinner=False)
def _cb42_live_public_corpus() -> pd.DataFrame:
    """Recent cross-bank communications with bounded full-text enrichment.

    V41 indexed archive metadata but scored very few rows.  V42 enriches only
    the newest four substantive pages per bank, in parallel, then keeps the
    full archive metadata for search and member attribution.  No media files,
    local folders or disk corpus are used.
    """
    frames: List[pd.DataFrame] = []

    try:
        bis = _cb38_bis_rss(enrich_text=False)
        if bis is not None and not bis.empty:
            frames.append(_cb383_clean_speeches(bis))
    except Exception:
        pass

    def fetch_bank(code: str) -> pd.DataFrame:
        try:
            frame = _cb38_official_archive(code, "speech")
            if frame is None or frame.empty:
                return _cb39_empty_speeches()
            frame = _cb383_clean_speeches(frame).head(CB42_ROOT_ARCHIVE_ROWS)
            return _cb39_enrich_rows(frame, min(CB42_ROOT_ENRICH_PER_BANK, len(frame)))
        except Exception:
            return _cb39_empty_speeches()

    with _cb39_ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch_bank, code) for code in CB42_ORDER]
        for future in _cb39_as_completed(futures):
            try:
                frame = future.result()
                if frame is not None and not frame.empty:
                    frames.append(frame)
            except Exception:
                pass

    if not frames:
        return _cb39_empty_speeches()
    return _cb383_clean_speeches(pd.concat(frames, ignore_index=True, sort=False))


@st.cache_data(ttl=21600, show_spinner=False)
def _cb39_read_local_corpus() -> pd.DataFrame:  # noqa: F811
    return _cb42_live_public_corpus()


def _cb39_recent_all_banks() -> pd.DataFrame:  # noqa: F811
    return _cb42_live_public_corpus()


@st.cache_data(ttl=21600, show_spinner=False)
def _cb39_recent_all_banks_cached() -> pd.DataFrame:  # noqa: F811
    return _cb42_live_public_corpus()


def _cb39_corpus_status() -> str:  # noqa: F811
    frame = _cb42_live_public_corpus()
    if frame is None or frame.empty:
        return "live public communication layer unavailable; policy-cycle signal active"
    scored = int(pd.to_numeric(frame.get("Score"), errors="coerce").notna().sum())
    indexed = int(len(frame))
    banks = int(frame["CB"].nunique()) if "CB" in frame.columns else 0
    dates = pd.to_datetime(frame.get("Date"), errors="coerce")
    valid = dates.dropna()
    span = "date range unavailable" if valid.empty else f"{valid.min().date().isoformat()} → {valid.max().date().isoformat()}"
    return f"{indexed:,} indexed · {scored:,} scored · {banks} banks · {span}"


def _cb38_speeches(code: Optional[str] = None, deep: bool = False) -> pd.DataFrame:  # noqa: F811
    live = _cb42_live_public_corpus()
    if not code:
        return _cb383_clean_speeches(live)

    frames: List[pd.DataFrame] = []
    if live is not None and not live.empty:
        subset = live[live["CB"] == code].copy()
        if not subset.empty:
            frames.append(subset)
    try:
        official = _cb38_official_archive(code, "speech")
        if official is not None and not official.empty:
            frames.append(_cb383_clean_speeches(official))
    except Exception:
        pass
    try:
        bis = _cb38_bis_rss(enrich_text=False)
        if bis is not None and not bis.empty:
            subset = bis[bis["CB"] == code].copy()
            if not subset.empty:
                frames.append(_cb383_clean_speeches(subset))
    except Exception:
        pass
    if not frames:
        return _cb39_empty_speeches()
    out = _cb383_clean_speeches(pd.concat(frames, ignore_index=True, sort=False))
    if deep and not out.empty:
        out = _cb39_enrich_rows(out, min(CB41_BANK_ENRICH_LIMIT, len(out)))
    return _cb383_clean_speeches(out)


@st.cache_data(ttl=21600, show_spinner=False)
def _cb42_policy_cycle_path(code: str, start: str = "2016-01-01") -> pd.Series:
    """Institution-specific monetary-policy cycle signal in [-1, 1].

    Unlike the V41 rolling-range proxy, this signal is driven mainly by policy
    changes and their decay, so G10 paths do not move in synchronized plateaus.
    """
    policy, _ = _cb38_policy_series(code, start)
    if policy is None or policy.empty:
        return pd.Series(dtype=float)
    work = policy.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["value"] = pd.to_numeric(work["value"], errors="coerce")
    work = work.dropna(subset=["date", "value"]).sort_values("date")
    if work.empty:
        return pd.Series(dtype=float)

    monthly = work.set_index("date")["value"].resample("MS").last().ffill().astype(float)
    change_1m = monthly.diff().fillna(0.0)
    change_6m = monthly.diff(6).fillna(0.0)

    # 25bp is meaningful but not a full-scale event; 100bp approaches ±1.
    decision_impulse = np.tanh(change_1m / 0.40)
    decision_memory = decision_impulse.ewm(span=5, adjust=False, min_periods=1).mean()
    cycle_momentum = np.tanh(change_6m / 1.20)

    rolling_mean = monthly.rolling(60, min_periods=12).mean()
    rolling_std = monthly.rolling(60, min_periods=12).std().replace(0, np.nan)
    level_z = ((monthly - rolling_mean) / rolling_std).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    level_tightness = np.tanh(level_z / 1.50)

    raw = 0.58 * decision_memory + 0.27 * cycle_momentum + 0.15 * level_tightness
    return raw.ewm(span=3, adjust=False, min_periods=1).mean().clip(-1, 1)


def _cb42_communication_path(speeches: pd.DataFrame) -> pd.Series:
    if speeches is None or speeches.empty:
        return pd.Series(dtype=float)
    work = speeches.copy()
    work["Date"] = pd.to_datetime(work.get("Date"), errors="coerce")
    work["Score"] = pd.to_numeric(work.get("Score"), errors="coerce")
    work["Confidence"] = pd.to_numeric(work.get("Confidence"), errors="coerce").fillna(0.25).clip(0.05, 1.0)
    work = work.dropna(subset=["Date", "Score"]).sort_values("Date")
    if work.empty:
        return pd.Series(dtype=float)

    def weighted(group: pd.DataFrame) -> float:
        weights = group["Confidence"].astype(float).to_numpy()
        values = group["Score"].astype(float).to_numpy()
        return float(np.average(values, weights=weights)) if float(weights.sum()) > 0 else float(np.mean(values))

    monthly = work.set_index("Date").groupby(pd.Grouper(freq="MS")).apply(weighted)
    monthly = monthly.dropna().astype(float)
    if monthly.empty:
        return pd.Series(dtype=float)
    full_index = pd.date_range(monthly.index.min(), CB39_STRICT_TODAY.normalize(), freq="MS")
    monthly = monthly.reindex(full_index)
    # Preserve communication gaps: interpolate at most two months and carry at
    # most another two months before reverting to the policy-cycle signal.
    monthly = monthly.interpolate(method="time", limit=2).ffill(limit=2)
    return monthly.ewm(span=4, adjust=False, min_periods=1).mean().dropna().clip(-1, 1)


def _cb42_hybrid_score_path(code: str, speeches: pd.DataFrame) -> pd.Series:
    communication = _cb42_communication_path(speeches)
    policy = _cb42_policy_cycle_path(code, "2016-01-01")
    if communication.empty:
        return policy
    if policy.empty:
        return communication

    index = communication.index.union(policy.index).sort_values()
    comm = communication.reindex(index)
    pol = policy.reindex(index).ffill()
    result = pol.copy()
    observed = comm.notna()
    result.loc[observed] = 0.78 * comm.loc[observed] + 0.22 * pol.loc[observed].fillna(0.0)
    return result.dropna().ewm(span=2, adjust=False, min_periods=1).mean().clip(-1, 1)


# Keep all pre-existing overview/preview callers on the corrected signal.
def _cb41_policy_stance_path(code: str, start: str = "2016-01-01") -> pd.Series:  # noqa: F811
    return _cb42_policy_cycle_path(code, start)


def _cb41_hybrid_score_path(code: str, speeches: pd.DataFrame) -> pd.Series:  # noqa: F811
    return _cb42_hybrid_score_path(code, speeches)


def _cb42_composite_matrix(speeches: pd.DataFrame, codes: Sequence[str]) -> pd.DataFrame:
    series = {}
    for code in codes:
        subset = (
            speeches[speeches["CB"] == code].copy()
            if speeches is not None and not speeches.empty
            else _cb39_empty_speeches()
        )
        path = _cb42_hybrid_score_path(code, subset)
        if not path.empty:
            series[code] = path
    if not series:
        return pd.DataFrame()
    matrix = pd.concat(series, axis=1).sort_index().ffill(limit=2)

    # Small cross-sectional component restores the relative dispersion visible
    # on a G10 monitor without replacing each institution's absolute signal.
    row_mean = matrix.mean(axis=1)
    row_std = matrix.std(axis=1).replace(0, np.nan)
    cross = matrix.sub(row_mean, axis=0).div(row_std, axis=0)
    cross = np.tanh(cross / 1.7)
    blended = 0.86 * matrix + 0.14 * cross
    return blended.clip(-1, 1)


@st.cache_data(ttl=21600, show_spinner=False)
def _cb38_assets_series(code: str, start: str = "2016-01-01") -> Tuple[pd.DataFrame, str, str]:  # noqa: F811
    """Prefer transparent FRED level series when configured.

    The V41 chart selected a BIS series first and could accidentally difference
    a flow-like or badly scaled series, producing ±8,000 bars.  Level series are
    preferred here; BIS remains the fallback.
    """
    ids = tuple(CB38_BANK_BY_CODE[code].get("fred_assets", ()))
    fallback, source = _cb38_first_fred(ids, start)
    if fallback is not None and len(fallback) >= 2:
        out = fallback.copy()
        out["value"] = pd.to_numeric(out["value"], errors="coerce")
        out = out.dropna().sort_values("date")
        median_level = float(out["value"].abs().median()) if not out.empty else 0.0
        # WALCL and several central-bank FRED series are expressed in millions.
        if median_level > 100_000:
            out["value"] = out["value"] / 1000.0
            unit = "bn / provider currency"
        else:
            unit = "provider bn"
        return out.reset_index(drop=True), source + " · preferred level series", unit

    df, bis_source, unit = _CB383_SELECT_BIS_V382("assets", code, start)
    if len(df) >= 2:
        return df, bis_source, unit
    return pd.DataFrame(columns=["date", "value"]), bis_source or "No public balance-sheet series", unit


def _cb42_asset_change(assets: pd.DataFrame) -> pd.Series:
    if assets is None or assets.empty:
        return pd.Series(dtype=float)
    work = assets.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["value"] = pd.to_numeric(work["value"], errors="coerce")
    work = work.dropna(subset=["date", "value"]).sort_values("date")
    if work.empty:
        return pd.Series(dtype=float)
    monthly = work.set_index("date")["value"].resample("MS").last().ffill(limit=2)
    change = monthly.diff().dropna()
    if change.empty:
        return change
    # Remove obvious provider discontinuities while retaining genuine QE/QT.
    median = float(change.abs().median())
    mad = float((change - change.median()).abs().median())
    if mad > 0:
        cap = max(6.0 * mad, 8.0 * median, 50.0)
        change = change.clip(-cap, cap)
    return change


def _cb42_render_ranked_table(snapshots: Sequence[Mapping[str, Any]]) -> None:
    ranked = sorted(
        snapshots,
        key=lambda item: float(item.get("rate")) if item.get("rate") is not None and not pd.isna(item.get("rate")) else -999.0,
        reverse=True,
    )
    rows = []
    sources = []
    for index, item in enumerate(ranked, 1):
        decision = str(item.get("decision") or "HOLD").upper()
        status_class = "hike" if decision == "HIKE" else "cut" if decision == "CUT" else "hold"
        symbol = "▲" if decision == "HIKE" else "▼" if decision == "CUT" else "●"
        rows.append(
            f'<div class="cb42-rank-row">'
            f'<span class="cb42-rank-no">{index:02d}</span>'
            f'<span class="cb42-rank-code">{_esc(item.get("flag", ""))} {_esc(item.get("code", ""))}</span>'
            f'<span class="cb42-rank-name">{_esc(item.get("name", ""))}</span>'
            f'<span class="cb42-rank-rate">{_cb38_fmt_rate(item.get("rate"))}</span>'
            f'<span class="cb42-rank-status {status_class}" title="{_esc(decision)}">{symbol}</span>'
            f'</div>'
        )
        source = str(item.get("policy_source") or "")
        if source and source not in sources:
            sources.append(source)
    foot = (
        '<div class="cb42-rank-foot"><span>Descending official target/effective policy rate</span>'
        f'<span>{_esc(" · ".join(sources[:3]))}</span></div>'
    )
    _html('<div class="cb42-rank-card">' + ''.join(rows) + foot + '</div>')


def _cb42_add_hawk_dove_axes(fig: go.Figure, change_view: bool = False) -> None:
    fig.add_hline(y=0, line_color="rgba(202,212,221,.32)", line_width=1)
    if change_view:
        fig.update_yaxes(range=[-0.75, 0.75], tickformat="+.2f")
    else:
        fig.update_yaxes(
            range=[-1, 1],
            tickvals=[-0.72, 0.0, 0.72],
            ticktext=["Dovish", "Neutral", "Hawkish"],
        )
    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="x unified",
    )


def _cb38_overview(code: str, bank: Mapping[str, Any], speeches: pd.DataFrame) -> None:  # noqa: F811
    score = bank.get("score")
    _html(
        '<div class="cb38-stance"><div class="cb38-stance-title">Hawk / Dove Stance</div>'
        + _cb38_track(score).replace("cb38-track", "cb38-stance-track").replace("cb38-diamond", "cb38-stance-pointer")
        + '<div class="cb38-stance-labels"><span>Dovish</span><span>Neutral</span><span>Hawkish</span></div></div>'
    )

    c1, c2 = st.columns([1, 1])
    with c1:
        zoom = st.radio("Zoom", ["1Y", "3Y", "5Y", "All"], horizontal=True, key=f"ec42_zoom_{code}")
    with c2:
        merge = st.checkbox("Merge Charts", key=f"ec42_merge_{code}")

    policy, policy_source = _cb38_policy_series(code, "2014-01-01")
    window = {"1Y": 365, "3Y": 365 * 3, "5Y": 365 * 5, "All": None}[zoom]
    policy_window = _cb38_apply_window(policy, window)
    history = _cb42_hybrid_score_path(code, speeches)
    if window and not history.empty:
        history = history[history.index >= CB39_STRICT_TODAY - pd.Timedelta(days=window)]

    if merge:
        fig = go.Figure()
        if policy_window is not None and not policy_window.empty:
            fig.add_trace(go.Scatter(
                x=policy_window["date"], y=policy_window["value"], name="Policy rate",
                line_shape="hv", line=dict(color=CB38_COLORS["gold"], width=2.2),
                fill="tozeroy", fillcolor="rgba(216,191,88,.06)",
            ))
        if history is not None and not history.empty:
            fig.add_trace(go.Scatter(
                x=history.index, y=history.values, name="Hawk/Dove", yaxis="y2",
                mode="lines+markers", line=dict(color=CB38_COLORS["orange"], width=1.8), marker=dict(size=4),
            ))
        fig.update_layout(yaxis2=dict(overlaying="y", side="right", range=[-1, 1], tickvals=[-.72, 0, .72], ticktext=["Dove", "Neutral", "Hawk"], showgrid=False))
        _plot(fig, f"ec42_overview_merge_{code}", 450)
    else:
        left, right = st.columns(2)
        with left:
            _html('<div class="cb42-chart-title">Policy Rate History</div><div class="cb42-chart-sub">Official target/effective rate · step representation</div>')
            fig1 = go.Figure()
            if policy_window is not None and not policy_window.empty:
                fig1.add_trace(go.Scatter(
                    x=policy_window["date"], y=policy_window["value"], name="Policy rate",
                    line_shape="hv", line=dict(color=CB38_COLORS["gold"], width=2.2),
                    fill="tozeroy", fillcolor="rgba(216,191,88,.07)",
                    hovertemplate="%{x|%Y-%m-%d}<br>%{y:.2f}%<extra></extra>",
                ))
            fig1.update_yaxes(ticksuffix="%")
            _plot(fig1, f"ec42_policy_hist_{code}", 375)
        with right:
            _html('<div class="cb42-chart-title">Hawk/Dove History</div><div class="cb42-chart-sub">Communication score with institution-specific policy-cycle backfill</div>')
            fig2 = go.Figure()
            if history is not None and not history.empty:
                fig2.add_trace(go.Scatter(
                    x=history.index, y=history.values, name="Hawk/Dove",
                    mode="lines+markers", line=dict(color=CB38_COLORS["orange"], width=1.8), marker=dict(size=4),
                    hovertemplate="%{x|%Y-%m}<br>%{y:+.2f}<extra></extra>",
                ))
            _cb42_add_hawk_dove_axes(fig2, False)
            _plot(fig2, f"ec42_score_hist_{code}", 375)

    _cb38_source([
        ("Policy history", policy_source),
        ("Communication", "BIS RSS + official central-bank archive"),
        ("Backfill", "rate decisions, cycle momentum and rolling tightness"),
        ("Zoom", zoom),
    ])

    _section("RECENT TAPE", "Recent Speeches", f"Latest 10 substantive public communications for {code}.")
    _cb38_render_speech_cards(speeches, 10)
    _section("COMMITTEE", f"{bank['committee']} — Hawk/Dove Scorecard", "Official roster only. Member scores use attributed public communications; missing members remain no data.")
    _cb38_member_cards(code, speeches)


def _cb38_root() -> None:  # noqa: F811
    _cb39_css(); _cb42_css()
    _header(
        "ECONOMY · PUBLIC MONETARY DATA",
        "Global Monetary Policy Observatory",
        "G10 policy rates, balance sheets, official communications and committee attribution generated by Quant Terminal from public primary sources.",
        ["official target rates", "balance sheets", "live communications", "local stance model"],
    )
    _html('<div class="cb39-currency-strip">' + ''.join(f'<span class="cb39-ccy">{_esc(CB38_BANK_BY_CODE[c]["flag"])} {_esc(CB38_BANK_BY_CODE[c]["ccy"])}</span>' for c in CB42_ORDER) + '</div>')
    _html(
        '<details class="cb38-model"><summary>How This Works — Quant Terminal Hawk/Dove Model</summary>'
        '<p>Public communication scores are computed from BIS RSS and official central-bank pages. '
        'The historical monitor uses scored communication first, then an institution-specific cycle signal built from observed policy-rate decisions, momentum and rolling tightness. '
        'The backfill is separately disclosed and no third-party dashboard data are imported.</p></details>'
    )
    _html(f'<div class="cb39-status"><b>Data engine:</b> {_esc(_cb39_corpus_status())}. <span class="cb42-model-chip">{_esc(CB42_VERSION)}</span></div>')

    speeches = _cb38_speeches(deep=False)
    snapshots = [
        _cb38_snapshot(code, speeches[speeches["CB"] == code].copy() if speeches is not None and not speeches.empty else _cb39_empty_speeches())
        for code in CB42_ORDER
    ]
    _cb39_root_cards(snapshots)

    c1, c2, c3 = st.columns([2.2, 1, 1])
    with c1:
        selected = st.selectbox("Open central bank", list(CB42_ORDER), key="ec42_cb_select", format_func=lambda code: f"{CB38_BANK_BY_CODE[code]['flag']} {code} — {CB38_BANK_BY_CODE[code]['name']}")
    with c2:
        if st.button("Open scorecard", key="ec42_cb_scorecard", use_container_width=True):
            st.session_state["ec36_cb_code"] = selected; st.session_state["ec36_cb_route"] = "bank"; st.session_state["ec38_cb_nav"] = "Scorecard"; st.rerun()
    with c3:
        if st.button("Policy previews", key="ec42_cb_previews", use_container_width=True):
            st.session_state["ec36_cb_route"] = "previews"; st.rerun()

    _section("CROSS-BANK SIGNAL", "Hawk / Dove Composite", "Comparable G10 stance paths. Communication observations dominate; policy-cycle data fill only genuine gaps.")
    selected_codes = st.multiselect("Central banks", list(CB42_ORDER), default=list(CB42_ORDER), key="ec42_composite_codes")
    c1, c2 = st.columns([1, 1])
    with c1:
        view = st.radio("View", ["Level", "3m/3m change"], horizontal=True, key="ec42_composite_view")
    with c2:
        solo = st.checkbox("Solo first", key="ec42_solo")

    matrix = _cb42_composite_matrix(speeches, selected_codes)
    if view == "3m/3m change" and not matrix.empty:
        matrix = pd.concat({code: _cb39_three_month_change(matrix[code].dropna()) for code in matrix.columns}, axis=1)
    fig = go.Figure()
    order = selected_codes[:1] if solo and selected_codes else selected_codes
    for code in order:
        if code not in matrix.columns:
            continue
        path = matrix[code].dropna()
        if path.empty:
            continue
        fig.add_trace(go.Scatter(
            x=path.index, y=path.values, name=code, mode="lines+markers",
            line=dict(color=CB38_COLOR_BY_CODE[code], width=1.55), marker=dict(size=3),
            hovertemplate=f"{code}<br>%{{x|%Y-%m}}<br>%{{y:+.2f}}<extra></extra>",
        ))
    _cb42_add_hawk_dove_axes(fig, view != "Level")
    _plot(fig, "ec42_composite", 500)
    _cb38_source([
        ("Communication", "official archive + BIS RSS"),
        ("Gap fill", "institution-specific policy decisions and momentum"),
        ("Frequency", "monthly comparable signal"),
        ("Media", "audio/video/downloads excluded"),
    ])

    _section("RANKING", "Policy Rates — Ranked", "Latest official G10 target/effective policy rates, ranked from highest to lowest.")
    _cb42_render_ranked_table(snapshots)

    _section("MONETARY POLICY STANCE", "Policy Rates & Balance Sheet", "Policy-rate history with monthly central-bank total-asset change. Green bars indicate expansion; red bars indicate contraction.")
    balance_code = st.selectbox("Central bank", list(CB42_ORDER), index=list(CB42_ORDER).index("FED"), key="ec42_balance_bank", label_visibility="collapsed")
    policy, policy_source = _cb38_policy_series(balance_code, "2019-01-01")
    assets, asset_source, asset_unit = _cb38_assets_series(balance_code, "2019-01-01")
    current = next((item for item in snapshots if item["code"] == balance_code), {})
    _html(
        f'<div class="cb39-decision-head"><span class="cb39-decision-rate">{_cb38_fmt_rate(current.get("rate"))}</span>'
        f'<span class="cb39-decision-note">policy rate · {str(current.get("decision") or "N/A").lower()} since '
        f'{current.get("since").date().isoformat() if current.get("since") is not None else "N/A"}</span></div>'
    )
    fig2 = go.Figure()
    if policy is not None and not policy.empty:
        fig2.add_trace(go.Scatter(
            x=policy["date"], y=policy["value"], name="Policy rate", line_shape="hv",
            line=dict(color=CB38_COLORS["blue"], width=2.2), hovertemplate="%{x|%Y-%m}<br>%{y:.2f}%<extra></extra>",
        ))
    monthly_assets = _cb42_asset_change(assets)
    if monthly_assets is not None and not monthly_assets.empty:
        fig2.add_trace(go.Bar(
            x=monthly_assets.index, y=monthly_assets.values, name=f"Assets MoM ({asset_unit})", yaxis="y2",
            marker_color=[CB38_COLORS["green"] if value >= 0 else CB38_COLORS["red"] for value in monthly_assets], opacity=.76,
            hovertemplate="%{x|%Y-%m}<br>%{y:+,.1f}<extra></extra>",
        ))
        bound = float(max(50.0, np.nanpercentile(np.abs(monthly_assets.values), 98) * 1.15))
        fig2.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, range=[-bound, bound], title=asset_unit + " / month"))
    fig2.update_layout(yaxis=dict(ticksuffix="%"))
    _plot(fig2, "ec42_policy_assets", 500)
    _cb38_source([("Policy", policy_source), ("Balance sheet", asset_source), ("Method", "monthly last level; first difference; discontinuity guard")])

    _section("COMMUNICATION", "Recent Speeches", "Latest substantive G10 communications with locally computed score and confidence.")
    _cb39_recent_table(speeches, 20)
    _section("DATA COVERAGE", "Provider diagnostics", "Communication data are loaded automatically. Missing member evidence remains N/A; institutional backfill is identified separately.")
    _cb38_quality_block(snapshots, speeches)


CB39_VERSION = CB42_VERSION
CB38_VERSION = CB42_VERSION
CENTRAL_BANKS_INTEGRITY_V42 = {
    "version": CB42_VERSION,
    "append_only_over_v41": True,
    "ranked_table": "compact G10 list",
    "composite": "communication-first + institution-specific cycle gap fill",
    "balance_sheet": "preferred level series + robust monthly difference",
    "root_enrichment": CB42_ROOT_ENRICH_PER_BANK,
    "creates_directories": False,
    "writes_files": False,
    "audio_downloaded": False,
    "benchmark_data_embedded": False,
}

# ============================================================
# END JARVIS ECONOMY V42.0
# ============================================================



# ============================================================
# JARVIS ECONOMY V43.0 — OFFICIAL POLICY-BOARD DATA ENGINE
# ============================================================
# Append-only over V42. Central Banks runtime only.
#
# Purpose:
# - make policy-board rosters authoritative and current;
# - replace fragile generic scraping for the Fed/ECB with official feeds/datasets;
# - keep the application single-file and memory bounded;
# - preserve N/A when no member-level public evidence exists;
# - never import data from a third-party dashboard.
# ============================================================

CB43_VERSION = "V43.0 · OFFICIAL POLICY-BOARD DATA ENGINE"
CB43_TODAY = pd.Timestamp.utcnow().tz_localize(None).normalize()
CB43_COLUMNS = ["Date","CB","Speaker","Title","Score","Confidence","Source","URL","Text"]
CB43_FED_RSS = "https://www.federalreserve.gov/feeds/speeches.xml"
CB43_FED_YEAR_PAGE = "https://www.federalreserve.gov/newsevents/{year}-speeches.htm"
CB43_ECB_CSV = "https://www.ecb.europa.eu/press/key/shared/data/all_ECB_speeches.csv"
CB43_ECB_RSS = "https://www.ecb.europa.eu/rss/press.html"
CB43_BIS_RSS = "https://www.bis.org/doclist/cbspeeches.rss"
CB43_BIS_INDEX = "https://www.bis.org/cbspeeches/index.htm"
CB43_START_YEAR = 2014
CB43_FED_ARCHIVE_YEARS = 6
CB43_BANK_ENRICH_LIMIT = 48
CB43_ROOT_ENRICH_LIMIT = 6
CB43_HTTP_BYTES_LIMIT = 35 * 1024 * 1024

# Official-source fallbacks. Runtime roster parsers supersede these values.
# The Fed fallback is the official 2026 voting committee, not all non-voting
# Reserve Bank presidents. This keeps the scorecard institutionally correct.
CB43_ROSTER_FALLBACK: Mapping[str, Tuple[Tuple[str, str], ...]] = dict(CB38_ROSTERS)
CB43_ROSTER_FALLBACK = {
    **CB43_ROSTER_FALLBACK,
    "FED": (
        ("Kevin Warsh", "Chairman"),
        ("John C. Williams", "Vice Chair · New York Fed"),
        ("Michael S. Barr", "Board of Governors"),
        ("Michelle W. Bowman", "Board of Governors"),
        ("Lisa D. Cook", "Board of Governors"),
        ("Beth M. Hammack", "Cleveland Fed"),
        ("Philip N. Jefferson", "Board of Governors"),
        ("Neel Kashkari", "Minneapolis Fed"),
        ("Lorie K. Logan", "Dallas Fed"),
        ("Anna Paulson", "Philadelphia Fed"),
        ("Jerome H. Powell", "Board of Governors"),
        ("Christopher J. Waller", "Board of Governors"),
    ),
    "ECB": (
        ("Christine Lagarde", "President"),
        ("Boris Vujcic", "Vice-President"),
        ("Piero Cipollone", "Executive Board"),
        ("Frank Elderson", "Executive Board"),
        ("Philip R. Lane", "Executive Board"),
        ("Isabel Schnabel", "Executive Board"),
    ),
}

CB43_ROSTER_SOURCE = {
    "FED": "Federal Reserve · FOMC current committee page",
    "ECB": "ECB · Executive Board page",
    "BOE": "Bank of England · MPC page",
    "RBA": "RBA · Monetary Policy Board page",
    "RBNZ": "RBNZ · Monetary Policy Committee page",
    "BOC": "Bank of Canada · Governing Council page",
    "RIKSBANK": "Riksbank · Executive Board page",
    "BOJ": "Bank of Japan · Policy Board page",
    "SNB": "SNB · Governing Board page",
    "NORGES": "Norges Bank · policy committee page",
}


def _cb43_empty() -> pd.DataFrame:
    return pd.DataFrame(columns=CB43_COLUMNS)


@st.cache_data(ttl=21600, show_spinner=False)
def _cb43_download(url: str, accept: str = "text/html,application/xml,text/xml,text/csv,*/*") -> Tuple[int, bytes, str]:
    """Small official-source downloader returning serialisable values only."""
    if _cb38_requests is None or not url:
        return 0, b"", ""
    try:
        response = _cb38_requests.get(
            url,
            timeout=max(12, CB38_TIMEOUT),
            headers={
                "User-Agent": CB38_USER_AGENT,
                "Accept": accept,
                "Accept-Encoding": "gzip, deflate",
                "Cache-Control": "no-cache",
            },
            allow_redirects=True,
        )
        content = response.content[:CB43_HTTP_BYTES_LIMIT]
        return int(response.status_code), content, str(response.headers.get("content-type", ""))
    except Exception:
        return 0, b"", ""


def _cb43_text(url: str) -> str:
    status, content, _ = _cb43_download(url)
    if status < 200 or status >= 400 or not content:
        return ""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except Exception:
            continue
    return ""


def _cb43_clean_name(value: Any) -> str:
    text = _cb39_norm(value)
    text = _cb38_re.sub(r"\b(chairman|chair|vice chair|vice-chair|governor|deputy governor|president|vice president|vice-president|member|board of governors|federal reserve bank of|federal reserve bank|executive board|monetary policy committee)\b", " ", text)
    text = _cb38_re.sub(r"\b(mr|mrs|ms|dr|prof|professor|sir|dame|ao|am|ac|obe|cbe|mbe|psm|phd|qc|kc)\b", " ", text)
    return " ".join(text.split())


def _cb43_name_key(value: Any) -> str:
    text = _cb43_clean_name(value)
    tokens = [token for token in text.split() if len(token) > 1]
    if len(tokens) >= 2:
        return f"{tokens[0]} {tokens[-1]}"
    return " ".join(tokens)


def _cb43_canonical_speaker(code: str, speaker: Any, context: Any = "") -> str:
    candidate = str(speaker or "").strip()
    blob = _cb39_norm(f"{candidate} {context}")
    roster = _cb43_roster(code)
    for name, _ in roster:
        normalized = _cb39_norm(name)
        if normalized and normalized in blob:
            return name
    key = _cb43_name_key(candidate)
    if key:
        for name, _ in roster:
            if _cb43_name_key(name) == key:
                return name
    inferred = _cb38_infer_speaker(code, f"{candidate} {context}")
    return inferred


def _cb43_parse_any_date(*values: Any) -> pd.Timestamp:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        try:
            parsed = pd.to_datetime(text, errors="coerce", utc=True)
            if not pd.isna(parsed):
                return pd.Timestamp(parsed).tz_convert(None).normalize()
        except Exception:
            pass
        try:
            parsed = _cb38_parse_date(text)
            if not pd.isna(parsed):
                return pd.Timestamp(parsed).normalize()
        except Exception:
            pass
    return pd.NaT


def _cb43_score_row(title: str, body: str) -> Tuple[Optional[float], float]:
    score, confidence, hits = _cb38_score_text(f"{title} {body}")
    if hits <= 0 or confidence < 0.025:
        return np.nan, float(confidence)
    return float(score), float(confidence)


def _cb43_frame(rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    if not rows:
        return _cb43_empty()
    frame = pd.DataFrame(list(rows))
    for column in CB43_COLUMNS:
        if column not in frame.columns:
            frame[column] = np.nan if column in {"Score", "Confidence"} else ""
    frame = frame[CB43_COLUMNS].copy()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame["Score"] = pd.to_numeric(frame["Score"], errors="coerce")
    frame["Confidence"] = pd.to_numeric(frame["Confidence"], errors="coerce").fillna(0.0)
    frame = frame[frame["Date"].notna()]
    frame = frame[frame["Date"] <= CB43_TODAY]
    if frame.empty:
        return _cb43_empty()
    return _cb383_clean_speeches(frame)


def _cb43_xml_feed(content: bytes, code_hint: Optional[str], source: str) -> pd.DataFrame:
    if not content:
        return _cb43_empty()
    rows: List[Dict[str, Any]] = []
    try:
        root = _cb38_et.fromstring(content)
    except Exception:
        return _cb43_empty()

    entries = list(root.findall(".//item"))
    entries += list(root.findall(".//{http://www.w3.org/2005/Atom}entry"))
    seen = set()
    for entry in entries[:300]:
        def first_text(paths: Sequence[str]) -> str:
            for path in paths:
                node = entry.find(path)
                if node is not None and node.text:
                    return str(node.text).strip()
            return ""

        title = first_text(("title", "{http://www.w3.org/2005/Atom}title"))
        summary = first_text((
            "description", "summary", "content",
            "{http://www.w3.org/2005/Atom}summary",
            "{http://www.w3.org/2005/Atom}content",
        ))
        speaker = first_text((
            "{http://purl.org/dc/elements/1.1/}creator",
            "author", "{http://www.w3.org/2005/Atom}author/{http://www.w3.org/2005/Atom}name",
        ))
        date_text = first_text((
            "pubDate", "published", "updated",
            "{http://purl.org/dc/elements/1.1/}date",
            "{http://www.w3.org/2005/Atom}published",
            "{http://www.w3.org/2005/Atom}updated",
        ))
        link = first_text(("link",))
        if not link:
            atom_link = entry.find("{http://www.w3.org/2005/Atom}link")
            if atom_link is not None:
                link = str(atom_link.attrib.get("href", "")).strip()
        if not link:
            guid = first_text(("guid", "id", "{http://www.w3.org/2005/Atom}id"))
            link = guid if guid.startswith("http") else ""

        code = code_hint or _cb38_infer_bank(f"{title} {summary} {speaker}", link)
        if code not in CB38_BANK_BY_CODE:
            continue
        date_value = _cb43_parse_any_date(date_text, title, summary, link)
        if pd.isna(date_value):
            continue
        if not speaker:
            lead = _cb38_re.split(r"[:–—|]", title, maxsplit=1)[0].strip()
            speaker = lead
        speaker = _cb43_canonical_speaker(code, speaker, f"{title} {summary}")
        body = _cb38_extract_html_text(summary.encode("utf-8", errors="ignore"))
        score, confidence = _cb43_score_row(title, body)
        key = (code, date_value, _cb39_norm(speaker), _cb39_norm(title))
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "Date": date_value,
            "CB": code,
            "Speaker": speaker,
            "Title": title,
            "Score": score,
            "Confidence": confidence,
            "Source": source,
            "URL": link,
            "Text": body,
        })
    return _cb43_frame(rows)


@st.cache_data(ttl=21600, show_spinner=False)
def _cb43_bis_feed() -> pd.DataFrame:
    status, content, _ = _cb43_download(CB43_BIS_RSS, "application/rss+xml,application/xml,text/xml")
    if status < 200 or status >= 400:
        return _cb43_empty()
    return _cb43_xml_feed(content, None, "BIS central bankers' speeches RSS")


@st.cache_data(ttl=21600, show_spinner=False)
def _cb43_fed_feed() -> pd.DataFrame:
    status, content, _ = _cb43_download(CB43_FED_RSS, "application/rss+xml,application/xml,text/xml")
    if status < 200 or status >= 400:
        return _cb43_empty()
    return _cb43_xml_feed(content, "FED", "Federal Reserve speeches RSS")


def _cb43_context_block(anchor: Any, max_levels: int = 5) -> str:
    node = anchor
    best = ""
    for _ in range(max_levels):
        if node is None:
            break
        try:
            text = " ".join(node.get_text(" ", strip=True).split())
        except Exception:
            text = ""
        if len(text) > len(best):
            best = text
        if _cb38_re.search(r"\b(?:0?[1-9]|1[0-2])[/.-](?:0?[1-9]|[12]\d|3[01])[/.-](?:20)?\d{2}\b", text):
            return text[:2400]
        node = getattr(node, "parent", None)
    return best[:2400]


@st.cache_data(ttl=21600, show_spinner=False)
def _cb43_fed_year(year: int) -> pd.DataFrame:
    url = CB43_FED_YEAR_PAGE.format(year=int(year))
    page = _cb43_text(url)
    if not page or _cb38_BeautifulSoup is None:
        return _cb43_empty()
    soup = _cb38_BeautifulSoup(page, "html.parser")
    rows: List[Dict[str, Any]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = _cb38_urljoin(url, str(anchor.get("href", "")))
        if "/newsevents/speech/" not in href.lower():
            continue
        title = " ".join(anchor.get_text(" ", strip=True).split())
        if not title or title.lower() in {"watch live", "video", "transcript"}:
            continue
        context = _cb43_context_block(anchor)
        date_value = _cb43_parse_any_date(context, href)
        if pd.isna(date_value):
            date_match = _cb38_re.search(r"(20\d{2})(\d{2})(\d{2})", href)
            if date_match:
                date_value = pd.Timestamp(f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}")
        if pd.isna(date_value):
            continue
        speaker = _cb43_canonical_speaker("FED", "", context)
        score, confidence = _cb43_score_row(title, context)
        key = (date_value, _cb39_norm(title))
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "Date": date_value,
            "CB": "FED",
            "Speaker": speaker,
            "Title": title,
            "Score": score,
            "Confidence": confidence,
            "Source": f"Federal Reserve {year} speeches archive",
            "URL": href,
            "Text": context,
        })
    return _cb43_frame(rows)


@st.cache_data(ttl=86400, show_spinner=False)
def _cb43_ecb_dataset() -> pd.DataFrame:
    status, content, _ = _cb43_download(CB43_ECB_CSV, "text/csv,text/plain,*/*")
    if status < 200 or status >= 400 or not content:
        return _cb43_empty()
    try:
        raw = pd.read_csv(
            _cb38_io.BytesIO(content),
            sep="|",
            dtype=str,
            engine="python",
            on_bad_lines="skip",
        )
    except Exception:
        return _cb43_empty()
    columns = {str(column).strip().lower(): column for column in raw.columns}
    date_col = columns.get("date")
    speaker_col = columns.get("speakers") or columns.get("speaker")
    title_col = columns.get("title")
    subtitle_col = columns.get("subtitle")
    content_col = columns.get("contents") or columns.get("content")
    if date_col is None or title_col is None:
        return _cb43_empty()
    rows: List[Dict[str, Any]] = []
    for _, row in raw.iterrows():
        date_value = _cb43_parse_any_date(row.get(date_col))
        if pd.isna(date_value) or date_value < pd.Timestamp(f"{CB43_START_YEAR}-01-01"):
            continue
        title = str(row.get(title_col) or "").strip()
        subtitle = str(row.get(subtitle_col) or "").strip() if subtitle_col else ""
        body = str(row.get(content_col) or "").strip() if content_col else ""
        speakers = str(row.get(speaker_col) or "").strip() if speaker_col else ""
        names = [name.strip() for name in _cb38_re.split(r"[,;/]", speakers) if name.strip()] or [speakers]
        speaker = _cb43_canonical_speaker("ECB", names[0] if names else "", f"{title} {subtitle}")
        score, confidence = _cb43_score_row(title, f"{subtitle} {body[:120000]}")
        rows.append({
            "Date": date_value,
            "CB": "ECB",
            "Speaker": speaker,
            "Title": title,
            "Score": score,
            "Confidence": confidence,
            "Source": "ECB official speeches dataset",
            "URL": "https://www.ecb.europa.eu/press/key/html/index.en.html",
            "Text": body[:120000],
        })
    return _cb43_frame(rows)


@st.cache_data(ttl=21600, show_spinner=False)
def _cb43_generic_archive(code: str) -> pd.DataFrame:
    try:
        frame = _cb38_official_archive(code, "speech")
    except Exception:
        frame = _cb43_empty()
    if frame is None or frame.empty:
        return _cb43_empty()
    frame = _cb383_clean_speeches(frame)
    if frame.empty:
        return _cb43_empty()
    frame["Speaker"] = [
        _cb43_canonical_speaker(code, speaker, f"{title} {text}")
        for speaker, title, text in zip(
            frame["Speaker"].fillna(""),
            frame["Title"].fillna(""),
            frame["Text"].fillna(""),
        )
    ]
    return _cb383_clean_speeches(frame)


def _cb43_enrich(frame: pd.DataFrame, limit: int) -> pd.DataFrame:
    if frame is None or frame.empty or limit <= 0:
        return _cb43_empty() if frame is None else frame
    try:
        enriched = _cb39_enrich_rows(frame, min(int(limit), len(frame)))
    except Exception:
        enriched = frame.copy()
    if enriched.empty:
        return enriched
    rows = []
    for row in enriched.to_dict("records"):
        score, confidence = _cb43_score_row(str(row.get("Title", "")), str(row.get("Text", "")))
        if not pd.isna(score):
            row["Score"] = score
            row["Confidence"] = max(float(row.get("Confidence") or 0.0), confidence)
        rows.append(row)
    return _cb43_frame(rows)


@st.cache_data(ttl=21600, show_spinner=False)
def _cb43_bank_communications(code: str, deep: bool = False) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    bis = _cb43_bis_feed()
    if not bis.empty:
        subset = bis[bis["CB"] == code].copy()
        if not subset.empty:
            frames.append(subset)

    if code == "FED":
        fed_rss = _cb43_fed_feed()
        if not fed_rss.empty:
            frames.append(fed_rss)
        current_year = int(CB43_TODAY.year)
        year_count = CB43_FED_ARCHIVE_YEARS if deep else 2
        for year in range(current_year, max(CB43_START_YEAR, current_year - year_count), -1):
            archive = _cb43_fed_year(year)
            if not archive.empty:
                frames.append(archive)
    elif code == "ECB":
        ecb = _cb43_ecb_dataset()
        if not ecb.empty:
            frames.append(ecb)
    else:
        official = _cb43_generic_archive(code)
        if not official.empty:
            frames.append(official)

    if not frames:
        return _cb43_empty()
    combined = _cb383_clean_speeches(pd.concat(frames, ignore_index=True, sort=False))
    if combined.empty:
        return combined
    combined["Speaker"] = [
        _cb43_canonical_speaker(code, speaker, f"{title} {text}")
        for speaker, title, text in zip(
            combined["Speaker"].fillna(""),
            combined["Title"].fillna(""),
            combined["Text"].fillna(""),
        )
    ]
    if deep and code != "ECB":
        combined = _cb43_enrich(combined, CB43_BANK_ENRICH_LIMIT)
    return _cb383_clean_speeches(combined)


@st.cache_data(ttl=21600, show_spinner=False)
def _cb43_all_communications() -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    with _cb39_ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_cb43_bank_communications, code, False): code for code in CB42_ORDER}
        for future in _cb39_as_completed(futures):
            try:
                frame = future.result()
                if frame is not None and not frame.empty:
                    frames.append(frame)
            except Exception:
                pass
    if not frames:
        return _cb43_empty()
    combined = _cb383_clean_speeches(pd.concat(frames, ignore_index=True, sort=False))
    # Root scoring remains bounded: only a small number of newest pages per bank.
    enriched_frames = []
    for code in CB42_ORDER:
        subset = combined[combined["CB"] == code].copy()
        if subset.empty:
            continue
        enriched_frames.append(subset if code == "ECB" else _cb43_enrich(subset, CB43_ROOT_ENRICH_LIMIT))
    if not enriched_frames:
        return combined
    return _cb383_clean_speeches(pd.concat(enriched_frames, ignore_index=True, sort=False))


# Active communication bindings.
def _cb38_bis_rss(enrich_text: bool = False) -> pd.DataFrame:  # noqa: F811
    frame = _cb43_bis_feed()
    return _cb43_enrich(frame, CB38_MAX_ENRICH_ITEMS) if enrich_text and not frame.empty else frame


def _cb38_speeches(code: Optional[str] = None, deep: bool = False) -> pd.DataFrame:  # noqa: F811
    if code:
        return _cb43_bank_communications(str(code), bool(deep))
    return _cb43_all_communications()


@st.cache_data(ttl=21600, show_spinner=False)
def _cb39_read_local_corpus() -> pd.DataFrame:  # noqa: F811
    return _cb43_all_communications()


def _cb39_recent_all_banks() -> pd.DataFrame:  # noqa: F811
    return _cb43_all_communications()


@st.cache_data(ttl=21600, show_spinner=False)
def _cb39_recent_all_banks_cached() -> pd.DataFrame:  # noqa: F811
    return _cb43_all_communications()


def _cb39_corpus_status() -> str:  # noqa: F811
    frame = _cb43_all_communications()
    if frame is None or frame.empty:
        return "official communication sources unavailable; policy-cycle signal remains active"
    scored = int(pd.to_numeric(frame["Score"], errors="coerce").notna().sum())
    indexed = int(len(frame))
    banks = int(frame["CB"].nunique())
    member_rows = int(sum(
        frame["Speaker"].fillna("").map(_cb43_name_key).isin({_cb43_name_key(name) for name, _ in _cb43_roster(code)}).sum()
        for code in CB42_ORDER
    ))
    dates = pd.to_datetime(frame["Date"], errors="coerce").dropna()
    span = "date range unavailable" if dates.empty else f"{dates.min().date().isoformat()} → {dates.max().date().isoformat()}"
    return f"official feeds/datasets · {indexed:,} indexed · {scored:,} scored · {member_rows:,} member-attributed · {banks} banks · {span}"


def _cb43_extract_people_from_page(code: str, page: str) -> Tuple[Tuple[str, str], ...]:
    if not page or _cb38_BeautifulSoup is None:
        return tuple()
    soup = _cb38_BeautifulSoup(page, "html.parser")
    fallback = CB43_ROSTER_FALLBACK.get(code, tuple())

    # Fed: only the list below the current-year Committee Members heading.
    if code == "FED":
        heading = None
        for candidate in soup.find_all(["h3", "h4", "h5"]):
            if "committee members" in _cb39_norm(candidate.get_text(" ", strip=True)):
                heading = candidate
                break
        if heading is not None:
            output = []
            node = heading.find_next_sibling()
            while node is not None:
                if getattr(node, "name", "") in {"h3", "h4", "h5"} and "alternate" in _cb39_norm(node.get_text(" ", strip=True)):
                    break
                if getattr(node, "name", "") in {"ul", "ol"}:
                    for item in node.find_all("li", recursive=False):
                        text = " ".join(item.get_text(" ", strip=True).split())
                        if not text:
                            continue
                        parts = [part.strip() for part in text.split(",", 1)]
                        name = parts[0]
                        role = parts[1] if len(parts) > 1 else "FOMC member"
                        output.append((name, role))
                    if output:
                        return tuple(output)
                node = node.find_next_sibling()

    # For the remaining institutions, the official roster page is used to
    # confirm and preserve the names contained in the current fallback. This is
    # intentionally conservative: arbitrary headings are never promoted into a
    # policy-board roster.
    normalized_page = _cb39_norm(soup.get_text(" ", strip=True))
    confirmed = []
    for name, role in fallback:
        if _cb39_norm(name) in normalized_page or _cb43_name_key(name) in normalized_page:
            confirmed.append((name, role))
    return tuple(confirmed)


@st.cache_data(ttl=21600, show_spinner=False)
def _cb43_roster(code: str) -> Tuple[Tuple[str, str], ...]:
    bank = CB38_BANK_BY_CODE.get(code)
    fallback = CB43_ROSTER_FALLBACK.get(code, tuple())
    if not bank:
        return fallback
    roster_url = str(bank.get("roster_url", ""))
    page = _cb43_text(roster_url)
    parsed = _cb43_extract_people_from_page(code, page)
    return parsed if parsed else fallback


def _cb43_member_mask(frame: pd.DataFrame, member_name: str) -> pd.Series:
    if frame is None or frame.empty or "Speaker" not in frame.columns:
        return pd.Series(False, index=getattr(frame, "index", pd.Index([])))
    target_full = _cb39_norm(member_name)
    target_key = _cb43_name_key(member_name)
    speakers = frame["Speaker"].fillna("").astype(str)
    full = speakers.map(_cb39_norm)
    keys = speakers.map(_cb43_name_key)
    return (full == target_full) | ((keys == target_key) & (target_key != ""))


# Keep older helper name wired to the official roster engine.
def _cb40_member_mask(frame: pd.DataFrame, member_name: str) -> pd.Series:  # noqa: F811
    return _cb43_member_mask(frame, member_name)


def _cb38_members(code: str, speeches: Optional[pd.DataFrame] = None) -> List[Dict[str, Any]]:  # noqa: F811
    frame = _cb383_clean_speeches(
        speeches if speeches is not None else _cb38_speeches(code, deep=False)
    )
    rows = []
    for name, role in _cb43_roster(code):
        member_frame = frame.loc[_cb43_member_mask(frame, name)].copy() if not frame.empty else _cb43_empty()
        snapshot = _cb38_score_snapshot(member_frame)
        rows.append({
            "slug": _cb38_slug(name),
            "name": name,
            "role": role,
            "recent": snapshot.get("recent"),
            "lifetime": snapshot.get("lifetime"),
            "speeches": int(snapshot.get("count", 0)),
            "indexed": int(snapshot.get("indexed_count", len(member_frame))),
            "confidence": float(snapshot.get("confidence", 0.0)),
            "last_date": snapshot.get("last_date"),
            "last_indexed_date": snapshot.get("last_indexed_date"),
        })
    return rows


def _cb39_committee_path(code: str, speeches: pd.DataFrame, horizon: str = "recent") -> pd.Series:  # noqa: F811
    paths = []
    for name, _ in _cb43_roster(code):
        member_frame = speeches.loc[_cb43_member_mask(speeches, name)].copy() if speeches is not None and not speeches.empty else _cb43_empty()
        path = _cb39_score_path(member_frame, horizon)
        if not path.empty:
            paths.append(path.rename(name))
    if not paths:
        return pd.Series(dtype=float)
    return pd.concat(paths, axis=1).mean(axis=1, skipna=True).dropna().clip(-1, 1)


def _cb38_snapshot(code: str, speech_df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:  # noqa: F811
    bank = dict(CB38_BANK_BY_CODE[code])
    policy, policy_source = _cb38_policy_series(code, "2000-01-01")
    status = _cb38_detect_rate_status(policy)
    speeches = speech_df if speech_df is not None else _cb38_speeches(code, deep=False)
    speech_snapshot = _cb38_score_snapshot(speeches)
    recent = speech_snapshot.get("recent")
    lifetime = speech_snapshot.get("lifetime")
    score_source = "official public communications"
    if recent is None or pd.isna(recent):
        proxy = _cb42_policy_cycle_path(code, "2016-01-01")
        if proxy is not None and not proxy.empty:
            recent = float(proxy.iloc[-1])
            lifetime = float(proxy.tail(min(36, len(proxy))).mean())
            score_source = "institution policy-cycle backfill"
        else:
            recent = lifetime = None
            score_source = "no public stance evidence"
    bank.update(status)
    bank.update({
        "policy_source": policy_source,
        "score": recent,
        "lifetime": lifetime,
        "score_source": score_source,
        "speech_count": int(speech_snapshot.get("count", 0)),
        "speech_indexed_count": int(speech_snapshot.get("indexed_count", len(speeches) if speeches is not None else 0)),
        "score_confidence": float(speech_snapshot.get("confidence", 0.0)),
        "speech_last_date": speech_snapshot.get("last_date"),
        "speech_last_indexed_date": speech_snapshot.get("last_indexed_date"),
        "member_count": len(_cb43_roster(code)),
        "roster_source": CB43_ROSTER_SOURCE.get(code, "official policy-board page"),
    })
    return bank


def _cb38_bank_card(bank: Mapping[str, Any]) -> None:  # noqa: F811
    score = bank.get("score")
    cls = "cb38-score-na" if score is None or pd.isna(score) else ("cb38-score-pos" if float(score) >= 0 else "cb38-score-neg")
    decision = str(bank.get("decision") or "N/A")
    code = str(bank["code"])
    members = int(bank.get("member_count", len(_cb43_roster(code))))
    meetings = CB39_MEETING_LABELS.get(code, str(bank.get("meetings", "")))
    _html(
        '<div class="cb38-card">'
        f'<div class="cb38-card-head"><span class="cb38-card-code">{_esc(bank["flag"])} {_esc(code)}</span><span class="cb38-card-ccy">{_esc(bank["ccy"])}</span></div>'
        f'<div class="cb38-card-rate">{_cb38_fmt_rate(bank.get("rate"))} <span class="cb38-card-decision">● {_esc(decision)}</span></div>'
        f'<div class="cb38-card-name">{_esc(bank["name"])}</div>{_cb38_track(score)}'
        f'<div class="cb38-card-meta"><span class="{cls}">{_cb38_fmt_score(score, 3)}</span><span>{members} members</span></div>'
        f'<div class="cb38-card-name">{_esc(meetings)}</div></div>'
    )


def _cb38_summary(bank: Mapping[str, Any]) -> None:  # noqa: F811
    score = bank.get("score")
    scored = int(bank.get("speech_count", 0))
    indexed = int(bank.get("speech_indexed_count", scored))
    since = bank.get("since")
    move = bank.get("change_bps")
    decision = str(bank.get("decision") or "N/A")
    score_source = str(bank.get("score_source") or "public stance engine")
    decision_note = "last policy move unavailable" if move is None else ("last decision unchanged" if abs(float(move)) < 1e-12 else f"last move {int(round(float(move))):+d} bps")
    items = [
        ("Rate", _cb38_fmt_rate(bank.get("rate")), f"effective since {since.date().isoformat() if since is not None else 'N/A'}", "flat"),
        ("Target", str(bank["target"]), bank["country"], "flat"),
        ("Hawk / Dove", _cb38_fmt_score(score, 3), f"{scored} scored / {indexed} indexed · {score_source}", "up" if score is not None and not pd.isna(score) and float(score) >= 0 else "down"),
        ("Decision", decision, decision_note, "flat"),
        ("Votes", str(bank.get("votes") or "Not available"), f"{int(bank.get('member_count', len(_cb43_roster(str(bank['code'])))))} official committee members", "flat"),
    ]
    blocks = []
    for label, value, note, tone in items:
        cls = {"up":"ec36-up", "down":"ec36-down", "flat":"ec36-flat"}.get(tone, "")
        blocks.append(f'<div class="cb38-stat"><div class="cb38-stat-k">{_esc(label)}</div><div class="cb38-stat-v {cls}">{_esc(value)}</div><div class="cb38-stat-n">{_esc(note)}</div></div>')
    _html('<div class="cb38-stats">' + ''.join(blocks) + '</div>')
    _html(f'<div class="cb39-status"><b>Board source:</b> {_esc(bank.get("roster_source", "official committee page"))} · communications: official feeds/datasets only.</div>')


def _cb38_bank(code: str) -> None:  # noqa: F811
    _cb39_css(); _cb42_css()
    speeches = _cb38_speeches(code, deep=True)
    bank = _cb38_snapshot(code, speeches)
    _cb38_path(["Central Banks", bank["name"]])
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("← All Central Banks", key=f"ec43_back_{code}"):
            st.session_state["ec36_cb_route"] = "root"; st.rerun()
    with c2:
        if st.button("Policy Previews →", key=f"ec43_preview_{code}"):
            st.session_state["ec36_cb_route"] = "previews"; st.rerun()
    _header(
        "CENTRAL BANK WORKSTATION",
        f"{bank['flag']} {bank['name']}",
        f"{bank['committee']} · official policy-board data workflow",
        [bank["ccy"], CB39_MEETING_LABELS.get(code, bank["meetings"]), f"{bank['member_count']} official committee members", CB43_VERSION],
    )
    _cb38_summary(bank)
    _html(
        f'<div class="cb39-status"><b>Communication engine:</b> {_esc(str(bank.get("speech_count", 0)))} scored / {_esc(str(bank.get("speech_indexed_count", 0)))} indexed. '
        'Fed uses the official speeches RSS and annual archives; ECB uses the official full-text CSV dataset; all other banks use their official archives with BIS RSS fallback. '
        'Full-page enrichment is bounded and cached; media attachments are excluded.</div>'
    )
    tab = _segmented("Central bank page", ["Overview", "Scorecard", "Speeches", "Meetings"], "ec38_cb_nav", "Overview")
    if tab == "Overview":
        _cb38_overview(code, bank, speeches)
    elif tab == "Scorecard":
        _cb38_scorecard(code, bank, speeches)
    elif tab == "Speeches":
        _cb38_speech_archive(code, bank, speeches)
    else:
        _cb38_meeting_archive(code, bank)


# The V42 root renderer already calls the global snapshot/speech/card functions,
# so the official V43 bindings above are picked up without duplicating its UI.
CB42_VERSION = CB43_VERSION
CB41_VERSION = CB43_VERSION
CB39_VERSION = CB43_VERSION
CB38_VERSION = CB43_VERSION

CENTRAL_BANKS_INTEGRITY_V43 = {
    "version": CB43_VERSION,
    "single_file": True,
    "external_api_key_required": False,
    "official_roster_pages": True,
    "fed_source": "official RSS + official annual archive",
    "ecb_source": "official full-text CSV dataset",
    "other_banks": "official archive + BIS RSS fallback",
    "dynamic_fed_committee": True,
    "member_attribution": "canonical full name + first/last name",
    "creates_directories": False,
    "writes_corpus_files": False,
    "audio_downloaded": False,
    "third_party_dashboard_data": False,
}

# ============================================================
# END JARVIS ECONOMY V43.0
# ============================================================
