#!/usr/bin/env python3
import sys
sys.path.insert(0, 'backend')

from sqlalchemy import create_engine
from app.models import CustomerRideRequest
from sqlalchemy.orm import sessionmaker

# Create database connection
engine = create_engine("sqlite:///./backend/pilot_a4_clean.db")
Session = sessionmaker(bind=engine)
session = Session()

# Query the most recent ride requests
requests = session.query(CustomerRideRequest).order_by(CustomerRideRequest.created_at.desc()).limit(5).all()

print("=== Most Recent Ride Requests ===\n")
for req in requests:
    print(f"ID: {req.id}")
    print(f"Ride ID: {req.ride_id}")
    print(f"Rider: {req.rider_name} ({req.rider_phone})")
    print(f"Pickup: {req.pickup_address}")
    print(f"Dropoff: {req.dropoff_address}")
    print(f"Status: {req.dispatch_status}")
    print(f"Created: {req.created_at}")
    print()

session.close()
print(f"Total records found: {len(requests)}")
