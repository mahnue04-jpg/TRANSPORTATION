/**
 * Provider operational intelligence rendering state.
 */

import type { OperationalDecisionIntelligenceSnapshot } from './operational_decision_contracts';

export interface ProviderOperationalIntelligenceState {
  providerWorkloadIntelligence: Array<Record<string, unknown>>;
  escalationPrioritizationVisibility: Array<Record<string, unknown>>;
  operationalQueuePrediction: Array<Record<string, unknown>>;
  continuityRiskIndicators: Array<Record<string, unknown>>;
  recommendationExplanationRendering: Array<Record<string, unknown>>;
  recommendationOnly: boolean;
  backendAuthoritative: boolean;
}

export function buildProviderOperationalIntelligenceState(
  decision: OperationalDecisionIntelligenceSnapshot | null | undefined,
): ProviderOperationalIntelligenceState {
  const recommendations = Array.isArray(decision?.recommendations) ? decision.recommendations : [];

  return {
    providerWorkloadIntelligence: [{
      queue_pressure: Number(decision?.pressure_analysis?.provider_queue_pressure || 0),
      workload_balance_forecast: Number(decision?.forecast?.workload_balance_forecast || 0),
      resource_pressure_forecast: Number(decision?.forecast?.resource_pressure_forecast || 0),
    }],
    escalationPrioritizationVisibility: recommendations
      .filter((item) => item.recommendation_type.includes('escalation'))
      .map((item) => ({
        recommendation_id: item.recommendation_id,
        escalation_score: Number(item.escalation_score || 0),
        severity_weight: Number(item.severity_weight || 0),
      })),
    operationalQueuePrediction: recommendations
      .filter((item) => item.recommendation_type.includes('workload') || item.recommendation_type.includes('resource'))
      .map((item) => ({
        recommendation_id: item.recommendation_id,
        operational_impact: item.operational_impact,
      })),
    continuityRiskIndicators: [{
      continuity_risk: Number(decision?.pressure_analysis?.continuity_degradation_risk || 0),
      continuity_forecast: Number(decision?.forecast?.continuity_risk_forecast || 0),
    }],
    recommendationExplanationRendering: recommendations.map((item) => ({
      recommendation_id: item.recommendation_id,
      evidence_chain: item.evidence_chain,
      reasoning_chain: item.reasoning_chain,
      confidence: Number(item.confidence || 0),
    })),
    recommendationOnly: Boolean(decision?.recommendation_only),
    backendAuthoritative: Boolean(decision?.backend_authoritative),
  };
}
