from __future__ import annotations

import ast
import gzip
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from worldmonitor.assets import DATA_DIR, asset_manifest, country_profiles, load_static_objects
from worldmonitor.country import merge_payload
from worldmonitor.performance import apply_render_budget
from worldmonitor.providers import PROVIDERS, provider_summary
from worldmonitor.quant import corroboration_score, event_decay_weight, propagate_shock, spatial_contagion


class WorldMonitorPackageTests(unittest.TestCase):
    def test_runtime_package_does_not_import_zipfile(self) -> None:
        for path in (ROOT / "worldmonitor").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.Import, ast.ImportFrom))
                for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(name=node.module or "")])
            }
            self.assertNotIn("zipfile", imports, path.name)

    def test_manifest_hashes_and_asset_counts(self) -> None:
        manifest = asset_manifest()
        for name, expected in manifest["assets"].items():
            path = DATA_DIR / name
            self.assertTrue(path.is_file(), name)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(digest, expected["sha256"], name)
        frame, status = load_static_objects("/path/that/must/not/be/read.zip")
        self.assertEqual(len(frame), manifest["static_objects"])
        self.assertIn("zip_scan=false", status.iloc[0]["detail"])

    def test_country_atlas_is_sourced_and_missingness_aware(self) -> None:
        profiles = country_profiles()
        self.assertGreaterEqual(len(profiles), 195)
        sourced = 0
        scored = 0
        for profile in profiles:
            indicators = profile.get("indicators") or {}
            quant = profile.get("quant") or {}
            if indicators:
                sourced += 1
                for record in indicators.values():
                    self.assertEqual(record.get("source"), "World Bank World Development Indicators")
                    self.assertIsNotNone(record.get("date"))
            if quant.get("score") is not None:
                scored += 1
                self.assertGreaterEqual(quant["score"], 0)
                self.assertLessEqual(quant["score"], 100)
                self.assertGreaterEqual(quant["confidence"], 0)
                self.assertLessEqual(quant["confidence"], 100)
                self.assertLessEqual(quant["uncertainty_low"], quant["score"])
                self.assertGreaterEqual(quant["uncertainty_high"], quant["score"])
        self.assertGreaterEqual(sourced, 190)
        self.assertGreaterEqual(scored, 190)

    def test_country_payload_exposes_sourced_channels_and_labels(self) -> None:
        payload = json.loads(merge_payload(None))
        self.assertGreaterEqual(len(payload["indicator_labels"]), 15)
        profile = next(row for row in payload["profiles"] if row["meta"]["iso3"] == "STP")
        self.assertEqual(profile["instability"]["score"], profile["quant"]["score"])
        self.assertGreaterEqual(len(profile["risk_channels"]), 3)
        self.assertIn("World Bank WDI", profile["energy"]["exposure"])
        self.assertNotIn("indicators", profile)

    def test_render_budget_preserves_geometry_and_layer_representation(self) -> None:
        frame, _ = load_static_objects()
        rendered, stats = apply_render_budget(frame, point_budget=700, per_layer=90)
        self.assertLess(len(rendered), len(frame))
        self.assertEqual(stats["rendered_points"], 700)
        self.assertEqual(
            len(rendered.loc[~rendered["kind"].astype(str).eq("point")]),
            len(frame.loc[~frame["kind"].astype(str).eq("point")]),
        )
        original_layers = set(frame.loc[frame["kind"].astype(str).eq("point"), "layer_id"])
        rendered_layers = set(rendered.loc[rendered["kind"].astype(str).eq("point"), "layer_id"])
        self.assertEqual(original_layers, rendered_layers)

    def test_quant_primitives_are_bounded_and_deterministic(self) -> None:
        self.assertAlmostEqual(event_decay_weight(12, 12), 0.5)
        self.assertEqual(corroboration_score([0.8, 0.7]), 94.0)
        self.assertAlmostEqual(spatial_contagion(650, 80), 29.43, places=2)
        propagated = propagate_shock(
            {"A": 100},
            [{"source": "A", "target": "B", "weight": 0.5}, {"source": "B", "target": "C", "weight": 0.5}],
        )
        self.assertEqual(propagated, {"A": 100.0, "B": 36.0, "C": 12.96})

    def test_provider_catalog_does_not_overstate_roadmap_sources(self) -> None:
        summary = provider_summary()
        self.assertGreaterEqual(summary["catalogued"], 20)
        self.assertEqual(summary["catalogued"], len(PROVIDERS))
        self.assertEqual(summary["catalogued"], summary["active"] + summary["snapshots"] + summary["adapters"] + summary["roadmap"])
        self.assertTrue(all(provider.authority and provider.cadence and provider.layers for provider in PROVIDERS))


if __name__ == "__main__":
    unittest.main()
