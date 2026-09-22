"""Release, packaging and transactional hardening tests for Quantum Lab V4.6."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from build_quantum_lab_v46_release import _write_deterministic_zip
from install_quantum_lab_v46 import (
    EXPECTED_V46_FROZEN_FILE_COUNT,
    EXPECTED_V46_FROZEN_PATHS_FINGERPRINT,
    EXPECTED_V46_OVERLAY_ORDER_SHA256,
    README_PATH,
    UI_PATH,
    V46_FREEZE_PATH,
    V46_TRANSITION_FILES,
    _source_inventory,
    apply_overlay,
    authenticate_target,
    preflight,
)
from .phase3_v46_validation import (
    EXPECTED_ARTIFACT_RAW_SHA256,
    EXPECTED_ARTIFACT_SHA256,
    EXPECTED_VALIDATION_EVIDENCE_SHA256,
    canonical_json_sha256,
    read_json_strict,
)
from .verify_freeze_contract_v46 import EXPECTED_FREEZE_CHECK_COUNT, verify_freeze_contract
from .verify_phase3_v46 import (
    EXPECTED_RELEASE_CHECK_COUNT,
    EXPECTED_SEALED_VALIDATION_EVIDENCE_RAW_SHA256,
    EXPECTED_SEALED_VALIDATION_EVIDENCE_SHA256,
    verify_release_chain,
)


ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_OUTPUTS = ROOT.parents[1] / "outputs"
V45_ARCHIVE = EXTERNAL_OUTPUTS / "Quantum_Lab_V4_5_Institutional_Release.zip"


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _v46_target(destination: Path) -> Path:
    freeze = read_json_strict(ROOT / V46_FREEZE_PATH)
    for relative in freeze["frozen_files"]:
        _copy_file(ROOT / relative, destination / relative)
    _copy_file(ROOT / V46_FREEZE_PATH, destination / V46_FREEZE_PATH)
    return destination


def _v45_target(destination: Path) -> Path:
    if not V45_ARCHIVE.is_file():
        raise unittest.SkipTest(f"Exact V4.5 institutional fixture unavailable: {V45_ARCHIVE}")
    with zipfile.ZipFile(V45_ARCHIVE) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
            raise AssertionError("Unsafe V4.5 fixture archive")
        archive.extractall(destination)
    return destination


class QuantumLabV46ReleaseTests(unittest.TestCase):
    def test_01_transition_inventory_is_exactly_ordered(self) -> None:
        self.assertEqual(len(V46_TRANSITION_FILES), 22)
        observed = hashlib.sha256(json.dumps(list(V46_TRANSITION_FILES), separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(observed, EXPECTED_V46_OVERLAY_ORDER_SHA256)

    def test_02_readme_and_ui_are_committed_last(self) -> None:
        self.assertEqual(V46_TRANSITION_FILES[-2:], (README_PATH, UI_PATH))

    def test_03_source_inventory_authenticates(self) -> None:
        freeze, rows, errors = _source_inventory(ROOT)
        self.assertFalse(errors, errors)
        self.assertEqual(freeze["frozen_file_count"], EXPECTED_V46_FROZEN_FILE_COUNT)
        self.assertTrue(all(row["valid"] for row in rows))

    def test_04_freeze_self_hash_and_path_fingerprint_are_exact(self) -> None:
        freeze = read_json_strict(ROOT / V46_FREEZE_PATH)
        semantic = canonical_json_sha256({key: value for key, value in freeze.items() if key != "freeze_contract_sha256"})
        fingerprint = hashlib.sha256(json.dumps(sorted(freeze["frozen_files"]), separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(freeze["freeze_contract_sha256"], semantic)
        self.assertEqual(fingerprint, EXPECTED_V46_FROZEN_PATHS_FINGERPRINT)

    def test_05_release_identity_verifier_passes_38_checks(self) -> None:
        report = verify_release_chain(ROOT, deep=False)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["check_count"], EXPECTED_RELEASE_CHECK_COUNT)

    def test_06_release_deep_verifier_passes_38_checks(self) -> None:
        report = verify_release_chain(ROOT, deep=True)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["check_count"], EXPECTED_RELEASE_CHECK_COUNT)

    def test_07_freeze_verifier_passes_20_checks(self) -> None:
        report = verify_freeze_contract(ROOT)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["check_count"], EXPECTED_FREEZE_CHECK_COUNT)

    def test_08_clean_replay_validation_evidence_is_exact(self) -> None:
        evidence_path = EXTERNAL_OUTPUTS / "QUANTUM_LAB_V4_6_VALIDATION_EVIDENCE.json"
        evidence = read_json_strict(evidence_path)
        core = {key: value for key, value in evidence.items() if key != "sealed_validation_evidence_sha256"}
        self.assertEqual(hashlib.sha256(evidence_path.read_bytes()).hexdigest(), EXPECTED_SEALED_VALIDATION_EVIDENCE_RAW_SHA256)
        self.assertEqual(evidence["sealed_validation_evidence_sha256"], canonical_json_sha256(core))
        self.assertEqual(evidence["sealed_validation_evidence_sha256"], EXPECTED_SEALED_VALIDATION_EVIDENCE_SHA256)
        self.assertEqual(evidence["scientific_validation"]["validation_evidence_sha256"], EXPECTED_VALIDATION_EVIDENCE_SHA256)
        self.assertTrue(evidence["clean_process_replay"]["byte_for_byte_equal_to_sealed_artifact"])

    def test_09_artifact_identities_are_retained_in_freeze(self) -> None:
        freeze = read_json_strict(ROOT / V46_FREEZE_PATH)
        identities = freeze["v46_identities"]
        self.assertEqual(identities["artifact_raw_file_sha256"], EXPECTED_ARTIFACT_RAW_SHA256)
        self.assertEqual(identities["artifact_sha256"], EXPECTED_ARTIFACT_SHA256)

    def test_10_deterministic_zip_double_build_is_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first, second = Path(temporary) / "a.zip", Path(temporary) / "b.zip"
            names = (V46_FREEZE_PATH, "DEPLOY_V4_6.md")
            _write_deterministic_zip(ROOT, names, first)
            _write_deterministic_zip(ROOT, names, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_11_duplicate_archive_members_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                _write_deterministic_zip(ROOT, (V46_FREEZE_PATH, V46_FREEZE_PATH), Path(temporary) / "bad.zip")

    def test_12_archive_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                _write_deterministic_zip(ROOT, ("../outside",), Path(temporary) / "bad.zip")

    def test_13_same_source_and_target_are_rejected(self) -> None:
        report = preflight(ROOT, ROOT)
        self.assertFalse(report["valid"])
        self.assertIn("Source and target must be distinct.", report["errors"])

    def test_14_exact_v46_target_is_a_valid_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = _v46_target(Path(temporary) / "target")
            report = apply_overlay(ROOT, target)
            self.assertTrue(report["valid"], report)
            self.assertTrue(report["idempotent_no_op"])
            self.assertFalse(report["applied"])

    def test_15_exact_v46_target_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = _v46_target(Path(temporary) / "target")
            (target / "DEPLOY_V4_6.md").write_text("tampered", encoding="utf-8")
            report = preflight(ROOT, target)
            self.assertFalse(report["valid"])
            self.assertTrue(any("mismatch" in error.lower() for error in report["errors"]))

    def test_16_symlinked_source_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            for relative in V46_TRANSITION_FILES:
                _copy_file(ROOT / relative, source / relative)
            victim = source / "DEPLOY_V4_6.md"
            victim.unlink()
            os.symlink(ROOT / "DEPLOY_V4_6.md", victim)
            _, _, errors = _source_inventory(source)
            self.assertTrue(errors)

    def test_17_tampered_source_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            for relative in V46_TRANSITION_FILES:
                _copy_file(ROOT / relative, source / relative)
            (source / "DEPLOY_V4_6.md").write_text("tampered", encoding="utf-8")
            _, _, errors = _source_inventory(source)
            self.assertTrue(any("mismatch" in error.lower() for error in errors))

    def test_18_partial_v46_state_on_v45_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = _v45_target(Path(temporary) / "target")
            _copy_file(ROOT / "DEPLOY_V4_6.md", target / "DEPLOY_V4_6.md")
            report = authenticate_target(ROOT, target)
            self.assertFalse(report["valid"])
            self.assertIn("DEPLOY_V4_6.md", report["partial_v46_paths"])

    def test_19_all_22_commit_fault_positions_roll_back_to_exact_v45(self) -> None:
        for position in range(1, len(V46_TRANSITION_FILES) + 1):
            with self.subTest(position=position), tempfile.TemporaryDirectory() as temporary:
                target = _v45_target(Path(temporary) / "target")
                report = apply_overlay(ROOT, target, fault_after=position)
                self.assertFalse(report["valid"], report)
                self.assertTrue(report.get("rolled_back"), report)
                restored = authenticate_target(ROOT, target)
                self.assertTrue(restored["valid"], restored)
                self.assertEqual(restored["state"], "V4.5")

    def test_20_exact_v45_target_promotes_transactionally(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = _v45_target(Path(temporary) / "target")
            report = apply_overlay(ROOT, target)
            self.assertTrue(report["valid"], report)
            self.assertTrue(report["applied"])
            self.assertEqual(authenticate_target(ROOT, target)["state"], "V4.6")

    def test_21_successful_apply_emits_backup_manifest_and_then_no_ops(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = _v45_target(Path(temporary) / "target")
            first = apply_overlay(ROOT, target)
            manifest = Path(first["manifest"]["backup_directory"]) / "deployment-manifest.json"
            self.assertTrue(manifest.is_file())
            second = apply_overlay(ROOT, target)
            self.assertTrue(second["valid"], second)
            self.assertTrue(second["idempotent_no_op"])

    def test_22_installer_has_no_provider_or_network_client_import(self) -> None:
        tree = ast.parse((ROOT / "install_quantum_lab_v46.py").read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
        self.assertTrue({"qiskit", "qiskit_ibm_runtime", "requests", "httpx", "urllib"}.isdisjoint(modules))


if __name__ == "__main__":
    unittest.main()
