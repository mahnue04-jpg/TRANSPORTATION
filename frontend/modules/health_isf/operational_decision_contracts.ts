/**
 * Operational decision intelligence contracts.
 * Frontend remains a renderer of backend-authoritative recommendations.
 */

export interface OperationalDecisionRecommendation {
  recommendation_id: string;
  recommendation_type: string;
  priority_score: number;
  escalation_score: number;
  severity_weight: number;
  confidence: number;
  sla_impact: 'low' | 'medium' | 'high' | string;
  operational_impact: string;
  evidence_chain: Array<Record<string, unknown>>;
  reasoning_chain: string[];
  recommendation_only: boolean;
  approval_required: boolean;
}

export interface OperationalDecisionIntelligenceSnapshot {
  organization_id: string;
  generated_at: string;
  recommendation_only: boolean;
  approval_governed: boolean;
  backend_authoritative: boolean;
  tenant_scoped: boolean;
  replay_safe: boolean;
  websocket_synchronized: boolean;
  pressure_analysis: {
    regional_congestion: number;
    driver_load_pressure: number;
    provider_queue_pressure: number;
    escalation_surge: number;
    incident_clustering: number;
    continuity_degradation_risk: number;
  };
  forecast: {
    operational_congestion_prediction: number;
    continuity_risk_forecast: number;
    workload_balance_forecast: number;
    resource_pressure_forecast: number;
    recommendation_only: boolean;
    tenant_scoped: boolean;
    replay_safe: boolean;
    websocket_synchronized: boolean;
  };
  recommendations: OperationalDecisionRecommendation[];
  summary: {
    total_recommendations: number;
    operational_prioritization: boolean;
    escalation_scoring: boolean;
    dispatch_recommendation_ranking: boolean;
    incident_severity_weighting: boolean;
    workload_balancing_recommendations: boolean;
    resource_pressure_forecasting: boolean;
    explainable: boolean;
    confidence_scored: boolean;
    recommendation_only: boolean;
    approval_governed: boolean;
    no_hidden_inference_paths: boolean;
  };
}

export interface OperationalDecisionStatusContract {
  organization_id: string;
  operational_intelligence_expansion?: {
    operational_decision_intelligence?: OperationalDecisionIntelligenceSnapshot;
  };
}

export function getOperationalDecisionSnapshot(
  payload: OperationalDecisionStatusContract | null | undefined,
): OperationalDecisionIntelligenceSnapshot | null {
  const snapshot = payload?.operational_intelligence_expansion?.operational_decision_intelligence;
  if (!snapshot) {
    return null;
  }

  if (!snapshot.backend_authoritative || !snapshot.approval_governed || !snapshot.tenant_scoped) {
    return null;
  }
  if (!snapshot.recommendation_only || !snapshot.summary?.recommendation_only) {
    return null;
  }
  return snapshot;
}
