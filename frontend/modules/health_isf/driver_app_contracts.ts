/**
 * Driver operations app contracts.
 * Backend operational status payload is authoritative.
 */

import type { OperationalDecisionIntelligenceSnapshot } from './operational_decision_contracts';
import type { OperationalCoordinationBundle } from './operational_coordination_contracts';

export type DriverClientRole = 'driver';

export interface DriverVisibilityScope {
  role_scope: string[];
  visibility: string[];
  hydration_safe: boolean;
  realtime_safe: boolean;
  websocket_payload_contract: {
    type: string;
    event_type: string;
    payload: string;
    timestamp: string;
    organization_id: string;
    contract_version: string;
  };
}

export interface DriverOperationalIdentitySnapshot {
  organization_id: string;
  operational_session_continuity: {
    active_sessions: number;
    active_identities: number;
    websocket_bound_sessions: number;
  };
  role_continuity: {
    enforced: boolean;
    identity_scoped: boolean;
  };
  tenant_continuity: {
    enforced: boolean;
    organization_id: string;
  };
  reconnect_continuity: {
    supported: boolean;
    append_only_events: boolean;
  };
  events: Array<Record<string, unknown>>;
  sessions: Array<Record<string, unknown>>;
  generated_at: string;
}

export interface DriverGeospatialSnapshot {
  organization_id: string;
  live_operational_map_state: {
    provider_zones: Array<Record<string, unknown>>;
    driver_positioning: Array<Record<string, unknown>>;
    incident_clustering: Array<Record<string, unknown>>;
    emergency_overlays: Array<Record<string, unknown>>;
    operational_density_regions: Array<Record<string, unknown>>;
  };
  realtime_safe: boolean;
  websocket_synchronized: boolean;
  tenant_isolated: boolean;
  replay_safe: boolean;
  hydration_compatible: boolean;
  generated_at: string;
}

export interface DriverDispatchRecommendation {
  recommendation_id: string;
  ride_id: string;
  recommendation_type: string;
  target_id: string;
  confidence: number;
  explainability: string[];
  evidence: Record<string, unknown>;
  approval_required: boolean;
  execution_mode: 'recommendation_only' | string;
}

export interface DriverDispatchSnapshot {
  organization_id: string;
  generated_at: string;
  recommendation_only: boolean;
  approval_required: boolean;
  unrestricted_execution: boolean;
  recommendations: DriverDispatchRecommendation[];
  summary: {
    total: number;
    assignment_recommendations: number;
    emergency_recommendations: number;
    confidence_scored: boolean;
    explainable: boolean;
  };
}

export interface DriverOperationalIntelligenceExpansion {
  operational_identity: DriverOperationalIdentitySnapshot;
  geospatial_intelligence: DriverGeospatialSnapshot;
  dispatch_intelligence: DriverDispatchSnapshot;
  operational_decision_intelligence?: OperationalDecisionIntelligenceSnapshot;
  operational_memory_fabric?: OperationalCoordinationBundle['operational_memory_fabric'];
  adaptive_operational_forecasting?: OperationalCoordinationBundle['adaptive_operational_forecasting'];
  multi_agent_operational_coordination?: OperationalCoordinationBundle['multi_agent_operational_coordination'];
  human_oversight_intelligence?: OperationalCoordinationBundle['human_oversight_intelligence'];
  live_client_foundation_contracts: {
    organization_id: string;
    driver_app: DriverVisibilityScope;
    shared_operational_contracts: {
      stable_websocket_payloads: boolean;
      role_scoped_visibility: boolean;
      tenant_isolated: boolean;
      approval_governed_actions: boolean;
      no_unrestricted_autonomy: boolean;
    };
    generated_at: string;
  };
}

export interface DriverOperationsStatusResponse {
  organization_id: string;
  operational_intelligence_expansion?: DriverOperationalIntelligenceExpansion;
}

export function getDriverExpansionFromOperationsStatus(
  payload: DriverOperationsStatusResponse | null | undefined,
): DriverOperationalIntelligenceExpansion | null {
  const expansion = payload?.operational_intelligence_expansion;
  if (!expansion) {
    return null;
  }

  if (!expansion?.live_client_foundation_contracts?.driver_app) {
    return null;
  }

  return expansion;
}
