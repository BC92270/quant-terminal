"""Scientific Research Brain internal package.

The package preserves source-grounded understanding, cross-domain transfer gates,
guarded experimentation and explicit measurement uncertainty. Phase 6.3 adds strict
historical data contracts, append-only attempts, forecast traces, reproducibility
capsules and a derived Mission Control. Phase 6.4 adds a transparent computational
Council dossier and frozen, point-in-time independent-market replication. Phase 6.5
adds a separately authored TypeScript/Node cross-runtime reproduction of the sealed
replication artifacts. Every object remains RESEARCH_ONLY.
Phase 6.6 adds an explicit direct-BIS revised-history reconciliation and a
prospective as-observed snapshot ledger without backfilling vintages.
"""

from .phase2_models import (
    AssumptionRecord,
    ClaimRecord,
    EquationStructure,
    KnowledgeEdge,
    KnowledgeNode,
    ProvenanceRecord,
    SemanticEntityRecord,
    UnderstandingBundle,
)
from .scientific_understanding import (
    EXTRACTOR_VERSION,
    build_understanding_bundle,
    extract_claim_records,
    extract_semantic_entities,
    parse_equation_structure,
)
from .knowledge_graph import ScientificKnowledgeGraph
from .ontology import MECHANISM_ONTOLOGY, ONTOLOGY_VERSION, extract_mechanism_scores
from .relevance import rank_literature_results
from .phase3_models import (
    CollisionCandidate,
    GapRecord,
    GraphDiscoveryCandidate,
    StructuralComparison,
    TransmutationCandidate,
    TransferAudit,
    VariableMapping,
)
from .mechanism_space import compare_mechanism_space, family_profile
from .concept_collider import collide_concepts, discover_graph_bridges
from .gap_detection import detect_domain_gaps
from .transmutation import build_transmutation_candidate, audit_transfer_candidate, parse_mapping_lines
from .phase3_registry import Phase3Registry
from .phase4_models import (
    BaselineSpec,
    DatasetContract,
    ExperimentRunResult,
    ExperimentSpecification,
    ReplicationPlan,
)
from .experiment_factory import (
    build_experiment_specification,
    build_replication_plan,
    dataset_fingerprint,
    recognize_experimental_family,
    run_historical_oos_experiment,
    run_synthetic_experiment,
    simulate_ou_series,
)
from .experiment_registry import ExperimentRegistry

from .phase5_models import (
    AuditorFinding,
    EvidenceEvent,
    FailureRecord,
    MultipleTestingAssessment,
    SurpriseRecord,
    TheoryPopulation,
    TheoryState,
    ValidationReview,
)
from .validation_engine import (
    build_multiple_testing_assessment,
    build_theory_population,
    build_validation_review,
    derive_failure_records,
    derive_surprise_records,
    validate_and_learn,
)
from .validation_registry import ValidationRegistry
from .replication_engine import (
    ALFRED_BIS_MARKETS,
    ALFRED_FORM_ACCESS_MODE,
    ALFRED_GRAPH_ACCESS_MODE,
    ALFRED_GRAPH_BASE,
    ALFRED_HELP_URL,
    BIS_TERMS_URL,
    FRED_TERMS_URL,
    INDEPENDENT_REPLICATION_PROTOCOL_VERSION,
    REPLICATION_EVENT_TIME_SUPPORT_POLICY,
    AlfredInitialReleaseRow,
    AlfredSeriesSnapshot,
    IndependentReplicationRecord,
    ReplicationDataError,
    build_alfred_bis_replication_protocol,
    execute_alfred_bis_replication,
    fetch_alfred_graph_initial_release_series,
    fetch_alfred_initial_release_series,
    load_persisted_alfred_snapshot_bundle,
)
from .phase65_models import CrossRuntimeVerificationRecord
from .phase65_registry import Phase65Registry
from .cross_runtime_verification import (
    CROSS_RUNTIME_ENGINE_PROTOCOL,
    CROSS_RUNTIME_PROTOCOL_VERSION,
    CROSS_RUNTIME_TOLERANCE,
    CrossRuntimeVerificationError,
    compare_cross_runtime_results,
    cross_runtime_runtime_status,
    execute_cross_runtime_verification,
    freeze_cross_runtime_verification,
)
from .phase66_models import DirectSourceReconciliationRecord
from .phase66_registry import Phase66Registry
from .direct_bis_reconciliation import (
    BisArchivePayload,
    DIRECT_BIS_ACCESS_MODE,
    DIRECT_BIS_EXPORT_HELP_URL,
    DIRECT_BIS_HISTORY_SEMANTICS,
    DIRECT_BIS_PROTOCOL_VERSION,
    DIRECT_BIS_SOURCE_URL,
    DIRECT_BIS_TERMS_URL,
    DIRECT_BIS_TOPIC_URL,
    DirectBisDataError,
    build_prospective_vintage_summary,
    download_bis_eer_archive,
    execute_direct_bis_reconciliation,
    freeze_direct_bis_reconciliation,
    parse_bis_eer_archive,
)

