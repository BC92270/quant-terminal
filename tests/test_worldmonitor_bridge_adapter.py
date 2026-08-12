from __future__ import annotations

import ast
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


try:
    import streamlit  # noqa: F401
except ImportError:
    class _Cache:
        def __call__(self, *_args, **_kwargs):
            return lambda function: function

        def clear(self) -> None:
            return None

    class _Streamlit(types.ModuleType):
        cache_data = _Cache()
        cache_resource = _Cache()
        session_state: dict[str, object] = {}

        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: None

    streamlit_stub = _Streamlit("streamlit")
    sys.modules["streamlit"] = streamlit_stub
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    component_stub = types.ModuleType("streamlit.components.v1")
    component_stub.html = lambda *_args, **_kwargs: None
    sys.modules["streamlit.components.v1"] = component_stub


import worldmonitor_bridge_v211 as bridge
from worldmonitor.assets import layer_registry


class WorldMonitorSingleRendererTests(unittest.TestCase):
    def test_adapter_has_no_native_runtime(self) -> None:
        source = (ROOT / "worldmonitor_bridge_v211.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertFalse({"subprocess", "socket", "shutil"} & imported_modules)
        self.assertNotIn("WORLDMONITOR_NATIVE", source)
        self.assertNotIn("NATIF · KOALA73", source)
        self.assertNotIn("st.iframe", source)

    def test_single_jarvis_capability_contract(self) -> None:
        capabilities = bridge.get_worldmonitor_capabilities()
        self.assertEqual(capabilities["architecture"], "worldmonitor-package")
        self.assertFalse(capabilities["native_runtime"])
        self.assertFalse(capabilities["zip_runtime_dependency"])
        self.assertGreaterEqual(capabilities["layer_count"], 130)
        self.assertGreaterEqual(capabilities["live_backed_layers"], 70)
        self.assertGreaterEqual(capabilities["layer_groups"], 20)
        self.assertGreaterEqual(capabilities["presets"], 20)
        self.assertGreaterEqual(capabilities["country_profiles"], 190)

    def test_reference_parity_layers_are_registered(self) -> None:
        layer_ids = {str(row.get("layer_id")) for row in layer_registry()}
        expected = {
            "ciiChoropleth", "commodityPorts", "dayNight", "diseaseOutbreaks",
            "fuelShortages", "gpsJamming", "iranAttacks", "liveTankers",
            "miningSites", "processingPlants", "radiationWatch", "resilienceScore",
            "satellites", "storageFacilities", "webcams",
        }
        self.assertTrue(expected.issubset(layer_ids), sorted(expected - layer_ids))

    def test_compiled_runtime_snapshot(self) -> None:
        snapshot = bridge.get_worldmonitor_capabilities()
        self.assertEqual(snapshot["asset_schema"], 1)
        self.assertEqual(snapshot["quant_model"], "WM-IQ 1.0")
        self.assertGreaterEqual(snapshot["static_objects"], 2000)
        coverage = snapshot["country_indicator_coverage"]
        self.assertGreaterEqual(coverage["countries_scored"], 190)
        self.assertGreaterEqual(coverage["median_indicators"], 12)


if __name__ == "__main__":
    unittest.main()
