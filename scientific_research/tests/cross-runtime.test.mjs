import test from 'node:test';
import assert from 'node:assert/strict';

import { executeCrossRuntimeChallenge } from '../dist/index.js';

function monthly(index) {
  const year = 2014 + Math.floor(index / 12);
  const month = index % 12 + 1;
  return `${year}-${String(month).padStart(2, '0')}-01`;
}

function release(index) {
  const year = 2014 + Math.floor((index + 1) / 12);
  const month = (index + 1) % 12 + 1;
  return `${year}-${String(month).padStart(2, '0')}-20`;
}

function rows(real) {
  return Array.from({ length: 132 }, (_, index) => ({
    period_start_date: monthly(index),
    value: 100 + 0.04 * index + (real ? 2.2 : 1.5) * Math.sin(index / (real ? 5.5 : 7)) + 0.3 * Math.cos(index / 2.9),
    realtime_start_date: release(index),
  }));
}

test('independent TypeScript engine executes nine causal OOS screens without promotion', () => {
  const markets = ['US', 'GB', 'JP'];
  const seriesMatrix = Object.fromEntries(markets.map((market) => [market, {
    label: market,
    real_series_id: `R${market}`,
    nominal_series_id: `N${market}`,
  }]));
  const challenge = {
    challenge_id: 'XRV-fixtured',
    challenge_fingerprint: 'sha256:fixture',
    replication_id: 'IRP-fixture',
    snapshot_id: 'ALFREDIR-fixture',
    snapshot_fingerprint: 'sha256:snapshot',
    event_time_support_policy: 'STRICT_RELEASE_EVENT_TIME_KEEP_LATEST_PERIOD_PER_CO_RELEASE_EXCLUDE_NON_ADVANCING_BACKFILLS',
    markets,
    measurement_variants: [
      { variant_id: 'REAL_EER_LOG', label: 'real', formula: 'log(real)' },
      { variant_id: 'NOMINAL_EER_LOG', label: 'nominal', formula: 'log(nominal)' },
      { variant_id: 'RELATIVE_PRICE_WEDGE', label: 'wedge', formula: 'log(real)-log(nominal)' },
    ],
    series_matrix: seriesMatrix,
    train_fraction: 0.7,
    forecast_horizon: 1,
    min_common_rows: 40,
    multiplicity_policy: 'HOLM_BONFERRONI_ACROSS_ALL_MARKET_MEASUREMENT_TESTS',
    engine_source_fingerprint: 'sha256:engine',
    production_status: 'RESEARCH_ONLY',
    automatic_promotion_authorized: false,
  };
  const series = {};
  for (const market of markets) {
    series[`R${market}`] = rows(true);
    series[`N${market}`] = rows(false);
  }
  const result = executeCrossRuntimeChallenge(challenge, series);
  assert.equal(result.result_count, 9);
  assert.equal(result.production_status, 'RESEARCH_ONLY');
  assert.equal(result.automatic_promotion_authorized, false);
  assert.equal(result.investigator_independent, false);
  assert.equal(result.implementation_separation, 'SEPARATE_TYPESCRIPT_NODE_CODEPATH');
  assert.equal(result.results.every((row) => row.test_size > 9), true);
  assert.equal(result.results.every((row) => row.forecast_comparison.holm_family_size === 9), true);
});

test('independent engine rejects production promotion', () => {
  assert.throws(() => executeCrossRuntimeChallenge({
    challenge_id: 'X', challenge_fingerprint: 'sha256:x', replication_id: 'R', snapshot_id: 'S', snapshot_fingerprint: 'F',
    event_time_support_policy: 'P', markets: [], measurement_variants: [], series_matrix: {}, train_fraction: 0.7,
    forecast_horizon: 1, min_common_rows: 40, multiplicity_policy: 'M', engine_source_fingerprint: 'E',
    production_status: 'PRODUCTION', automatic_promotion_authorized: true,
  }, {}), /lock is not intact/);
});
