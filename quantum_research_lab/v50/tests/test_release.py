"""Structure, reproducibility, release, and installer tests for V5.0."""

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
from unittest.mock import patch
import zipfile

from ..engine.evaluator import ARTIFACT, default_root
from ..engine.evidence import SOURCE_CATALOG, raw_file_sha256, read_json_strict
from ..engine.validation import REPORT
from release.quantum_v50.build import (
    FREEZE_PATH,
    MANIFEST_NAME,
    OVERLAY_NAME,
    PARENT_FREEZE_RAW,
    SUPERSEDED,
    TRANSITION_FILES,
    build_freeze,
)
from release.quantum_v50.install import (
    EXPECTED_SUPERSEDED,
    EXPECTED_TRANSITIONS,
    RECOGNIZED_STAGED_RELEASE_FREEZES,
    install,
)


ROOT = default_root()


def _materialize_v49_parent(target: Path) -> tuple[str, ...]:
    freeze_relative = "release/quantum_v49/freeze.json"
    freeze_path = target / freeze_relative
    freeze_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / freeze_relative, freeze_path)
    freeze = read_json_strict(ROOT / freeze_relative)
    frozen = freeze["frozen_files"]
    for relative in frozen:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    superseded = {
        "QUANTUM_RELEASES.md",
        "quantum_research_lab/README.md",
        "quantum_research_lab/ui.py",
    }
    return tuple(sorted(relative for relative in frozen if relative not in superseded))


