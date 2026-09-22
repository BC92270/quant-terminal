"""Negative-path tests for the V3.7 release and transactional installer."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from install_quantum_lab_v37 import (
    LOCK_NAME,
    OVERLAY_FILES,
    SUPPORT_CLOSURE_FILES,
    V37_ONLY_FILES,
    install,
    preflight,
)
from .phase3_v36_algorithmic_reduction import canonical_json_sha256
from .verify_phase3_v37 import (
    EXPECTED_V37_FROZEN_PATHS,
    README_PATH,
    UI_PATH,
    V36_FROZEN_PATHS,
    V36_README_SHA256,
    V36_UI_SHA256,
    V37_LEGACY_SUPPORT_SHA256,
    V37_README_SHA256,
    V37_UI_SHA256,
    _read_json_strict,
    _regular_contained,
    classify_successor_pair,
    verify_release_chain,
)


class ReleaseHardeningV37Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        if not (cls.root / "FREEZE_CONTRACT_V3_7.json").is_file():
            raise unittest.SkipTest("V3.7 freeze is not assembled yet.")

    def _copy_release(self, target: Path, name: str = "release") -> Path:
        destination = target / name
        shutil.copytree(
            self.root,
            destination,
            ignore=shutil.ignore_patterns(
                "__pycache__",
                ".quantum-lab-v36-*",
                ".quantum-lab-v37-*",
            ),
        )
        return destination

    def test_inventory_closure_is_hard_coded(self) -> None:
        self.assertEqual(len(V36_FROZEN_PATHS), 57)
        self.assertEqual(len(V37_LEGACY_SUPPORT_SHA256), 27)
        self.assertEqual(len(EXPECTED_V37_FROZEN_PATHS), 99)
        freeze = _read_json_strict(self.root / "FREEZE_CONTRACT_V3_7.json")
        self.assertEqual(set(freeze["frozen_files"]), EXPECTED_V37_FROZEN_PATHS)

    def test_successor_state_rejects_mixed_and_third_values(self) -> None:
        self.assertEqual(classify_successor_pair(V36_README_SHA256, V36_UI_SHA256), "V3.6")
        self.assertEqual(classify_successor_pair(V37_README_SHA256, V37_UI_SHA256), "V3.7")
        self.assertEqual(classify_successor_pair(V36_README_SHA256, V37_UI_SHA256), "INVALID")
        self.assertEqual(classify_successor_pair(V37_README_SHA256, V36_UI_SHA256), "INVALID")
        self.assertEqual(classify_successor_pair("0" * 64, "1" * 64), "INVALID")

    def test_duplicate_and_nonfinite_json_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            duplicate = Path(tmp) / "duplicate.json"
            duplicate.write_text('{"a":1,"a":2}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                _read_json_strict(duplicate)
            nonfinite = Path(tmp) / "nonfinite.json"
            nonfinite.write_text('{"a":NaN}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Non-finite JSON number"):
                _read_json_strict(nonfinite)

    def test_path_traversal_and_symlink_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "regular").write_text("ok", encoding="utf-8")
            os.symlink(root / "regular", root / "link")
            with self.assertRaises((ValueError, FileNotFoundError)):
                _regular_contained(root, "../regular")
            with self.assertRaisesRegex(ValueError, "Symlinked"):
                _regular_contained(root, "link")

    def test_rehashed_parent_freeze_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = self._copy_release(Path(tmp))
            freeze_path = release / "FREEZE_CONTRACT_V3_6.json"
            freeze = _read_json_strict(freeze_path)
            freeze["frozen_files"].pop("DEPLOY_V3_4.md")
            freeze["freeze_contract_sha256"] = canonical_json_sha256(
                {key: value for key, value in freeze.items() if key != "freeze_contract_sha256"}
            )
            freeze_path.write_text(
                json.dumps(freeze, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            report = verify_release_chain(release)
            self.assertFalse(report["valid"])
            self.assertFalse(report["checks"]["v36_freeze_raw_and_semantic_identity_exact"])
            self.assertFalse(report["checks"]["v36_frozen_inventory_57_paths_exact"])

    def test_legacy_support_mutation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = self._copy_release(Path(tmp))
            relative = sorted(V37_LEGACY_SUPPORT_SHA256)[0]
            with (release / relative).open("ab") as handle:
                handle.write(b"\nmutated")
            report = verify_release_chain(release)
            self.assertFalse(report["valid"])
            self.assertFalse(report["checks"]["legacy_support_snapshot_27_files_exact"])

    def test_preflight_rejects_unknown_successor_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = self._copy_release(Path(tmp))
            (release / UI_PATH).write_text("# unauthorized successor\n", encoding="utf-8")
            report = preflight(self.root, release)
            self.assertFalse(report["valid"])
            self.assertEqual(report["target"]["successor_state"], "INVALID")

    def test_preflight_rejects_partial_v37_overlay_on_v36_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = self._copy_release(Path(tmp))
            # Recreate only the authenticated predecessor successor pair; all
            # other V3.7-only files deliberately remain, which must fail closed.
            v36_overlay = self.root.parents[1] / "outputs" / "Quantum_Lab_V3_6_Deployment_Overlay.zip"
            if not v36_overlay.is_file():
                self.skipTest("Local V3.6 deployment overlay unavailable.")
            import zipfile

            with zipfile.ZipFile(v36_overlay) as archive:
                for relative in (README_PATH, UI_PATH):
                    (release / relative).write_bytes(archive.read(relative))
            report = preflight(self.root, release)
            self.assertFalse(report["valid"])
            self.assertEqual(report["target"]["successor_state"], "V3.6")
            self.assertTrue(report["target"]["partial_v37_paths"])

    def test_preflight_accepts_only_missing_support_in_known_v36_packaged_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = self._copy_release(Path(tmp))
            v36_overlay = self.root.parents[1] / "outputs" / "Quantum_Lab_V3_6_Deployment_Overlay.zip"
            if not v36_overlay.is_file():
                self.skipTest("Local V3.6 deployment overlay unavailable.")
            import zipfile

            with zipfile.ZipFile(v36_overlay) as archive:
                for relative in (README_PATH, UI_PATH):
                    (release / relative).write_bytes(archive.read(relative))
            for relative in V37_ONLY_FILES:
                (release / relative).unlink()
            missing = [
                "NEXT_PHASE_V3_2_GATE_LEVEL_COMPILER.md",
                "app_v34_fast_harness.py",
                "app_v34_harness.py",
                "baseline_phase3_v31.png",
            ]
            for relative in missing:
                (release / relative).unlink()
            report = preflight(self.root, release)
            self.assertTrue(report["valid"], report["errors"])
            self.assertEqual(report["target"]["successor_state"], "V3.6")
            self.assertTrue(report["target"]["legacy_support_repair_required"])
            self.assertEqual(report["target"]["legacy_support_missing_paths"], sorted(missing))
            self.assertFalse(report["target"]["legacy_support_mismatched_paths"])

    def test_existing_lock_blocks_install_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = self._copy_release(Path(tmp))
            lock = release / LOCK_NAME
            lock.write_text("held\n", encoding="utf-8")
            before = (release / UI_PATH).read_bytes()
            report = install(self.root, release)
            self.assertFalse(report["valid"])
            self.assertFalse(report["applied"])
            self.assertEqual((release / UI_PATH).read_bytes(), before)

    def test_exact_reapplication_is_idempotent_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = self._copy_release(Path(tmp))
            report = install(self.root, release)
            self.assertTrue(report["valid"])
            self.assertTrue(report["idempotent"])
            self.assertFalse(report["applied"])
            self.assertFalse((release / LOCK_NAME).exists())

    def test_injected_partial_apply_restores_authenticated_preimages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = self._copy_release(Path(tmp))
            before = {relative: (release / relative).read_bytes() for relative in OVERLAY_FILES}
            report = install(
                self.root,
                release,
                _test_fail_after=9,
                _test_force_apply=True,
            )
            self.assertFalse(report["applied"])
            self.assertTrue(report["rolled_back"])
            self.assertTrue(report["preimages_restored"])
            self.assertEqual(len(report["applied_files_before_failure"]), 9)
            self.assertFalse((release / LOCK_NAME).exists())
            for relative, expected in before.items():
                self.assertEqual((release / relative).read_bytes(), expected)

    def test_source_mutation_after_stage_is_detected_before_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = self._copy_release(Path(tmp), "source")
            target = self._copy_release(Path(tmp), "target")

            def mutate(candidate: Path, _stage: Path) -> None:
                with (candidate / "DEPLOY_V3_7.md").open("ab") as handle:
                    handle.write(b"\nrace")

            before = (target / UI_PATH).read_bytes()
            report = install(
                source,
                target,
                _test_force_apply=True,
                _test_after_stage=mutate,
            )
            self.assertFalse(report["applied"])
            self.assertIn("Source changed after preflight", report.get("error", ""))
            self.assertEqual((target / UI_PATH).read_bytes(), before)
            self.assertFalse((target / LOCK_NAME).exists())

    def test_ui_is_strictly_last_in_overlay_order(self) -> None:
        self.assertEqual(OVERLAY_FILES[-2], README_PATH)
        self.assertEqual(OVERLAY_FILES[-1], UI_PATH)
        self.assertEqual(len(SUPPORT_CLOSURE_FILES), 27)
        self.assertEqual(len(OVERLAY_FILES), 45)
        self.assertEqual(len(OVERLAY_FILES), len(set(OVERLAY_FILES)))


if __name__ == "__main__":
    unittest.main()