__all__ = [
    "AssumptionRecord", "ClaimRecord", "EquationStructure", "KnowledgeEdge", "KnowledgeNode",
    "ProvenanceRecord", "SemanticEntityRecord", "UnderstandingBundle", "EXTRACTOR_VERSION", "build_understanding_bundle",
    "extract_claim_records", "extract_semantic_entities", "parse_equation_structure",
    "ScientificKnowledgeGraph", "MECHANISM_ONTOLOGY", "ONTOLOGY_VERSION", "extract_mechanism_scores",
    "rank_literature_results", "CollisionCandidate", "GapRecord", "GraphDiscoveryCandidate",
    "StructuralComparison", "TransmutationCandidate", "TransferAudit", "VariableMapping",
    "compare_mechanism_space", "family_profile", "collide_concepts", "discover_graph_bridges",
    "detect_domain_gaps", "build_transmutation_candidate", "audit_transfer_candidate",
    "parse_mapping_lines", "Phase3Registry", "BaselineSpec", "DatasetContract",
    "ExperimentRunResult", "ExperimentSpecification", "ReplicationPlan",
    "build_experiment_specification", "build_replication_plan", "dataset_fingerprint",
    "recognize_experimental_family", "run_historical_oos_experiment", "run_synthetic_experiment",
    "simulate_ou_series", "ExperimentRegistry",
    "AuditorFinding", "EvidenceEvent", "FailureRecord", "MultipleTestingAssessment",
    "SurpriseRecord", "TheoryPopulation", "TheoryState", "ValidationReview",
    "build_multiple_testing_assessment", "build_theory_population", "build_validation_review",
    "derive_failure_records", "derive_surprise_records", "validate_and_learn", "ValidationRegistry",
    "ALFRED_BIS_MARKETS", "ALFRED_FORM_ACCESS_MODE", "ALFRED_GRAPH_ACCESS_MODE", "ALFRED_GRAPH_BASE",
    "ALFRED_HELP_URL", "BIS_TERMS_URL", "FRED_TERMS_URL",
    "INDEPENDENT_REPLICATION_PROTOCOL_VERSION", "REPLICATION_EVENT_TIME_SUPPORT_POLICY",
    "AlfredInitialReleaseRow", "AlfredSeriesSnapshot",
    "IndependentReplicationRecord", "ReplicationDataError", "build_alfred_bis_replication_protocol",
    "execute_alfred_bis_replication", "fetch_alfred_graph_initial_release_series", "fetch_alfred_initial_release_series",
    "load_persisted_alfred_snapshot_bundle",
    "CrossRuntimeVerificationRecord", "Phase65Registry",
    "CROSS_RUNTIME_ENGINE_PROTOCOL", "CROSS_RUNTIME_PROTOCOL_VERSION", "CROSS_RUNTIME_TOLERANCE",
    "CrossRuntimeVerificationError", "compare_cross_runtime_results", "cross_runtime_runtime_status",
    "execute_cross_runtime_verification", "freeze_cross_runtime_verification",
    "DirectSourceReconciliationRecord", "Phase66Registry", "BisArchivePayload",
    "DIRECT_BIS_ACCESS_MODE", "DIRECT_BIS_EXPORT_HELP_URL", "DIRECT_BIS_HISTORY_SEMANTICS",
    "DIRECT_BIS_PROTOCOL_VERSION", "DIRECT_BIS_SOURCE_URL", "DIRECT_BIS_TERMS_URL",
    "DIRECT_BIS_TOPIC_URL", "DirectBisDataError", "build_prospective_vintage_summary",
    "download_bis_eer_archive", "execute_direct_bis_reconciliation",
    "freeze_direct_bis_reconciliation", "parse_bis_eer_archive",
]

