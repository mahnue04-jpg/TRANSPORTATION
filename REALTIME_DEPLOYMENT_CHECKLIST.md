# Real-Time Dispatch Operations - Deployment Checklist

## Pre-Deployment Validation

- [ ] All tests passing: `pytest backend/tests/test_health_isf_realtime.py -v`
- [ ] Code review completed
- [ ] Database backup created
- [ ] Downtime window scheduled (if needed)

## Database Migration

- [ ] Run migration: `cd backend && alembic upgrade head`
- [ ] Verify tables created:
  ```sql
  SELECT COUNT(*) FROM information_schema.tables 
  WHERE table_name IN ('health_isf_realtime_events', 'health_isf_dispatcher_activity', 'health_isf_assignment_locks');
  ```
- [ ] Verify columns added:
  ```sql
  SELECT COUNT(*) FROM information_schema.columns 
  WHERE table_name IN ('health_isf_rides', 'health_isf_drivers') AND column_name = 'version';
  ```

## Application Deployment

- [ ] Pull latest code
- [ ] Install dependencies: `pip install -r backend/requirements.txt`
- [ ] Run tests: `pytest backend/tests/test_health_isf_realtime.py`
- [ ] Start application: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- [ ] Verify startup logs show: `"Real-time dispatch operations infrastructure initialized"`

## Smoke Tests

### WebSocket Connection
```bash
# Connect to WebSocket
wscat -c "ws://localhost:8000/api/health-isf/ws/live/org_1/user_1?role=dispatcher"

# Send subscribe message
{"type": "subscribe", "subscription_type": "dispatcher_board"}

# Should receive confirmation
```

### Activity Feed
```bash
# Retrieve activity feed
curl -H "Authorization: Bearer <token>" \
  "http://localhost:8000/api/health-isf/activity-feed?skip=0&limit=10"

# Should return 200 OK with activity entries
```

### Ride Assignment (with Lock)
```bash
# Assign ride to driver
curl -X PATCH \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"driver_id": "driver_1"}' \
  "http://localhost:8000/api/health-isf/rides/ride_1/assign-driver"

# Should return 200 OK
# Check that event was logged: SELECT COUNT(*) FROM health_isf_realtime_events;
```

## Monitoring Setup

### Database Queries to Monitor

```sql
-- Active locks count
SELECT COUNT(*) as active_locks FROM health_isf_assignment_locks 
WHERE expires_at > NOW();

-- Recent events (last 5 minutes)
SELECT COUNT(*) as recent_events FROM health_isf_realtime_events 
WHERE created_at > DATE_SUB(NOW(), INTERVAL 5 MINUTE);

-- Activity log entries (last hour)
SELECT COUNT(*) as recent_activities FROM health_isf_dispatcher_activity 
WHERE created_at > DATE_SUB(NOW(), INTERVAL 1 HOUR);
```

### Application Logs to Monitor

```
Level: INFO
- "Real-time dispatch operations infrastructure initialized" (startup)
- "Connection registered: <id> for org <org_id>" (WebSocket connect)
- "Emitted ride_assigned: <ride_id> -> <driver_id>" (events)
- "Logged activity: <action>" (activity logging)

Level: WARNING
- "Lock already exists for ride <ride_id>" (concurrent assignment attempt)
- "Cleaned up stale connection: <id>" (connection cleanup)

Level: ERROR
- "Real-time infrastructure init failed" (startup issue)
- "Error sending message: <error>" (WebSocket send error)
```

## Post-Deployment Validation

- [ ] No errors in application logs (check for ERROR level messages)
- [ ] WebSocket connections working (test in browser console)
- [ ] Activity feed returning entries
- [ ] Concurrent assignment protection active (test with 2 dispatchers)
- [ ] Events being logged (query realtime_events table)
- [ ] Database performance normal (check query times)

## Rollback Plan (if needed)

If serious issues occur:
```bash
# 1. Stop application
sudo systemctl stop amicor

# 2. Rollback database migration
cd backend
alembic downgrade -1

# 3. Deploy previous version
git checkout <previous-tag>
pip install -r backend/requirements.txt

# 4. Restart application
sudo systemctl start amicor

# 5. Verify restored
curl http://localhost:8000/api/health-isf/status
```

## Maintenance Schedule

### Immediate (After Deployment)
- Monitor application logs for 2 hours
- Check WebSocket connection stability
- Verify concurrent assignment locks working

### Daily
- Monitor database table sizes
- Check for stale locks: `SELECT * FROM health_isf_assignment_locks WHERE expires_at < NOW();`
- Archive old events if using scheduled job

### Weekly
- Review real-time event patterns
- Check WebSocket connection statistics
- Analyze activity log for unusual patterns

### Monthly
- Archive events older than 7 days
- Archive activity logs older than 30 days
- Review performance metrics
- Analyze lock contention patterns

## Feature Flags (Optional)

If you want to gradually roll out real-time features:

```python
# In app config
REALTIME_ENABLED = os.environ.get("REALTIME_ENABLED", "true").lower() == "true"

# In routes
if REALTIME_ENABLED:
    # Emit events and use locks
    await emitter.emit_ride_assigned(...)
    broadcaster.broadcast_event(...)
```

## Support Contacts

- Database Team: [contact info]
- DevOps Team: [contact info]
- Engineering Lead: [contact info]

---

**Status**: Ready for Production Deployment ✓
