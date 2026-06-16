"""Operational graph relationship models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class GraphNode:
    organization_id: str
    node_id: str
    node_type: str
    label: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GraphRelationship:
    organization_id: str
    relationship_id: str
    source_node_id: str
    target_node_id: str
    relationship_type: str
    confidence: float
    explanation: str
    append_only: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
