# Scientific Research Brain v0.6.7.0 — architecture contract

## Design rule

Registries own facts. Mission Control is a pure projection over one captured snapshot and must never create a second source of truth. A disagreement between registries is a first-class `CONFLICT`, not something the dashboard silently repairs.

Mission Control holds the shared state-root lock while capturing every registry and the audit tail, preventing one dashboard snapshot from mixing bytes observed before and after a concurrent transaction.

When every gate is satisfied, the derived mission action is the final Validation Council review. A pre-completion action persisted in the research plan remains historical context and cannot contradict `READY_FOR_REVIEW`.

## Layers

```text
Literature Radar / authorized source text
  ↓ provenance + source digest
Scientific Compiler / versioned UnderstandingBundle
  ↓ claims, assumptions, mechanisms, entities, equations actually present
Knowledge Graph / Discovery Lab
  ↓ structural candidates only
Transmutation Lab + Transfer Auditor
  ↓ PARTIAL_TRANSFER only
Research Director
  ↓ question, explicit null, plan, budget, stop rules
Observable Lab + Measurement Model
  ↓ explicit human MeasurementDecision; competitors retained
Historical Data Contract Studio
  ↓ point-in-time audit + causal materialization + fingerprints
Experiment Registry
  ↓ append-only attempt + unique run + timestamped trace
Reproducibility / Selection / Break diagnostics
  ↓ frozen three-measure protocol + identical support/split execution
Measurement robustness report
  ↓ versioned computational Validation Council dossier
Failure + Surprise + Theory memory
  ↓ persist-before-fetch independent-market protocol
ALFRED/BIS initial-release snapshot
  ↓ 9 OOS screens + paired forecast tests + Holm correction
Independent replication record
  ↓ frozen source/snapshot/build challenge
Independent TypeScript/Node reconstruction
  ↓ field-level parity or retained discrepancy
Cross-runtime verification record
  ↓ frozen direct-source observation contract
Official BIS current revised-history snapshot
  ↓ six-series initial-versus-revised comparison
Direct-source reconciliation + prospective as-observed ledger
  ↓ frozen cross-provider comparability contract
Official OECD monthly CPI-based REER snapshot
  ↓ monthly-log-change diagnostics; raw levels never equated
Cross-provider triangulation + retained concordance/divergence
```

## Registry ownership

- Phase 2 owns papers, compilations, understanding revisions, provenance and graph objects.
- Phase 3 owns transfer candidates and transfer audits.
- Phase 4 owns experiment specifications, unique execution results and replication plans.
- Phase 5 owns Council reviews, failure memory, surprise memory and theory populations.
- Phase 6 owns questions, hypotheses, plans, cycles, scouts and diary entries.
- Phase 6.1 owns observable lifecycles, evidence promotions, evidence records and budgets.
- Phase 6.2 owns measurement models/decisions, evidence assessments and syntheses.
- Phase 6.3 owns historical contracts/audits, dataset manifests, append-only attempts, break diagnostics, reproducibility capsules, measurement-robustness protocols and comparative reports.
- Phase 6.4 uses the Phase-4 replication registry for an immutable frozen protocol followed by one guarded completion transition; it owns ALFRED initial-release snapshots, cross-market OOS traces and multiplicity-adjusted forecast comparisons.
- Phase 6.5 owns append-only cross-runtime verification records and content-addressed challenge/result artifacts. The independent Node process reads only the sealed canonical source files and cannot authorize production.
- Phase 6.6 owns append-only direct-source reconciliation records, content-addressed BIS revised-history snapshots and the derived forward-vintage readiness ledger. It can validate provenance and revision accounting only; it cannot rewrite Phase-6.4 point-in-time evidence.
- Phase 6.7 owns append-only cross-provider triangulation records and content-addressed OECD revised-history snapshots. It separates provider/host independence from unresolved methodology and underlying lineage, and it cannot rewrite Phase-6.4 point-in-time evidence or select a preferred source after observing disagreement.

All mutable registries under one state root share a bounded POSIX inter-process lock. Each JSON read-modify-write transaction is serialized, fsynced and published with atomic replacement; the audit JSONL file is validated, locked and fsynced before append. A missing file is valid empty state. Invalid JSON, a non-array root or a non-object row raises `RegistryCorruptionError` and blocks mutation. A lock timeout also fails closed instead of risking a lost scientific record.

## Mission gate policy

The derived gate order is:

