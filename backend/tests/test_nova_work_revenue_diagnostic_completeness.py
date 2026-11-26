"""The shared Render diagnostic must finish Work & Revenue.

Job 117550654453 failed in Creative Studio and GitHub then skipped
"Run Nova Work & Revenue regression". A skipped Work step is an incomplete
build. This test fails while Work is a later step in that same job, and it
fails if a skip is treated as a pass.

Creative Studio files are not edited here. The Studio failure stays visible
on backend-diagnostic. It must not cancel the Work job.
"""
from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "render-backend-diagnostic.yml"

# The step GitHub skipped after the Studio failure in run 39085366881.
REQUIRED_WORK_FILES = (
    "tests/test_nova_work_revenue.py",
    "tests/test_nova_work_revenue_completion.py",
    "tests/test_nova_work_revenue_v2.py",
    "tests/test_nova_work_revenue_live_discovery_flag_bridge.py",
    "tests/test_nova_work_autopilot_cycle.py",
    "tests/test_nova_live_opportunity_qualification.py",
    "tests/test_nova_capability_first_discovery.py",
    "tests/test_nova_international_match.py",
    "tests/test_nova_work_eligibility_explanations.py",
    "tests/test_nova_multi_source_discovery.py",
    "tests/test_nova_sam_gov_discovery.py",
    "tests/test_nova_capability_catalog.py",
    "tests/test_nova_execution_playbooks.py",
    "tests/test_nova_work_packets.py",
    "tests/test_nova_autonomous_execution.py",
    "tests/test_nova_application_review.py",
    "tests/test_nova_work_revenue_block5.py",
    "tests/test_nova_work_revenue_labeling.py",
    "tests/test_nova_work_revenue_operator_ui.py",
    "tests/test_nova_work_revenue_owner_facts.py",
    "tests/test_nova_work_revenue_simulated_ingest_guard.py",
    "tests/test_nova_work_revenue_v2_hardening.py",
    "tests/test_nova_work_revenue_v2_migration.py",
    "tests/test_nova_first_client_pipeline.py",
    "tests/test_nova_v3_phase2_scheduler.py",
    "tests/test_nova_work_revenue_diagnostic_completeness.py",
)


def _job_blocks(text: str) -> dict[str, str]:
    lines = text.splitlines()
    try:
        start = lines.index("jobs:") + 1
    except ValueError as exc:
        raise AssertionError("render diagnostic workflow has no jobs") from exc
    blocks: dict[str, str] = {}
    name: str | None = None
    buf: list[str] = []
    for line in lines[start:]:
        if line.startswith("  ") and not line.startswith("   ") and line.endswith(":"):
            if name is not None:
                blocks[name] = "\n".join(buf)
            name = line.strip()[:-1]
            buf = [line]
            continue
        if name is None:
            continue
        if line.startswith(" ") or line.strip() == "":
            buf.append(line)
            continue
        break
    if name is not None:
        blocks[name] = "\n".join(buf)
    return blocks


def _steps(job_body: str) -> list[dict[str, str]]:
    """Return step name, if-condition, and whether continue-on-error is set."""
    steps: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in job_body.splitlines():
        stripped = line.strip()
        if stripped.startswith("- name:"):
            if current is not None:
                steps.append(current)
            current = {"name": stripped.split(":", 1)[1].strip(), "if": "", "continue": ""}
            continue
        if current is None:
            continue
        if stripped.startswith("if:"):
            current["if"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("continue-on-error:"):
            current["continue"] = stripped.split(":", 1)[1].strip()
    if current is not None:
        steps.append(current)
    return steps


def _runs_after_failure(condition: str) -> bool:
    token = condition.replace(" ", "")
    return "always()" in token or "!cancelled()" in token or "failure()" in token


def test_work_regression_is_not_skipped_when_creative_studio_fails() -> None:
    """GitHub skips later steps after a failure. Work must be its own job."""
    text = WORKFLOW.read_text(encoding="utf-8")
    blocks = _job_blocks(text)
    diagnostic = blocks["backend-diagnostic"]
    studio_steps = [
        step for step in _steps(diagnostic) if "Creative Studio" in step["name"]
    ]
    assert studio_steps, "Creative Studio regression must stay in backend-diagnostic"
    assert all(step["continue"] != "true" for step in studio_steps)

    work_steps = [
        step for step in _steps(diagnostic) if "Work & Revenue" in step["name"]
    ]
    assert not work_steps, (
        "Work & Revenue is still a later step of backend-diagnostic. "
        "A Creative Studio failure skips it, which is the incomplete build "
        "in job 117550654453."
    )

    work_jobs = [
        name
        for name, body in blocks.items()
        if name != "backend-diagnostic" and "tests/test_nova_work_revenue.py" in body
    ]
    assert work_jobs == ["work-revenue-diagnostic"]
    body = blocks["work-revenue-diagnostic"]
    assert "\n    needs:" not in body
    assert "continue-on-error" not in body
    assert "Run Creative Studio" not in body
    for test_file in REQUIRED_WORK_FILES:
        assert test_file in body
    assert 'test "$skipped" -eq 0' in body
    assert 'test "$ran" -eq ' + str(len(REQUIRED_WORK_FILES)) in body
    assert "unset SAM_GOV_API_KEY" in body


def test_github_step_runner_would_skip_work_behind_studio() -> None:
    """The failed job's rule: a nonzero step skips every following step."""
    diagnostic = _job_blocks(WORKFLOW.read_text(encoding="utf-8"))["backend-diagnostic"]
    steps = _steps(diagnostic)
    names = [step["name"] for step in steps]
    assert any("Creative Studio" in name for name in names)
    failed = False
    for step in steps:
        if failed and not _runs_after_failure(step["if"]):
            assert "Work & Revenue" not in step["name"], (
                f"{step['name']} would be SKIPPED after Creative Studio fails"
            )
            continue
        if "Creative Studio" in step["name"] and step["continue"] != "true":
            failed = True
