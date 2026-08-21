"""Institutional Company Intelligence UI — V2.4.1.

The UI deliberately distinguishes reported facts, provider snapshots and analytical
proxies. Missing data stays N/A; it is never silently displayed as a neutral score.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .common import fmt_large_number, fmt_num, fmt_pct, safe_float


def _score_text(value) -> str:
    value = safe_float(value)
    return "N/A" if value is None or pd.isna(value) else f"{value:.0f}/100"


def _fmt_optional_pct(value) -> str:
    value = safe_float(value)
    return "N/A" if value is None or pd.isna(value) else fmt_pct(value)


def _fmt_pp(value, decimals: int = 2) -> str:
    """Format a decimal share delta as percentage points, not percent change."""
    value = safe_float(value)
    return "N/A" if value is None or pd.isna(value) else f"{100.0 * value:+.{decimals}f} pp"


def _fmt_signed(value, decimals: int = 2) -> str:
    value = safe_float(value)
    return "N/A" if value is None or pd.isna(value) else f"{value:+.{decimals}f}"


def _format_large_df(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = out[col].apply(fmt_large_number)
    return out


def _format_percent_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = out[col].apply(_fmt_optional_pct)
    return out


def render_institutional_overview(company: dict):
    inst = company.get("institutional", {}) if isinstance(company, dict) else {}
    scores = inst.get("scores", {}) if isinstance(inst, dict) else {}
    own = inst.get("ownership_v2", {}) if isinstance(inst, dict) else {}
    own_sum = own.get("summary", {}) if isinstance(own, dict) else {}
    insider = inst.get("insider_v2", {}) if isinstance(inst, dict) else {}
    insider_sum = insider.get("summary", {}) if isinstance(insider, dict) else {}
    rel = inst.get("relationships", {}) if isinstance(inst, dict) else {}
    rel_sum = rel.get("summary", {}) if isinstance(rel, dict) else {}
    overlay = inst.get("overlay", {}) if isinstance(inst, dict) else {}

    st.subheader("Institutional Intelligence — Executive Cockpit")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Ownership Conviction", _score_text(scores.get("ownership_score")))
    c2.metric("Insider Signal", _score_text(scores.get("insider_score")))
    c3.metric("Product Diversification", _score_text(scores.get("product_diversification_score")))
    c4.metric("Customer Risk", _score_text(scores.get("customer_risk_score")))
    c5.metric("Supplier Risk", _score_text(scores.get("supplier_risk_score")))
    c6.metric("Data Confidence", _score_text(scores.get("data_confidence")))
    if isinstance(overlay, dict) and overlay.get("score") is not None:
        st.caption(
            f"Institutional Overlay: {overlay.get('score'):.0f}/100 · {overlay.get('label', 'N/A')} · "
            f"dimension coverage {overlay.get('coverage', 0):.0f}%. This overlay is kept separate from the Core Fundamental Score."
        )
        with st.expander("Institutional overlay decomposition", expanded=False):
            odf = pd.DataFrame(overlay.get("components", []))
            if not odf.empty:
                if "Score" in odf.columns:
                    odf["Score"] = odf["Score"].apply(lambda x: "N/A" if safe_float(x) is None else f"{safe_float(x):.0f}/100")
                if "Weight" in odf.columns:
                    odf["Weight"] = odf["Weight"].apply(lambda x: f"{safe_float(x):.0f}%" if safe_float(x) is not None else "N/A")
                st.dataframe(odf, use_container_width=True, hide_index=True)

    summary_rows = [
        {
            "Dimension": "Institutional direction",
            "Lecture": _fmt_signed(own_sum.get("weighted_position_change_proxy")),
            "Détail": "Robust weighted reported-holder position-change proxy; this is not a cash-flow estimate.",
        },
        {
            "Dimension": "Active-manager direction",
            "Lecture": _fmt_signed(own_sum.get("active_position_change_proxy")),
            "Détail": "Same proxy excluding holders classified as explicitly passive/index when possible.",
        },
        {
            "Dimension": "Holder breadth",
            "Lecture": _fmt_signed(own_sum.get("breadth")),
            "Détail": f"Increasing {own_sum.get('up_holders', 0)} · Reducing {own_sum.get('down_holders', 0)} · Stable {own_sum.get('stable_holders', 0)}.",
        },
        {
            "Dimension": "Top-10 holder concentration",
            "Lecture": _fmt_optional_pct(own_sum.get("top10")),
            "Détail": "Concentration / crowding measure, not a directional bullish/bearish input by itself.",
        },
        {
            "Dimension": "Product concentration",
            "Lecture": _fmt_optional_pct(inst.get("product_summary", {}).get("top_share")),
            "Détail": "Largest disclosed product/operating revenue segment.",
        },
        {
            "Dimension": "Geographic concentration",
            "Lecture": _fmt_optional_pct(inst.get("geographic_summary", {}).get("top_share")),
            "Détail": "Largest disclosed geographic revenue segment.",
        },
        {
            "Dimension": "Largest explicit customer concentration",
            "Lecture": _fmt_optional_pct(rel_sum.get("max_customer_concentration")),
            "Détail": "Latest 10-K primary-source scan after section filtering and deduplication.",
        },
        {
            "Dimension": "Informative insider activity",
            "Lecture": insider_sum.get("status", "N/A") if insider_sum else "N/A",
            "Détail": "Only open-market purchases/sales are directional; grants, gifts, tax withholding and option mechanics are excluded from the score.",
        },
    ]
    summary_df = pd.DataFrame(summary_rows)
    confidence_map = {
        "Institutional direction": 65 if own_sum else 0,
        "Active-manager direction": 55 if own_sum.get("active_position_change_proxy") is not None else 0,
        "Holder breadth": 65 if own_sum else 0,
        "Top-10 holder concentration": 70 if own_sum.get("top10") is not None else 0,
        "Product concentration": 90 if inst.get("product_summary", {}).get("top_share") is not None else 0,
        "Geographic concentration": 90 if inst.get("geographic_summary", {}).get("top_share") is not None else 0,
        "Largest explicit customer concentration": int(rel_sum.get("customer_confidence") or 0),
        "Informative insider activity": 80 if insider_sum else 0,
    }
    summary_df["Evidence"] = summary_df["Dimension"].map(lambda x: f"{confidence_map.get(x, 0)}/100" if confidence_map.get(x, 0) else "N/A")
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    source_quality = inst.get("source_quality", {})
    source_flags = inst.get("source_flags", {})
    if source_flags:
        with st.expander("Data coverage / source audit", expanded=False):
            audit = pd.DataFrame([
                {
                    "Source layer": k,
                    "Available": "YES" if source_flags.get(k) else "NO",
                    "Quality weight": source_quality.get(k, "N/A"),
                }
                for k in source_flags
            ])
            st.dataframe(audit, use_container_width=True, hide_index=True)
            conf = inst.get("confidence_detail", {}) if isinstance(inst, dict) else {}
            if isinstance(conf, dict) and conf:
                st.dataframe(pd.DataFrame([{
                    "Coverage": f"{conf.get('coverage', 0):.0f}%",
                    "Source quality": f"{conf.get('source_quality', 0):.0f}%",
                    "Freshness": f"{conf.get('freshness', 0):.0f}%",
                    "Cross-validation": f"{conf.get('cross_validation', 0):.0f}%",
                    "Unified confidence": f"{conf.get('score', 0):.0f}/100",
                }]), use_container_width=True, hide_index=True)
            st.caption("Missing provider coverage remains unavailable. It is never converted into an artificial 50/100 neutral score.")


def render_ownership_positioning(company: dict):
    inst = company.get("institutional", {}) if isinstance(company, dict) else {}
    scores = inst.get("scores", {})
    history = inst.get("ownership_history", pd.DataFrame())
    own = inst.get("ownership_v2", {}) if isinstance(inst, dict) else {}
    own_sum = own.get("summary", {}) if isinstance(own, dict) else {}
    insider_v2 = inst.get("insider_v2", {}) if isinstance(inst, dict) else {}
    insider_sum = insider_v2.get("summary", {}) if isinstance(insider_v2, dict) else {}

    st.subheader("Ownership & Positioning Intelligence — V2")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Ownership Conviction", _score_text(scores.get("ownership_score")))
    c2.metric("Holder Breadth", _fmt_signed(own_sum.get("breadth")))
    c3.metric("Weighted Position Proxy", _fmt_signed(own_sum.get("weighted_position_change_proxy")))
    c4.metric("Active Position Proxy", _fmt_signed(own_sum.get("active_position_change_proxy")))
    c5.metric("Top-10 Concentration", _fmt_optional_pct(own_sum.get("top10")))
    c6.metric("Ownership HHI", fmt_num(own_sum.get("hhi")))

    st.caption(
        f"Score basis: {own.get('score_basis', 'Unavailable')}. Reported-holder pctChange is winsorized / nonlinearly compressed into a robust directional proxy; "
        "it is not presented as real-time institutional flow. Active Position Proxy excludes explicitly passive/index and mixed-manager aggregates unless a clearly discretionary holder classification is available."
    )

    if isinstance(history, pd.DataFrame) and not history.empty:
        plot_df = history.sort_values(["Year", "Quarter"]).copy()
        fig = go.Figure()
        if "Ownership %" in plot_df.columns and pd.to_numeric(plot_df["Ownership %"], errors="coerce").notna().any():
            fig.add_trace(go.Scatter(
                x=plot_df["Period"],
                y=pd.to_numeric(plot_df["Ownership %"], errors="coerce") * 100,
                mode="lines+markers",
                name="Institutional ownership %",
            ))
        if "Investors" in plot_df.columns and pd.to_numeric(plot_df["Investors"], errors="coerce").notna().any():
            fig.add_trace(go.Bar(
                x=plot_df["Period"],
                y=pd.to_numeric(plot_df["Investors"], errors="coerce"),
                name="Investor count",
                yaxis="y2",
                opacity=0.35,
            ))
        fig.update_layout(
            height=450,
            title="13F Ownership Trend",
            xaxis_title="Quarter",
            yaxis_title="Ownership %",
            yaxis2=dict(title="Investors", overlaying="y", side="right", showgrid=False),
            hovermode="x unified",
            margin=dict(l=20, r=20, t=65, b=35),
        )
        st.plotly_chart(fig, use_container_width=True)
        display = history.copy()
        if "Ownership %" in display.columns:
            display["Ownership %"] = display["Ownership %"].apply(_fmt_optional_pct)
        display = _format_large_df(display, ["Shares Held", "Shares Change", "Market Value"])
        st.dataframe(display, use_container_width=True, hide_index=True)
        st.caption("13F holdings are periodic filings and are not real-time positioning.")
    else:
        st.info("FMP 13F aggregate is unavailable for this symbol/plan. The V2 conviction score can still use the reported Yahoo holder-change proxy when available.")

    st.markdown("#### Top institutional holders — classified")
    holders = own.get("holders", pd.DataFrame()) if isinstance(own, dict) else pd.DataFrame()
    if isinstance(holders, pd.DataFrame) and not holders.empty:
        display = holders.copy().head(40)
        display = _format_percent_columns(display, ["Pct Held", "Pct Change"])
        display = _format_large_df(display, ["Shares", "Value"])
        st.dataframe(display, use_container_width=True, hide_index=True)
    else:
        st.caption("Institutional holder table unavailable.")

    st.markdown("#### Mutual fund / ETF holder layer — active vs passive")
    funds = own.get("funds", pd.DataFrame()) if isinstance(own, dict) else pd.DataFrame()
    if isinstance(funds, pd.DataFrame) and not funds.empty:
        display = funds.copy().head(40)
        display = _format_percent_columns(display, ["Pct Held", "Pct Change"])
        display = _format_large_df(display, ["Shares", "Value"])
        st.dataframe(display, use_container_width=True, hide_index=True)
        if own_sum.get("passive_fund_share") is not None:
            st.caption(f"Passive/index share within the displayed fund-holder weight: {_fmt_optional_pct(own_sum.get('passive_fund_share'))}.")
    else:
        st.caption("Mutual-fund holder table unavailable.")

    st.markdown("#### Insider Intelligence — informative trades only")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Insider Signal", _score_text(insider_v2.get("score")))
    c2.metric("Informative 90D", fmt_num(insider_sum.get("informative_count_90d")))
    c3.metric("Buyers 90D", fmt_num(insider_sum.get("buyers_90d")))
    c4.metric("Sellers 90D", fmt_num(insider_sum.get("sellers_90d")))
    c5.metric("Net Informative Ratio", _fmt_signed(insider_sum.get("net_informative_ratio")))

    if insider_v2.get("score") is None:
        st.info("No informative open-market insider activity was found. Grants, awards, gifts, withholding and option mechanics are shown for audit but do not receive a neutral 50/100 score.")

    tx = insider_v2.get("transactions", pd.DataFrame()) if isinstance(insider_v2, dict) else pd.DataFrame()
    if isinstance(tx, pd.DataFrame) and not tx.empty:
        display = tx.copy().head(120)
        if "Value" in display.columns:
            display["Value"] = display["Value"].apply(fmt_large_number)
        if "Shares" in display.columns:
            display["Shares"] = display["Shares"].apply(fmt_large_number)
        if "Price" in display.columns:
            display["Price"] = display["Price"].apply(lambda x: "N/A" if safe_float(x) is None else f"{safe_float(x):,.2f}")
        st.dataframe(display, use_container_width=True, hide_index=True)
    else:
        st.caption("No insider transaction feed available.")


def _render_segment_block(title: str, df: pd.DataFrame, summary: dict):
    st.markdown(f"#### {title}")
    if not isinstance(df, pd.DataFrame) or df.empty:
        st.caption("No segment data available from the configured provider.")
        return

    latest = summary.get("latest", pd.DataFrame()) if isinstance(summary, dict) else pd.DataFrame()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Largest segment", _fmt_optional_pct(summary.get("top_share")))
    if summary.get("taxonomy_changed"):
        c2.metric("Δ largest share", "N/M", help="Not meaningful because the segment taxonomy changed versus the previous disclosure.")
    else:
        c2.metric("Δ largest share", _fmt_pp(summary.get("top_share_delta")))
    c3.metric("Concentration HHI", fmt_num(summary.get("hhi")))
    c4.metric("Diversification Score", _score_text(summary.get("diversification_score")))

    if summary.get("taxonomy_changed"):
        added = ", ".join(summary.get("added_segments", [])) or "none"
        removed = ", ".join(summary.get("removed_segments", [])) or "none"
        st.warning(
            f"Segment taxonomy changed versus the previous disclosure. Added: {added}. Removed: {removed}. "
            "Growth comparisons across renamed/reclassified segments should not be interpreted mechanically."
        )

    if isinstance(latest, pd.DataFrame) and not latest.empty:
        fig = go.Figure(go.Bar(
            x=latest["Segment"],
            y=latest["Revenue"],
            text=latest["Share"].apply(_fmt_optional_pct),
            textposition="auto",
            name=title,
        ))
        fig.update_layout(
            height=420,
            title=f"Latest disclosed mix — {title}",
            xaxis_title="Segment",
            yaxis_title="Revenue",
            margin=dict(l=20, r=20, t=65, b=80),
        )
        st.plotly_chart(fig, use_container_width=True)

    display = df.copy().head(140)
    display = _format_percent_columns(display, ["Share", "Growth"])
    if "Revenue" in display.columns:
        display["Revenue"] = display["Revenue"].apply(fmt_large_number)
    st.dataframe(display, use_container_width=True, hide_index=True)


def render_business_ecosystem(company: dict):
    inst = company.get("institutional", {}) if isinstance(company, dict) else {}
    segments = inst.get("segments", {})
    relationships = inst.get("relationships", {})
    scores = inst.get("scores", {})
    rel_sum = relationships.get("summary", {}) if isinstance(relationships, dict) else {}

    st.subheader("Business, Customers & Supply-Chain Intelligence — V2.4.1")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Product Diversification", _score_text(scores.get("product_diversification_score")))
    c2.metric("Geo Diversification", _score_text(scores.get("geographic_diversification_score")))
    c3.metric("Customer Risk", _score_text(scores.get("customer_risk_score")))
    c4.metric("Supplier Risk", _score_text(scores.get("supplier_risk_score")))
    c5.metric("Single-Source Flags", fmt_num(rel_sum.get("single_source_count")))
    st.caption(
        f"Customer evidence confidence: {rel_sum.get('customer_confidence', 0):.0f}/100 · "
        f"Supplier evidence confidence: {rel_sum.get('supplier_confidence', 0):.0f}/100. "
        "Risk scores describe structural dependency, not directional price signals."
    )
    seg_meta = segments.get("metadata", {}) if isinstance(segments, dict) else {}
    if isinstance(seg_meta, dict) and (seg_meta.get("product_source") or seg_meta.get("geographic_source")):
        st.caption(
            "Segment resolution · Product: " + str(seg_meta.get("product_source") or "N/A") +
            " · Geography: " + str(seg_meta.get("geographic_source") or "N/A") +
            (f" · Snapshot observed: {seg_meta.get('snapshot_observed_at')}" if seg_meta.get("snapshot_observed_at") else "")
        )

    _render_segment_block(
        "Product / operating revenue segments",
        segments.get("product", pd.DataFrame()) if isinstance(segments, dict) else pd.DataFrame(),
        inst.get("product_summary", {}),
    )
    _render_segment_block(
        "Geographic revenue exposure",
        segments.get("geographic", pd.DataFrame()) if isinstance(segments, dict) else pd.DataFrame(),
        inst.get("geographic_summary", {}),
    )

    st.markdown("#### Material customer / supplier disclosures — SEC section-aware scan")
    disclosures = relationships.get("disclosures", pd.DataFrame()) if isinstance(relationships, dict) else pd.DataFrame()
    if isinstance(disclosures, pd.DataFrame) and not disclosures.empty:
        display = disclosures.copy()
        if "Disclosed %" in display.columns:
            display["Disclosed %"] = display["Disclosed %"].apply(_fmt_optional_pct)
        preferred = ["Section", "Risk Type", "Counterparty", "Disclosed %", "Confidence", "Disclosure", "Source", "Filing Date", "URL"]
        cols = [c for c in preferred if c in display.columns]
        st.dataframe(display[cols] if cols else display, use_container_width=True, hide_index=True)
        st.caption(
            "The V2.4.1 scanner prioritizes Item 1, Item 1A, Item 7 and Item 8, rejects common table-of-contents/investment-portfolio false positives, "
            "and deduplicates repeated XBRL text. It still does not claim to be a complete named customer-supplier graph."
        )
    else:
        st.info("No material customer/supplier dependency disclosure was extracted from the latest 10-K, or the filing could not be retrieved. Absence is not evidence of zero dependency.")


def _peer_metric_format(metric: str, value):
    v = safe_float(value)
    if v is None:
        return "N/A"
    if metric in {"Revenue Growth", "Gross Margin", "Operating Margin", "FCF Margin", "ROIC", "FCF Yield", "Premium / Discount"}:
        return fmt_pct(v)
    return f"{v:,.2f}"


def _format_peer_summary_display(summary: pd.DataFrame) -> pd.DataFrame:
    """Build a presentation-only peer bridge without mutating numeric dtypes in-place.

    Pandas 2.2+/3.x can raise TypeError when a formatted string (for example
    ``"85.20%"``) is assigned with ``.at`` into a float64 column.  The analytical
    ``summary`` must remain numeric for charts/percentiles, so this helper creates a
    display copy and explicitly promotes only presentation columns to ``object``.
    """
    if not isinstance(summary, pd.DataFrame) or summary.empty:
        return pd.DataFrame()

    sview = summary.copy(deep=True)

    presentation_cols = [
        "Target",
        "Peer Median",
        "Target Percentile",
        "Premium / Discount",
    ]
    for col in presentation_cols:
        if col in sview.columns:
            sview[col] = sview[col].astype(object)

    for idx, row in summary.iterrows():
        metric = str(row.get("Metric"))

        if "Target" in sview.columns:
            sview.at[idx, "Target"] = _peer_metric_format(metric, row.get("Target"))

        if "Peer Median" in sview.columns:
            sview.at[idx, "Peer Median"] = _peer_metric_format(metric, row.get("Peer Median"))

        if "Target Percentile" in sview.columns:
            pct = safe_float(row.get("Target Percentile"))
            sview.at[idx, "Target Percentile"] = "N/A" if pct is None else f"{pct:.0f}/100"

        if "Premium / Discount" in sview.columns:
            premium = safe_float(row.get("Premium / Discount"))
            sview.at[idx, "Premium / Discount"] = "N/A" if premium is None else fmt_pct(premium)

    if "Target Percentile" in sview.columns:
        sview = sview.rename(columns={"Target Percentile": "Relative Attractiveness Percentile"})
    return sview


def render_peers(company: dict):
    inst = company.get("institutional", {}) if isinstance(company, dict) else {}
    peer = inst.get("peer_intelligence", {}) if isinstance(inst, dict) else {}

    st.subheader("Peer Intelligence — Similarity-Ranked Relative Analysis")
    table = peer.get("table", pd.DataFrame()) if isinstance(peer, dict) else pd.DataFrame()
    summary = peer.get("summary", pd.DataFrame()) if isinstance(peer, dict) else pd.DataFrame()
    scores = peer.get("scores", {}) if isinstance(peer, dict) else {}

    if not isinstance(table, pd.DataFrame) or table.empty:
        raw = inst.get("peers", pd.DataFrame())
        if isinstance(raw, pd.DataFrame) and not raw.empty:
            st.warning("V2 peer enrichment was unavailable; showing the provider-curated universe only.")
            st.dataframe(raw.head(50), use_container_width=True, hide_index=True)
        else:
            st.info("Peer universe unavailable for the current symbol/plan.")
        return

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Relative Fundamental", _score_text(scores.get("relative_fundamental_score")))
    c2.metric("Quality / Growth Percentile", _score_text(scores.get("relative_quality_percentile")))
    c3.metric("Valuation Cheapness", _score_text(scores.get("valuation_cheapness_percentile")))
    c4.metric("Candidate Universe", fmt_num(peer.get("universe_size")))
    c5.metric("Data Confidence", _score_text(scores.get("data_confidence")))

    st.caption(
        "Peers are ranked by industry match, sector match, market-cap proximity and provider peer membership. "
        "V2.4.1 applies one metric contract across target and peers; ROIC uses the same canonical engine as Capital Allocation."
    )

    contract = peer.get("metric_contract", {}) if isinstance(peer, dict) else {}
    roic_audit = peer.get("roic_audit", {}) if isinstance(peer, dict) else {}
    if (isinstance(contract, dict) and contract) or (isinstance(roic_audit, dict) and roic_audit):
        with st.expander("Metric contract / comparison basis", expanded=False):
            if isinstance(contract, dict) and contract:
                st.dataframe(
                    pd.DataFrame([{"Metric": k, "Basis": v} for k, v in contract.items()]),
                    use_container_width=True, hide_index=True,
                )
                st.caption(
                    "Relative Attractiveness Percentile is direction-adjusted: higher is better for growth/quality/FCF yield, "
                    "while lower valuation multiples receive a higher attractiveness percentile."
                )
            if isinstance(roic_audit, dict) and safe_float(roic_audit.get("roic")) is not None:
                st.markdown("##### ROIC audit bridge — target")
                audit_rows = [
                    {"Component": "Basis", "Value": str(roic_audit.get("basis") or "TTM")},
                    {"Component": "NOPAT", "Value": fmt_large_number(roic_audit.get("nopat"))},
                    {"Component": "Average Invested Capital", "Value": fmt_large_number(roic_audit.get("average_invested_capital"))},
                    {"Component": "Normalized Tax Rate", "Value": _fmt_optional_pct(roic_audit.get("tax_rate"))},
                    {"Component": "ROIC", "Value": _fmt_optional_pct(roic_audit.get("roic"))},
                ]
                st.dataframe(pd.DataFrame(audit_rows), use_container_width=True, hide_index=True)

    display = table.copy()
    display = _format_large_df(display, ["Market Cap"])
    display = _format_percent_columns(display, ["Revenue Growth", "Gross Margin", "Operating Margin", "FCF Margin", "ROIC", "FCF Yield"])
    st.dataframe(display, use_container_width=True, hide_index=True)

    st.markdown("#### Relative metric bridge")
    if isinstance(summary, pd.DataFrame) and not summary.empty:
        sview = _format_peer_summary_display(summary)
        st.dataframe(sview.drop(columns=["Higher Is Better"], errors="ignore"), use_container_width=True, hide_index=True)

        chart = summary.dropna(subset=["Target Percentile"]).copy()
        if not chart.empty:
            fig = go.Figure(go.Bar(
                x=chart["Target Percentile"],
                y=chart["Metric"],
                orientation="h",
                text=chart["Target Percentile"].apply(lambda x: f"{x:.0f}"),
                textposition="auto",
            ))
            fig.add_vline(x=50, line_dash="dot", annotation_text="Peer median")
            fig.update_layout(height=460, title="Relative attractiveness percentile vs similarity-ranked peers", xaxis=dict(range=[0, 100], title="Relative Attractiveness Percentile"), margin=dict(l=20, r=20, t=65, b=40))
            st.plotly_chart(fig, use_container_width=True)


def render_capital_allocation(company: dict):
    inst = company.get("institutional", {}) if isinstance(company, dict) else {}
    cap = inst.get("capital_allocation", {}) if isinstance(inst, dict) else {}
    history = cap.get("history", pd.DataFrame()) if isinstance(cap, dict) else pd.DataFrame()
    summary = cap.get("summary", {}) if isinstance(cap, dict) else {}

    st.subheader("Capital Allocation Intelligence")
    if not isinstance(history, pd.DataFrame) or history.empty:
        st.info("Capital-allocation cash-flow history is unavailable for this symbol/plan.")
        return

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Allocation Quality", _score_text(cap.get("score")))
    c2.metric("Shareholder Yield", _fmt_optional_pct(summary.get("shareholder_yield")))
    c3.metric("Net Buyback", fmt_large_number(summary.get("net_buyback")))
    c4.metric("ROIC (TTM)", _fmt_optional_pct(summary.get("roic")))
    c5.metric("SBC / FCF", _fmt_optional_pct(summary.get("sbc_fcf")))
    c6.metric("Data Confidence", _score_text(cap.get("confidence")))

    st.caption(
        "Shareholder yield = net buybacks + dividends normalized by available market cap. SBC is shown separately because non-cash compensation is not identical to issued shares, but it is an important dilution-pressure diagnostic. "
        "Allocation Quality is composed only from observed sub-dimensions. ROIC (TTM) uses the same canonical NOPAT / average-invested-capital engine as Peer Intelligence; historical rows show FY ROIC separately. "
        f"Data source: {summary.get('source', 'reported cash-flow fallback')} · Evidence confidence {cap.get('confidence', 0):.0f}/100."
    )
    conf = cap.get("confidence_detail", {}) if isinstance(cap, dict) else {}
    if isinstance(conf, dict) and conf:
        st.caption(
            f"Coverage {conf.get('coverage', 0):.0f}% · Source quality {conf.get('source_quality', 0):.0f}% · "
            f"Freshness {conf.get('freshness', 0):.0f}% · Cross-validation {conf.get('cross_validation', 0):.0f}%."
        )

    component_labels = [
        ("Capital Return", "capital_return_score"),
        ("Capital Efficiency / ROIC", "capital_efficiency_score"),
        ("Dilution Control", "dilution_score"),
        ("Reinvestment Discipline", "reinvestment_score"),
        ("Balance-Sheet Allocation", "balance_sheet_allocation_score"),
    ]
    component_rows = [
        {"Dimension": label, "Score": summary.get(key)}
        for label, key in component_labels if summary.get(key) is not None
    ]
    if component_rows:
        st.markdown("#### Allocation score decomposition")
        component_df = pd.DataFrame(component_rows)
        component_df["Score"] = component_df["Score"].apply(lambda x: f"{float(x):.0f}/100" if x is not None else "N/A")
        st.dataframe(component_df, use_container_width=True, hide_index=True)

    plot_df = history.sort_values("Fiscal Year").copy()
    fig = go.Figure()
    for col in ["Buybacks", "Dividends", "Stock Issuance", "SBC"]:
        if col in plot_df.columns and pd.to_numeric(plot_df[col], errors="coerce").notna().any():
            fig.add_trace(go.Bar(x=plot_df["Fiscal Year"], y=pd.to_numeric(plot_df[col], errors="coerce"), name=col))
    fig.update_layout(
        barmode="group",
        height=460,
        title="Capital returned vs issuance / dilution pressure",
        xaxis_title="Fiscal Year",
        yaxis_title="Cash / reported amount",
        margin=dict(l=20, r=20, t=65, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)

    display = history.copy()
    display = _format_large_df(display, [
        "Operating Cash Flow", "Free Cash Flow", "Buybacks", "Stock Issuance", "Net Buyback",
        "Dividends", "SBC", "Capex", "Acquisitions", "Debt Issuance", "Debt Repayment",
        "Net Debt Issuance", "Market Cap",
    ])
    display = _format_percent_columns(display, ["FY ROIC", "Shareholder Yield", "Distributions / FCF", "SBC / FCF", "Reinvestment / FCF"])
    st.dataframe(display, use_container_width=True, hide_index=True)


def render_governance_filings(company: dict):
    inst = company.get("institutional", {}) if isinstance(company, dict) else {}
    governance = inst.get("governance", {})
    sec = inst.get("sec", {})
    sec_events = inst.get("sec_events", {}) if isinstance(inst, dict) else {}

    st.subheader("Management, Governance & Filings Intelligence")

    executives = governance.get("executives", pd.DataFrame()) if isinstance(governance, dict) else pd.DataFrame()
    compensation = governance.get("compensation", pd.DataFrame()) if isinstance(governance, dict) else pd.DataFrame()
    transcript_dates = governance.get("transcript_dates", pd.DataFrame()) if isinstance(governance, dict) else pd.DataFrame()
    share_float = governance.get("share_float", pd.DataFrame()) if isinstance(governance, dict) else pd.DataFrame()

    st.markdown("#### Key executives")
    if isinstance(executives, pd.DataFrame) and not executives.empty:
        preferred = ["name", "title", "pay", "currencyPay", "yearBorn", "titleSince", "active"]
        cols = [c for c in preferred if c in executives.columns]
        st.dataframe(executives[cols] if cols else executives, use_container_width=True, hide_index=True)
        if "source" in executives.columns and executives["source"].astype(str).str.contains("Yahoo", case=False, na=False).any():
            st.caption("FMP executive feed unavailable; leadership is populated from the existing Yahoo company-officers payload.")
    else:
        st.caption("Executive data unavailable.")

    if isinstance(compensation, pd.DataFrame) and not compensation.empty:
        with st.expander("Executive compensation / incentive alignment", expanded=False):
            st.dataframe(compensation.head(100), use_container_width=True, hide_index=True)

    if isinstance(share_float, pd.DataFrame) and not share_float.empty:
        with st.expander("Share float / liquidity", expanded=False):
            st.dataframe(share_float, use_container_width=True, hide_index=True)

    event_table = sec_events.get("table", pd.DataFrame()) if isinstance(sec_events, dict) else pd.DataFrame()
    if isinstance(event_table, pd.DataFrame) and not event_table.empty:
        st.markdown("#### SEC event materiality — V2.4.1")
        event_cols = [c for c in ["Event Date", "Form", "Items", "Category", "Event", "Materiality Label", "Materiality"] if c in event_table.columns]
        st.dataframe(event_table[event_cols].head(30), use_container_width=True, hide_index=True)
        st.caption("Routine Form 3/4 filings remain visible in the raw timeline but are not counted as material thesis events unless the filing class itself carries higher materiality.")

    st.markdown("#### SEC filing timeline")
    filings = sec.get("filings", pd.DataFrame()) if isinstance(sec, dict) else pd.DataFrame()
    if isinstance(filings, pd.DataFrame) and not filings.empty:
        important_forms = ["10-K", "10-Q", "8-K", "DEF 14A", "4", "SC 13D", "SC 13G", "13F-HR"]
        form_filter = st.multiselect(
            "Forms",
            important_forms,
            default=["10-K", "10-Q", "8-K", "DEF 14A", "4"],
            key="company_intelligence_sec_form_filter",
        )
        view = filings.copy()
        if form_filter and "form" in view.columns:
            view = view[view["form"].astype(str).isin(form_filter)]
        preferred = ["filingDate", "reportDate", "form", "accessionNumber", "primaryDocument", "primaryDocDescription", "items"]
        cols = [c for c in preferred if c in view.columns]
        st.dataframe(view[cols].head(120) if cols else view.head(120), use_container_width=True, hide_index=True)
    else:
        st.caption("SEC filing timeline unavailable (non-US issuer or retrieval failure).")

    st.markdown("#### Earnings-call transcript availability")
    if isinstance(transcript_dates, pd.DataFrame) and not transcript_dates.empty:
        st.dataframe(transcript_dates.head(80), use_container_width=True, hide_index=True)
        st.caption("Only transcript availability/dates are loaded here. Transcript NLP remains isolated so it cannot slow every ticker analysis.")
    else:
        st.caption("Transcript date feed unavailable.")


def render_what_changed(company: dict):
    inst = company.get("institutional", {}) if isinstance(company, dict) else {}
    wc = inst.get("what_changed", {}) if isinstance(inst, dict) else {}
    table = wc.get("table", pd.DataFrame()) if isinstance(wc, dict) else pd.DataFrame()
    summary = wc.get("summary", {}) if isinstance(wc, dict) else {}

    st.subheader("What Changed? — Thesis Delta Engine")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Directional Balance", str(summary.get("bias", "N/A")))
    c2.metric("Positive Changes", fmt_num(summary.get("positive")))
    c3.metric("Negative Changes", fmt_num(summary.get("negative")))
    c4.metric("Structural Risks", fmt_num(summary.get("structural_risks")))
    c5.metric("Material Events", fmt_num(summary.get("events")))
    c6.metric("Evidence Confidence", _score_text(summary.get("confidence")))

    st.caption(
        "V2.4.1 separates true directional thesis changes from structural states and SEC events classified by form/item materiality. "
        "Customer concentration, peer-relative valuation and filing activity no longer distort the Directional Balance simply because they exist."
    )

    if not isinstance(table, pd.DataFrame) or table.empty:
        st.info("No comparable change signals could be assembled from the currently available data layers.")
        return

    directional = table[table.get("Class", pd.Series(index=table.index, dtype=str)).eq("Directional Change")].copy()
    structural = table[table.get("Class", pd.Series(index=table.index, dtype=str)).eq("Structural State")].copy()
    events = table[table.get("Class", pd.Series(index=table.index, dtype=str)).eq("Material Event")].copy()

    st.markdown("#### Directional thesis changes")
    if directional.empty:
        st.caption("No directional change signal available.")
    else:
        st.dataframe(directional, use_container_width=True, hide_index=True)
        signed = {"Positive": 1, "Negative": -1, "Stable": 0, "Mixed": 0, "N/A": 0}
        chart = directional.copy()
        chart["Signed Materiality"] = chart["Direction"].map(signed).fillna(0) * pd.to_numeric(chart["Materiality"], errors="coerce").fillna(0)
        if chart["Signed Materiality"].abs().sum() > 0:
            fig = go.Figure(go.Bar(
                x=chart["Signed Materiality"], y=chart["Dimension"], orientation="h",
                text=chart["Direction"], textposition="auto",
            ))
            fig.add_vline(x=0, line_dash="dot")
            fig.update_layout(height=max(340, 46 * len(chart)), title="Directional thesis changes — signed materiality", margin=dict(l=20, r=20, t=65, b=40))
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Structural states / standing risks")
    if structural.empty:
        st.caption("No structural state assembled from current coverage.")
    else:
        st.dataframe(structural, use_container_width=True, hide_index=True)

    st.markdown("#### Material events")
    if events.empty:
        st.caption("No material event layer assembled from current coverage.")
    else:
        st.dataframe(events, use_container_width=True, hide_index=True)


def render_institutional_layer(ticker: str, company: dict, layer: str):
    layer = str(layer or "Institutional Overview")
    if layer == "Institutional Overview":
        render_institutional_overview(company)
    elif layer == "Ownership & Positioning":
        render_ownership_positioning(company)
    elif layer == "Business / Ecosystem":
        render_business_ecosystem(company)
    elif layer == "Peers":
        render_peers(company)
    elif layer == "Capital Allocation":
        render_capital_allocation(company)
    elif layer == "Governance / Filings":
        render_governance_filings(company)
    elif layer == "What Changed?":
        render_what_changed(company)
    else:
        render_institutional_overview(company)