1. `REGISTRY_INTEGRITY`
2. `PARTIAL_TRANSFER_ELIGIBLE`
3. `SOURCE_GROUNDED_EVIDENCE`
4. `MEASUREMENT_DECISION_RECORDED`
5. `MEASUREMENT_STATE_CONSISTENT`
6. `DATA_CONTRACT_VALIDATED`
7. `POINT_IN_TIME_AUDITED`
8. `MATERIALIZED_DATA_FINGERPRINTED`
9. `BUILTIN_EXECUTOR_AUDITED`
10. `ATTEMPT_REGISTERED`
11. `HISTORICAL_OOS_COMPLETE`
12. `FORECAST_TRACE_AVAILABLE`
13. `SELECTION_PRESSURE_RECORDED`
14. `REPRODUCIBILITY_CAPSULE`
15. `MEASUREMENT_ROBUSTNESS`
16. `VALIDATION_COUNCIL_REVIEWED`
17. `INDEPENDENT_REPLICATION`
18. `CROSS_RUNTIME_REPRODUCIBILITY`
19. `DIRECT_SOURCE_RECONCILIATION`
20. `CROSS_PROVIDER_MEASUREMENT_TRIANGULATION`
21. `PRODUCTION_PROMOTION_LOCK`

`SATISFIED` means that the required artifact exists and passes that gate's narrow policy. It never implies scientific truth. `BLOCKED` and `CONFLICT` dominate the mission state. `NOT_EVALUATED` is not a pass.

`MEASUREMENT_ROBUSTNESS` is satisfied only by a complete immutable report linked to a previously frozen protocol with at least three distinct measurements, identical temporal support, identical chronological split and passing point-in-time controls. Multiple ordinary historical runs are at most `WARNING`. A consistent negative result closes the protocol gate without supporting the hypothesis.

`VALIDATION_COUNCIL_REVIEWED` is satisfied only by `SRB_COUNCIL_REVIEW_V2` tied to the latest historical run and latest measurement report. It requires an explicit computational-not-human boundary, `RESEARCH_WORKFLOW_ONLY`, retained negative-result disposition when applicable, `automatic_promotion_authorized=false` and `RESEARCH_ONLY`.

`INDEPENDENT_REPLICATION` ignores legacy status strings. It requires `SRB_INDEPENDENT_REPLICATION_V1`, a persisted frozen protocol, complete execution tied to the latest historical run, point-in-time `PASS`, at least one declared independent market/period/implementation axis, snapshot and execution fingerprints, an outcome (of any sign), and intact production/auto-promotion locks.

`CROSS_RUNTIME_REPRODUCIBILITY` requires a completed `SRB_CROSS_RUNTIME_VERIFICATION_V1` challenge tied to an eligible independent replication. The challenge binds the sealed source snapshot and TypeScript source hashes before execution. Every declared result must match, retained discrepancy count must be zero, implementation independence must be explicit, investigator independence must remain false, and production/automatic-promotion locks must remain intact.

`DIRECT_SOURCE_RECONCILIATION` requires a completed `SRB_DIRECT_BIS_RECONCILIATION_V1` observation tied to an eligible replication. Every frozen series must pass archive/schema/coverage gates and have a comparison fingerprint. The record must say `CURRENT_REVISED_HISTORY_NOT_A_VINTAGE_ARCHIVE`, `NOT_POINT_IN_TIME`, `historical_evidence_eligible=false`, shared underlying lineage, non-independent investigator and intact promotion locks. Revision differences are admissible; boundary overclaims are conflicts. Prospective readiness is reported separately and never backfilled.

`CROSS_PROVIDER_MEASUREMENT_TRIANGULATION` requires a completed `SRB_CROSS_PROVIDER_TRIANGULATION_V1` record tied to an eligible direct-BIS observation. The raw OECD CSV, three canonical series and every country comparison must be fingerprinted. Comparable countries must expose the exact frozen correlation, directional-agreement and mean-gap checks. `CONCORDANT` and `MEASUREMENT_DIVERGENCE` both satisfy execution quality because disagreement is an admissible result; `NOT_COMPARABLE` remains `WARNING`. Provider and host independence must be true while methodology, underlying lineage, point-in-time and investigator independence remain false. Any overclaim is a `CONFLICT`.

## Identity model

