/**
 * Dispatcher Command Center - Main component
 * Real-time enterprise dispatcher dashboard for healthcare transportation operations
 */

import React, { useState, useCallback, useEffect, useRef } from 'react';
import {
  DispatcherRide,
  DispatcherVehicle,
  DispatcherFilters,
  RideStatus,
  RecurringSchedule,
  CreateRecurringScheduleRequest,
} from './dispatcherTypes';
import {
  useDispatcherBoard,
  useDispatcherQueues,
  useAuditLog,
  useDispatchActiveOffers,
  useDispatchLifecycleAudit,
  useActiveVehicles,
  useRecurringSchedules,
  useRecurringScheduleRides,
  useDispatcherAction,
  useDispatcherWebSocket,
} from './dispatcherHooks';
import { DispatcherRideCard } from './components/DispatcherRideCard';
import { DispatcherFiltersBar } from './components/DispatcherFiltersBar';
import { DispatcherBoard } from './components/DispatcherBoard';
import { RideActionModal } from './components/RideActionModal';
import { AuditLogPanel } from './components/AuditLogPanel';
import './DispatcherCommandCenter.css';

interface DispatcherCommandCenterProps {
  organizationId: string;
  userId: string;
}

interface ToastNotice {
  id: string;
  tone: 'info' | 'success' | 'warning' | 'error';
  message: string;
}

