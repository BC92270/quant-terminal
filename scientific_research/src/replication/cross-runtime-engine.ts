export const CROSS_RUNTIME_ENGINE_PROTOCOL = 'SRB_TYPESCRIPT_REPLICATION_ENGINE_V1';

export interface CanonicalReleaseRow {
  period_start_date: string;
  value: number;
  realtime_start_date: string;
}

export interface ChallengeMarket {
  label: string;
  real_series_id: string;
  nominal_series_id: string;
}

export interface ChallengeMeasurement {
  variant_id: string;
  label: string;
  formula: string;
}

export interface CrossRuntimeChallenge {
  challenge_id: string;
  challenge_fingerprint: string;
  replication_id: string;
  snapshot_id: string;
  snapshot_fingerprint: string;
  event_time_support_policy: string;
  markets: string[];
  measurement_variants: ChallengeMeasurement[];
  series_matrix: Record<string, ChallengeMarket>;
  train_fraction: number;
  forecast_horizon: number;
  min_common_rows: number;
  multiplicity_policy: string;
  engine_source_fingerprint: string;
  production_status: string;
  automatic_promotion_authorized: boolean;
}

interface AlignedRow {
  period_start_date: string;
  available_at: string;
  real_value: number;
  nominal_value: number;
  real_first_release: string;
  nominal_first_release: string;
}

interface ExcludedAlignedRow extends AlignedRow {
  exclusion_reason: string;
  selected_period_start_date?: string;
  last_included_period_start_date?: string;
}

interface MetricSet {
  RMSE: number;
  MAE: number;
  DIRECTIONAL_ACCURACY: number;
}

interface ScoredSeries {
  split: number;
  train: number[];
  test: number[];
  candidate_metrics: MetricSet;
  baseline_metrics: Record<string, MetricSet>;
  deltas: Record<string, Record<string, number>>;
  fitted: Record<string, number>;
  previous: number[];
  candidate_predictions: number[];
  candidate_errors: number[];
  baseline_predictions: Record<string, number[]>;
  baseline_errors: Record<string, number[]>;
}

function assertFinite(value: number, label: string): void {
  if (!Number.isFinite(value)) throw new Error(`${label} must be finite.`);
}

function assertIsoDate(value: string, label: string): void {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(Date.parse(`${value}T00:00:00Z`))) {
    throw new Error(`${label} is not a valid ISO date: ${value}`);
  }
}

function pythonUtcMidnight(value: string): string {
  assertIsoDate(value, 'release timestamp');
  return `${value}T00:00:00+00:00`;
}

