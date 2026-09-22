"""Fast regression suite for the V3.2 proof-carrying compiler layer."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from .phase3_artifact_guard import (
    EXPECTED_PARENT_RAW_SHA256,
    load_and_validate_dyadic_artifact,
    validate_dyadic_payload,
)
from .phase3_circuit_validation import (
    DEFAULT_SEAL_NAME,
    default_compiler_root,
    load_compiler_artifact,
    run_arithmetic_validation,
    run_small_n_validation,
)
from .phase3_gate_compiler import (
    DOMAIN_EXACT_K,
    DOMAIN_FULL_BINARY,
    compile_seed_circuit,
    load_compiler_spec,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PARENT_CANDIDATES = (
    PROJECT_ROOT / "SEALED_EXACT_DYADIC_BANDS_ORACLE.json",
    PROJECT_ROOT
    / "outputs"
    / "quantum_phase3"
    / "dyadic_bands_oracle"
    / "N40_BANDS"
    / "SEALED_EXACT_DYADIC_BANDS_ORACLE.json",
)
PARENT_PATH = next(
    (candidate for candidate in _PARENT_CANDIDATES if candidate.exists()),
    _PARENT_CANDIDATES[0],
)


class GateCompilerFastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.parent = json.loads(PARENT_PATH.read_text(encoding="utf-8"))

    def test_compiler_spec_self_hash(self) -> None:
        spec = load_compiler_spec()
        self.assertEqual(len(spec["gate_compiler_spec_sha256"]), 64)
        self.assertFalse(spec["claim_boundary"]["hardware_executable"])

    def test_parent_guard_and_tamper_rejection(self) -> None:
        report = load_and_validate_dyadic_artifact(
            PARENT_PATH, expected_raw_sha256=EXPECTED_PARENT_RAW_SHA256
        )
        self.assertTrue(report["valid"], report["failed_checks"])
        tampered = copy.deepcopy(self.parent)
        tampered["seed_certificates"][0]["factor_bands"][0][
            "coefficients_int"
        ][0] += 1
        tamper_report = validate_dyadic_payload(tampered)
        self.assertFalse(tamper_report["valid"])
        self.assertIn("certificate_hashes_recomputed", tamper_report["failed_checks"])

    def test_exhaustive_arithmetic(self) -> None:
        report = run_arithmetic_validation()
        self.assertTrue(report["passed"], report["failures"])
        self.assertGreater(report["addition_cases"], 1_000)
        self.assertGreater(report["comparator_cases"], 1_000)

    def test_small_n_oracle_equivalence_and_clean_ancillas(self) -> None:
        report = run_small_n_validation()
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual(report["total_basis_state_cases"], 44)

    def test_full_binary_range_proof_retains_extra_bit(self) -> None:
        certificate = next(
            item
            for item in self.parent["seed_certificates"]
            if int(item["seed"]) == 6607
        )
        kwargs = {
            "parent_dyadic_oracle_sha": self.parent["dyadic_oracle_sha"],
            "parent_artifact_file_sha256": EXPECTED_PARENT_RAW_SHA256,
        }
        exact = compile_seed_circuit(certificate, DOMAIN_EXACT_K, **kwargs)
        full = compile_seed_circuit(certificate, DOMAIN_FULL_BINARY, **kwargs)
        exact_width = max(
            item.width for item in exact.constraints if item.kind == "FACTOR"
        )
        full_width = max(
            item.width for item in full.constraints if item.kind == "FACTOR"
        )
        self.assertEqual(exact_width, 68)
        self.assertEqual(full_width, 69)
        self.assertEqual(exact.logical_qubits, 119)
        self.assertEqual(full.logical_qubits, 121)

    def test_sealed_artifact_when_present(self) -> None:
        path = PROJECT_ROOT / default_compiler_root() / DEFAULT_SEAL_NAME
        if not path.exists():
            self.skipTest("Canonical compiler artifact is not sealed yet.")
        artifact, report = load_compiler_artifact(path)
        self.assertTrue(report["valid"], report["errors"])
        self.assertTrue(artifact["validation"]["overall_pass"])
        self.assertFalse(artifact["claim_boundary"]["hardware_executable"])


if __name__ == "__main__":
    unittest.main()
