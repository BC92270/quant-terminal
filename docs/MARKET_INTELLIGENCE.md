# Market Intelligence — Catalyst × Microstructure

## Boundary

This package is an institutional research and strategic decision-support
workspace. It is not a live trading engine, an HFT execution stack, an LLM
opinion generator, a capital-approval system, or a source of unqualified
directional labels.

The V4 integrated release preserves the V2 institutional control plane and V3
strategic-decision layer, then adds a real, governed ML pattern-discovery
engine. It
provides:

- an autonomous `?workspace=market-intelligence` route;
- thirteen connected research and decision views, with the first view acting
  as the Strategic Decision Room;
- point-in-time typed contracts and timestamp-chain validation;
- transparent surprise, novelty, collision, OFI, queue-imbalance and
  microprice baselines;
- empirical distribution forecasts with monotone quantiles;
- a deterministic Fed × NVDA collision fixture;
- explicit provider, calibration, drift and promotion states;
- strict symbol/context isolation: the canonical NVDA fixture is never
  repainted or fused into a requested unsupported instrument;
- a deterministic append-only SHA-256 evidence chain with tamper and conflict
  detection;
- executable freshness, completeness, point-in-time, calibration, OOS,
  scenario, shadow-history, human-review and evidence-integrity gates;
- a typed model inventory with versioned artifact, configuration and training
  data hashes plus guarded lifecycle transitions and typed, attributable human
  approval records for any future shadow entry;
- assumption-labelled risk envelopes and an immutable research decision packet;
- a deterministic strategic memo that separates research readiness, process
  action, portfolio review and execution authority;
- an options matrix with process, review and prohibited-execution classes;
- typed evidence-for/evidence-against claims, impact states, monitoring rules,
  warning triggers, invalidation conditions, owner roles and review clocks;
- an explicit portfolio state of `UNPRICED` whenever mandate, holdings,
  constraints or exposure sensitivities are absent;
- a hash-chained, session-scoped human disposition journal supporting
  `RETURN_FOR_EVIDENCE`, `DEFER`, `REJECT_MEMO` and a gate-conditioned
  `ADVANCE_TO_INDEPENDENT_REVIEW` without representing capital approval or a
  durable system-of-record;
- explicit memo validity: expired dossiers cannot be deferred or advanced and
  any permitted retrospective record remains labelled `EXPIRED`;
- a blocking `CONTEXT_INTEGRITY` gate, so an unsupported requested ticker can
  never inherit the canonical NVDA strategic interpretation;
- an exportable JSON evidence dossier containing the decision, ledger, model
  registry, risk envelope, canonical source contracts and scenario definitions
  required for deterministic replay;
- a two-level institutional workflow (`FRAME & OBSERVE → EXPLAIN → SYNTHESIZE
  → DECIDE & GOVERN`) while preserving all thirteen views;
- deterministic causal OHLCV features, train-only robust scaling, return-blind
  cluster-count selection, fitted k-means market states, a horizon-sized purge
  and a run-locked terminal OOS segment;
- an admissibility contract requiring a complete provider-observed next open
  and either provider-observed adjusted close or a declared native
  non-corporate-action series; synthesized or partial required price fields
  block fitting rather than being promoted as economic evidence;
- split-consistent price geometry, one-bar next-open entry, a feature manifest
  selected on training data only, and train-fit OOD heuristics;
- train-fixed conditional direction, after-cost OOS outcomes, matched-rest
  conditional uplift, subperiod stability, full-chronology block-bootstrap
  Sharpe lower bounds, Deflated Sharpe diagnostics on greedily selected
  non-overlapping OOS occurrences, and a run-local Benjamini-Yekutieli screen
  over the complete disclosed cluster family, including under-powered
  hypotheses;
- reuse of the ML Lab's actual prior, logistic, histogram-gradient-boosting and
  Extra Trees estimators on purged expanding folds as a separate supervised
  falsification layer;
- a content-hashed `PatternDiscoveryReport` bound to the exact dataset,
  configuration, feature manifest, split, candidates, gates, runtime versions,
  model scores and exact learned imputer/scaler/centroid/OOD fit state;
- a fail-closed pattern-to-strategy bridge that verifies report integrity,
  subject identity, current dataset identity, snapshot clock, provider lineage,
  gate vocabulary and absence of execution-authority mutations, while leaving
  full-experiment correction, calibrated novelty, shadow history and
  independent review open before any future governed memo rebuild;
