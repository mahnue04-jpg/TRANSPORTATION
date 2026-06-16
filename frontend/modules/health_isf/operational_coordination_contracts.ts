/**
 * Multi-agent coordination, memory, adaptive forecast, and oversight contracts.
 */

export interface MultiAgentCoordinationRecommendation {
  recommendation_id: string;
  coordination_type: string;
  confidence: number;
  workload_score: number;
  continuity_score: number;
  regional_score: number;
  evidence_chain: Array<Record<string, unknown>>;
  reasoning_chain: string[];
  recommendation_only: boolean;
  approval_required: boolean;
}

export interface OperationalCoordinationBundle {
  operational_memory_fabric?: Record<string, unknown>;
  adaptive_operational_forecasting?: Record<string, unknown>;
  multi_agent_operational_coordination?: {
    organization_id: string;
    backend_authoritative: boolean;
    tenant_scoped: boolean;
    replay_safe: boolean;
    websocket_synchronized: boolean;
    explainable: boolean;
    auditable: boolean;
    recommendation_only: boolean;
    coordination_summary: Record<string, unknown>;
    recommendations: MultiAgentCoordinationRecommendation[];
  };
  human_oversight_intelligence?: {
    approval_governed: boolean;
    recommendation_only: boolean;
    replay_safe: boolean;
    auditable: boolean;
    no_automatic_execution: boolean;
    approval_workflows: Array<Record<string, unknown>>;
    reasoning_inspection: Record<string, unknown>;
    audit_playback: Record<string, unknown>;
  };
}

export interface OperationalCoordinationStatusContract {
  operational_intelligence_expansion?: OperationalCoordinationBundle;
}

export function getOperationalCoordinationBundle(
  payload: OperationalCoordinationStatusContract | null | undefined,
): OperationalCoordinationBundle | null {
  const expansion = payload?.operational_intelligence_expansion;
  if (!expansion) {
    return null;
  }

  const coordination = expansion.multi_agent_operational_coordination;
  if (coordination) {
    if (!coordination.backend_authoritative || !coordination.tenant_scoped || !coordination.recommendation_only) {
      return null;
    }
  }

  const oversight = expansion.human_oversight_intelligence;
  if (oversight && (!oversight.approval_governed || !oversight.no_automatic_execution)) {
    return null;
  }

  return expansion;
}
