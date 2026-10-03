from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CrossRuntimeVerificationRecord:
    verification_id: str
    created_at: str
    replication_id: str
    challenge_fingerprint: str
    challenge_manifest_path: str
    source_snapshot_id: str
    source_snapshot_fingerprint: str
    reference_execution_fingerprint: str
    engine_source_fingerprint: str
    protocol_version: str = "SRB_CROSS_RUNTIME_VERIFICATION_V1"
    status: str = "FROZEN"
    execution_status: str = "NOT_RUN"
    implementation_gate_status: str = "PENDING_EXECUTION"
    parity_status: str = "NOT_RUN"
    numerical_tolerance: float = 1e-6
    engine_language: str = "TypeScript"
    engine_runtime: str = "Node.js"
    engine_protocol_version: str = "SRB_TYPESCRIPT_REPLICATION_ENGINE_V1"
    engine_build_fingerprint: str = ""
    runtime_version: str = ""
    runtime_platform: str = ""
    result_path: str = ""
    result_fingerprint: str = ""
    result_count: int = 0
    matched_result_count: int = 0
    discrepancy_count: int = 0
    discrepancies: tuple[str, ...] = ()
    independence_dimensions: dict[str, bool] = field(default_factory=lambda: {
        "market": True,
        "period": False,
        "implementation": True,
        "data_lineage": True,
        "provider": True,
        "investigator": False,
    })
    lifecycle_history: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = (
        "Implementation independence means a separately authored TypeScript/Node numerical code path reading the sealed source artifacts; it is not a third-party audit.",
        "The investigator, research question, frozen protocol and source snapshot are not independent.",
        "Cross-runtime parity validates reproducibility of this implementation contract, not scientific truth, causal validity or production readiness.",
    )
    automatic_promotion_authorized: bool = False
    production_status: str = "RESEARCH_ONLY"
