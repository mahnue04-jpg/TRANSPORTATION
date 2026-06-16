/**
 * React Hooks for Dispatcher Operations
 * Custom hooks for state management and data fetching
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import {
  DispatcherRide,
  DispatcherDriver,
  DispatcherVehicle,
  DispatcherBoardState,
  DispatcherActivityLog,
  DispatchActiveOffer,
  DispatchLifecycleAuditRow,
  DispatcherFilters,
  RideStatus,
  RecurringSchedule,
  CreateRecurringScheduleRequest,
  AssignDriverRequest,
  ReassignDriverRequest,
  EscalateIssueRequest,
} from './dispatcherTypes';
import { createDispatcherWebSocketManager, WebSocketManager, WebSocketConnectionState } from './webSocketManager';

const API_BASE = '/api/health-isf';

type DispatcherErrorCode = 'auth' | 'offline' | 'network' | 'http' | 'unknown';

interface DispatcherRequestError {
  message: string;
  code: DispatcherErrorCode;
  retryable: boolean;
  status?: number;
}

function isOffline(): boolean {
  return typeof navigator !== 'undefined' && navigator.onLine === false;
}

async function buildRequestError(response: Response): Promise<DispatcherRequestError> {
  let detail = response.statusText || 'Request failed';
  try {
    const payload = await response.json();
    detail = payload?.detail || payload?.message || detail;
  } catch {
    // Ignore body parsing failures and fall back to status text.
  }

  if (response.status === 401 || response.status === 403) {
    return {
      message: 'Authentication expired or access denied. Sign in again to continue live operations.',
      code: 'auth',
      retryable: false,
      status: response.status,
    };
  }

  return {
    message: detail,
    code: 'http',
    retryable: response.status >= 500 || response.status === 429,
    status: response.status,
  };
}

function normalizeUnknownError(error: unknown, fallbackMessage: string): DispatcherRequestError {
  if (isOffline()) {
    return {
      message: 'You are offline. Live dispatcher updates will resume when connectivity returns.',
      code: 'offline',
      retryable: true,
    };
  }

  if (error instanceof Error) {
    return {
      message: error.message || fallbackMessage,
      code: 'network',
      retryable: true,
    };
  }

  return {
    message: fallbackMessage,
    code: 'unknown',
    retryable: true,
  };
}

function getAccessToken(): string | null {
  try {
    const sessionToken = localStorage.getItem('amicore:accessToken');
    if (sessionToken) {
      return sessionToken;
    }

    const identityRaw = localStorage.getItem('amicor_identity');
    if (identityRaw) {
      const identity = JSON.parse(identityRaw);
      if (identity && typeof identity.accessToken === 'string' && identity.accessToken) {
        return identity.accessToken;
      }
      if (identity && typeof identity.access_token === 'string' && identity.access_token) {
        return identity.access_token;
      }
    }

    const legacyToken = localStorage.getItem('auth_token');
    return legacyToken || null;
  } catch {
    return localStorage.getItem('auth_token');
  }
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (isOffline()) {
    throw {
      message: 'You are offline. Live dispatcher updates will resume when connectivity returns.',
      code: 'offline',
      retryable: true,
    } satisfies DispatcherRequestError;
  }

  const headers = new Headers(init.headers || {});
  const token = getAccessToken();
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await globalThis.fetch(path, {
    ...init,
    headers,
  });

  if (!response.ok) {
    throw await buildRequestError(response);
  }

  return response.json() as Promise<T>;
}

// Hook: Fetch dispatcher board state
export function useDispatcherBoard(organizationId?: string) {
  const [state, setState] = useState<DispatcherBoardState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<DispatcherErrorCode | null>(null);
  const [authExpired, setAuthExpired] = useState(false);
  const [offline, setOffline] = useState(isOffline());

  const loadBoard = useCallback(async () => {
    if (!organizationId) return;

    try {
      setLoading(true);
      setOffline(isOffline());
      const data = await requestJson<DispatcherBoardState>(`${API_BASE}/dispatcher/board`);
      setState(data);
      setError(null);
      setErrorCode(null);
      setAuthExpired(false);
    } catch (err) {
      const normalized = (err as DispatcherRequestError)?.message ? err as DispatcherRequestError : normalizeUnknownError(err, 'Failed to fetch dispatcher board');
      setError(normalized.message);
      setErrorCode(normalized.code);
      setAuthExpired(normalized.code === 'auth');
      setOffline(normalized.code === 'offline' || isOffline());
    } finally {
      setLoading(false);
    }
  }, [organizationId]);

  useEffect(() => {
    loadBoard();
    const interval = setInterval(loadBoard, 5000);
    return () => clearInterval(interval);
  }, [loadBoard]);

  useEffect(() => {
    const handleOnline = () => {
      setOffline(false);
      loadBoard();
    };
    const handleOffline = () => setOffline(true);

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, [loadBoard]);

  return { state, loading, error, errorCode, authExpired, offline, refetch: loadBoard };
}

// Hook: Fetch dispatcher queues
export function useDispatcherQueues(organizationId?: string, filters?: DispatcherFilters) {
  const [queues, setQueues] = useState<Record<string, DispatcherRide[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadQueues = useCallback(async () => {
    if (!organizationId) return;

    try {
      setLoading(true);
      const queryParams = new URLSearchParams();

      if (filters?.status) {
        filters.status.forEach(s => queryParams.append('status', s));
      }
      if (filters?.provider_id) {
        queryParams.append('provider_id', filters.provider_id);
      }
      if (filters?.search_query) {
        queryParams.append('search_query', filters.search_query);
      }

      const data = await requestJson<Record<string, DispatcherRide[]>>(`${API_BASE}/dispatcher/queues?${queryParams}`);
      setQueues(data);
      setError(null);
    } catch (err) {
      const normalized = (err as DispatcherRequestError)?.message ? err as DispatcherRequestError : normalizeUnknownError(err, 'Failed to fetch dispatcher queues');
      setError(normalized.message);
    } finally {
      setLoading(false);
    }
  }, [organizationId, filters]);

  useEffect(() => {
    loadQueues();
  }, [loadQueues]);

  return { queues, loading, error, refetch: loadQueues };
}

// Hook: Fetch audit log
export function useAuditLog(organizationId?: string, rideId?: string) {
  const [activities, setActivities] = useState<DispatcherActivityLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAuditLog = useCallback(async () => {
    if (!organizationId) return;

    try {
      setLoading(true);
      const queryParams = new URLSearchParams();
      if (rideId) {
        queryParams.append('ride_id', rideId);
      }

      const data = await requestJson<{ data?: DispatcherActivityLog[] }>(`${API_BASE}/dispatcher/audit-log?${queryParams}`);
      setActivities(Array.isArray(data.data) ? data.data : []);
      setError(null);
    } catch (err) {
      const normalized = (err as DispatcherRequestError)?.message ? err as DispatcherRequestError : normalizeUnknownError(err, 'Failed to fetch audit log');
      setError(normalized.message);
    } finally {
      setLoading(false);
    }
  }, [organizationId, rideId]);

  useEffect(() => {
    loadAuditLog();
  }, [loadAuditLog]);

  return { activities, loading, error, refetch: loadAuditLog };
}

export function useDispatchActiveOffers(organizationId?: string) {
  const [offers, setOffers] = useState<DispatchActiveOffer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadOffers = useCallback(async () => {
    if (!organizationId) return;
    try {
      setLoading(true);
      const data = await requestJson<DispatchActiveOffer[]>(`${API_BASE}/dispatch/active-assignments`);
      setOffers(Array.isArray(data) ? data : []);
      setError(null);
    } catch (err) {
      const normalized = (err as DispatcherRequestError)?.message ? err as DispatcherRequestError : normalizeUnknownError(err, 'Failed to fetch active offers');
      setError(normalized.message);
    } finally {
      setLoading(false);
    }
  }, [organizationId]);

  useEffect(() => {
    loadOffers();
    const interval = setInterval(loadOffers, 5000);
    return () => clearInterval(interval);
  }, [loadOffers]);

  return { offers, loading, error, refetch: loadOffers };
}

export function useDispatchLifecycleAudit(rideId?: string) {
  const [rows, setRows] = useState<DispatchLifecycleAuditRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAudit = useCallback(async () => {
    if (!rideId) {
      setRows([]);
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      const data = await requestJson<DispatchLifecycleAuditRow[]>(`${API_BASE}/rides/${rideId}/dispatch-history`);
      setRows(Array.isArray(data) ? data : []);
      setError(null);
    } catch (err) {
      const normalized = (err as DispatcherRequestError)?.message ? err as DispatcherRequestError : normalizeUnknownError(err, 'Failed to fetch lifecycle audit');
      setError(normalized.message);
    } finally {
      setLoading(false);
    }
  }, [rideId]);

  useEffect(() => {
    loadAudit();
  }, [loadAudit]);

  return { rows, loading, error, refetch: loadAudit };
}

export function useActiveVehicles(organizationId?: string) {
  const [vehicles, setVehicles] = useState<DispatcherVehicle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadVehicles = useCallback(async () => {
    if (!organizationId) return;

    try {
      setLoading(true);
      const data = await requestJson<DispatcherVehicle[]>(`${API_BASE}/vehicles/active`);
      setVehicles(Array.isArray(data) ? data : []);
      setError(null);
    } catch (err) {
      const normalized = (err as DispatcherRequestError)?.message ? err as DispatcherRequestError : normalizeUnknownError(err, 'Failed to fetch active vehicles');
      setError(normalized.message);
    } finally {
      setLoading(false);
    }
  }, [organizationId]);

  useEffect(() => {
    loadVehicles();
  }, [loadVehicles]);

  return { vehicles, loading, error, refetch: loadVehicles };
}

export function useRecurringSchedules(organizationId?: string) {
  const [schedules, setSchedules] = useState<RecurringSchedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadSchedules = useCallback(async () => {
    if (!organizationId) return;
    try {
      setLoading(true);
      const data = await requestJson<RecurringSchedule[]>(`${API_BASE}/recurring/schedules`);
      setSchedules(Array.isArray(data) ? data : []);
      setError(null);
    } catch (err) {
      const normalized = (err as DispatcherRequestError)?.message ? err as DispatcherRequestError : normalizeUnknownError(err, 'Failed to fetch recurring schedules');
      setError(normalized.message);
    } finally {
      setLoading(false);
    }
  }, [organizationId]);

  useEffect(() => {
    loadSchedules();
  }, [loadSchedules]);

  return { schedules, loading, error, refetch: loadSchedules };
}

export function useRecurringScheduleRides(scheduleId?: string) {
  const [rides, setRides] = useState<DispatcherRide[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadGeneratedRides = useCallback(async () => {
    if (!scheduleId) {
      setRides([]);
      return;
    }
    try {
      setLoading(true);
      const data = await requestJson<DispatcherRide[]>(`${API_BASE}/recurring/schedules/${scheduleId}/rides`);
      setRides(Array.isArray(data) ? data : []);
      setError(null);
    } catch (err) {
      const normalized = (err as DispatcherRequestError)?.message ? err as DispatcherRequestError : normalizeUnknownError(err, 'Failed to fetch generated rides');
      setError(normalized.message);
    } finally {
      setLoading(false);
    }
  }, [scheduleId]);

  useEffect(() => {
    loadGeneratedRides();
  }, [loadGeneratedRides]);

  return { rides, loading, error, refetch: loadGeneratedRides };
}

// Hook: Perform dispatcher action
export function useDispatcherAction() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<DispatcherErrorCode | null>(null);
  const [authExpired, setAuthExpired] = useState(false);

  const reassignDriver = useCallback(async (rideId: string, request: ReassignDriverRequest) => {
    try {
      setLoading(true);
      const payload = await requestJson(`${API_BASE}/dispatcher/rides/${rideId}/reassign-driver`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(request),
      });
      setError(null);
      setErrorCode(null);
      setAuthExpired(false);
      return payload;
    } catch (err) {
      const normalized = (err as DispatcherRequestError)?.message ? err as DispatcherRequestError : normalizeUnknownError(err, 'Failed to reassign driver');
      setError(normalized.message);
      setErrorCode(normalized.code);
      setAuthExpired(normalized.code === 'auth');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const cancelRide = useCallback(async (rideId: string, reason: string) => {
    try {
      setLoading(true);
      const payload = await requestJson(`${API_BASE}/dispatcher/rides/${rideId}/cancel`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ reason }),
      });
      setError(null);
      setErrorCode(null);
      setAuthExpired(false);
      return payload;
    } catch (err) {
      const normalized = (err as DispatcherRequestError)?.message ? err as DispatcherRequestError : normalizeUnknownError(err, 'Failed to cancel ride');
      setError(normalized.message);
      setErrorCode(normalized.code);
      setAuthExpired(normalized.code === 'auth');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const escalateRide = useCallback(async (rideId: string, request: EscalateIssueRequest) => {
    try {
      setLoading(true);
      const payload = await requestJson(`${API_BASE}/dispatcher/rides/${rideId}/escalate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(request),
      });
      setError(null);
      setErrorCode(null);
      setAuthExpired(false);
      return payload;
    } catch (err) {
      const normalized = (err as DispatcherRequestError)?.message ? err as DispatcherRequestError : normalizeUnknownError(err, 'Failed to escalate ride');
      setError(normalized.message);
      setErrorCode(normalized.code);
      setAuthExpired(normalized.code === 'auth');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const retryRide = useCallback(async (rideId: string) => {
    try {
      setLoading(true);
      const payload = await requestJson(`${API_BASE}/dispatcher/rides/${rideId}/retry`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({}),
      });
      setError(null);
      setErrorCode(null);
      setAuthExpired(false);
      return payload;
    } catch (err) {
      const normalized = (err as DispatcherRequestError)?.message ? err as DispatcherRequestError : normalizeUnknownError(err, 'Failed to retry ride');
      setError(normalized.message);
      setErrorCode(normalized.code);
      setAuthExpired(normalized.code === 'auth');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const assignVehicle = useCallback(async (rideId: string, vehicleId: string) => {
    try {
      setLoading(true);
      const payload = await requestJson(`${API_BASE}/rides/${rideId}/assign-vehicle`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ vehicle_id: vehicleId }),
      });
      setError(null);
      setErrorCode(null);
      setAuthExpired(false);
      return payload;
    } catch (err) {
      const normalized = (err as DispatcherRequestError)?.message ? err as DispatcherRequestError : normalizeUnknownError(err, 'Failed to assign vehicle');
      setError(normalized.message);
      setErrorCode(normalized.code);
      setAuthExpired(normalized.code === 'auth');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const completeRide = useCallback(async (rideId: string) => {
    try {
      setLoading(true);
      const payload = await requestJson(`${API_BASE}/dispatcher/rides/${rideId}/complete`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      setError(null);
      setErrorCode(null);
      setAuthExpired(false);
      return payload;
    } catch (err) {
      const normalized = (err as DispatcherRequestError)?.message ? err as DispatcherRequestError : normalizeUnknownError(err, 'Failed to complete ride');
      setError(normalized.message);
      setErrorCode(normalized.code);
      setAuthExpired(normalized.code === 'auth');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const setRideStatus = useCallback(async (rideId: string, status: RideStatus) => {
    try {
      setLoading(true);
      const payload = await requestJson(`${API_BASE}/rides/${rideId}/status`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ status }),
      });
      setError(null);
      setErrorCode(null);
      setAuthExpired(false);
      return payload;
    } catch (err) {
      const normalized = (err as DispatcherRequestError)?.message ? err as DispatcherRequestError : normalizeUnknownError(err, 'Failed to update ride status');
      setError(normalized.message);
      setErrorCode(normalized.code);
      setAuthExpired(normalized.code === 'auth');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const createRecurringSchedule = useCallback(async (payload: CreateRecurringScheduleRequest) => {
    try {
      setLoading(true);
      const data = await requestJson<RecurringSchedule>(`${API_BASE}/recurring/schedules`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });
      setError(null);
      setErrorCode(null);
      setAuthExpired(false);
      return data;
    } catch (err) {
      const normalized = (err as DispatcherRequestError)?.message ? err as DispatcherRequestError : normalizeUnknownError(err, 'Failed to create recurring schedule');
      setError(normalized.message);
      setErrorCode(normalized.code);
      setAuthExpired(normalized.code === 'auth');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const pauseRecurringSchedule = useCallback(async (scheduleId: string) => {
    try {
      setLoading(true);
      const data = await requestJson<RecurringSchedule>(`${API_BASE}/recurring/schedules/${scheduleId}/pause`, {
        method: 'PATCH',
      });
      setError(null);
      setErrorCode(null);
      setAuthExpired(false);
      return data;
    } catch (err) {
      const normalized = (err as DispatcherRequestError)?.message ? err as DispatcherRequestError : normalizeUnknownError(err, 'Failed to pause recurring schedule');
      setError(normalized.message);
      setErrorCode(normalized.code);
      setAuthExpired(normalized.code === 'auth');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const resumeRecurringSchedule = useCallback(async (scheduleId: string, horizonDays = 30) => {
    try {
      setLoading(true);
      const data = await requestJson<RecurringSchedule>(`${API_BASE}/recurring/schedules/${scheduleId}/resume?horizon_days=${horizonDays}`, {
        method: 'PATCH',
      });
      setError(null);
      setErrorCode(null);
      setAuthExpired(false);
      return data;
    } catch (err) {
      const normalized = (err as DispatcherRequestError)?.message ? err as DispatcherRequestError : normalizeUnknownError(err, 'Failed to resume recurring schedule');
      setError(normalized.message);
      setErrorCode(normalized.code);
      setAuthExpired(normalized.code === 'auth');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return {
    loading,
    error,
    errorCode,
    authExpired,
    reassignDriver,
    assignVehicle,
    setRideStatus,
    createRecurringSchedule,
    pauseRecurringSchedule,
    resumeRecurringSchedule,
    completeRide,
    cancelRide,
    escalateRide,
    retryRide,
  };
}

// Hook: WebSocket connection for real-time updates
export function useDispatcherWebSocket(organizationId?: string, userId?: string) {
  const [wsManager, setWsManager] = useState<WebSocketManager | null>(null);
  const [connectionState, setConnectionState] = useState<WebSocketConnectionState>('disconnected');
  const [rides, setRides] = useState<DispatcherRide[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [offline, setOffline] = useState(isOffline());
  const [authExpired, setAuthExpired] = useState(false);
  const wsRef = useRef<WebSocketManager | null>(null);

  const retryConnect = useCallback(async () => {
    const manager = wsRef.current;
    if (!manager) return;

    try {
      setError(null);
      setOffline(isOffline());
      await manager.connect();
      await manager.subscribe('dispatcher_board');
    } catch (wsError) {
      const normalized = wsError instanceof Error ? wsError.message : 'Realtime connection failed';
      setError(normalized);
    }
  }, []);

  useEffect(() => {
    if (!organizationId || !userId) return;

    const token = getAccessToken();
    if (!token) {
      setAuthExpired(true);
      setError('Authentication token missing. Sign in again to restore realtime dispatch updates.');
      return;
    }

    const manager = createDispatcherWebSocketManager(organizationId, userId, token, 'dispatcher');
    wsRef.current = manager;
    setWsManager(manager);

    (async () => {
      try {
        await manager.connect();
        setConnectionState(manager.state);
        setError(null);
        setAuthExpired(false);

        manager.onStateChange(state => {
          setConnectionState(state);
          if (state === 'disconnected' && isOffline()) {
            setOffline(true);
          }
        });

        manager.onRideUpdate(ride => {
          setRides(prev => {
            const idx = prev.findIndex(r => r.id === ride.id);
            if (idx >= 0) {
              const updated = [...prev];
              updated[idx] = ride;
              return updated;
            }
            return [...prev, ride];
          });
        });

        manager.onEvent(event => {
          if (event.type === 'error') {
            setError(event.detail || 'Realtime dispatch update failed.');
            if ((event.detail || '').toLowerCase().includes('token')) {
              setAuthExpired(true);
            }
          }
        });

        await manager.subscribe('dispatcher_board');
      } catch (error) {
        const message = error instanceof Error ? error.message : 'WebSocket setup failed';
        setError(message);
        setAuthExpired(message.toLowerCase().includes('auth') || message.toLowerCase().includes('token'));
      }
    })();

    const handleOnline = () => {
      setOffline(false);
      retryConnect();
    };
    const handleOffline = () => {
      setOffline(true);
      setError('You are offline. The dashboard will keep polling when connectivity returns.');
    };

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
      if (wsRef.current) {
        wsRef.current.disconnect();
      }
    };
  }, [organizationId, userId, retryConnect]);

  return {
    wsManager,
    connectionState,
    isConnected: connectionState === 'connected' || connectionState === 'subscribed',
    rides,
    error,
    offline,
    authExpired,
    retryConnect,
  };
}