from .phase6_models import (
    DirectorCycle,
    LiteratureScoutRecord,
    OpenResearchQuestion,
    ResearchBudget,
    ResearchDiaryEntry,
    ResearchHypothesis,
    ResearchPlan,
    ResearchTask,
)
from .autonomy_engine import (
    BoundedCycleOutput,
    build_research_plan,
    build_scout_record,
    derive_open_questions,
    evaluate_stop_conditions,
    generate_hypotheses,
    run_bounded_research_cycle,
)
from .autonomy_registry import AutonomyRegistry

__all__ += [
    "DirectorCycle", "LiteratureScoutRecord", "OpenResearchQuestion", "ResearchBudget",
    "ResearchDiaryEntry", "ResearchHypothesis", "ResearchPlan", "ResearchTask",
    "BoundedCycleOutput", "build_research_plan", "build_scout_record", "derive_open_questions",
    "evaluate_stop_conditions", "generate_hypotheses", "run_bounded_research_cycle", "AutonomyRegistry",
]

from .phase61_models import (
    BudgetEvent,
    BudgetLedger,
    EvidencePromotion,
    GroundedEvidenceRecord,
    ObservableCandidate,
)
from .closed_loop_engine import (
    build_budget_ledger,
    build_evidence_promotion,
    build_grounded_evidence_record,
    generate_observable_candidates,
)
from .closed_loop_registry import ClosedLoopRegistry

__all__ += [
    "BudgetEvent", "BudgetLedger", "EvidencePromotion", "GroundedEvidenceRecord", "ObservableCandidate",
    "build_budget_ledger", "build_evidence_promotion", "build_grounded_evidence_record",
    "generate_observable_candidates", "ClosedLoopRegistry",
]

from .phase62_models import (
    EvidenceAssessment,
    EvidenceSynthesis,
    MeasurementDecision,
    MeasurementHypothesis,
    MeasurementModel,
)
from .measurement_evidence_engine import (
    build_evidence_assessment,
    build_evidence_synthesis,
    build_measurement_decision,
    build_measurement_model,
)
from .phase62_registry import Phase62Registry

__all__ += [
    "EvidenceAssessment", "EvidenceSynthesis", "MeasurementDecision", "MeasurementHypothesis", "MeasurementModel",
    "build_evidence_assessment", "build_evidence_synthesis", "build_measurement_decision", "build_measurement_model",
    "Phase62Registry",
]

