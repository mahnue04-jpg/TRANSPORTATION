/**
 * Driver intelligence assist rendering state.
 * Recommendation-only visibility for backend decision intelligence.
 */

import type { OperationalDecisionIntelligenceSnapshot } from './operational_decision_contracts';

export interface DriverIntelligenceAssistState {
  operationalRecommendationVisibility: Array<Record<string, unknown>>;
  escalationAwareness: Array<Record<string, unknown>>;
  congestionRerouteSuggestions: Array<Record<string, unknown>>;
  continuityRiskWarnings: Array<Record<string, unknown>>;
  explainableDispatchReasoning: Array<Record<string, unknown>>;
  recommendationOnly: boolean;
  backendAuthoritative: boolean;
  reconnectSafe: boolean;
}

export function buildDriverIntelligenceAssistState(
  decision: OperationalDecisionIntelligenceSnapshot | null | undefined,
): DriverIntelligenceAssistState {
  const recommendations = Array.isArray(decision?.recommendations) ? decision.recommendations : [];

  return {
    operationalRecommendationVisibility: recommendations.map((item) => ({
      recommendation_id: item.recommendation_id,
      recommendation_type: item.recommendation_type,
      priority_score: Number(item.priority_score || 0),
      confidence: Number(item.confidence || 0),
      sla_impact: item.sla_impact,
    })),
    escalationAwareness: recommendations
      .filter((item) => item.recommendation_type.includes('escalation') || Number(item.escalation_score || 0) >= 0.7)
      .map((item) => ({
        recommendation_id: item.recommendation_id,
        escalation_score: Number(item.escalation_score || 0),
      })),
    congestionRerouteSuggestions: recommendations
      .filter((item) => item.recommendation_type.includes('congestion') || item.recommendation_type.includes('dispatch'))
      .map((item) => ({
        recommendation_id: item.recommendation_id,
        operational_impact: item.operational_impact,
      })),
    continuityRiskWarnings: [{
      continuity_risk: Number(decision?.pressure_analysis?.continuity_degradation_risk || 0),
      continuity_forecast: Number(decision?.forecast?.continuity_risk_forecast || 0),
    }],
    explainableDispatchReasoning: recommendations.map((item) => ({
      recommendation_id: item.recommendation_id,
      evidence_chain: item.evidence_chain || [],
      reasoning_chain: item.reasoning_chain || [],
    })),
    recommendationOnly: Boolean(decision?.recommendation_only),
    backendAuthoritative: Boolean(decision?.backend_authoritative),
    reconnectSafe: Boolean(decision?.replay_safe),
  };
}
