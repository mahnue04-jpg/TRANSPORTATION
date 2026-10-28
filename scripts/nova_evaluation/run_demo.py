"""Run the isolated synthetic readiness proof without any production services."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend/app/core/nova"))
from evaluation.engine import correct_fixture, digest, evaluate, render_site_report
from evaluation.fixtures import build_fixture, inject_errors


def run(output):
    output = Path(output);output.mkdir(parents=True, exist_ok=True)
    source = build_fixture()
    bad = inject_errors(source)
    blocked = evaluate(bad)
    initial = evaluate(source)
    row = source["calls"][0]
    corrected, review = correct_fixture(source, expected_input_sha256=digest(source), record_id=row["record_id"], field="captured_county", old_value="DEMO_COUNTY_WRONG", new_value="DEMO_COUNTY_A", reason="Simulated reviewer repairs imported analysis-table value against original fictional matter export. The raw export and genuine Florida capture error are unchanged. No actual human reviewed.", evidence_ref=source["matters"][0]["record_id"])
    final = evaluate(corrected)
    for name, value in [("input_v1.json",source),("input_with_injected_errors.json",bad),("blocked_error_run.json",blocked),("analysis_v1.json",initial),("input_v2.json",corrected),("simulated_review_event.json",review),("analysis_v2.json",final)]:
        (output/name).write_text(json.dumps(value,indent=2,allow_nan=False)+"\n")
    for version, result in [("v1", initial), ("v2", final)]:
        for site in sorted(result["sites"]):
            (output/f"{site}_{version}.html").write_text(render_site_report(result,site))
    summary = {"synthetic":True,"valid_calls":initial["valid_call_count"],"deliberate_error_run_status":blocked["status"],"error_codes_caught":sorted({i["code"] for i in blocked["issues"]}),"blocking_issue_count":len(blocked["issues"]),"repeated_imports_collapsed":len(blocked["duplicate_calls_collapsed"]),"before_correction":initial["sites"]["DEMO_TENNESSEE"]["cohorts"]["AI"]["metrics"]["county_accuracy"],"after_correction":final["sites"]["DEMO_TENNESSEE"]["cohorts"]["AI"]["metrics"]["county_accuracy"],"initial_snapshot":initial["input_sha256"],"corrected_snapshot":final["input_sha256"],"final_status":final["status"],"approved_for_client_delivery":False,"actual_human_review":False,"external_calls":0,"live_client_data_used":False}
    (output/"demo_summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    (output/"START_HERE.txt").write_text("NOVA SYNTHETIC EVALUATION READINESS DEMO\n\nAll calls, transcripts, transfer records and matters are invented.\nOpen the two v2 HTML site reports, then demo_summary.json.\nThe v1 reports preserve the initial county mismatch.\nThe error run quarantines malformed/conflicting evidence and blocks release.\nA simulated reviewer correction creates v2; no actual human approved it.\nanalysis_v1.json and analysis_v2.json contain formulas, source row references, source records and SHA-256 hashes.\nNo real telephony, LegalServer connection or production deployment was tested.\n")
    return summary


if __name__ == "__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",required=True)
    print(json.dumps(run(parser.parse_args().output),indent=2))
