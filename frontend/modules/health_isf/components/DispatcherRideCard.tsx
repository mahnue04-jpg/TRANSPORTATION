/**
 * Ride Card Component - Display individual ride details in the dispatcher board
 */

import React, { useState } from 'react';
import { DispatcherRide, RideStatus, PriorityLevel } from './dispatcherTypes';
import './DispatcherRide.css';

interface DispatcherRideCardProps {
  ride: DispatcherRide;
  vehicleLabel?: string;
  onReassign?: (rideId: string) => void;
  onComplete?: (rideId: string) => void;
  onCancel?: (rideId: string) => void;
  onEscalate?: (rideId: string) => void;
  onSelect?: (rideId: string) => void;
  isSelected?: boolean;
}

export function DispatcherRideCard({
  ride,
  vehicleLabel,
  onReassign,
  onComplete,
  onCancel,
  onEscalate,
  onSelect,
  isSelected,
}: DispatcherRideCardProps) {
  const [showActions, setShowActions] = useState(false);

  const statusClass = `status-${ride.status}`;
  const priorityClass = ride.is_emergency ? 'priority-emergency' : ride.priority_tag ? `priority-${ride.priority_tag}` : 'priority-normal';

  const getStatusLabel = (status: RideStatus): string => {
    const labels: Record<RideStatus, string> = {
      pending: 'Pending',
      accepted: 'Accepted',
      in_transit: 'In Transit',
      completed: 'Completed',
      cancelled: 'Cancelled',
    };
    return labels[status];
  };

  const getEstimatedTime = (): string => {
    if (!ride.requested_at || !ride.estimated_duration_minutes) return 'N/A';
    const requestedTime = new Date(ride.requested_at);
    const eta = new Date(requestedTime.getTime() + ride.estimated_duration_minutes * 60000);
    return eta.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const isOverdue = (): boolean => {
    if (!ride.requested_at || !ride.estimated_duration_minutes) return false;
    const requestedTime = new Date(ride.requested_at);
    const estimatedEnd = new Date(requestedTime.getTime() + ride.estimated_duration_minutes * 60000);
    return new Date() > estimatedEnd && ride.status !== 'completed' && ride.status !== 'cancelled';
  };

  const canMarkCompleted = ['accepted', 'in_transit', 'in_progress', 'driver_en_route', 'arrived', 'rider_onboard'].includes(String(ride.status || '').toLowerCase());

  return (
    <div
      className={`dispatcher-ride-card ${statusClass} ${priorityClass} ${isSelected ? 'selected' : ''} ${isOverdue() ? 'overdue' : ''}`}
      onClick={() => onSelect?.(ride.id)}
      onMouseEnter={() => setShowActions(true)}
      onMouseLeave={() => setShowActions(false)}
    >
      {/* Header */}
      <div className="ride-card-header">
        <div className="ride-id-priority">
          <span className="ride-id">#{ride.id.substring(0, 8)}</span>
          <span className={`priority-badge ${ride.is_emergency ? 'emergency' : ''}`}>
            {ride.is_emergency ? '🚨 EMERGENCY' : ride.priority_tag || 'NORMAL'}
          </span>
        </div>
        <span className={`status-badge ${statusClass}`}>{getStatusLabel(ride.status)}</span>
      </div>

      {/* Passenger Info */}
      <div className="ride-card-section">
        <div className="passenger-info">
          <span className="label">Passenger:</span>
          <span className="value">{ride.passenger_name}</span>
        </div>
      </div>

      {/* Pickup & Dropoff */}
      <div className="ride-card-section addresses">
        <div className="address-info pickup">
          <span className="location-icon">📍</span>
          <div>
            <span className="label">Pickup:</span>
            <span className="value">{ride.pickup_address}</span>
          </div>
        </div>
        <div className="address-info dropoff">
          <span className="location-icon">🏁</span>
          <div>
            <span className="label">Dropoff:</span>
            <span className="value">{ride.dropoff_address}</span>
          </div>
        </div>
      </div>

      {/* Driver Info */}
      {ride.driver_name && (
        <div className="ride-card-section driver-info">
          <span className="label">Driver:</span>
          <span className="value">{ride.driver_name}</span>
          {ride.provider_name && <span className="provider">({ride.provider_name})</span>}
        </div>
      )}

      {vehicleLabel && (
        <div className="ride-card-section vehicle-info">
          <span className="label">Vehicle:</span>
          <span className="value">{vehicleLabel}</span>
        </div>
      )}

      {/* Time Info */}
      <div className="ride-card-section time-info">
        <div className="time-slot">
          <span className="label">ETA:</span>
          <span className="value">{getEstimatedTime()}</span>
        </div>
        {ride.estimated_distance_miles && (
          <div className="distance-slot">
            <span className="label">Distance:</span>
            <span className="value">{ride.estimated_distance_miles.toFixed(1)} mi</span>
          </div>
        )}
      </div>

      {/* Notes */}
      {ride.notes && (
        <div className="ride-card-section notes">
          <span className="label">Notes:</span>
          <span className="value">{ride.notes}</span>
        </div>
      )}

      {/* Actions */}
      {showActions && (
        <div className="ride-card-actions">
          {ride.status === 'pending' && onReassign && (
            <button className="action-btn reassign" onClick={e => {
              e.stopPropagation();
              onReassign(ride.id);
            }}>
              Assign Driver
            </button>
          )}
          {ride.status === 'accepted' && onReassign && (
            <button className="action-btn reassign" onClick={e => {
              e.stopPropagation();
              onReassign(ride.id);
            }}>
              Reassign
            </button>
          )}
          {(ride.status === 'pending' || ride.status === 'accepted') && onCancel && (
            <button className="action-btn cancel" onClick={e => {
              e.stopPropagation();
              onCancel(ride.id);
            }}>
              Cancel
            </button>
          )}
          {canMarkCompleted && onComplete && (
            <button className="action-btn complete" onClick={e => {
              e.stopPropagation();
              onComplete(ride.id);
            }}>
              Complete
            </button>
          )}
          {onEscalate && (
            <button className="action-btn escalate" onClick={e => {
              e.stopPropagation();
              onEscalate(ride.id);
            }}>
              Escalate
            </button>
          )}
        </div>
      )}
    </div>
  );
}
