import json
from pathlib import Path

p = Path("evidence/state_propagation/state_propagation_16deda2c-f544-45a8-b35f-5677e26bf196.json")
obj = json.loads(p.read_text(encoding="utf-8"))

print("ride_id=", obj["ids"]["ride_id"])
print("request_id=", obj["ids"]["request_id"])
print("driver_id=", obj["ids"]["driver_id"])
print("offer_id=", obj["ids"]["offer_id"])
print("\nSTATE_SUMMARY")
for s in obj["steps"]:
    name = s["state"]
    t = s["transition_api"]
    ride_payload = s["view_verification"]["ride"]["payload"] if isinstance(s["view_verification"]["ride"]["payload"], dict) else {}
    lifecycle = ride_payload.get("lifecycle_state")
    status = ride_payload.get("status")
    riders_match = bool(s["view_verification"]["riders"].get("match"))
    drivers_match = bool(s["view_verification"]["drivers"].get("match"))
    dispatch_match = bool(s["view_verification"]["dispatch"].get("match"))
    print(f"- {name}: transition={t.get('status')} lifecycle={lifecycle} status={status} riders_match={riders_match} drivers_match={drivers_match} dispatch_match={dispatch_match}")

print("\nTRANSITION_PAYLOADS")
for s in obj["steps"]:
    print(s["state"], "=>", json.dumps(s["transition_api"], ensure_ascii=False))
