/**
 * Dispatcher Filters Bar Component
 * Real-time filtering for dispatcher rides
 */

import React, { useState } from 'react';
import { DispatcherFilters, RideStatus } from '../dispatcherTypes';
import './DispatcherFiltersBar.css';

interface DispatcherFiltersBarProps {
  filters: DispatcherFilters;
  onFiltersChange: (filters: DispatcherFilters) => void;
}

const RIDE_STATUSES: RideStatus[] = ['pending', 'accepted', 'in_transit', 'completed', 'cancelled'];

export function DispatcherFiltersBar({
  filters,
  onFiltersChange,
}: DispatcherFiltersBarProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  const handleStatusToggle = (status: RideStatus) => {
    const currentStatuses = filters.status || [];
    const updated = currentStatuses.includes(status)
      ? currentStatuses.filter(s => s !== status)
      : [...currentStatuses, status];

    onFiltersChange({
      ...filters,
      status: updated.length > 0 ? updated : undefined,
    });
  };

  const handleSearch = (query: string) => {
    onFiltersChange({
      ...filters,
      search_query: query || undefined,
    });
  };

  const handleClearAll = () => {
    onFiltersChange({});
  };

  const hasActiveFilters = filters.status?.length || filters.search_query || filters.provider_id || filters.is_emergency_only;

  return (
    <div className="dispatcher-filters-bar">
      <div className="filters-container">
        {/* Search */}
        <div className="filter-group search">
          <input
            type="text"
            placeholder="Search passenger, address..."
            value={filters.search_query || ''}
            onChange={(e) => handleSearch(e.target.value)}
            className="search-input"
          />
        </div>

        {/* Quick Status Filters */}
        <div className="filter-group statuses">
          {RIDE_STATUSES.map(status => (
            <button
              key={status}
              className={`status-filter ${filters.status?.includes(status) ? 'active' : ''}`}
              onClick={() => handleStatusToggle(status)}
            >
              {status.charAt(0).toUpperCase() + status.slice(1)}
            </button>
          ))}
        </div>

        {/* Emergency Only */}
        <div className="filter-group emergency">
          <button
            className={`emergency-filter ${filters.is_emergency_only ? 'active' : ''}`}
            onClick={() => onFiltersChange({
              ...filters,
              is_emergency_only: !filters.is_emergency_only,
            })}
          >
            🚨 Emergency Only
          </button>
        </div>

        {/* Clear Filters */}
        {hasActiveFilters && (
          <button className="clear-filters-btn" onClick={handleClearAll}>
            Clear All
          </button>
        )}
      </div>

      {/* Advanced Filters Toggle */}
      <button
        className="advanced-toggle"
        onClick={() => setShowAdvanced(!showAdvanced)}
      >
        {showAdvanced ? '▼' : '▶'} Advanced
      </button>

      {/* Advanced Filters */}
      {showAdvanced && (
        <div className="advanced-filters">
          {/* Provider Filter would go here */}
          <div className="advanced-filter-group">
            <label>Provider ID:</label>
            <input
              type="text"
              placeholder="Filter by provider..."
              value={filters.provider_id || ''}
              onChange={(e) => onFiltersChange({
                ...filters,
                provider_id: e.target.value || undefined,
              })}
            />
          </div>
        </div>
      )}
    </div>
  );
}
