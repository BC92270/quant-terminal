from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scientific_research.autonomy_registry import AutonomyRegistry
from scientific_research.knowledge_graph import ScientificKnowledgeGraph
from scientific_research.phase2_models import KnowledgeNode
from scientific_research.phase3_registry import Phase3Registry
from scientific_research.phase63_registry import RegistryCorruptionError
from scientific_research.validation_registry import ValidationRegistry


class ScientificRegistryCorruptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_missing_registry_files_are_empty_state(self) -> None:
        phase3 = Phase3Registry(self.root / "phase3")
        phase5 = ValidationRegistry(self.root / "phase5")
        phase6 = AutonomyRegistry(self.root / "phase6")
        graph = ScientificKnowledgeGraph(self.root / "graph")

        self.assertEqual(phase3.list_candidates(), [])
        self.assertEqual(phase5.list_reviews(), [])
        self.assertEqual(phase6.list_questions(), [])
        self.assertEqual(graph.nodes(), [])
        self.assertEqual(graph.edges(), [])

    def test_invalid_json_fails_closed_in_every_remaining_registry(self) -> None:
        cases = (
            (Phase3Registry(self.root / "phase3"), "candidates", lambda registry: registry.list_candidates()),
            (ValidationRegistry(self.root / "phase5"), "reviews", lambda registry: registry.list_reviews()),
            (AutonomyRegistry(self.root / "phase6"), "questions", lambda registry: registry.list_questions()),
        )
        for registry, bucket, loader in cases:
            with self.subTest(registry=type(registry).__name__):
                path = registry.paths[bucket]
                path.write_text('{"truncated":', encoding="utf-8")
                before = path.read_bytes()

                with self.assertRaisesRegex(RegistryCorruptionError, path.name):
                    loader(registry)

                self.assertEqual(path.read_bytes(), before)

        graph = ScientificKnowledgeGraph(self.root / "graph-invalid")
        graph.nodes_path.write_text('[{"node_id":', encoding="utf-8")
        before = graph.nodes_path.read_bytes()
        with self.assertRaisesRegex(RegistryCorruptionError, graph.nodes_path.name):
            graph.nodes()
        self.assertEqual(graph.nodes_path.read_bytes(), before)

    def test_non_array_and_non_object_rows_are_corruption(self) -> None:
        registry = Phase3Registry(self.root / "phase3-shape")
        path = registry.paths["audits"]
        for payload in ('{"audit_id": "A-1"}', '[{"audit_id": "A-1"}, 7]'):
            with self.subTest(payload=payload):
                path.write_text(payload, encoding="utf-8")
                before = path.read_bytes()
                with self.assertRaisesRegex(RegistryCorruptionError, "array of objects"):
                    registry.list_audits()
                self.assertEqual(path.read_bytes(), before)

    def test_mutations_do_not_overwrite_corrupt_registry_files(self) -> None:
        cases = (
            (
                Phase3Registry(self.root / "phase3-write"),
                "candidates",
                lambda registry: registry.save_candidate({"candidate_id": "C-1"}),
            ),
            (
                ValidationRegistry(self.root / "phase5-write"),
                "reviews",
                lambda registry: registry.save_review({"review_id": "R-1"}),
            ),
            (
                AutonomyRegistry(self.root / "phase6-write"),
                "questions",
                lambda registry: registry.save_question({"question_id": "Q-1"}),
            ),
        )
        for registry, bucket, mutation in cases:
            with self.subTest(registry=type(registry).__name__):
                path = registry.paths[bucket]
                path.write_text("not-json", encoding="utf-8")
                before = path.read_bytes()

                with self.assertRaises(RegistryCorruptionError):
                    mutation(registry)

                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(list(path.parent.glob(f"{path.name}*.tmp")), [])

        graph = ScientificKnowledgeGraph(self.root / "graph-write")
        graph.nodes_path.write_text("null", encoding="utf-8")
        before = graph.nodes_path.read_bytes()
        with self.assertRaises(RegistryCorruptionError):
            graph.upsert_nodes((KnowledgeNode("N-1", "Concept", "test"),))
        self.assertEqual(graph.nodes_path.read_bytes(), before)
        self.assertEqual(list(graph.nodes_path.parent.glob(f"{graph.nodes_path.name}*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
