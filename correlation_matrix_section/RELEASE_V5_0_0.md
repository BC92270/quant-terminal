# Correlation Intelligence V5.0.0

Status: `RESEARCH_ONLY`  
Scope: Correlation Matrix workspace, institutional UX and governed data/validation adapters.

## Institutional workspace

- The section is now an eleven-desk command center with a responsive visual system, compact
  market tape, capability states and explicit research/no-order boundaries.
- Desk routing is lazy: only the active desk renders. Universe/model controls are transactional
  inside a form, so editing a field no longer rebuilds every chart.
- Heatmaps use a dark, accessible institutional palette, hover-first rendering for wide matrices
  and readable annotations only on compact universes.

## Six-axis completion

1. **Point-in-time data:** externally injected histories can pass a strict provider/as-of/
   available-at/revision/license contract. Free Yahoo/Stooq snapshots remain explicitly
   `FREE_RESEARCH_NOT_POINT_IN_TIME`.
2. **Persistent compute:** a bounded DuckDB catalog (SQLite fallback), Arrow IPC frames,
   checksummed analysis bundles and optional Redis hot tier persist work across reruns.
3. **Option-implied correlation:** the variance-identity, history, term-structure and skew
   contracts remain available; a strict public Cboe index-history adapter accepts only
   user-verified symbols. Licensed constituent option surfaces remain external.
4. **Dynamic heavy-tail dependence:** bounded-influence Student-t GARCH filters feed constrained
   DCC(1,1), with PCA factor reconstruction for wide panels, positive-definite publication gates
   and a rolling Student-t copula versus Gaussian challenger.
5. **Asynchronous intraday dependence:** Hayashi-Yoshida correlation matrices, clock-time
   lead/lag scans with circular-shift max-statistic inference and Epps-effect curves accept
   timestamped returns. Daily closes are never silently treated as intraday events.
6. **Validation surveillance:** recent structure is compared with a strictly prior baseline;
   chronological calibration folds and a persistent ledger monitor drift. Independent validation
   is never self-certified and requires an external evidence contract.

## Reproducibility and governance

- Research packs now include correlation-drift links and the rolling calibration ledger plus
  data/cache/validation metadata.
- Free fallbacks have no production-data authority, no institutional SLA and no vintage guarantee.
- Dynamic, tail, allocation, factor, network, hedge and break outputs remain diagnostics only.
- All numerical engines fail closed when data depth, optimization, stationarity, finiteness or
  positive-definiteness gates fail.

## Verification gates

- `80 passed` in `tests/correlation_matrix` on the V5 dependency set.
- The 17-asset reference engine completes in about 10 seconds after vectorizing the 500-sample
  network/regime resampling paths and locking Factor-GLasso alpha at the first chronological
  outer origin; network bootstrap depth and model coverage were not reduced.
- The five-asset robust GARCH-DCC reference completes in about 6 seconds after removing a
  redundant per-date eigendecomposition; every published path still passes the full finite and
  positive-definite gate. The 199-sample HY max-stat lead/lag bootstrap completes in about
  0.4 seconds on a 500-event asynchronous reference, with numerical equivalence to the direct
  interval-overlap implementation.
- Python compilation and `git diff --check` pass.
- Persistent cache round-trip/checksum rejection, point-in-time contracts, strict-prior drift,
  chronological calibration, idempotent validation history, HY/Epps/lead-lag, GARCH-DCC,
  factor reduction and dynamic t-copula behavior have dedicated tests.

## Production boundaries

- A complete survivorship-safe, point-in-time daily/intraday archive is not available free.
- Universe-specific live option surfaces and exchange constituent weights require licensed data.
- Free intraday sources provide short research snapshots, not a governed trade/quote archive.
- Independent model validation requires a real reviewer and external evidence; application code
  cannot grant that status to itself.
