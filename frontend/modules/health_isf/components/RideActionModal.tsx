/**
 * Ride Action Modal Component
 * Handles dispatcher actions: assign, reassign, cancel, escalate
 */

import React, { useState } from 'react';
import { DispatcherRide, ReassignDriverRequest, EscalateIssueRequest } from '../dispatcherTypes';
import './RideActionModal.css';

interface RideActionModalProps {
  type: 'assign' | 'reassign' | 'cancel' | 'escalate';
  ride: DispatcherRide;
  onClose: () => void;
  onReassign: (driverId: string) => void;
  onCancel: (reason: string) => void;
  onEscalate: (issueType: string, description: string) => void;
  loading?: boolean;
  error?: string | null;
}

// Mock drivers - in real app, fetch from API
const MOCK_DRIVERS = [
  { id: 'dr1', name: 'John Smith', status: 'available', rating: 4.8 },
  { id: 'dr2', name: 'Jane Doe', status: 'available', rating: 4.9 },
  { id: 'dr3', name: 'Bob Wilson', status: 'assigned', rating: 4.7 },
];

export function RideActionModal({
  type,
  ride,
  onClose,
  onReassign,
  onCancel,
  onEscalate,
  loading = false,
  error = null,
}: RideActionModalProps) {
  const [selectedDriver, setSelectedDriver] = useState<string>('');
  const [cancelReason, setCancelReason] = useState('');
  const [issueType, setIssueType] = useState('');
  const [issueDescription, setIssueDescription] = useState('');

  const handleSubmit = () => {
    if (type === 'reassign' || type === 'assign') {
      if (selectedDriver) onReassign(selectedDriver);
    } else if (type === 'cancel') {
      if (cancelReason) onCancel(cancelReason);
    } else if (type === 'escalate') {
      if (issueType && issueDescription) onEscalate(issueType, issueDescription);
    }
  };

  const canSubmit = () => {
    if (type === 'reassign' || type === 'assign') return !!selectedDriver;
    if (type === 'cancel') return !!cancelReason;
    if (type === 'escalate') return !!issueType && !!issueDescription;
    return false;
  };

  const getModalTitle = () => {
    const titles = {
      assign: 'Assign Driver',
      reassign: 'Reassign Driver',
      cancel: 'Cancel Ride',
      escalate: 'Escalate Issue',
    };
    return titles[type];
  };

  const getModalDescription = () => {
    const descriptions = {
      assign: `Assign an available driver to ride ${ride.id}`,
      reassign: `Reassign ride ${ride.id} to a different driver`,
      cancel: `Cancel ride ${ride.id} for passenger ${ride.passenger_name}`,
      escalate: `Report an operational issue with ride ${ride.id}`,
    };
    return descriptions[type];
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="ride-action-modal" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <h2>{getModalTitle()}</h2>
          <button className="close-btn" onClick={onClose}>✕</button>
        </div>

        {/* Description */}
        <p className="modal-description">{getModalDescription()}</p>

        {/* Error */}
        {error && (
          <div className="modal-error">
            {error}
          </div>
        )}

        {/* Content */}
        <div className="modal-content">
          {(type === 'assign' || type === 'reassign') && (
            <AssignDriverPanel
              currentDriver={ride.driver_name}
              onDriverSelect={setSelectedDriver}
              selectedDriver={selectedDriver}
            />
          )}

          {type === 'cancel' && (
            <CancelRidePanel
              reason={cancelReason}
              onReasonChange={setCancelReason}
            />
          )}

          {type === 'escalate' && (
            <EscalateIssuePanel
              issueType={issueType}
              description={issueDescription}
              onIssueTypeChange={setIssueType}
              onDescriptionChange={setIssueDescription}
            />
          )}
        </div>

        {/* Actions */}
        <div className="modal-actions">
          <button className="action-btn cancel-btn" onClick={onClose}>
            Cancel
          </button>
          <button
            className="action-btn submit-btn"
            onClick={handleSubmit}
            disabled={!canSubmit() || loading}
          >
            {loading ? 'Processing...' : 'Submit'}
          </button>
        </div>
      </div>
    </div>
  );
}

// Assign Driver Panel
function AssignDriverPanel({
  currentDriver,
  onDriverSelect,
  selectedDriver,
}: {
  currentDriver?: string;
  onDriverSelect: (driverId: string) => void;
  selectedDriver: string;
}) {
  const availableDrivers = MOCK_DRIVERS.filter(d => d.status === 'available');

  return (
    <div className="panel-content">
      <h3>Select Driver</h3>
      {currentDriver && (
        <div className="current-driver">
          <span>Current: {currentDriver}</span>
        </div>
      )}

      <div className="driver-list">
        {availableDrivers.map(driver => (
          <div
            key={driver.id}
            className={`driver-option ${selectedDriver === driver.id ? 'selected' : ''}`}
            onClick={() => onDriverSelect(driver.id)}
          >
            <div className="driver-info">
              <span className="driver-name">{driver.name}</span>
              <span className="driver-rating">⭐ {driver.rating}</span>
            </div>
          </div>
        ))}
      </div>

      {availableDrivers.length === 0 && (
        <div className="no-drivers">
          No available drivers at this time
        </div>
      )}
    </div>
  );
}

// Cancel Ride Panel
function CancelRidePanel({
  reason,
  onReasonChange,
}: {
  reason: string;
  onReasonChange: (reason: string) => void;
}) {
  const commonReasons = [
    'Passenger not ready',
    'Driver unavailable',
    'Traffic/Road closure',
    'System error',
    'Other',
  ];

  return (
    <div className="panel-content">
      <h3>Cancellation Reason</h3>

      <div className="reason-buttons">
        {commonReasons.map(r => (
          <button
            key={r}
            className={`reason-btn ${reason === r ? 'selected' : ''}`}
            onClick={() => onReasonChange(r)}
          >
            {r}
          </button>
        ))}
      </div>

      <textarea
        placeholder="Additional details (optional)..."
        value={reason}
        onChange={(e) => onReasonChange(e.target.value)}
        className="reason-textarea"
      />
    </div>
  );
}

// Escalate Issue Panel
function EscalateIssuePanel({
  issueType,
  description,
  onIssueTypeChange,
  onDescriptionChange,
}: {
  issueType: string;
  description: string;
  onIssueTypeChange: (type: string) => void;
  onDescriptionChange: (desc: string) => void;
}) {
  const issueTypes = [
    'Driver issue',
    'Safety concern',
    'Navigation problem',
    'Communication failure',
    'Passenger complaint',
    'Vehicle issue',
  ];

  return (
    <div className="panel-content">
      <h3>Issue Type</h3>

      <div className="issue-type-select">
        <select
          value={issueType}
          onChange={(e) => onIssueTypeChange(e.target.value)}
          className="select-input"
        >
          <option value="">Select an issue type...</option>
          {issueTypes.map(type => (
            <option key={type} value={type}>{type}</option>
          ))}
        </select>
      </div>

      <h3 style={{ marginTop: '1rem' }}>Description</h3>
      <textarea
        placeholder="Describe the issue in detail..."
        value={description}
        onChange={(e) => onDescriptionChange(e.target.value)}
        className="description-textarea"
      />
    </div>
  );
}
