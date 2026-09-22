"""Release-hardening tests for the Quantum Lab V4.1 to V4.2 transition."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from install_quantum_lab_v42 import (
    EXPECTED_V42_FROZEN_FILE_COUNT,
    EXPECTED_V42_FROZEN_PATHS_FINGERPRINT,
    LOCK_NAME,
    PARENT_FREEZE_RAW_SHA256,
    PARENT_FREEZE_SEMANTIC_SHA256,
    PARENT_FROZEN_FILE_COUNT,
    PARENT_FROZEN_PATHS_FINGERPRINT,
    README_PATH,
    UI_PATH,
    V42_FREEZE_PATH,
    V42_ONLY_FILES,
    V42_TRANSITION_FILES,
    _canonical_json_sha256,
    _path_fingerprint,
    _read_json_strict,
    apply_overlay,
    preflight,
)
from .verify_freeze_contract_v42 import verify_freeze_contract
from .verify_phase3_v42 import V42_PATHS, verify_release_chain


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT.parents[1] / "outputs"
V41_ARCHIVE = OUTPUT_ROOT / "Quantum_Lab_V4_1_Institutional_Release.zip"
V42_FULL_ARCHIVE = OUTPUT_ROOT / "Quantum_Lab_V4_2_Institutional_Release.zip"
V42_OVERLAY_ARCHIVE = OUTPUT_ROOT / "Quantum_Lab_V4_2_Deployment_Overlay.zip"


def _safe_extract(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise AssertionError("Archive contains duplicate names.")
        for name in names:
            item = Path(name)
            if item.is_absolute() or any(part in {"", ".", ".."} for part in item.parts):
                raise AssertionError(f"Unsafe archive member: {name}")
            (destination / item).resolve().relative_to(destination.resolve())
        archive.extractall(destination)


def _transition_snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        relative: (
            (root / relative).read_bytes()
            if (root / relative).is_file() and not (root / relative).is_symlink()
            else None
        )
        for relative in V42_TRANSITION_FILES
    }


class InstallerV42StaticContractTests(unittest.TestCase):
    def test_overlay_is_unique_and_dependency_ordered(self) -> None:
        self.assertEqual(len(V42_TRANSITION_FILES), 18)
        self.assertEqual(len(V42_TRANSITION_FILES), len(set(V42_TRANSITION_FILES)))
        self.assertEqual(V42_TRANSITION_FILES[0], V42_FREEZE_PATH)
        self.assertEqual(V42_TRANSITION_FILES[-2:], (README_PATH, UI_PATH))

    def test_inventory_constants_are_final(self) -> None:
        self.assertEqual(EXPECTED_V42_FROZEN_FILE_COUNT, 177)
        self.assertEqual(
            EXPECTED_V42_FROZEN_PATHS_FINGERPRINT,
            "cc3dd736d2475cfc1d143bc720fc37863d62ede26019a3aa99cd33e96643b166",
        )

    def test_exact_v41_parent_constants_match_local_parent(self) -> None:
        parent_path = ROOT / "FREEZE_CONTRACT_V4_1.json"
        parent = _read_json_strict(parent_path)
        semantic = _canonical_json_sha256(
            {key: value for key, value in parent.items() if key != "freeze_contract_sha256"}
        )
        self.assertEqual(hashlib.sha256(parent_path.read_bytes()).hexdigest(), PARENT_FREEZE_RAW_SHA256)
        self.assertEqual(semantic, PARENT_FREEZE_SEMANTIC_SHA256)
        self.assertEqual(len(parent["frozen_files"]), PARENT_FROZEN_FILE_COUNT)
        self.assertEqual(_path_fingerprint(parent["frozen_files"]), PARENT_FROZEN_PATHS_FINGERPRINT)

    def test_transition_paths_and_freeze_inventory_match(self) -> None:
        freeze = _read_json_strict(ROOT / V42_FREEZE_PATH)
        frozen = freeze["frozen_files"]
        self.assertEqual(len(frozen), 177)
        self.assertEqual(freeze["frozen_file_count"], 177)
        self.assertEqual(_path_fingerprint(frozen), EXPECTED_V42_FROZEN_PATHS_FINGERPRINT)
        self.assertTrue(set(V42_PATHS).issubset(frozen))
        self.assertNotIn(V42_FREEZE_PATH, frozen)
        self.assertEqual(frozen["FREEZE_CONTRACT_V4_1.json"], PARENT_FREEZE_RAW_SHA256)
        self.assertEqual(freeze["validation_targets"]["release_hardening_tests"], 15)

    def test_identity_release_and_freeze_verifiers_pass(self) -> None:
        release = verify_release_chain(ROOT, deep=False)
        freeze = verify_freeze_contract(ROOT)
        self.assertTrue(release["valid"], release)
        self.assertEqual(release["check_count"], 32)
        self.assertFalse(release["deep_scientific_replay"])
        self.assertTrue(freeze["valid"], freeze)
        self.assertEqual(freeze["check_count"], 18)

    def test_preflight_rejects_same_root_and_broad_root(self) -> None:
        same = preflight(ROOT, ROOT)
        broad = preflight(ROOT, Path.home())
        self.assertFalse(same["valid"])
        self.assertFalse(broad["valid"])


@unittest.skipUnless(V41_ARCHIVE.is_file(), "Exact V4.1 institutional archive is required")
class InstallerV42TransitionTests(unittest.TestCase):
    def _target(self, temporary: str) -> Path:
        destination = Path(temporary) / "target"
        destination.mkdir()
        _safe_extract(V41_ARCHIVE, destination)
        return destination

    def test_exact_v41_target_preflight_passes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v42-preflight-") as temporary:
            destination = self._target(temporary)
            report = preflight(ROOT, destination)
            self.assertTrue(report["valid"], report)
            self.assertEqual(report["target"]["successor_state"], "V4.1")
            self.assertEqual(report["target"]["immutable_v41_file_count"], 159)
            self.assertTrue(report["target"]["immutable_v41_files_exact"])

    def test_partial_overlay_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v42-partial-") as temporary:
            destination = self._target(temporary)
            relative = sorted(V42_ONLY_FILES)[0]
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
            report = preflight(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertIn(relative, report["target"]["partial_v42_paths"])

    def test_mixed_readme_ui_successor_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v42-mixed-") as temporary:
            destination = self._target(temporary)
            (destination / README_PATH).write_bytes((ROOT / README_PATH).read_bytes())
            report = preflight(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertEqual(report["target"]["successor_state"], "INVALID")

    def test_symlinked_overlay_destination_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v42-symlink-") as temporary:
            destination = self._target(temporary)
            relative = "DEPLOY_V4_2.md"
            (destination / relative).symlink_to(destination / "DEPLOY_V4_1.md")
            report = preflight(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertTrue(any("Unsafe overlay destination" in error or "Partial V4.2" in error for error in report["errors"]))

    def test_apply_is_exact_and_reapply_is_noop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v42-apply-") as temporary:
            destination = self._target(temporary)
            applied = apply_overlay(ROOT, destination, run_post_checks=False)
            self.assertTrue(applied["valid"], applied)
            self.assertTrue(applied["applied"])
            self.assertEqual(applied["status"], "APPLIED_AND_VERIFIED")
            installed = verify_release_chain(destination, deep=False)
            self.assertTrue(installed["valid"], installed)
            replay = apply_overlay(ROOT, destination, run_post_checks=False)
            self.assertTrue(replay["valid"], replay)
            self.assertFalse(replay["applied"])
            self.assertEqual(replay["status"], "NO_OP_ALREADY_EXACT_V4_2")
            self.assertFalse((destination / LOCK_NAME).exists())

    def test_overlay_only_source_applies_without_masking_parent_modules(self) -> None:
        if not V42_OVERLAY_ARCHIVE.is_file():
            self.skipTest("V4.2 deployment overlay is not built yet.")
        with tempfile.TemporaryDirectory(prefix="quantum-v42-overlay-source-") as temporary:
            destination = self._target(temporary)
            source = Path(temporary) / "source"
            source.mkdir()
            _safe_extract(V42_OVERLAY_ARCHIVE, source)
            source_files = {
                path.relative_to(source).as_posix()
                for path in source.rglob("*")
                if path.is_file()
            }
            self.assertEqual(source_files, set(V42_TRANSITION_FILES))
            applied = apply_overlay(source, destination, run_post_checks=False)
            self.assertTrue(applied["valid"], applied)
            self.assertEqual(applied["status"], "APPLIED_AND_VERIFIED")
            installed = verify_release_chain(destination, deep=False)
            self.assertTrue(installed["valid"], installed)

    def test_postcheck_failure_restores_every_preimage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v42-rollback-") as temporary:
            destination = self._target(temporary)
            before = _transition_snapshot(destination)
            failed = apply_overlay(
                ROOT,
                destination,
                run_post_checks=True,
                force_post_failure=True,
            )
            self.assertFalse(failed["valid"], failed)
            self.assertEqual(failed["status"], "ROLLED_BACK_AFTER_FAILURE")
            self.assertTrue(failed["rollback"]["preimages_restored"])
            self.assertEqual(_transition_snapshot(destination), before)
            self.assertFalse((destination / LOCK_NAME).exists())

    def test_existing_foreign_lock_is_not_removed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v42-lock-") as temporary:
            destination = self._target(temporary)
            lock = destination / LOCK_NAME
            lock.write_text('{"token":"foreign"}\n', encoding="utf-8")
            report = apply_overlay(ROOT, destination, run_post_checks=False)
            self.assertFalse(report["valid"])
            self.assertEqual(report["status"], "ABORTED_BEFORE_COMMIT")
            self.assertTrue(lock.exists())
            self.assertEqual(json.loads(lock.read_text())["token"], "foreign")


class ArchiveV42Tests(unittest.TestCase):
    def test_built_archives_have_exact_safe_inventories(self) -> None:
        if not (V42_FULL_ARCHIVE.is_file() and V42_OVERLAY_ARCHIVE.is_file()):
            self.skipTest("V4.2 deployment archives are not built yet.")
        freeze = _read_json_strict(ROOT / V42_FREEZE_PATH)
        with zipfile.ZipFile(V42_FULL_ARCHIVE) as full:
            full_names = full.namelist()
            self.assertIsNone(full.testzip())
            for name in full_names:
                self.assertEqual(full.read(name), (ROOT / name).read_bytes(), name)
        with zipfile.ZipFile(V42_OVERLAY_ARCHIVE) as overlay:
            overlay_names = overlay.namelist()
            self.assertIsNone(overlay.testzip())
            for name in overlay_names:
                self.assertEqual(overlay.read(name), (ROOT / name).read_bytes(), name)
        self.assertEqual(len(full_names), 178)
        self.assertEqual(len(full_names), len(set(full_names)))
        self.assertEqual(set(full_names), {*freeze["frozen_files"], V42_FREEZE_PATH})
        self.assertEqual(overlay_names, list(V42_TRANSITION_FILES))
        self.assertEqual(len(overlay_names), 18)
        for name in [*full_names, *overlay_names]:
            item = Path(name)
            self.assertFalse(item.is_absolute())
            self.assertFalse(any(part in {"", ".", ".."} for part in item.parts), name)


if __name__ == "__main__":
    unittest.main()
