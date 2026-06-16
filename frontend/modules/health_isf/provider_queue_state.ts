/**
 * Provider queue state selectors from backend authoritative contracts.
 */

export interface ProviderQueueRenderableState {
  providerQueue: Array<Record<string, unknown>>;
  escalationItems: Array<Record<string, unknown>>;
  recommendationFeed: Array<Record<string, unknown>>;
  realtimeSafe: boolean;
  hydrationSafe: boolean;
  tenantScoped: boolean;
}

export function buildProviderQueueState(expansion: Record<string, unknown> | null | undefined): ProviderQueueRenderableState {
  const dispatch = (expansion?.dispatch_intelligence as Record<string, unknown> | undefined) || {};
  const distributed = (expansion?.distributed_operational_event_fabric as Record<string, unknown> | undefined) || {};
  const replay = (distributed.replay as Record<string, unknown> | undefined) || {};
  const replayEvents = Array.isArray(replay.events) ? (replay.events as Array<Record<string, unknown>>) : [];

  const recommendations = Array.isArray(dispatch.recommendations)
    ? (dispatch.recommendations as Array<Record<string, unknown>>)
    : [];

  const escalations = replayEvents.filter((item) => item.event_type === 'escalation_event');

  return {
    providerQueue: replayEvents.filter((item) => item.event_type === 'provider_status_event' || item.event_type === 'incident_event'),
    escalationItems: escalations,
    recommendationFeed: recommendations,
    realtimeSafe: Boolean(distributed.backend_authoritative),
    hydrationSafe: true,
    tenantScoped: Boolean(distributed.tenant_scoped),
  };
}
