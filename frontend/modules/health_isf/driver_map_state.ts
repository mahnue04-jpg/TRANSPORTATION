/**
 * Driver map-state selectors for realtime-safe and hydration-safe rendering.
 */

import type { DriverGeospatialSnapshot } from './driver_app_contracts';

export interface DriverMapRenderableState {
  providerZones: Array<Record<string, unknown>>;
  driverPositions: Array<Record<string, unknown>>;
  incidentOverlays: Array<Record<string, unknown>>;
  emergencyOverlays: Array<Record<string, unknown>>;
  dispatchRecommendationOverlays: Array<Record<string, unknown>>;
  densityRegions: Array<Record<string, unknown>>;
  synchronized: boolean;
  hydrationSafe: boolean;
}

export function buildDriverMapRenderableState(
  geospatial: DriverGeospatialSnapshot | null | undefined,
  recommendations: Array<Record<string, unknown>> = [],
): DriverMapRenderableState {
  const state = geospatial?.live_operational_map_state;

  return {
    providerZones: Array.isArray(state?.provider_zones) ? state.provider_zones : [],
    driverPositions: Array.isArray(state?.driver_positioning) ? state.driver_positioning : [],
    incidentOverlays: Array.isArray(state?.incident_clustering) ? state.incident_clustering : [],
    emergencyOverlays: Array.isArray(state?.emergency_overlays) ? state.emergency_overlays : [],
    dispatchRecommendationOverlays: Array.isArray(recommendations) ? recommendations : [],
    densityRegions: Array.isArray(state?.operational_density_regions) ? state.operational_density_regions : [],
    synchronized: Boolean(geospatial?.websocket_synchronized && geospatial?.tenant_isolated),
    hydrationSafe: Boolean(geospatial?.hydration_compatible && geospatial?.realtime_safe),
  };
}
