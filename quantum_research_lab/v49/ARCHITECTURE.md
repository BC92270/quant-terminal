# Quantum Lab V4.9 · Offline Pre-Hardware Admission

## Terminal question

V4.9 asks one falsifiable question: can the exact frozen `BANDS · N=40 · K=10`
workload pass every prerequisite required before controlled provider discovery?
It is the final offline V4 phase. A negative result closes the lineage cleanly;
a positive result opens only a separately preregistered V5 protocol.

## Two independent gates

1. **Authentic epoch gate** — at least three epochs from the same target family,
   each with distinct raw bytes, normalized property identity and source time.
2. **Architecture gate** — every seed and every epoch must satisfy exact
   semantics, clean ancillas, capacity, routing, ISA, coupling, property,
   duration and strict error-screen requirements.

The existing cohort contains one historical FakeMarrakesh properties epoch.
It is useful offline evidence, but it is not current calibration. The V4.8
candidate range of `795,990–838,686` direct CX remains above the strict
exclusive error ceiling of `964`; the admissible maximum is therefore `963`.

## Decision states

- `V49_NOT_EVALUABLE_INSUFFICIENT_AUTHENTIC_EPOCHS`
- `V49_TERMINAL_EXACT_ARCHITECTURE_NO_GO`
- `V49_OFFLINE_PRE_HARDWARE_ADMISSION_PASSED_PROVIDER_DISCOVERY_ONLY`

Decision precedence is fail-closed. Missing authentic epochs produce
`NOT_EVALUABLE`; they are never replaced with synthetic observations. A future
complete cohort that still fails the architecture gate produces a terminal
no-go, which is a valid scientific result.

## Non-claims

V4.9 remains `RESEARCH_ONLY` and `hardware_executable=false`. It performs no
provider discovery, credential access, network call, simulator job, backend
run or QPU job. Necessary resource screens are not fidelity, runtime, utility
or quantum-advantage evidence.
