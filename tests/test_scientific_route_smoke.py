from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


class ScientificRouteSmokeTests(unittest.TestCase):
    def test_scientific_research_native_route_renders_fail_closed_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"SRB_MEMORY_DIR": str(Path(directory) / "scientific-state")},
        ):
            app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
            app.query_params["workspace"] = "scientific-research"
            app.run(timeout=90)

        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertTrue(
            any(
                "SCIENTIFIC RESEARCH BRAIN" in str(item.value)
                and "RESEARCH_ONLY" in str(item.value)
                for item in app.caption
            )
        )
        labels = {item.label for item in app.tabs}
        self.assertTrue(
            {
                "Command Center",
                "Historical Data Contracts",
                "Validation Council",
                "Independent Replication",
                "Memory / Audit",
            }
            <= labels
        )
        self.assertEqual(
            app.button(key="scientific_research_back_to_command_center_v0641").label,
            "← Command Center",
        )


if __name__ == "__main__":
    unittest.main()