function mean(values: number[]): number {
  if (values.length === 0) throw new Error('Cannot compute a mean over an empty array.');
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function roundTo(value: number, digits: number): number {
  assertFinite(value, 'Rounded value');
  const factor = 10 ** digits;
  return Math.round((value + Number.EPSILON * Math.sign(value)) * factor) / factor;
}

function fitAr1(train: number[]): { intercept: number; phi: number } {
  const x = train.slice(0, -1);
  const y = train.slice(1);
  if (x.length < 3) throw new Error('Insufficient training pairs for AR(1)/OU fit.');
  const xbar = mean(x);
  const ybar = mean(y);
  const denominator = x.reduce((total, value) => total + (value - xbar) ** 2, 0);
  if (denominator <= 1e-15) return { intercept: ybar, phi: 0 };
  const numerator = x.reduce(
    (total, value, index) => total + (value - xbar) * ((y[index] ?? 0) - ybar),
    0,
  );
  const phi = numerator / denominator;
  return { intercept: ybar - phi * xbar, phi };
}

function metrics(actual: number[], predicted: number[], previous: number[]): MetricSet {
  if (actual.length === 0 || actual.length !== predicted.length || actual.length !== previous.length) {
    throw new Error('Metric arrays must have equal non-zero length.');
  }
  const errors = actual.map((value, index) => value - (predicted[index] ?? 0));
  const rmse = Math.sqrt(mean(errors.map((value) => value ** 2)));
  const mae = mean(errors.map((value) => Math.abs(value)));
  const hits = actual.map((value, index) => {
    const prior = previous[index] ?? 0;
    const prediction = predicted[index] ?? 0;
    const actualDirection = value > prior ? 1 : value < prior ? -1 : 0;
    const predictedDirection = prediction > prior ? 1 : prediction < prior ? -1 : 0;
    return actualDirection === predictedDirection ? 1 : 0;
  });
  return {
    RMSE: roundTo(rmse, 10),
    MAE: roundTo(mae, 10),
    DIRECTIONAL_ACCURACY: roundTo(mean(hits), 6),
  };
}

function scoreSeries(values: number[], trainFraction: number): ScoredSeries {
  if (values.length < 40) throw new Error('At least 40 chronological observations are required.');
  values.forEach((value, index) => assertFinite(value, `Series value ${index}`));
  if (!(trainFraction > 0 && trainFraction < 1)) throw new Error('train_fraction must be between zero and one.');
  const split = Math.max(20, Math.min(values.length - 10, Math.floor(values.length * trainFraction)));
  const train = values.slice(0, split);
  const test = values.slice(split);
  const fitted = fitAr1(train);
  const previous = [train[train.length - 1] ?? 0, ...test.slice(0, -1)];
  const candidatePredictions = previous.map((value) => fitted.intercept + fitted.phi * value);
  const randomWalkPredictions = [...previous];
  const trainingMeanPredictions = Array(test.length).fill(mean(train)) as number[];
  const candidateErrors = test.map((value, index) => value - (candidatePredictions[index] ?? 0));
  const randomWalkErrors = test.map((value, index) => value - (randomWalkPredictions[index] ?? 0));
  const trainingMeanErrors = test.map((value, index) => value - (trainingMeanPredictions[index] ?? 0));
  const candidateMetrics = metrics(test, candidatePredictions, previous);
  const randomWalkMetrics = metrics(test, randomWalkPredictions, previous);
  const trainingMeanMetrics = metrics(test, trainingMeanPredictions, previous);
  const deltas: Record<string, Record<string, number>> = {};
  for (const [name, baseline] of [
    ['Random Walk / Last Observation', randomWalkMetrics],
    ['Training Mean', trainingMeanMetrics],
  ] as const) {
    deltas[name] = {
      RMSE_IMPROVEMENT_PCT: baseline.RMSE > 0
        ? roundTo(100 * (baseline.RMSE - candidateMetrics.RMSE) / baseline.RMSE, 4)
        : 0,
      MAE_IMPROVEMENT_PCT: baseline.MAE > 0
        ? roundTo(100 * (baseline.MAE - candidateMetrics.MAE) / baseline.MAE, 4)
        : 0,
    };
  }
  const fittedValues: Record<string, number> = { intercept: fitted.intercept, phi: fitted.phi };
  if (fitted.phi > 0 && fitted.phi < 1) {
    fittedValues.kappa_implied = -Math.log(fitted.phi);
    if (Math.abs(1 - fitted.phi) > 1e-12) fittedValues.long_run_mean = fitted.intercept / (1 - fitted.phi);
  }
  return {
    split,
    train,
    test,
    candidate_metrics: candidateMetrics,
    baseline_metrics: {
      'Random Walk / Last Observation': randomWalkMetrics,
      'Training Mean': trainingMeanMetrics,
    },
    deltas,
    fitted: fittedValues,
    previous,
    candidate_predictions: candidatePredictions,
    candidate_errors: candidateErrors,
    baseline_predictions: {
      'Random Walk / Last Observation': randomWalkPredictions,
      'Training Mean': trainingMeanPredictions,
    },
    baseline_errors: {
      'Random Walk / Last Observation': randomWalkErrors,
      'Training Mean': trainingMeanErrors,
    },
  };
}

function strictEventTimeSupport(rows: AlignedRow[]): { included: AlignedRow[]; excluded: ExcludedAlignedRow[] } {
  const grouped = new Map<string, AlignedRow[]>();
  for (const row of rows) {
    assertIsoDate(row.period_start_date, 'period_start_date');
    assertIsoDate(row.available_at, 'available_at');
    if (row.available_at < row.period_start_date) throw new Error('A replication row is available before its reference period.');
    const bucket = grouped.get(row.available_at) ?? [];
    bucket.push(row);
    grouped.set(row.available_at, bucket);
  }
  const included: AlignedRow[] = [];
  const excluded: ExcludedAlignedRow[] = [];
  let lastPeriod = '';
  for (const availableAt of [...grouped.keys()].sort()) {
    const eventRows = [...(grouped.get(availableAt) ?? [])].sort((a, b) => a.period_start_date.localeCompare(b.period_start_date));
    const selected = eventRows[eventRows.length - 1];
    if (selected === undefined) continue;
    for (const row of eventRows.slice(0, -1)) {
      excluded.push({
        ...row,
        exclusion_reason: 'CO_RELEASE_KEEP_LATEST_REFERENCE_PERIOD',
        selected_period_start_date: selected.period_start_date,
      });
    }
    if (lastPeriod !== '' && selected.period_start_date <= lastPeriod) {
      excluded.push({
        ...selected,
        exclusion_reason: 'NON_ADVANCING_BACKFILL',
        last_included_period_start_date: lastPeriod,
      });
      continue;
    }
    included.push(selected);
    lastPeriod = selected.period_start_date;
  }
  const labels = included.map((row) => row.available_at);
  const periods = included.map((row) => row.period_start_date);
  if (new Set(labels).size !== labels.length || labels.some((value, index) => index > 0 && value <= (labels[index - 1] ?? ''))) {
    throw new Error('Event-time support is not strictly increasing and unique.');
  }
  if (new Set(periods).size !== periods.length || periods.some((value, index) => index > 0 && value <= (periods[index - 1] ?? ''))) {
    throw new Error('Event-time support does not preserve advancing reference periods.');
  }
  return { included, excluded };
}

function valuesForVariant(variantId: string, realValues: number[], nominalValues: number[]): number[] {
  if (variantId === 'REAL_EER_LOG') return realValues.map((value) => Math.log(value));
  if (variantId === 'NOMINAL_EER_LOG') return nominalValues.map((value) => Math.log(value));
  if (variantId === 'RELATIVE_PRICE_WEDGE') {
    return realValues.map((value, index) => Math.log(value) - Math.log(nominalValues[index] ?? Number.NaN));
  }
  throw new Error(`Unsupported measurement variant: ${variantId}`);
}

// Numerical Recipes erfc approximation. It is intentionally independent from
// Python's math.erfc and is compared under a tight declared tolerance.
function erfc(value: number): number {
  const z = Math.abs(value);
  const t = 1 / (1 + 0.5 * z);
  const polynomial = t * Math.exp(
    -z * z - 1.26551223 + t * (
      1.00002368 + t * (
        0.37409196 + t * (
          0.09678418 + t * (
            -0.18628806 + t * (
              0.27886807 + t * (
                -1.13520398 + t * (
                  1.48851587 + t * (-0.82215223 + t * 0.17087277)
                )
              )
            )
          )
        )
      )
    ),
  );
  return value >= 0 ? polynomial : 2 - polynomial;
}

function pairedForecastTest(candidateErrors: number[], baselineErrors: number[]): Record<string, unknown> {
  if (candidateErrors.length !== baselineErrors.length || candidateErrors.length < 8) {
    return {
      method: 'DIEBOLD_MARIANO_NORMAL_APPROX_H1',
      status: 'INSUFFICIENT_OBSERVATIONS',
      sample_size: Math.min(candidateErrors.length, baselineErrors.length),
    };
  }
  const differential = candidateErrors.map((candidate, index) => (baselineErrors[index] ?? 0) ** 2 - candidate ** 2);
  const meanDifference = mean(differential);
  const variance = differential.length > 1
    ? differential.reduce((total, value) => total + (value - meanDifference) ** 2, 0) / (differential.length - 1)
    : 0;
  let statistic: number;
  let pValue: number;
  if (variance <= 0) {
    statistic = meanDifference === 0 ? 0 : Math.sign(meanDifference) * Number.POSITIVE_INFINITY;
    pValue = meanDifference === 0 ? 1 : 0;
  } else {
    const raw = meanDifference / Math.sqrt(variance / differential.length);
    statistic = raw * Math.sqrt((differential.length - 1) / differential.length);
    pValue = erfc(Math.abs(statistic) / Math.sqrt(2));
  }
  return {
    method: 'DIEBOLD_MARIANO_NORMAL_APPROX_H1',
    status: 'COMPUTED',
    sample_size: differential.length,
    mean_squared_loss_advantage: roundTo(meanDifference, 12),
    statistic: Number.isFinite(statistic) ? roundTo(statistic, 8) : statistic,
    p_value_two_sided: roundTo(Math.max(0, Math.min(1, pValue)), 10),
    direction: meanDifference > 0 ? 'CANDIDATE_BETTER' : meanDifference < 0 ? 'RANDOM_WALK_BETTER' : 'TIE',
    caveat: 'Normal approximation with horizon one; multiplicity is controlled separately with Holm-Bonferroni.',
  };
}

function applyHolm(results: Array<Record<string, unknown>>): void {
  const eligible: Array<{ index: number; pValue: number }> = [];
  results.forEach((result, index) => {
    const comparison = result.forecast_comparison as Record<string, unknown> | undefined;
    if (comparison?.status === 'COMPUTED') eligible.push({ index, pValue: Number(comparison.p_value_two_sided ?? 1) });
  });
  eligible.sort((a, b) => a.pValue - b.pValue);
  let running = 0;
  const total = eligible.length;
  eligible.forEach((item, rankIndex) => {
    const adjusted = Math.min(1, (total - rankIndex) * item.pValue);
    running = Math.max(running, adjusted);
    const result = results[item.index];
    if (result === undefined) return;
    const comparison = { ...(result.forecast_comparison as Record<string, unknown>) };
    comparison.holm_adjusted_p_value = roundTo(running, 10);
    comparison.holm_family_size = total;
    comparison.candidate_better_after_holm_5pct = comparison.direction === 'CANDIDATE_BETTER' && running <= 0.05;
    result.forecast_comparison = comparison;
  });
}

function roundedArray(values: number[]): number[] {
  return values.map((value) => roundTo(value, 12));
}

function roundedFitted(values: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [key, value] of Object.entries(values)) if (Number.isFinite(value)) out[key] = roundTo(value, 10);
  return out;
}

