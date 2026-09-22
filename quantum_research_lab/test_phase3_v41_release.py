"""Release-hardening tests for the Quantum Lab V4.0 -> V4.1 transition."""

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

from install_quantum_lab_v41 import (
    EXPECTED_V41_FROZEN_FILE_COUNT,
    EXPECTED_V41_FROZEN_PATHS_FINGERPRINT,
    LOCK_NAME,
    PARENT_FREEZE_RAW_SHA256,
    PARENT_FREEZE_SEMANTIC_SHA256,
    PARENT_FROZEN_FILE_COUNT,
    PARENT_FROZEN_PATHS_FINGERPRINT,
    PARENT_README_SHA256,
    PARENT_UI_SHA256,
    README_PATH,
    UI_PATH,
    V41_FREEZE_PATH,
    V41_ONLY_FILES,
    V41_TRANSITION_FILES,
    _canonical_json_sha256,
    _contained,
    _path_fingerprint,
    _read_json_strict,
    install,
    preflight,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT.parents[1] / "outputs"
V40_ARCHIVE = OUTPUT_ROOT / "Quantum_Lab_V4_0_Institutional_Release.zip"
V41_FULL_ARCHIVE = OUTPUT_ROOT / "Quantum_Lab_V4_1_Institutional_Release.zip"
V41_OVERLAY_ARCHIVE = OUTPUT_ROOT / "Quantum_Lab_V4_1_Deployment_Overlay.zip"

EXPECTED_TRANSITION_FILES = (
    "FREEZE_CONTRACT_V4_1.json",
    "DEPLOY_V4_1.md",
    "app_v41_offline_harness.py",
    "install_quantum_lab_v41.py",
    "outputs/quantum_phase3/v41_certified_bridge/SEALED_V4_1_CERTIFIED_BRIDGE_COMPILER_ARTIFACT.json",
    "quantum_research_lab/PHASE_III_V4_1_CERTIFIED_BRIDGE_COMPILER_SPEC_V1.json",
    "quantum_research_lab/QUANTUM_LAB_V4_1_ARCHITECTURE.md",
    "quantum_research_lab/phase3_v41_bridge_engine.cpp",
    "quantum_research_lab/phase3_v41_certified_bridge_compiler.py",
    "quantum_research_lab/phase3_v41_ui.py",
    "quantum_research_lab/phase3_v41_validation.py",
    "quantum_research_lab/test_phase3_v41.py",
    "quantum_research_lab/test_phase3_v41_release.py",
    "quantum_research_lab/verify_freeze_contract_v41.py",
    "quantum_research_lab/verify_phase3_v41.py",
    "quantum_research_lab/verify_phase3_v41_ui.py",
    "quantum_research_lab/README.md",
    "quantum_research_lab/ui.py",
)
EXPECTED_V41_FINGERPRINT = (
    "27bb43b53f3c6847d1ef80518c595755c1e606015b423c194c8a2e61f3f76ea8"
)


def _safe_extract(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise AssertionError("Archive contains duplicate names.")
        for name in names:
            item = Path(name)
            if item.is_absolute() or any(
                part in {"", ".", ".."} for part in item.parts
            ):
                raise AssertionError(f"Unsafe archive member: {name}")
            target = (destination / item).resolve()
            target.relative_to(destination.resolve())
        archive.extractall(destination)


def _transition_snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        relative: (
            (root / relative).read_bytes()
            if (root / relative).is_file() and not (root / relative).is_symlink()
            else None
        )
        for relative in V41_TRANSITION_FILES
    }


class InstallerV41StaticContractTests(unittest.TestCase):
    def test_overlay_is_exact_unique_and_in_dependency_order(self) -> None:
        self.assertEqual(V41_TRANSITION_FILES, EXPECTED_TRANSITION_FILES)
        self.assertEqual(len(V41_TRANSITION_FILES), 18)
        self.assertEqual(len(V41_TRANSITION_FILES), len(set(V41_TRANSITION_FILES)))
        self.assertEqual(V41_TRANSITION_FILES[-2:], (README_PATH, UI_PATH))
        self.assertEqual(V41_TRANSITION_FILES[0], V41_FREEZE_PATH)

    def test_v41_inventory_constants_are_final(self) -> None:
        self.assertEqual(EXPECTED_V41_FROZEN_FILE_COUNT, 161)
        self.assertEqual(
            EXPECTED_V41_FROZEN_PATHS_FINGERPRINT,
            EXPECTED_V41_FINGERPRINT,
        )

    def test_exact_parent_v40_constants_match_local_parent(self) -> None:
        parent_path = ROOT / "FREEZE_CONTRACT_V4_0.json"
        parent = _read_json_strict(parent_path)
        semantic = _canonical_json_sha256(
            {
                key: value
                for key, value in parent.items()
                if key != "freeze_contract_sha256"
            }
        )
        self.assertEqual(
            hashlib.sha256(parent_path.read_bytes()).hexdigest(),
            PARENT_FREEZE_RAW_SHA256,
        )
        self.assertEqual(semantic, PARENT_FREEZE_SEMANTIC_SHA256)
        self.assertEqual(parent["freeze_contract_sha256"], semantic)
        self.assertEqual(parent["frozen_file_count"], PARENT_FROZEN_FILE_COUNT)
        self.assertEqual(len(parent["frozen_files"]), PARENT_FROZEN_FILE_COUNT)
        self.assertEqual(
            _path_fingerprint(parent["frozen_files"]),
            PARENT_FROZEN_PATHS_FINGERPRINT,
        )
        self.assertEqual(parent["frozen_files"][README_PATH], PARENT_README_SHA256)
        self.assertEqual(parent["frozen_files"][UI_PATH], PARENT_UI_SHA256)

    def test_duplicate_nonfinite_traversal_and_symlink_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v41-strict-") as temporary:
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
        with tempfile.TemporaryDirectory(prefix="quantum-v41-lock-") as temporary:
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


class FrozenV41ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        required = (
            ROOT / V41_FREEZE_PATH,
            ROOT / "install_quantum_lab_v41.py",
            ROOT / "quantum_research_lab/verify_phase3_v41.py",
            ROOT / "quantum_research_lab/verify_freeze_contract_v41.py",
        )
        if not all(path.is_file() for path in required):
            raise unittest.SkipTest(
                "V4.1 freeze, installer and release verifiers are not assembled yet."
            )
        cls.freeze = _read_json_strict(ROOT / V41_FREEZE_PATH)

    def _copy_release(self, destination: Path) -> None:
        for relative in [*self.freeze["frozen_files"], V41_FREEZE_PATH]:
            source = ROOT / relative
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def _extract_v40(self, destination: Path) -> None:
        if not V40_ARCHIVE.is_file():
            self.skipTest("Institutional V4.0 predecessor archive is unavailable.")
        _safe_extract(V40_ARCHIVE, destination)

    def test_release_chain_and_freeze_pass(self) -> None:
        from .verify_freeze_contract_v41 import verify_freeze_contract
        from .verify_phase3_v41 import verify_release_chain

        release = verify_release_chain(ROOT, deep=False)
        freeze = verify_freeze_contract(ROOT, ROOT / V41_FREEZE_PATH)
        self.assertTrue(release["valid"], release)
        self.assertEqual(release["check_count"], 29)
        self.assertTrue(freeze["valid"], freeze)
        self.assertEqual(freeze["check_count"], 18)

    def test_inventory_self_hash_and_all_raw_hashes_are_exact(self) -> None:
        frozen = self.freeze["frozen_files"]
        self.assertEqual(len(frozen), EXPECTED_V41_FROZEN_FILE_COUNT)
        self.assertEqual(
            self.freeze["frozen_file_count"], EXPECTED_V41_FROZEN_FILE_COUNT
        )
        self.assertEqual(
            _path_fingerprint(frozen), EXPECTED_V41_FROZEN_PATHS_FINGERPRINT
        )
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
        self.assertTrue(
            set(V41_TRANSITION_FILES) - {V41_FREEZE_PATH} <= set(frozen)
        )
        self.assertEqual(
            frozen["FREEZE_CONTRACT_V4_0.json"], PARENT_FREEZE_RAW_SHA256
        )
        self.assertNotIn(V41_FREEZE_PATH, frozen)

    def test_clean_extract_is_self_contained(self) -> None:
        from .verify_freeze_contract_v41 import verify_freeze_contract
        from .verify_phase3_v41 import verify_release_chain

        with tempfile.TemporaryDirectory(prefix="quantum-v41-clean-") as temporary:
            destination = Path(temporary)
            self._copy_release(destination)
            release = verify_release_chain(destination, deep=False)
            freeze = verify_freeze_contract(
                destination, destination / V41_FREEZE_PATH
            )
            self.assertTrue(release["valid"], release)
            self.assertTrue(freeze["valid"], freeze)

            environment = os.environ.copy()
            environment.pop("PYTHONPATH", None)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            isolated = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "quantum_research_lab.verify_phase3_v41",
                    ".",
                    "--identity-only",
                ],
                cwd=destination,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=240,
            )
            self.assertEqual(
                isolated.returncode, 0, isolated.stdout + isolated.stderr
            )
            isolated_report = json.loads(isolated.stdout)
            self.assertTrue(isolated_report["valid"], isolated_report)

    def test_exact_reapplication_is_noop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v41-noop-") as temporary:
            destination = Path(temporary)
            self._copy_release(destination)
            before = _transition_snapshot(destination)
            report = install(ROOT, destination, apply=True)
            self.assertTrue(report["valid"], report)
            self.assertTrue(report["no_op"])
            self.assertFalse(report["applied"])
            self.assertEqual(report["postinstall"]["successor_state"], "V4.1")
            self.assertEqual(before, _transition_snapshot(destination))
            self.assertFalse((destination / LOCK_NAME).exists())

    def test_unknown_or_mixed_successor_surface_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v41-mixed-") as temporary:
            destination = Path(temporary)
            self._copy_release(destination)
            (destination / README_PATH).write_text(
                "unauthorized successor\n", encoding="utf-8"
            )
            report = preflight(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertEqual(report["target"]["successor_state"], "INVALID")

    def test_symlinked_overlay_destination_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v41-link-") as temporary:
            destination = Path(temporary)
            self._copy_release(destination)
            victim = destination / "DEPLOY_V4_1.md"
            victim.unlink()
            victim.symlink_to(destination / V41_FREEZE_PATH)
            report = preflight(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertTrue(
                any(
                    "Unsafe overlay destination" in error
                    for error in report.get("errors", [])
                ),
                report,
            )

    def test_partial_v41_overlay_on_v40_surface_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v41-partial-") as temporary:
            destination = Path(temporary)
            self._extract_v40(destination)
            relative = "DEPLOY_V4_1.md"
            self.assertIn(relative, V41_ONLY_FILES)
            source = ROOT / relative
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            report = preflight(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertEqual(report["target"]["successor_state"], "V4.0")
            self.assertIn(relative, report["target"]["partial_v41_paths"])

    def test_staged_source_race_is_rejected_before_commit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v41-source-race-") as temporary:
            base = Path(temporary)
            source = base / "source"
            target = base / "target"
            source.mkdir()
            target.mkdir()
            self._copy_release(source)
            self._extract_v40(target)
            before = _transition_snapshot(target)

            def mutate(candidate: Path, _stage: Path) -> None:
                with (candidate / "DEPLOY_V4_1.md").open("ab") as handle:
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
            self.assertEqual(before, _transition_snapshot(target))
            self.assertFalse((target / LOCK_NAME).exists())

    def test_target_race_after_preimages_is_rejected_before_commit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v41-target-race-") as temporary:
            target = Path(temporary)
            self._extract_v40(target)
            marker = b"\nexternal-target-race"

            def mutate(candidate: Path, _backup: Path) -> None:
                with (candidate / README_PATH).open("ab") as handle:
                    handle.write(marker)

            report = install(
                ROOT,
                target,
                apply=True,
                _test_after_preimages=mutate,
                _test_skip_verification=True,
            )
            self.assertFalse(report["valid"])
            self.assertIn(
                "Target changed after preimage capture", report.get("error", "")
            )
            self.assertTrue((target / README_PATH).read_bytes().endswith(marker))
            self.assertTrue(
                all(
                    not (target / relative).exists()
                    and not (target / relative).is_symlink()
                    for relative in V41_ONLY_FILES
                )
            )
            self.assertFalse((target / LOCK_NAME).exists())

    def test_partial_commit_faults_restore_exact_v40_preimages(self) -> None:
        self.assertEqual(len(V41_TRANSITION_FILES), 18)
        for failure_index in (1, 16, 18):
            with self.subTest(failure_index=failure_index):
                with tempfile.TemporaryDirectory(
                    prefix="quantum-v41-rollback-"
                ) as temporary:
                    destination = Path(temporary)
                    self._extract_v40(destination)
                    before = _transition_snapshot(destination)
                    report = install(
                        ROOT,
                        destination,
                        apply=True,
                        _test_fail_after=failure_index,
                        _test_skip_verification=True,
                    )
                    after = _transition_snapshot(destination)
                    self.assertFalse(report["valid"])
                    self.assertTrue(report["rolled_back"], report)
                    self.assertTrue(report["preimages_restored"])
                    self.assertEqual(
                        len(report["applied_files_before_failure"]), failure_index
                    )
                    self.assertEqual(
                        report["rollback"]["successor_state"], "V4.0"
                    )
                    self.assertEqual(before, after)
                    self.assertFalse((destination / LOCK_NAME).exists())

    def test_real_v40_archive_to_v41_apply_then_reapply_is_noop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v41-e2e-") as temporary:
            destination = Path(temporary)
            self._extract_v40(destination)
            initial = preflight(ROOT, destination)
            self.assertTrue(initial["valid"], initial)
            self.assertEqual(initial["target"]["successor_state"], "V4.0")

            # The hook avoids recursively launching this release-test module
            # from the installer's own validation ladder. The real 18-file
            # stage, preimage capture, atomic commit and authentication still run.
            applied = install(
                ROOT,
                destination,
                apply=True,
                _test_skip_verification=True,
            )
            self.assertTrue(applied["valid"], applied)
            self.assertTrue(applied["applied"])
            self.assertFalse(applied["no_op"])
            self.assertEqual(applied["applied_files"], list(V41_TRANSITION_FILES))
            self.assertTrue(applied["readme_committed_penultimate"])
            self.assertTrue(applied["ui_committed_last"])
            self.assertEqual(applied["postinstall"]["successor_state"], "V4.1")
            self.assertTrue(applied["postinstall"]["exact_overlay"])

            replay = install(ROOT, destination, apply=True)
            self.assertTrue(replay["valid"], replay)
            self.assertTrue(replay["no_op"])
            self.assertFalse(replay["applied"])
            self.assertEqual(replay["postinstall"]["successor_state"], "V4.1")
            self.assertFalse((destination / LOCK_NAME).exists())

    def test_built_archives_have_exact_safe_inventories(self) -> None:
        if not (V41_FULL_ARCHIVE.is_file() and V41_OVERLAY_ARCHIVE.is_file()):
            self.skipTest("V4.1 deployment archives are not built yet.")

        with zipfile.ZipFile(V41_FULL_ARCHIVE) as full:
            full_names = full.namelist()
            self.assertIsNone(full.testzip())
            for name in full_names:
                self.assertEqual(full.read(name), (ROOT / name).read_bytes(), name)

        with zipfile.ZipFile(V41_OVERLAY_ARCHIVE) as overlay:
            overlay_names = overlay.namelist()
            self.assertIsNone(overlay.testzip())
            for name in overlay_names:
                self.assertEqual(overlay.read(name), (ROOT / name).read_bytes(), name)

        self.assertEqual(len(full_names), 162)
        self.assertEqual(len(full_names), len(set(full_names)))
        self.assertEqual(
            set(full_names), {*self.freeze["frozen_files"], V41_FREEZE_PATH}
        )
        self.assertEqual(len(overlay_names), 18)
        self.assertEqual(overlay_names, list(V41_TRANSITION_FILES))
        for name in [*full_names, *overlay_names]:
            item = Path(name)
            self.assertFalse(item.is_absolute())
            self.assertFalse(
                any(part in {"", ".", ".."} for part in item.parts), name
            )


if __name__ == "__main__":
    unittest.main()
