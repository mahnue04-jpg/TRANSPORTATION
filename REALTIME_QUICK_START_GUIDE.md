# Real-Time Dispatch Operations - Quick Start Guide

## For Dispatchers

### 1. Opening the Live Dashboard

The dispatcher dashboard now receives real-time updates automatically. No manual refresh needed!

**What's Updated Live:**
- ✅ Rides appear/disappear from "Pending" column
- ✅ Driver availability status changes instantly
- ✅ Assigned rides move to "Active" column
- ✅ Completed rides move to "Completed" column
- ✅ Activity feed shows recent actions at bottom

### 2. Assigning a Ride (with Concurrent Protection)

When you assign a ride:
1. Click "Assign Driver" button
2. Select available driver
3. Click "Confirm"

**What happens:**
- System locks the ride (prevents other dispatchers from assigning simultaneously)
- Your assignment is processed
- Lock is automatically released
- Event sent to driver dashboard
- Activity log updated
- All other dispatchers see the change instantly

**If you see 409 Conflict Error:**
- Another dispatcher is assigning this ride at the same time
- Wait a moment and retry
- Ride will refresh automatically

### 3. Monitoring Activity Feed

Bottom-right of dashboard shows recent actions:
- 🚗 "Ride assigned to driver John Smith"
- ✅ "Ride completed"
- ❌ "Assignment declined by Maria"
- 🔄 "Driver went online"

Click on any activity to see full details and timestamp.

### 4. Real-Time Connection Status

Top-right corner shows:
- 🟢 **Connected**: Live updates active (normal)
- 🟡 **Reconnecting**: Brief connection loss (auto-reconnects)
- 🔴 **Disconnected**: Manual refresh needed (rare)

## For Drivers

### 1. Accepting/Declining Rides (Live)

When dispatcher assigns you a ride:
1. Notification appears on your phone instantly
2. "Accept" or "Decline" button
3. Your response updates dispatcher board immediately

**What happens when you accept:**
- Your status changes to "Assigned"
- Ride moves to your "Current Rides" section
- Dispatcher sees you accepted instantly

### 2. Status Changes (Live)

When you change your status (Online/Offline/On Break):
- Dispatcher board updates instantly
- Shows your availability in real-time
- Affects whether you receive new ride assignments

### 3. Tracking Your Ride

Once assigned to a ride:
- See estimated pickup time
- See passenger details
- Track completion status live
- Activity logs show your progress

## For Admins

### 1. Monitoring Real-Time System

Check system health:
```bash
# View activity feed
GET /api/health-isf/activity-feed

# Monitor WebSocket connections
GET /api/health-isf/status

# Query event logs
SELECT COUNT(*) FROM health_isf_realtime_events WHERE created_at > NOW() - INTERVAL '1 hour';
```

### 2. Troubleshooting

**Problem: Live updates not appearing**
- Check connection status indicator (should be 🟢)
- Try refreshing page
- Check browser console for errors
- Verify WebSocket port 8000 is not blocked

**Problem: Rides locked for too long**
- Check database for expired locks:
  ```sql
  SELECT * FROM health_isf_assignment_locks 
  WHERE expires_at < NOW();
  ```
- Delete stale locks if needed

**Problem: Missing activity logs**
- Check dispatcher_activity table is not full:
  ```sql
  SELECT COUNT(*) FROM health_isf_dispatcher_activity;
  ```
- Archive old entries if needed (> 30 days)

## Technical Integration

### For Frontend Developers

#### Subscribe to Live Updates

```javascript
const ws = new WebSocket(
  `ws://localhost:8000/api/health-isf/ws/live/org_123/user_456?role=dispatcher`
);

// Connect
ws.onopen = () => {
  console.log('Connected to live updates');
  
  // Subscribe to dispatcher board events
  ws.send(JSON.stringify({
    type: 'subscribe',
    subscription_type: 'dispatcher_board'
  }));
};

// Receive events
ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log('Event received:', message.event_type);
  
  if (message.event_type === 'ride_assigned') {
    updateRideUI(message.payload);
  } else if (message.event_type === 'driver_status_changed') {
    updateDriverUI(message.payload);
  }
};

