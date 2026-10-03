from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CrossProviderTriangulationRecord:
    """Frozen and append-only BIS/OECD measurement-triangulation record."""

    triangulation_id: str
    created_at: str
    replication_id: str
    direct_reconciliation_id: str
    direct_snapshot_id: str
    direct_snapshot_fingerprint: str
    protocol_frozen_at: str
    protocol_fingerprint: str
    comparison_matrix: dict[str, dict[str, str]]
    direct_series_matrix: dict[str, dict[str, str]]
    protocol_version: str = "SRB_CROSS_PROVIDER_TRIANGULATION_V1"
    source_provider: str = "Organisation for Economic Co-operation and Development"
    source_dataset: str = "OECD Financial market (DF_FINMARK 4.0) — CPI-based real effective exchange rates"
    source_access_mode: str = "PUBLIC_OECD_SDMX_CSV_WITH_LABELS"
    source_url: str = (
        "https://sdmx.oecd.org/public/rest/data/"
        "OECD.SDD.STES,DSD_STES@DF_FINMARK,4.0/"
        "USA+GBR+JPN.M.CCRE......?startPeriod=1994-01&"
        "dimensionAtObservation=AllDimensions&format=csvfilewithlabels"
    )
    source_documentation_url: str = "https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html"
    source_structure_url: str = (
        "https://sdmx.oecd.org/public/rest/dataflow/"
        "OECD.SDD.STES/DSD_STES@DF_FINMARK/4.0?references=all"
    )
    source_terms_url: str = "https://www.oecd.org/en/about/terms-conditions.html"
    access_cost: str = "FREE"
    credentials_required: bool = False
    frequency: str = "MONTHLY"
    measure: str = "REAL_EFFECTIVE_EXCHANGE_RATE_CPI_BASED"
    history_semantics: str = "CURRENT_REVISED_HISTORY_NOT_A_VINTAGE_ARCHIVE"
    point_in_time_status: str = "NOT_POINT_IN_TIME"
    historical_evidence_eligible: bool = False
    min_rows_per_series: int = 120
    min_overlap_rows: int = 120
    min_change_correlation: float = 0.90
    min_sign_agreement: float = 0.80
    max_mean_absolute_change_gap_pp: float = 0.50
    rolling_window_months: int = 36
    status: str = "FROZEN"
    execution_status: str = "NOT_RUN"
    completed_at: str = ""
    source_integrity_status: str = "PENDING_EXECUTION"
    coverage_status: str = "PENDING_EXECUTION"
    comparability_status: str = "NOT_EVALUATED"
    triangulation_outcome: str = "NOT_RUN"
    oecd_snapshot_id: str = ""
    oecd_snapshot_path: str = ""
    oecd_snapshot_fingerprint: str = ""
    raw_csv_sha256: str = ""
    raw_csv_bytes: int = 0
    retrieved_at: str = ""
    response_metadata: dict[str, str] = field(default_factory=dict)
    base_period: str = ""
    latest_period: str = ""
    expected_series_count: int = 3
    source_series_count: int = 0
    comparable_series_count: int = 0
    concordant_series_count: int = 0
    divergent_series_count: int = 0
    series_results: tuple[dict[str, Any], ...] = ()
    triangulation_fingerprint: str = ""
    independence_dimensions: dict[str, bool] = field(default_factory=lambda: {
        "distribution_channel": True,
        "source_host": True,
        "provider_organization": True,
        "underlying_data_lineage": False,
        "methodology": False,
        "point_in_time": False,
        "investigator": False,
    })
    lineage_assessment: str = "COUNTRY_SPECIFIC_LINEAGE_UNRESOLVED_FROM_OECD_FEED_METADATA"
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = (
        "OECD is a distinct official provider and distribution route, but the feed's 'National' methodology code does not prove an underlying data lineage independent from BIS.",
        "Raw index levels are not compared because base periods, baskets, weights and revision policies can differ; the primary estimands are monthly log changes.",
        "The OECD and BIS histories are current revised views, not historical vintages and not point-in-time evidence.",
        "Agreement is measurement concordance only; disagreement is retained as evidence and neither provider is declared ground truth.",
        "The same investigator and governed workflow execute both paths; independent-investigator replication remains absent.",
    )
    lifecycle_history: tuple[dict[str, Any], ...] = ()
    automatic_promotion_authorized: bool = False
    production_status: str = "RESEARCH_ONLY"


__all__ = ["CrossProviderTriangulationRecord"]
