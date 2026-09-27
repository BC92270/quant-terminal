"""Workspace orchestration with panel-level failure isolation."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import logging
from typing import Any

import streamlit as st

from .demo import build_workspace_snapshot
from .patterns.bridge import build_pattern_strategy_bridge
from .patterns.contracts import (
    PatternDiscoveryConfig,
    PatternDiscoveryReport,
    PatternStrategyBridge,
)
from .patterns.features import normalize_price_history
from .state import initialize_state
from .strategy import DecisionPurpose, build_strategic_decision_memo
from .ui.common import render_data_contract
from .ui.control_note import render_view_control_note
from .ui.institutional_control import governance_assessment, render_governance_bar
from .ui.shell import render_context_controls, render_navigation, render_shell_header
from .ui.strategic_decision import render_strategy_ribbon, render_strategy_unavailable
from .ui.theme import inject_market_intelligence_theme


LOGGER = logging.getLogger(__name__)


def _current_pattern_config() -> PatternDiscoveryConfig | None:
    """Recreate the visible pattern protocol without loading the ML engine."""

    try:
        return PatternDiscoveryConfig(
            horizon_bars=int(st.session_state.get("mi_pattern_horizon_bars", 5)),
            transaction_cost_bps=float(st.session_state.get("mi_pattern_cost_bps", 10.0)),
            max_clusters=int(st.session_state.get("mi_pattern_max_clusters", 6)),
            fdr_alpha=float(st.session_state.get("mi_pattern_fdr_alpha", 0.10)),
        )
    except (TypeError, ValueError):
        return None


def _current_pattern_report(
    snapshot: Any,
    *,
    current_dataset_id: str | None,
) -> PatternDiscoveryReport | None:
    """Return only an immutable report bound to the visible dataset and protocol."""

    session_report = st.session_state.get("mi_pattern_discovery_report")
    report = session_report if isinstance(session_report, PatternDiscoveryReport) else None
    current_config = _current_pattern_config()
    try:
        integrity_ok = report.verify_hash() if report is not None else False
    except Exception:
        integrity_ok = False
    if (
        report is None
        or current_config is None
        or not integrity_ok
        or report.symbol != snapshot.symbol.upper()
        or report.input_audit.dataset_id != current_dataset_id
        or report.config != current_config
    ):
        return None
    return report


def _incident_id(scope: str, exc: Exception, symbol: str, as_of: str = "unavailable") -> str:
    seed = f"{scope}|{type(exc).__name__}|{symbol}|{as_of}"
    return "MI-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:10].upper()


def _record_incident(incident_id: str) -> None:
    incidents = list(st.session_state.get("mi_incident_ids") or [])
    if incident_id not in incidents:
        incidents.append(incident_id)
    st.session_state["mi_incident_ids"] = incidents[-20:]


def _render_incident(incident_id: str, *, scope: str) -> None:
    st.error(f"{scope} isolated safely · incident {incident_id}")
    st.info(
        "The diagnostic was retained in application logs without exposing provider or runtime details. "
        "Execution remains disabled and the rest of Quant Terminal remains available."
    )


def _renderers() -> dict[str, Callable[[Any], None]]:
    from .ui.catalyst_collision import render_catalyst_collision
    from .ui.catalyst_map import render_catalyst_map
    from .ui.cross_asset import render_cross_asset
    from .ui.discovered_patterns import render_discovered_patterns
    from .ui.event_explorer import render_event_explorer
    from .ui.forecast_surface import render_forecast_surface
    from .ui.historical_analogues import render_historical_analogues
    from .ui.information_gap import render_information_gap
    from .ui.live_intelligence import render_live_intelligence
    from .ui.microstructure_intelligence import render_microstructure_intelligence
    from .ui.model_observatory import render_model_observatory
    from .ui.narrative_monitor import render_narrative_monitor
    from .ui.research_validation import render_research_validation

    return {
        "live": render_live_intelligence,
        "events": render_event_explorer,
        "catalyst-map": render_catalyst_map,
        "narratives": render_narrative_monitor,
        "collision": render_catalyst_collision,
        "analogues": render_historical_analogues,
        "microstructure": render_microstructure_intelligence,
        "information-gap": render_information_gap,
        "cross-asset": render_cross_asset,
        "forecast": render_forecast_surface,
        "patterns": render_discovered_patterns,
        "models": render_model_observatory,
        "research": render_research_validation,
    }


def render_market_intelligence_lab(
    ticker: str = "SPY",
    price_data: Any = None,
    analysis: Any = None,
) -> None:
    initialize_state(st.session_state, ticker=ticker)
    inject_market_intelligence_theme()
    selected_symbol = st.session_state.get("mi_selected_symbol") or ticker or "NVDA"
    try:
        snapshot = build_workspace_snapshot(selected_symbol, price_data=price_data, analysis=analysis)
    except Exception as exc:
        incident_id = _incident_id("snapshot", exc, str(selected_symbol))
        _record_incident(incident_id)
        LOGGER.exception("Market Intelligence snapshot incident %s", incident_id)
        _render_incident(incident_id, scope="Input context")
        st.warning(
            "The requested context could not be admitted. A separate canonical NVDA fixture is shown for "
            "research inspection only; no input was relabelled or fused."
        )
        try:
            snapshot = build_workspace_snapshot("NVDA")
        except Exception as fallback_exc:
            fallback_id = _incident_id("canonical-fallback", fallback_exc, "NVDA")
            _record_incident(fallback_id)
            LOGGER.exception("Market Intelligence canonical fallback incident %s", fallback_id)
            _render_incident(fallback_id, scope="Canonical fallback")
            return
    render_shell_header(snapshot)
    render_context_controls(snapshot)
    assessment = None
    strategic_memo = None
    pattern_bridge: PatternStrategyBridge | None = None
    current_pattern_dataset_id: str | None = None
    try:
        assessment = governance_assessment(snapshot)
        render_governance_bar(assessment)
    except Exception as exc:
        governance_id = _incident_id("governance", exc, snapshot.symbol, snapshot.as_of.isoformat())
        _record_incident(governance_id)
        st.session_state.pop("mi_governance_assessment", None)
        st.session_state.pop("mi_governance_snapshot", None)
        LOGGER.exception("Market Intelligence governance incident %s", governance_id)
        _render_incident(governance_id, scope="Governance control plane")
        st.warning("Decision state unavailable · fail-closed posture enforced · human review ineligible.")
    if assessment is not None:
        try:
            purpose_value = str(st.session_state.get("mi_strategy_purpose", "RESEARCH_PRIORITIZATION"))
            try:
                purpose = DecisionPurpose(purpose_value)
            except ValueError:
                purpose = DecisionPurpose.RESEARCH_PRIORITIZATION
                st.session_state["mi_strategy_purpose"] = purpose.value
            strategic_memo = build_strategic_decision_memo(
                snapshot,
                assessment,
                horizon=str(st.session_state.get("mi_horizon", snapshot.forecasts[0].horizon)),
                purpose=purpose,
            )
        except Exception as exc:
            strategy_id = _incident_id("strategy", exc, snapshot.symbol, snapshot.as_of.isoformat())
            _record_incident(strategy_id)
            LOGGER.exception("Market Intelligence strategy incident %s", strategy_id)
            _render_incident(strategy_id, scope="Strategic decision layer")
            render_strategy_unavailable()
        else:
            # Pattern evidence is a separable addendum.  A data/parser/ML
            # incident must never take the core strategic memo off the desk.
            try:
                _, pattern_audit = normalize_price_history(price_data, snapshot.symbol)
                current_pattern_dataset_id = (
                    pattern_audit.dataset_id if pattern_audit.normalized_rows else None
                )
                report = _current_pattern_report(
                    snapshot,
                    current_dataset_id=current_pattern_dataset_id,
                )
                pattern_bridge = build_pattern_strategy_bridge(
                    snapshot,
                    report,
                    current_dataset_id=current_pattern_dataset_id,
                    memo_id=strategic_memo.memo_id,
                )
            except Exception as exc:
                pattern_id = _incident_id(
                    "pattern-addendum", exc, snapshot.symbol, snapshot.as_of.isoformat()
                )
                _record_incident(pattern_id)
                LOGGER.exception("Market Intelligence pattern addendum incident %s", pattern_id)
                pattern_bridge = None
            render_strategy_ribbon(strategic_memo, assessment, pattern_bridge=pattern_bridge)
    else:
        render_strategy_unavailable()
    active_view = render_navigation(assessment=assessment, strategic_memo=strategic_memo)
    renderer = _renderers().get(active_view, _renderers()["live"])
    try:
        if active_view == "live":
            renderer(
                snapshot,
                assessment=assessment,
                strategic_memo=strategic_memo,
                pattern_bridge=pattern_bridge,
            )
        elif active_view == "patterns":
            renderer(
                snapshot,
                price_data=price_data,
                strategic_memo=strategic_memo,
                pattern_bridge=pattern_bridge,
            )
        elif active_view in {"models", "research"}:
            renderer(snapshot, assessment=assessment)
        else:
            renderer(snapshot)
        footer_report = _current_pattern_report(
            snapshot,
            current_dataset_id=current_pattern_dataset_id,
        )
        render_view_control_note(snapshot, active_view, pattern_report=footer_report)
    except Exception as exc:
        active_view = str(st.session_state.get("mi_active_view", "unknown"))
        incident_id = _incident_id(active_view, exc, snapshot.symbol, snapshot.as_of.isoformat())
        _record_incident(incident_id)
        LOGGER.exception("Market Intelligence panel incident %s in %s", incident_id, active_view)
        _render_incident(incident_id, scope="Panel")
    render_data_contract(snapshot)
