"""Standard institutional claim/evidence/limit/next-control footer."""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from ..contracts import WorkspaceSnapshot
from .common import esc, section_header


@dataclass(frozen=True, slots=True)
class ViewControlNote:
    claim_type: str
    claim: str
    evidence: str
    limitation: str
    next_control: str


_NOTES: dict[str, ViewControlNote] = {
    "events": ViewControlNote("OBSERVED / FIXTURE", "Timestamped records can be audited from publication through feature readiness.", "Structured event rows and their point-in-time chain.", "No licensed source feed, republication corpus or extraction validation sample.", "Connect an authorized document corpus and replay revisions."),
    "catalyst-map": ViewControlNote("ECONOMIC LINK / HYPOTHESIS", "The fixture supports an auditable propagation path across rates, index and issuer nodes.", "Versioned relationship edges with validity and evidence type.", "Association and economic linkage do not establish causality.", "Validate edges and lead-lag stability on PIT relationship history."),
    "narratives": ViewControlNote("DERIVED / FIXTURE", "Three concurrent narratives describe the scenario context.", "Deterministic intensity, novelty and source-diversity fixture fields.", "No historical documents, lifecycle fit or source-level deduplication.", "Replay a licensed corpus and measure lifecycle stability."),
    "collision": ViewControlNote("DERIVED / FIXTURE", "Opposing catalyst mass is high while the net directional balance is weak.", "Signed contribution ledger and deterministic collision equation.", "Contributions are fixture attributions, not validated causal effects.", "Run grouped ablation with an explicit interaction residual."),
    "analogues": ViewControlNote("MODEL ASSOCIATION / SYNTHETIC", "Multivariate state similarity can organize historical comparison.", "Synthetic state vectors with decomposed similarity dimensions.", "No real episodes, sample confidence or outcome-safe neighbour index.", "Build a leakage-audited PIT analogue store."),
    "microstructure": ViewControlNote("OBSERVED / SIMULATED L2", "The sequenced fixture is consistent with bid-side replenishment during negative flow.", "OFI, queue imbalance, microprice and replenishment primitives.", "No venue entitlement, packet-gap audit or synchronized exchange clock.", "Certify sequence integrity before enabling L2 interpretation."),
    "information-gap": ViewControlNote("DERIVED / CONSERVATIVE", "Known fixture catalysts explain most measured state; no residual-flow alert is raised.", "Known-intensity, microstructure and related-asset fixture components.", "Options are unavailable and thresholds are not calibrated.", "Stress missing modalities and calibrate the residual alarm rate."),
    "cross-asset": ViewControlNote("MODEL ASSOCIATION / FIXTURE", "Rates and Nasdaq form a plausible propagation channel in this scenario.", "Typed point-in-time edges and simple relation weights.", "Lead-lag association is not an economic causal estimate.", "Test graph-free and linear propagation baselines OOS."),
    "forecast": ViewControlNote("LEVEL-0 BENCHMARK", "The empirical distribution is a control benchmark across horizons.", "Trailing fixture returns with monotone quantiles and explicit cutoff.", "Unconditional, uncalibrated and not catalyst-conditioned.", "Accumulate PIT outcomes before estimating calibration."),
    "patterns": ViewControlNote("RESEARCH HYPOTHESIS", "Registered patterns are hypotheses only.", "Stable pattern IDs and explicit discovery status.", "No chronological OOS, multiple-testing or cost evidence.", "Register the search universe and lock an untouched test."),
    "models": ViewControlNote("MODEL INVENTORY", "No production champion exists; the empirical distribution is a research baseline.", "Versioned registry rows and provider-state matrix.", "No validation, shadow outcomes, drift series or rollback artifact.", "Create an immutable evidence passport before human review."),
    "research": ViewControlNote("GOVERNANCE CONTROL", "The deterministic foundation passes its bounded fixture checks.", "Reproducible audit gates and explicit blocker matrix.", "Fixture integrity is not scientific or production validation.", "Supply licensed PIT history, OOS evidence and independent review."),
}


def render_view_control_note(snapshot: WorkspaceSnapshot, view: str) -> None:
    note = _NOTES.get(
        view,
        ViewControlNote(
            "DESCRIPTIVE / FIXTURE",
            f"{snapshot.interaction.state.replace('_', ' ').title()} is the current deterministic scenario state.",
            "Structured catalysts, sequenced L2 fixture and explicit timestamp contracts.",
            "No live provider, calibration, shadow history or execution path.",
            "Review the selected event, missing layers and promotion blockers.",
        ),
    )
    section_header("CONTROL NOTE", "Claim boundary and next evidence", f"{note.claim_type} · {snapshot.as_of:%Y-%m-%d %H:%M UTC}")
    st.markdown(
        f'''<div class="mi-brief-grid mi-brief-grid-four">
          <div class="mi-brief-card"><div>Claim</div><p>{esc(note.claim)}</p></div>
          <div class="mi-brief-card"><div>Evidence</div><p>{esc(note.evidence)}</p></div>
          <div class="mi-brief-card"><div>Limit</div><p>{esc(note.limitation)}</p></div>
          <div class="mi-brief-card"><div>Next control</div><p>{esc(note.next_control)}</p></div>
        </div>''',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Snapshot {snapshot.audit.get('fixture_id', 'UNVERSIONED')} · "
        "RESEARCH_ONLY · WAITING_EVIDENCE · no execution or automatic promotion path"
    )