- a lazy bridge preserving the historical root `market_intelligence.py`
  consumed by Macro / Central Banks.

It does **not** provide live event/news coverage, licensed L2/L3 market data,
historical point-in-time consensus, calibrated catalyst forecasts, proven alpha,
shadow-live evidence, durable decision-journal storage, portfolio mandate or
exposure integration, OMS/broker integration, or production promotion.

## V4 ML pattern-discovery contract

The Patterns view now runs estimators rather than presenting a cosmetic ML
label. It consumes only the inherited terminal OHLCV frame; the canonical
event/L2 fixture is never used as training history. With fewer than 180 usable
rows after feature warm-up and forward-label construction, it fits nothing and
returns `WAITING_DATA`.

Before feature construction, the engine verifies that the required entry and
adjustment fields are economically observable rather than merely present as
columns. Every eligible observation must have a complete provider-observed next
open. The price-adjustment contract must supply a provider-observed adjusted
close, a separately declared adjusted-close series, or a declared native
non-corporate-action series. A gateway-filled open, a close copied into
`adj_close`, an unverified raw close, or partial coverage of either required
field blocks the economic run. Observed high/low and volume extend the feature
set only when their coverage permits; they are not silently represented as
observed when a provider synthesized them.

Each row's `known_at` must be no later than the next observed open at which the
row could first influence a position. Revision identity remains part of the
dataset hash. An explicitly late row or a source/evaluation clock in the future
blocks the fit. Missing row-level known-at or revision metadata may still permit
a quarantined exploratory run, but can never pass PIT lineage or the strategic
bridge. This is a mechanical point-in-time eligibility check over the supplied
metadata, not independent verification of the provider's historical archive.

For a frame that passes those checks, the engine builds contemporaneous and
backward-looking return-shape, momentum, volatility, downside-risk,
trend-distance, drawdown, range, close-location, gap and, when coverage permits,
volume/liquidity features. Price geometry is put on the admissible adjustment
basis before fitting. Forward returns exist only in the label/outcome frame: a
close-of-bar observation enters at the next observed open and exits after the
declared horizon. The final chronological segment is run-locked as terminal OOS
and separated from selection by the complete entry-to-exit label span. Feature
eligibility, imputation, scaling, cluster-count selection, centroids, novelty
thresholds and conditional direction are fitted only before that purge.

Cluster count is chosen from a bounded range using training silhouette, which
does not inspect returns. Each discovered state fixes its UP/DOWN/NEUTRAL
direction from training outcomes, then receives a run-locked terminal-OOS
after-cost test. Evidence must be positive both absolutely and relative to the
same-direction matched-rest baseline. The displayed Sharpe interval is computed
on the complete chronological, zero-padded OOS strategy series with a
horizon-sized block bootstrap; its lower 95% bound remains a conservative
descriptive stability measure. Deflated Sharpe is computed separately on a
greedy sequence of OOS occurrences spaced by at least the forward horizon, so
overlapping labels are not counted as independent bets in that diagnostic.

One-sided p-values come from circularly shifting the fixed cluster mask across
the complete chronological OOS outcome series. Benjamini-Yekutieli adjustment
is then applied across every disclosed cluster, with an under-powered cluster
retained in the family as p=1. Both operations are explicitly **run-local
diagnostics**: cyclic invariance, stationarity and an independent global
experiment registry have not been established. Consequently, the FDR gate
remains `WAITING_EVIDENCE`; a qualifying cluster can be labelled only as a
run-local screened hypothesis. This release never emits an
`OOS_SUPPORTED_HYPOTHESIS` claim. White Reality Check, Hansen SPA, PBO or an
equivalent independently governed full-experiment analysis remains future
evidence, not an implied property of the local screen.

The current point is left `UNASSIGNED_OOD` when it breaches a q99 distance
boundary fitted on the training partition. That boundary and the displayed
proximity are train-fit novelty heuristics, not calibrated tail probabilities
or validated distribution-shift controls. The corresponding strategic OOD
gate therefore remains `WAITING_EVIDENCE` even when the point is assigned to a
cluster.

