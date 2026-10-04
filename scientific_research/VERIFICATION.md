# Scientific Research Brain v0.6.8.0 — verification

## Required commands

```bash
git diff --check
python3 -c "import json,pathlib,subprocess; [json.loads(pathlib.Path(p).read_text(encoding='utf-8')) for p in subprocess.check_output(['git','ls-files','*.json'], text=True).splitlines()]"
python3 -m compileall -q scientific_research scientific_research_lab.py
python3 -m unittest discover -s scientific_research/tests_python -p 'test_*.py' -v
python3 -m unittest discover -s tests -p 'test_scientific*.py' -v
```

The TypeScript foundation is pinned by `pnpm-lock.yaml`:

```bash
pnpm --dir scientific_research install --frozen-lockfile
pnpm --dir scientific_research run verify
```

The release proof records 63 internal Python tests, 90 scientific integration tests (including the route smoke) and 11 TypeScript/Node tests. A later code change invalidates those counts until every command is rerun on the new exact commit.

## Python coverage

The v0.6.8.0 suite covers:

- complete point-in-time contract validation and revised-history warnings;
- measurement-lineage and observable-lifecycle conflicts;
- allowlisted transforms and one price-to-fundamental materializer;
- strict chronological timestamps and timestamp parser failures;
- public availability plus declared publication lag;
- vintage requirements and future/incoherent vintage rejection;
- leading pre-release exclusion accounting;
- causal post-release carry-forward and partial-pair rejection;
- positivity before logarithms and minimum valid sample size;
- raw, contract, materialized and trace fingerprints;
- future-row changes not rewriting earlier states;
- aligned actuals, predictions and `actual - prediction` errors;
- unique attempt/run IDs with stable signatures and evidence units;
- append-only attempt lifecycle and retained execution failure;
- selection pressure counting reruns without epistemic duplication;
- registry corruption failing closed without overwrite;
- concurrent multi-process registry writes retaining every unique record, plus bounded lock-contention failure without mutation;
- native `?workspace=scientific-research` Streamlit rendering with its research-only banner, governed workspaces and return control;
- explicit, idempotent legacy lifecycle alignment without a fabricated historical assertion;
- reproducibility capsule identity checks and secret-field filtering;
- source-grounded evidence gates rejecting empty extraction;
- measurement-state conflicts remaining visible;
- Mission gates for selection pressure and reproducibility;
- production/belief lock violations;
- theory population and independent-failure deduplication by evidence unit.
- Council v2 measurement-report linkage, negative-result retention, human-attestation boundary and automatic-promotion lock;
- legacy Council/replication artifacts failing closed in Mission Control;
- persist-before-fetch independent-replication lifecycle and append-only completion;
- ALFRED form/graph response validation, HTTP/2 transport, 12-column graph cap, source snapshot persistence, fail-closed no-network restart and point-in-time alignment;
- fail-closed causal handling of co-released observations and non-advancing backfills;
- three markets × three measurements with complete chronological forecast traces;
- paired horizon-one forecast comparisons and nine-test Holm-Bonferroni adjustment;
- explicit market/data-lineage independence with implementation/investigator non-independence.
- replacement of stale persisted plan instructions when every Mission Control gate is satisfied and the mission is ready for final review.
- deterministic challenge identity from the governed replication, sealed snapshot, canonical CSV hashes and TypeScript source hashes;
- independent TypeScript reconstruction of all nine causal OOS screens without importing Python numerical code;
- field-level cross-runtime comparison of support exclusions, splits, metrics, parameters, traces, forecast tests, multiplicity adjustment and verdicts;
- append-only `FROZEN → COMPLETE` verification lifecycle, retained disagreement and a fail-closed Mission Control gate;
- exact UTC timestamp serialization across Python and TypeScript, with a declared numerical tolerance of `1e-6`;
- explicit implementation independence, explicit investigator non-independence and unbroken `RESEARCH_ONLY` locks.
- persist-before-network direct BIS observation protocols and append-only `FROZEN → COMPLETE` lifecycle;
- bounded ZIP/CSV validation, exact six-series filtering, source schema/status/collection checks, content-addressed raw/canonical persistence and fail-closed restart/tamper revalidation;
- field-level reconciliation of ALFRED initial releases against current BIS revised history without classifying legitimate revisions as transport failures;
- explicit independent distribution path with shared underlying BIS lineage and permanently non-point-in-time historical eligibility;
- prospective forward-vintage readiness that deduplicates identical content and requires 12 distinct snapshots, 12 distinct latest months and 300 observed days;
- fail-closed `DIRECT_SOURCE_RECONCILIATION` Mission Control behavior for coverage, fingerprints, provenance overclaims and promotion locks.
- persist-before-network OECD/BIS triangulation protocols and append-only `FROZEN → COMPLETE` lifecycle;
- exact three-country OECD SDMX schema, identity, status, frequency, unit, methodology, continuity, positivity and base-period checks;
- raw OECD CSV plus canonical GB/JP/US persistence with restart and tamper revalidation;
- base-invariant monthly log-change comparison, rolling diagnostics and frozen correlation/direction/mean-gap thresholds;
- outcome-neutral `CONCORDANT`, `MEASUREMENT_DIVERGENCE` and `NOT_COMPARABLE` semantics without provider selection after result observation;
- fail-closed `CROSS_PROVIDER_MEASUREMENT_TRIANGULATION` behavior for incomplete matrices, provenance overclaims, revised-history misuse and promotion-lock violations.
- strict question-to-experiment lineage with no first-global-experiment fallback in Mission Control or Run Room;
- epistemic-timeline isolation that excludes unlinked records and audit events from other missions;
- immutable prospective-program identities, exact real-seed lineage and frozen 12/12/300 thresholds;
- first-eligible-month enforcement, captured/open/missed calendar states, permanent no-backfill gaps and one schedule credit per UTC month;
- deterministic one-per-month evidence selection even when many content-distinct observations share a window, plus late-completion exclusion;
- full future-observation validation for lifecycle chronology, reconciliation hashes, frozen matrix coverage, comparison fingerprints and real month-start dates;
- duplicate program rows (including identical IDs) failing closed, with one valid program allowed for each governed replication;
- explicit foreign `question_id` authority over a shared experiment ID in Mission Control, Run Room and the epistemic timeline;
- content-distinct maturity accounting that retains duplicate observations without manufacturing snapshots or latest months;
- separate current-study review readiness and prospective-evidence maturity in Mission Control and closure exports;
- closure dossier/calendar fingerprints, direct/OECD artifact indexes, exact missed-window identities, runtime timestamp authority and external-verifier non-claims;
- finite-only dated chart frames plus responsive, focus-visible and reduced-motion UI rules.

