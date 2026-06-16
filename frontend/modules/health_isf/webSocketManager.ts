/**
 * Real-Time WebSocket Manager for Dispatcher Operations
 * Manages WebSocket connections, subscriptions, and event handling
 */

import {
  WebSocketEvent,
  RideUpdateEvent,
  DispatcherRide,
} from './dispatcherTypes';

export type WebSocketConnectionState = 'disconnected' | 'connecting' | 'connected' | 'subscribed' | 'error';

export interface WebSocketManager {
  state: WebSocketConnectionState;
  connectionId?: string;
  connect(): Promise<void>;
  disconnect(): void;
  subscribe(subscriptionType: 'dispatcher_board'): Promise<void>;
  unsubscribe(subscriptionType: 'dispatcher_board'): Promise<void>;
  onRideUpdate(callback: (ride: DispatcherRide) => void): () => void;
  onEvent(callback: (event: WebSocketEvent) => void): () => void;
  onStateChange(callback: (state: WebSocketConnectionState) => void): () => void;
  isConnected(): boolean;
  getReliabilitySnapshot(): Record<string, unknown>;
  getCoordinationSnapshot(): Record<string, unknown>;
  getCognitiveSnapshot(): Record<string, unknown>;
}

class DispatcherWebSocketManager implements WebSocketManager {
  state: WebSocketConnectionState = 'disconnected';
  connectionId?: string;
  private ws?: WebSocket;
  private organizationId: string;
  private userId: string;
  private token: string;
  private role: string;
  private heartbeatInterval?: number;
  private stateListeners: Set<(state: WebSocketConnectionState) => void> = new Set();
  private eventListeners: Set<(event: WebSocketEvent) => void> = new Set();
  private rideUpdateListeners: Set<(ride: DispatcherRide) => void> = new Set();
  private messageQueue: string[] = [];
  private subscribedTypes: Set<'dispatcher_board'> = new Set();
  private maxRetries = 8;
  private retryCount = 0;
  private retryDelay = 1000;
  private maxRetryDelay = 30000;
  private shouldReconnect = true;
  private reconnectTimer?: number;
  private staleSocketGuard?: number;
  private lastPongAt = 0;
  private readonly staleTimeoutMs = 70000;
  private lastSequence = 0;
  private seenEventIds: Set<string> = new Set();
  private readonly maxSeenEventIds = 5000;
  private reconnectCount = 0;
  private replayCount = 0;
  private hydrationRetries = 0;
  private recoveryAttempts = 0;
  private degradedReasons: string[] = [];
  private workflowCoordination: Record<string, unknown> = {};
  private distributedGovernance: Record<string, unknown> = {};
  private cognitiveDiagnostics: Record<string, unknown> = {};
  private workflowTimelines: Map<string, Record<string, unknown>> = new Map();
  private clientSessionId = `dispatch-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  private hydrationRetryTimer?: number;

  constructor(organizationId: string, userId: string, token: string, role: string = 'dispatcher') {
    this.organizationId = organizationId;
    this.userId = userId;
    this.token = token;
    this.role = role;
  }

  async connect(): Promise<void> {
    if (this.state !== 'disconnected' && this.state !== 'error') {
      console.warn(`Cannot connect: already in state ${this.state}`);
      return;
    }

    this.shouldReconnect = true;
    this.setState('connecting');
    this.restoreContinuityState();

    try {
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const restoreSubs = Array.from(this.subscribedTypes.values()).join(',');
      const wsUrl = `${wsProtocol}//${window.location.host}/api/health-isf/ws/live/${this.organizationId}/${this.userId}?role=${this.role}&token=${encodeURIComponent(this.token)}&last_sequence=${encodeURIComponent(String(this.lastSequence || 0))}&restore_subscriptions=${encodeURIComponent(restoreSubs)}&client_session_id=${encodeURIComponent(this.clientSessionId)}`;

      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        console.log('[Dispatcher WebSocket] Connected');
        if (this.retryCount > 0) {
          this.reconnectCount += 1;
        }
        this.retryCount = 0;
        this.lastPongAt = Date.now();
        this.startHeartbeat();
        this.startStaleSocketGuard();
      };

      this.ws.onmessage = (event) => {
        this.handleMessage(event.data);
      };

      this.ws.onerror = (error) => {
        console.error('[Dispatcher WebSocket] Error:', error);
        this.setState('error');
      };

      this.ws.onclose = () => {
        console.log('[Dispatcher WebSocket] Disconnected');
        this.stopHeartbeat();
        this.stopStaleSocketGuard();
        this.setState('disconnected');
        if (this.shouldReconnect) {
          this.attemptReconnect();
        }
      };

      // Wait for connection to be established
      await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => {
          reject(new Error('WebSocket connection timeout'));
        }, 5000);

        const checkConnection = () => {
          if (this.state === 'connected') {
            clearTimeout(timeout);
            resolve();
          } else if (this.state === 'error') {
            clearTimeout(timeout);
            reject(new Error('WebSocket connection failed'));
          } else {
            setTimeout(checkConnection, 100);
          }
        };

        checkConnection();
      });
    } catch (error) {
      console.error('[Dispatcher WebSocket] Connection failed:', error);
      this.setState('error');
      throw error;
    }
  }

  disconnect(): void {
    this.shouldReconnect = false;
    this.stopHeartbeat();
    this.stopStaleSocketGuard();
    this.stopHydrationRetry();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = undefined;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = undefined;
    }
    this.setState('disconnected');
  }

  async subscribe(subscriptionType: 'dispatcher_board'): Promise<void> {
    if (!this.isConnected()) {
      throw new Error('WebSocket not connected');
    }

    const message = JSON.stringify({
      type: 'subscribe',
      subscription_type: subscriptionType,
    });

    this.send(message);
    this.subscribedTypes.add(subscriptionType);

    // Wait for subscription confirmation
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error(`Subscription timeout for ${subscriptionType}`));
      }, 5000);

      const listener = (event: WebSocketEvent) => {
        if (event.type === 'subscribed' && event.subscription_type === subscriptionType) {
          clearTimeout(timeout);
          this.removeEventListener(listener);
          this.setState('subscribed');
          resolve();
        }
      };

      this.onEvent(listener);
    });
  }

  async unsubscribe(subscriptionType: 'dispatcher_board'): Promise<void> {
    if (!this.isConnected()) {
      return;
    }

    const message = JSON.stringify({
      type: 'unsubscribe',
      subscription_type: subscriptionType,
    });

    this.send(message);
    this.subscribedTypes.delete(subscriptionType);
  }

  onRideUpdate(callback: (ride: DispatcherRide) => void): () => void {
    this.rideUpdateListeners.add(callback);
    return () => this.rideUpdateListeners.delete(callback);
  }

  onEvent(callback: (event: WebSocketEvent) => void): () => void {
    this.eventListeners.add(callback);
    return () => this.eventListeners.delete(callback);
  }

  onStateChange(callback: (state: WebSocketConnectionState) => void): () => void {
    this.stateListeners.add(callback);
    return () => this.stateListeners.delete(callback);
  }

  isConnected(): boolean {
    return this.state === 'connected' || this.state === 'subscribed';
  }

  getReliabilitySnapshot(): Record<string, unknown> {
    return {
      reconnectCount: this.reconnectCount,
      replayCount: this.replayCount,
      hydrationRetries: this.hydrationRetries,
      recoveryAttempts: this.recoveryAttempts,
      lastSequence: this.lastSequence,
      degradedReasons: this.degradedReasons,
      queueDepth: this.messageQueue.length,
      websocketState: this.state,
    };
  }

  getCoordinationSnapshot(): Record<string, unknown> {
    return {
      workflowCoordination: this.workflowCoordination,
      distributedGovernance: this.distributedGovernance,
      cognitiveDiagnostics: this.cognitiveDiagnostics,
      workflowTimelines: Object.fromEntries(this.workflowTimelines.entries()),
      trackedChains: this.workflowTimelines.size,
      lastSequence: this.lastSequence,
    };
  }

  getCognitiveSnapshot(): Record<string, unknown> {
    return {
      cognitiveDiagnostics: this.cognitiveDiagnostics,
      runtimeStabilityScore: Number((this.cognitiveDiagnostics as Record<string, unknown>).runtime_stability_score || 0),
      orchestrationConfidence: Number((this.cognitiveDiagnostics as Record<string, unknown>).orchestration_confidence || 0),
      executionRiskLevel: String((this.cognitiveDiagnostics as Record<string, unknown>).execution_risk_level || 'low'),
      workflowHealthScore: Number((this.cognitiveDiagnostics as Record<string, unknown>).workflow_health_score || 0),
    };
  }

  // Private methods

  private send(message: string): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(message);
    } else {
      this.messageQueue.push(message);
    }
  }

  private setState(newState: WebSocketConnectionState): void {
    if (this.state !== newState) {
      this.state = newState;
      if (newState === 'connected') {
        this.flushMessageQueue();
      }
      this.stateListeners.forEach(listener => listener(newState));
    }
  }

  private handleMessage(data: string): void {
    try {
      const event = JSON.parse(data) as WebSocketEvent;

      // Handle connection confirmation
      if (event.type === 'connected') {
        this.connectionId = event.connection_id;
        if (event.workflow_coordination) {
          this.workflowCoordination = { ...event.workflow_coordination };
        }
        if (event.distributed_governance) {
          this.distributedGovernance = { ...event.distributed_governance };
        }
        if (event.cognitive_diagnostics) {
          this.cognitiveDiagnostics = { ...event.cognitive_diagnostics };
        }
        this.setState('connected');
        if (this.lastSequence > 0) {
          this.requestSync(false);
        }
      }

      if (event.type === 'sync') {
        if (event.workflow_coordination) {
          this.workflowCoordination = { ...event.workflow_coordination };
        }
        if (event.distributed_governance) {
          this.distributedGovernance = { ...event.distributed_governance };
        }
        if (event.cognitive_diagnostics) {
          this.cognitiveDiagnostics = { ...event.cognitive_diagnostics };
        }
        this.applyReplayEvents(event);
      }

      if (event.type === 'workflow_timeline' && event.chain_id) {
        this.workflowTimelines.set(event.chain_id, {
          timeline: event.timeline || {},
          updatedAt: event.timestamp || new Date().toISOString(),
        });
        if (this.workflowTimelines.size > 50) {
          const keys = Array.from(this.workflowTimelines.keys());
          for (let i = 0; i < keys.length - 30; i += 1) {
            this.workflowTimelines.delete(keys[i]);
          }
        }
      }

      if (event.type === 'error') {
        this.degradedReasons = Array.isArray(event.degraded_reasons) ? event.degraded_reasons.slice(0, 12) : [];
        if (event.code === 'sync_out_of_order') {
          this.scheduleHydrationRetry();
        }
      }

      if (event.type === 'event' && event.event_type && event.event_type.startsWith('workflow_')) {
        const chainId = String((event.payload as Record<string, unknown> | undefined)?.chain_id || 'unknown_chain');
        const current = this.workflowTimelines.get(chainId) || {};
        this.workflowTimelines.set(chainId, {
          ...current,
          lastEventType: event.event_type,
          lastEventAt: event.timestamp,
          lastEventPayload: event.payload || {},
        });
      }

      // Emit to listeners
      if (this.shouldEmitEvent(event)) {
        this.eventListeners.forEach(listener => listener(event));
      }

      // Handle ride updates
      if (event.type === 'event' && event.payload) {
        this.handleRideEvent(event.payload as RideUpdateEvent);
      }

      // Handle pong
      if (event.type === 'pong') {
        // Heartbeat response received
        this.lastPongAt = Date.now();
      }
    } catch (error) {
      console.error('[Dispatcher WebSocket] Failed to parse message:', error);
      this.scheduleHydrationRetry();
    }
  }

  private shouldEmitEvent(event: WebSocketEvent): boolean {
    if (event.type !== 'event') {
      return true;
    }

    const sequence = Number(event.sequence || 0);
    if (sequence > 0 && sequence <= this.lastSequence) {
      return false;
    }

    const eventId = String(event.event_id || '');
    if (eventId) {
      if (this.seenEventIds.has(eventId)) {
        return false;
      }
      this.seenEventIds.add(eventId);
      if (this.seenEventIds.size > this.maxSeenEventIds) {
        const trimmed = Array.from(this.seenEventIds).slice(this.seenEventIds.size - 3000);
        this.seenEventIds = new Set(trimmed);
      }
    }

    if (sequence > 0) {
      this.lastSequence = sequence;
      this.persistContinuityState();
    }
    this.degradedReasons = [];
    return true;
  }

  private applyReplayEvents(event: WebSocketEvent): void {
    const rows = Array.isArray(event.events) ? event.events : [];
    if (rows.length === 0) {
      return;
    }

    const ordered = rows
      .map((row) => ({
        sequence: Number((row as Record<string, unknown>).sequence || 0),
        event_id: String((row as Record<string, unknown>).event_id || ''),
        event_type: String((row as Record<string, unknown>).event_type || ''),
        payload: ((row as Record<string, unknown>).payload || {}) as Record<string, unknown>,
        timestamp: String((row as Record<string, unknown>).timestamp || new Date().toISOString()),
      }))
      .sort((a, b) => a.sequence - b.sequence);

    for (let i = 0; i < ordered.length; i += 1) {
      const row = ordered[i];
      const syntheticEvent: WebSocketEvent = {
        type: 'event',
        event_type: row.event_type,
        event_id: row.event_id,
        sequence: row.sequence,
        payload: row.payload,
        timestamp: row.timestamp,
      };
      if (this.shouldEmitEvent(syntheticEvent)) {
        this.eventListeners.forEach((listener) => listener(syntheticEvent));
        if (syntheticEvent.payload) {
          this.handleRideEvent(syntheticEvent.payload as RideUpdateEvent);
        }
      }
    }

    this.replayCount += rows.length;
    this.recoveryAttempts += 1;
    this.persistContinuityState();
  }

  private handleRideEvent(eventData: RideUpdateEvent): void {
    // Construct ride update from event data
    const ride: DispatcherRide = {
      id: eventData.ride_id,
      passenger_name: '',
      pickup_address: '',
      dropoff_address: '',
      status: (eventData.to_status || 'pending') as any,
      driver_id: eventData.driver_id,
      driver_name: eventData.driver_name,
      is_emergency: false,
      requested_at: new Date().toISOString(),
    };

    this.rideUpdateListeners.forEach(listener => listener(ride));
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatInterval = window.setInterval(() => {
      if (this.isConnected()) {
        this.send(JSON.stringify({ type: 'ping' }));
      }
    }, 30000); // Every 30 seconds
  }

  private stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = undefined;
    }
  }

  private flushMessageQueue(): void {
    while (this.messageQueue.length > 0) {
      const message = this.messageQueue.shift();
      if (message) {
        this.send(message);
      }
    }
  }

  private removeEventListener(listener: (event: WebSocketEvent) => void): void {
    this.eventListeners.delete(listener);
  }

  private startStaleSocketGuard(): void {
    this.stopStaleSocketGuard();
    this.staleSocketGuard = window.setInterval(() => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        return;
      }
      if (Date.now() - this.lastPongAt > this.staleTimeoutMs) {
        try {
          this.ws.close();
        } catch {
          // noop
        }
      }
    }, 10000);
  }

  private stopStaleSocketGuard(): void {
    if (this.staleSocketGuard) {
      clearInterval(this.staleSocketGuard);
      this.staleSocketGuard = undefined;
    }
  }

  private attemptReconnect(): void {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      return;
    }

    if (this.retryCount < this.maxRetries) {
      this.retryCount++;
      const expDelay = Math.min(this.retryDelay * (2 ** (this.retryCount - 1)), this.maxRetryDelay);
      const jitter = Math.floor(Math.random() * 250);
      const delay = expDelay + jitter;
      console.log(`[Dispatcher WebSocket] Attempting reconnect (${this.retryCount}/${this.maxRetries}) in ${delay}ms`);

      this.reconnectTimer = window.setTimeout(() => {
        this.reconnectTimer = undefined;
        this.connect().catch(error => {
          console.error('[Dispatcher WebSocket] Reconnect failed:', error);
          this.scheduleHydrationRetry();
        });
      }, delay);
    }
  }

  private requestSync(force: boolean): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return;
    }
    if (!force && this.lastSequence <= 0) {
      return;
    }
    this.send(JSON.stringify({ type: 'sync', last_sequence: this.lastSequence }));
  }

  private requestWorkflowTimeline(chainId: string): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return;
    }
    this.send(JSON.stringify({ type: 'workflow_timeline', chain_id: chainId }));
  }

  private scheduleHydrationRetry(): void {
    if (this.hydrationRetries >= 3) {
      return;
    }
    this.hydrationRetries += 1;
    this.stopHydrationRetry();
    const delay = Math.min(6000, 1000 * this.hydrationRetries);
    this.hydrationRetryTimer = window.setTimeout(() => {
      this.hydrationRetryTimer = undefined;
      this.requestSync(true);
    }, delay);
  }

  private stopHydrationRetry(): void {
    if (this.hydrationRetryTimer) {
      clearTimeout(this.hydrationRetryTimer);
      this.hydrationRetryTimer = undefined;
    }
  }

  private persistContinuityState(): void {
    try {
      const persistenceKey = `amicor:dispatcher-ws:${this.organizationId}:${this.userId}`;
      window.sessionStorage.setItem(
        persistenceKey,
        JSON.stringify({
          lastSequence: this.lastSequence,
          seenEventIds: Array.from(this.seenEventIds).slice(-400),
          subscribedTypes: Array.from(this.subscribedTypes.values()),
          workflowCoordination: this.workflowCoordination,
            distributedGovernance: this.distributedGovernance,
            cognitiveDiagnostics: this.cognitiveDiagnostics,
          workflowTimelines: Array.from(this.workflowTimelines.entries()).slice(-20),
        }),
      );
    } catch {
      // Best-effort persistence only.
    }
  }

  private restoreContinuityState(): void {
    try {
      const persistenceKey = `amicor:dispatcher-ws:${this.organizationId}:${this.userId}`;
      const raw = window.sessionStorage.getItem(persistenceKey);
      if (!raw) {
        return;
      }
      const parsed = JSON.parse(raw) as {
        lastSequence?: number;
        seenEventIds?: string[];
        subscribedTypes?: string[];
        workflowCoordination?: Record<string, unknown>;
        distributedGovernance?: Record<string, unknown>;
        cognitiveDiagnostics?: Record<string, unknown>;
        workflowTimelines?: Array<[string, Record<string, unknown>]>;
      };
      this.lastSequence = Number(parsed.lastSequence || 0);
      this.seenEventIds = new Set(Array.isArray(parsed.seenEventIds) ? parsed.seenEventIds.slice(-400) : []);
      this.subscribedTypes = new Set(
        (Array.isArray(parsed.subscribedTypes) ? parsed.subscribedTypes : [])
          .filter((item) => item === 'dispatcher_board') as Array<'dispatcher_board'>,
      );
      this.workflowCoordination = parsed.workflowCoordination && typeof parsed.workflowCoordination === 'object'
        ? parsed.workflowCoordination
        : {};
      this.distributedGovernance = parsed.distributedGovernance && typeof parsed.distributedGovernance === 'object'
        ? parsed.distributedGovernance
        : {};
      this.cognitiveDiagnostics = parsed.cognitiveDiagnostics && typeof parsed.cognitiveDiagnostics === 'object'
        ? parsed.cognitiveDiagnostics
        : {};
      this.workflowTimelines = new Map(
        Array.isArray(parsed.workflowTimelines)
          ? parsed.workflowTimelines.filter((row) => Array.isArray(row) && typeof row[0] === 'string')
          : [],
      );

      const activeChains = Array.isArray((this.workflowCoordination as Record<string, unknown>).active_chains)
        ? ((this.workflowCoordination as Record<string, unknown>).active_chains as Array<Record<string, unknown>>)
        : [];
      for (let i = 0; i < activeChains.length; i += 1) {
        const chainId = String(activeChains[i]?.chain_id || '').trim();
        if (chainId) {
          this.requestWorkflowTimeline(chainId);
        }
      }
    } catch {
      // Ignore corrupted continuity snapshots.
    }
  }
}

export function createDispatcherWebSocketManager(
  organizationId: string,
  userId: string,
  token: string,
  role?: string,
): WebSocketManager {
  return new DispatcherWebSocketManager(organizationId, userId, token, role);
}