export function executeCrossRuntimeChallenge(
  challenge: CrossRuntimeChallenge,
  series: Record<string, CanonicalReleaseRow[]>,
): Record<string, unknown> {
  if (challenge.forecast_horizon !== 1) throw new Error('The TypeScript verifier supports horizon one only.');
  if (challenge.production_status !== 'RESEARCH_ONLY' || challenge.automatic_promotion_authorized !== false) {
    throw new Error('Cross-runtime production/promotion lock is not intact.');
  }
  const results: Array<Record<string, unknown>> = [];
  for (const market of challenge.markets) {
    const matrix = challenge.series_matrix[market];
    if (matrix === undefined) throw new Error(`Missing series matrix for market ${market}.`);
    const realRows = series[matrix.real_series_id];
    const nominalRows = series[matrix.nominal_series_id];
    if (realRows === undefined || nominalRows === undefined) throw new Error(`Missing canonical series for market ${market}.`);
    const realIndex = new Map(realRows.map((row) => [row.period_start_date, row]));
    const nominalIndex = new Map(nominalRows.map((row) => [row.period_start_date, row]));
    const commonPeriods = [...realIndex.keys()].filter((period) => nominalIndex.has(period)).sort();
    if (commonPeriods.length < challenge.min_common_rows) throw new Error(`${market} has insufficient common rows.`);
    const aligned = commonPeriods.map((period): AlignedRow => {
      const real = realIndex.get(period);
      const nominal = nominalIndex.get(period);
      if (real === undefined || nominal === undefined) throw new Error(`Alignment failed for ${market} ${period}.`);
      if (!(real.value > 0) || !(nominal.value > 0)) throw new Error(`Non-positive series value for ${market} ${period}.`);
      return {
        period_start_date: period,
        available_at: real.realtime_start_date >= nominal.realtime_start_date ? real.realtime_start_date : nominal.realtime_start_date,
        real_value: real.value,
        nominal_value: nominal.value,
        real_first_release: real.realtime_start_date,
        nominal_first_release: nominal.realtime_start_date,
      };
    });
    const support = strictEventTimeSupport(aligned);
    if (support.included.length < challenge.min_common_rows) throw new Error(`${market} has insufficient causal event-time rows.`);
    const releaseDates = support.included.map((row) => row.available_at);
    const realValues = support.included.map((row) => row.real_value);
    const nominalValues = support.included.map((row) => row.nominal_value);
    const coReleaseExcluded = support.excluded.filter((row) => row.exclusion_reason === 'CO_RELEASE_KEEP_LATEST_REFERENCE_PERIOD').length;
    const backfillExcluded = support.excluded.filter((row) => row.exclusion_reason === 'NON_ADVANCING_BACKFILL').length;
    for (const variant of challenge.measurement_variants) {
      const values = valuesForVariant(variant.variant_id, realValues, nominalValues);
      const scored = scoreSeries(values, challenge.train_fraction);
      const splitDate = releaseDates[scored.split];
      const randomWalkErrors = roundedArray(scored.baseline_errors['Random Walk / Last Observation'] ?? []);
      const candidateErrors = roundedArray(scored.candidate_errors);
      const randomWalkDelta = scored.deltas['Random Walk / Last Observation']?.RMSE_IMPROVEMENT_PCT ?? 0;
      const trainingMeanDelta = scored.deltas['Training Mean']?.RMSE_IMPROVEMENT_PCT ?? 0;
      const verdict = randomWalkDelta >= 1 && trainingMeanDelta >= 0 ? 'PROMISING_OOS' : 'NO_OOS_IMPROVEMENT';
      results.push({
        market,
        market_label: matrix.label,
        variant_id: variant.variant_id,
        variant_label: variant.label,
        formula: variant.formula,
        real_series_id: matrix.real_series_id,
        nominal_series_id: matrix.nominal_series_id,
        event_time_support_policy: challenge.event_time_support_policy,
        raw_common_row_count: aligned.length,
        co_release_excluded_count: coReleaseExcluded,
        non_advancing_backfill_excluded_count: backfillExcluded,
        excluded_support_rows: support.excluded,
        row_count: values.length,
        verdict,
        train_size: scored.split,
        test_size: scored.test.length,
        split_timestamp: splitDate === undefined ? '' : pythonUtcMidnight(splitDate),
        candidate_metrics: scored.candidate_metrics,
        baseline_metrics: scored.baseline_metrics,
        deltas_vs_baseline: scored.deltas,
        fitted_parameters: roundedFitted(scored.fitted),
        forecast_origin_timestamps: releaseDates.slice(scored.split - 1, -1).map(pythonUtcMidnight),
        forecast_timestamps: releaseDates.slice(scored.split).map(pythonUtcMidnight),
        actual_values: roundedArray(scored.test),
        candidate_predictions: roundedArray(scored.candidate_predictions),
        candidate_errors: candidateErrors,
        baseline_predictions: Object.fromEntries(Object.entries(scored.baseline_predictions).map(([key, value]) => [key, roundedArray(value)])),
        baseline_errors: Object.fromEntries(Object.entries(scored.baseline_errors).map(([key, value]) => [key, roundedArray(value)])),
        forecast_comparison: pairedForecastTest(candidateErrors, randomWalkErrors),
        production_status: 'RESEARCH_ONLY',
      });
    }
  }
  applyHolm(results);
  const promising = results.filter((row) => row.verdict === 'PROMISING_OOS').length;
  const noImprovement = results.filter((row) => row.verdict === 'NO_OOS_IMPROVEMENT').length;
  const outcome = noImprovement === results.length
    ? 'CONSISTENT_NO_OOS_IMPROVEMENT'
    : promising === results.length
      ? 'CONSISTENT_PROMISING_REQUIRES_EXTERNAL_REVIEW'
      : 'MIXED_REPLICATION_EVIDENCE';
  return {
    engine_protocol_version: CROSS_RUNTIME_ENGINE_PROTOCOL,
    challenge_id: challenge.challenge_id,
    challenge_fingerprint: challenge.challenge_fingerprint,
    replication_id: challenge.replication_id,
    snapshot_id: challenge.snapshot_id,
    snapshot_fingerprint: challenge.snapshot_fingerprint,
    engine_source_fingerprint: challenge.engine_source_fingerprint,
    implementation_separation: 'SEPARATE_TYPESCRIPT_NODE_CODEPATH',
    investigator_independent: false,
    result_count: results.length,
    promising_result_count: promising,
    no_improvement_result_count: noImprovement,
    replication_outcome: outcome,
    results,
    production_status: 'RESEARCH_ONLY',
    automatic_promotion_authorized: false,
  };
}
