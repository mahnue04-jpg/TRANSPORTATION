/**
 * Audit Log Panel Component
 * Display dispatcher activity logs
 */

import React from 'react';
import { DispatcherActivityLog } from '../dispatcherTypes';
import './AuditLogPanel.css';

interface AuditLogPanelProps {
  activities: DispatcherActivityLog[];
  loading: boolean;
  error?: string | null;
}

export function AuditLogPanel({
  activities,
  loading,
  error,
}: AuditLogPanelProps) {
  const getActionIcon = (action: string): string => {
    const icons: Record<string, string> = {
      ride_created: '📝',
      driver_assigned: '👤',
      driver_reassigned: '🔄',
      ride_cancelled: '❌',
      ride_completed: '✅',
      ride_escalated: '⚠️',
      status_changed: '📊',
      retry_attempted: '🔁',
    };
    return icons[action] || '📋';
  };

  const formatTime = (timestamp: string): string => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
    return date.toLocaleString();
  };

  if (loading) {
    return <div className="audit-log-panel loading">Loading activity log...</div>;
  }

  if (error) {
    return <div className="audit-log-panel error">Failed to load activity log: {error}</div>;
  }

  return (
    <div className="audit-log-panel">
      {activities.length > 0 ? (
        <div className="activity-list">
          {activities.map(activity => (
            <div key={activity.id} className="activity-item">
              <div className="activity-icon">{getActionIcon(activity.action)}</div>
              <div className="activity-details">
                <div className="activity-action">
                  {activity.action.replace(/_/g, ' ').toUpperCase()}
                </div>
                <div className="activity-description">{activity.description}</div>
                {activity.actor_user_name && (
                  <div className="activity-actor">by {activity.actor_user_name}</div>
                )}
              </div>
              <div className="activity-time">{formatTime(activity.created_at)}</div>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-log">No activity recorded yet</div>
      )}
    </div>
  );
}