## Acceptance criteria

1. No malformed registry is interpreted as empty.
2. No historical run can execute without explicit increasing ISO-8601 timestamps.
3. A Phase-6.3 run must be attributable to one validated contract, audit, manifest, measurement and pre-registered attempt.
4. Manifest and run data fingerprints are equal.
5. Trace arrays have equal non-zero lengths and a digest.
6. Repeating the same holdout creates a new attempt/run but not a new independent evidence unit.
7. Empty extraction cannot complete evidence, plan or synthesis gates.
8. `CONTEXT_ONLY` evidence remains non-directional and cannot authorize belief update.
9. Production status is `RESEARCH_ONLY` throughout.
10. Mission Control is read-only and reports rather than hides legacy contradictions; any alignment is explicit, idempotent and non-assertive.
11. No Council artifact can imply human review or authorize automatic promotion.
12. No independent-replication execution can be inserted without a previously persisted frozen protocol.
13. Replication completion requires point-in-time initial releases, an independent axis, raw/canonical snapshot evidence and execution fingerprints.
14. A legacy replication without the frozen co-release/backfill event-time policy cannot execute or satisfy Mission Control.
15. Concurrent registry writers cannot silently overwrite one another; lock timeout fails closed and preserves prior bytes.
16. A cross-runtime challenge must be persisted frozen before Node execution and must bind exact source, build, snapshot and result fingerprints.
17. `CROSS_RUNTIME_REPRODUCIBILITY` cannot pass unless every persisted Python result has one matching TypeScript result, with zero retained discrepancy.
18. A direct BIS acquisition must be persisted frozen before network access and must retain the exact raw archive, six canonical series and complete comparison fingerprints.
19. Current revised BIS history must remain `NOT_POINT_IN_TIME` and `historical_evidence_eligible=false`; violating either boundary is a Mission Control conflict.
20. A prospective vintage count increases only for a content-distinct snapshot actually observed by the ledger; no historical vintage may be inferred or fabricated.
21. An OECD/BIS triangulation must be persisted frozen before OECD access and bind the exact direct-BIS snapshot, country matrix and thresholds.
22. Raw index levels are never an equality criterion; conclusions use consecutive monthly log changes on governed common support.
23. Provider/host independence cannot be promoted into methodology, underlying-lineage, point-in-time or investigator independence.
24. A retained `MEASUREMENT_DIVERGENCE` may close the execution-quality gate, while `NOT_COMPARABLE` cannot become a concordance claim.
25. A mission without an explicit or governed foreign-key experiment link cannot inherit another mission's specification, attempts, runs, replications or timeline events.
26. A Phase-6.8 program must be frozen around one exact completed direct-BIS seed; its first eligible window is the next UTC calendar month.
27. The prospective calendar can never credit more than one observation per month; extra distinct snapshots in the same month cannot increase maturity, and a closed empty or late-only window remains missed with `backfillable=false`.
28. A program threshold, seed, cadence, fingerprint, identity or research-only boundary change must fail closed in both the registry and Mission Control.
29. `READY_FOR_REVIEW` for the current dossier cannot be represented as `READY_FOR_FORWARD_VINTAGE_STUDY` until 12 distinct snapshots, 12 distinct latest periods and 300 genuinely observed days exist.
30. Closure exports must explicitly keep investigator independence, peer review, scientific truth and production authorization false.
31. A complete prospective observation cannot accrue evidence unless its creation/freeze/retrieval/completion chronology, reconciliation hashes, exact series coverage and comparison fingerprints all validate.
32. Two program rows for the active replication are a conflict even when their `program_id` values are identical; acquisition and export must stop.
33. A record with an explicit foreign `question_id` cannot enter another mission merely by sharing its experiment ID.
34. The historical `core_study_status` must remain derivable independently of `prospective_operations_status`; the combined operational Mission state may still wait or block.
35. A verifier handoff is an index, not a self-contained reproduction: it must name the program, seed, direct snapshots, hashes, calendar gaps and cross-provider artifact while requiring the referenced state and files.

## Current scientific acceptance boundary

Passing the software suite proves implementation behavior only. Scientific gates close only from persisted live artifacts satisfying their narrow contracts. A Council dossier is computational; ALFRED/BIS supplies independent market/data lineage; TypeScript/Node supplies an independent implementation. Direct BIS supplies an independent distribution route but shares the underlying BIS lineage and exposes revised history. OECD supplies another official provider/host and a country-labelled representation, but the feed alone does not prove methodology or underlying-lineage independence. The investigator and governed workflow remain shared. None of these is peer review, causal proof, production authorization or scientific truth.

## Release boundary

- The product route is `?workspace=scientific-research` and is registered in both the Institutional Navigator and the contextual-assistant manifest.
- Release code never contains `.scientific_research_data`; runtime state is supplied through `SRB_MEMORY_DIR` or the ignored default directory.
- A clean checkout must pass the Python suites and the pinned TypeScript verification before deployment.
- A live acceptance additionally requires a successful Streamlit health check, zero current tracebacks, route rendering and restoration of the selected runtime state after restart.
