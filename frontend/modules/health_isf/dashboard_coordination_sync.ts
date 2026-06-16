/**
 * Dashboard coordination rendering helpers for multi-agent operational coordination.
 */

import type { OperationalCoordinationBundle } from './operational_coordination_contracts';

export interface DashboardCoordinationSyncState {
  coordinationRecommendationRendering: Array<Record<string, unknown>>;
  operationalMemoryRecall: Array<Record<string, unknown>>;
  escalationVisibility: Array<Record<string, unknown>>;
  operationsCenterAwareness: Array<Record<string, unknown>>;
  websocketSynchronized: boolean;
}

export function buildDashboardCoordinationSyncState(
  bundle: OperationalCoordinationBundle | null | undefined,
): DashboardCoordinationSyncState {
  const coordination = bundle?.multi_agent_operational_coordination;
  const memory = (bundle?.operational_memory_fabric || {}) as Record<string, unknown>;
  const recommendations = Array.isArray(coordination?.recommendations) ? coordination.recommendations : [];
  const recallSummary = (memory.recall_summary || {}) as Record<string, unknown>;

  return {
    coordinationRecommendationRendering: recommendations.map((item) => ({
      recommendation_id: item.recommendation_id,
      coordination_type: item.coordination_type,
      confidence: Number(item.confidence || 0),
    })),
    operationalMemoryRecall: [recallSummary],
    escalationVisibility: recommendations
      .filter((item) => item.coordination_type.includes('escalation') || item.coordination_type.includes('incident'))
      .map((item) => ({
        recommendation_id: item.recommendation_id,
        reasoning_chain: item.reasoning_chain,
      })),
    operationsCenterAwareness: [coordination?.coordination_summary || {}],
    websocketSynchronized: Boolean(coordination?.websocket_synchronized),
  };
}