class QuantumLabV50ReleaseTests(unittest.TestCase):
    def test_01_compact_package_exists(self) -> None:
        self.assertTrue((ROOT / "quantum_research_lab/v50/engine").is_dir())
        self.assertTrue((ROOT / "quantum_research_lab/v50/evidence/raw").is_dir())
        self.assertTrue((ROOT / "quantum_research_lab/v50/tests").is_dir())
        self.assertTrue((ROOT / "release/quantum_v50").is_dir())

    def test_02_no_flat_v50_release_files_pollute_root(self) -> None:
        forbidden = [
            path
            for path in ROOT.iterdir()
            if path.name.startswith(
                (
                    "DEPLOY_V5_0",
                    "FREEZE_CONTRACT_V5_0",
                    "install_quantum_lab_v50",
                    "build_quantum_lab_v50",
                )
            )
        ]
        self.assertEqual(forbidden, [])

    def test_03_source_catalog_binds_eight_raw_files(self) -> None:
        catalog = read_json_strict(ROOT / SOURCE_CATALOG)
        rows = catalog["snapshots"]
        self.assertEqual(len(rows), 4)
        for row in rows:
            for kind in ("configuration", "properties"):
                path = ROOT / row[f"{kind}_path"]
                self.assertTrue(path.is_file() and not path.is_symlink())
                self.assertEqual(raw_file_sha256(path), row[f"{kind}_raw_sha256"])
                self.assertEqual(path.stat().st_size, row[f"{kind}_size"])

    def test_04_source_catalog_pins_official_distribution_urls(self) -> None:
        catalog = read_json_strict(ROOT / SOURCE_CATALOG)
        self.assertEqual([row["version"] for row in catalog["distributions"]], ["0.37.0", "0.47.0"])
        for row in catalog["distributions"]:
            self.assertTrue(row["wheel_url"].startswith("https://files.pythonhosted.org/"))
            self.assertTrue(row["pypi_metadata_url"].startswith("https://pypi.org/pypi/"))
            self.assertEqual(len(row["wheel_sha256"]), 64)

    def test_05_artifact_and_report_exist(self) -> None:
        self.assertTrue((ROOT / ARTIFACT).is_file())
        self.assertTrue((ROOT / REPORT).is_file())
        self.assertTrue(read_json_strict(ROOT / REPORT)["valid"])

    def test_06_clean_process_replay_is_byte_exact(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v50-replay-") as temporary:
            target = Path(temporary) / "artifact.json"
            environment = dict(os.environ)
            environment["PYTHONHASHSEED"] = "0"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "quantum_research_lab.v50.engine.evaluator",
                    "--root",
                    str(ROOT),
                    "--output",
                    str(target),
                ],
                cwd=ROOT,
                env=environment,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            self.assertEqual(target.read_bytes(), (ROOT / ARTIFACT).read_bytes())

    def test_07_release_engine_is_standard_library_only(self) -> None:
        for path in sorted((ROOT / "quantum_research_lab/v50/engine").glob("*.py")):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("import streamlit", source)
            self.assertNotIn("import pandas", source)

    def test_08_freeze_preserves_exact_v49_parent(self) -> None:
        freeze = read_json_strict(ROOT / FREEZE_PATH)
        self.assertEqual(freeze["parent"]["freeze_raw_sha256"], PARENT_FREEZE_RAW)
        self.assertEqual(freeze["parent"]["release"], "V4.9")
        self.assertEqual(
            freeze["scientific_decision"],
            "V50_AUTHENTIC_EPOCH_GATE_PASSED_ARCHITECTURE_NO_GO",
        )
        rebuilt = build_freeze(ROOT)
        self.assertEqual(rebuilt, freeze)

    def test_09_freeze_self_hash_and_transition_order_are_exact(self) -> None:
        freeze = read_json_strict(ROOT / FREEZE_PATH)
        body = {key: value for key, value in freeze.items() if key != "freeze_contract_sha256"}
        semantic = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        self.assertEqual(freeze["freeze_contract_sha256"], semantic)
        self.assertEqual(tuple(freeze["transition_files"]), TRANSITION_FILES)

    def test_10_overlay_is_complete_and_deterministically_ordered(self) -> None:
        overlay = ROOT / "release/quantum_v50/dist" / OVERLAY_NAME
        manifest_path = ROOT / "release/quantum_v50/dist" / MANIFEST_NAME
        self.assertTrue(overlay.is_file())
        manifest = read_json_strict(manifest_path)
        self.assertEqual(raw_file_sha256(overlay), manifest["overlay_raw_sha256"])
        with zipfile.ZipFile(overlay) as archive:
            self.assertEqual(tuple(archive.namelist()), TRANSITION_FILES)

    def test_11_installer_is_transactional_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v50-install-") as temporary:
            target = Path(temporary) / "target"
            immutable_parent = _materialize_v49_parent(target)
            first = install(ROOT, target)
            second = install(ROOT, target)
            self.assertTrue(first["installed"])
            self.assertTrue(second["installed"])
            self.assertTrue(first["parent_immutable_lineage_authenticated"])
            self.assertEqual(
                first["parent_immutable_path_count"], len(immutable_parent)
            )
            self.assertEqual(first["transition_file_count"], len(TRANSITION_FILES))
            self.assertEqual(second["created"], [])
            self.assertEqual(
                raw_file_sha256(target / ARTIFACT), raw_file_sha256(ROOT / ARTIFACT)
            )

    def test_12_installer_rejects_missing_or_drifted_parent_lineage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v50-parent-lineage-") as temporary:
            target = Path(temporary) / "target"
            immutable_parent = _materialize_v49_parent(target)
            candidate = immutable_parent[0]
            candidate_path = target / candidate

            candidate_path.unlink()
            with self.assertRaisesRegex(ValueError, "Immutable V4.9 lineage"):
                install(ROOT, target)

            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / candidate, candidate_path)

            external = Path(temporary) / "external"
            external.mkdir()
            symlink = target / "quantum_research_lab/v50"
            symlink.symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                install(ROOT, target)
            symlink.unlink()

            candidate_path.write_bytes(b"deliberate lineage drift")
            with self.assertRaisesRegex(ValueError, "Immutable V4.9 lineage"):
                install(ROOT, target)

    def test_13_installer_scope_allowlists_match_release_builder(self) -> None:
        self.assertEqual(EXPECTED_TRANSITIONS, TRANSITION_FILES)
        self.assertEqual(EXPECTED_SUPERSEDED, frozenset(SUPERSEDED))
        self.assertTrue(
            all(".." not in Path(relative).parts for relative in EXPECTED_TRANSITIONS)
        )

    def test_14_explorer_index_promotes_v50_without_moving_history(self) -> None:
        text = (ROOT / "QUANTUM_RELEASES.md").read_text(encoding="utf-8")
        self.assertIn("remain at their original paths", text)
        self.assertIn("quantum_research_lab/v50/", text)
        self.assertIn("outputs/quantum_phase3/v50_hardware_evidence_control/", text)

    def test_15_installer_migrates_only_an_exact_recognized_pre_release(self) -> None:
        self.assertEqual(
            RECOGNIZED_STAGED_RELEASE_FREEZES,
            {
                "7f14c39d5a981c364d6e0d9eab8913f3bdea5a6f6e7d3f0d4bb523b4aee9e39c": (
                    "7ea4daa73211daf6724f0a378363ad728bd79bfb6b83258ecef19fc2bf34b743"
                ),
                "c95b5442f6fcb560ccf3b7af91d47d8d23c69afe283666ea17d2b58da927e4a6": (
                    "fa8acb511824cac448bec6a42b6c8b4b98f52571bec2a9b13f5fea7f595af6b5"
                ),
            },
        )
        with tempfile.TemporaryDirectory(prefix="v50-pre-release-") as temporary:
            target = Path(temporary) / "target"
            _materialize_v49_parent(target)
            install(ROOT, target)

            changed_relative = "quantum_research_lab/v50/ui.py"
            changed_path = target / changed_relative
            changed_path.write_bytes(b"recognized historical pre-release bytes\n")
            prior = read_json_strict(ROOT / FREEZE_PATH)
            prior["frozen_files"][changed_relative] = raw_file_sha256(changed_path)
            prior["freeze_contract_sha256"] = ""
            body = {
                key: value
                for key, value in prior.items()
                if key != "freeze_contract_sha256"
            }
            prior["freeze_contract_sha256"] = hashlib.sha256(
                json.dumps(
                    body,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            prior_path = target / FREEZE_PATH
            prior_path.write_text(
                json.dumps(
                    prior,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n",
                encoding="utf-8",
            )
            prior_raw = raw_file_sha256(prior_path)
            prior_semantic = prior["freeze_contract_sha256"]

            with patch.dict(
                "release.quantum_v50.install.RECOGNIZED_STAGED_RELEASE_FREEZES",
                {prior_raw: prior_semantic},
                clear=True,
            ):
                result = install(ROOT, target)

            self.assertTrue(result["recognized_pre_release_migration"])
            self.assertEqual(
                changed_path.read_bytes(), (ROOT / changed_relative).read_bytes()
            )

            prior_path.write_bytes(prior_path.read_bytes() + b"unknown drift")
            with self.assertRaisesRegex(ValueError, "unrecognized V5.0 freeze"):
                install(ROOT, target)


if __name__ == "__main__":
    unittest.main()
