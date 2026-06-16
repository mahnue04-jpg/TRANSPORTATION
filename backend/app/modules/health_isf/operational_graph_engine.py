"""Append-only operational knowledge graph engine with tenant isolation."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from threading import RLock
from typing import Any

from app.modules.health_isf.relationship_models import GraphNode, GraphRelationship


class OperationalGraphEngine:
    def __init__(self) -> None:
        self._lock = RLock()
        self._nodes: dict[str, dict[str, GraphNode]] = defaultdict(dict)
        self._relationships: dict[str, list[GraphRelationship]] = defaultdict(list)

    def upsert_node(self, node: GraphNode) -> GraphNode:
        with self._lock:
            self._nodes[node.organization_id][node.node_id] = node
            return node

    def append_relationship(self, relationship: GraphRelationship) -> GraphRelationship:
        with self._lock:
            self._relationships[relationship.organization_id].append(relationship)
            return relationship

    def snapshot(self, organization_id: str, limit: int = 500) -> dict[str, Any]:
        with self._lock:
            nodes = list(self._nodes.get(organization_id, {}).values())
            relationships = list(self._relationships.get(organization_id, []))[-max(1, limit):]

        return {
            "organization_id": organization_id,
            "node_count": len(nodes),
            "relationship_count": len(relationships),
            "nodes": [
                {
                    "node_id": item.node_id,
                    "node_type": item.node_type,
                    "label": item.label,
                    "attributes": item.attributes,
                }
                for item in nodes
            ],
            "relationships": [
                {
                    "relationship_id": item.relationship_id,
                    "source_node_id": item.source_node_id,
                    "target_node_id": item.target_node_id,
                    "relationship_type": item.relationship_type,
                    "confidence": item.confidence,
                    "explanation": item.explanation,
                    "append_only": item.append_only,
                    "metadata": item.metadata,
                }
                for item in relationships
            ],
            "append_only_relationships": True,
            "explainable_links": True,
            "tenant_isolated": True,
            "replay_safe": True,
            "generated_at": datetime.utcnow().isoformat(),
        }


_engine = OperationalGraphEngine()


def get_operational_graph_engine() -> OperationalGraphEngine:
    return _engine
