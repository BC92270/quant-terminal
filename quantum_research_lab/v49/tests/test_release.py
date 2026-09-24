"""Structure, reproducibility and Explorer hardening tests for V4.9."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ..engine.checker import read_json_strict
from ..engine.evaluator import ARTIFACT_RELATIVE_PATH, default_root
from ..engine.validation import REPORT_RELATIVE_PATH


ROOT = default_root()


class QuantumLabV49ReleaseTests(unittest.TestCase):
    def test_01_compact_package_exists(self) -> None:
        self.assertTrue((ROOT / "quantum_research_lab/v49/engine").is_dir())
        self.assertTrue((ROOT / "quantum_research_lab/v49/snapshots").is_dir())
        self.assertTrue((ROOT / "quantum_research_lab/v49/tests").is_dir())

    def test_02_no_flat_v49_release_files_pollute_root(self) -> None:
        forbidden = [path for path in ROOT.iterdir() if path.name.startswith(("DEPLOY_V4_9", "FREEZE_CONTRACT_V4_9", "install_quantum_lab_v49", "build_quantum_lab_v49"))]
        self.assertEqual(forbidden, [])

    def test_03_explorer_settings_are_valid_json(self) -> None:
        settings = json.loads((ROOT / ".vscode/settings.json").read_text(encoding="utf-8"))
        self.assertTrue(settings["explorer.fileNesting.enabled"])
        self.assertFalse(settings["explorer.fileNesting.expand"])

    def test_04_quantum_history_is_nested_under_one_index(self) -> None:
        settings = json.loads((ROOT / ".vscode/settings.json").read_text(encoding="utf-8"))
        pattern = settings["explorer.fileNesting.patterns"]["QUANTUM_RELEASES.md"]
        for token in ("DEPLOY_V*.md", "FREEZE_CONTRACT_V*.json", "install_quantum_lab_v*.py", "build_quantum_lab_v*_release.py"):
            self.assertIn(token, pattern)

    def test_05_runtime_and_backup_trees_are_hidden(self) -> None:
        settings = json.loads((ROOT / ".vscode/settings.json").read_text(encoding="utf-8"))
        excluded = settings["files.exclude"]
        self.assertTrue(excluded["**/.quantum-lab-v*-backup*"])
        self.assertTrue(excluded["**/__pycache__"])
        self.assertTrue(excluded["**/backups"])

    def test_06_release_index_preserves_frozen_paths(self) -> None:
        text = (ROOT / "QUANTUM_RELEASES.md").read_text(encoding="utf-8")
        self.assertIn("remain at their original paths", text)
        self.assertIn("V4.9", text)

    def test_07_artifact_and_report_exist(self) -> None:
        self.assertTrue((ROOT / ARTIFACT_RELATIVE_PATH).is_file())
        self.assertTrue((ROOT / REPORT_RELATIVE_PATH).is_file())

    def test_08_validation_report_is_self_consistent(self) -> None:
        report = read_json_strict(ROOT / REPORT_RELATIVE_PATH)
        self.assertTrue(report["valid"])
        self.assertTrue(report["independent_checker"]["valid"])

    def test_09_clean_process_replay_is_byte_exact(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v49-replay-") as tmp:
            target = Path(tmp) / "artifact.json"
            env = dict(os.environ)
            env["PYTHONHASHSEED"] = "0"
            subprocess.run(
                [sys.executable, "-m", "quantum_research_lab.v49.engine.evaluator", "--root", str(ROOT), "--output", str(target)],
                cwd=ROOT,
                env=env,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            self.assertEqual(target.read_bytes(), (ROOT / ARTIFACT_RELATIVE_PATH).read_bytes())

    def test_10_report_binds_artifact_raw_identity(self) -> None:
        report = read_json_strict(ROOT / REPORT_RELATIVE_PATH)
        observed = hashlib.sha256((ROOT / ARTIFACT_RELATIVE_PATH).read_bytes()).hexdigest()
        self.assertEqual(report["artifact_raw_sha256"], observed)

    def test_11_raw_epoch_intake_is_documented(self) -> None:
        text = (ROOT / "quantum_research_lab/v49/snapshots/raw/README.md").read_text(encoding="utf-8")
        self.assertIn("synthetic jitter", text)
        self.assertIn("must never", text)

    def test_12_release_engine_is_standard_library_only(self) -> None:
        for path in sorted((ROOT / "quantum_research_lab/v49/engine").glob("*.py")):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("import streamlit", source)
            self.assertNotIn("import pandas", source)


if __name__ == "__main__":
    unittest.main()
