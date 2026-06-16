/**
 * Driver operational store for hydration-safe state and session continuity.
 */

import {
  DriverDispatchFeedItem,
  buildDriverDispatchFeed,
} from './driver_dispatch_feed';
import {
  DriverOperationalIntelligenceExpansion,
  DriverOperationsStatusResponse,
  getDriverExpansionFromOperationsStatus,
} from './driver_app_contracts';
import {
  DriverMapRenderableState,
  buildDriverMapRenderableState,
} from './driver_map_state';
import {
  DriverWebSocketClient,
  DriverWebSocketEvent,
  DriverWebSocketState,
  createDriverWebSocketClient,
} from './driver_websocket_client';
import {
  DriverIntelligenceAssistState,
  buildDriverIntelligenceAssistState,
} from './driver_intelligence_assist';
import {
  DriverCoordinationAssistState,
  buildDriverCoordinationAssistState,
} from './driver_coordination_assist';
import { getOperationalCoordinationBundle } from './operational_coordination_contracts';

interface DriverOperationalState {
  organizationId: string;
  userId: string;
  loadedAt: string | null;
  stale: boolean;
  websocketState: DriverWebSocketState;
  expansion: DriverOperationalIntelligenceExpansion | null;
  mapState: DriverMapRenderableState;
  dispatchFeed: DriverDispatchFeedItem[];
  operationalAlerts: Array<Record<string, unknown>>;
  incidents: Array<Record<string, unknown>>;
  intelligenceAssist: DriverIntelligenceAssistState;
  coordinationAssist: DriverCoordinationAssistState;
  sessionRecovered: boolean;
  governanceSafe: boolean;
  tenantScoped: boolean;
}

type DriverOperationalListener = (state: DriverOperationalState) => void;

const STALE_AFTER_MS = 2 * 60 * 1000;

function nowIso(): string {
  return new Date().toISOString();
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

    const legacyToken = localStorage.getItem('auth_token');
    return legacyToken || null;
  } catch {
    return localStorage.getItem('auth_token');
  }
}

function storageKey(organizationId: string, userId: string): string {
  return `amicor:driver-operational:${organizationId}:${userId}`;
}

function emptyMapState(): DriverMapRenderableState {
  return {
    providerZones: [],
    driverPositions: [],
    incidentOverlays: [],
    emergencyOverlays: [],
    dispatchRecommendationOverlays: [],
    densityRegions: [],
    synchronized: false,
    hydrationSafe: true,
  };
}

function emptyIntelligenceAssistState(): DriverIntelligenceAssistState {
  return {
    operationalRecommendationVisibility: [],
    escalationAwareness: [],
    congestionRerouteSuggestions: [],
    continuityRiskWarnings: [],
    explainableDispatchReasoning: [],
    recommendationOnly: true,
    backendAuthoritative: true,
    reconnectSafe: true,
  };
}

function emptyCoordinationAssistState(): DriverCoordinationAssistState {
  return {
    coordinationRecommendations: [],
    operationalMemoryRecall: [],
    continuityAwareness: [],
    recommendationOnly: true,
    replaySafe: true,
  };
}

export class DriverOperationalStore {
  private state: DriverOperationalState;
  private listeners = new Set<DriverOperationalListener>();
  private websocketClient: DriverWebSocketClient | null = null;

  constructor(private organizationId: string, private userId: string) {
    this.state = {
      organizationId,
      userId,
      loadedAt: null,
      stale: false,
      websocketState: 'disconnected',
      expansion: null,
      mapState: emptyMapState(),
      dispatchFeed: [],
      operationalAlerts: [],
      incidents: [],
      intelligenceAssist: emptyIntelligenceAssistState(),
      coordinationAssist: emptyCoordinationAssistState(),
      sessionRecovered: false,
      governanceSafe: true,
      tenantScoped: true,
    };

    this.restoreHydration();
  }

  subscribe(listener: DriverOperationalListener): () => void {
    this.listeners.add(listener);
    listener(this.state);
    return () => this.listeners.delete(listener);
  }

  getState(): DriverOperationalState {
    return this.state;
  }

