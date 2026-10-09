# Correlation Intelligence V4.1.0

Status: `RESEARCH_ONLY`
Scope: Correlation Matrix workspace and its Multi-Force Dependency sub-workspace.

## Quantitative changes

- Temporal Graphical Lasso uses expanding forward folds, out-of-sample Gaussian likelihood,
  train-only standardisation/PCA residualisation, explicit convergence events and disclosed
  Ledoit-Wolf fallback.
- Regularized Tyler correlation adds a heavy-tail/outlier-resistant signed estimator.
- Distance correlation adds a nonlinear, non-signed diagnostic. It is explicitly ineligible
  for covariance, optimisation or hedge direction.
- Covariance champion/challenger validation fixes the universe ex ante and compares
  Ledoit-Wolf, OAS, EWMA, POET-style, Factor-GLasso and RMT over 20 non-overlapping OOS folds.
  Top-two uncertainty uses a paired circular moving-block bootstrap and is not labelled as a
  familywise test across all challengers.
- Directional and spectral connectedness publish only when a VAR candidate passes stability,
  residual covariance, adjusted multivariate Portmanteau whiteness, finite FEVD and row-sum
  gates. BIC is applied only among admissible lags; otherwise output is suppressed.
- Regime correlation uses 20-day market trend and 20-day volatility relative to its expanding
  median. No regime is assigned before both inputs mature. Intervals use moving-block bootstrap.
- Lead/lag selection, interval and max-stat null share an AR(1)-prewhitened estimand. Raw lag
  correlation remains descriptive and no causal claim is made.
- Survival Clayton and survival Gumbel challengers distinguish lower- and upper-tail asymmetry.
- Cluster consensus uses Ledoit-Wolf average-linkage moving-block bootstrap.
- Allocation challenger compares 1/N, inverse volatility, HRP and long-only minimum variance
  on chronological, non-overlapping OOS blocks with explicit turnover cost and ex-ante universe.
- Factor HAC tests use ex-ante factor priority, factor-only collinearity screening and
  Benjamini-Hochberg q-values.

## Integrity and provenance

- Requested-period depth, observed-grid completeness, relative history depth and
  leading/internal/trailing missingness are reported separately.
- Research Pack ZIPs are deterministic. Every exported CSV has a canonical DataFrame hash,
  exact CSV SHA-256, byte count and shape in `manifest.json`.
- Partial correlations are not projected to PSD: they remain conditional-association
  diagnostics and have no covariance/portfolio authority.
- Global JARVIS BUY/SELL labels are explicitly outside this workspace's authority.

## Verified release gates

- `67 passed` in `tests/correlation_matrix`.
- `13 passed` for institutional routing and contextual section-agent UI.
- Python compilation and `git diff --check` pass.
- Default NVDA 2Y run: finite/symmetric/unit-diagonal matrices; every matrix that requires PSD
  passes its eigenvalue gate; Temporal Graphical Lasso converges without fallback; cluster and
  allocation bootstraps/folds complete; Research Pack is byte-for-byte reproducible and every
  artifact hash verifies.

## Boundaries

- The yfinance path is a compatibility fallback, not point-in-time institutional market data.
- Historical constituents can contain survivorship bias unless the caller injects a governed
  point-in-time universe.
- Option-implied correlation remains inactive without an injected option/index variance feed.
- All allocation, hedge, factor, break and connectedness outputs are research diagnostics.
  No order generation or execution authority is provided.
