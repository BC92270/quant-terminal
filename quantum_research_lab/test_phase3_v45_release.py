"""Release hardening tests for the Quantum Lab V4.4 to V4.5 transition."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

import build_quantum_lab_v45_release as builder
import install_quantum_lab_v45 as installer
from build_quantum_lab_v45_release import build_release
from install_quantum_lab_v45 import (
    EXPECTED_V45_FROZEN_FILE_COUNT,
    EXPECTED_V45_OVERLAY_ORDER_SHA256,
    EXPECTED_V45_FROZEN_PATHS_FINGERPRINT,
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
    V45_FREEZE_PATH,
    V45_ONLY_FILES,
    V45_TRANSITION_FILES,
    V45_TRANSITION_ORDER_SHA256,
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
from .verify_freeze_contract_v45 import verify_freeze_contract
from .verify_phase3_v45 import V45_FROZEN_TRANSITION_PATHS, verify_release_chain


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT.parents[1] / "outputs"
V44_ARCHIVE = OUTPUT_ROOT / "Quantum_Lab_V4_4_Institutional_Release.zip"
V45_FULL_ARCHIVE = OUTPUT_ROOT / "Quantum_Lab_V4_5_Institutional_Release.zip"
V45_OVERLAY_ARCHIVE = OUTPUT_ROOT / "Quantum_Lab_V4_5_Deployment_Overlay.zip"


def _safe_extract(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise AssertionError("Archive contains duplicate names.")
        for info in infos:
            item = Path(info.filename)
            mode = (info.external_attr >> 16) & 0o170000
            if not info.filename or info.is_dir() or item.is_absolute() or any(part in {"", ".", ".."} for part in item.parts) or mode == stat.S_IFLNK:
                raise AssertionError(f"Unsafe archive member: {info.filename}")
            target = destination / item
            target.resolve().relative_to(destination.resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))


def _transition_snapshot(root: Path) -> dict[str, tuple[bool, int | None, str | None]]:
    result: dict[str, tuple[bool, int | None, str | None]] = {}
    for relative in V45_TRANSITION_FILES:
        path = root / relative
        if path.is_file() and not path.is_symlink():
            result[relative] = (True, stat.S_IMODE(path.stat().st_mode), hashlib.sha256(path.read_bytes()).hexdigest())
        else:
            result[relative] = (False, None, None)
    return result


def _copy_overlay_source(destination: Path) -> Path:
    source = destination / "source"
    source.mkdir()
    for relative in V45_TRANSITION_FILES:
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target, follow_symlinks=False)
    return source


def _fast_commands(commands: object, cwd: Path, *, force_failure: bool = False) -> dict[str, object]:
    del commands, cwd
    if force_failure:
        raise RuntimeError("Injected V4.5 post-install verification fault.")
    return {"test_fast_path": {"returncode": 0}}


class InstallerV45StaticContractTests(unittest.TestCase):
    def test_01_overlay_is_unique_and_dependency_ordered(self) -> None:
        self.assertEqual(len(V45_TRANSITION_FILES), 20)
        self.assertEqual(len(V45_TRANSITION_FILES), len(set(V45_TRANSITION_FILES)))
        self.assertEqual(tuple(builder.V45_TRANSITION_FILES), V45_TRANSITION_FILES)
        self.assertEqual(V45_TRANSITION_FILES[0], V45_FREEZE_PATH)
        self.assertEqual(V45_TRANSITION_FILES[-2:], (README_PATH, UI_PATH))
        self.assertEqual(V45_TRANSITION_ORDER_SHA256, EXPECTED_V45_OVERLAY_ORDER_SHA256)

    def test_02_inventory_constants_are_final(self) -> None:
        self.assertEqual(EXPECTED_V45_FROZEN_FILE_COUNT, 229)
        self.assertEqual(EXPECTED_V45_FROZEN_PATHS_FINGERPRINT, "1c81474eee596a857d099c7882ddb02d409a620a2ddf311f25c783c491370d14")

    def test_03_exact_v44_parent_constants_match_archive_and_local_parent(self) -> None:
        self.assertTrue(V44_ARCHIVE.is_file(), "Exact V4.4 institutional archive is required; missing archives never skip.")
        parent_path = ROOT / PARENT_FREEZE_PATH
        parent = _read_json_strict(parent_path)
        self.assertEqual(PARENT_FREEZE_RAW_SHA256, "f7b4507410aee41e409b3a0a1ce36ba1adff38299dc8a2d424e13885598ada13")
        self.assertEqual(PARENT_FREEZE_SEMANTIC_SHA256, "e17aa8ce04c97416f7f0565f2eda4f16b739c5c921fb58ee25752a546ffe95b3")
        self.assertEqual(PARENT_FROZEN_FILE_COUNT, 211)
        self.assertEqual(hashlib.sha256(parent_path.read_bytes()).hexdigest(), PARENT_FREEZE_RAW_SHA256)
        self.assertEqual(_canonical_json_sha256({key: value for key, value in parent.items() if key != "freeze_contract_sha256"}), PARENT_FREEZE_SEMANTIC_SHA256)
        self.assertEqual(len(parent["frozen_files"]), PARENT_FROZEN_FILE_COUNT)
        self.assertEqual(PARENT_IMMUTABLE_FILE_COUNT, 209)
        self.assertEqual(_path_fingerprint(parent["frozen_files"]), PARENT_FROZEN_PATHS_FINGERPRINT)

    def test_04_transition_paths_and_freeze_inventory_match(self) -> None:
        freeze = _read_json_strict(ROOT / V45_FREEZE_PATH)
        frozen = freeze["frozen_files"]
        self.assertEqual(len(frozen), 229)
        self.assertEqual(freeze["frozen_file_count"], 229)
        self.assertEqual(_path_fingerprint(frozen), EXPECTED_V45_FROZEN_PATHS_FINGERPRINT)
        self.assertTrue(set(V45_FROZEN_TRANSITION_PATHS).issubset(frozen))
        self.assertNotIn(V45_FREEZE_PATH, frozen)
        self.assertEqual(frozen[PARENT_FREEZE_PATH], PARENT_FREEZE_RAW_SHA256)

    def test_05_identity_release_and_freeze_verifiers_pass(self) -> None:
        release = verify_release_chain(ROOT, deep=False)
        freeze = verify_freeze_contract(ROOT)
        self.assertTrue(release["valid"], release)
        self.assertEqual(release["check_count"], 36)
        self.assertFalse(release["deep_scientific_replay"])
        self.assertTrue(freeze["valid"], freeze)
        self.assertEqual(freeze["check_count"], 18)

    def test_06_preflight_rejects_same_root_and_broad_root(self) -> None:
        self.assertFalse(preflight(ROOT, ROOT)["valid"])
        self.assertFalse(preflight(ROOT, Path.home())["valid"])

    def test_07_source_snapshot_rehash_rejects_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v45-source-mutation-") as temporary:
            source = _copy_overlay_source(Path(temporary))
            _, rows, errors = _source_inventory(source)
            self.assertFalse(errors, errors)
            commitments = {row["path"]: row["actual_sha256"] for row in rows}
            (source / "DEPLOY_V4_5.md").write_bytes(b"mutated after preflight\n")
            with self.assertRaisesRegex(RuntimeError, "Source changed after preflight"):
                _rehash_source(source, commitments)

    def test_08_stage_or_target_rehash_rejects_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v45-stage-mutation-") as temporary:
            candidate = _copy_overlay_source(Path(temporary))
            _, rows, errors = _source_inventory(candidate)
            self.assertFalse(errors, errors)
            commitments = {row["path"]: row["actual_sha256"] for row in rows}
            (candidate / "DEPLOY_V4_5.md").write_bytes(b"mutated candidate\n")
            with self.assertRaisesRegex(RuntimeError, "transition mismatch"):
                _rehash_transition_root(candidate, commitments, "Candidate")

    def test_09_source_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v45-source-symlink-") as temporary:
            source = _copy_overlay_source(Path(temporary))
            path = source / "DEPLOY_V4_5.md"
            path.unlink()
            path.symlink_to(source / "install_quantum_lab_v45.py")
            _, _, errors = _source_inventory(source)
            self.assertTrue(any("DEPLOY_V4_5.md" in error for error in errors))

    def test_10_installer_has_no_provider_or_network_client_import(self) -> None:
        tree = ast.parse((ROOT / "install_quantum_lab_v45.py").read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        self.assertFalse({"qiskit_ibm_runtime", "requests", "httpx", "boto3"} & {name.split(".")[0] for name in modules})


class InstallerV45TransitionTests(unittest.TestCase):
    def _target(self, temporary: str, suffix: str = "target") -> Path:
        self.assertTrue(V44_ARCHIVE.is_file(), "Exact V4.4 institutional archive is required; missing archives never skip.")
        destination = Path(temporary) / suffix
        destination.mkdir()
        _safe_extract(V44_ARCHIVE, destination)
        return destination

    def test_11_exact_v44_target_preflight_passes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v45-preflight-") as temporary:
            destination = self._target(temporary)
            report = preflight(ROOT, destination)
            self.assertTrue(report["valid"], report)
            self.assertEqual(report["target"]["successor_state"], "V4.4")
            self.assertEqual(report["target"]["immutable_v44_file_count"], 209)

    def test_12_partial_overlay_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v45-partial-") as temporary:
            destination = self._target(temporary)
            relative = sorted(V45_ONLY_FILES)[0]
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
            report = preflight(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertIn(relative, report["target"]["partial_v45_paths"])

    def test_13_mixed_readme_ui_successor_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v45-mixed-") as temporary:
            destination = self._target(temporary)
            (destination / README_PATH).write_bytes((ROOT / README_PATH).read_bytes())
            report = preflight(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertEqual(report["target"]["successor_state"], "INVALID")

    def test_14_symlinked_overlay_destination_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v45-destination-symlink-") as temporary:
            destination = self._target(temporary)
            (destination / "DEPLOY_V4_5.md").symlink_to(destination / "DEPLOY_V4_4.md")
            report = preflight(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertTrue(any("Unsafe overlay destination" in error for error in report["errors"]))

    def test_15_existing_foreign_v45_lock_is_retained(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v45-lock-") as temporary:
            destination = self._target(temporary)
            lock = destination / LOCK_NAME
            lock.write_text('{"token":"foreign"}\n', encoding="utf-8")
            report = apply_overlay(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertEqual(report["status"], "LOCK_ACQUISITION_FAILED")
            self.assertEqual(json.loads(lock.read_text())["token"], "foreign")

    def test_16_residual_parent_lock_is_retained_and_v45_lock_released(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v45-parent-lock-") as temporary:
            destination = self._target(temporary)
            parent_lock = destination / PARENT_LOCK_NAME
            parent_lock.write_text('{"token":"parent"}\n', encoding="utf-8")
            report = apply_overlay(ROOT, destination)
            self.assertFalse(report["valid"])
            self.assertEqual(report["status"], "ABORTED_BEFORE_COMMIT")
            self.assertTrue(parent_lock.exists())
            self.assertFalse((destination / LOCK_NAME).exists())

    def test_17_apply_is_exact_audited_and_reapply_is_noop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v45-apply-") as temporary:
            destination = self._target(temporary)
            with mock.patch.object(installer, "_run_commands", side_effect=_fast_commands):
                applied = apply_overlay(ROOT, destination)
            self.assertTrue(applied["valid"], applied)
            self.assertEqual(applied["status"], "APPLIED_AND_VERIFIED")
            self.assertEqual(applied["touched_paths"], list(V45_TRANSITION_FILES))
            backup = Path(applied["backup_preserved"])
            self.assertTrue(backup.is_dir())
            for filename, field in (("PREIMAGE_MANIFEST.json", "preimage_manifest_sha256"), ("INSTALL_INTENT.json", "install_intent_sha256")):
                payload = _read_json_strict(backup / filename)
                self.assertEqual(payload[field], _canonical_json_sha256({key: value for key, value in payload.items() if key != field}))
            self.assertTrue(verify_release_chain(destination, deep=False)["valid"])
            replay = apply_overlay(ROOT, destination)
            self.assertTrue(replay["valid"], replay)
            self.assertEqual(replay["status"], "NO_OP_ALREADY_EXACT_V4_5")
            self.assertFalse((destination / LOCK_NAME).exists())

    def test_18_each_of_20_ordered_commit_faults_restores_exact_v44(self) -> None:
        for fault_after in range(1, len(V45_TRANSITION_FILES) + 1):
            with self.subTest(fault_after=fault_after):
                with tempfile.TemporaryDirectory(prefix=f"quantum-v45-fault-{fault_after}-") as temporary:
                    destination = self._target(temporary)
                    before = _transition_snapshot(destination)
                    with mock.patch.object(installer, "_run_commands", side_effect=_fast_commands):
                        failed = apply_overlay(ROOT, destination, force_commit_failure_after=fault_after)
                    self.assertFalse(failed["valid"], failed)
                    self.assertEqual(failed["status"], "ROLLED_BACK_AFTER_FAILURE")
                    self.assertTrue(failed["rollback"]["preimages_restored"])
                    self.assertTrue(failed["rollback"]["predecessor_reauthenticated"])
                    self.assertEqual(_transition_snapshot(destination), before)

    def test_19_postcheck_failure_restores_every_preimage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v45-post-rollback-") as temporary:
            destination = self._target(temporary)
            before = _transition_snapshot(destination)
            with mock.patch.object(installer, "_run_commands", side_effect=_fast_commands):
                failed = apply_overlay(ROOT, destination, force_post_failure=True)
            self.assertFalse(failed["valid"], failed)
            self.assertEqual(failed["status"], "ROLLED_BACK_AFTER_FAILURE")
            self.assertEqual(_transition_snapshot(destination), before)

    def test_20_concurrent_future_target_mutation_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v45-concurrent-") as temporary:
            destination = self._target(temporary)
            original = installer._atomic_copy
            calls = 0

            def mutate(source: Path, target: Path, token: str, label: str) -> None:
                nonlocal calls
                original(source, target, token, label)
                if label == "commit":
                    calls += 1
                    if calls == 1:
                        external = destination / V45_TRANSITION_FILES[1]
                        external.parent.mkdir(parents=True, exist_ok=True)
                        external.write_bytes(b"external concurrent mutation\n")

            with mock.patch.object(installer, "_atomic_copy", side_effect=mutate), mock.patch.object(installer, "_run_commands", side_effect=_fast_commands):
                failed = apply_overlay(ROOT, destination)
            self.assertFalse(failed["valid"], failed)
            self.assertEqual(failed["status"], "ROLLBACK_INCOMPLETE")
            self.assertEqual((destination / V45_TRANSITION_FILES[1]).read_bytes(), b"external concurrent mutation\n")

    def test_21_stage_mutation_aborts_before_first_target_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v45-mutated-stage-") as temporary:
            destination = self._target(temporary)
            before = _transition_snapshot(destination)
            original_stage = installer._stage_candidate

            def mutate_stage(source_root: Path, target_root: Path, stage_root: Path, freeze: object) -> dict[str, object]:
                report = original_stage(source_root, target_root, stage_root, freeze)
                (stage_root / "DEPLOY_V4_5.md").write_bytes(b"mutated staged byte\n")
                return report

            with mock.patch.object(installer, "_stage_candidate", side_effect=mutate_stage), mock.patch.object(installer, "_run_commands", side_effect=_fast_commands):
                failed = apply_overlay(ROOT, destination)
            self.assertFalse(failed["valid"], failed)
            self.assertEqual(failed["status"], "ABORTED_BEFORE_COMMIT")
            self.assertEqual(_transition_snapshot(destination), before)

    def test_22_source_mutation_aborts_before_first_target_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v45-mutated-source-") as temporary:
            base = Path(temporary)
            destination = self._target(temporary)
            source = _copy_overlay_source(base)
            before = _transition_snapshot(destination)
            original_stage = installer._stage_candidate

            def mutate_source(source_root: Path, target_root: Path, stage_root: Path, freeze: object) -> dict[str, object]:
                report = original_stage(source_root, target_root, stage_root, freeze)
                (source_root / "DEPLOY_V4_5.md").write_bytes(b"mutated source byte\n")
                return report

            with mock.patch.object(installer, "_stage_candidate", side_effect=mutate_source), mock.patch.object(installer, "_run_commands", side_effect=_fast_commands):
                failed = apply_overlay(source, destination)
            self.assertFalse(failed["valid"], failed)
            self.assertEqual(failed["status"], "ABORTED_BEFORE_COMMIT")
            self.assertEqual(_transition_snapshot(destination), before)

    def test_23_external_mutation_blocks_destructive_rollback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v45-safe-rollback-") as temporary:
            base = Path(temporary)
            target_root = base / "target"
            backup_root = base / "backup"
            target = target_root / README_PATH
            backup = backup_root / README_PATH
            target.parent.mkdir(parents=True)
            backup.parent.mkdir(parents=True)
            backup.write_bytes(b"parent bytes\n")
            target.write_bytes(b"installed bytes\n")
            preimages = {README_PATH: {"existed": True, "mode": stat.S_IMODE(target.stat().st_mode), "sha256": hashlib.sha256(b"parent bytes\n").hexdigest()}}
            installed_states = {README_PATH: installer._preimage(target)}
            target.write_bytes(b"external mutation\n")
            report = _rollback(target_root, backup_root, preimages, installed_states, [README_PATH], "test-token")
            self.assertFalse(report["preimages_restored"])
            self.assertEqual(report["external_mutations"], [README_PATH])
            self.assertEqual(target.read_bytes(), b"external mutation\n")

    def test_24_overlay_only_source_applies_without_masking_parent_modules(self) -> None:
        self.assertTrue(V45_OVERLAY_ARCHIVE.is_file(), "V4.5 overlay archive must exist; no skip is permitted.")
        with tempfile.TemporaryDirectory(prefix="quantum-v45-overlay-source-") as temporary:
            destination = self._target(temporary)
            source = Path(temporary) / "overlay-source"
            source.mkdir()
            _safe_extract(V45_OVERLAY_ARCHIVE, source)
            source_files = {path.relative_to(source).as_posix() for path in source.rglob("*") if path.is_file()}
            self.assertEqual(source_files, set(V45_TRANSITION_FILES))
            with mock.patch.object(installer, "_run_commands", side_effect=_fast_commands):
                applied = apply_overlay(source, destination)
            self.assertTrue(applied["valid"], applied)
            self.assertTrue(verify_release_chain(destination, deep=False)["valid"])


class ArchiveV45Tests(unittest.TestCase):
    def test_25_built_archives_have_exact_safe_inventories(self) -> None:
        self.assertTrue(V45_FULL_ARCHIVE.is_file() and V45_OVERLAY_ARCHIVE.is_file(), "Both V4.5 archives are mandatory.")
        freeze = _read_json_strict(ROOT / V45_FREEZE_PATH)
        with zipfile.ZipFile(V45_FULL_ARCHIVE) as full:
            full_names = full.namelist()
            self.assertIsNone(full.testzip())
            for name in full_names:
                self.assertEqual(full.read(name), (ROOT / name).read_bytes(), name)
        with zipfile.ZipFile(V45_OVERLAY_ARCHIVE) as overlay:
            overlay_names = overlay.namelist()
            self.assertIsNone(overlay.testzip())
            for name in overlay_names:
                self.assertEqual(overlay.read(name), (ROOT / name).read_bytes(), name)
        self.assertEqual(len(full_names), 230)
        self.assertEqual(set(full_names), {*freeze["frozen_files"], V45_FREEZE_PATH})
        self.assertEqual(overlay_names, list(V45_TRANSITION_FILES))
        self.assertEqual(
            hashlib.sha256(json.dumps(overlay_names, separators=(",", ":")).encode("utf-8")).hexdigest(),
            EXPECTED_V45_OVERLAY_ORDER_SHA256,
        )
        for name in [*full_names, *overlay_names]:
            item = Path(name)
            self.assertFalse(item.is_absolute())
            self.assertFalse(any(part in {"", ".", ".."} for part in item.parts), name)

    def test_26_safe_extract_rejects_duplicate_traversal_and_symlink_members(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v45-unsafe-archive-") as temporary:
            base = Path(temporary)
            duplicate = base / "duplicate.zip"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
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

    def test_27_deterministic_builder_repeats_identically(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v45-build-a-") as first_dir, tempfile.TemporaryDirectory(prefix="quantum-v45-build-b-") as second_dir:
            first = build_release(ROOT, first_dir)
            second = build_release(ROOT, second_dir)
            self.assertTrue(first["valid"] and second["valid"])
            self.assertEqual(first["overlay_order_sha256"], EXPECTED_V45_OVERLAY_ORDER_SHA256)
            self.assertEqual(second["overlay_order_sha256"], EXPECTED_V45_OVERLAY_ORDER_SHA256)
            for name in (builder.INSTITUTIONAL_ARCHIVE, builder.OVERLAY_ARCHIVE):
                first_path = Path(first_dir) / name
                second_path = Path(second_dir) / name
                self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
                self.assertTrue(first["archives"][name]["double_build_identical"])

    def test_28_builder_fails_hard_on_missing_payload_or_tampered_freeze(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantum-v45-missing-source-") as temporary:
            fake_root = Path(temporary) / "root"
            fake_root.mkdir()
            shutil.copy2(ROOT / V45_FREEZE_PATH, fake_root / V45_FREEZE_PATH)
            with self.assertRaises((FileNotFoundError, ValueError)):
                build_release(fake_root, Path(temporary) / "out")
        with tempfile.TemporaryDirectory(prefix="quantum-v45-tampered-freeze-") as temporary:
            fake_root = Path(temporary) / "root"
            shutil.copytree(ROOT, fake_root)
            freeze_path = fake_root / V45_FREEZE_PATH
            freeze = _read_json_strict(freeze_path)
            freeze["created_utc"] = "TAMPERED"
            freeze_path.write_text(
                json.dumps(freeze, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "freeze identity"):
                build_release(fake_root, Path(temporary) / "out-tampered")


if __name__ == "__main__":
    unittest.main()
