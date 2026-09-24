"""Positive-rerun AppTest checks for the standalone V5.0 surface."""

from __future__ import annotations

import unittest

from streamlit.testing.v1 import AppTest

from ..engine.evaluator import default_root


ROOT = default_root()


def _text(app: AppTest) -> str:
    parts: list[str] = []
    for name in (
        "title",
        "header",
        "markdown",
        "caption",
        "warning",
        "error",
        "info",
        "success",
        "code",
        "metric",
    ):
        for element in getattr(app, name, ()):
            value = getattr(element, "value", None)
            if value is not None:
                parts.append(str(value))
            label = getattr(element, "label", None)
            if label is not None:
                parts.append(str(label))
    return "\n".join(parts)


class QuantumLabV50AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        target = ROOT / "release/quantum_v50/harness.py"
        cls.app = AppTest.from_file(str(target), default_timeout=120.0)
        cls.app.run(timeout=120.0)
        cls.first_exceptions = [str(item.value) for item in cls.app.exception]
        cls.first_tabs = tuple(tab.label for tab in cls.app.tabs)
        cls.app.run(timeout=120.0)
        cls.final_exceptions = [str(item.value) for item in cls.app.exception]
        cls.final_tabs = tuple(tab.label for tab in cls.app.tabs)
        cls.final_text = _text(cls.app)

    def test_01_first_run_has_no_exception(self) -> None:
        self.assertEqual(self.first_exceptions, [])

    def test_02_positive_rerun_has_no_exception(self) -> None:
        self.assertEqual(self.final_exceptions, [])

    def test_03_six_tabs_are_stable(self) -> None:
        expected = (
            "CONTROL PLANE",
            "EPOCH COHORT",
            "32-CELL MATRIX",
            "ARCHITECTURE",
            "PROVENANCE",
            "GOVERNANCE",
        )
        self.assertEqual(self.first_tabs, expected)
        self.assertEqual(self.final_tabs, expected)

    def test_04_scientific_decision_is_visible(self) -> None:
        self.assertIn("V50_AUTHENTIC_EPOCH_GATE_PASSED_ARCHITECTURE_NO_GO", self.final_text)

    def test_05_evidence_and_execution_boundaries_are_visible(self) -> None:
        self.assertIn("The evidence gap is closed. The architecture gap is not.", self.final_text)
        self.assertIn("V5 EXECUTION · CLOSED", self.final_text)
        self.assertIn("not a current calibration export", self.final_text)

    def test_06_six_metrics_are_rendered(self) -> None:
        self.assertEqual(len(self.app.metric), 6)

    def test_07_four_downloads_are_rendered(self) -> None:
        self.assertEqual(len(self.app.get("download_button")), 4)

    def test_08_nine_governance_actions_are_disabled(self) -> None:
        buttons = list(self.app.button)
        self.assertEqual(len(buttons), 9)
        self.assertTrue(all(getattr(button, "disabled", False) for button in buttons))

    def test_09_epoch_and_matrix_counts_are_visible(self) -> None:
        self.assertIn("4 / 3", self.final_text)
        self.assertIn("32 cells", self.final_text)

    def test_10_strict_target_and_best_observed_are_visible(self) -> None:
        self.assertIn("467", self.final_text)
        self.assertIn("795,990", self.final_text)


if __name__ == "__main__":
    unittest.main()