from .phase63_models import (
    BreakDiagnostic,
    CausalTransformStep,
    DataContractAudit,
    DataFieldSpec,
    DatasetManifest,
    ExperimentAttemptRecord,
    HistoricalDataContract,
    MaterializedDataset,
    MeasurementRobustnessProtocol,
    MeasurementRobustnessReport,
    MeasurementVariantResult,
    MeasurementVariantSpec,
    MissionSnapshot,
    RegistryFileHealth,
    ReproducibilityCapsule,
    ResearchGate,
    SelectionPressureSnapshot,
)
from .data_contract_engine import (
    ALLOWED_ANCHOR_FAMILIES,
    ALLOWED_FREQUENCIES,
    ALLOWED_REVISION_POLICIES,
    audit_historical_data_contract,
    build_break_diagnostic,
    build_experiment_attempt,
    build_historical_data_contract,
    build_reproducibility_capsule,
    build_selection_pressure_snapshot,
    materialize_price_to_fundamental,
)
from .phase63_registry import Phase63Registry, RegistryCorruptionError
from .measurement_robustness import (
    MEASUREMENT_ROBUSTNESS_POLICY_VERSION,
    build_ecb_measurement_robustness_protocol,
    ecb_measurement_variant_specs,
    execute_ecb_measurement_robustness,
    measurement_robustness_executor_digest,
    snapshot_rows_fingerprint,
)
from .mission_control_engine import (
    build_epistemic_timeline,
    build_evidence_inspector,
    build_measurement_arena,
    build_mission_snapshot,
    build_run_room,
    capture_registry_snapshot,
    inspect_registry_file,
)
from .public_data_pipeline import (
    BLS_HOUSING_URL,
    BLS_RENT_SERIES_ID,
    ECB_RTD_DATASET_ID,
    ECB_RTD_NOMINAL_SERIES_KEY,
    ECB_RTD_NOMINAL_URL,
    ECB_RTD_REAL_SERIES_KEY,
    ECB_RTD_REAL_URL,
    FHFA_HPI_URL,
    FHFA_SERIES_ID,
    PUBLIC_DATASET_ID,
    PublicDataBundle,
    PublicDataError,
    PublicDataManifest,
    ecb_rtd_contract_preset,
    fetch_ecb_rtd_eer_bundle,
    fetch_fhfa_bls_housing_bundle,
    list_public_data_snapshots,
    load_public_data_snapshot,
    persist_public_data_bundle,
    public_data_contract_preset,
)

__all__ += [
    "BreakDiagnostic", "CausalTransformStep", "DataContractAudit", "DataFieldSpec",
    "DatasetManifest", "ExperimentAttemptRecord", "HistoricalDataContract", "MaterializedDataset",
    "MeasurementRobustnessProtocol", "MeasurementRobustnessReport", "MeasurementVariantResult",
    "MeasurementVariantSpec",
    "MissionSnapshot", "RegistryFileHealth", "ReproducibilityCapsule", "ResearchGate",
    "SelectionPressureSnapshot", "ALLOWED_ANCHOR_FAMILIES", "ALLOWED_FREQUENCIES",
    "ALLOWED_REVISION_POLICIES", "audit_historical_data_contract", "build_break_diagnostic",
    "build_experiment_attempt", "build_historical_data_contract", "build_reproducibility_capsule",
    "build_selection_pressure_snapshot", "materialize_price_to_fundamental", "Phase63Registry",
    "RegistryCorruptionError",
    "MEASUREMENT_ROBUSTNESS_POLICY_VERSION", "build_ecb_measurement_robustness_protocol",
    "ecb_measurement_variant_specs", "execute_ecb_measurement_robustness",
    "measurement_robustness_executor_digest", "snapshot_rows_fingerprint",
    "build_epistemic_timeline", "build_evidence_inspector", "build_measurement_arena",
    "build_mission_snapshot", "build_run_room", "capture_registry_snapshot", "inspect_registry_file",
    "BLS_HOUSING_URL", "BLS_RENT_SERIES_ID", "FHFA_HPI_URL", "FHFA_SERIES_ID",
    "ECB_RTD_DATASET_ID", "ECB_RTD_NOMINAL_SERIES_KEY", "ECB_RTD_NOMINAL_URL",
    "ECB_RTD_REAL_SERIES_KEY", "ECB_RTD_REAL_URL",
    "PUBLIC_DATASET_ID", "PublicDataBundle", "PublicDataError", "PublicDataManifest",
    "ecb_rtd_contract_preset", "fetch_ecb_rtd_eer_bundle", "fetch_fhfa_bls_housing_bundle",
    "list_public_data_snapshots", "load_public_data_snapshot", "persist_public_data_bundle",
    "public_data_contract_preset",
]
