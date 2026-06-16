/**
 * Provider operational app contracts.
 */

import type { DistributedEventFabricSnapshot } from './operational_event_contracts';
import type { OperationalDecisionIntelligenceSnapshot } from './operational_decision_contracts';
import type { OperationalCoordinationBundle } from './operational_coordination_contracts';

export interface ProviderVisibilityScope {
  role_scope: string[];
  visibility: string[];
  hydration_safe: boolean;
  realtime_safe: boolean;
  websocket_payload_contract: Record<string, string>;
}

export interface ProviderOperationalContracts {
  organization_id: string;
  live_client_foundation_contracts?: {
    provider_app?: ProviderVisibilityScope;
    shared_operational_contracts?: {
      stable_websocket_payloads: boolean;
      role_scoped_visibility: boolean;
      tenant_isolated: boolean;
      approval_governed_actions: boolean;
      no_unrestricted_autonomy: boolean;
    };
  };
  distributed_operational_event_fabric?: DistributedEventFabricSnapshot;
  operational_decision_intelligence?: OperationalDecisionIntelligenceSnapshot;
  operational_memory_fabric?: OperationalCoordinationBundle['operational_memory_fabric'];
  adaptive_operational_forecasting?: OperationalCoordinationBundle['adaptive_operational_forecasting'];
  multi_agent_operational_coordination?: OperationalCoordinationBundle['multi_agent_operational_coordination'];
  human_oversight_intelligence?: OperationalCoordinationBundle['human_oversight_intelligence'];
}

export function getProviderContracts(payload: Record<string, unknown> | null | undefined): ProviderOperationalContracts | null {
  if (!payload || typeof payload !== 'object') {
    return null;
  }

  const expansion = (payload as { operational_intelligence_expansion?: Record<string, unknown> }).operational_intelligence_expansion;
  if (!expansion || typeof expansion !== 'object') {
    return null;
  }

  return {
    organization_id: String((payload as { organization_id?: string }).organization_id || ''),
    live_client_foundation_contracts: expansion.live_client_foundation_contracts as ProviderOperationalContracts['live_client_foundation_contracts'],
    distributed_operational_event_fabric: expansion.distributed_operational_event_fabric as DistributedEventFabricSnapshot,
    operational_decision_intelligence: expansion.operational_decision_intelligence as OperationalDecisionIntelligenceSnapshot,
    operational_memory_fabric: expansion.operational_memory_fabric as ProviderOperationalContracts['operational_memory_fabric'],
    adaptive_operational_forecasting: expansion.adaptive_operational_forecasting as ProviderOperationalContracts['adaptive_operational_forecasting'],
    multi_agent_operational_coordination: expansion.multi_agent_operational_coordination as ProviderOperationalContracts['multi_agent_operational_coordination'],
    human_oversight_intelligence: expansion.human_oversight_intelligence as ProviderOperationalContracts['human_oversight_intelligence'],
  };
}
