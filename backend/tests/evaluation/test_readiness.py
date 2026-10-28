"""Independent expectations and adversarial checks for the synthetic prototype."""
import copy
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2] / "app/core/nova"))
from evaluation.engine import correct_fixture,digest,evaluate,render_site_report
from evaluation.fixtures import build_fixture,inject_errors


class ReadinessTests(unittest.TestCase):
    def setUp(self): self.bundle=build_fixture()
    def metric(self,result,site="DEMO_TENNESSEE",channel="AI",name="completion"):
        return result["sites"][site]["cohorts"][channel]["metrics"][name]
    def test_expected_completion_and_abandonment(self):
        r=evaluate(self.bundle)
        self.assertEqual(r["valid_call_count"],32)
        self.assertEqual((self.metric(r)["numerator"],self.metric(r)["denominator"]),(6,7))
        self.assertEqual(self.metric(r,name="abandonment")["numerator"],1)
        self.assertAlmostEqual(r["sites"]["DEMO_TENNESSEE"]["comparison"]["completion"]["ai_minus_traditional"],1/7)
    def test_handoff_uses_request_denominator_and_matter_evidence(self):
        m=self.metric(evaluate(self.bundle),name="handoff_success")
        self.assertEqual((m["numerator"],m["denominator"]),(5,6))
        self.assertTrue(any("MATTER-ROW" in x for x in m["numerator_refs"]))
    def test_no_false_human_approval(self):
        r=evaluate(self.bundle)
        self.assertEqual(r["status"],"AWAITING_HUMAN_REVIEW")
        self.assertFalse(r["approved_for_client_delivery"])
    def test_every_metric_reference_resolves(self):
        r=evaluate(self.bundle)
        for site in r["sites"].values():
            for cohort in site["cohorts"].values():
                for m in cohort["metrics"].values():
                    for k in ("numerator_refs","denominator_refs","excluded_call_refs"):
                        for ref in m.get(k,[]):self.assertIn(ref,r["source_manifest"])
                    for o in m.get("observations",[]):
                        for ref in o["source_refs"]: self.assertIn(ref,r["source_manifest"])
        for ref, source in r["source_manifest"].items(): self.assertEqual(source["sha256"],digest(source["record"]))
    def test_missing_staff_time_not_zero_imputed(self):
        m=self.metric(evaluate(self.bundle),site="DEMO_FLORIDA",name="staff_minutes_per_eligible_call")
        self.assertEqual(m["denominator"],6)
        self.assertEqual(m["numerator"],38)
        self.assertEqual(len(m["excluded_call_refs"]),1)
    def test_small_language_samples_suppressed(self):
        r=evaluate(self.bundle)
        for site in r["sites"].values():
            for row in site["language_strata"].values():
                self.assertTrue(row["suppressed"]);self.assertIsNone(row["completion_rate"])
    def test_repeated_import_collapses_but_different_calls_remain(self):
        other=copy.deepcopy(self.bundle["calls"][0]);other["record_id"]="DEMO-REPEAT"
        self.bundle["calls"].append(other)
        r=evaluate(self.bundle)
        self.assertEqual(r["valid_call_count"],32);self.assertEqual(len(r["duplicate_calls_collapsed"]),1)
        self.assertEqual(self.metric(r)["denominator"],7)
    def test_conflicting_duplicate_excludes_all_versions(self):
        other=copy.deepcopy(self.bundle["calls"][7]);other["record_id"]="DEMO-CONFLICT";other["status"]="completed"
        self.bundle["calls"].append(other)
        r=evaluate(self.bundle)
        self.assertEqual(r["valid_call_count"],31)
        self.assertIn("CONFLICTING_CALL_ID",{x["code"] for x in r["issues"]})
        self.assertEqual(self.metric(r)["numerator"],6)
    def test_deliberate_corruption_blocks(self):
        r=evaluate(inject_errors(self.bundle))
        codes={x["code"] for x in r["issues"]}
        self.assertTrue({"CONFLICTING_CALL_ID","INVALID_CALL_FIELDS","TRANSCRIPT_LINK","MATTER_LINK","ORPHAN_TRANSFER"}.issubset(codes))
        self.assertEqual(r["status"],"BLOCKED_DATA_QUALITY")
    def test_timezone_is_required(self):
        self.bundle["calls"][0]["started"]="2026-10-10T12:00:00"
        self.assertIn("INVALID_CALL_FIELDS",{i["code"] for i in evaluate(self.bundle)["issues"]})
    def test_nan_and_infinity_rejected(self):
        for v in [float("nan"),float("inf")]:
            with self.subTest(v=v):
                b=copy.deepcopy(self.bundle);b["calls"][0]["staff_minutes"]=v
                with self.assertRaises(ValueError):evaluate(b)
    def test_empty_denominator_is_null(self):
        self.bundle["calls"]=[c for c in self.bundle["calls"] if c["site"]=="DEMO_TENNESSEE"]
        r=evaluate(self.bundle)
        self.assertIsNone(self.metric(r,site="DEMO_FLORIDA")["value"])
    def test_no_causal_claim_in_comparison(self):
        row=evaluate(self.bundle)["sites"]["DEMO_TENNESSEE"]["comparison"]["completion"]
        self.assertIn("no causal",row["interpretation"])
    def test_immutable_simulated_correction_and_regeneration(self):
        before=copy.deepcopy(self.bundle);r1=evaluate(before);row=before["calls"][0]
        after,audit=correct_fixture(before,expected_input_sha256=digest(before),record_id=row["record_id"],field="captured_county",old_value="DEMO_COUNTY_WRONG",new_value="DEMO_COUNTY_A",reason="Fixture import review",evidence_ref=before["matters"][0]["record_id"])
        r2=evaluate(after)
        self.assertEqual(before,self.bundle)
        self.assertEqual(self.metric(r1,name="county_accuracy")["numerator"],5)
        self.assertEqual(self.metric(r2,name="county_accuracy")["numerator"],6)
        self.assertNotEqual(r1["input_sha256"],r2["input_sha256"])
        self.assertFalse(audit["real_human_approval"])
        self.assertEqual(r1["sites"]["DEMO_FLORIDA"],r2["sites"]["DEMO_FLORIDA"])
    def test_stale_review_blocked(self):
        with self.assertRaisesRegex(ValueError,"Stale"):
            correct_fixture(self.bundle,expected_input_sha256="old",record_id=self.bundle["calls"][0]["record_id"],field="status",old_value="completed",new_value="abandoned",reason="test",evidence_ref=self.bundle["transcripts"][0]["record_id"])
    def test_cross_site_review_evidence_rejected(self):
        with self.assertRaisesRegex(ValueError,"same site"):
            correct_fixture(self.bundle,expected_input_sha256=digest(self.bundle),record_id=self.bundle["calls"][0]["record_id"],field="status",old_value="completed",new_value="abandoned",reason="test",evidence_ref=self.bundle["transcripts"][20]["record_id"])
    def test_report_escapes_text(self):
        self.bundle["calls"][0]["language"]="<script>alert(1)</script>"
        report=render_site_report(evaluate(self.bundle),"DEMO_TENNESSEE")
        self.assertNotIn("<script>",report)
        self.assertIn("&lt;script&gt;",report)
    def test_input_without_synthetic_flag_rejected(self):
        self.bundle["synthetic"]=False
        with self.assertRaisesRegex(ValueError,"Synthetic"):evaluate(self.bundle)
    def test_replay_is_deterministic(self):
        self.assertEqual(evaluate(self.bundle),evaluate(self.bundle))
    def test_changed_input_changes_manifest(self):
        r1=evaluate(self.bundle);self.bundle["calls"][0]["staff_minutes"]=100;r2=evaluate(self.bundle)
        self.assertNotEqual(r1["input_sha256"],r2["input_sha256"])
        ref=self.bundle["calls"][0]["record_id"]
        self.assertNotEqual(r1["source_manifest"][ref]["sha256"],r2["source_manifest"][ref]["sha256"])
    def test_reference_mismatch_enters_review_queue(self):
        r=evaluate(self.bundle)
        self.assertEqual(len(r["findings"]),2)
        f=next(f for f in r["findings"] if f["site"]=="DEMO_TENNESSEE")
        self.assertEqual(f["code"],"FIELD_MISMATCH");self.assertTrue(f["review_required"])
        self.assertEqual(f["source_refs"][0],self.bundle["calls"][0]["record_id"])
    def test_known_staff_and_duration_totals(self):
        r=evaluate(self.bundle)
        self.assertEqual(self.metric(r,name="staff_minutes_per_eligible_call")["numerator"],42)
        self.assertEqual(self.metric(r,channel="TRADITIONAL",name="staff_minutes_per_eligible_call")["numerator"],84)
        self.assertEqual(self.metric(r,name="median_completed_call_seconds")["value"],450)
        self.assertEqual(self.metric(r,name="field_completeness")["value"],5/6)
    def test_different_call_ids_with_same_business_values_preserved(self):
        a=self.bundle["calls"][6];b=self.bundle["calls"][14]
        for field in ["started","ended","status","staff_minutes","complete_fields","language","captured_county"]:b[field]=a[field]
        r=evaluate(self.bundle)
        self.assertEqual(r["valid_call_count"],32)
        self.assertEqual(len(r["duplicate_calls_collapsed"]),0)
    def test_duplicate_transcript_id_blocks(self):
        t=copy.deepcopy(self.bundle["transcripts"][0]);t["record_id"]="DEMO-TRANSCRIPT-CONFLICT"
        self.bundle["transcripts"].append(t)
        r=evaluate(self.bundle)
        self.assertIn("DUPLICATE_EVIDENCE_ID",{x["code"] for x in r["issues"]})
        self.assertEqual(r["status"],"BLOCKED_DATA_QUALITY")
    def test_duplicate_source_id_blocks(self):
        self.bundle["calls"][1]["record_id"]=self.bundle["calls"][0]["record_id"]
        self.assertIn("INVALID_SOURCE_ID",{x["code"] for x in evaluate(self.bundle)["issues"]})
    def test_string_false_is_not_true(self):
        self.bundle["calls"][0]["complete_fields"]="false"
        r=evaluate(self.bundle)
        self.assertEqual(self.metric(r)["numerator"],5)
        self.assertEqual(r["status"],"BLOCKED_DATA_QUALITY")
    def test_duplicate_terminal_handoff_not_counted_twice(self):
        tr=copy.deepcopy(self.bundle["transfers"][0]);tr["id"]="DEMO-TRANSFER-EXTRA";tr["record_id"]="DEMO-TRANSFER-EXTRA-ROW"
        self.bundle["transfers"].append(tr)
        r=evaluate(self.bundle)
        self.assertEqual(self.metric(r,name="handoff_success")["numerator"],4)
        self.assertIn("TRANSFER_CARDINALITY",{x["code"] for x in r["issues"]})
    def test_failed_transfer_does_not_count_as_success(self):
        self.bundle["transfers"][0]["status"]="failed"
        self.assertEqual(self.metric(evaluate(self.bundle),name="handoff_success")["numerator"],4)
    def test_correction_requires_reason(self):
        with self.assertRaisesRegex(ValueError,"reason"):
            correct_fixture(self.bundle,expected_input_sha256=digest(self.bundle),record_id=self.bundle["calls"][0]["record_id"],field="status",old_value="completed",new_value="abandoned",reason="",evidence_ref=self.bundle["transcripts"][0]["record_id"])
    def test_correction_cannot_change_call_identity(self):
        with self.assertRaisesRegex(ValueError,"review-editable"):
            correct_fixture(self.bundle,expected_input_sha256=digest(self.bundle),record_id=self.bundle["calls"][0]["record_id"],field="site",old_value="DEMO_TENNESSEE",new_value="DEMO_FLORIDA",reason="test",evidence_ref=self.bundle["transcripts"][0]["record_id"])
    def test_review_cannot_erase_real_capture_error(self):
        row=self.bundle["calls"][18]
        matter=next(m for m in self.bundle["matters"] if m["call_id"]==row["call_id"])
        with self.assertRaisesRegex(ValueError,"raw source value"):
            correct_fixture(self.bundle,expected_input_sha256=digest(self.bundle),record_id=row["record_id"],field="captured_county",old_value="DEMO_COUNTY_WRONG",new_value="DEMO_COUNTY_B",reason="Try to erase a real error",evidence_ref=matter["record_id"])
        self.assertEqual(self.metric(evaluate(self.bundle),site="DEMO_FLORIDA",name="county_accuracy")["numerator"],4)
    def test_unhashable_call_fields_are_quarantined(self):
        for field in ["site","channel","status","transcript_id"]:
            with self.subTest(field=field):
                b=copy.deepcopy(self.bundle);b["calls"][0][field]=[]
                self.assertEqual(evaluate(b)["status"],"BLOCKED_DATA_QUALITY")
    def test_invalid_transfer_identity_is_quarantined(self):
        self.bundle["transfers"][0]["call_id"]=[]
        self.assertEqual(evaluate(self.bundle)["status"],"BLOCKED_DATA_QUALITY")


if __name__=="__main__":unittest.main()
