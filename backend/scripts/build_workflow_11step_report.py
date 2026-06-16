import json
from pathlib import Path

base = Path(r"C:\Users\smoni\OneDrive\New folder\New folder\Amicore_Rebuild")
results_path = base / "evidence/workflow_11step/workflow_11step_results.json"
out_path = base / "evidence/workflow_11step/WORKFLOW_11STEP_FINAL_REPORT.md"

data = json.loads(results_path.read_text(encoding="utf-8"))

lines = []
lines.append("# End-to-End Transportation Workflow Lifecycle Report")
lines.append("")
lines.append(f"Generated: {data.get('generated_at')}")
lines.append(f"Runtime: {data.get('base_url')}")
lines.append(f"Ride ID: {data.get('ride_id')}")
lines.append(f"Request ID: {data.get('request_id')}")
lines.append(f"Driver ID: {data.get('driver_id')}")
lines.append("")
lines.append("## Final Verdict")
lines.append(f"- Overall: {'PASS' if data.get('all_passed') else 'FAIL'}")
lines.append(f"- Passed steps: {data.get('passed_steps')}/{data.get('total_steps')}")
lines.append("")

for step in data.get("steps", []):
    n = step.get("step")
    name = step.get("name")
    lines.append(f"## Step {n}: {name}")
    lines.append(f"- PASS/FAIL: {'PASS' if step.get('passed') else 'FAIL'}")
    lines.append(f"- Screenshot: {step.get('screenshot')}")

    api = step.get("api", {})
    lines.append("- API Evidence:")
    lines.append(f"  - Method: {api.get('method')}")
    lines.append(f"  - Path: {api.get('path')}")
    lines.append(f"  - Status: {api.get('status')}")
    lines.append(f"  - Response Summary: {json.dumps(api.get('response'), ensure_ascii=True)}")

    db = step.get("db", {})
    ride = db.get("ride") or {}
    req_row = db.get("customer_request") or {}
    assignments = db.get("assignments") or []
    lines.append("- Database Evidence:")
    lines.append(f"  - customer_request.dispatch_status: {req_row.get('dispatch_status')}")
    lines.append(f"  - ride.status: {ride.get('status')}")
    lines.append(f"  - ride.lifecycle_state: {ride.get('lifecycle_state')}")
    lines.append(f"  - ride.driver_id: {ride.get('driver_id')}")
    lines.append(f"  - assignments(latest up to 3): {json.dumps(assignments, ensure_ascii=True)}")
    lines.append("")

lines.append("## Evidence Files")
lines.append("- JSON results: evidence/workflow_11step/workflow_11step_results.json")
lines.append("- Screenshots: evidence/workflow_11step/step_01.png through step_11.png")

out_path.write_text("\n".join(lines), encoding="utf-8")
print(out_path)
