/**
 * Additive dashboard live coordination layer.
 * Preserves existing analytics surfaces while adding synchronized overlays.
 */

import type { DistributedEventFabricSnapshot } from './operational_event_contracts';
import type { OperationalDecisionIntelligenceSnapshot } from './operational_decision_contracts';
import { buildDashboardIntelligenceOverlays, DashboardIntelligenceOverlays } from './dashboard_intelligence_overlays';
import type { OperationalCoordinationBundle } from './operational_coordination_contracts';
import { buildDashboardCoordinationSyncState, DashboardCoordinationSyncState } from './dashboard_coordination_sync';

export interface DashboardLiveCoordinationState {
  synchronizedOperationalOverlays: Array<Record<string, unknown>>;
  liveOperationalReplayStream: Array<Record<string, unknown>>;
  realtimeAlertSynchronization: Array<Record<string, unknown>>;
  distributedOperationalVisibility: {
    latestSequence: number;
    totalEvents: number;
    integrityOk: boolean;
  };
  tenantScopedIntelligenceRendering: boolean;
  dashboardIntelligenceOverlays: DashboardIntelligenceOverlays;
  coordinationSync: DashboardCoordinationSyncState;
}

export function buildDashboardLiveCoordinationState(
  fabric: DistributedEventFabricSnapshot | null | undefined,
  decision: OperationalDecisionIntelligenceSnapshot | null | undefined = null,
  coordinationBundle: OperationalCoordinationBundle | null | undefined = null,
): DashboardLiveCoordinationState {
  const replayEvents = Array.isArray(fabric?.replay?.events) ? fabric!.replay.events : [];
  const recentEvents = Array.isArray(fabric?.synchronization?.recent_events) ? fabric!.synchronization.recent_events : [];

  return {
    synchronizedOperationalOverlays: recentEvents.filter((item) => item.event_type === 'geospatial_update_event'),
    liveOperationalReplayStream: replayEvents,
    realtimeAlertSynchronization: replayEvents.filter((item) => item.event_type === 'operational_alert_broadcast_event'),
    distributedOperationalVisibility: {
      latestSequence: Number(fabric?.synchronization?.event_bus?.latest_sequence || 0),
      totalEvents: Number(fabric?.synchronization?.event_bus?.total_events || 0),
      integrityOk: Boolean(fabric?.replay_integrity?.integrity_ok),
    },
    tenantScopedIntelligenceRendering: Boolean(fabric?.tenant_scoped),
    dashboardIntelligenceOverlays: buildDashboardIntelligenceOverlays(decision),
    coordinationSync: buildDashboardCoordinationSyncState(coordinationBundle),
  };
}
