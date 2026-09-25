# Market Intelligence — Catalyst × Microstructure

## Boundary

This package is an institutional research workspace. It is not a live trading
engine, an HFT execution stack, an LLM opinion generator, or a source of
unqualified BUY/SELL labels.

The first integrated release is a foundation release. It provides:

- an autonomous `?workspace=market-intelligence` route;
- thirteen connected research views;
- point-in-time typed contracts and timestamp-chain validation;
- transparent surprise, novelty, collision, OFI, queue-imbalance and
  microprice baselines;
- empirical distribution forecasts with monotone quantiles;
- a deterministic Fed × NVDA collision fixture;
- explicit provider, calibration, drift and promotion states;
- a lazy bridge preserving the historical root `market_intelligence.py`
  consumed by Macro / Central Banks.

It does **not** provide live event/news coverage, licensed L2/L3 market data,
historical point-in-time consensus, calibrated catalyst forecasts, proven alpha,
shadow-live evidence, OMS/broker integration, or production promotion.

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

## Research basis

- A. C. MacKinlay, “Event Studies in Economics and Finance,” *JEL* (1997).
- R. Cont, A. Kukanov and S. Stoikov, “The Price Impact of Order Book Events,”
  *Journal of Financial Econometrics* (2014).
- M. D. Gould and J. Bonart, “Queue Imbalance as a One-Tick-Ahead Price
  Predictor in a Limit Order Book,” *Market Microstructure and Liquidity* (2016).
- Z. Zhang, S. Zohren and S. Roberts, “DeepLOB,” *IEEE TSP* (2019).

These papers motivate baselines and research questions. They do not establish
that this implementation generates alpha on Quant Terminal data.
