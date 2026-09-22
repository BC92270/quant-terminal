"""Release-hardening tests for Quantum Lab V3.8."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from .phase3_v36_algorithmic_reduction import canonical_json_sha256
from .phase3_v38_elementary_admission import load_v38_artifact, validate_v38_artifact
from .verify_phase3_v38 import (
    EXPECTED_FROZEN_FILE_COUNT,
    V38_PATHS,
    verify_release_chain,
)


ROOT = Path(__file__).resolve().parents[1]


class ReleaseHardeningV38Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.release = verify_release_chain(ROOT)
        cls.freeze = json.loads((ROOT / "FREEZE_CONTRACT_V3_8.json").read_text(encoding="utf-8"))

    def _copy_release(self, destination: Path) -> None:
        frozen = self.freeze["frozen_files"]
        for relative in [*frozen, "FREEZE_CONTRACT_V3_8.json"]:
            source = ROOT / relative
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def test_release_chain_passes(self) -> None:
        self.assertTrue(self.release["valid"], self.release)
        self.assertEqual(self.release["check_count"], 21)

    def test_frozen_inventory_is_complete(self) -> None:
        frozen = self.freeze["frozen_files"]
        self.assertEqual(len(frozen), EXPECTED_FROZEN_FILE_COUNT)
        self.assertTrue(set(V38_PATHS).issubset(frozen))

    def test_freeze_self_hash_is_exact(self) -> None:
        expected = canonical_json_sha256(
            {key: value for key, value in self.freeze.items() if key != "freeze_contract_sha256"}
        )
        self.assertEqual(self.freeze["freeze_contract_sha256"], expected)

    def test_all_frozen_raw_hashes_match(self) -> None:
        for relative, expected in self.freeze["frozen_files"].items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected, relative)

    def test_nested_artifact_tamper_is_rejected_after_rehash(self) -> None:
        artifact, report = load_v38_artifact()
        self.assertTrue(report["valid"])
        tampered = copy.deepcopy(artifact)
        tampered["elementary_resource_ledger"]["cnot_count"] = 1
        tampered["artifact_sha256"] = canonical_json_sha256(
            {key: value for key, value in tampered.items() if key != "artifact_sha256"}
        )
        self.assertFalse(validate_v38_artifact(tampered)["valid"])

    def test_negative_n40_result_is_valid_science_not_invalid_artifact(self) -> None:
        artifact, report = load_v38_artifact()
        self.assertTrue(report["valid"])
        self.assertEqual(
            artifact["n40_admission"]["admission_decision"],
            "BLOCKED_INCOMPLETE_REVERSIBLE_IR",
        )

    def test_clean_extract_release_verifies(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v38-clean-") as temporary:
            destination = Path(temporary)
            self._copy_release(destination)
            report = verify_release_chain(destination)
            self.assertTrue(report["valid"], report)

    def test_installer_exact_reapply_is_noop(self) -> None:
        from install_quantum_lab_v38 import install

        with tempfile.TemporaryDirectory(prefix="quantum-v38-target-") as temporary:
            destination = Path(temporary)
            self._copy_release(destination)
            report = install(ROOT, destination, apply=True)
            self.assertTrue(report["valid"], report)
            self.assertTrue(report["no_op"])
            self.assertFalse(report["applied"])

    def test_installer_rejects_mixed_successor_surface(self) -> None:
        from install_quantum_lab_v38 import preflight

        with tempfile.TemporaryDirectory(prefix="quantum-v38-mixed-") as temporary:
            destination = Path(temporary)
            self._copy_release(destination)
            (destination / "quantum_research_lab/README.md").write_text("unknown successor\n", encoding="utf-8")
            report = preflight(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertEqual(report["target"]["successor_state"], "INVALID")

    def test_installer_rejects_symlinked_overlay_destination(self) -> None:
        from install_quantum_lab_v38 import preflight

        with tempfile.TemporaryDirectory(prefix="quantum-v38-link-") as temporary:
            destination = Path(temporary)
            self._copy_release(destination)
            victim = destination / "app_v38_offline_harness.py"
            victim.unlink()
            victim.symlink_to(destination / "DEPLOY_V3_8.md")
            report = preflight(ROOT, destination)
            self.assertFalse(report["valid"])


if __name__ == "__main__":
    unittest.main()
