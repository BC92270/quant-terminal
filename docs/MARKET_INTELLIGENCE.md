# Market Intelligence — Catalyst × Microstructure

## Boundary

This package is an institutional research workspace. It is not a live trading
engine, an HFT execution stack, an LLM opinion generator, or a source of
unqualified BUY/SELL labels.

The V2 integrated release is an institutional control-plane release. It
provides:

- an autonomous `?workspace=market-intelligence` route;
- thirteen connected research views;
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
- an exportable JSON evidence dossier containing the decision, ledger, model
  registry, risk envelope, canonical source contracts and scenario definitions
  required for deterministic replay;
- a two-level institutional workflow (`OBSERVE → EXPLAIN → SYNTHESIZE → GOVERN`)
  while preserving all thirteen views;
- a lazy bridge preserving the historical root `market_intelligence.py`
  consumed by Macro / Central Banks.

It does **not** provide live event/news coverage, licensed L2/L3 market data,
historical point-in-time consensus, calibrated catalyst forecasts, proven alpha,
shadow-live evidence, OMS/broker integration, or production promotion.

## V2 decision contract

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

The global focus-horizon control is limited to horizons actually present in
the snapshot (`10m`, `30m`, `1h`, `2h` in the canonical fixture). It drives the
selected forecast cards, table marker and scenario-risk marker; it does not
retrain a model or imply promotion.

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

These papers motivate baselines and research questions. They do not establish
that this implementation generates alpha on Quant Terminal data.
