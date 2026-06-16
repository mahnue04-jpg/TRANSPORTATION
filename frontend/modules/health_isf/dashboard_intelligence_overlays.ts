/**
 * Dashboard intelligence overlays for decision support rendering.
 */

import type { OperationalDecisionIntelligenceSnapshot } from './operational_decision_contracts';

export interface DashboardIntelligenceOverlays {
  liveOperationalRiskOverlays: Array<Record<string, unknown>>;
  escalationHeatmaps: Array<Record<string, unknown>>;
  congestionVisibility: Array<Record<string, unknown>>;
  slaImpactIndicators: Array<Record<string, unknown>>;
  operationalConfidenceVisualization: Array<Record<string, unknown>>;
  recommendationEvidenceRendering: Array<Record<string, unknown>>;
  hydrationSafe: boolean;
  synchronizationSafe: boolean;
}

export function buildDashboardIntelligenceOverlays(
  decision: OperationalDecisionIntelligenceSnapshot | null | undefined,
): DashboardIntelligenceOverlays {
  const recommendations = Array.isArray(decision?.recommendations) ? decision.recommendations : [];

  return {
    liveOperationalRiskOverlays: recommendations.map((item) => ({
      recommendation_id: item.recommendation_id,
      recommendation_type: item.recommendation_type,
      risk_score: Number(item.priority_score || 0),
      continuity_risk: Number(decision?.pressure_analysis?.continuity_degradation_risk || 0),
    })),
    escalationHeatmaps: recommendations
      .filter((item) => item.recommendation_type.includes('escalation'))
      .map((item) => ({
        recommendation_id: item.recommendation_id,
        escalation_score: Number(item.escalation_score || 0),
        severity_weight: Number(item.severity_weight || 0),
      })),
    congestionVisibility: [{
      regional_congestion: Number(decision?.pressure_analysis?.regional_congestion || 0),
      congestion_prediction: Number(decision?.forecast?.operational_congestion_prediction || 0),
      incident_clustering: Number(decision?.pressure_analysis?.incident_clustering || 0),
    }],
    slaImpactIndicators: recommendations.map((item) => ({
      recommendation_id: item.recommendation_id,
      sla_impact: item.sla_impact,
      operational_impact: item.operational_impact,
    })),
    operationalConfidenceVisualization: recommendations.map((item) => ({
      recommendation_id: item.recommendation_id,
      confidence: Number(item.confidence || 0),
    })),
    recommendationEvidenceRendering: recommendations.map((item) => ({
      recommendation_id: item.recommendation_id,
      evidence_chain: Array.isArray(item.evidence_chain) ? item.evidence_chain : [],
      reasoning_chain: Array.isArray(item.reasoning_chain) ? item.reasoning_chain : [],
    })),
    hydrationSafe: true,
    synchronizationSafe: Boolean(decision?.websocket_synchronized && decision?.replay_safe),
  };
}