  async loadFromBackend(): Promise<void> {
    const token = getAccessToken();
    if (!token) {
      this.setState({ stale: true, governanceSafe: true, tenantScoped: true });
      return;
    }

    const response = await fetch(`/api/ai/operations/status?organization_id=${encodeURIComponent(this.organizationId)}`, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    if (!response.ok) {
      this.setState({ stale: true });
      return;
    }

    const payload = (await response.json()) as DriverOperationsStatusResponse;
    const expansion = getDriverExpansionFromOperationsStatus(payload);
    const dispatchFeed = buildDriverDispatchFeed(expansion?.dispatch_intelligence);
    const mapState = buildDriverMapRenderableState(
      expansion?.geospatial_intelligence,
      dispatchFeed as unknown as Array<Record<string, unknown>>,
    );

    const incidents = mapState.incidentOverlays;
    const operationalAlerts = mapState.emergencyOverlays;
    const intelligenceAssist = buildDriverIntelligenceAssistState(expansion?.operational_decision_intelligence);
    const coordinationBundle = getOperationalCoordinationBundle(payload);
    const coordinationAssist = buildDriverCoordinationAssistState(coordinationBundle);

    this.setState({
      loadedAt: nowIso(),
      stale: false,
      expansion,
      dispatchFeed,
      mapState,
      incidents,
      operationalAlerts,
      intelligenceAssist,
      coordinationAssist,
      governanceSafe: Boolean(
        expansion?.dispatch_intelligence?.recommendation_only &&
        expansion?.live_client_foundation_contracts?.shared_operational_contracts?.approval_governed_actions &&
        intelligenceAssist.recommendationOnly &&
        coordinationAssist.recommendationOnly,
      ),
      tenantScoped: Boolean(
        expansion?.geospatial_intelligence?.tenant_isolated &&
        expansion?.operational_identity?.tenant_continuity?.enforced,
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

    this.websocketClient = createDriverWebSocketClient(this.organizationId, this.userId, token);
    this.websocketClient.onStateChange((state) => {
      this.setState({ websocketState: state });
      if (state === 'subscribed' || state === 'connected') {
        this.setState({ sessionRecovered: true, stale: false });
      } else if (state === 'disconnected' || state === 'error') {
        this.setState({ stale: true });
      }
    });
    this.websocketClient.onEvent((event) => this.handleWebSocketEvent(event));

    await this.websocketClient.connect();
    await this.websocketClient.subscribe('driver_dashboard');
    await this.websocketClient.subscribe('ride_updates');
    await this.websocketClient.subscribe('incident_updates');
  }

  async recoverSession(): Promise<void> {
    this.restoreHydration();

    const loadedAt = this.state.loadedAt ? Date.parse(this.state.loadedAt) : 0;
    const stale = !loadedAt || Number.isNaN(loadedAt) || Date.now() - loadedAt > STALE_AFTER_MS;

    if (stale) {
      this.setState({ stale: true });
      try {
        await this.loadFromBackend();
      } catch {
        this.setState({ stale: true });
      }
    }

    if (!this.websocketClient || !this.websocketClient.isConnected()) {
      try {
        await this.connectRealtime();
      } catch {
        this.setState({ stale: true, websocketState: 'error' });
      }
    }
  }

  disconnectRealtime(): void {
    if (this.websocketClient) {
      this.websocketClient.disconnect();
      this.websocketClient = null;
    }
    this.setState({ websocketState: 'disconnected' });
  }

  private handleWebSocketEvent(event: DriverWebSocketEvent): void {
    if (event.type === 'event' && event.payload) {
      const payload = event.payload;
      if (event.event_type === 'incident_updates') {
        const incidents = [payload, ...this.state.incidents].slice(0, 100);
        this.setState({ incidents });
      }
      if (event.event_type === 'driver_status_changed' || event.event_type === 'ride_updates') {
        this.setState({ loadedAt: nowIso(), stale: false });
      }
    }

    if (event.type === 'error') {
      this.setState({ stale: true, websocketState: 'error' });
    }

    this.persistHydration();
  }

  private setState(patch: Partial<DriverOperationalState>): void {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((listener) => listener(this.state));
  }

  private persistHydration(): void {
    try {
      localStorage.setItem(storageKey(this.organizationId, this.userId), JSON.stringify(this.state));
    } catch {
      // no-op, hydration persistence is best-effort.
    }
  }

  private restoreHydration(): void {
    try {
      const raw = localStorage.getItem(storageKey(this.organizationId, this.userId));
      if (!raw) {
        return;
      }
      const parsed = JSON.parse(raw) as Partial<DriverOperationalState>;
      if (parsed.organizationId !== this.organizationId || parsed.userId !== this.userId) {
        return;
      }

      const loadedAt = parsed.loadedAt ? Date.parse(parsed.loadedAt) : 0;
      const stale = !loadedAt || Number.isNaN(loadedAt) || Date.now() - loadedAt > STALE_AFTER_MS;

      this.state = {
        ...this.state,
        ...parsed,
        stale,
      } as DriverOperationalState;
    } catch {
      // no-op, fallback to defaults.
    }
  }
}

export function createDriverOperationalStore(organizationId: string, userId: string): DriverOperationalStore {
  return new DriverOperationalStore(organizationId, userId);
}
