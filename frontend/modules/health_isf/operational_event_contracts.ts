/**
 * Frontend contracts for distributed operational event fabric.
 * Clients remain consumers of backend-authoritative event streams.
 */

export type OperationalEventType =
  | 'incident_event'
  | 'dispatch_recommendation_event'
  | 'coordination_recommendation_event'
  | 'geospatial_update_event'
  | 'escalation_event'
  | 'provider_status_event'
  | 'driver_state_event'
  | 'websocket_reconnect_event'
  | 'operational_alert_broadcast_event';

export interface OperationalEventEnvelope {
  organization_id: string;
  sequence: number;
  event_type: OperationalEventType;
  role_scope: string[];
  payload: Record<string, unknown>;
  emitted_at: string;
  approval_governed: boolean;
  replayable: boolean;
}

export interface DistributedEventFabricSnapshot {
  event_types_supported: OperationalEventType[];
  synchronization: {
    organization_id: string;
    cross_client_operational_synchronization: boolean;
    dashboard_driver_provider_event_propagation: boolean;
    future_customer_synchronization_hooks: boolean;
    tenant_scoped_event_streaming: boolean;
    operational_state_reconciliation: boolean;
    reconnect_safe_replay_handling: boolean;
    stale_event_rejection: boolean;
    ordered_operational_event_sequencing: boolean;
    event_bus: {
      organization_id: string;
      total_events: number;
      latest_sequence: number;
      tenant_scoped: boolean;
      ordered: boolean;
      replay_safe: boolean;
    };
    recent_events: OperationalEventEnvelope[];
  };
  replay: {
    organization_id: string;
    role: string;
    events: OperationalEventEnvelope[];
    cursor: {
      organization_id: string;
      last_sequence: number;
      generated_at: string;
    };
    reconnect_safe: boolean;
    tenant_scoped: boolean;
    approval_governed: boolean;
    backend_authoritative: boolean;
  };
  replay_integrity: {
    organization_id: string;
    ordered: boolean;
    no_duplicates: boolean;
    latest_sequence: number;
    total_events: number;
    integrity_ok: boolean;
  };
  event_publication_results: Array<Record<string, unknown>>;
  backend_authoritative: boolean;
  approval_governed: boolean;
  tenant_scoped: boolean;
}

export interface DistributedOperationsStatusContract {
  organization_id: string;
  operational_intelligence_expansion?: {
    distributed_operational_event_fabric?: DistributedEventFabricSnapshot;
  };
}

export function getDistributedEventFabric(
  payload: DistributedOperationsStatusContract | null | undefined,
): DistributedEventFabricSnapshot | null {
  const snapshot = payload?.operational_intelligence_expansion?.distributed_operational_event_fabric;
  if (!snapshot) {
    return null;
  }
  if (!snapshot.backend_authoritative || !snapshot.approval_governed || !snapshot.tenant_scoped) {
    return null;
  }
  return snapshot;
}
