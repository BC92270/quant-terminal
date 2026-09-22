"""Release, packaging and transactional hardening tests for Quantum Lab V4.7."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import zipfile

from build_quantum_lab_v47_release import (
    EXPECTED_RELEASE_HARDENING_TEST_COUNT,
    _load_validation_report,
    _write_deterministic_zip,
)
import install_quantum_lab_v47 as installer
from install_quantum_lab_v47 import (
    EXPECTED_V47_FROZEN_FILE_COUNT,
    EXPECTED_V47_FROZEN_PATHS_FINGERPRINT,
    EXPECTED_V47_OVERLAY_ORDER_SHA256,
    FAULT_PHASES,
    README_PATH,
    UI_PATH,
    V47_FREEZE_PATH,
    V47_TRANSITION_FILES,
    _source_inventory,
    apply_overlay,
    authenticate_target,
    preflight,
    source_tree_raw_sha256,
)
from .phase3_v47_validation import (
    EXPECTED_CHECK_COUNT as EXPECTED_SCIENTIFIC_CHECK_COUNT,
    canonical_json_sha256,
    read_json_strict,
    run_v47_validation,
)
from .verify_freeze_contract_v47 import (
    ARTIFACT_PATH,
    EXPECTED_FREEZE_CHECK_COUNT,
    VALIDATION_REPORT_PATH,
    verify_freeze_contract,
)
from .verify_phase3_v47 import (
    EXPECTED_RELEASE_CHECK_COUNT,
    verify_release_chain,
)


ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_OUTPUTS = ROOT.parents[1] / "outputs"
V46_ARCHIVE = Path(
    os.environ.get(
        "QUANTUM_LAB_V46_ARCHIVE",
        str(EXTERNAL_OUTPUTS / "Quantum_Lab_V4_6_Institutional_Release.zip"),
    )
).expanduser().resolve()
EXPECTED_V46_ARCHIVE_RAW_SHA256 = (
    "bb21a0ee147734b0d4fa3585c96740fd7fcb2a57a966dade9db6f43aec9390ba"
)


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _extract_archive_safely(archive_path: Path, destination: Path) -> Path:
    if not archive_path.is_file():
        raise AssertionError(f"Exact V4.6 institutional fixture unavailable: {archive_path}")
    observed_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if observed_sha256 != EXPECTED_V46_ARCHIVE_RAW_SHA256:
        raise AssertionError(
            "Exact V4.6 institutional fixture identity mismatch: "
            f"{observed_sha256}"
        )
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise AssertionError("Duplicate fixture members")
        for info in infos:
            item = Path(info.filename)
            mode = info.external_attr >> 16
            if (
                not info.filename
                or item.is_absolute()
                or any(part in {"", ".", ".."} for part in item.parts)
                or (mode and (mode & 0o170000) == 0o120000)
            ):
                raise AssertionError(f"Unsafe V4.6 fixture member: {info.filename}")
        archive.extractall(destination)
    return destination


def _v46_target(destination: Path) -> Path:
    return _extract_archive_safely(V46_ARCHIVE, destination)


def _v47_target(destination: Path) -> Path:
    freeze = read_json_strict(ROOT / V47_FREEZE_PATH)
    destination.mkdir(parents=True, exist_ok=True)
    for relative in freeze["frozen_files"]:
        _copy_file(ROOT / relative, destination / relative)
    _copy_file(ROOT / V47_FREEZE_PATH, destination / V47_FREEZE_PATH)
    return destination


def _sparse_v47_source(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    for relative in V47_TRANSITION_FILES:
        _copy_file(ROOT / relative, destination / relative)
    return destination


def _source_pin(source: Path) -> str:
    return source_tree_raw_sha256(source)


def _fake_candidate(*_args: object, **_kwargs: object) -> tuple[Path, dict[str, object]]:
    stage = Path(tempfile.mkdtemp(prefix="quantum-v47-test-candidate."))
    return stage, {
        "passed": True,
        "counts": {"checks_total": EXPECTED_SCIENTIFIC_CHECK_COUNT},
    }


class QuantumLabV47ReleaseTests(unittest.TestCase):
    def test_01_transition_inventory_is_exactly_ordered(self) -> None:
        self.assertEqual(len(V47_TRANSITION_FILES), 25)
        observed = hashlib.sha256(
            json.dumps(list(V47_TRANSITION_FILES), separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(observed, EXPECTED_V47_OVERLAY_ORDER_SHA256)

    def test_02_readme_and_ui_are_committed_last(self) -> None:
        self.assertEqual(V47_TRANSITION_FILES[-2:], (README_PATH, UI_PATH))

    def test_03_freeze_self_hash_count_and_fingerprint_are_exact(self) -> None:
        freeze = read_json_strict(ROOT / V47_FREEZE_PATH)
        semantic = canonical_json_sha256(
            {key: value for key, value in freeze.items() if key != "freeze_contract_sha256"}
        )
        fingerprint = hashlib.sha256(
            json.dumps(sorted(freeze["frozen_files"]), separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(freeze["freeze_contract_sha256"], semantic)
        self.assertEqual(freeze["frozen_file_count"], EXPECTED_V47_FROZEN_FILE_COUNT)
        self.assertEqual(fingerprint, EXPECTED_V47_FROZEN_PATHS_FINGERPRINT)

    def test_04_source_inventory_authenticates_every_overlay_path(self) -> None:
        freeze, rows, errors = _source_inventory(ROOT)
        self.assertFalse(errors, errors)
        self.assertEqual(freeze["frozen_file_count"], EXPECTED_V47_FROZEN_FILE_COUNT)
        self.assertEqual(len(rows), len(V47_TRANSITION_FILES))
        self.assertTrue(all(row["valid"] for row in rows))
        self.assertEqual({row["lineage_mode"] for row in rows}, {"FULL_SOURCE"})

    def test_05_freeze_verifier_passes_all_checks(self) -> None:
        report = verify_freeze_contract(ROOT)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["check_count"], EXPECTED_FREEZE_CHECK_COUNT)

    def test_06_release_identity_verifier_passes_20_checks(self) -> None:
        artifact = read_json_strict(ROOT / ARTIFACT_PATH)
        report = verify_release_chain(
            ROOT,
            deep=False,
            expected_artifact_raw_sha256=hashlib.sha256((ROOT / ARTIFACT_PATH).read_bytes()).hexdigest(),
            expected_artifact_sha256=artifact["artifact_sha256"],
        )
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["counts"]["checks_total"], EXPECTED_RELEASE_CHECK_COUNT)

    def test_07_release_deep_verifier_passes_20_checks(self) -> None:
        artifact = read_json_strict(ROOT / ARTIFACT_PATH)
        report = verify_release_chain(
            ROOT,
            deep=True,
            expected_artifact_raw_sha256=hashlib.sha256((ROOT / ARTIFACT_PATH).read_bytes()).hexdigest(),
            expected_artifact_sha256=artifact["artifact_sha256"],
        )
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["counts"]["checks_total"], EXPECTED_RELEASE_CHECK_COUNT)

    def test_08_scientific_validation_passes_96_checks(self) -> None:
        artifact = read_json_strict(ROOT / ARTIFACT_PATH)
        report = run_v47_validation(
            root=ROOT,
            expected_artifact_raw_sha256=hashlib.sha256((ROOT / ARTIFACT_PATH).read_bytes()).hexdigest(),
            expected_artifact_sha256=artifact["artifact_sha256"],
        )
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["counts"]["checks_total"], EXPECTED_SCIENTIFIC_CHECK_COUNT)

    def test_09_validation_report_is_self_hashed_and_byte_exact(self) -> None:
        path = ROOT / VALIDATION_REPORT_PATH
        report = read_json_strict(path)
        core = {
            key: value
            for key, value in report.items()
            if key != "sealed_validation_evidence_sha256"
        }
        self.assertEqual(
            report["sealed_validation_evidence_sha256"],
            canonical_json_sha256(core),
        )
        self.assertTrue(report["scientific_validation"]["passed"])
        self.assertTrue(report["clean_process_replay"]["performed"])
        self.assertTrue(
            report["clean_process_replay"]["byte_for_byte_equal_to_sealed_artifact"]
        )

        with tempfile.TemporaryDirectory() as temporary:
            tampered = dict(report)
            tampered["artifact_raw_file_sha256"] = "0" * 64
            tampered["sealed_validation_evidence_sha256"] = canonical_json_sha256(
                {
                    key: value
                    for key, value in tampered.items()
                    if key != "sealed_validation_evidence_sha256"
                }
            )
            tampered_path = Path(temporary) / "self-consistent-stale-report.json"
            tampered_path.write_text(
                json.dumps(
                    tampered,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n",
                encoding="utf-8",
            )
            artifact = read_json_strict(ROOT / ARTIFACT_PATH)
            scientific = run_v47_validation(root=ROOT)
            with self.assertRaises(ValueError):
                _load_validation_report(
                    tampered_path,
                    artifact_raw_sha256=hashlib.sha256(
                        (ROOT / ARTIFACT_PATH).read_bytes()
                    ).hexdigest(),
                    artifact_sha256=artifact["artifact_sha256"],
                    scientific_validation=scientific,
                )

    def test_10_artifact_identities_are_retained_in_freeze(self) -> None:
        freeze = read_json_strict(ROOT / V47_FREEZE_PATH)
        artifact = read_json_strict(ROOT / ARTIFACT_PATH)
        identities = freeze["v47_identities"]
        self.assertEqual(
            identities["artifact_raw_file_sha256"],
            hashlib.sha256((ROOT / ARTIFACT_PATH).read_bytes()).hexdigest(),
        )
        self.assertEqual(identities["artifact_sha256"], artifact["artifact_sha256"])

    def test_11_deterministic_zip_double_build_is_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first, second = Path(temporary) / "a.zip", Path(temporary) / "b.zip"
            names = (V47_FREEZE_PATH, "DEPLOY_V4_7.md")
            _write_deterministic_zip(ROOT, names, first)
            _write_deterministic_zip(ROOT, names, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_12_duplicate_archive_members_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                _write_deterministic_zip(
                    ROOT,
                    (V47_FREEZE_PATH, V47_FREEZE_PATH),
                    Path(temporary) / "bad.zip",
                )

    def test_13_archive_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                _write_deterministic_zip(ROOT, ("../outside",), Path(temporary) / "bad.zip")

    def test_14_symlinked_archive_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            root.mkdir()
            os.symlink(ROOT / "DEPLOY_V4_7.md", root / "linked.md")
            with self.assertRaises(ValueError):
                _write_deterministic_zip(root, ("linked.md",), Path(temporary) / "bad.zip")

    def test_15_same_source_and_target_are_rejected(self) -> None:
        report = preflight(
            ROOT,
            ROOT,
            expected_source_tree_raw_sha256=_source_pin(ROOT),
        )
        self.assertFalse(report["valid"])
        self.assertIn("Source and target must be distinct.", report["errors"])

    def test_16_exact_v47_target_is_a_valid_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = _v47_target(Path(temporary) / "target")
            report = apply_overlay(
                ROOT,
                target,
                expected_source_tree_raw_sha256=_source_pin(ROOT),
            )
            self.assertTrue(report["valid"], report)
            self.assertTrue(report["idempotent_no_op"])
            self.assertFalse(report["applied"])

    def test_17_exact_v47_target_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = _v47_target(Path(temporary) / "target")
            (target / "DEPLOY_V4_7.md").write_text("tampered", encoding="utf-8")
            report = preflight(
                ROOT,
                target,
                expected_source_tree_raw_sha256=_source_pin(ROOT),
            )
            self.assertFalse(report["valid"])
            self.assertTrue(any("mismatch" in error.lower() for error in report["errors"]))

        with tempfile.TemporaryDirectory() as temporary:
            target = _v47_target(Path(temporary) / "target")
            freeze_path = target / V47_FREEZE_PATH
            freeze = read_json_strict(freeze_path)
            freeze_path.write_text(
                json.dumps(
                    freeze,
                    separators=(",", ":"),
                    sort_keys=True,
                    ensure_ascii=False,
                    allow_nan=False,
                ),
                encoding="utf-8",
            )
            report = preflight(
                ROOT,
                target,
                expected_source_tree_raw_sha256=_source_pin(ROOT),
            )
            self.assertFalse(report["valid"], report)
            self.assertTrue(
                any(
                    f"Exact V4.7 target mismatch: {V47_FREEZE_PATH}" in error
                    for error in report["errors"]
                ),
                report,
            )

    def test_18_symlinked_source_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            shutil.copytree(ROOT, source, symlinks=True)
            victim = source / "DEPLOY_V4_7.md"
            victim.unlink()
            os.symlink(ROOT / "DEPLOY_V4_7.md", victim)
            _, _, errors = _source_inventory(source)
            self.assertTrue(errors)

    def test_19_tampered_source_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = Path(temporary) / "source"
            shutil.copytree(ROOT, source, symlinks=True)
            original_pin = _source_pin(source)
            (source / "DEPLOY_V4_7.md").write_text("tampered", encoding="utf-8")
            _, _, errors = _source_inventory(source)
            self.assertTrue(any("mismatch" in error.lower() for error in errors))

            # A self-consistent attacker can update the changed member digest
            # and recompute the freeze self-hash.  The independent raw-tree pin
            # must still reject that newly self-signed source before executing
            # its validator.
            freeze_path = source / V47_FREEZE_PATH
            freeze = read_json_strict(freeze_path)
            freeze["frozen_files"]["DEPLOY_V4_7.md"] = hashlib.sha256(
                (source / "DEPLOY_V4_7.md").read_bytes()
            ).hexdigest()
            freeze["freeze_contract_sha256"] = canonical_json_sha256(
                {
                    key: value
                    for key, value in freeze.items()
                    if key != "freeze_contract_sha256"
                }
            )
            freeze_path.write_text(
                json.dumps(
                    freeze,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n",
                encoding="utf-8",
            )
            _, _, resealed_errors = _source_inventory(source)
            self.assertFalse(resealed_errors, resealed_errors)
            target = _v46_target(base / "target")
            report = preflight(
                source,
                target,
                expected_source_tree_raw_sha256=original_pin,
            )
            self.assertFalse(report["valid"], report)
            self.assertTrue(
                any("source-tree raw identity mismatch" in error for error in report["errors"]),
                report,
            )

    def test_20_partial_v47_state_on_v46_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = _v46_target(Path(temporary) / "target")
            _copy_file(ROOT / "DEPLOY_V4_7.md", target / "DEPLOY_V4_7.md")
            report = authenticate_target(
                ROOT,
                target,
                expected_source_tree_raw_sha256=_source_pin(ROOT),
            )
            self.assertFalse(report["valid"])
            self.assertIn("DEPLOY_V4_7.md", report["partial_v47_paths"])

    def test_21_all_25_commit_fault_positions_restore_exact_v46(self) -> None:
        with mock.patch.object(installer, "_build_candidate", side_effect=_fake_candidate):
            for position in range(1, len(V47_TRANSITION_FILES) + 1):
                with self.subTest(position=position), tempfile.TemporaryDirectory() as temporary:
                    target = _v46_target(Path(temporary) / "target")
                    source_pin = _source_pin(ROOT)
                    report = apply_overlay(
                        ROOT,
                        target,
                        expected_source_tree_raw_sha256=source_pin,
                        fault_after=position,
                    )
                    self.assertFalse(report["valid"], report)
                    self.assertTrue(report.get("rolled_back"), report)
                    restored = authenticate_target(
                        ROOT,
                        target,
                        expected_source_tree_raw_sha256=source_pin,
                    )
                    self.assertTrue(restored["valid"], restored)
                    self.assertEqual(restored["state"], "V4.6")

            with self.subTest(phase="partial_commit_copy"), tempfile.TemporaryDirectory() as temporary:
                target = _v46_target(Path(temporary) / "target")
                source_pin = _source_pin(ROOT)
                real_copy2 = installer.shutil.copy2

                def fail_partial_commit_copy(source: Path, destination: Path, *args: object, **kwargs: object) -> Path:
                    target_path = Path(destination)
                    if ".v47-" in target_path.name and target_path.name.endswith(".tmp"):
                        target_path.write_bytes(b"partial")
                        raise OSError("injected partial commit copy")
                    return real_copy2(source, destination, *args, **kwargs)

                with mock.patch.object(
                    installer.shutil,
                    "copy2",
                    side_effect=fail_partial_commit_copy,
                ):
                    report = apply_overlay(
                        ROOT,
                        target,
                        expected_source_tree_raw_sha256=source_pin,
                    )
                self.assertFalse(report["valid"], report)
                self.assertTrue(report.get("rolled_back"), report)
                self.assertFalse(list(target.rglob(".*.tmp")))
                restored = authenticate_target(
                    ROOT,
                    target,
                    expected_source_tree_raw_sha256=source_pin,
                )
                self.assertTrue(restored["valid"], restored)
                self.assertEqual(restored["state"], "V4.6")

            with self.subTest(phase="partial_rollback_replace"), tempfile.TemporaryDirectory() as temporary:
                target = _v46_target(Path(temporary) / "target")
                source_pin = _source_pin(ROOT)
                real_replace = installer.os.replace

                def fail_rollback_replace(source: Path, destination: Path) -> None:
                    if ".rollback-" in Path(source).name:
                        raise OSError("injected rollback replace")
                    real_replace(source, destination)

                with mock.patch.object(
                    installer.os,
                    "replace",
                    side_effect=fail_rollback_replace,
                ):
                    report = apply_overlay(
                        ROOT,
                        target,
                        expected_source_tree_raw_sha256=source_pin,
                        fault_after=len(V47_TRANSITION_FILES),
                    )
                self.assertFalse(report["valid"], report)
                self.assertFalse(report.get("rolled_back"), report)
                self.assertTrue(report.get("rollback_errors"), report)
                self.assertFalse(list(target.rglob(".*.tmp")))

    def test_22_all_phase_faults_restore_exact_v46(self) -> None:
        with mock.patch.object(installer, "_build_candidate", side_effect=_fake_candidate):
            for phase in sorted(FAULT_PHASES):
                with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary:
                    target = _v46_target(Path(temporary) / "target")
                    source_pin = _source_pin(ROOT)
                    report = apply_overlay(
                        ROOT,
                        target,
                        expected_source_tree_raw_sha256=source_pin,
                        fault_phase=phase,
                    )
                    self.assertFalse(report["valid"], report)
                    self.assertTrue(report.get("rolled_back"), report)
                    restored = authenticate_target(
                        ROOT,
                        target,
                        expected_source_tree_raw_sha256=source_pin,
                    )
                    self.assertTrue(restored["valid"], restored)
                    self.assertEqual(restored["state"], "V4.6")

    def test_23_exact_v46_target_promotes_with_real_candidate_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = _v46_target(Path(temporary) / "target")
            source_pin = _source_pin(ROOT)
            report = apply_overlay(
                ROOT,
                target,
                expected_source_tree_raw_sha256=source_pin,
            )
            self.assertTrue(report["valid"], report)
            self.assertTrue(report["applied"])
            self.assertEqual(
                authenticate_target(
                    ROOT,
                    target,
                    expected_source_tree_raw_sha256=source_pin,
                )["state"],
                "V4.7",
            )

    def test_24_successful_apply_emits_manifest_and_then_no_ops(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            installer,
            "_build_candidate",
            side_effect=_fake_candidate,
        ):
            target = _v46_target(Path(temporary) / "target")
            source_pin = _source_pin(ROOT)
            first = apply_overlay(
                ROOT,
                target,
                expected_source_tree_raw_sha256=source_pin,
            )
            self.assertTrue(first["valid"], first)
            manifest = Path(first["manifest"]["backup_directory"]) / "deployment-manifest.json"
            self.assertTrue(manifest.is_file())
            second = apply_overlay(
                ROOT,
                target,
                expected_source_tree_raw_sha256=source_pin,
            )
            self.assertTrue(second["valid"], second)
            self.assertTrue(second["idempotent_no_op"])

    def test_25_residual_predecessor_lock_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            installer,
            "_build_candidate",
            side_effect=_fake_candidate,
        ):
            target = _v46_target(Path(temporary) / "target")
            (target / ".quantum-lab-v46-install.lock").mkdir()
            report = apply_overlay(
                ROOT,
                target,
                expected_source_tree_raw_sha256=_source_pin(ROOT),
            )
            self.assertFalse(report["valid"])
            self.assertTrue(any("Residual predecessor" in error for error in report["errors"]))

    def test_26_predecessor_is_reauthenticated_under_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            installer,
            "_build_candidate",
            side_effect=_fake_candidate,
        ):
            target = _v46_target(Path(temporary) / "target")
            original = installer.authenticate_target
            calls = 0

            def changing_target(
                source: Path,
                destination: Path,
                **kwargs: object,
            ) -> dict[str, object]:
                nonlocal calls
                calls += 1
                if calls == 2:
                    return {"valid": False, "state": "INVALID", "errors": ["injected drift"]}
                return original(source, destination, **kwargs)

            with mock.patch.object(installer, "authenticate_target", side_effect=changing_target):
                source_pin = _source_pin(ROOT)
                report = apply_overlay(
                    ROOT,
                    target,
                    expected_source_tree_raw_sha256=source_pin,
                )
            self.assertFalse(report["valid"])
            self.assertIn("predecessor changed before commit", report["errors"][0].lower())
            self.assertEqual(
                original(
                    ROOT,
                    target,
                    expected_source_tree_raw_sha256=source_pin,
                )["state"],
                "V4.6",
            )

    def test_27_source_is_rehashed_under_lock_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            installer,
            "_build_candidate",
            side_effect=_fake_candidate,
        ):
            target = _v46_target(Path(temporary) / "target")
            original = installer._transition_root
            calls = 0

            def changing_source(source: Path, *predecessor: Path) -> str:
                nonlocal calls
                calls += 1
                digest = original(source, *predecessor)
                return "0" * 64 if calls == 2 else digest

            with mock.patch.object(installer, "_transition_root", side_effect=changing_source):
                source_pin = _source_pin(ROOT)
                report = apply_overlay(
                    ROOT,
                    target,
                    expected_source_tree_raw_sha256=source_pin,
                )
            self.assertFalse(report["valid"])
            self.assertIn("source changed after preflight", report["errors"][0].lower())
            self.assertEqual(
                authenticate_target(
                    ROOT,
                    target,
                    expected_source_tree_raw_sha256=source_pin,
                )["state"],
                "V4.6",
            )

    def test_28_installer_has_no_provider_or_network_client_import(self) -> None:
        self.assertEqual(EXPECTED_RELEASE_HARDENING_TEST_COUNT, 29)
        builder_source = (ROOT / "build_quantum_lab_v47_release.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("--skip-ui", builder_source)
        self.assertNotIn("--skip-tests", builder_source)
        self.assertNotIn("--seal-only", builder_source)
        tree = ast.parse((ROOT / "install_quantum_lab_v47.py").read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
        self.assertTrue(
            {"qiskit", "qiskit_ibm_runtime", "requests", "httpx", "urllib"}.isdisjoint(modules)
        )
        with mock.patch.dict(
            os.environ,
            {
                "IBM_QUANTUM_TOKEN": "must-not-leak",
                "QISKIT_IBM_TOKEN": "must-not-leak",
                "UNRELATED_SECRET": "must-not-leak",
            },
            clear=False,
        ):
            candidate_env = installer._candidate_environment(ROOT)
        self.assertEqual(
            set(candidate_env),
            {
                "LANG",
                "LC_ALL",
                "PYTHONHASHSEED",
                "PYTHONNOUSERSITE",
                "PYTHONDONTWRITEBYTECODE",
                "PYTHONPATH",
                "TZ",
            },
        )
        self.assertFalse(any("TOKEN" in key or "SECRET" in key for key in candidate_env))
        static_report = installer._candidate_static_boundary(ROOT)
        self.assertEqual(set(static_report), set(installer.CANDIDATE_EXECUTED_PYTHON_PATHS))

    def test_29_sparse_deployment_overlay_preflights_applies_and_no_ops(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = _sparse_v47_source(base / "source")
            target = _v46_target(base / "target")
            source_pin = _source_pin(source)
            report = preflight(
                source,
                target,
                expected_source_tree_raw_sha256=source_pin,
            )
            self.assertTrue(report["valid"], report)
            self.assertTrue(report["candidate_validation"]["performed"])
            self.assertEqual(report["candidate_validation"]["scientific_checks"], 96)
            self.assertEqual(report["source_lineage_mode"], "SPARSE_TARGET_PREDECESSOR")
            self.assertTrue(report["candidate_validation"]["static_offline_boundary"])
            with mock.patch.object(installer, "_build_candidate", side_effect=_fake_candidate):
                applied = apply_overlay(
                    source,
                    target,
                    expected_source_tree_raw_sha256=source_pin,
                )
            self.assertTrue(applied["valid"], applied)
            self.assertTrue(applied["applied"])
            self.assertEqual(
                authenticate_target(
                    source,
                    target,
                    expected_source_tree_raw_sha256=source_pin,
                )["state"],
                "V4.7",
            )
            no_op = apply_overlay(
                source,
                target,
                expected_source_tree_raw_sha256=source_pin,
            )
            self.assertTrue(no_op["valid"], no_op)
            self.assertTrue(no_op["idempotent_no_op"])


if __name__ == "__main__":
    unittest.main()
