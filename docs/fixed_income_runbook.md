# Fixed Income V8 — Industrialization Runbook

## Purpose

This runbook defines how to validate, operate, deploy and recover the fixed-income and credit workstation. The Streamlit interface is an adapter. Pure calculations, data controls and operational services live in the fixed_income package.

## Architecture

- fixed_income/contracts.py: units, classifications and validation reports.
- fixed_income/analytics: refinancing and constrained portfolio engines.
- fixed_income/research: decision diagnostics and point-in-time leakage audit.
- fixed_income/data: quality gates and vintage-preserving SQLite storage.
- fixed_income/services: bounded background jobs, structured logs and health probes.
- fixed_income/governance: model registry and tamper-evident audit trail.
- fixed_income_credit.py: backward-compatible Streamlit facade.
- scripts/validate_fixed_income.py: fail-closed release gate.
- tests/test_fixed_income_*.py: characterization, unit, integration and operational tests.

## Data classifications

Every production input must be assigned one of the following states:

- observed: directly sourced public observation;
- licensed: supplied under an approved data license;
- analyst: manually entered and owned by a named analyst;
- derived: calculated from identified upstream inputs;
- illustrative: generated only for demonstration or scenario design.

Illustrative values must never be silently substituted for missing observed data.

## Unit conventions

- Decimal rates are stored as fractions, for example 0.05 for five percent.
- Fields ending with _pct contain percentage points, for example 5.0.
- Fields ending with _bp contain basis points, for example 125.
- Money values require an ISO three-letter currency.
- Observation time, availability time and decision time are distinct fields.

## Local validation

Run the following gates before any review:

1. python -m compileall -q fixed_income
2. python -m py_compile fixed_income_credit.py
3. python scripts/validate_fixed_income.py
4. pytest -q tests/test_fixed_income_*.py --disable-warnings

A release is rejected if any command fails.

## Point-in-time policy

The market_observations table preserves observation time, publication time and vintage identifier. Research queries must use an explicit decision timestamp. Data with an availability timestamp after the decision timestamp is ineligible.

Revisions are not overwritten by a later value. A new vintage is inserted and selected only when it was available at the requested decision time.

## Model change protocol

Every material model change requires:

1. a unique model version;
2. an owner;
3. characterization results against the prior version;
4. an independent validation record;
5. known limitations and challenger evidence;
6. approval status in the model registry;
7. a release event in the audit trail.

Statuses are DEVELOPMENT, VALIDATION, APPROVED and RETIRED.

## Deployment gates

A production deployment requires:

- green GitHub fixed-income workflow;
- approved model version;
- absolute production data and audit paths;
- monitored SEC_USER_AGENT contact;
- successful database integrity check;
- successful application health endpoint;
- documented rollback target.

Build the production image with Dockerfile.fixed-income. Secrets are injected by the runtime and must never be committed.

## Monitoring

Monitor at least:

- source freshness and publication lag;
- adapter error rate;
- missing and non-finite values;
- job queue depth, failure rate and latency;
- SQLite integrity and disk capacity;
- Streamlit health endpoint;
- model version and research-run volume;
- audit-chain verification.

Alerts must identify the affected source, first failure time, last valid observation and owning team.

## Incident response

1. Freeze automated refresh or execution for the affected component.
2. Preserve logs, audit events and the last valid data snapshot.
3. Classify the issue as data, model, infrastructure or access control.
4. Prevent publication of results derived from invalid inputs.
5. Restore the last validated model or data vintage.
6. Re-run the validation gate and characterization suite.
7. Record cause, scope, resolution and prevention action in the audit trail.

## Rollback

The protected V7 reference is stored at:

.industrialization/baseline/fixed_income_credit_v7_0_0.py

Its SHA-256 is:

192fbb036711ae5fed32f5e690a5f8ae2f5cde28726512547acc8c353cd66eee

The V8 migration is reproducible through:

python scripts/apply_fixed_income_v8_migration.py

For an emergency rollback, copy the protected V7 file over fixed_income_credit.py, compile it, run characterization tests, then restart Streamlit. Do not delete the failed V8 artifact until the incident evidence has been retained.

## Backup and recovery

Back up the following as one consistent recovery set:

- point-in-time SQLite database and WAL files;
- audit JSONL and model registry;
- deployed Git commit and model versions;
- environment configuration excluding secret values;
- approved input snapshots and research-run metadata.

Perform periodic restoration drills into an isolated validation environment.

## Access and secrets

Use least-privilege service identities. Separate read-only research access from model approval and deployment permissions. Do not store API keys, credentials, private positions or client data in the repository, browser session state, logs or audit payloads.

## Release checklist

- Baseline and migration hashes recorded.
- Compilation passes.
- Characterization and operational tests pass.
- Coverage threshold passes.
- Data-quality and PIT controls pass.
- Model version approved.
- Audit chain verifies.
- Production settings validate.
- Rollback has been tested.
- Deployment owner and monitoring owner are assigned.