export function DispatcherCommandCenter({
  organizationId,
  userId,
}: DispatcherCommandCenterProps) {
  // State
  const [filters, setFilters] = useState<DispatcherFilters>({});
  const [selectedRide, setSelectedRide] = useState<string | null>(null);
  const [selectedScheduleId, setSelectedScheduleId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'board' | 'audit'>('board');
  const [actionModal, setActionModal] = useState<{
    type: 'assign' | 'reassign' | 'cancel' | 'escalate' | null;
    rideId: string | null;
  }>({ type: null, rideId: null });
  const [toasts, setToasts] = useState<ToastNotice[]>([]);
  const lastToastRef = useRef<string | null>(null);

  // Data hooks
  const board = useDispatcherBoard(organizationId);
  const queues = useDispatcherQueues(organizationId, filters);
  const auditLog = useAuditLog(organizationId, selectedRide || undefined);
  const activeOffers = useDispatchActiveOffers(organizationId);
  const lifecycleAudit = useDispatchLifecycleAudit(selectedRide || undefined);
  const vehicles = useActiveVehicles(organizationId);
  const recurringSchedules = useRecurringSchedules(organizationId);
  const recurringScheduleRides = useRecurringScheduleRides(selectedScheduleId || undefined);
  const actions = useDispatcherAction();
  const wsConnection = useDispatcherWebSocket(organizationId, userId);

  const pushToast = useCallback((tone: ToastNotice['tone'], message: string) => {
    if (!message || lastToastRef.current === `${tone}:${message}`) {
      return;
    }

    lastToastRef.current = `${tone}:${message}`;
    const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setToasts(prev => [...prev, { id, tone, message }]);
    window.setTimeout(() => {
      setToasts(prev => prev.filter(item => item.id !== id));
      if (lastToastRef.current === `${tone}:${message}`) {
        lastToastRef.current = null;
      }
    }, 4000);
  }, []);

  // Merge WebSocket updates with API data
  const mergedRides = useCallback(() => {
    const boardRides = board.state?.active_rides || [];
    if (wsConnection.isConnected && wsConnection.rides.length > 0) {
      const byId = new Map<string, DispatcherRide>(boardRides.map((ride) => [ride.id, ride]));
      wsConnection.rides.forEach((ride) => {
        const existing = byId.get(ride.id);
        byId.set(ride.id, existing ? { ...existing, ...ride } : ride);
      });
      return Array.from(byId.values());
    }
    return boardRides;
  }, [board.state?.active_rides, wsConnection.rides, wsConnection.isConnected]);

  const vehicleLabelById = useCallback(() => {
    const map = new Map<string, string>();
    vehicles.vehicles.forEach((vehicle) => {
      map.set(vehicle.id, `${vehicle.vehicle_plate} · ${vehicle.vehicle_type}`);
    });
    return map;
  }, [vehicles.vehicles]);

  // Filter rides
  const filteredRides = useCallback(() => {
    const rides = mergedRides();
    return rides.filter(ride => {
      if (filters.status?.length && !filters.status.includes(ride.status)) {
        return false;
      }
      if (filters.provider_id && ride.provider_id !== filters.provider_id) {
        return false;
      }
      if (filters.search_query) {
        const query = filters.search_query.toLowerCase();
        return (
          ride.passenger_name.toLowerCase().includes(query) ||
          ride.pickup_address.toLowerCase().includes(query) ||
          ride.dropoff_address.toLowerCase().includes(query)
        );
      }
      return true;
    });
  }, [mergedRides, filters]);

  // Handle reassign action
  const handleReassign = useCallback(async (rideId: string, driverId: string) => {
    try {
      await actions.reassignDriver(rideId, { driver_id: driverId });
      pushToast('success', 'Driver assignment updated.');
      setActionModal({ type: null, rideId: null });
      board.refetch();
      auditLog.refetch();
    } catch (error) {
      pushToast('error', actions.error || 'Failed to reassign driver.');
    }
  }, [actions, auditLog, board, pushToast]);

  // Handle cancel action
  const handleCancel = useCallback(async (rideId: string, reason: string) => {
    try {
      await actions.cancelRide(rideId, reason);
      pushToast('success', 'Ride cancelled and dashboard refreshed.');
      setActionModal({ type: null, rideId: null });
      board.refetch();
      auditLog.refetch();
    } catch (error) {
      pushToast('error', actions.error || 'Failed to cancel ride.');
    }
  }, [actions, auditLog, board, pushToast]);

  // Handle escalate action
  const handleEscalate = useCallback(async (rideId: string, issueType: string, description: string) => {
    try {
      await actions.escalateRide(rideId, { issue_type: issueType, description });
      pushToast('success', 'Issue escalated for dispatcher review.');
      setActionModal({ type: null, rideId: null });
      board.refetch();
      auditLog.refetch();
    } catch (error) {
      pushToast('error', actions.error || 'Failed to escalate ride issue.');
    }
  }, [actions, auditLog, board, pushToast]);

  const handleAssignVehicle = useCallback(async (rideId: string, vehicleId: string) => {
    try {
      await actions.assignVehicle(rideId, vehicleId);
      pushToast('success', 'Vehicle assignment saved.');
      board.refetch();
      queues.refetch();
      auditLog.refetch();
      vehicles.refetch();
    } catch (error) {
      pushToast('error', actions.error || 'Failed to assign vehicle.');
    }
  }, [actions, auditLog, board, pushToast, queues, vehicles]);

  const handleSetRideStatus = useCallback(async (rideId: string, status: RideStatus) => {
    try {
      await actions.setRideStatus(rideId, status);
      pushToast('success', `Ride status updated to ${status}.`);
      board.refetch();
      queues.refetch();
      auditLog.refetch();
    } catch (error) {
      pushToast('error', actions.error || 'Failed to update ride status.');
    }
  }, [actions, auditLog, board, pushToast, queues]);

  const handleCompleteRide = useCallback(async (rideId: string) => {
    try {
      await actions.completeRide(rideId);
      pushToast('success', 'Ride marked completed and persisted.');
      board.refetch();
      queues.refetch();
      auditLog.refetch();
    } catch (error) {
      pushToast('error', actions.error || 'Failed to complete ride.');
    }
  }, [actions, auditLog, board, pushToast, queues]);

  const handleCreateRecurringSchedule = useCallback(async (payload: CreateRecurringScheduleRequest) => {
    try {
      const created = await actions.createRecurringSchedule(payload);
      pushToast('success', 'Recurring schedule created. Future rides generated.');
      recurringSchedules.refetch();
      board.refetch();
      queues.refetch();
      if (created?.id) {
        setSelectedScheduleId(created.id);
      }
    } catch (error) {
      pushToast('error', actions.error || 'Failed to create recurring schedule.');
    }
  }, [actions, board, pushToast, queues, recurringSchedules]);

  const handlePauseSchedule = useCallback(async (scheduleId: string) => {
    try {
      await actions.pauseRecurringSchedule(scheduleId);
      pushToast('success', 'Recurring schedule paused.');
      recurringSchedules.refetch();
    } catch (error) {
      pushToast('error', actions.error || 'Failed to pause schedule.');
    }
  }, [actions, pushToast, recurringSchedules]);

  const handleResumeSchedule = useCallback(async (scheduleId: string) => {
    try {
      await actions.resumeRecurringSchedule(scheduleId, 30);
      pushToast('success', 'Recurring schedule resumed.');
      recurringSchedules.refetch();
      board.refetch();
      queues.refetch();
      if (selectedScheduleId === scheduleId) {
        recurringScheduleRides.refetch();
      }
    } catch (error) {
      pushToast('error', actions.error || 'Failed to resume schedule.');
    }
  }, [actions, board, pushToast, queues, recurringScheduleRides, recurringSchedules, selectedScheduleId]);

  useEffect(() => {
    if (board.error) {
      pushToast(board.authExpired ? 'warning' : 'error', board.error);
    }
  }, [board.authExpired, board.error, pushToast]);

  useEffect(() => {
    if (wsConnection.error) {
      pushToast(wsConnection.authExpired ? 'warning' : 'error', wsConnection.error);
    }
  }, [pushToast, wsConnection.authExpired, wsConnection.error]);

  useEffect(() => {
    if (wsConnection.offline || board.offline) {
      pushToast('warning', 'Offline mode active. The dispatcher board will retry automatically when connectivity returns.');
    }
  }, [board.offline, pushToast, wsConnection.offline]);

  const statusLabel = wsConnection.authExpired
    ? 'Authentication required for realtime sync'
    : wsConnection.offline
      ? 'Offline mode'
      : wsConnection.isConnected
        ? 'Connected (Real-Time)'
        : `Realtime reconnecting (${wsConnection.connectionState})`;

  // Get selected ride details
  const selectedRideData = selectedRide ? mergedRides().find(r => r.id === selectedRide) : null;
  const vehicleLabels = vehicleLabelById();

  return (
    <div className="dispatcher-command-center">
      <div className="dispatcher-toast-stack" aria-live="polite">
        {toasts.map(toast => (
          <div key={toast.id} className={`dispatcher-toast ${toast.tone}`}>
            {toast.message}
          </div>
        ))}
      </div>

      {/* Connection Status */}
      <div className={`connection-status ${wsConnection.connectionState}`}>
        <span className="status-dot"></span>
        <span className="status-text">
          {statusLabel}
        </span>
      </div>

      {(board.authExpired || actions.authExpired || wsConnection.authExpired || board.offline || wsConnection.offline || board.error) && (
        <div className="dispatcher-operational-banner">
          <div>
            <strong>Operational attention required.</strong>
            <span>
              {board.authExpired || actions.authExpired || wsConnection.authExpired
                ? ' Session access expired. Sign in again to restore live dispatch actions.'
                : board.offline || wsConnection.offline
                  ? ' Network connectivity is unavailable. The dashboard is running in degraded mode.'
                  : ` ${board.error}`}
            </span>
          </div>
          <div className="banner-actions">
            <button onClick={() => board.refetch()}>Retry dashboard</button>
            <button onClick={() => wsConnection.retryConnect()}>Retry realtime</button>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="command-center-header">
        <div className="header-title">
          <h1>🚗 Enterprise Dispatcher Command Center</h1>
          <p>Real-time healthcare transportation operations</p>
        </div>

        {/* Key Metrics */}
        {board.state && (
          <div className="metrics-bar">
            <div className="metric active-rides">
              <span className="value">{board.state.active_rides.length}</span>
              <span className="label">Active Rides</span>
            </div>
            <div className="metric pending-rides">
              <span className="value">{board.state.pending_rides.length}</span>
              <span className="label">Pending</span>
            </div>
            <div className="metric available-drivers">
              <span className="value">{board.state.available_drivers.length}</span>
              <span className="label">Drivers Available</span>
            </div>
            <div className={`metric dispatch-load ${board.state.dispatch_load > 80 ? 'critical' : board.state.dispatch_load > 60 ? 'warning' : ''}`}>
              <span className="value">{Math.round(board.state.dispatch_load)}%</span>
              <span className="label">Dispatch Load</span>
            </div>
          </div>
        )}
      </div>

      {/* Filters */}
      <DispatcherFiltersBar
        filters={filters}
        onFiltersChange={setFilters}
      />

      <RecurringSchedulePanel
        schedules={recurringSchedules.schedules}
        schedulesLoading={recurringSchedules.loading}
        generatedRides={recurringScheduleRides.rides}
        generatedRidesLoading={recurringScheduleRides.loading}
        selectedScheduleId={selectedScheduleId}
        onSelectSchedule={setSelectedScheduleId}
        onCreateSchedule={handleCreateRecurringSchedule}
        onPauseSchedule={handlePauseSchedule}
        onResumeSchedule={handleResumeSchedule}
      />

      {/* Main Content */}
      <div className="command-center-content">
        {/* Left: Board/Queues */}
        <div className="board-section">
          <div className="board-tabs">
            <button
              className={`tab ${activeTab === 'board' ? 'active' : ''}`}
              onClick={() => setActiveTab('board')}
            >
              📊 Dispatcher Board
            </button>
            <button
              className={`tab ${activeTab === 'audit' ? 'active' : ''}`}
              onClick={() => setActiveTab('audit')}
            >
              📋 Activity Log
            </button>
          </div>

          {activeTab === 'board' && (
            <div className="rides-grid">
              {board.loading ? (
                <div className="loading">Loading dispatcher board...</div>
              ) : board.error && filteredRides().length === 0 ? (
                <div className="board-error-state">
                  <p>{board.error}</p>
                  <div className="banner-actions">
                    <button onClick={() => board.refetch()}>Retry dashboard</button>
                    <button onClick={() => wsConnection.retryConnect()}>Retry realtime</button>
                  </div>
                </div>
              ) : filteredRides().length > 0 ? (
                filteredRides().map(ride => (
                  <DispatcherRideCard
                    key={ride.id}
                    ride={ride}
                    vehicleLabel={ride.vehicle_id ? vehicleLabels.get(ride.vehicle_id) : undefined}
                    isSelected={selectedRide === ride.id}
                    onSelect={setSelectedRide}
                    onReassign={(rideId) => {
                      setSelectedRide(rideId);
                      setActionModal({ type: 'reassign', rideId });
                    }}
                    onComplete={handleCompleteRide}
                    onCancel={(rideId) => {
                      setSelectedRide(rideId);
                      setActionModal({ type: 'cancel', rideId });
                    }}
                    onEscalate={(rideId) => {
                      setSelectedRide(rideId);
                      setActionModal({ type: 'escalate', rideId });
                    }}
                  />
                ))
              ) : (
                <div className="empty-state">
                  <p>No rides match the current filters</p>
                  <button onClick={() => setFilters({})}>Clear Filters</button>
                </div>
              )}
            </div>
          )}

          {activeTab === 'audit' && (
            <AuditLogPanel
              activities={auditLog.activities}
              loading={auditLog.loading}
              error={auditLog.error}
            />
          )}
        </div>

        {/* Right: Details & Actions */}
        {selectedRideData && (
          <div className="details-section">
            <RideDetailsPanel
              ride={selectedRideData}
              vehicles={vehicles.vehicles}
              vehiclesLoading={vehicles.loading}
              currentVehicleLabel={selectedRideData.vehicle_id ? vehicleLabels.get(selectedRideData.vehicle_id) : undefined}
              activeOffers={activeOffers.offers.filter(row => row.ride_id === selectedRideData.id)}
              lifecycleAudit={lifecycleAudit.rows}
              onAssignVehicle={handleAssignVehicle}
              onSetRideStatus={handleSetRideStatus}
              onCompleteRide={handleCompleteRide}
              onReassign={() => setActionModal({ type: 'reassign', rideId: selectedRideData.id })}
              onCancel={() => setActionModal({ type: 'cancel', rideId: selectedRideData.id })}
              onEscalate={() => setActionModal({ type: 'escalate', rideId: selectedRideData.id })}
            />
          </div>
        )}
      </div>

      {/* Action Modals */}
      {actionModal.type && actionModal.rideId && (
        <RideActionModal
          type={actionModal.type}
          ride={selectedRideData!}
          onClose={() => setActionModal({ type: null, rideId: null })}
          onReassign={(driverId) => handleReassign(actionModal.rideId!, driverId)}
          onCancel={(reason) => handleCancel(actionModal.rideId!, reason)}
          onEscalate={(issueType, description) => handleEscalate(actionModal.rideId!, issueType, description)}
          loading={actions.loading}
          error={actions.error}
        />
      )}
    </div>
  );
}

function RecurringSchedulePanel({
  schedules,
  schedulesLoading,
  generatedRides,
  generatedRidesLoading,
  selectedScheduleId,
  onSelectSchedule,
  onCreateSchedule,
  onPauseSchedule,
  onResumeSchedule,
}: {
  schedules: RecurringSchedule[];
  schedulesLoading: boolean;
  generatedRides: DispatcherRide[];
  generatedRidesLoading: boolean;
  selectedScheduleId: string | null;
  onSelectSchedule: (scheduleId: string) => void;
  onCreateSchedule: (payload: CreateRecurringScheduleRequest) => Promise<void>;
  onPauseSchedule: (scheduleId: string) => Promise<void>;
  onResumeSchedule: (scheduleId: string) => Promise<void>;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState<CreateRecurringScheduleRequest>({
    provider_id: '',
    passenger_name: '',
    passenger_phone: '',
    pickup_address: '',
    dropoff_address: '',
    service_type: 'medical_transport',
    start_date: '',
    end_date: '',
    frequency: 'weekly',
    interval_count: 1,
    weekdays: [],
    pickup_time_local: '08:00',
    horizon_days: 30,
  });

  const toggleWeekday = (day: string) => {
    setForm((prev) => ({
      ...prev,
      weekdays: prev.weekdays.includes(day)
        ? prev.weekdays.filter((value) => value !== day)
        : [...prev.weekdays, day],
    }));
  };

  const selectedSchedule = schedules.find((item) => item.id === selectedScheduleId) || null;

  const handleSubmit = async () => {
    if (!form.provider_id || !form.passenger_name || !form.passenger_phone || !form.pickup_address || !form.dropoff_address || !form.start_date) {
      return;
    }
    setSubmitting(true);
    try {
      await onCreateSchedule(form);
      setForm((prev) => ({
        ...prev,
        passenger_name: '',
        passenger_phone: '',
        pickup_address: '',
        dropoff_address: '',
      }));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="recurring-schedule-panel">
      <div className="recurring-create">
        <h3>Recurring Transportation Scheduling</h3>
        <div className="recurring-form-grid">
          <input placeholder="Provider ID" value={form.provider_id} onChange={(event) => setForm({ ...form, provider_id: event.target.value })} />
          <input placeholder="Passenger Name" value={form.passenger_name} onChange={(event) => setForm({ ...form, passenger_name: event.target.value })} />
          <input placeholder="Passenger Phone" value={form.passenger_phone} onChange={(event) => setForm({ ...form, passenger_phone: event.target.value })} />
          <input placeholder="Pickup Address" value={form.pickup_address} onChange={(event) => setForm({ ...form, pickup_address: event.target.value })} />
          <input placeholder="Dropoff Address" value={form.dropoff_address} onChange={(event) => setForm({ ...form, dropoff_address: event.target.value })} />
          <input placeholder="Service Type" value={form.service_type} onChange={(event) => setForm({ ...form, service_type: event.target.value })} />
          <label>
            Start Date
            <input type="date" value={form.start_date} onChange={(event) => setForm({ ...form, start_date: event.target.value })} />
          </label>
          <label>
            End Date
            <input type="date" value={form.end_date || ''} onChange={(event) => setForm({ ...form, end_date: event.target.value })} />
          </label>
          <label>
            Frequency
            <select value={form.frequency} onChange={(event) => setForm({ ...form, frequency: event.target.value as CreateRecurringScheduleRequest['frequency'] })}>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
              <option value="custom">Custom weekdays</option>
            </select>
          </label>
          <label>
            Interval
            <input type="number" min={1} value={form.interval_count} onChange={(event) => setForm({ ...form, interval_count: Number(event.target.value || 1) })} />
          </label>
          <label>
            Pickup Time
            <input type="time" value={form.pickup_time_local} onChange={(event) => setForm({ ...form, pickup_time_local: event.target.value })} />
          </label>
          <label>
            Horizon Days
            <input type="number" min={1} max={180} value={form.horizon_days} onChange={(event) => setForm({ ...form, horizon_days: Number(event.target.value || 30) })} />
          </label>
        </div>

        {form.frequency === 'custom' && (
          <div className="weekday-toggle-group">
            {['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'].map((day) => (
              <button
                key={day}
                className={`weekday-toggle ${form.weekdays.includes(day) ? 'active' : ''}`}
                onClick={() => toggleWeekday(day)}
                type="button"
              >
                {day.toUpperCase()}
              </button>
            ))}
          </div>
        )}

        <button className="recurring-submit-btn" disabled={submitting} onClick={handleSubmit}>
          {submitting ? 'Creating...' : 'Create Recurring Schedule'}
        </button>
      </div>

      <div className="recurring-lists">
        <div className="recurring-schedule-list">
          <h4>Schedules</h4>
          {schedulesLoading ? (
            <div className="small-loading">Loading schedules...</div>
          ) : schedules.length === 0 ? (
            <div className="small-empty">No recurring schedules</div>
          ) : (
            schedules.map((schedule) => (
              <div key={schedule.id} className={`schedule-row ${selectedScheduleId === schedule.id ? 'selected' : ''}`}>
                <button type="button" onClick={() => onSelectSchedule(schedule.id)}>
                  {schedule.passenger_name} · {schedule.frequency}
                </button>
                {schedule.is_active ? (
                  <button type="button" onClick={() => onPauseSchedule(schedule.id)}>Pause</button>
                ) : (
                  <button type="button" onClick={() => onResumeSchedule(schedule.id)}>Resume</button>
                )}
              </div>
            ))
          )}
        </div>

        <div className="recurring-generated-list">
          <h4>Generated Rides{selectedSchedule ? ` (${selectedSchedule.passenger_name})` : ''}</h4>
          {generatedRidesLoading ? (
            <div className="small-loading">Loading generated rides...</div>
          ) : generatedRides.length === 0 ? (
            <div className="small-empty">No generated rides for selected schedule</div>
          ) : (
            generatedRides.slice(0, 8).map((ride) => (
              <div key={ride.id} className="generated-ride-row">
                <span>{ride.passenger_name}</span>
                <span>{ride.requested_at ? new Date(ride.requested_at).toLocaleDateString() : 'n/a'}</span>
                <span>{ride.status}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </section>
  );
}

// Ride Details Panel Component
function RideDetailsPanel({
  ride,
  vehicles,
  vehiclesLoading,
  currentVehicleLabel,
  activeOffers,
  lifecycleAudit,
  onAssignVehicle,
  onSetRideStatus,
  onCompleteRide,
  onReassign,
  onCancel,
  onEscalate,
}: {
  ride: DispatcherRide;
  vehicles: DispatcherVehicle[];
  vehiclesLoading: boolean;
  currentVehicleLabel?: string;
  activeOffers: Array<any>;
  lifecycleAudit: Array<any>;
  onAssignVehicle: (rideId: string, vehicleId: string) => Promise<void>;
  onSetRideStatus: (rideId: string, status: RideStatus) => Promise<void>;
  onCompleteRide: (rideId: string) => Promise<void>;
  onReassign: () => void;
  onCancel: () => void;
  onEscalate: () => void;
}) {
  const [selectedVehicleId, setSelectedVehicleId] = useState<string>(ride.vehicle_id || '');
  const [selectedStatus, setSelectedStatus] = useState<RideStatus | ''>('');
  const [updatingStatus, setUpdatingStatus] = useState(false);
  const [savingVehicle, setSavingVehicle] = useState(false);

  useEffect(() => {
    setSelectedVehicleId(ride.vehicle_id || '');
  }, [ride.id, ride.vehicle_id]);

  useEffect(() => {
    setSelectedStatus('');
  }, [ride.id, ride.status, ride.lifecycle_state]);

  const handleSaveVehicle = async () => {
    if (!selectedVehicleId) {
      return;
    }
    setSavingVehicle(true);
    try {
      await onAssignVehicle(ride.id, selectedVehicleId);
    } finally {
      setSavingVehicle(false);
    }
  };

  const currentLifecycle = String(ride.lifecycle_state || ride.status || '').toLowerCase();

  const nextLifecycleStatusByCurrent: Partial<Record<string, RideStatus>> = {
    requested: 'assigned',
    queued: 'assigned',
    assigned: 'driver_en_route',
    driver_en_route: 'arrived',
    arrived: 'rider_onboard',
    rider_onboard: 'in_progress',
    in_progress: 'completed',
  };

  const nextLifecycleStatus = nextLifecycleStatusByCurrent[currentLifecycle];
  const canMarkCompleted = currentLifecycle === 'in_progress';

  const handleCompleteRideClick = async () => {
    await onCompleteRide(ride.id);
  };

  const handleUpdateStatusClick = async () => {
    if (!selectedStatus) {
      return;
    }
    setUpdatingStatus(true);
    try {
      await onSetRideStatus(ride.id, selectedStatus);
    } finally {
      setUpdatingStatus(false);
    }
  };

  return (
    <div className="ride-details-panel">
      <h3>Ride Details</h3>

      <div className="detail-section">
        <h4>Passenger Information</h4>
        <div className="detail-row">
          <span className="label">Name:</span>
          <span className="value">{ride.passenger_name}</span>
        </div>
      </div>

      <div className="detail-section">
        <h4>Route</h4>
        <div className="detail-row">
          <span className="label">Pickup:</span>
          <span className="value">{ride.pickup_address}</span>
        </div>
        <div className="detail-row">
          <span className="label">Dropoff:</span>
          <span className="value">{ride.dropoff_address}</span>
        </div>
      </div>

      {ride.driver_name && (
        <div className="detail-section">
          <h4>Driver Assignment</h4>
          <div className="detail-row">
            <span className="label">Driver:</span>
            <span className="value">{ride.driver_name}</span>
          </div>
          {ride.provider_name && (
            <div className="detail-row">
              <span className="label">Provider:</span>
              <span className="value">{ride.provider_name}</span>
            </div>
          )}
        </div>
      )}

      <div className="detail-section">
        <h4>Vehicle Assignment</h4>
        <div className="detail-row">
          <span className="label">Current:</span>
          <span className="value">{currentVehicleLabel || 'Not assigned'}</span>
        </div>
        <div className="detail-vehicle-assignment">
          <select
            className="detail-vehicle-select"
            value={selectedVehicleId}
            onChange={(event) => setSelectedVehicleId(event.target.value)}
            disabled={vehiclesLoading || savingVehicle}
          >
            <option value="">Select active vehicle</option>
            {vehicles.map((vehicle) => (
              <option key={vehicle.id} value={vehicle.id}>
                {vehicle.vehicle_plate} · {vehicle.vehicle_type} (cap {vehicle.capacity})
              </option>
            ))}
          </select>
          <button
            className="detail-action-btn"
            onClick={handleSaveVehicle}
            disabled={!selectedVehicleId || savingVehicle || vehiclesLoading}
          >
            {savingVehicle ? 'Saving...' : 'Save Vehicle'}
          </button>
        </div>
      </div>

      <div className="detail-section">
        <h4>Trip Status</h4>
        <div className="detail-row">
          <span className="label">Status:</span>
          <span className="value">{ride.lifecycle_state || ride.status}</span>
        </div>
        {nextLifecycleStatus && (
          <div className="detail-status-controls">
            <select
              className="detail-status-select"
              value={selectedStatus}
              onChange={(event) => setSelectedStatus(event.target.value as RideStatus)}
              disabled={updatingStatus}
            >
              <option value="">Select next status</option>
              <option value={nextLifecycleStatus}>{nextLifecycleStatus}</option>
            </select>
            <button
              className="detail-action-btn"
              onClick={handleUpdateStatusClick}
              disabled={!selectedStatus || updatingStatus}
            >
              {updatingStatus ? 'Updating...' : 'Update Status'}
            </button>
          </div>
        )}
      </div>

      <div className="detail-section">
        <h4>Status Timeline</h4>
        <div className="detail-row">
          <span className="label">Requested:</span>
          <span className="value">{ride.requested_at ? new Date(ride.requested_at).toLocaleString() : 'n/a'}</span>
        </div>
        <div className="detail-row">
          <span className="label">Assigned:</span>
          <span className="value">{ride.assigned_at ? new Date(ride.assigned_at).toLocaleString() : 'n/a'}</span>
        </div>
        <div className="detail-row">
          <span className="label">En Route:</span>
          <span className="value">{ride.enroute_at ? new Date(ride.enroute_at).toLocaleString() : 'n/a'}</span>
        </div>
        <div className="detail-row">
          <span className="label">Arrived:</span>
          <span className="value">{ride.arrived_at ? new Date(ride.arrived_at).toLocaleString() : 'n/a'}</span>
        </div>
        <div className="detail-row">
          <span className="label">Picked Up:</span>
          <span className="value">{ride.picked_up_at ? new Date(ride.picked_up_at).toLocaleString() : 'n/a'}</span>
        </div>
        <div className="detail-row">
          <span className="label">Transporting:</span>
          <span className="value">{ride.transporting_at ? new Date(ride.transporting_at).toLocaleString() : 'n/a'}</span>
        </div>
        <div className="detail-row">
          <span className="label">Completed:</span>
          <span className="value">{ride.completed_at ? new Date(ride.completed_at).toLocaleString() : 'Not completed'}</span>
        </div>
      </div>

      <div className="detail-section">
        <h4>Quick Actions</h4>
        <div className="detail-actions">
          {(ride.status === 'pending' || ride.status === 'accepted') && (
            <>
              <button className="detail-action-btn" onClick={onReassign}>
                {ride.status === 'pending' ? '👤 Assign Driver' : '🔄 Reassign'}
              </button>
              <button className="detail-action-btn cancel" onClick={onCancel}>
                ❌ Cancel Ride
              </button>
            </>
          )}
          <button className="detail-action-btn escalate" onClick={onEscalate}>
            ⚠️ Escalate Issue
          </button>
          {canMarkCompleted && (
            <button className="detail-action-btn complete" onClick={handleCompleteRideClick}>
              ✅ Mark Completed
            </button>
          )}
        </div>
      </div>

      <div className="detail-section">
        <h4>Active Offer Visibility</h4>
        {activeOffers.length === 0 ? (
          <div className="detail-row">
            <span className="value">No active offers</span>
          </div>
        ) : (
          activeOffers.map((offer) => (
            <div key={offer.offer_id} className="detail-row">
              <span className="label">Offer {offer.attempt_index}:</span>
              <span className="value">
                {offer.assignment_state} | Driver {offer.driver_name || offer.driver_id || 'unassigned'}
                {offer.reassignment_attempt_count ? ` | Reassign #${offer.reassignment_attempt_count}` : ''}
              </span>
            </div>
          ))
        )}
      </div>

      <div className="detail-section">
        <h4>Lifecycle Audit Viewer</h4>
        {lifecycleAudit.length === 0 ? (
          <div className="detail-row">
            <span className="value">No lifecycle audit rows</span>
          </div>
        ) : (
          lifecycleAudit.slice(-6).map((row) => (
            <div key={row.id} className="detail-row">
              <span className="label">{row.action}:</span>
              <span className="value">{row.emitted_event_name || row.transition_reason || row.note || 'n/a'}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
