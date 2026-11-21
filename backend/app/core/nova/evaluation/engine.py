"""Deterministic, synthetic-only intake evaluation and review evidence.

No network, LLM, client system, database, approval grant or financial action.
Caller authentication, encrypted storage and real reviewer authority belong to a
future integration, not to this offline demonstration. Fixture flags are not DLP.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime
import hashlib
import html
import json
import math
from statistics import median
from typing import Any

VERSION = "nova-evaluation-demo-v1"
SITES = {"DEMO_TENNESSEE", "DEMO_FLORIDA"}
CHANNELS = {"AI", "TRADITIONAL"}
STATUSES = {"completed", "abandoned", "ineligible"}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be text")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timezone required")
    return result


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _require_fixture(bundle: dict[str, Any]) -> None:
    if bundle.get("synthetic") is not True or not str(bundle.get("project_id", "")).startswith("DEMO-"):
        raise ValueError("Synthetic demonstration only; real client inputs are not supported")
    if not isinstance(bundle.get("calls"), list) or not bundle["calls"]:
        raise ValueError("Nonempty calls list required")
    for name in ("transcripts", "transfers", "matters"):
        if not isinstance(bundle.get(name), list):
            raise ValueError(f"{name} list required")


def evaluate(bundle: dict[str, Any]) -> dict[str, Any]:
    """Calculate evidence-bearing descriptive measures, retaining every exclusion."""
    _require_fixture(bundle)
    issues: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}

    def issue(code: str, refs: list[str], detail: str) -> None:
        issues.append({"code": code, "source_refs": refs, "detail": detail, "severity": "BLOCKING"})

    all_ids: set[str] = set()
    raw_calls = []
    for row_index, row in enumerate(bundle["calls"], 1):
        if not isinstance(row, dict):
            issue("INVALID_RECORD", [f"calls:row:{row_index}"], "Object required")
            continue
        ref = row.get("record_id")
        if not isinstance(ref, str) or not ref.startswith("DEMO-") or ref in all_ids:
            issue("INVALID_SOURCE_ID", [f"calls:row:{row_index}"], "Unique DEMO record_id required")
            continue
        all_ids.add(ref)
        evidence[ref] = {"source": "calls", "row": row_index, "sha256": digest(row), "record": deepcopy(row)}
        raw_calls.append(row)

    def index_records(name: str) -> tuple[dict[str, dict], set[str]]:
        groups: dict[str, list] = defaultdict(list)
        for i, row in enumerate(bundle[name], 1):
            ref = row.get("record_id") if isinstance(row, dict) else None
            if not isinstance(ref, str) or not ref.startswith("DEMO-") or ref in all_ids:
                issue("INVALID_SOURCE_ID", [f"{name}:row:{i}"], "Unique DEMO record_id required")
                continue
            all_ids.add(ref)
            evidence[ref] = {"source": name, "row": i, "sha256": digest(row), "record": deepcopy(row)}
            entity_id = row.get("id")
            if not isinstance(entity_id, str) or not entity_id.startswith("DEMO-"):
                issue("INVALID_ENTITY_ID", [ref], "DEMO id required")
                continue
            groups[entity_id].append(row)
        invalid = {key for key, rows in groups.items() if len(rows) != 1}
        for key in sorted(invalid):
            issue("DUPLICATE_EVIDENCE_ID", [r["record_id"] for r in groups[key]], key)
        return {key: rows[0] for key, rows in groups.items() if key not in invalid}, invalid

    transcripts, _ = index_records("transcripts")
    transfers, _ = index_records("transfers")
    matters, _ = index_records("matters")
    call_groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in raw_calls:
        key = (row.get("site"), row.get("call_id"))
        if not isinstance(row.get("site"), str) or row["site"] not in SITES or not isinstance(row.get("call_id"), str) or not row["call_id"].startswith("DEMO-"):
            issue("INVALID_CALL_IDENTITY", [row["record_id"]], "Valid site and DEMO call id required")
            continue
        call_groups[key].append(row)

    calls = []
    duplicates = []
    for key, rows in sorted(call_groups.items()):
        fingerprints = {digest({k: v for k, v in r.items() if k != "record_id"}) for r in rows}
        refs = [r["record_id"] for r in rows]
        if len(fingerprints) != 1:
            issue("CONFLICTING_CALL_ID", refs, "Conflicting versions excluded; no latest-row-wins rule")
            continue
        row = rows[0]
        errors = []
        if not isinstance(row.get("channel"), str) or row["channel"] not in CHANNELS: errors.append("channel")
        if not isinstance(row.get("status"), str) or row["status"] not in STATUSES: errors.append("status")
        if not isinstance(row.get("transcript_id"), str): errors.append("transcript_id")
        if type(row.get("handoff_requested")) is not bool: errors.append("handoff_requested")
        if row.get("complete_fields") is not None and type(row.get("complete_fields")) is not bool: errors.append("complete_fields")
        if row.get("staff_minutes") is not None and not _number(row["staff_minutes"]): errors.append("staff_minutes")
        if not isinstance(row.get("language"), str) or not row["language"]: errors.append("language")
        try:
            duration = (_time(row.get("ended")) - _time(row.get("started"))).total_seconds()
            if duration < 0: errors.append("reversed_time")
        except (TypeError, ValueError):
            errors.append("invalid_timestamp")
            duration = None
        if errors:
            issue("INVALID_CALL_FIELDS", refs, ",".join(errors))
            continue
        if len(rows) > 1:
            duplicates.append({"site": key[0], "call_id": key[1], "retained_ref": refs[0], "duplicate_refs": refs[1:]})
        calls.append({**row, "source_refs": refs, "duration_seconds": duration})

    call_lookup = {(c["site"], c["call_id"]): c for c in calls}
    handoffs: dict[tuple, list] = defaultdict(list)
    for transfer in transfers.values():
        key = (transfer.get("site"), transfer.get("call_id"))
        if not all(isinstance(v, str) for v in key):
            issue("ORPHAN_TRANSFER", [transfer["record_id"]], "Text site and call id required")
            continue
        if key not in call_lookup or not call_lookup[key]["handoff_requested"]:
            issue("ORPHAN_TRANSFER", [transfer["record_id"]], "Transfer has no valid requesting call")
            continue
        handoffs[key].append(transfer)

    for matter in matters.values():
        key = (matter.get("site"), matter.get("call_id"))
        if not all(isinstance(v, str) for v in key) or key not in call_lookup:
            issue("ORPHAN_MATTER", [matter["record_id"]], "Matter has no valid call")

    linked = []
    findings = []
    for call in calls:
        refs = list(call["source_refs"])
        transcript = transcripts.get(call.get("transcript_id"))
        truth = None
        if transcript is None or (transcript.get("site"), transcript.get("call_id")) != (call["site"], call["call_id"]):
            issue("TRANSCRIPT_LINK", refs, "Missing transcript or site/call mismatch")
        elif not isinstance(transcript.get("text"), str) or not transcript["text"].strip() or not isinstance(transcript.get("reference_fields"), dict):
            issue("INVALID_REFERENCE", [transcript["record_id"]], "Transcript text and fixture reference fields required")
        else:
            refs.append(transcript["record_id"])
            truth = transcript["reference_fields"]
            if call["status"] == "completed" and "county" in truth and call.get("captured_county") != truth["county"]:
                findings.append({"code": "FIELD_MISMATCH", "field": "captured_county", "site": call["site"], "call_id": call["call_id"], "observed": call.get("captured_county"), "reference": truth["county"], "source_refs": list(refs), "review_required": True, "reference_kind": "INVENTED_FIXTURE_TRUTH"})
        transfer_success = False
        transfer_rows = handoffs.get((call["site"], call["call_id"]), [])
        if call["handoff_requested"] and len(transfer_rows) != 1:
            issue("TRANSFER_CARDINALITY", refs, "Exactly one terminal transfer record required per requesting call")
        for tr in transfer_rows:
            refs.append(tr["record_id"])
            if not isinstance(tr.get("status"), str) or tr["status"] not in {"succeeded", "failed"}:
                issue("INVALID_TRANSFER_STATUS", [tr["record_id"]], "Terminal status required")
            if tr.get("status") == "succeeded":
                matter = matters.get(tr.get("matter_id")) if isinstance(tr.get("matter_id"), str) else None
                if not matter or (matter.get("site"), matter.get("call_id")) != (call["site"], call["call_id"]):
                    issue("MATTER_LINK", [tr["record_id"]], "Successful transfer needs matching matter evidence")
                else:
                    refs.append(matter["record_id"])
                    transfer_success = len(transfer_rows) == 1
        linked.append({**call, "reference_fields": truth, "transfer_succeeded": transfer_success, "evidence_refs": refs})

    def measure(name: str, cohort: list[dict], predicate, applicable=lambda c: True) -> dict:
        applicable_calls = [c for c in cohort if applicable(c)]
        positives = [c for c in applicable_calls if predicate(c)]
        def refs(rows):
            return sorted({ref for c in rows for ref in c["evidence_refs"]})
        return {"name": name, "numerator": len(positives), "denominator": len(applicable_calls),
                "value": len(positives) / len(applicable_calls) if applicable_calls else None,
                "numerator_refs": refs(positives), "denominator_refs": refs(applicable_calls),
                "excluded_call_refs": refs([c for c in cohort if not applicable(c)])}

    results = {}
    for site in sorted(SITES):
        site_calls = [c for c in linked if c["site"] == site]
        results[site] = {"cohorts": {}, "comparison": {}, "language_strata": {}}
        for channel in sorted(CHANNELS):
            cohort = [c for c in site_calls if c["channel"] == channel]
            eligible = lambda c: c["status"] != "ineligible"
            m = {
                "completion": measure("completion", cohort, lambda c: c["status"] == "completed", eligible),
                "abandonment": measure("abandonment", cohort, lambda c: c["status"] == "abandoned", eligible),
                "field_completeness": measure("field_completeness", cohort, lambda c: c["complete_fields"] is True,
                    lambda c: c["status"] == "completed" and c["complete_fields"] is not None),
                "county_accuracy": measure("county_accuracy", cohort,
                    lambda c: c.get("captured_county") == c["reference_fields"]["county"],
                    lambda c: c["status"] == "completed" and c["reference_fields"] is not None and "county" in c["reference_fields"]),
                "handoff_success": measure("handoff_success", cohort, lambda c: c["transfer_succeeded"], lambda c: c["handoff_requested"]),
            }
            staff_calls = [c for c in cohort if eligible(c) and c["staff_minutes"] is not None]
            m["staff_minutes_per_eligible_call"] = {"name": "staff_minutes_per_eligible_call", "numerator": sum(c["staff_minutes"] for c in staff_calls), "denominator": len(staff_calls), "value": sum(c["staff_minutes"] for c in staff_calls)/len(staff_calls) if staff_calls else None,
                "numerator_refs": sorted(r for c in staff_calls for r in c["source_refs"]), "denominator_refs": sorted(r for c in staff_calls for r in c["source_refs"]),
                "excluded_call_refs": sorted(r for c in cohort if eligible(c) and c["staff_minutes"] is None for r in c["source_refs"])}
            duration_calls = [c for c in cohort if c["status"] == "completed"]
            m["median_completed_call_seconds"] = {"name": "median_completed_call_seconds", "value": median(c["duration_seconds"] for c in duration_calls) if duration_calls else None, "sample_count": len(duration_calls), "observations": [{"seconds": c["duration_seconds"], "source_refs": c["source_refs"]} for c in duration_calls]}
            results[site]["cohorts"][channel] = {"call_count": len(cohort), "call_refs": sorted(r for c in cohort for r in c["source_refs"]), "ineligible_count": sum(c["status"] == "ineligible" for c in cohort), "ineligible_refs": sorted(r for c in cohort if c["status"] == "ineligible" for r in c["source_refs"]), "metrics": m}
            for language in sorted({c["language"] for c in cohort}):
                subset = [c for c in cohort if c["language"] == language and eligible(c)]
                results[site]["language_strata"][channel+":"+language] = {"n": len(subset), "completion_rate": sum(c["status"] == "completed" for c in subset)/len(subset) if len(subset) >= 5 else None, "suppressed": len(subset) < 5, "minimum_n": 5, "source_refs": sorted(r for c in subset for r in c["source_refs"])}
        for metric in ("completion", "abandonment", "county_accuracy", "handoff_success", "staff_minutes_per_eligible_call"):
            a = results[site]["cohorts"]["AI"]["metrics"][metric]
            b = results[site]["cohorts"]["TRADITIONAL"]["metrics"][metric]
            results[site]["comparison"][metric] = {"ai_minus_traditional": a["value"]-b["value"] if a["value"] is not None and b["value"] is not None else None, "metric_refs": [f"{site}/AI/{metric}", f"{site}/TRADITIONAL/{metric}"], "interpretation": "Descriptive synthetic comparison; no causal, significance, population or fairness claim."}
    return {"engine_version": VERSION, "project_id": bundle["project_id"], "synthetic": True,
            "input_sha256": digest(bundle), "source_manifest": evidence, "sites": results,
            "issues": issues, "findings": findings, "duplicate_calls_collapsed": duplicates, "valid_call_count": len(calls),
            "status": "BLOCKED_DATA_QUALITY" if issues else "AWAITING_HUMAN_REVIEW",
            "approved_for_client_delivery": False,
            "limitations": ["Synthetic records and structured fixture reference fields; no audio transcription or semantic truth verification.", "No real LegalServer, telephony or customer system integration.", "No approved sampling, interviews, accessibility study, causal inference or client-data security validation.", "No actual human review or approval has occurred; approval is never granted by this module."]}


def correct_fixture(bundle: dict, *, expected_input_sha256: str, record_id: str, field: str,
                    old_value: Any, new_value: Any, reason: str, evidence_ref: str) -> tuple[dict, dict]:
    """Immutable simulated reviewer correction with stale-version and evidence checks.

    A future authenticated integration must supply real review provenance. This
    function cannot record actual owner approval and deliberately labels simulation.
    """
    _require_fixture(bundle)
    if digest(bundle) != expected_input_sha256: raise ValueError("Stale review version")
    if field not in {"captured_county", "status", "complete_fields", "staff_minutes"}: raise ValueError("Field is not review-editable")
    if not reason.strip(): raise ValueError("Correction reason required")
    updated = deepcopy(bundle)
    rows = [r for r in updated["calls"] if r.get("record_id") == record_id]
    if len(rows) != 1 or rows[0].get(field) != old_value: raise ValueError("Record or old value mismatch")
    references = [r for r in updated["matters"] if r.get("record_id") == evidence_ref]
    if len(references) != 1 or (references[0].get("site"),references[0].get("call_id")) != (rows[0].get("site"),rows[0].get("call_id")): raise ValueError("Correction evidence must belong to the same site and call")
    if references[0].get("recorded_fields", {}).get(field) != new_value:
        raise ValueError("Import correction must match the raw source value, not a desired outcome")
    rows[0][field] = new_value
    return updated, {"event": "SIMULATED_IMPORT_MAPPING_CORRECTION", "actor": "DEMO_REVIEWER_SIMULATED", "record_id": record_id, "field": field, "old_value": old_value, "new_value": new_value, "reason": reason, "evidence_ref": evidence_ref, "previous_sha256": digest(bundle), "new_sha256": digest(updated), "real_human_approval": False}


def render_site_report(result: dict, site: str) -> str:
    """Static, escaped report; every cell links to downloadable JSON evidence."""
    if site not in result["sites"]: raise ValueError("Unknown site")
    e = html.escape
    rows = []
    for channel, cohort in result["sites"][site]["cohorts"].items():
        for metric, value in cohort["metrics"].items():
            shown = "Not available" if value["value"] is None else f'{value["value"]:.4f}'
            fraction = f'{value["numerator"]}/{value["denominator"]}' if "numerator" in value else f'n={value["sample_count"]}'
            trace = e(json.dumps(value, sort_keys=True))
            rows.append(f'<tr><td>{e(channel)}</td><td>{e(metric)}</td><td>{shown}</td><td>{fraction}</td><td><details><summary>Source trace</summary><pre>{trace}</pre></details></td></tr>')
    return '<!doctype html><meta charset="utf-8"><title>Nova synthetic evaluation</title><style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:16px;color:#142536}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd4db;padding:9px;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}h1{font-size:26px}</style>' + f'<h1>{e(site)} evaluation demonstration</h1><p><strong>FICTIONAL DATA ONLY — {e(result["status"])}</strong></p><p>No actual client findings or real human approval. Numerical rates are proportions; staff time is minutes per observed eligible call; median duration is seconds.</p><p>Dataset SHA-256: {e(result["input_sha256"])}</p><table><tr><th>Channel</th><th>Metric</th><th>Value</th><th>Calculation / sample</th><th>Evidence</th></tr>' + ''.join(rows) + '</table><h2>AI versus traditional comparison</h2><pre>'+e(json.dumps(result["sites"][site]["comparison"],indent=2))+'</pre><h2>Language strata</h2><p>Rates suppressed below five eligible calls; these fictional groups do not establish fairness.</p><pre>'+e(json.dumps(result["sites"][site]["language_strata"],indent=2))+'</pre><h2>Limitations</h2><ul>'+''.join('<li>'+e(x)+'</li>' for x in result["limitations"])+'</ul>'
