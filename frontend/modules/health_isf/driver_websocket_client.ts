/**
 * Driver websocket client for reconnect-safe operational continuity.
 */

import type { DriverClientRole } from './driver_app_contracts';

export type DriverWebSocketState = 'disconnected' | 'connecting' | 'connected' | 'subscribed' | 'error';

export interface DriverWebSocketEvent {
  type: string;
  event_type?: string;
  event_id?: string;
  sequence?: number;
  payload?: Record<string, unknown>;
  events?: Array<Record<string, unknown>>;
  timestamp?: string;
  detail?: string;
  subscription_type?: string;
  connection_id?: string;
}

export interface DriverWebSocketClient {
  state: DriverWebSocketState;
  connect(): Promise<void>;
  disconnect(): void;
  subscribe(subscriptionType: 'driver_dashboard' | 'ride_updates' | 'incident_updates'): Promise<void>;
  onEvent(callback: (event: DriverWebSocketEvent) => void): () => void;
  onStateChange(callback: (state: DriverWebSocketState) => void): () => void;
  reconnect(): Promise<void>;
  isConnected(): boolean;
}

class DriverWebSocketClientImpl implements DriverWebSocketClient {
  state: DriverWebSocketState = 'disconnected';

  private ws?: WebSocket;
  private token: string;
  private organizationId: string;
  private userId: string;
  private role: DriverClientRole;
  private listeners: Set<(event: DriverWebSocketEvent) => void> = new Set();
  private stateListeners: Set<(state: DriverWebSocketState) => void> = new Set();
  private heartbeatTimer?: number;
  private reconnectAttempts = 0;
  private readonly maxReconnectAttempts = 5;
  private shouldReconnect = true;
  private lastSequence = 0;
  private replayCount = 0;
  private reconnectCount = 0;
  private seenEventIds: Set<string> = new Set();
  private subscribedTypes: Set<'driver_dashboard' | 'ride_updates' | 'incident_updates'> = new Set();
  private clientSessionId = `driver-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

  constructor(organizationId: string, userId: string, token: string, role: DriverClientRole) {
    this.organizationId = organizationId;
    this.userId = userId;
    this.token = token;
    this.role = role;
  }

  async connect(): Promise<void> {
    if (this.state === 'connecting' || this.state === 'connected' || this.state === 'subscribed') {
      return;
    }

    this.setState('connecting');

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const restoreSubs = Array.from(this.subscribedTypes.values()).join(',');
    const url = `${protocol}//${window.location.host}/api/health-isf/ws/live/${encodeURIComponent(this.organizationId)}/${encodeURIComponent(this.userId)}?role=${encodeURIComponent(this.role)}&token=${encodeURIComponent(this.token)}&last_sequence=${encodeURIComponent(String(this.lastSequence || 0))}&restore_subscriptions=${encodeURIComponent(restoreSubs)}&client_session_id=${encodeURIComponent(this.clientSessionId)}`;

    await new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(() => {
        reject(new Error('Driver websocket connection timeout'));
      }, 8000);

      this.ws = new WebSocket(url);

      this.ws.onopen = () => {
        window.clearTimeout(timeout);
        if (this.reconnectAttempts > 0) {
          this.reconnectCount += 1;
        }
        this.reconnectAttempts = 0;
        this.setState('connected');
        this.startHeartbeat();
        if (this.lastSequence > 0) {
          this.requestSync();
        }
        resolve();
      };

      this.ws.onmessage = (evt: MessageEvent<string>) => {
        let eventPayload: DriverWebSocketEvent;
        try {
          eventPayload = JSON.parse(evt.data) as DriverWebSocketEvent;
        } catch {
          eventPayload = { type: 'error', detail: 'Malformed websocket payload' };
        }

        if (eventPayload.type === 'connected') {
          this.setState('connected');
        }
        if (eventPayload.type === 'subscribed') {
          this.setState('subscribed');
        }

        if (eventPayload.type === 'sync' && Array.isArray(eventPayload.events)) {
          const ordered = eventPayload.events
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
            const synthetic: DriverWebSocketEvent = {
              type: 'event',
              event_type: row.event_type,
              event_id: row.event_id,
              sequence: row.sequence,
              payload: row.payload,
              timestamp: row.timestamp,
            };
            if (this.shouldEmitEvent(synthetic)) {
              this.listeners.forEach((listener) => listener(synthetic));
            }
          }
          this.replayCount += ordered.length;
          return;
        }

        if (!this.shouldEmitEvent(eventPayload)) {
          return;
        }

        this.listeners.forEach((listener) => listener(eventPayload));
      };

      this.ws.onerror = () => {
        window.clearTimeout(timeout);
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
    this.stopHeartbeat();
    if (this.ws) {
      this.ws.close();
      this.ws = undefined;
    }
    this.setState('disconnected');
  }

  async subscribe(subscriptionType: 'driver_dashboard' | 'ride_updates' | 'incident_updates'): Promise<void> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('Websocket not connected');
    }

    const payload = JSON.stringify({
      type: 'subscribe',
      subscription_type: subscriptionType,
    });

    this.ws.send(payload);
    this.subscribedTypes.add(subscriptionType);
  }

  onEvent(callback: (event: DriverWebSocketEvent) => void): () => void {
    this.listeners.add(callback);
    return () => this.listeners.delete(callback);
  }

  onStateChange(callback: (state: DriverWebSocketState) => void): () => void {
    this.stateListeners.add(callback);
    return () => this.stateListeners.delete(callback);
  }

  async reconnect(): Promise<void> {
    this.shouldReconnect = true;
    this.disconnect();
    this.shouldReconnect = true;
    await this.connect();
  }

  isConnected(): boolean {
    return this.state === 'connected' || this.state === 'subscribed';
  }

  private setState(next: DriverWebSocketState): void {
    if (this.state === next) {
      return;
    }
    this.state = next;
    this.stateListeners.forEach((listener) => listener(next));
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = window.setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, 30000);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      window.clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = undefined;
    }
  }

  private scheduleReconnect(): void {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      return;
    }
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      this.setState('error');
      return;
    }

    this.reconnectAttempts += 1;
    const delay = Math.min(10000, 1000 * this.reconnectAttempts);
    window.setTimeout(() => {
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

  private shouldEmitEvent(event: DriverWebSocketEvent): boolean {
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

export function createDriverWebSocketClient(
  organizationId: string,
  userId: string,
  token: string,
): DriverWebSocketClient {
  return new DriverWebSocketClientImpl(organizationId, userId, token, 'driver');
}
