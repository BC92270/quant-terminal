from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .phase2_models import KnowledgeEdge, KnowledgeNode, UnderstandingBundle
from .phase63_registry import RegistryCorruptionError
from .registry_io import json_array_transaction, read_json_array


class ScientificKnowledgeGraph:
    """Small persistent JSON graph for Phase 2.

    The interface is intentionally storage-agnostic so a future Neo4j/graph database
    backend can replace this implementation without changing the SRB UI contract.
    """

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.nodes_path = self.root / "knowledge_nodes.json"
        self.edges_path = self.root / "knowledge_edges.json"

    @staticmethod
    def _read(path: Path) -> list[dict[str, Any]]:
        return read_json_array(path, RegistryCorruptionError)

    @staticmethod
    def _merge(existing: list[dict[str, Any]], incoming: Iterable[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        index = {str(row.get(key)): dict(row) for row in existing if row.get(key)}
        for row in incoming:
            value = str(row.get(key) or "")
            if value:
                index[value] = dict(row)
        return list(index.values())

    def upsert_nodes(self, nodes: Iterable[KnowledgeNode]) -> None:
        incoming = [asdict(node) for node in nodes]
        with json_array_transaction(self.nodes_path, RegistryCorruptionError) as existing:
            existing[:] = self._merge(existing, incoming, "node_id")

    def upsert_edges(self, edges: Iterable[KnowledgeEdge]) -> None:
        incoming = [asdict(edge) for edge in edges]
        with json_array_transaction(self.edges_path, RegistryCorruptionError) as existing:
            existing[:] = self._merge(existing, incoming, "edge_id")

    def ingest_bundle(self, bundle: UnderstandingBundle) -> None:
        self.upsert_nodes(bundle.knowledge_nodes)
        self.upsert_edges(bundle.knowledge_edges)

    def nodes(self, node_type: str | None = None) -> list[dict[str, Any]]:
        rows = self._read(self.nodes_path)
        if node_type is None:
            return rows
        return [row for row in rows if str(row.get("node_type")) == str(node_type)]

    def edges(self, relation: str | None = None) -> list[dict[str, Any]]:
        rows = self._read(self.edges_path)
        if relation is None:
            return rows
        return [row for row in rows if str(row.get("relation")) == str(relation)]

    def node(self, node_id: str) -> dict[str, Any] | None:
        return next((row for row in self.nodes() if str(row.get("node_id")) == str(node_id)), None)

    def neighbors(self, node_id: str) -> list[dict[str, Any]]:
        nodes = {str(row.get("node_id")): row for row in self.nodes()}
        out: list[dict[str, Any]] = []
        for edge in self.edges():
            source = str(edge.get("source"))
            target = str(edge.get("target"))
            if source == node_id:
                out.append({"direction": "OUT", "relation": edge.get("relation"), "node": nodes.get(target), "edge": edge})
            elif target == node_id:
                out.append({"direction": "IN", "relation": edge.get("relation"), "node": nodes.get(source), "edge": edge})
        return out

    def summary(self) -> dict[str, Any]:
        nodes = self.nodes()
        edges = self.edges()
        by_type: dict[str, int] = {}
        by_relation: dict[str, int] = {}
        for node in nodes:
            key = str(node.get("node_type") or "Unknown")
            by_type[key] = by_type.get(key, 0) + 1
        for edge in edges:
            key = str(edge.get("relation") or "Unknown")
            by_relation[key] = by_relation.get(key, 0) + 1
        return {
            "nodes": len(nodes),
            "edges": len(edges),
            "node_types": dict(sorted(by_type.items())),
            "relations": dict(sorted(by_relation.items())),
        }
