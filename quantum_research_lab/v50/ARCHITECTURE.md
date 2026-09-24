# Quantum Lab V5.0 — Hardware-Evidence Control Plane

V5.0 closes the missing historical-epoch question left by V4.9 without
silently crossing the hardware boundary.  It authenticates four calibration
snapshots bundled in two pinned official `qiskit-ibm-runtime` wheel releases,
normalizes them with standard-library-only code, and evaluates the unchanged
eight-seed V4.8 architecture in a 4 × 8 decision matrix.

## Scientific boundary

The bundled fake-provider files are historical device-derived calibration
snapshots.  They are useful offline stress evidence; they are not a live
provider export, current hardware evidence, executed circuits, or QPU results.
Their official wheel URL, wheel digest, archive member, RECORD digest, raw file
digest, size, backend identity, and source epoch are all pinned.

Every cell must pass capacity, exact-route replay, inverse-best-CZ-error, and
idealized T2-duration necessary screens.  A failed cell cannot be averaged
away.  The duration model is not runtime and additive reported error is not
fidelity.  Passing these screens would only permit a human review of a future
metadata-only provider discovery protocol; it would not permit credentials,
sampling, sessions, backend execution, or QPU jobs.

## Fail-closed flow

1. Authenticate the exact V4.9 freeze, artifact, and validation report.
2. Authenticate every pinned raw configuration and properties file.
3. Require distinct raw hashes, normalized hashes, and source epochs.
4. Require one processor family, revision, directed topology, basis, and dt.
5. Derive fault-excluded capacity and strict per-snapshot necessary ceilings.
6. Evaluate all 32 snapshot × seed cells against the unchanged architecture.
7. Keep current-provider discovery and V5 execution closed on any failure.

The provider gate module deliberately contains no provider SDK import and no
network or execution path.  It exposes the closed decision and rejects access
before credentials can be read.