The separate supervised challenge invokes the existing ML Lab on the same
causal matrix with purged expanding folds, temporal calibration, drift checks
and baseline-versus-nonlinear comparison. In this integration it is explicitly
`CLASSIFICATION_DIAGNOSTIC_ONLY`: the legacy ML Lab economic screen uses a
synthetic class-return proxy, so its selected classification challenger cannot claim
economic promotion or shadow eligibility. Its leaderboard cannot override the
terminal OOS pattern test, promote itself or trade.

The session report never mutates the current `StrategicDecisionMemo`. The
Strategic Decision Office displays it as a separate addendum. Dataset subject,
provider/source symbol, per-row known-at and revision IDs are bound into the
dataset identity. A PIT gate marked pass means the supplied contract is
internally consistent, not that an external party verified the provider. A
report newer than the immutable snapshot is placed in `CLOCK_MISMATCH`; a
changed terminal frame is `STALE_DATASET`; incomplete known-at/revision
metadata is `WAITING_LINEAGE`; missing global experiment correction,
append-only shadow history or independent review is `WAITING_VALIDATION`.

The fail-closed bridge does not trust the report's headline eligibility alone.
It independently rejects any mutation granting autonomous trading or execution,
any order payload, removal of mandatory human review, or execution permission
on a candidate. Under the active policy it also rejects any injected
`OOS_SUPPORTED_HYPOTHESIS` state, unknown gates and any additional
strategic-admission gate that is not `PASS`, rather than allowing a legacy or
surplus gate to evade the current policy. Only a future enlarged governance
packet may produce a new memo identity and evidence root.

The content hash proves deterministic self-consistency and detects accidental
or post-run mutation inside the session; it is not an external signature,
provider attestation or authenticity proof. A production evidence passport
still requires authenticated identity, append-only durable storage and an
independently controlled signing key.

Deflated Sharpe, the block-bootstrap interval, the circular-shift result and the
BY-adjusted value are diagnostics, not proof of economic value. The
implementation deliberately keeps global multiple-testing, calibrated OOD,
forward shadow history and independent review gates open until their evidence
exists.

## V3 strategic decision contract

Research governance and strategic decision support are intentionally separate.
The `ResearchDecisionPacket` answers whether evidence is admissible and
reviewable. The `StrategicDecisionMemo` answers which research or monitoring
process action is currently defensible, what alternatives exist, which impacts
are priced or unpriced, what would invalidate the thesis, and who must review
it.

For the canonical fixture the valid process response is
`ACQUIRE_EVIDENCE`: prioritize licensed point-in-time events, entitled L2,
realized outcomes, chronological validation and shadow history. This is a real
strategic process decision, but it is not a preferred portfolio action. The
portfolio field remains `UNPRICED`, capital authority is absent,
`execution_allowed=false`, and `order_payload=null`.

Changing the decision lens or decision horizon creates a new deterministic memo
identity while preserving the exact research packet and evidence root. A human
may record a non-authorizing session disposition against an available process
option. In the current fixture UI, actor and role are self-asserted and therefore
stored as `SELF_ASSERTED_UNVERIFIED`; the records are hash chained but remain
explicitly session-scoped until authenticated identity and durable audited
storage are connected. Journal displays are partitioned by memo while the full
session export preserves the multi-memo chain and each record's own basis.

The governance V3 engine and policy have separate version identifiers. The
validation-run ID hashes its complete gate set, clocks and evidence root; the
decision-packet ID hashes the complete semantic packet. Strategic synthesis
rejects missing or surplus primary evidence, a mutated workspace basis, a
foreign governance assessment, or a memo that does not reproduce from the
supplied snapshot and packet.

## Research-readiness contract

The workspace evaluates one deterministic governance packet per snapshot. The
canonical fixture must resolve to `RESEARCH_ONLY`, `OBSERVE_ONLY` and
`WAITING_EVIDENCE`; `execution_allowed` is always `false`. A non-eligible
packet carries explicit blockers and shares the same SHA-256 evidence root as
its validation run. The interface exposes the packet ID, validation run,
quality matrix, gate reasons, scenario assumptions and evidence lineage.

Passing architecture, unit, integration or UI checks proves only that those
checks passed. It does not establish provider fitness, model validity, alpha,
shadow readiness, human approval or execution authorization.

The canonical fixture uses a `SNAPSHOT_AS_OF` replay clock: freshness ages are
prediction-time ages, not claims about wall-clock recency. A live adapter must
call the governance engine with its actual evaluation timestamp and satisfy the
active freshness and completeness policy. The UI labels this distinction in
the quality matrix.

