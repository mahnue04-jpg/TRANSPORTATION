/**
 * Dispatcher Command Center Types & Schemas
 * Enterprise dispatcher operations data structures
 */

export type RideStatus =
  | "requested"
  | "queued"
  | "assigned"
  | "driver_en_route"
  | "arrived"
  | "rider_onboard"
  | "in_progress"
  | "pending"
  | "accepted"
  | "in_transit"
  | "completed"
  | "cancelled";
export type DriverStatus = "offline" | "available" | "assigned" | "en_route_pickup" | "waiting_at_pickup" | "in_transit" | "completed" | "unavailable" | "busy";
export type PriorityLevel = "low" | "normal" | "high" | "emergency";
export type RideQueueType = "active" | "pending" | "delayed" | "completed";

export interface DispatcherRide {
  id: string;
  passenger_name: string;
  pickup_address: string;
  dropoff_address: string;
  status: RideStatus;
  lifecycle_state?: string;
  priority_tag?: string;
  priority_score?: number;
  is_emergency: boolean;
  driver_id?: string;
  driver_name?: string;
  vehicle_id?: string;
  vehicle_type?: string;
  vehicle_plate?: string;
  provider_id?: string;
  provider_name?: string;
  scheduled_time?: string; // ISO datetime
  estimated_duration_minutes?: number;
  estimated_distance_miles?: number;
  requested_at: string; // ISO datetime
  recurring_schedule_id?: string;
  recurring_instance_date?: string;
  assigned_at?: string;
  enroute_at?: string;
  arrived_at?: string;
  picked_up_at?: string;
  transporting_at?: string;
  created_at?: string;
  accepted_at?: string;
  completed_at?: string;
  notes?: string;
}

export interface DispatcherDriver {
  id: string;
  name: string;
  phone: string;
  status: DriverStatus;
  vehicle_plate?: string;
  vehicle_type?: string;
  total_trips?: number;
  rating?: number;
  is_active: boolean;
}

export interface DispatcherVehicle {
  id: string;
  organization_id: string;
  vehicle_type: string;
  vehicle_plate: string;
  capacity: number;
  is_active: boolean;
}

export interface DispatcherProvider {
  id: string;
  name: string;
  address: string;
  phone: string;
  service_type: string;
  is_active: boolean;
}

export interface DispatcherQueue {
  active: DispatcherRide[];
  pending: DispatcherRide[];
  delayed: DispatcherRide[];
  completed: DispatcherRide[];
}

export interface DispatcherBoardState {
  organization_id: string;
  active_rides: DispatcherRide[];
  pending_rides: DispatcherRide[];
  available_drivers: DispatcherDriver[];
  dispatch_load: number; // 0-100
  operational_alerts: OperationalAlert[];
  timestamp: string;
}

export interface OperationalAlert {
  id: string;
  alert_type: string;
  severity: "low" | "medium" | "high" | "critical";
  message: string;
  ride_id?: string;
  driver_id?: string;
  created_at: string;
}

export interface DispatcherActivityLog {
  id: string;
  action: string;
  description: string;
  ride_id?: string;
  driver_id?: string;
  actor_user_id?: string;
  actor_user_name?: string;
  created_at: string;
  details?: Record<string, any>;
}

export interface DispatchActiveOffer {
  offer_id: string;
  ride_id: string;
  driver_id?: string;
  driver_name?: string;
  assignment_state: string;
  attempt_index: number;
  score?: number;
  offered_at?: string;
  offer_expires_at?: string;
  reassignment_attempt_count?: number;
  reassignment_reason?: string;
  reassignment_chain_id?: string;
}

export interface DispatchLifecycleAuditRow {
  id: string;
  ride_id: string;
  driver_id?: string;
  action: string;
  note?: string;
  emitted_event_name?: string;
  lifecycle_state?: string;
  transition_reason?: string;
  transition_timestamp?: string;
  assignment_transition_source?: string;
  created_at: string;
}

export interface DispatcherFilters {
  status?: RideStatus[];
  provider_id?: string;
  driver_id?: string;
  priority_level?: PriorityLevel;
  search_query?: string;
  is_emergency_only?: boolean;
}

export interface AssignDriverRequest {
  driver_id: string;
}

export interface ReassignDriverRequest {
  driver_id: string;
}

export interface EscalateIssueRequest {
  issue_type: string;
  description: string;
}

export interface RecurringSchedule {
  id: string;
  organization_id: string;
  provider_id?: string;
  passenger_name: string;
  passenger_phone: string;
  pickup_address: string;
  dropoff_address: string;
  service_type: string;
  pickup_time_local: string;
  frequency: "daily" | "weekly" | "monthly" | "custom";
  interval_count: number;
  weekdays: number[];
  start_date: string;
  end_date?: string;
  is_active: boolean;
  last_generated_at?: string;
  generated_until?: string;
  generated_ride_count: number;
}

export interface CreateRecurringScheduleRequest {
  provider_id: string;
  passenger_name: string;
  passenger_phone: string;
  pickup_address: string;
  dropoff_address: string;
  service_type: string;
  start_date: string;
  end_date?: string;
  frequency: "daily" | "weekly" | "monthly" | "custom";
  interval_count: number;
  weekdays: string[];
  pickup_time_local: string;
  horizon_days: number;
}

export interface WebSocketEvent<T = any> {
  type: "event" | "error" | "connected" | "subscribed" | "ping" | "pong" | "sync" | "unsubscribed" | "workflow_timeline";
  event_type?: string;
  event_id?: string;
  sequence?: number;
  payload?: T;
  events?: Array<Record<string, any>>;
  latest_sequence?: number;
  requested_sequence?: number;
  recovery?: Record<string, any>;
  workflow_coordination?: Record<string, any>;
  distributed_governance?: Record<string, any>;
  cognitive_diagnostics?: Record<string, any>;
  timeline?: {
    chain?: Record<string, any>;
    checkpoints?: Array<Record<string, any>>;
    queued_tasks?: Array<Record<string, any>>;
  };
  chain_id?: string;
  connection_id?: string;
  timestamp: string;
  code?: string;
  detail?: string;
  degraded_reasons?: string[];
}

export interface RideUpdateEvent {
  ride_id: string;
  from_status?: string;
  to_status?: string;
  driver_id?: string;
  driver_name?: string;
  issue_type?: string;
  description?: string;
  actor_user_id?: string;
}
