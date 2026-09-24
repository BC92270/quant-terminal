"""Authentication and integration tests for the V5.0 Streamlit surface."""

from __future__ import annotations

import unittest

from ..engine.evaluator import default_root
from ..ui import (
    EXPECTED_UI_AUTH_CHECK_COUNT,
    apply_v50_encoding_state,
    load_v50_ui_artifact,
    normalize_v50_artifact,
)


ROOT = default_root()


class QuantumLabV50UiTests(unittest.TestCase):
    def test_01_authenticated_load_passes_twelve_checks(self) -> None:
        artifact, report = load_v50_ui_artifact()
        self.assertIsNotNone(artifact)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["check_count"], EXPECTED_UI_AUTH_CHECK_COUNT)

    def test_02_normalized_state_exposes_no_go(self) -> None:
        artifact, report = load_v50_ui_artifact()
        state = normalize_v50_artifact(artifact, integrity=report["valid"])
        self.assertTrue(state["authenticated"])
        self.assertEqual(state["observed_epochs"], 4)
        self.assertEqual(state["matrix_cells"], 32)
        self.assertEqual(state["required_maximum_direct_cx"], 467)
        self.assertEqual(state["provider_discovery"], "DENIED_ARCHITECTURE_NO_GO")
        self.assertEqual(state["v5_execution"], "CLOSED")

    def test_03_masked_state_never_becomes_executable(self) -> None:
        state = normalize_v50_artifact(None, integrity=False)
        self.assertFalse(state["authenticated"])
        self.assertFalse(state["hardware_executable"])

    def test_04_bands_encoding_receives_v50_decision(self) -> None:
        artifact, report = load_v50_ui_artifact()
        state = normalize_v50_artifact(artifact, integrity=report["valid"])
        encoded = apply_v50_encoding_state({}, regime="BANDS", state=state, artifact=artifact)
        self.assertEqual(encoded["v50_provider_discovery"], "DENIED_ARCHITECTURE_NO_GO")
        self.assertEqual(encoded["v50_execution"], "CLOSED")
        self.assertEqual(encoded["v50_authentic_epochs"], 4)
        self.assertFalse(encoded["hardware_executable"])

    def test_05_other_regimes_are_not_mutated(self) -> None:
        artifact, report = load_v50_ui_artifact()
        state = normalize_v50_artifact(artifact, integrity=report["valid"])
        self.assertEqual(
            apply_v50_encoding_state({"sentinel": 1}, regime="VOL", state=state, artifact=artifact),
            {"sentinel": 1},
        )

    def test_06_surface_exposes_six_control_tabs(self) -> None:
        source = (ROOT / "quantum_research_lab/v50/ui.py").read_text(encoding="utf-8")
        for label in (
            "CONTROL PLANE",
            "EPOCH COHORT",
            "32-CELL MATRIX",
            "ARCHITECTURE",
            "PROVENANCE",
            "GOVERNANCE",
        ):
            self.assertIn(f'"{label}"', source)

    def test_07_surface_exposes_hash_gated_downloads(self) -> None:
        source = (ROOT / "quantum_research_lab/v50/ui.py").read_text(encoding="utf-8")
        for label in (
            "V5.0 sealed artifact",
            "Independent validation report",
            "V5.0 protocol",
            "Pinned source catalog",
        ):
            self.assertIn(label, source)

    def test_08_surface_states_historical_not_current_boundary(self) -> None:
        source = (ROOT / "quantum_research_lab/v50/ui.py").read_text(encoding="utf-8")
        self.assertIn("The evidence gap is closed. The architecture gap is not.", source)
        self.assertIn("not a current calibration export", source)
        self.assertIn("current_hardware_evidence=false", source)

    def test_09_main_ui_imports_and_renders_v50(self) -> None:
        source = (ROOT / "quantum_research_lab/ui.py").read_text(encoding="utf-8")
        self.assertIn("from .v50.ui import", source)
        self.assertIn("render_v50_control_plane", source)
        self.assertIn("apply_v50_encoding_state", source)

    def test_10_main_ui_prefers_v50_provider_boundary(self) -> None:
        source = (ROOT / "quantum_research_lab/ui.py").read_text(encoding="utf-8")
        self.assertIn("if v50_integrity:", source)
        self.assertIn("V5.0 authenticates four distinct historical offline calibration epochs", source)

    def test_11_workspace_and_phase_headers_promote_v50(self) -> None:
        source = (ROOT / "quantum_research_lab/ui.py").read_text(encoding="utf-8")
        self.assertIn("V5.0 · HARDWARE-EVIDENCE CONTROL PLANE", source)
        self.assertIn("Historical Hardware-Evidence Control Plane & Zero-Job Governance", source)


if __name__ == "__main__":
    unittest.main()
