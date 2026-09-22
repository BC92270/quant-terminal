"""Release-hardening tests for the Quantum Lab V3.9 transition."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

from install_quantum_lab_v39 import (
    EXPECTED_V39_FROZEN_FILE_COUNT,
    EXPECTED_V39_FROZEN_PATHS_FINGERPRINT,
    LOCK_NAME,
    PARENT_FREEZE_RAW_SHA256,
    PARENT_FREEZE_SEMANTIC_SHA256,
    PARENT_FROZEN_FILE_COUNT,
    PARENT_FROZEN_PATHS_FINGERPRINT,
    PARENT_README_SHA256,
    PARENT_UI_SHA256,
    README_PATH,
    UI_PATH,
    V39_FREEZE_PATH,
    V39_ONLY_FILES,
    V39_TRANSITION_FILES,
    _canonical_json_sha256,
    _contained,
    _path_fingerprint,
    _read_json_strict,
    install,
    preflight,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT.parents[1] / "outputs"
V38_ARCHIVE = OUTPUT_ROOT / "Quantum_Lab_V3_8_Institutional_Release.zip"
V39_FULL_ARCHIVE = OUTPUT_ROOT / "Quantum_Lab_V3_9_Institutional_Release.zip"
V39_OVERLAY_ARCHIVE = OUTPUT_ROOT / "Quantum_Lab_V3_9_Deployment_Overlay.zip"


def _safe_extract(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise AssertionError("Archive contains duplicate names.")
        for name in names:
            item = Path(name)
            if item.is_absolute() or any(part in {"", ".", ".."} for part in item.parts):
                raise AssertionError(f"Unsafe archive member: {name}")
            target = (destination / item).resolve()
            target.relative_to(destination.resolve())
        archive.extractall(destination)


class InstallerV39StaticContractTests(unittest.TestCase):
    def test_overlay_is_unique_and_in_dependency_order(self) -> None:
        self.assertEqual(len(V39_TRANSITION_FILES), 17)
        self.assertEqual(len(V39_TRANSITION_FILES), len(set(V39_TRANSITION_FILES)))
        self.assertEqual(V39_TRANSITION_FILES[-2:], (README_PATH, UI_PATH))
        self.assertEqual(V39_TRANSITION_FILES[0], V39_FREEZE_PATH)

    def test_v39_inventory_constants_are_final(self) -> None:
        self.assertEqual(EXPECTED_V39_FROZEN_FILE_COUNT, 129)
        self.assertEqual(
            EXPECTED_V39_FROZEN_PATHS_FINGERPRINT,
            "ed2f8d6027b7b00c4ad68ed48f72e73b81dd240238849daba4c79ea050f72ce7",
        )

    def test_exact_parent_v38_constants_match_local_parent(self) -> None:
        parent_path = ROOT / "FREEZE_CONTRACT_V3_8.json"
        parent = _read_json_strict(parent_path)
        semantic = _canonical_json_sha256(
            {key: value for key, value in parent.items() if key != "freeze_contract_sha256"}
        )
        self.assertEqual(hashlib.sha256(parent_path.read_bytes()).hexdigest(), PARENT_FREEZE_RAW_SHA256)
        self.assertEqual(semantic, PARENT_FREEZE_SEMANTIC_SHA256)
        self.assertEqual(parent["frozen_file_count"], PARENT_FROZEN_FILE_COUNT)
        self.assertEqual(len(parent["frozen_files"]), PARENT_FROZEN_FILE_COUNT)
        self.assertEqual(_path_fingerprint(parent["frozen_files"]), PARENT_FROZEN_PATHS_FINGERPRINT)
        self.assertEqual(parent["frozen_files"][README_PATH], PARENT_README_SHA256)
        self.assertEqual(parent["frozen_files"][UI_PATH], PARENT_UI_SHA256)

    def test_duplicate_nonfinite_and_path_traversal_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v39-strict-") as temporary:
            root = Path(temporary)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"a":1,"a":2}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                _read_json_strict(duplicate)
            nonfinite = root / "nonfinite.json"
            nonfinite.write_text('{"a":NaN}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Non-finite JSON"):
                _read_json_strict(nonfinite)
            regular = root / "regular"
            regular.write_text("ok\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unsafe path"):
                _contained(root, "../regular", must_exist=True)
            link = root / "link"
            os.symlink(regular, link)
            with self.assertRaisesRegex(ValueError, "non-symlink"):
                _contained(root, "link", must_exist=True)

    def test_foreign_lock_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v39-lock-") as temporary:
            target = Path(temporary)
            (target / "quantum_research_lab").mkdir()
            lock = target / LOCK_NAME
            marker = b"foreign-lock-must-survive\n"
            lock.write_bytes(marker)
            report = install(ROOT, target, apply=True)
            self.assertFalse(report["valid"])
            self.assertFalse(report["applied"])
            self.assertTrue(lock.is_file())
            self.assertEqual(lock.read_bytes(), marker)


class FrozenV39ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        freeze_path = ROOT / V39_FREEZE_PATH
        verifier_path = ROOT / "quantum_research_lab/verify_phase3_v39.py"
        freeze_verifier_path = ROOT / "quantum_research_lab/verify_freeze_contract_v39.py"
        if not (freeze_path.is_file() and verifier_path.is_file() and freeze_verifier_path.is_file()):
            raise unittest.SkipTest("V3.9 freeze and release verifiers are not assembled yet.")
        cls.freeze = _read_json_strict(freeze_path)

    def _copy_release(self, destination: Path) -> None:
        for relative in [*self.freeze["frozen_files"], V39_FREEZE_PATH]:
            source = ROOT / relative
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def _extract_v38(self, destination: Path) -> None:
        if not V38_ARCHIVE.is_file():
            self.skipTest("Institutional V3.8 predecessor archive is unavailable.")
        _safe_extract(V38_ARCHIVE, destination)

    def test_release_chain_and_freeze_pass(self) -> None:
        from .verify_freeze_contract_v39 import verify_freeze_contract
        from .verify_phase3_v39 import verify_release_chain

        release = verify_release_chain(ROOT)
        freeze = verify_freeze_contract(ROOT, ROOT / V39_FREEZE_PATH)
        self.assertTrue(release["valid"], release)
        self.assertTrue(freeze["valid"], freeze)

    def test_inventory_self_hash_and_all_raw_hashes_are_exact(self) -> None:
        frozen = self.freeze["frozen_files"]
        self.assertEqual(len(frozen), EXPECTED_V39_FROZEN_FILE_COUNT)
        self.assertEqual(self.freeze["frozen_file_count"], EXPECTED_V39_FROZEN_FILE_COUNT)
        self.assertEqual(_path_fingerprint(frozen), EXPECTED_V39_FROZEN_PATHS_FINGERPRINT)
        semantic = _canonical_json_sha256(
            {
                key: value
                for key, value in self.freeze.items()
                if key != "freeze_contract_sha256"
            }
        )
        self.assertEqual(self.freeze["freeze_contract_sha256"], semantic)
        for relative, expected in frozen.items():
            actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(actual, expected, relative)
        self.assertTrue(set(V39_TRANSITION_FILES) - {V39_FREEZE_PATH} <= set(frozen))

    def test_clean_extract_is_self_contained(self) -> None:
        from .verify_freeze_contract_v39 import verify_freeze_contract
        from .verify_phase3_v39 import verify_release_chain

        with tempfile.TemporaryDirectory(prefix="quantum-v39-clean-") as temporary:
            destination = Path(temporary)
            self._copy_release(destination)
            self.assertTrue(verify_release_chain(destination)["valid"])
            self.assertTrue(
                verify_freeze_contract(destination, destination / V39_FREEZE_PATH)["valid"]
            )
            isolated = subprocess.run(
                [sys.executable, "-m", "quantum_research_lab.verify_phase3_v39", "."],
                cwd=destination,
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
            self.assertEqual(isolated.returncode, 0, isolated.stdout + isolated.stderr)
            isolated_report = json.loads(isolated.stdout)
            self.assertTrue(isolated_report["valid"], isolated_report)

    def test_exact_reapplication_is_noop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v39-noop-") as temporary:
            destination = Path(temporary)
            self._copy_release(destination)
            report = install(ROOT, destination, apply=True)
            self.assertTrue(report["valid"], report)
            self.assertTrue(report["no_op"])
            self.assertFalse(report["applied"])
            self.assertFalse((destination / LOCK_NAME).exists())

    def test_unknown_or_mixed_successor_surface_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v39-mixed-") as temporary:
            destination = Path(temporary)
            self._copy_release(destination)
            (destination / README_PATH).write_text("unauthorized successor\n", encoding="utf-8")
            report = preflight(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertEqual(report["target"]["successor_state"], "INVALID")

    def test_symlinked_overlay_destination_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v39-link-") as temporary:
            destination = Path(temporary)
            self._copy_release(destination)
            victim = destination / "DEPLOY_V3_9.md"
            victim.unlink()
            victim.symlink_to(destination / V39_FREEZE_PATH)
            report = preflight(ROOT, destination)
            self.assertFalse(report["valid"])

    def test_partial_v39_overlay_on_v38_surface_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v39-partial-") as temporary:
            destination = Path(temporary)
            self._extract_v38(destination)
            relative = sorted(V39_ONLY_FILES)[0]
            source = ROOT / relative
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            report = preflight(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertEqual(report["target"]["successor_state"], "V3.8")
            self.assertIn(relative, report["target"]["partial_v39_paths"])

    def test_staged_source_race_is_rejected_before_commit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v39-race-") as temporary:
            base = Path(temporary)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            target.mkdir()
            self._copy_release(source)
            self._extract_v38(target)
            before = (target / UI_PATH).read_bytes()

            def mutate(candidate: Path, _stage: Path) -> None:
                with (candidate / "DEPLOY_V3_9.md").open("ab") as handle:
                    handle.write(b"\nsource-race")

            report = install(
                source,
                target,
                apply=True,
                _test_after_stage=mutate,
                _test_skip_verification=True,
            )
            self.assertFalse(report["valid"])
            self.assertIn("Source changed after staging", report.get("error", ""))
            self.assertEqual((target / UI_PATH).read_bytes(), before)
            self.assertFalse((target / LOCK_NAME).exists())

    def test_partial_commit_faults_restore_exact_v38_preimages(self) -> None:
        for failure_index in (1, len(V39_TRANSITION_FILES) - 2, len(V39_TRANSITION_FILES)):
            with self.subTest(failure_index=failure_index):
                with tempfile.TemporaryDirectory(prefix="quantum-v39-rollback-") as temporary:
                    destination = Path(temporary)
                    self._extract_v38(destination)
                    before = {
                        relative: (
                            (destination / relative).read_bytes()
                            if (destination / relative).exists()
                            else None
                        )
                        for relative in V39_TRANSITION_FILES
                    }
                    report = install(
                        ROOT,
                        destination,
                        apply=True,
                        _test_fail_after=failure_index,
                        _test_skip_verification=True,
                    )
                    after = {
                        relative: (
                            (destination / relative).read_bytes()
                            if (destination / relative).exists()
                            else None
                        )
                        for relative in V39_TRANSITION_FILES
                    }
                    self.assertFalse(report["valid"])
                    self.assertTrue(report["rolled_back"], report)
                    self.assertTrue(report["preimages_restored"])
                    self.assertEqual(before, after)
                    self.assertFalse((destination / LOCK_NAME).exists())

    def test_real_v38_to_v39_apply_then_reapply_is_noop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v39-e2e-") as temporary:
            destination = Path(temporary)
            self._extract_v38(destination)
            applied = install(
                ROOT,
                destination,
                apply=True,
                _test_skip_verification=True,
            )
            self.assertTrue(applied["valid"], applied)
            self.assertTrue(applied["applied"])
            self.assertEqual(applied["postinstall"]["successor_state"], "V3.9")
            replay = install(ROOT, destination, apply=True)
            self.assertTrue(replay["valid"], replay)
            self.assertTrue(replay["no_op"])
            self.assertFalse(replay["applied"])

    def test_built_archives_have_exact_safe_inventories(self) -> None:
        if not (V39_FULL_ARCHIVE.is_file() and V39_OVERLAY_ARCHIVE.is_file()):
            self.skipTest("V3.9 deployment archives are not built yet.")
        with zipfile.ZipFile(V39_FULL_ARCHIVE) as full:
            full_names = full.namelist()
            self.assertIsNone(full.testzip())
            for name in full_names:
                self.assertEqual(full.read(name), (ROOT / name).read_bytes(), name)
        with zipfile.ZipFile(V39_OVERLAY_ARCHIVE) as overlay:
            overlay_names = overlay.namelist()
            self.assertIsNone(overlay.testzip())
            for name in overlay_names:
                self.assertEqual(overlay.read(name), (ROOT / name).read_bytes(), name)
        self.assertEqual(len(full_names), 130)
        self.assertEqual(len(full_names), len(set(full_names)))
        self.assertEqual(set(full_names), {*self.freeze["frozen_files"], V39_FREEZE_PATH})
        self.assertEqual(overlay_names, list(V39_TRANSITION_FILES))
        for name in [*full_names, *overlay_names]:
            item = Path(name)
            self.assertFalse(item.is_absolute())
            self.assertFalse(any(part in {"", ".", ".."} for part in item.parts))


if __name__ == "__main__":
    unittest.main()
