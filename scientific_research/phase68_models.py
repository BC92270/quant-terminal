from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


PROSPECTIVE_PROGRAM_WARNINGS: tuple[str, ...] = (
    "The seed is a real prior observation; schedule adherence starts only with the first future UTC month.",
    "A calendar window is an acquisition opportunity, not evidence. Only content-distinct snapshots and distinct latest periods advance maturity.",
    "Missed windows remain visible and can never be repaired with a retroactively labelled observation.",
    "Acquisition timestamps are runtime-asserted and receipt-bound, not third-party trusted timestamps; durable external hash inventories remain required.",
    "Prospective maturity does not create investigator independence, peer review, causal truth or production authority.",
)


@dataclass(frozen=True)
class ProspectiveObservationProgram:
    """Frozen operating contract for genuinely prospective BIS observations."""

    program_id: str
    created_at: str
    replication_id: str
    seed_reconciliation_id: str
    seed_snapshot_id: str
    seed_snapshot_fingerprint: str
    seed_retrieved_at: str
    seed_latest_period: str
    protocol_frozen_at: str
    protocol_fingerprint: str
    first_future_window: str
    protocol_version: str = "SRB_PROSPECTIVE_OBSERVATION_PROGRAM_V1"
    cadence: str = "UTC_CALENDAR_MONTH"
    maximum_credited_observations_per_window: int = 1
    duplicate_content_policy: str = "RETAIN_OBSERVATION_EXCLUDE_FROM_DISTINCT_EVIDENCE"
    missed_window_policy: str = "RETAIN_GAP_NEVER_BACKFILL"
    prospective_min_distinct_snapshots: int = 12
    prospective_min_distinct_latest_periods: int = 12
    prospective_min_span_days: int = 300
    history_semantics: str = "CURRENT_REVISED_HISTORY_NOT_A_VINTAGE_ARCHIVE"
    point_in_time_status: str = "PROSPECTIVE_AS_OBSERVED_ONLY"
    historical_backfill_permitted: bool = False
    historical_evidence_eligible: bool = False
    status: str = "ACTIVE"
    lifecycle_history: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = PROSPECTIVE_PROGRAM_WARNINGS
    automatic_execution_authorized: bool = False
    automatic_promotion_authorized: bool = False
    production_status: str = "RESEARCH_ONLY"


__all__ = ["PROSPECTIVE_PROGRAM_WARNINGS", "ProspectiveObservationProgram"]
