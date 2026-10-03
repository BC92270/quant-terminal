from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DatasetContract:
    contract_id: str
    created_at: str
    source_kind: str
    target_variable: str
    time_variable: str = ""
    frequency: str = "UNKNOWN"
    train_fraction: float = 0.7
    max_rows: int = 250000
    leakage_controls: tuple[str, ...] = (
        "chronological split only",
        "fit candidate and baselines on train sample only",
        "test sample remains untouched until scoring",
    )
    required_columns: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class BaselineSpec:
    baseline_id: str
    name: str
    family: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExperimentSpecification:
    experiment_id: str
    created_at: str
    candidate_id: str
    transfer_audit_id: str
    transfer_verdict: str
    stage: str
    status: str
    experimental_family: str
    source_equation_type: str
    hypothesis: str
    null_hypothesis: str
    falsification_rule: str
    target_variable: str
    mapped_variables: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ("RMSE", "MAE")
    baselines: tuple[BaselineSpec, ...] = ()
    dataset_contract: DatasetContract | None = None
    seed: int = 17
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    code_policy: str = "BUILTIN_EXECUTORS_ONLY_NO_EVAL_NO_EXEC"
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class ExperimentRunResult:
    run_id: str
    experiment_id: str
    created_at: str
    stage: str
    status: str
    verdict: str
    seed: int
    data_fingerprint: str
    train_size: int
    test_size: int
    candidate_metrics: dict[str, float] = field(default_factory=dict)
    baseline_metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    deltas_vs_baseline: dict[str, dict[str, float]] = field(default_factory=dict)
    fitted_parameters: dict[str, float] = field(default_factory=dict)
    robustness: dict[str, Any] = field(default_factory=dict)
    falsification_status: str = "NOT_AUTOMATED"
    environment: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    production_status: str = "RESEARCH_ONLY"
    # Phase 6.3 append-only attempt identity and evidence lineage. Defaults keep
    # every v0.6.2.1 JSON record readable without migration.
    attempt_id: str = ""
    run_signature: str = ""
    evidence_unit_id: str = ""
    data_contract_id: str = ""
    data_contract_audit_id: str = ""
    dataset_manifest_id: str = ""
    measurement_model_id: str = ""
    measurement_decision_id: str = ""
    observable_id: str = ""
    forecast_horizon: int = 1
    forecast_origin_timestamps: tuple[str, ...] = ()
    forecast_timestamps: tuple[str, ...] = ()
    actual_values: tuple[float, ...] = ()
    candidate_predictions: tuple[float, ...] = ()
    candidate_errors: tuple[float, ...] = ()
    baseline_predictions: dict[str, tuple[float, ...]] = field(default_factory=dict)
    baseline_errors: dict[str, tuple[float, ...]] = field(default_factory=dict)
    error_definition: str = "ACTUAL_MINUS_PREDICTION"
    split_timestamp: str = ""
    forecast_trace_fingerprint: str = ""
    reproducibility_capsule_id: str = ""
    run_protocol_version: str = "SRB_OU_OOS_V2"
    selection_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReplicationPlan:
    replication_id: str
    created_at: str
    experiment_id: str
    paper_id: str
    claim_ids: tuple[str, ...] = ()
    required_data: tuple[str, ...] = ()
    required_code: tuple[str, ...] = ()
    target_metrics: tuple[str, ...] = ()
    status: str = "DATA_REQUIRED"
    warnings: tuple[str, ...] = ()
