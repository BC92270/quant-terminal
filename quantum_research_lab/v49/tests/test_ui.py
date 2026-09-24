"""Authentication and integration tests for the V4.9 Streamlit surface."""

from __future__ import annotations

from pathlib import Path
import unittest

from ..engine.evaluator import default_root
from ..ui import (
    EXPECTED_UI_AUTH_CHECK_COUNT,
    apply_v49_encoding_state,
    load_v49_ui_artifact,
    normalize_v49_artifact,
)


ROOT = default_root()


class QuantumLabV49UiTests(unittest.TestCase):
    def test_01_authenticated_load_passes_ten_checks(self) -> None:
        artifact, report = load_v49_ui_artifact()
        self.assertIsNotNone(artifact)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["check_count"], EXPECTED_UI_AUTH_CHECK_COUNT)

    def test_02_normalized_state_is_fail_closed(self) -> None:
        artifact, report = load_v49_ui_artifact()
        state = normalize_v49_artifact(artifact, integrity=report["valid"])
        self.assertTrue(state["authenticated"])
        self.assertEqual(state["provider_discovery"], "DENIED")
        self.assertEqual(state["v5_entry"], "CLOSED")
        self.assertFalse(state["hardware_executable"])

    def test_03_masked_state_never_becomes_executable(self) -> None:
        state = normalize_v49_artifact(None, integrity=False)
        self.assertFalse(state["authenticated"])
        self.assertFalse(state["hardware_executable"])

    def test_04_bands_encoding_receives_v49_decision(self) -> None:
        artifact, report = load_v49_ui_artifact()
        state = normalize_v49_artifact(artifact, integrity=report["valid"])
        encoded = apply_v49_encoding_state({}, regime="BANDS", state=state, artifact=artifact)
        self.assertEqual(encoded["v49_provider_discovery"], "DENIED")
        self.assertEqual(encoded["v49_v5_entry"], "CLOSED")
        self.assertFalse(encoded["hardware_executable"])

    def test_05_other_regimes_are_not_mutated(self) -> None:
        artifact, report = load_v49_ui_artifact()
        state = normalize_v49_artifact(artifact, integrity=report["valid"])
        self.assertEqual(
            apply_v49_encoding_state({"sentinel": 1}, regime="VOL", state=state, artifact=artifact),
            {"sentinel": 1},
        )

    def test_06_surface_exposes_six_evidence_tabs(self) -> None:
        source = (ROOT / "quantum_research_lab/v49/ui.py").read_text(encoding="utf-8")
        for label in ("DECISION", "EPOCH REGISTRY", "RESOURCE GAP", "CELL MATRIX", "PROVENANCE", "GOVERNANCE"):
            self.assertIn(f'"{label}"', source)

    def test_07_surface_exposes_five_hash_gated_downloads(self) -> None:
        source = (ROOT / "quantum_research_lab/v49/ui.py").read_text(encoding="utf-8")
        self.assertIn("Sealed V4.9 artifact", source)
        self.assertIn("Independent validation report", source)
        self.assertIn("V4.9 protocol", source)
        self.assertIn("Authentic epoch registry", source)
        self.assertIn("Normalized cohort", source)

    def test_08_surface_states_the_not_evaluable_boundary(self) -> None:
        source = (ROOT / "quantum_research_lab/v49/ui.py").read_text(encoding="utf-8")
        self.assertIn("A not-evaluable result is preserved", source)
        self.assertIn("provider discovery DENIED", source)

    def test_09_main_ui_imports_and_renders_v49(self) -> None:
        source = (ROOT / "quantum_research_lab/ui.py").read_text(encoding="utf-8")
        self.assertIn("from .v49.ui import", source)
        self.assertIn("render_v49_admission_panel", source)
        self.assertIn("apply_v49_encoding_state", source)

    def test_10_main_ui_prefers_v49_provider_boundary(self) -> None:
        source = (ROOT / "quantum_research_lab/ui.py").read_text(encoding="utf-8")
        self.assertIn("if v49_integrity:", source)
        self.assertIn("V4.9 is the terminal offline V4 admission dossier", source)


if __name__ == "__main__":
    unittest.main()
