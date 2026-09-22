# Quantum Lab V4.8 · Exact Architecture Reduction and Snapshot Governance

## Executive decision

V4.8 demonstrates a large, exact, offline resource reduction for the frozen
`BANDS · N=40 · K=10` research family. It does **not** demonstrate hardware
readiness.

- Eight of eight candidate logical streams are fully materialized.
- Eight of eight streams route through the unchanged V4.6 BasicSwap oracle
  with zero ISA and coupling violations.
- Aggregate logical CX decreases from `19,251,104` to `6,474,096`
  (`12,777,008`, approximately `66.37%`).
- Aggregate routed CZ decreases from `119,029,964` to `59,565,732`
  (`59,464,232`, approximately `49.96%`).
- Exact computational-basis equivalence passes `28,240 / 28,240` cases.
- Only one distinct authentic historical properties epoch exists. The
  preregistered three-epoch robustness gate is therefore not evaluable.
- Even after the reduction, all eight deliberately optimistic
  V4.7-comparable duration and additive-error necessary screens fail.

The sealed outcome is:

`V48_EXACT_ARCHITECTURE_CX_AND_BASICSWAP_CZ_REDUCTION_DEMONSTRATED_MULTI_SNAPSHOT_ROBUSTNESS_NOT_EVALUABLE_HARDWARE_REJECTED`

Production admission is:

`RESEARCH_ONLY_HARDWARE_EXECUTION_REJECTED`

## Immutable parent and chronology

V4.8 authenticates the exact V4.7 parent before reading a V4.8 result:

| Parent evidence | Raw SHA-256 | Semantic SHA-256 |
|---|---|---|
| V4.7 sealed artifact | `ddb8dae96c1d5fe1040f92731c995315e04232da645fed0b2d34cf7575a06185` | `fa1b8a2be1471080134f34ada7ba8cff488c87077a4e5f271fd29828f1fffbaf` |
| V4.7 freeze contract | `89dfc8f614955d4fe1c92cfd286ab04f4022d9eb69e566edf46a65e84aa81a3a` | `3f870a5ff89368d2000a58533fba395b0d077cc377cdc830fdc4b362f6465858` |

The candidate architecture, selection order, equivalence suite, frozen route
replay and decision thresholds were committed before candidate evaluation in
`PHASE_III_V4_8_ARCHITECTURE_CANDIDATE_ORACLE_V1.json`. The known V4.7
development snapshot cannot be relabelled as a holdout. A negative or
not-evaluable result is explicitly admissible scientific output.

## Exact circuit change

V4.8 changes one primitive only: controlled modular addition of a classical
constant. Width allocation, binary coin rings, the streamed Bennett selector,
certified bridges, initial layout and ordered BasicSwap path oracle remain
inherited.

The legacy implementation controlled every gate inside the ripple-carry
adder. V4.8 instead uses:

1. load each set bit of the constant register with `CX(control, constant[i])`;
2. execute the exact uncontrolled Cuccaro constant adder; and
3. unload those same constant bits with `CX(control, constant[i])`.

For width `w` and constant `c mod 2^w`, the translated CX cost per addition is:

- legacy: `68w − 102`;
- V4.8: `17w − 25 + 2·popcount(c mod 2^w)`.

The construction relies on a clean constant register and clean carry exit.
When the control is zero, load/unload are identities and the data register is
unchanged. When the control is one, the uncontrolled adder receives the exact
constant. Both circuits implement the same computational-basis permutation
without relative phase, so equality extends linearly to superpositions. This
is an exact circuit statement, not a device-fidelity claim.