- `attempt_id`: unique for every explicit execution attempt, including failures.
- `run_id`: unique for every completed executor invocation.
- `run_signature`: stable for the same declared protocol and materialized data.
- `evidence_unit_id`: stable unit for epistemic independence; rerunning an identical holdout does not create new evidence.
- `contract_id`, `audit_id`, `manifest_id`: deterministic content identities, idempotent across JSON tuple/list round trips.
- `forecast_trace_fingerprint`: digest over aligned timestamps, actuals, predictions and errors.
- `capsule_id`: digest over run/attempt, contract/data/trace and executor code identity.
- `protocol_id`: digest over question/experiment/contract/audit, verified snapshot, split policy and the complete predeclared measurement allow-list.
- `report_id`: digest over protocol identity, executor source digest and all comparative result/trace identities.
- `replication_id`: digest over the frozen reference run/report, markets, official series, measurements, split, baseline, multiplicity and causal event-time support contract.
- `source_snapshot_fingerprint`: digest over canonical ALFRED initial-release rows for all six BIS series.
- `execution_fingerprint`: digest over the frozen replication contract, snapshot and every OOS trace/result identity.
- `verification_id`: digest-derived identity over the governed replication, snapshot manifest, canonical CSV inventory, TypeScript source inventory and frozen comparison contract.
- `engine_build_fingerprint`: digest over the compiled independent engine and fixed Node CLI used for the execution.
- `result_fingerprint`: SHA-256 digest of the bounded TypeScript result artifact compared with the Python reference.
- `reconciliation_id`: unique frozen observation-cycle identity derived from its replication, reference snapshot, freeze time and protocol fingerprint.
- `direct_snapshot_fingerprint`: digest over the official BIS raw archive identity, six canonical series inventories and revised-history semantics.
- `reconciliation_fingerprint`: digest over the frozen protocol, sealed ALFRED/BIS snapshots and all initial-versus-revised comparison rows.
- `triangulation_id`: unique frozen comparison identity derived from replication, direct snapshot, freeze time and protocol fingerprint.
- `oecd_snapshot_fingerprint`: digest over the exact raw OECD response, three canonical inventories and revised-history semantics.
- `triangulation_fingerprint`: digest over the frozen protocol, sealed BIS/OECD snapshots, every monthly-change row and the retained outcome.

Selection pressure counts every attempt. Theory weights and independent-failure stop rules deduplicate by `evidence_unit_id`, falling back to legacy `run_id` only when necessary.

## Point-in-time materialization

The materializer accepts only allowlisted transforms. It validates raw chronology before any exclusion, enforces `availability + publication_lag <= event_time`, validates vintages, rejects nonpositive log inputs and never reorders data. It may:

- count and exclude leading rows before the first public anchor;
- causally carry an already-public anchor forward when both anchor and availability fields are blank;
- reject partial anchor/availability pairs, backward release time, future vintage and unexplained vintage change.

The run fingerprint must match the manifest's materialized fingerprint exactly.

For ALFRED graph-vintage replication, raw first-observed rows remain sorted by reference period and are never discarded from the snapshot. Forecasting support is then constructed in release-event time: the latest reference period is kept within each co-release event, non-advancing backfills are excluded, and included release timestamps and reference periods must both be strictly increasing. The policy, included rows, excluded rows and exclusion reasons are fingerprinted together.

## Failure semantics

- Empty source extraction is `INCOMPLETE_EXTRACTION`, never grounded evidence.
- Recompilation preserves extraction history and creates a new understanding identity when extractor/ontology signatures change.
- A Phase-6.3 attempt is saved as `PLANNED` before execution, transitions through `RUNNING`, and ends as `COMPLETED`, `FAILED` or another declared terminal state.
- Identical reruns are retained as separate attempts/runs.
- Capsules fail closed when attempt, signature, evidence unit, contract, manifest, observable, data or trace identity disagrees.
- Lifecycle inconsistencies in legacy failure/surprise rows remain visible until explicitly migrated.
- Legacy alignment preserves the stored status and records `historical_transition_asserted=false`; it never invents an original date, actor, reason or evidence reference.

## Compatibility

Legacy JSON rows remain readable because every new dataclass field has a default. The Phase-4 CSV route remains available as `Legacy / unaudited`, but requires explicit timestamps and cannot satisfy v0.6.3 Mission gates. No existing ID is destructively migrated on view.

## Absolute boundaries

- no `eval` or `exec`;
- no execution of LLM-generated source;
- no automatic evidence promotion;
- no automatic belief update;
- no `FULL_TRANSFER`;
- no automatic production promotion;
- no unattended network or experiment loop;
- no claim of independent investigator or independent implementation when only market/data lineage differ.
- no cross-runtime pass when any structural or numerical discrepancy remains.
