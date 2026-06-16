"""Typed prediction contracts for controlled AI forecasting."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AIPrediction(BaseModel):
    prediction_type: str
    horizon: str
    value: float
    confidence: float
    evidence: list[dict] = Field(default_factory=list)
    tenant_scope: str


class AIPredictionBundle(BaseModel):
    organization_id: str
    enabled: bool
    predictions: list[AIPrediction]
