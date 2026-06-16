/**
 * Provider coordination assist rendering for supervised multi-agent coordination.
 */

import type { OperationalCoordinationBundle } from './operational_coordination_contracts';

export interface ProviderCoordinationAssistState {
  coordinationRecommendations: Array<Record<string, unknown>>;
  workloadDistributionVisibility: Array<Record<string, unknown>>;
  operationalMemoryRecall: Array<Record<string, unknown>>;
  oversightAwareness: Array<Record<string, unknown>>;
  recommendationOnly: boolean;
}

export function buildProviderCoordinationAssistState(
  bundle: OperationalCoordinationBundle | null | undefined,
): ProviderCoordinationAssistState {
  const coordination = bundle?.multi_agent_operational_coordination;
  const recommendations = Array.isArray(coordination?.recommendations) ? coordination.recommendations : [];
  const summary = (coordination?.coordination_summary || {}) as Record<string, unknown>;

  return {
    coordinationRecommendations: recommendations.map((item) => ({
      recommendation_id: item.recommendation_id,
      coordination_type: item.coordination_type,
      confidence: item.confidence,
    })),
    workloadDistributionVisibility: [(summary.workload_summary as Record<string, unknown> | undefined) || {}],
    operationalMemoryRecall: [((bundle?.operational_memory_fabric || {}) as Record<string, unknown>).recall_summary || {}],
    oversightAwareness: [bundle?.human_oversight_intelligence || {}],
    recommendationOnly: Boolean(coordination?.recommendation_only),
  };
}
