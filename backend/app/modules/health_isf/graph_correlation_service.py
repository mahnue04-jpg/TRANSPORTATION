"""Correlation service for operational knowledge graph relationships."""

from __future__ import annotations

from typing import Any

from app.helpers import uuid4
from app.modules.health_isf.operational_graph_engine import get_operational_graph_engine
from app.modules.health_isf.relationship_models import GraphNode, GraphRelationship


class GraphCorrelationService:
    @staticmethod
    def correlate(
        *,
        organization_id: str,
        source: dict[str, Any],
        target: dict[str, Any],
        relationship_type: str,
        confidence: float,
        explanation: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        engine = get_operational_graph_engine()

        source_node = GraphNode(
            organization_id=organization_id,
            node_id=str(source.get("node_id") or source.get("id")),
            node_type=str(source.get("node_type") or source.get("type") or "entity"),
            label=str(source.get("label") or source.get("name") or source.get("id") or "source"),
            attributes=dict(source),
        )
        target_node = GraphNode(
            organization_id=organization_id,
            node_id=str(target.get("node_id") or target.get("id")),
            node_type=str(target.get("node_type") or target.get("type") or "entity"),
            label=str(target.get("label") or target.get("name") or target.get("id") or "target"),
            attributes=dict(target),
        )

        engine.upsert_node(source_node)
        engine.upsert_node(target_node)
        engine.append_relationship(
            GraphRelationship(
                organization_id=organization_id,
                relationship_id=str(uuid4()),
                source_node_id=source_node.node_id,
                target_node_id=target_node.node_id,
                relationship_type=relationship_type,
                confidence=round(max(0.0, min(1.0, float(confidence))), 4),
                explanation=explanation,
                append_only=True,
                metadata=metadata or {},
            )
        )

        return engine.snapshot(organization_id)

    @staticmethod
    def snapshot(*, organization_id: str) -> dict[str, Any]:
        return get_operational_graph_engine().snapshot(organization_id)
