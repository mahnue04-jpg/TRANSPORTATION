/**
 * Provider websocket client for operational synchronization.
 */

export type ProviderWebSocketState = 'disconnected' | 'connecting' | 'connected' | 'subscribed' | 'error';

export interface ProviderWebSocketClient {
  state: ProviderWebSocketState;
  connect(): Promise<void>;
  disconnect(): void;
  subscribe(subscriptionType: 'ride_updates' | 'incident_updates' | 'workflow_events'): Promise<void>;
  onEvent(callback: (event: Record<string, unknown>) => void): () => void;
  onStateChange(callback: (state: ProviderWebSocketState) => void): () => void;
}

class ProviderWebSocketClientImpl implements ProviderWebSocketClient {
  state: ProviderWebSocketState = 'disconnected';
  private ws?: WebSocket;
  private listeners: Set<(event: Record<string, unknown>) => void> = new Set();
  private stateListeners: Set<(state: ProviderWebSocketState) => void> = new Set();
  private reconnectAttempts = 0;
  private reconnectTimer?: number;
  private shouldReconnect = true;
  private heartbeatTimer?: number;
  private lastPongAt = 0;
  private lastSequence = 0;
  private replayCount = 0;
  private reconnectCount = 0;
  private seenEventIds: Set<string> = new Set();
  private subscribedTypes: Set<'ride_updates' | 'incident_updates' | 'workflow_events'> = new Set();
  private clientSessionId = `provider-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

  constructor(private organizationId: string, private userId: string, private token: string) {}

  async connect(): Promise<void> {
    if (this.state === 'connecting' || this.state === 'connected' || this.state === 'subscribed') {
      return;
    }
    this.setState('connecting');
    this.shouldReconnect = true;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const restoreSubs = Array.from(this.subscribedTypes.values()).join(',');
    const url = `${protocol}//${window.location.host}/api/health-isf/ws/live/${encodeURIComponent(this.organizationId)}/${encodeURIComponent(this.userId)}?role=provider&token=${encodeURIComponent(this.token)}&last_sequence=${encodeURIComponent(String(this.lastSequence || 0))}&restore_subscriptions=${encodeURIComponent(restoreSubs)}&client_session_id=${encodeURIComponent(this.clientSessionId)}`;

    await new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(() => reject(new Error('Provider websocket connection timeout')), 8000);
      this.ws = new WebSocket(url);
      this.ws.onopen = () => {
        if (this.reconnectAttempts > 0) {
          this.reconnectCount += 1;
        }
        this.reconnectAttempts = 0;
        this.lastPongAt = Date.now();
        this.startHeartbeat();
        window.clearTimeout(timeout);
        this.setState('connected');
        if (this.lastSequence > 0) {
          this.requestSync();
        }
        resolve();
      };
      this.ws.onmessage = (evt: MessageEvent<string>) => {
        let parsed: Record<string, unknown>;
        try {
          parsed = JSON.parse(evt.data) as Record<string, unknown>;
        } catch {
          parsed = { type: 'error', detail: 'Malformed websocket payload' };
        }
        if (parsed.type === 'subscribed') {
          this.setState('subscribed');
        }
        if (parsed.type === 'pong') {
          this.lastPongAt = Date.now();
        }

        if (parsed.type === 'sync' && Array.isArray(parsed.events)) {
          const ordered = (parsed.events as Array<Record<string, unknown>>)
            .map((row) => ({
              sequence: Number(row.sequence || 0),
              event_id: String(row.event_id || ''),
              event_type: String(row.event_type || ''),
              payload: (row.payload || {}) as Record<string, unknown>,
              timestamp: String(row.timestamp || new Date().toISOString()),
            }))
            .sort((a, b) => a.sequence - b.sequence);
          for (let i = 0; i < ordered.length; i += 1) {
            const row = ordered[i];
            const synthetic = {
              type: 'event',
              event_type: row.event_type,
              event_id: row.event_id,
              sequence: row.sequence,
              payload: row.payload,
              timestamp: row.timestamp,
            } as Record<string, unknown>;
            if (this.shouldEmitEvent(synthetic)) {
              this.listeners.forEach((listener) => listener(synthetic));
            }
          }
          this.replayCount += ordered.length;
          return;
        }

        if (this.shouldEmitEvent(parsed)) {
          this.listeners.forEach((listener) => listener(parsed));
        }
      };
      this.ws.onerror = () => {
        this.setState('error');
      };
      this.ws.onclose = () => {
        this.stopHeartbeat();
        this.setState('disconnected');
        if (this.shouldReconnect) {
          this.scheduleReconnect();
        }
      };
    });
  }

  disconnect(): void {
    this.shouldReconnect = false;
    if (this.reconnectTimer) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = undefined;
    }
    this.stopHeartbeat();
    if (this.ws) {
      this.ws.close();
      this.ws = undefined;
    }
    this.setState('disconnected');
  }

  async subscribe(subscriptionType: 'ride_updates' | 'incident_updates' | 'workflow_events'): Promise<void> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('Provider websocket not connected');
    }
    this.ws.send(JSON.stringify({ type: 'subscribe', subscription_type: subscriptionType }));
    this.subscribedTypes.add(subscriptionType);
  }

  onEvent(callback: (event: Record<string, unknown>) => void): () => void {
    this.listeners.add(callback);
    return () => this.listeners.delete(callback);
  }

  onStateChange(callback: (state: ProviderWebSocketState) => void): () => void {
    this.stateListeners.add(callback);
    return () => this.stateListeners.delete(callback);
  }

  private setState(next: ProviderWebSocketState): void {
    if (this.state === next) {
      return;
    }
    this.state = next;
    this.stateListeners.forEach((listener) => listener(next));
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = window.setInterval(() => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        return;
      }
      if (Date.now() - this.lastPongAt > 70000) {
        try {
          this.ws.close();
        } catch {
          // noop
        }
        return;
      }
      this.ws.send(JSON.stringify({ type: 'ping' }));
    }, 30000);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      window.clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = undefined;
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= 8) {
      return;
    }
    this.reconnectAttempts += 1;
    const baseDelay = Math.min(1000 * (2 ** (this.reconnectAttempts - 1)), 30000);
    const jitter = Math.floor(Math.random() * 250);
    const delay = baseDelay + jitter;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = undefined;
      this.connect().catch(() => {
        this.scheduleReconnect();
      });
    }, delay);
  }

  private requestSync(): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return;
    }
    this.ws.send(JSON.stringify({ type: 'sync', last_sequence: this.lastSequence }));
  }

  private shouldEmitEvent(event: Record<string, unknown>): boolean {
    if (String(event.type || '') !== 'event') {
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
      if (this.seenEventIds.size > 4000) {
        const trimmed = Array.from(this.seenEventIds).slice(this.seenEventIds.size - 2000);
        this.seenEventIds = new Set(trimmed);
      }
    }

    if (sequence > 0) {
      this.lastSequence = sequence;
    }

    return true;
  }
}

export function createProviderWebSocketClient(
  organizationId: string,
  userId: string,
  token: string,
): ProviderWebSocketClient {
  return new ProviderWebSocketClientImpl(organizationId, userId, token);
}
