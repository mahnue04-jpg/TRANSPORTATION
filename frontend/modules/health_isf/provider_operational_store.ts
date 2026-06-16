/**
 * Provider operational store for live queue visibility and continuity.
 */

import { buildProviderQueueState, ProviderQueueRenderableState } from './provider_queue_state';
import { createProviderWebSocketClient, ProviderWebSocketClient, ProviderWebSocketState } from './provider_websocket_client';
import {
  ProviderOperationalIntelligenceState,
  buildProviderOperationalIntelligenceState,
} from './provider_intelligence_state';
import { getOperationalDecisionSnapshot } from './operational_decision_contracts';
import {
  ProviderCoordinationAssistState,
  buildProviderCoordinationAssistState,
} from './provider_coordination_assist';
import { getOperationalCoordinationBundle } from './operational_coordination_contracts';

interface ProviderOperationalState {
  organizationId: string;
  userId: string;
  loadedAt: string | null;
  websocketState: ProviderWebSocketState;
  queueState: ProviderQueueRenderableState;
  intelligenceState: ProviderOperationalIntelligenceState;
  coordinationState: ProviderCoordinationAssistState;
  stale: boolean;
  tenantScoped: boolean;
  governanceSafe: boolean;
}

type ProviderStoreListener = (state: ProviderOperationalState) => void;

function nowIso(): string {
  return new Date().toISOString();
}

function storageKey(organizationId: string, userId: string): string {
  return `amicor:provider-operational:${organizationId}:${userId}`;
}

function getAccessToken(): string | null {
  try {
    const sessionToken = localStorage.getItem('amicore:accessToken');
    if (sessionToken) {
      return sessionToken;
    }
    const identityRaw = localStorage.getItem('amicor_identity');
    if (identityRaw) {
      const identity = JSON.parse(identityRaw) as Record<string, unknown>;
      const token = identity?.accessToken || identity?.access_token;
      if (typeof token === 'string' && token.length > 0) {
        return token;
      }
    }
    return localStorage.getItem('auth_token');
  } catch {
    return localStorage.getItem('auth_token');
  }
}

function emptyQueueState(): ProviderQueueRenderableState {
  return {
    providerQueue: [],
    escalationItems: [],
    recommendationFeed: [],
    realtimeSafe: false,
    hydrationSafe: true,
    tenantScoped: true,
  };
}

function emptyIntelligenceState(): ProviderOperationalIntelligenceState {
  return {
    providerWorkloadIntelligence: [],
    escalationPrioritizationVisibility: [],
    operationalQueuePrediction: [],
    continuityRiskIndicators: [],
    recommendationExplanationRendering: [],
    recommendationOnly: true,
    backendAuthoritative: true,
  };
}

function emptyCoordinationState(): ProviderCoordinationAssistState {
  return {
    coordinationRecommendations: [],
    workloadDistributionVisibility: [],
    operationalMemoryRecall: [],
    oversightAwareness: [],
    recommendationOnly: true,
  };
}

export class ProviderOperationalStore {
  private state: ProviderOperationalState;
  private listeners = new Set<ProviderStoreListener>();
  private websocketClient: ProviderWebSocketClient | null = null;

  constructor(private organizationId: string, private userId: string) {
    this.state = {
      organizationId,
      userId,
      loadedAt: null,
      websocketState: 'disconnected',
      queueState: emptyQueueState(),
      intelligenceState: emptyIntelligenceState(),
      coordinationState: emptyCoordinationState(),
      stale: false,
      tenantScoped: true,
      governanceSafe: true,
    };
    this.restoreHydration();
  }

  subscribe(listener: ProviderStoreListener): () => void {
    this.listeners.add(listener);
    listener(this.state);
    return () => this.listeners.delete(listener);
  }

  getState(): ProviderOperationalState {
    return this.state;
  }

  async loadFromBackend(): Promise<void> {
    const token = getAccessToken();
    if (!token) {
      this.setState({ stale: true });
      return;
    }

    const response = await fetch(`/api/ai/operations/status?organization_id=${encodeURIComponent(this.organizationId)}`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (!response.ok) {
      this.setState({ stale: true });
      return;
    }

    const payload = (await response.json()) as {
      organization_id?: string;
      operational_intelligence_expansion?: Record<string, unknown>;
    };
    const expansion = payload.operational_intelligence_expansion;
    const queueState = buildProviderQueueState(expansion);
    const decision = getOperationalDecisionSnapshot(payload);
    const intelligenceState = buildProviderOperationalIntelligenceState(decision);
    const coordinationBundle = getOperationalCoordinationBundle(payload);
    const coordinationState = buildProviderCoordinationAssistState(coordinationBundle);

    this.setState({
      loadedAt: nowIso(),
      stale: false,
      queueState,
      intelligenceState,
      coordinationState,
      tenantScoped: Boolean(queueState.tenantScoped),
      governanceSafe: Boolean(
        (expansion?.distributed_operational_event_fabric as Record<string, unknown> | undefined)?.approval_governed &&
        intelligenceState.recommendationOnly &&
        coordinationState.recommendationOnly,
      ),
    });

    this.persistHydration();
  }

  async connectRealtime(): Promise<void> {
    const token = getAccessToken();
    if (!token) {
      this.setState({ websocketState: 'error', stale: true });
      return;
    }

    this.websocketClient = createProviderWebSocketClient(this.organizationId, this.userId, token);
    this.websocketClient.onStateChange((state) => {
      const disconnected = state === 'disconnected' || state === 'error';
      this.setState({ websocketState: state, stale: disconnected ? true : this.state.stale });
    });
    this.websocketClient.onEvent((event) => {
      const eventType = String(event.event_type || event.type || '');
      if (eventType === 'sync') {
        this.setState({ stale: false, loadedAt: nowIso() });
      }
      if (eventType === 'provider_status_event' || eventType === 'escalation_event' || eventType === 'dispatch_recommendation_event') {
        this.setState({ stale: true });
      }
    });

    await this.websocketClient.connect();
    await this.websocketClient.subscribe('ride_updates');
    await this.websocketClient.subscribe('incident_updates');
    await this.websocketClient.subscribe('workflow_events');
  }

  async recoverContinuity(): Promise<void> {
    this.restoreHydration();
    try {
      await this.loadFromBackend();
      if (!this.websocketClient || this.state.websocketState === 'disconnected' || this.state.websocketState === 'error') {
        await this.connectRealtime();
      }
      this.setState({ stale: false });
    } catch {
      this.setState({ stale: true });
    }
  }

  disconnectRealtime(): void {
    if (this.websocketClient) {
      this.websocketClient.disconnect();
      this.websocketClient = null;
    }
    this.setState({ websocketState: 'disconnected' });
  }

  private setState(patch: Partial<ProviderOperationalState>): void {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((listener) => listener(this.state));
  }

  private persistHydration(): void {
    try {
      localStorage.setItem(storageKey(this.organizationId, this.userId), JSON.stringify(this.state));
    } catch {
      // no-op
    }
  }

  private restoreHydration(): void {
    try {
      const raw = localStorage.getItem(storageKey(this.organizationId, this.userId));
      if (!raw) {
        return;
      }
      const parsed = JSON.parse(raw) as Partial<ProviderOperationalState>;
      if (parsed.organizationId !== this.organizationId || parsed.userId !== this.userId) {
        return;
      }
      this.state = { ...this.state, ...parsed } as ProviderOperationalState;
    } catch {
      // no-op
    }
  }
}

export function createProviderOperationalStore(organizationId: string, userId: string): ProviderOperationalStore {
  return new ProviderOperationalStore(organizationId, userId);
}