## Data policy

Every feature must be reconstructible as known at prediction time. Required
timestamps include publication, first seen, ingestion, tradable, feature
computation, prediction, and data cutoff. A missing value stays null and carries
an uncertainty flag; the UI never silently replaces a missing provider with a
simulation.

The integrated fixture displays `SIMULATED` at the shell and panel level. An
inherited Quant Terminal price frame, when present, is shown as terminal
context only. It does not convert the catalyst, order-book, analogue or model
layers into live data.

The global decision-horizon control is limited to horizons actually present in
the snapshot (`10m`, `30m`, `1h`, `2h` in the canonical fixture). It drives the
strategic question, memo identity, review clock, selected forecast cards and
scenario-risk marker; it does not retrain a model or imply promotion.

## Model ladder

1. Unconditional empirical / naive baselines.
2. Interpretable linear, logistic and quantile models.
3. Strong tabular challengers.
4. Temporal challengers such as TFT, PatchTST, TimesNet or DeepLOB.
5. Gated multimodal fusion; cross-attention only after simpler fusion.
6. GNN, Hawkes, chart-vision and large MoE experiments behind research flags.

No level replaces the previous level without chronological OOS evidence,
calibration, multiple-testing controls where applicable, stability analysis and
shadow observation.

## Microstructure scope

Microstructure is an information-absorption sensor over seconds to minutes.
Queue imbalance and microprice can be computed from valid L1 quotes. Reliable
replenishment, add and cancellation intensities require sequenced L2/MBO
messages and must stay null in L1 mode. HMM regime probabilities, when added,
must be filtered or predicted as-of and refit inside each validation fold;
full-sample smoothed probabilities are prohibited.

## Validation

```bash
pytest -q tests/market_intelligence tests/test_institutional_router.py
python -m compileall -q market_intelligence app.py asset_class_router.py institutional_router.py
streamlit run scripts/market_intelligence_smoke_app.py
```

The canonical fixture must produce high catalyst collision, slightly negative
net catalyst pressure, a `negative_catalyst_absorption` candidate, a short
horizon no stronger than the medium horizon, and no unexplained-flow alarm when
known catalysts explain the measured move.

## Governance design anchors

The control-plane design is informed by current primary guidance on model-risk
governance, independent validation, risk-data lineage and explicit AI-risk
management:

- [Federal Reserve SR 26-2](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm)
- [Bank of England PRA SS1/23](https://www.bankofengland.co.uk/prudential-regulation/publication/2023/may/model-risk-management-principles-for-banks-ss)
- [BCBS 239 implementation guidance](https://www.bis.org/publications/implementation-principles-effective-risk-data-aggregation-and-risk-reporting-bcbs-239-principles)
- [NIST AI Risk Management Framework 1.0](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10)

These sources are design anchors only. This software has not been certified or
assessed as compliant with any regulatory or supervisory standard.

## Research basis

- A. C. MacKinlay, “Event Studies in Economics and Finance,” *JEL* (1997).
- R. Cont, A. Kukanov and S. Stoikov, “The Price Impact of Order Book Events,”
  *Journal of Financial Econometrics* (2014).
- M. D. Gould and J. Bonart, “Queue Imbalance as a One-Tick-Ahead Price
  Predictor in a Limit Order Book,” *Market Microstructure and Liquidity* (2016).
- Z. Zhang, S. Zohren and S. Roberts, “DeepLOB,” *IEEE TSP* (2019).
- D. H. Bailey et al., “The Probability of Backtest Overfitting,” *Journal of
  Computational Finance* (2017), with the [author manuscript](https://escholarship.org/uc/item/4w1110bb).
- D. H. Bailey and M. López de Prado, “The Deflated Sharpe Ratio,” *Journal of
  Portfolio Management* (2014), [working-paper record](https://doi.org/10.2139/ssrn.2460551).
- P. R. Hansen, “A Test for Superior Predictive Ability,” *Journal of Business
  & Economic Statistics* (2005), [bibliographic record](https://ideas.repec.org/a/bes/jnlbes/v23y2005p365-380.html).

These papers motivate baselines and research questions. They do not establish
that this implementation generates alpha on Quant Terminal data.
