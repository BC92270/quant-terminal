"""Typed contracts for governed machine-discovered market patterns.

The pattern domain is intentionally research-only.  Its outputs may create a
testable hypothesis or a strategic evidence-acquisition action, but never an
order, a position, or an autonomous model promotion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math
from typing import Any

from ..contracts import as_utc
from ..evidence import canonical_hash


PATTERN_SCHEMA_VERSION = "mi-pattern-discovery-1.2.0"
PATTERN_ENGINE_VERSION = "mi-pattern-engine-1.2.0"
PATTERN_POLICY_VERSION = "mi-pattern-policy-1.2.0"

REQUIRED_COMPLETED_GATE_IDS = frozenset(
    {
        "INPUT_CONTRACT",
        "CAUSAL_FEATURES",
        "PURGED_LOCKED_HOLDOUT",
        "UNSUPERVISED_DISCOVERY",
        "AFTER_COST_OOS",
        "FDR_CORRECTION",
        "FULL_EXPERIMENT_CORRECTION",
        "SUPERVISED_CHALLENGER",
        "PIT_PROVIDER_LINEAGE",
        "SHADOW_HISTORY",
        "INDEPENDENT_REVIEW",
        "CURRENT_STATE_OOD",
        "AUTONOMOUS_EXECUTION",
    }
)

STRATEGIC_ADMISSION_GATE_IDS = frozenset(
    {
        "INPUT_CONTRACT",
        "CAUSAL_FEATURES",
        "PURGED_LOCKED_HOLDOUT",
        "UNSUPERVISED_DISCOVERY",
        "AFTER_COST_OOS",
        "FDR_CORRECTION",
        "FULL_EXPERIMENT_CORRECTION",
        "SUPERVISED_CHALLENGER",
        "PIT_PROVIDER_LINEAGE",
        "SHADOW_HISTORY",
        "INDEPENDENT_REVIEW",
        "CURRENT_STATE_OOD",
        "AUTONOMOUS_EXECUTION",
    }
)

ADMISSIBLE_REVISION_POLICIES = frozenset(
    {
        "IMMUTABLE",
        "APPEND_ONLY_VINTAGES",
        "AS_KNOWN_VINTAGES",
        "POINT_IN_TIME_REVISIONS",
    }
)

ADMISSIBLE_PRICE_ADJUSTMENT_POLICIES = frozenset(
    {
        "PROVIDER_ADJUSTED_CLOSE",
        "DECLARED_ADJUSTED_CLOSE_SERIES",
        "NATIVE_NON_CORPORATE_ACTION_SERIES",
    }
)


class PatternRunState(str, Enum):
    WAITING_DATA = "WAITING_DATA"
    BLOCKED_DATA_QUALITY = "BLOCKED_DATA_QUALITY"
    COMPLETED_RESEARCH_ONLY = "COMPLETED_RESEARCH_ONLY"
    ENGINE_ERROR = "ENGINE_ERROR"


class GateState(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WAITING_EVIDENCE = "WAITING_EVIDENCE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class PatternCandidateState(str, Enum):
    RUN_LOCAL_SCREENED_HYPOTHESIS = "RUN_LOCAL_SCREENED_HYPOTHESIS"
    OOS_SUPPORTED_HYPOTHESIS = "OOS_SUPPORTED_HYPOTHESIS"
    PROMISING_HYPOTHESIS = "PROMISING_HYPOTHESIS"
    REJECTED_OOS = "REJECTED_OOS"
    INSUFFICIENT_OOS = "INSUFFICIENT_OOS"


class PatternBridgeState(str, Enum):
    NOT_RUN = "NOT_RUN"
    STALE_DATASET = "STALE_DATASET"
    BLOCKED_SUBJECT = "BLOCKED_SUBJECT"
    CLOCK_MISMATCH = "CLOCK_MISMATCH"
    WAITING_LINEAGE = "WAITING_LINEAGE"
    WAITING_VALIDATION = "WAITING_VALIDATION"
    ELIGIBLE_FOR_GOVERNED_REBUILD = "ELIGIBLE_FOR_GOVERNED_REBUILD"


def _require_text(value: str, label: str) -> None:
    if not str(value).strip():
        raise ValueError(f"{label} cannot be empty")


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _finite_or_none(value: float | None, label: str) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite or null")
    return number


@dataclass(frozen=True, slots=True)
class PatternDiscoveryConfig:
    horizon_bars: int = 5
    execution_lag_bars: int = 1
    min_rows: int = 180
    min_train_rows: int = 100
    min_holdout_rows: int = 40
    holdout_fraction: float = 0.25
    min_clusters: int = 3
    max_clusters: int = 6
    min_oos_occurrences: int = 8
    transaction_cost_bps: float = 10.0
    fdr_alpha: float = 0.10
    random_state: int = 42
    selected_models: tuple[str, ...] = (
        "Prior",
        "Logistic",
        "HistGradientBoosting",
        "Extra Trees",
    )

    def __post_init__(self) -> None:
        for name in (
            "horizon_bars",
            "execution_lag_bars",
            "min_rows",
            "min_train_rows",
            "min_holdout_rows",
            "min_clusters",
            "max_clusters",
            "min_oos_occurrences",
        ):
            if int(getattr(self, name)) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.min_clusters < 2 or self.max_clusters < self.min_clusters:
            raise ValueError("cluster search bounds are inconsistent")
        if self.execution_lag_bars != 1:
            raise ValueError("the institutional pattern policy requires one next-bar execution lag")
        if not 0.10 <= float(self.holdout_fraction) <= 0.45:
            raise ValueError("holdout_fraction must be in [0.10, 0.45]")
        if not 0.0 < float(self.fdr_alpha) <= 0.25:
            raise ValueError("fdr_alpha must be in (0, 0.25]")
        if not 0.0 <= float(self.transaction_cost_bps) <= 250.0:
            raise ValueError("transaction_cost_bps must be in [0, 250]")
        if not self.selected_models:
            raise ValueError("selected_models cannot be empty")


@dataclass(frozen=True, slots=True)
class PatternInputAudit:
    symbol: str
    source_symbol: str
    subject_match: bool
    dataset_id: str
    source: str
    source_status: str
    recency: str
    source_known_at: datetime | None
    latest_row_known_at: datetime | None
    revision_policy: str
    price_adjustment_policy: str
    open_price_observed: bool
    high_low_observed: bool
    adjusted_close_observed: bool
    corporate_action_safe: bool
    raw_rows: int
    normalized_rows: int
    first_observation: datetime | None
    data_cutoff: datetime | None
    chronological: bool
    unique_timestamps: bool
    source_identified: bool
    point_in_time_declared: bool
    row_lineage_complete: bool
    pit_lineage_complete: bool
    fallback_used: bool
    quality_flags: tuple[str, ...]
    blocking_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", str(self.symbol).upper().strip())
        object.__setattr__(self, "source_symbol", str(self.source_symbol).upper().strip())
        _require_text(self.symbol, "symbol")
        _require_text(self.source_symbol, "source_symbol")
        for name in (
            "source",
            "source_status",
            "recency",
            "revision_policy",
            "price_adjustment_policy",
        ):
            _require_text(str(getattr(self, name)), name)
        if not _is_sha256(self.dataset_id):
            raise ValueError("dataset_id must be a lowercase SHA-256 digest")
        if self.first_observation is not None:
            object.__setattr__(self, "first_observation", as_utc(self.first_observation))
        if self.data_cutoff is not None:
            object.__setattr__(self, "data_cutoff", as_utc(self.data_cutoff))
        if self.source_known_at is not None:
            object.__setattr__(self, "source_known_at", as_utc(self.source_known_at))
        if self.latest_row_known_at is not None:
            object.__setattr__(self, "latest_row_known_at", as_utc(self.latest_row_known_at))
        if self.first_observation and self.data_cutoff and self.first_observation > self.data_cutoff:
            raise ValueError("first_observation cannot be after data_cutoff")
        if self.pit_lineage_complete and (
            not self.source_identified
            or not self.subject_match
            or not self.point_in_time_declared
            or not self.row_lineage_complete
            or self.source_known_at is None
            or self.latest_row_known_at is None
            or self.data_cutoff is None
            or self.source_known_at < self.data_cutoff
            or self.source_known_at < self.latest_row_known_at
            or self.revision_policy not in ADMISSIBLE_REVISION_POLICIES
        ):
            raise ValueError(
                "complete PIT lineage requires matched subject, identified source, row lineage, "
                "known-at >= cutoff and an admissible revision policy"
            )
        if self.subject_match != (self.source_symbol == self.symbol):
            raise ValueError("subject_match must equal source_symbol == symbol")
        for name in (
            "subject_match",
            "chronological",
            "unique_timestamps",
            "source_identified",
            "point_in_time_declared",
            "row_lineage_complete",
            "pit_lineage_complete",
            "fallback_used",
            "open_price_observed",
            "high_low_observed",
            "adjusted_close_observed",
            "corporate_action_safe",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a boolean")
        expected_corporate_action_safe = bool(
            self.normalized_rows > 0
            and self.price_adjustment_policy in ADMISSIBLE_PRICE_ADJUSTMENT_POLICIES
            and (
                self.adjusted_close_observed
                or self.price_adjustment_policy == "NATIVE_NON_CORPORATE_ACTION_SERIES"
            )
        )
        if self.corporate_action_safe != expected_corporate_action_safe:
            raise ValueError("corporate_action_safe must derive from observed adjustment provenance")
        if self.corporate_action_safe and (
            self.price_adjustment_policy not in ADMISSIBLE_PRICE_ADJUSTMENT_POLICIES
        ):
            raise ValueError("corporate-action-safe data requires an admissible adjustment policy")
        if self.raw_rows < 0 or self.normalized_rows < 0 or self.normalized_rows > self.raw_rows:
            raise ValueError("input row counts are inconsistent")


@dataclass(frozen=True, slots=True)
class PatternGate:
    gate_id: str
    state: GateState
    reason: str
    evidence: str
    blocks_strategic_admission: bool = True

    def __post_init__(self) -> None:
        for name in ("gate_id", "reason", "evidence"):
            _require_text(str(getattr(self, name)), name)
        if not isinstance(self.state, GateState):
            raise TypeError("state must be a GateState")


@dataclass(frozen=True, slots=True)
class PatternCandidate:
    pattern_id: str
    cluster_id: int
    signature: str
    direction: str
    train_occurrences: int
    oos_occurrences: int
    oos_nonoverlap_occurrences: int
    train_mean_forward_return: float | None
    oos_mean_forward_return: float | None
    oos_after_cost_mean: float | None
    oos_rest_after_cost_mean: float | None
    conditional_uplift: float | None
    oos_hit_rate: float | None
    oos_strategy_sharpe: float | None
    oos_strategy_sharpe_lower_95: float | None
    deflated_sharpe_probability: float | None
    raw_p_value: float | None
    fdr_q_value: float | None
    stability: str
    current_match_score: float | None
    state: PatternCandidateState
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        for name in ("pattern_id", "signature", "direction", "stability"):
            _require_text(str(getattr(self, name)), name)
        if (
            self.cluster_id < 0
            or self.train_occurrences < 0
            or self.oos_occurrences < 0
            or self.oos_nonoverlap_occurrences < 0
            or self.oos_nonoverlap_occurrences > self.oos_occurrences
        ):
            raise ValueError("candidate counts cannot be negative")
        for name in (
            "train_mean_forward_return",
            "oos_mean_forward_return",
            "oos_after_cost_mean",
            "oos_rest_after_cost_mean",
            "conditional_uplift",
            "oos_hit_rate",
            "oos_strategy_sharpe",
            "oos_strategy_sharpe_lower_95",
            "deflated_sharpe_probability",
            "raw_p_value",
            "fdr_q_value",
            "current_match_score",
        ):
            object.__setattr__(self, name, _finite_or_none(getattr(self, name), name))
        for name in (
            "oos_hit_rate",
            "deflated_sharpe_probability",
            "raw_p_value",
            "fdr_q_value",
            "current_match_score",
        ):
            value = getattr(self, name)
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if not isinstance(self.state, PatternCandidateState):
            raise TypeError("state must be a PatternCandidateState")
        if self.execution_allowed:
            raise ValueError("pattern candidates cannot authorize execution")


@dataclass(frozen=True, slots=True)
class ModelValidationScore:
    model: str
    oos_rows: int
    balanced_accuracy: float | None
    roc_auc: float | None
    brier: float | None
    expected_calibration_error: float | None

    def __post_init__(self) -> None:
        _require_text(self.model, "model")
        if self.oos_rows < 0:
            raise ValueError("oos_rows cannot be negative")
        for name in ("balanced_accuracy", "roc_auc", "brier", "expected_calibration_error"):
            object.__setattr__(self, name, _finite_or_none(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class PatternFitArtifact:
    """Exact learned numerical state needed to reproduce assignments."""

    feature_names: tuple[str, ...]
    imputer_statistics: tuple[float, ...]
    scaler_center: tuple[float, ...]
    scaler_scale: tuple[float, ...]
    cluster_centers: tuple[tuple[float, ...], ...]
    cluster_search: tuple[tuple[int, float], ...]
    ood_quantile: float
    cluster_ood_thresholds: tuple[float, ...]
    current_scaled_features: tuple[float, ...]
    current_distances: tuple[float, ...]
    current_nearest_distance: float
    kmeans_n_init: int = 20
    kmeans_max_iter: int = 500
    kmeans_algorithm: str = "lloyd"

    def __post_init__(self) -> None:
        width = len(self.feature_names)
        if width < 1 or any(not str(name).strip() for name in self.feature_names):
            raise ValueError("fit artifact requires named features")
        for values, label in (
            (self.imputer_statistics, "imputer_statistics"),
            (self.scaler_center, "scaler_center"),
            (self.scaler_scale, "scaler_scale"),
        ):
            if len(values) != width or any(not math.isfinite(float(value)) for value in values):
                raise ValueError(f"{label} must contain one finite value per feature")
        if len(self.cluster_centers) < 2 or any(
            len(center) != width or any(not math.isfinite(float(value)) for value in center)
            for center in self.cluster_centers
        ):
            raise ValueError("cluster_centers must be finite and feature-aligned")
        if not self.cluster_search or any(
            int(clusters) < 2 or not math.isfinite(float(score))
            for clusters, score in self.cluster_search
        ):
            raise ValueError("cluster_search must contain finite admissible partitions")
        if not 0.90 <= float(self.ood_quantile) < 1.0:
            raise ValueError("ood_quantile must be in [0.90, 1.0)")
        clusters = len(self.cluster_centers)
        if len(self.cluster_ood_thresholds) != clusters or any(
            not math.isfinite(float(value)) or float(value) < 0.0
            for value in self.cluster_ood_thresholds
        ):
            raise ValueError(
                "cluster_ood_thresholds must contain one finite non-negative value per cluster"
            )
        if len(self.current_scaled_features) != width or any(
            not math.isfinite(float(value)) for value in self.current_scaled_features
        ):
            raise ValueError("current_scaled_features must be finite and feature-aligned")
        if len(self.current_distances) != clusters or any(
            not math.isfinite(float(value)) or float(value) < 0.0
            for value in self.current_distances
        ):
            raise ValueError(
                "current_distances must contain one finite non-negative value per cluster"
            )
        if (
            not math.isfinite(float(self.current_nearest_distance))
            or float(self.current_nearest_distance) < 0.0
            or not math.isclose(
                float(self.current_nearest_distance),
                min(float(value) for value in self.current_distances),
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ):
            raise ValueError(
                "current_nearest_distance must equal the minimum recorded cluster distance"
            )
        if self.kmeans_n_init < 1 or self.kmeans_max_iter < 1:
            raise ValueError("K-means fit controls must be positive")
        _require_text(self.kmeans_algorithm, "kmeans_algorithm")


@dataclass(frozen=True, slots=True)
class PatternDiscoveryReport:
    report_id: str
    content_hash: str
    schema_version: str
    engine_version: str
    policy_version: str
    state: PatternRunState
    reason: str
    symbol: str
    evaluated_at: datetime
    input_audit: PatternInputAudit
    config: PatternDiscoveryConfig
    feature_names: tuple[str, ...]
    usable_rows: int
    train_rows: int
    purge_rows: int
    holdout_rows: int
    selected_clusters: int | None
    silhouette_score: float | None
    current_pattern_id: str | None
    nearest_pattern_id: str | None
    current_assignment_status: str
    candidates: tuple[PatternCandidate, ...]
    gates: tuple[PatternGate, ...]
    supervised_engine_version: str | None
    supervised_champion: str | None
    supervised_promotion_status: str
    model_scores: tuple[ModelValidationScore, ...]
    runtime_versions: tuple[tuple[str, str], ...]
    fit_artifact: PatternFitArtifact | None
    autonomous_trading: bool = False
    human_review_required: bool = True
    execution_allowed: bool = False
    order_payload: None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluated_at", as_utc(self.evaluated_at))
        object.__setattr__(self, "symbol", str(self.symbol).upper().strip())
        for name in (
            "report_id",
            "schema_version",
            "engine_version",
            "policy_version",
            "reason",
            "symbol",
            "supervised_promotion_status",
            "current_assignment_status",
        ):
            _require_text(str(getattr(self, name)), name)
        if not _is_sha256(self.content_hash):
            raise ValueError("content_hash must be a lowercase SHA-256 digest")
        if self.report_id != "MI-PAT-" + self.content_hash[:20].upper():
            raise ValueError("report_id must derive from content_hash")
        if not isinstance(self.state, PatternRunState):
            raise TypeError("state must be a PatternRunState")
        if self.symbol != self.input_audit.symbol:
            raise ValueError("report and input-audit symbols must match")
        for name in ("usable_rows", "train_rows", "purge_rows", "holdout_rows"):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} cannot be negative")
        object.__setattr__(self, "silhouette_score", _finite_or_none(self.silhouette_score, "silhouette_score"))
        if self.selected_clusters is not None and self.selected_clusters < 2:
            raise ValueError("selected_clusters must be at least two")
        if len({candidate.pattern_id for candidate in self.candidates}) != len(self.candidates):
            raise ValueError("candidate IDs must be unique")
        if len({gate.gate_id for gate in self.gates}) != len(self.gates):
            raise ValueError("gate IDs must be unique")
        candidate_ids = {candidate.pattern_id for candidate in self.candidates}
        if self.current_pattern_id is not None and self.current_pattern_id not in {
            candidate.pattern_id for candidate in self.candidates
        }:
            raise ValueError("current_pattern_id must reference a report candidate")
        if self.nearest_pattern_id is not None and self.nearest_pattern_id not in candidate_ids:
            raise ValueError("nearest_pattern_id must reference a report candidate")
        if self.current_assignment_status not in {
            "ASSIGNED_IN_DISTRIBUTION",
            "UNASSIGNED_OOD",
            "NOT_AVAILABLE",
        }:
            raise ValueError("unsupported current_assignment_status")
        if self.current_assignment_status == "ASSIGNED_IN_DISTRIBUTION" and self.current_pattern_id is None:
            raise ValueError("in-distribution assignment requires current_pattern_id")
        if self.current_assignment_status == "UNASSIGNED_OOD" and self.current_pattern_id is not None:
            raise ValueError("OOD state cannot carry a current_pattern_id")
        if len({name for name, _ in self.runtime_versions}) != len(self.runtime_versions):
            raise ValueError("runtime version names must be unique")
        for name, version in self.runtime_versions:
            _require_text(name, "runtime version name")
            _require_text(version, f"runtime version for {name}")
        if self.state == PatternRunState.COMPLETED_RESEARCH_ONLY:
            gate_ids = {gate.gate_id for gate in self.gates}
            missing = REQUIRED_COMPLETED_GATE_IDS - gate_ids
            if missing:
                raise ValueError("completed pattern report is missing mandatory gates: " + ", ".join(sorted(missing)))
            gates_by_id = {gate.gate_id: gate for gate in self.gates}
            foundational_gate_ids = {
                "INPUT_CONTRACT",
                "CAUSAL_FEATURES",
                "PURGED_LOCKED_HOLDOUT",
                "UNSUPERVISED_DISCOVERY",
                "AUTONOMOUS_EXECUTION",
            }
            if any(gates_by_id[gate_id].state != GateState.PASS for gate_id in foundational_gate_ids):
                raise ValueError("completed pattern report requires every foundational gate to pass")
            if self.selected_clusters is None or len(self.candidates) != self.selected_clusters:
                raise ValueError("completed pattern report must bind every selected cluster")
            if self.usable_rows != self.train_rows + self.purge_rows + self.holdout_rows:
                raise ValueError("completed pattern split rows must sum to usable_rows")
            if self.nearest_pattern_id is None:
                raise ValueError("completed pattern report requires a nearest trained state")
            if self.fit_artifact is None:
                raise ValueError("completed pattern report requires an exact learned fit artifact")
            if self.fit_artifact.feature_names != self.feature_names:
                raise ValueError("fit artifact feature manifest must match the report")
            if len(self.fit_artifact.cluster_centers) != self.selected_clusters:
                raise ValueError("fit artifact cluster centers must match selected_clusters")
            runtime_names = {name for name, _ in self.runtime_versions}
            required_runtime_names = {"python", "numpy", "pandas", "scipy", "scikit-learn"}
            if not required_runtime_names.issubset(runtime_names):
                raise ValueError("completed pattern report requires the full numerical runtime manifest")
            if not self.input_audit.subject_match:
                raise ValueError("completed pattern report requires matched dataset subject")
            execution_gate = gates_by_id["AUTONOMOUS_EXECUTION"]
            if execution_gate.state != GateState.PASS:
                raise ValueError("completed pattern report must retain the execution prohibition gate")
        availability_clocks = tuple(
            value
            for value in (
                self.input_audit.data_cutoff,
                self.input_audit.source_known_at,
                self.input_audit.latest_row_known_at,
            )
            if value is not None
        )
        if (
            self.state == PatternRunState.COMPLETED_RESEARCH_ONLY
            and availability_clocks
            and self.evaluated_at < max(availability_clocks)
        ):
            raise ValueError("evaluated_at cannot precede source/data availability")
        if self.autonomous_trading or self.execution_allowed or self.order_payload is not None:
            raise ValueError("pattern discovery cannot carry autonomous trading or orders")
        if not self.human_review_required:
            raise ValueError("pattern research always requires human review")

    def hash_material(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "engine_version": self.engine_version,
            "policy_version": self.policy_version,
            "state": self.state,
            "reason": self.reason,
            "symbol": self.symbol,
            "evaluated_at": self.evaluated_at,
            "input_audit": self.input_audit,
            "config": self.config,
            "feature_names": self.feature_names,
            "usable_rows": self.usable_rows,
            "train_rows": self.train_rows,
            "purge_rows": self.purge_rows,
            "holdout_rows": self.holdout_rows,
            "selected_clusters": self.selected_clusters,
            "silhouette_score": self.silhouette_score,
            "current_pattern_id": self.current_pattern_id,
            "nearest_pattern_id": self.nearest_pattern_id,
            "current_assignment_status": self.current_assignment_status,
            "candidates": self.candidates,
            "gates": self.gates,
            "supervised_engine_version": self.supervised_engine_version,
            "supervised_champion": self.supervised_champion,
            "supervised_promotion_status": self.supervised_promotion_status,
            "model_scores": self.model_scores,
            "runtime_versions": self.runtime_versions,
            "fit_artifact": self.fit_artifact,
            "autonomous_trading": self.autonomous_trading,
            "human_review_required": self.human_review_required,
            "execution_allowed": self.execution_allowed,
            "order_payload": self.order_payload,
        }

    def verify_hash(self) -> bool:
        return canonical_hash(self.hash_material()) == self.content_hash


@dataclass(frozen=True, slots=True)
class PatternStrategyBridge:
    bridge_id: str
    state: PatternBridgeState
    report_id: str | None
    memo_id: str | None
    status_label: str
    strategic_action: str
    reason: str
    admissible_for_governed_rebuild: bool
    admitted_to_current_memo: bool = False
    capital_authority: bool = False
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        for name in ("bridge_id", "status_label", "strategic_action", "reason"):
            _require_text(str(getattr(self, name)), name)
        if not isinstance(self.state, PatternBridgeState):
            raise TypeError("state must be a PatternBridgeState")
        if self.admitted_to_current_memo or self.capital_authority or self.execution_allowed:
            raise ValueError("pattern bridge cannot mutate a current memo or authorize capital/execution")
