/**
 * Driver coordination assist rendering for supervised multi-agent coordination.
 */

import type { OperationalCoordinationBundle } from './operational_coordination_contracts';

export interface DriverCoordinationAssistState {
  coordinationRecommendations: Array<Record<string, unknown>>;
  operationalMemoryRecall: Array<Record<string, unknown>>;
  continuityAwareness: Array<Record<string, unknown>>;
  recommendationOnly: boolean;
  replaySafe: boolean;
}

export function buildDriverCoordinationAssistState(
  bundle: OperationalCoordinationBundle | null | undefined,
): DriverCoordinationAssistState {
  const coordination = bundle?.multi_agent_operational_coordination;
  const forecast = (bundle?.adaptive_operational_forecasting || {}) as Record<string, unknown>;
  const memory = (bundle?.operational_memory_fabric || {}) as Record<string, unknown>;
  const recommendations = Array.isArray(coordination?.recommendations) ? coordination.recommendations : [];

  return {
    coordinationRecommendations: recommendations.map((item) => ({
      recommendation_id: item.recommendation_id,
      coordination_type: item.coordination_type,
      evidence_chain: item.evidence_chain,
    })),
    operationalMemoryRecall: [((memory.recall_summary as Record<string, unknown> | undefined) || {}) as Record<string, unknown>],
    continuityAwareness: [
      (forecast.continuity_degradation_forecast as Record<string, unknown> | undefined) || {},
      (forecast.recovery_timeline_estimation as Record<string, unknown> | undefined) || {},
    ],
    recommendationOnly: Boolean(coordination?.recommendation_only),
    replaySafe: Boolean(coordination?.replay_safe),
  };
}