// Keep connection alive
setInterval(() => {
  ws.send(JSON.stringify({ type: 'ping' }));
}, 30000);

// Handle disconnect
ws.onclose = () => {
  console.log('Disconnected, will retry...');
  setTimeout(reconnect, 3000);
};
```

#### Event Types to Handle

```javascript
{
  type: 'event',
  event_type: 'ride_status_changed',
  payload: {
    ride_id: 'ride_123',
    from_status: 'pending',
    to_status: 'accepted',
    timestamp: '2026-05-17T20:30:00Z'
  }
}

{
  type: 'event',
  event_type: 'ride_assigned',
  payload: {
    ride_id: 'ride_123',
    driver_id: 'driver_456',
    driver_name: 'John Smith',
    timestamp: '2026-05-17T20:31:00Z'
  }
}

{
  type: 'event',
  event_type: 'driver_status_changed',
  payload: {
    driver_id: 'driver_456',
    from_status: 'available',
    to_status: 'assigned',
    driver_name: 'John Smith',
    timestamp: '2026-05-17T20:31:05Z'
  }
}
```

### For Backend Developers

#### Emit Custom Events

```python
from app.modules.health_isf.realtime import get_emitter, get_broadcaster

emitter = get_emitter()
broadcaster = get_broadcaster()

# Emit ride status changed
asyncio.create_task(
    emitter.emit_ride_status_changed(
        organization_id='org_123',
        ride_id='ride_456',
        from_status='pending',
        to_status='accepted',
        actor_user_id='dispatcher_789'
    )
)

# Emit custom event
await broadcaster.broadcast_event(
    event_type='custom_event',
    payload={'key': 'value'},
    organization_id='org_123',
    subscription_types=['dispatcher_board']
)
```

#### Check Concurrent Assignment Lock

```python
from app.modules.health_isf.realtime_service import ConcurrentAssignmentService

# Check if ride is locked
if ConcurrentAssignmentService.has_assignment_lock(db, ride_id):
    raise HTTPException(status_code=409, detail="Ride is locked")

# Acquire lock
lock = ConcurrentAssignmentService.acquire_assignment_lock(
    db, ride_id=ride_id, user_id=user_id, lock_duration_seconds=30
)

try:
    # Do assignment work
    assign_ride(db, ride_id, driver_id)
finally:
    # Always release lock
    ConcurrentAssignmentService.release_assignment_lock(db, ride_id)
```

## Performance Tips

### For Dispatchers
- Keep dashboard open during busy hours (reusing connection is efficient)
- Close unused tabs to reduce WebSocket connections
- Avoid assigning same ride twice (lock prevents double-assign anyway)

### For Drivers
- Keep app alive when accepting rides
- Mobile app auto-reconnects if connection drops
- Longer vehicle journeys = minimal impact

### For Admins
- Monitor WebSocket connection count
- Archive old events weekly (keeps DB fast)
- Use indexes for analytics queries

## FAQ

**Q: What if the internet goes out?**
A: WebSocket will show 🔴 Disconnected. Data remains in database. App auto-reconnects when internet returns.

**Q: Can two dispatchers assign the same ride?**
A: No. Lock mechanism prevents this. If both try simultaneously, one gets 409 and must retry.

**Q: How long does assignment lock last?**
A: 30 seconds by default. If dispatcher crashes, lock expires automatically and another can try.

**Q: What happens to old events?**
A: Events older than 7 days are archived (moved or deleted). Activity logs kept 30 days.

**Q: Can I see historical events?**
A: Yes, via /api/health-isf/activity-feed endpoint. Shows recent actions.

**Q: Is real-time included in pricing?**
A: Yes, real-time events and WebSocket updates are included in standard Health ISF license.

## Support

- **Dashboard not updating?** Check connection indicator, refresh page
- **Can't assign ride?** Check for concurrent lock (wait 30 seconds if needed)
- **WebSocket errors?** Check network, verify port 8000 not blocked
- **Database performance slow?** Archive old events (admin task)

---

**Last Updated**: May 17, 2026  
**Status**: Ready for Production Use ✓
