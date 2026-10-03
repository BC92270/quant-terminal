from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DirectSourceReconciliationRecord:
    reconciliation_id: str
    created_at: str
    replication_id: str
    reference_snapshot_id: str
    reference_snapshot_fingerprint: str
    protocol_frozen_at: str
    protocol_fingerprint: str
    series_matrix: dict[str, dict[str, str]]
    protocol_version: str = "SRB_DIRECT_BIS_RECONCILIATION_V1"
    source_provider: str = "Bank for International Settlements"
    source_dataset: str = "BIS Effective exchange rates (WS_EER 1.0)"
    source_access_mode: str = "PUBLIC_BIS_BULK_CSV_FLAT_ZIP"
    source_url: str = "https://data.bis.org/static/bulk/WS_EER_csv_flat.zip"
    source_documentation_url: str = "https://data.bis.org/help/export"
    source_terms_url: str = "https://data.bis.org/help/legal"
    access_cost: str = "FREE"
    credentials_required: bool = False
    frequency: str = "MONTHLY"
    basket: str = "BROAD_64_ECONOMIES"
    history_semantics: str = "CURRENT_REVISED_HISTORY_NOT_A_VINTAGE_ARCHIVE"
    point_in_time_status: str = "NOT_POINT_IN_TIME"
    historical_evidence_eligible: bool = False
    min_rows_per_series: int = 120
    min_overlap_rows: int = 24
    equality_tolerance: float = 1e-10
    prospective_min_distinct_snapshots: int = 12
    prospective_min_distinct_latest_periods: int = 12
    prospective_min_span_days: int = 300
    status: str = "FROZEN"
    execution_status: str = "NOT_RUN"
    completed_at: str = ""
    source_integrity_status: str = "PENDING_EXECUTION"
    coverage_status: str = "PENDING_EXECUTION"
    reconciliation_status: str = "NOT_RUN"
    direct_snapshot_id: str = ""
    direct_snapshot_path: str = ""
    direct_snapshot_fingerprint: str = ""
    raw_archive_sha256: str = ""
    raw_archive_bytes: int = 0
    raw_csv_bytes: int = 0
    retrieved_at: str = ""
    response_metadata: dict[str, str] = field(default_factory=dict)
    latest_period: str = ""
    series_count: int = 0
    expected_series_count: int = 0
    total_overlap_rows: int = 0
    total_exact_match_rows: int = 0
    total_revised_rows: int = 0
    series_results: tuple[dict[str, Any], ...] = ()
    reconciliation_fingerprint: str = ""
    prospective_distinct_snapshots: int = 0
    prospective_distinct_latest_periods: int = 0
    prospective_span_days: int = 0
    prospective_vintage_status: str = "WARMING_UP"
    independence_dimensions: dict[str, bool] = field(default_factory=lambda: {
        "distribution_channel": True,
        "source_host": True,
        "underlying_data_lineage": False,
        "methodology": False,
        "point_in_time": False,
        "investigator": False,
    })
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = (
        "The BIS bulk file is current revised history, not a historical vintage archive and not point-in-time evidence.",
        "The direct BIS route is independent from the ALFRED distribution channel, but the underlying BIS data and methodology are shared.",
        "Revision differences are measured and retained; they are not silently treated as data errors or causal replication.",
        "Forward-vintage readiness can only grow from snapshots actually observed after this ledger was installed; no earlier vintage is fabricated.",
    )
    lifecycle_history: tuple[dict[str, Any], ...] = ()
    automatic_promotion_authorized: bool = False
    production_status: str = "RESEARCH_ONLY"


__all__ = ["DirectSourceReconciliationRecord"]
