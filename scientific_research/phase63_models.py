from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RegistryFileHealth:
    registry: str
    path: str
    status: str
    row_count: int = 0
    detail: str = ""


@dataclass(frozen=True)
class DataFieldSpec:
    name: str
    role: str
    dtype: str
    unit: str = ""
    required: bool = True
    strictly_positive: bool = False


@dataclass(frozen=True)
class CausalTransformStep:
    step_id: str
    operation: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HistoricalDataContract:
    contract_id: str
    created_at: str
    question_id: str
    plan_id: str
    experiment_id: str
    measurement_model_id: str
    measurement_decision_id: str
    observable_id: str
    target_concept: str
    market: str
    universe: str
    asset_identifier: str
    provider: str
    raw_data_uri: str
    license_or_terms: str
    price_field: str
    fundamental_field: str
    event_time_field: str
    availability_time_field: str
    vintage_time_field: str
    anchor_family: str
    frequency: str
    timezone: str
    publication_lag_days: int
    revision_policy: str
    missing_data_policy: str
    duplicate_policy: str
    split_policy: str
    train_fraction: float
    forecast_horizon: int
    embargo_periods: int
    max_rows: int
    formula: str
    field_specs: tuple[DataFieldSpec, ...]
    transform_steps: tuple[CausalTransformStep, ...]
    source_refs: tuple[str, ...]
    rationale: str
    status: str
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    schema_version: str = "SRB_HISTORICAL_DATA_CONTRACT_V1"
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class DataContractAudit:
    audit_id: str
    created_at: str
    contract_id: str
    schema_status: str
    chronology_status: str
    point_in_time_status: str
    measurement_alignment_status: str
    transformation_status: str
    overall_status: str
    checks: tuple[dict[str, Any], ...]
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class DatasetManifest:
    manifest_id: str
    created_at: str
    contract_id: str
    observable_id: str
    dataset_label: str
    raw_fingerprint: str
    materialized_fingerprint: str
    contract_fingerprint: str
    row_count: int
    valid_row_count: int
    excluded_row_count: int
    start_timestamp: str
    end_timestamp: str
    split_timestamp: str
    train_size: int
    test_size: int
    point_in_time_status: str
    revision_risk_status: str
    checks: tuple[dict[str, Any], ...]
    status: str
    source_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class MaterializedDataset:
    manifest: DatasetManifest
    timestamps: tuple[str, ...]
    values: tuple[float, ...]
    prices: tuple[float, ...]
    fundamental_anchors: tuple[float, ...]
    availability_timestamps: tuple[str, ...]
    vintage_timestamps: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExperimentAttemptRecord:
    attempt_id: str
    created_at: str
    experiment_id: str
    run_signature: str
    evidence_unit_id: str
    contract_id: str
    manifest_id: str
    observable_id: str
    purpose: str
    status: str
    actor: str = "HUMAN"
    started_at: str = ""
    completed_at: str = ""
    run_id: str = ""
    error_type: str = ""
    error_message: str = ""
    lifecycle_history: tuple[dict[str, Any], ...] = ()
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class BreakDiagnostic:
    diagnostic_id: str
    created_at: str
    run_id: str
    experiment_id: str
    observable_id: str
    baseline_name: str
    method: str
    calibration_size: int
    threshold: float
    status: str
    signal_timestamps: tuple[str, ...]
    cumulative_path: tuple[float, ...]
    max_abs_statistic: float
    warnings: tuple[str, ...] = ()
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class SelectionPressureSnapshot:
    snapshot_id: str
    created_at: str
    question_id: str
    experiment_id: str
    total_attempts: int
    completed_runs: int
    unique_run_signatures: int
    unique_evidence_units: int
    unique_data_fingerprints: int
    unique_observables: int
    baseline_comparisons: int
    robustness_variants: int
    observed_screens: int
    selection_risk: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReproducibilityCapsule:
    capsule_id: str
    created_at: str
    experiment_id: str
    run_id: str
    attempt_id: str
    contract_id: str
    contract_fingerprint: str
    manifest_id: str
    data_fingerprint: str
    forecast_trace_fingerprint: str
    observable_id: str
    measurement_model_id: str
    measurement_decision_id: str
    run_signature: str
    evidence_unit_id: str
    executor: str
    executor_version: str
    code_digest: str
    seed: int
    train_size: int
    test_size: int
    split_timestamp: str
    environment: dict[str, str]
    source_refs: tuple[str, ...]
    replay_grade: str
    status: str
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class MeasurementVariantSpec:
    variant_id: str
    label: str
    formula: str
    economic_interpretation: str
    source_fields: tuple[str, ...]
    transform: str
    counts_as_distinct_measurement: bool = True
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MeasurementRobustnessProtocol:
    protocol_id: str
    created_at: str
    question_id: str
    experiment_id: str
    contract_id: str
    contract_audit_id: str
    measurement_model_id: str
    measurement_decision_id: str
    primary_observable_id: str
    snapshot_id: str
    snapshot_fingerprint: str
    snapshot_rows_fingerprint: str
    dataset_file_sha256: str
    dataset_id: str
    executor_code_digest: str
    point_in_time_status: str
    revision_risk_status: str
    train_fraction: float
    forecast_horizon: int
    split_policy: str
    common_support_policy: str
    variants: tuple[MeasurementVariantSpec, ...]
    status: str = "FROZEN"
    warnings: tuple[str, ...] = ()
    schema_version: str = "SRB_MEASUREMENT_ROBUSTNESS_PROTOCOL_V1"
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class MeasurementVariantResult:
    variant_result_id: str
    variant_id: str
    label: str
    formula: str
    verdict: str
    data_fingerprint: str
    forecast_trace_fingerprint: str
    row_count: int
    train_size: int
    test_size: int
    split_timestamp: str
    candidate_metrics: dict[str, float]
    baseline_metrics: dict[str, dict[str, float]]
    deltas_vs_baseline: dict[str, dict[str, float]]
    fitted_parameters: dict[str, float]
    chronological_split_robustness: dict[str, Any]
    forecast_origin_timestamps: tuple[str, ...]
    forecast_timestamps: tuple[str, ...]
    actual_values: tuple[float, ...]
    candidate_predictions: tuple[float, ...]
    candidate_errors: tuple[float, ...]
    baseline_predictions: dict[str, tuple[float, ...]]
    baseline_errors: dict[str, tuple[float, ...]]
    status: str = "COMPLETED"
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class MeasurementRobustnessReport:
    report_id: str
    created_at: str
    protocol_id: str
    question_id: str
    experiment_id: str
    contract_id: str
    snapshot_id: str
    snapshot_fingerprint: str
    executor_code_digest: str
    execution_fingerprint: str
    common_timestamps_fingerprint: str
    common_support_status: str
    common_split_status: str
    point_in_time_status: str
    variant_count: int
    promising_variant_count: int
    no_improvement_variant_count: int
    conclusion: str
    gate_status: str
    variant_results: tuple[MeasurementVariantResult, ...]
    status: str = "COMPLETE"
    warnings: tuple[str, ...] = ()
    schema_version: str = "SRB_MEASUREMENT_ROBUSTNESS_REPORT_V1"
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class ResearchGate:
    gate_id: str
    label: str
    status: str
    summary: str
    artifact_refs: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    next_action: str = ""
    policy_version: str = "SRB_GATE_POLICY_V1"


@dataclass(frozen=True)
class MissionSnapshot:
    snapshot_id: str
    created_at: str
    question_id: str
    question_title: str
    question_status: str
    plan_id: str
    plan_status: str
    leading_hypothesis_id: str
    leading_hypothesis_label: str
    null_hypothesis_id: str
    null_hypothesis_label: str
    primary_observable_id: str
    primary_observable_label: str
    next_action: str
    overall_status: str
    gates: tuple[ResearchGate, ...]
    inconsistencies: tuple[str, ...]
    blockers: tuple[str, ...]
    budget_remaining: dict[str, float]
    counts: dict[str, int]
    production_status: str = "RESEARCH_ONLY"
