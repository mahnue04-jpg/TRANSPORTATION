/**
 * Dispatcher Board Component
 * Displays the list of rides from the Health ISF API
 */

import React, { useEffect, useState } from 'react';
import { fetchHealthRides } from '../apiClient';
import './DispatcherBoard.css';
import './DispatcherBoard.css';

interface Ride {
  id: string;
  passenger_name: string;
  phone: string;
  pickup_address: string;
  dropoff_address: string;
  status: string;
  lifecycle_state: string;
  priority_tag?: string;
  service_type?: string;
  is_emergency?: boolean;
  requested_at?: string;
  driver_id?: string;
  vehicle_id?: string;
}

export function DispatcherBoard() {
  const [rides, setRides] = useState<Ride[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedRide, setSelectedRide] = useState<string | null>(null);

  useEffect(() => {
    const loadRides = async () => {
      try {
        setLoading(true);
        const data = await fetchHealthRides();
        setRides(Array.isArray(data) ? data : []);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load rides');
        setRides([]);
      } finally {
        setLoading(false);
      }
    };

    loadRides();
    const interval = setInterval(loadRides, 5000);
    return () => clearInterval(interval);
  }, []);

  const getRidesByStatus = (status: string) => rides.filter(r => r.status === status);
  const pendingRides = getRidesByStatus('pending');
  const acceptedRides = getRidesByStatus('accepted');
  const inTransitRides = getRidesByStatus('in_transit');
  const completedRides = getRidesByStatus('completed');
  const cancelledRides = getRidesByStatus('cancelled');

  const renderRideCard = (ride: Ride) => (
    <div 
      key={ride.id} 
      className={`ride-card ${ride.is_emergency ? 'emergency' : ''} ${selectedRide === ride.id ? 'selected' : ''}`}
      onClick={() => setSelectedRide(ride.id)}
    >
      <div className="ride-card-header">
        <div className="ride-id">{ride.id.substring(0, 8)}</div>
        <div className={`ride-status status-${ride.status}`}>{ride.status}</div>
      </div>
      <div className="ride-card-body">
        <p><strong>{ride.passenger_name}</strong></p>
        <p className="ride-phone">{ride.phone}</p>
        <div className="ride-addresses">
          <p><span className="label">From:</span> {ride.pickup_address}</p>
          <p><span className="label">To:</span> {ride.dropoff_address}</p>
        </div>
      </div>
      <div className="ride-card-footer">
        {ride.service_type && <span className="badge">{ride.service_type}</span>}
        {ride.priority_tag && <span className={`badge priority-${ride.priority_tag}`}>{ride.priority_tag}</span>}
        {ride.driver_id && <span className="badge">Assigned</span>}
      </div>
    </div>
  );

  return (
    <div className="dispatcher-board">
      {error && (
        <div className="error-banner">
          <p>{error}</p>
          <button onClick={() => window.location.reload()}>Retry</button>
        </div>
      )}

      {loading && !rides.length && <div className="loading">Loading rides...</div>}

      <div className="rides-grid">
        <section className="ride-queue">
          <h3>Pending Rides ({pendingRides.length})</h3>
          <div className="ride-card-list">
            {pendingRides.length > 0 ? pendingRides.map(renderRideCard) : <p>No pending rides</p>}
          </div>
        </section>

        <section className="ride-queue">
          <h3>Accepted Rides ({acceptedRides.length})</h3>
          <div className="ride-card-list">
            {acceptedRides.length > 0 ? acceptedRides.map(renderRideCard) : <p>No accepted rides</p>}
          </div>
        </section>

        <section className="ride-queue">
          <h3>In Transit ({inTransitRides.length})</h3>
          <div className="ride-card-list">
            {inTransitRides.length > 0 ? inTransitRides.map(renderRideCard) : <p>No rides in transit</p>}
          </div>
        </section>

        <section className="ride-queue">
          <h3>Completed ({completedRides.length})</h3>
          <div className="ride-card-list">
            {completedRides.length > 0 ? completedRides.map(renderRideCard) : <p>No completed rides</p>}
          </div>
        </section>
      </div>

      {selectedRide && (
        <div className="ride-details">
          <h3>Ride Details</h3>
          {rides.find(r => r.id === selectedRide) && (
            <pre>{JSON.stringify(rides.find(r => r.id === selectedRide), null, 2)}</pre>
          )}
        </div>
      )}
    </div>
  );
}
