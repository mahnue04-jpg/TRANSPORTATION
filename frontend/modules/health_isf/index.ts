/**
 * Dispatcher Module - Public API
 * Exports all dispatcher command center components and utilities
 */

// Main Component
export { DispatcherCommandCenter } from './DispatcherCommandCenter';

// Types
export type {
  RideStatus,
  DriverStatus,
  PriorityLevel,
  RideQueueType,
  DispatcherRide,
  DispatcherDriver,
  DispatcherProvider,
  DispatcherQueue,
  DispatcherBoardState,
  OperationalAlert,
  DispatcherActivityLog,
  DispatcherFilters,
  AssignDriverRequest,
  ReassignDriverRequest,
  EscalateIssueRequest,
  WebSocketEvent,
  RideUpdateEvent,
} from './dispatcherTypes';

// Hooks
export {
  useDispatcherBoard,
  useDispatcherQueues,
  useAuditLog,
  useDispatcherAction,
  useDispatcherWebSocket,
} from './dispatcherHooks';

// WebSocket
export {
  createDispatcherWebSocketManager,
  type WebSocketManager,
  type WebSocketConnectionState,
} from './webSocketManager';

// UI Components
export { DispatcherRideCard } from './components/DispatcherRideCard';
export { DispatcherFiltersBar } from './components/DispatcherFiltersBar';
export { RideActionModal } from './components/RideActionModal';
export { AuditLogPanel } from './components/AuditLogPanel';
export { DispatcherBoard } from './components/DispatcherBoard';

// Driver Operations App Foundation
export type {
  DriverClientRole,
  DriverVisibilityScope,
  DriverOperationalIdentitySnapshot,
  DriverGeospatialSnapshot,
  DriverDispatchRecommendation,
  DriverDispatchSnapshot,
  DriverOperationalIntelligenceExpansion,
  DriverOperationsStatusResponse,
} from './driver_app_contracts';
export { getDriverExpansionFromOperationsStatus } from './driver_app_contracts';

export type { DriverMapRenderableState } from './driver_map_state';
export { buildDriverMapRenderableState } from './driver_map_state';

export type { DriverDispatchFeedItem } from './driver_dispatch_feed';
export { buildDriverDispatchFeed } from './driver_dispatch_feed';

export type {
  DriverWebSocketState,
  DriverWebSocketEvent,
  DriverWebSocketClient,
} from './driver_websocket_client';
export { createDriverWebSocketClient } from './driver_websocket_client';

export { DriverOperationalStore, createDriverOperationalStore } from './driver_operational_store';

// Distributed Operational Synchronization
export type {
  OperationalEventType,
  OperationalEventEnvelope,
  DistributedEventFabricSnapshot,
  DistributedOperationsStatusContract,
} from './operational_event_contracts';
export { getDistributedEventFabric } from './operational_event_contracts';

export type {
  OperationalDecisionRecommendation,
  OperationalDecisionIntelligenceSnapshot,
  OperationalDecisionStatusContract,
} from './operational_decision_contracts';
export { getOperationalDecisionSnapshot } from './operational_decision_contracts';

export type {
  MultiAgentCoordinationRecommendation,
  OperationalCoordinationBundle,
  OperationalCoordinationStatusContract,
} from './operational_coordination_contracts';
export { getOperationalCoordinationBundle } from './operational_coordination_contracts';

export type { DashboardIntelligenceOverlays } from './dashboard_intelligence_overlays';
export { buildDashboardIntelligenceOverlays } from './dashboard_intelligence_overlays';

export type { DashboardCoordinationSyncState } from './dashboard_coordination_sync';
export { buildDashboardCoordinationSyncState } from './dashboard_coordination_sync';

export type { DriverIntelligenceAssistState } from './driver_intelligence_assist';
export { buildDriverIntelligenceAssistState } from './driver_intelligence_assist';

export type { DriverCoordinationAssistState } from './driver_coordination_assist';
export { buildDriverCoordinationAssistState } from './driver_coordination_assist';

export type { ProviderOperationalIntelligenceState } from './provider_intelligence_state';
export { buildProviderOperationalIntelligenceState } from './provider_intelligence_state';

export type { ProviderCoordinationAssistState } from './provider_coordination_assist';
export { buildProviderCoordinationAssistState } from './provider_coordination_assist';

export type { ProviderVisibilityScope, ProviderOperationalContracts } from './provider_app_contracts';
export { getProviderContracts } from './provider_app_contracts';

export type { ProviderWebSocketState, ProviderWebSocketClient } from './provider_websocket_client';
export { createProviderWebSocketClient } from './provider_websocket_client';

export type { ProviderQueueRenderableState } from './provider_queue_state';
export { buildProviderQueueState } from './provider_queue_state';

export { ProviderOperationalStore, createProviderOperationalStore } from './provider_operational_store';

export type { DashboardLiveCoordinationState } from './dashboard_live_coordination';
export { buildDashboardLiveCoordinationState } from './dashboard_live_coordination';
