"""Release-hardening tests for the Quantum Lab V4.2 to V4.3 transition."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest import mock
import zipfile

import install_quantum_lab_v43 as installer
from install_quantum_lab_v43 import (
    EXPECTED_V43_FROZEN_FILE_COUNT,
    EXPECTED_V43_FROZEN_PATHS_FINGERPRINT,
    LOCK_NAME,
    PARENT_FREEZE_PATH,
    PARENT_FREEZE_RAW_SHA256,
    PARENT_FREEZE_SEMANTIC_SHA256,
    PARENT_FROZEN_FILE_COUNT,
    PARENT_FROZEN_PATHS_FINGERPRINT,
    PARENT_IMMUTABLE_FILE_COUNT,
    PARENT_LOCK_NAME,
    README_PATH,
    UI_PATH,
    V43_FREEZE_PATH,
    V43_ONLY_FILES,
    V43_TRANSITION_FILES,
    _canonical_json_sha256,
    _path_fingerprint,
    _read_json_strict,
    _rehash_source,
    _rehash_transition_root,
    _rollback,
    _source_inventory,
    apply_overlay,
    preflight,
)
from .verify_freeze_contract_v43 import verify_freeze_contract
from .verify_phase3_v43 import V43_PATHS, verify_release_chain


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT.parents[1] / "outputs"
V42_ARCHIVE = OUTPUT_ROOT / "Quantum_Lab_V4_2_Institutional_Release.zip"
V43_FULL_ARCHIVE = OUTPUT_ROOT / "Quantum_Lab_V4_3_Institutional_Release.zip"
V43_OVERLAY_ARCHIVE = OUTPUT_ROOT / "Quantum_Lab_V4_3_Deployment_Overlay.zip"


def _safe_extract(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise AssertionError("Archive contains duplicate names.")
        for info in infos:
            name = info.filename
            item = Path(name)
            mode = (info.external_attr >> 16) & 0o170000
            if (
                not name
                or info.is_dir()
                or item.is_absolute()
                or any(part in {"", ".", ".."} for part in item.parts)
                or mode == stat.S_IFLNK
            ):
                raise AssertionError(f"Unsafe archive member: {name}")
            target = destination / item
            target.resolve().relative_to(destination.resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))


def _transition_snapshot(root: Path) -> dict[str, tuple[bool, int | None, str | None]]:
    result: dict[str, tuple[bool, int | None, str | None]] = {}
    for relative in V43_TRANSITION_FILES:
        path = root / relative
        if path.is_file() and not path.is_symlink():
            result[relative] = (
                True,
                stat.S_IMODE(path.stat().st_mode),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        else:
            result[relative] = (False, None, None)
    return result


def _copy_overlay_source(destination: Path) -> Path:
    source = destination / "source"
    source.mkdir()
    for relative in V43_TRANSITION_FILES:
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target, follow_symlinks=False)
    return source


def _fast_commands(
    commands: object,
    cwd: Path,
    *,
    force_failure: bool = False,
) -> dict[str, object]:
    del commands, cwd
    if force_failure:
        raise RuntimeError("Injected V4.3 post-install verification fault.")
    return {"test_fast_path": {"returncode": 0}}


class InstallerV43StaticContractTests(unittest.TestCase):
    def test_01_overlay_is_unique_and_dependency_ordered(self) -> None:
        self.assertEqual(len(V43_TRANSITION_FILES), 18)
        self.assertEqual(len(V43_TRANSITION_FILES), len(set(V43_TRANSITION_FILES)))
        self.assertEqual(V43_TRANSITION_FILES[0], V43_FREEZE_PATH)
        self.assertEqual(V43_TRANSITION_FILES[-2:], (README_PATH, UI_PATH))

    def test_02_inventory_constants_are_final(self) -> None:
        self.assertEqual(EXPECTED_V43_FROZEN_FILE_COUNT, 193)
        self.assertEqual(
            EXPECTED_V43_FROZEN_PATHS_FINGERPRINT,
            "3bc4c8805cf38d5e55c8cc4d1c99cfc3950f9b7faa2cb85fa891fb42987467fc",
        )

    def test_03_exact_v42_parent_constants_match_local_parent(self) -> None:
        parent_path = ROOT / PARENT_FREEZE_PATH
        parent = _read_json_strict(parent_path)
        semantic = _canonical_json_sha256(
            {key: value for key, value in parent.items() if key != "freeze_contract_sha256"}
        )
        self.assertEqual(hashlib.sha256(parent_path.read_bytes()).hexdigest(), PARENT_FREEZE_RAW_SHA256)
        self.assertEqual(semantic, PARENT_FREEZE_SEMANTIC_SHA256)
        self.assertEqual(len(parent["frozen_files"]), PARENT_FROZEN_FILE_COUNT)
        self.assertEqual(PARENT_IMMUTABLE_FILE_COUNT, 175)
        self.assertEqual(_path_fingerprint(parent["frozen_files"]), PARENT_FROZEN_PATHS_FINGERPRINT)

    def test_04_transition_paths_and_freeze_inventory_match(self) -> None:
        freeze = _read_json_strict(ROOT / V43_FREEZE_PATH)
        frozen = freeze["frozen_files"]
        self.assertEqual(len(frozen), 193)
        self.assertEqual(freeze["frozen_file_count"], 193)
        self.assertEqual(_path_fingerprint(frozen), EXPECTED_V43_FROZEN_PATHS_FINGERPRINT)
        self.assertTrue(set(V43_PATHS).issubset(frozen))
        self.assertNotIn(V43_FREEZE_PATH, frozen)
        self.assertEqual(frozen[PARENT_FREEZE_PATH], PARENT_FREEZE_RAW_SHA256)
        self.assertEqual(freeze["validation_targets"]["release_hardening_tests"], 24)

    def test_05_identity_release_and_freeze_verifiers_pass(self) -> None:
        release = verify_release_chain(ROOT, deep=False)
        freeze = verify_freeze_contract(ROOT)
        self.assertTrue(release["valid"], release)
        self.assertEqual(release["check_count"], 32)
        self.assertFalse(release["deep_scientific_replay"])
        self.assertTrue(freeze["valid"], freeze)
        self.assertEqual(freeze["check_count"], 18)

    def test_06_preflight_rejects_same_root_and_broad_root(self) -> None:
        self.assertFalse(preflight(ROOT, ROOT)["valid"])
        self.assertFalse(preflight(ROOT, Path.home())["valid"])

    def test_07_source_snapshot_rehash_rejects_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v43-source-mutation-") as temporary:
            source = _copy_overlay_source(Path(temporary))
            _, rows, errors = _source_inventory(source)
            self.assertFalse(errors, errors)
            commitments = {row["path"]: row["actual_sha256"] for row in rows}
            (source / "DEPLOY_V4_3.md").write_bytes(b"mutated after preflight\n")
            with self.assertRaisesRegex(RuntimeError, "Source changed after preflight"):
                _rehash_source(source, commitments)

    def test_08_stage_or_target_rehash_rejects_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v43-stage-mutation-") as temporary:
            candidate = _copy_overlay_source(Path(temporary))
            _, rows, errors = _source_inventory(candidate)
            self.assertFalse(errors, errors)
            commitments = {row["path"]: row["actual_sha256"] for row in rows}
            (candidate / "DEPLOY_V4_3.md").write_bytes(b"mutated candidate\n")
            with self.assertRaisesRegex(RuntimeError, "transition mismatch"):
                _rehash_transition_root(candidate, commitments, "Candidate")


@unittest.skipUnless(V42_ARCHIVE.is_file(), "Exact V4.2 institutional archive is required")
class InstallerV43TransitionTests(unittest.TestCase):
    def _target(self, temporary: str, suffix: str = "target") -> Path:
        destination = Path(temporary) / suffix
        destination.mkdir()
        _safe_extract(V42_ARCHIVE, destination)
        return destination

    def test_09_exact_v42_target_preflight_passes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v43-preflight-") as temporary:
            destination = self._target(temporary)
            report = preflight(ROOT, destination)
            self.assertTrue(report["valid"], report)
            self.assertEqual(report["target"]["successor_state"], "V4.2")
            self.assertEqual(report["target"]["immutable_v42_file_count"], 175)
            self.assertTrue(report["target"]["immutable_v42_files_exact"])

    def test_10_partial_overlay_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v43-partial-") as temporary:
            destination = self._target(temporary)
            relative = sorted(V43_ONLY_FILES)[0]
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
            report = preflight(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertIn(relative, report["target"]["partial_v43_paths"])

    def test_11_mixed_readme_ui_successor_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v43-mixed-") as temporary:
            destination = self._target(temporary)
            (destination / README_PATH).write_bytes((ROOT / README_PATH).read_bytes())
            report = preflight(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertEqual(report["target"]["successor_state"], "INVALID")

    def test_12_symlinked_overlay_destination_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v43-symlink-") as temporary:
            destination = self._target(temporary)
            relative = "DEPLOY_V4_3.md"
            (destination / relative).symlink_to(destination / "DEPLOY_V4_2.md")
            report = preflight(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertTrue(any("Unsafe overlay destination" in error for error in report["errors"]))

    def test_13_existing_foreign_v43_lock_is_retained(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v43-lock-") as temporary:
            destination = self._target(temporary)
            lock = destination / LOCK_NAME
            lock.write_text('{"token":"foreign"}\n', encoding="utf-8")
            report = apply_overlay(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertEqual(report["status"], "LOCK_ACQUISITION_FAILED")
            self.assertEqual(json.loads(lock.read_text())["token"], "foreign")

    def test_14_residual_parent_lock_is_retained_and_v43_lock_released(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v43-parent-lock-") as temporary:
            destination = self._target(temporary)
            parent_lock = destination / PARENT_LOCK_NAME
            parent_lock.write_text('{"token":"parent"}\n', encoding="utf-8")
            report = apply_overlay(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertEqual(report["status"], "ABORTED_BEFORE_COMMIT")
            self.assertTrue(parent_lock.exists())
            self.assertFalse((destination / LOCK_NAME).exists())

    def test_15_apply_is_exact_audited_and_reapply_is_noop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v43-apply-") as temporary:
            destination = self._target(temporary)
            with mock.patch.object(installer, "_run_commands", side_effect=_fast_commands):
                applied = apply_overlay(ROOT, destination)
            self.assertTrue(applied["valid"], applied)
            self.assertTrue(applied["applied"])
            self.assertEqual(applied["status"], "APPLIED_AND_VERIFIED")
            self.assertEqual(applied["touched_paths"], list(V43_TRANSITION_FILES))
            backup = Path(applied["backup_preserved"])
            self.assertTrue(backup.is_dir())
            for filename, field in (
                ("PREIMAGE_MANIFEST.json", "preimage_manifest_sha256"),
                ("INSTALL_INTENT.json", "install_intent_sha256"),
            ):
                payload = _read_json_strict(backup / filename)
                self.assertEqual(
                    payload[field],
                    _canonical_json_sha256({key: value for key, value in payload.items() if key != field}),
                )
            installed = verify_release_chain(destination, deep=False)
            self.assertTrue(installed["valid"], installed)
            replay = apply_overlay(ROOT, destination)
            self.assertTrue(replay["valid"], replay)
            self.assertFalse(replay["applied"])
            self.assertEqual(replay["status"], "NO_OP_ALREADY_EXACT_V4_3")
            self.assertFalse((destination / LOCK_NAME).exists())

    def test_16_each_of_18_ordered_commit_faults_restores_exact_v42(self) -> None:
        for fault_after in range(1, len(V43_TRANSITION_FILES) + 1):
            with self.subTest(fault_after=fault_after):
                with tempfile.TemporaryDirectory(prefix=f"quantum-v43-fault-{fault_after}-") as temporary:
                    destination = self._target(temporary)
                    before = _transition_snapshot(destination)
                    with mock.patch.object(installer, "_run_commands", side_effect=_fast_commands):
                        failed = apply_overlay(
                            ROOT,
                            destination,
                            force_commit_failure_after=fault_after,
                        )
                    self.assertFalse(failed["valid"], failed)
                    self.assertEqual(failed["status"], "ROLLED_BACK_AFTER_FAILURE")
                    self.assertTrue(failed["rollback"]["preimages_restored"])
                    self.assertTrue(failed["rollback"]["predecessor_reauthenticated"])
                    self.assertEqual(_transition_snapshot(destination), before)
                    self.assertFalse((destination / LOCK_NAME).exists())

    def test_17_postcheck_failure_restores_every_preimage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v43-post-rollback-") as temporary:
            destination = self._target(temporary)
            before = _transition_snapshot(destination)
            with mock.patch.object(installer, "_run_commands", side_effect=_fast_commands):
                failed = apply_overlay(ROOT, destination, force_post_failure=True)
            self.assertFalse(failed["valid"], failed)
            self.assertEqual(failed["status"], "ROLLED_BACK_AFTER_FAILURE")
            self.assertTrue(failed["rollback"]["preimages_restored"])
            self.assertTrue(failed["rollback"]["predecessor_reauthenticated"])
            self.assertEqual(_transition_snapshot(destination), before)

    def test_18_concurrent_future_target_mutation_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v43-concurrent-target-") as temporary:
            destination = self._target(temporary)
            original_atomic_copy = installer._atomic_copy
            calls = 0

            def mutate_after_first(source: Path, target: Path, token: str, label: str) -> None:
                nonlocal calls
                original_atomic_copy(source, target, token, label)
                if label == "commit":
                    calls += 1
                    if calls == 1:
                        external = destination / V43_TRANSITION_FILES[1]
                        external.parent.mkdir(parents=True, exist_ok=True)
                        external.write_bytes(b"external concurrent mutation\n")

            with (
                mock.patch.object(installer, "_atomic_copy", side_effect=mutate_after_first),
                mock.patch.object(installer, "_run_commands", side_effect=_fast_commands),
            ):
                failed = apply_overlay(ROOT, destination)
            self.assertFalse(failed["valid"], failed)
            self.assertEqual(failed["status"], "ROLLBACK_INCOMPLETE")
            self.assertEqual(
                (destination / V43_TRANSITION_FILES[1]).read_bytes(),
                b"external concurrent mutation\n",
            )
            self.assertFalse((destination / LOCK_NAME).exists())

    def test_19_stage_mutation_aborts_before_first_target_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v43-mutated-stage-") as temporary:
            destination = self._target(temporary)
            before = _transition_snapshot(destination)
            original_stage = installer._stage_candidate

            def mutate_stage(source_root: Path, target_root: Path, stage_root: Path, freeze: object) -> dict[str, object]:
                report = original_stage(source_root, target_root, stage_root, freeze)
                (stage_root / "DEPLOY_V4_3.md").write_bytes(b"mutated staged byte\n")
                return report

            with (
                mock.patch.object(installer, "_stage_candidate", side_effect=mutate_stage),
                mock.patch.object(installer, "_run_commands", side_effect=_fast_commands),
            ):
                failed = apply_overlay(ROOT, destination)
            self.assertFalse(failed["valid"], failed)
            self.assertEqual(failed["status"], "ABORTED_BEFORE_COMMIT")
            self.assertEqual(_transition_snapshot(destination), before)

    def test_20_source_mutation_aborts_before_first_target_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v43-mutated-source-") as temporary:
            base = Path(temporary)
            destination = self._target(temporary)
            source = _copy_overlay_source(base)
            before = _transition_snapshot(destination)
            original_stage = installer._stage_candidate

            def mutate_source(source_root: Path, target_root: Path, stage_root: Path, freeze: object) -> dict[str, object]:
                report = original_stage(source_root, target_root, stage_root, freeze)
                (source_root / "DEPLOY_V4_3.md").write_bytes(b"mutated source byte\n")
                return report

            with (
                mock.patch.object(installer, "_stage_candidate", side_effect=mutate_source),
                mock.patch.object(installer, "_run_commands", side_effect=_fast_commands),
            ):
                failed = apply_overlay(source, destination)
            self.assertFalse(failed["valid"], failed)
            self.assertEqual(failed["status"], "ABORTED_BEFORE_COMMIT")
            self.assertEqual(_transition_snapshot(destination), before)

    def test_21_external_mutation_blocks_destructive_rollback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v43-safe-rollback-") as temporary:
            base = Path(temporary)
            target_root = base / "target"
            backup_root = base / "backup"
            relative = README_PATH
            target = target_root / relative
            backup = backup_root / relative
            target.parent.mkdir(parents=True)
            backup.parent.mkdir(parents=True)
            backup.write_bytes(b"parent bytes\n")
            target.write_bytes(b"installed bytes\n")
            preimages = {
                relative: {
                    "existed": True,
                    "mode": stat.S_IMODE(target.stat().st_mode),
                    "sha256": hashlib.sha256(b"parent bytes\n").hexdigest(),
                }
            }
            installed_states = {relative: installer._preimage(target)}
            target.write_bytes(b"external mutation\n")
            report = _rollback(
                target_root,
                backup_root,
                preimages,
                installed_states,
                [relative],
                "test-token",
            )
            self.assertFalse(report["preimages_restored"])
            self.assertEqual(report["external_mutations"], [relative])
            self.assertEqual(target.read_bytes(), b"external mutation\n")

    def test_22_overlay_only_source_applies_without_masking_parent_modules(self) -> None:
        if not V43_OVERLAY_ARCHIVE.is_file():
            self.skipTest("V4.3 deployment overlay is not built yet.")
        with tempfile.TemporaryDirectory(prefix="quantum-v43-overlay-source-") as temporary:
            destination = self._target(temporary)
            source = Path(temporary) / "overlay-source"
            source.mkdir()
            _safe_extract(V43_OVERLAY_ARCHIVE, source)
            source_files = {
                path.relative_to(source).as_posix()
                for path in source.rglob("*")
                if path.is_file()
            }
            self.assertEqual(source_files, set(V43_TRANSITION_FILES))
            with mock.patch.object(installer, "_run_commands", side_effect=_fast_commands):
                applied = apply_overlay(source, destination)
            self.assertTrue(applied["valid"], applied)
            self.assertEqual(applied["status"], "APPLIED_AND_VERIFIED")
            self.assertTrue(verify_release_chain(destination, deep=False)["valid"])


class ArchiveV43Tests(unittest.TestCase):
    def test_23_built_archives_have_exact_safe_inventories(self) -> None:
        if not (V43_FULL_ARCHIVE.is_file() and V43_OVERLAY_ARCHIVE.is_file()):
            self.skipTest("V4.3 deployment archives are not built yet.")
        freeze = _read_json_strict(ROOT / V43_FREEZE_PATH)
        with zipfile.ZipFile(V43_FULL_ARCHIVE) as full:
            full_names = full.namelist()
            self.assertIsNone(full.testzip())
            for name in full_names:
                self.assertEqual(full.read(name), (ROOT / name).read_bytes(), name)
        with zipfile.ZipFile(V43_OVERLAY_ARCHIVE) as overlay:
            overlay_names = overlay.namelist()
            self.assertIsNone(overlay.testzip())
            for name in overlay_names:
                self.assertEqual(overlay.read(name), (ROOT / name).read_bytes(), name)
        self.assertEqual(len(full_names), 194)
        self.assertEqual(len(full_names), len(set(full_names)))
        self.assertEqual(set(full_names), {*freeze["frozen_files"], V43_FREEZE_PATH})
        self.assertEqual(overlay_names, list(V43_TRANSITION_FILES))
        self.assertEqual(len(overlay_names), 18)
        for name in [*full_names, *overlay_names]:
            item = Path(name)
            self.assertFalse(item.is_absolute())
            self.assertFalse(any(part in {"", ".", ".."} for part in item.parts), name)

    def test_24_safe_extract_rejects_duplicate_traversal_and_symlink_members(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v43-unsafe-archive-") as temporary:
            base = Path(temporary)
            duplicate = base / "duplicate.zip"
            with zipfile.ZipFile(duplicate, "w") as archive:
                archive.writestr("same.txt", b"one")
                archive.writestr("same.txt", b"two")
            traversal = base / "traversal.zip"
            with zipfile.ZipFile(traversal, "w") as archive:
                archive.writestr("../escape.txt", b"no")
            symlink = base / "symlink.zip"
            with zipfile.ZipFile(symlink, "w") as archive:
                info = zipfile.ZipInfo("link")
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, "target")
            for archive_path in (duplicate, traversal, symlink):
                with self.subTest(archive=archive_path.name):
                    destination = base / f"extract-{archive_path.stem}"
                    destination.mkdir()
                    with self.assertRaises(AssertionError):
                        _safe_extract(archive_path, destination)


if __name__ == "__main__":
    unittest.main()

