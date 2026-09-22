"""Negative-path tests for the hardened V3.6 release and installer controls."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from install_quantum_lab_v36 import LOCK_NAME, OVERLAY_FILES, install, preflight
from .phase3_v36_algorithmic_reduction import canonical_json_sha256
from .verify_phase3_v36 import (
    V35_FROZEN_PATHS,
    V35_README_SHA256,
    V35_UI_SHA256,
    V36_README_SHA256,
    V36_UI_SHA256,
    _read_json_strict,
    _regular_contained,
    classify_successor_pair,
    verify_release_chain,
)


class ReleaseHardeningV36Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        if not (cls.root / "FREEZE_CONTRACT_V3_6.json").is_file():
            raise unittest.SkipTest("V3.6 freeze is not assembled yet.")

    def _copy_release(self, target: Path) -> Path:
        destination = target / "release"
        shutil.copytree(
            self.root,
            destination,
            ignore=shutil.ignore_patterns("__pycache__", ".quantum-lab-v36-*"),
        )
        return destination

    def test_exact_parent_inventory_is_hard_coded(self) -> None:
        self.assertEqual(len(V35_FROZEN_PATHS), 41)
        freeze = json.loads((self.root / "FREEZE_CONTRACT_V3_5.json").read_text())
        self.assertEqual(set(freeze["frozen_files"]), V35_FROZEN_PATHS)

    def test_successor_state_rejects_mixed_and_third_values(self) -> None:
        self.assertEqual(classify_successor_pair(V35_README_SHA256, V35_UI_SHA256), "V3.5")
        self.assertEqual(classify_successor_pair(V36_README_SHA256, V36_UI_SHA256), "V3.6")
        self.assertEqual(classify_successor_pair(V35_README_SHA256, V36_UI_SHA256), "INVALID")
        self.assertEqual(classify_successor_pair(V36_README_SHA256, V35_UI_SHA256), "INVALID")
        self.assertEqual(classify_successor_pair("0" * 64, "1" * 64), "INVALID")

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.json"
            path.write_text('{"a":1,"a":2}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                _read_json_strict(path)

    def test_path_traversal_and_symlink_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "regular").write_text("ok", encoding="utf-8")
            os.symlink(root / "regular", root / "link")
            with self.assertRaises((ValueError, FileNotFoundError)):
                _regular_contained(root, "../regular")
            with self.assertRaisesRegex(ValueError, "non-symlink"):
                _regular_contained(root, "link")

    def test_deleted_parent_inventory_cannot_be_self_rehashed_into_validity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = self._copy_release(Path(tmp))
            freeze_path = release / "FREEZE_CONTRACT_V3_5.json"
            freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
            freeze["frozen_files"].pop("DEPLOY_V3_4.md")
            # Preserve the declared count to reproduce the predecessor bypass.
            freeze["freeze_contract_sha256"] = canonical_json_sha256(
                {key: value for key, value in freeze.items() if key != "freeze_contract_sha256"}
            )
            freeze_path.write_text(
                json.dumps(freeze, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            report = verify_release_chain(release)
            self.assertFalse(report["valid"])
            self.assertFalse(report["checks"]["v35_freeze_raw_and_semantic_identity_exact"])
            self.assertFalse(report["checks"]["v35_frozen_inventory_41_paths_exact"])

    def test_preflight_rejects_unknown_successor_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = self._copy_release(Path(tmp))
            (release / "quantum_research_lab" / "ui.py").write_text(
                "# unauthorized successor\n", encoding="utf-8"
            )
            report = preflight(self.root, release)
            self.assertFalse(report["valid"])
            self.assertEqual(report["target"]["successor_state"], "INVALID")

    def test_existing_lock_blocks_install_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = self._copy_release(Path(tmp))
            lock = release / LOCK_NAME
            lock.write_text("held\n", encoding="utf-8")
            before = (release / "quantum_research_lab" / "ui.py").read_bytes()
            report = install(self.root, release)
            after = (release / "quantum_research_lab" / "ui.py").read_bytes()
            self.assertFalse(report["valid"])
            self.assertFalse(report["applied"])
            self.assertEqual(before, after)

    def test_exact_reapplication_is_idempotent_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = self._copy_release(Path(tmp))
            report = install(self.root, release)
            self.assertTrue(report["valid"])
            self.assertTrue(report["idempotent"])
            self.assertFalse(report["applied"])
            self.assertFalse((release / LOCK_NAME).exists())

    def test_injected_partial_apply_restores_and_reauthenticates_preimages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = self._copy_release(Path(tmp))
            before = {
                relative: (release / relative).read_bytes()
                for relative in OVERLAY_FILES
            }
            report = install(
                self.root,
                release,
                _test_fail_after=8,
                _test_force_apply=True,
            )
            self.assertFalse(report["applied"])
            self.assertTrue(report["rolled_back"])
            self.assertTrue(report["preimages_restored"])
            self.assertEqual(len(report["applied_files_before_failure"]), 8)
            self.assertFalse((release / LOCK_NAME).exists())
            for relative, expected in before.items():
                self.assertEqual((release / relative).read_bytes(), expected)

    def test_ui_is_strictly_last_in_overlay_order(self) -> None:
        self.assertEqual(OVERLAY_FILES[-2], "quantum_research_lab/README.md")
        self.assertEqual(OVERLAY_FILES[-1], "quantum_research_lab/ui.py")
        self.assertEqual(len(OVERLAY_FILES), len(set(OVERLAY_FILES)))


if __name__ == "__main__":
    unittest.main()