The ripple-carry construction is grounded in the reversible adder of
[Cuccaro et al., 2004](https://arxiv.org/abs/quant-ph/0410184); V4.8's
control-load specialization and its exact cost ledger are project-specific and
independently checked here.

## Equivalence protocol

The independent checker does not import the optimizer. It reconstructs both
gate-level circuits and verifies the complete permutation, constant cleanup
and carry cleanup under this fixed suite:

- exhaustive widths `5` and `6`: `10,240` cases;
- deterministic random widths `7, 8, 16, 31, 33, 34, 35, 36, 39`:
  `2,000` cases per width, `18,000` cases; and
- total: `28,240 / 28,240` exact cases.

The deterministic random seed is `480048`. Passing this suite supports the
specified primitive substitution; it does not prove unrelated circuit,
compiler or hardware behavior.

## Full-stream and route ledger

| Seed | Width | Parent CX | V4.8 CX | Parent CZ | V4.8 CZ | V4.8 structural depth |
|---:|---:|---:|---:|---:|---:|---:|
| 1103 | 135 | 2,405,038 | 808,014 | 14,839,144 | 7,418,727 | 7,348,857 |
| 2207 | 137 | 2,408,638 | 811,478 | 14,916,301 | 7,418,714 | 7,370,423 |
| 3301 | 133 | 2,361,262 | 795,990 | 14,579,062 | 7,327,440 | 7,247,341 |
| 4409 | 135 | 2,361,262 | 796,174 | 14,563,795 | 7,241,677 | 7,231,760 |
| 5501 | 137 | 2,361,262 | 796,158 | 14,603,197 | 7,328,538 | 7,252,504 |
| 6607 | 137 | 2,405,038 | 807,950 | 14,852,263 | 7,420,451 | 7,345,974 |
| 7703 | 145 | 2,499,790 | 838,686 | 15,527,797 | 7,811,853 | 7,632,359 |
| 8807 | 139 | 2,448,814 | 819,646 | 15,148,405 | 7,598,332 | 7,468,370 |

Every candidate CX count is strictly below its V4.5 parent and every candidate
routed CZ count is strictly below its V4.6 parent. Structural depth is an ASAP
gate-layer diagnostic. It is neither a pulse schedule nor wall-clock runtime.

## Why hardware remains rejected

The V4.7 historical model gives two deliberately favorable lower bounds:

- reported-error mass: `direct CX × minimum historical CZ error < 1`;
- duration: `ceil(direct CX / 78) × minimum historical CZ duration ≤ maximum historical T2`.

They assume zero SWAP, zero one-qubit cost and ideal 78-way CZ parallelism.
They are necessary, not sufficient, conditions. Every V4.8 seed still fails
both. Additive reported-error mass is not fidelity, success probability,
expected failures, logical error or solution quality.

The stricter historical ceilings are `964` direct CX for the additive-error
screen and `613,392` for the idealized duration screen. The V4.8 range remains
`795,990–838,686` CX. A further architecture reduction is therefore required
before any current-provider discovery could become scientifically relevant.

## Authentic snapshot registry

An exhaustive search of authenticated V4.7 inputs found one distinct raw
properties identity: the dated `2025-02-26` FakeMarrakesh snapshot. Release
copies, archive members and normalized forms have identical identity and do
not increase sample size.

The sealed admission rule requires at least three snapshots from the same
target family with distinct:

- raw-file SHA-256;
- normalized property-vector SHA-256; and
- source epoch.

Synthetic jitter, bootstrap samples, resampling, filename changes and metadata
rewrites are not authentic epochs. All snapshot × seed cells must pass;
averaging cannot rescue a failed cell. Current observation is `1 / 3`, so the
only honest decision is:

`MULTI_SNAPSHOT_ROBUSTNESS_NOT_EVALUABLE_INSUFFICIENT_DISTINCT_AUTHENTIC_SNAPSHOT_IDENTITIES`

## Evidence identities

| Evidence | Raw SHA-256 | Semantic SHA-256 |
|---|---|---|
| V4.8 artifact | `f6fcce00b9ce95cd9e30eeb938e243c308b5408255dc98556e8be45a36691f76` | `6df8440320e38e0bb73674f3ceb0f4bc179385d0d344c9521fa35f197504c55f` |
| Protocol | `93a1b8744323b1dfffa86c4019cc30c6e83dd696ee88eab2f8174c821b2707fd` | `2f5874030f433d1bd542804a20208d42276127d5e79851daf00d6d1d39db46b2` |
| Snapshot catalog | `7a5c8cf6a4a33f0f32ce5ea1ba0df7c45ee5c35d343eebc86ba174470a77be53` | `9a585764e2de35edcd66695da7abfea9726785c06065133170917d8587341ef6` |
| Normalized cohort | `54c5cf463ec0c2fa591864ed595fac26a7c0a9e279f47a41942ad4073da5af5e` | `8364f86f0360fff5938eed57d926a8c5d6a960bc8639300a7f366f46bf940da5` |
| Architecture oracle | `6fbe442d0ce00b88ee7f74113b51f5375b939ca34459e68e37d94e8da880a72d` | `689c6b5ac55703ea869abc4087245bc6a13f1ab35cc5e5eab8c86dc49ffaac6a` |
| Robustness cost model | `a8fe16d0810aede0348bdb4010d9fbab5fa7736438df71782351436a54ad05cb` | `58f7e2c84ecf138ed26912950055a083202ce4e7f7e4407eaf2898ae6f6ee1b6` |
| Optimizer source | `0bef3609b7c535b13cd25254a8c322f7d1c207b4111549e5b86bd5ff2e9ea0e9` | n/a |
| Independent checker | `1435e1c4efb61c30e884e87132ec39f30f1206c96332e3802c19dd0a42269f3c` | n/a |

An empty-environment replay with `PYTHONHASHSEED=0` reproduces the artifact
byte-for-byte. The sealed report records `65/65` independent checks and
`96/96` scientific validation checks.

## Claim and execution boundary

V4.8 is `RESEARCH_ONLY` and `hardware_executable=false`.

- provider SDK imported: false;
- provider credentials read: false;
- credential reads: `0`;
- provider calls: `0`;
- network calls: `0`;
- backend run calls: `0`;
- local simulator jobs: `0`; and
- QPU jobs: `0`.

No current calibration, calibrated fidelity, pulse timing, wall-clock runtime,
utility or quantum advantage is claimed. The final falsifiable gate is:

`ACQUIRE_TWO_ADDITIONAL_AUTHENTIC_OFFLINE_SNAPSHOT_EPOCHS_AND_REDUCE_DIRECT_CX_BELOW_BOTH_HISTORICAL_NECESSARY_THRESHOLDS_BEFORE_ANY_CURRENT_PROVIDER_DISCOVERY`
