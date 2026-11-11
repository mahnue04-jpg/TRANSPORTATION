"""Invented records for offline demonstrations; no real calls or organizations."""
from copy import deepcopy


def build_fixture():
    bundle = {"project_id": "DEMO-INTAKE-EVALUATION", "synthetic": True, "calls": [], "transcripts": [], "transfers": [], "matters": []}
    for site, channel, completed in [("DEMO_TENNESSEE", "AI", 6), ("DEMO_TENNESSEE", "TRADITIONAL", 5), ("DEMO_FLORIDA", "AI", 5), ("DEMO_FLORIDA", "TRADITIONAL", 6)]:
        for i in range(8):
            cid = f"DEMO-{site}-{channel}-{i+1:02d}"
            status = "ineligible" if i == 7 else "completed" if i < completed else "abandoned"
            language = "English" if i % 2 == 0 else "Spanish"
            county = "DEMO_COUNTY_A" if site == "DEMO_TENNESSEE" else "DEMO_COUNTY_B"
            start = f"2026-10-{10+i:02d}T12:00:00+00:00"
            end = f"2026-10-{10+i:02d}T12:{5+i:02d}:00+00:00"
            call = {"record_id": cid+"-ROW", "site": site, "call_id": cid, "channel": channel, "started": start, "ended": end, "status": status, "handoff_requested": status == "completed", "complete_fields": i != 2, "staff_minutes": (3+i if channel == "AI" else 9+i), "language": language, "transcript_id": cid+"-TRANSCRIPT", "captured_county": county}
            if site == "DEMO_TENNESSEE" and channel == "AI" and i == 0: call["captured_county"] = "DEMO_COUNTY_WRONG"
            # Florida has a genuine fictional capture error, also present in the raw matter.
            if site == "DEMO_FLORIDA" and channel == "AI" and i == 2: call["captured_county"] = "DEMO_COUNTY_WRONG"
            if site == "DEMO_FLORIDA" and channel == "AI" and i == 1: call["staff_minutes"] = None
            bundle["calls"].append(call)
            bundle["transcripts"].append({"id": cid+"-TRANSCRIPT", "record_id": cid+"-TRANSCRIPT-ROW", "site": site, "call_id": cid, "text": f"Fictional caller states county {county}. Language {language}. No real caller or audio.", "reference_fields": {"county": county, "language": language}, "reference_provenance": "INVENTED_FIXTURE_TRUTH_NOT_HUMAN_ANNOTATION"})
            if call["handoff_requested"]:
                success = i != 3
                bundle["transfers"].append({"id": cid+"-TRANSFER", "record_id": cid+"-TRANSFER-ROW", "site": site, "call_id": cid, "status": "succeeded" if success else "failed", "matter_id": cid+"-MATTER" if success else None})
                if success: bundle["matters"].append({"id": cid+"-MATTER", "record_id": cid+"-MATTER-ROW", "site": site, "call_id": cid, "source": "FICTIONAL_LEGALSERVER_EXPORT", "recorded_fields": {"captured_county": call["captured_county"] if site == "DEMO_FLORIDA" else county}})
    return bundle


def inject_errors(bundle):
    bad = deepcopy(bundle)
    # Repeated import of the same call, versus a conflicting version of another.
    duplicate = deepcopy(bad["calls"][0]);duplicate["record_id"] = "DEMO-REPEATED-IMPORT";bad["calls"].append(duplicate)
    conflict = deepcopy(bad["calls"][7]);conflict["record_id"] = "DEMO-CONFLICT";conflict["status"] = "completed";bad["calls"].append(conflict)
    bad["calls"][16]["ended"] = "2026-10-10T11:00:00+00:00"
    bad["calls"][24]["staff_minutes"] = -1
    bad["calls"][8]["transcript_id"] = bad["calls"][25]["transcript_id"]
    bad["calls"][10]["complete_fields"] = "false"
    bad["transfers"][0]["matter_id"] = "DEMO-NONEXISTENT-MATTER"
    bad["transfers"].append({"id":"DEMO-ORPHAN", "record_id":"DEMO-ORPHAN-ROW", "site":"DEMO_FLORIDA", "call_id":"DEMO-NO-CALL", "status":"failed", "matter_id":None})
    return bad
