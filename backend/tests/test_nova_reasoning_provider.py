"""Offline contract tests, not claims about actual model accuracy or account access."""
from types import SimpleNamespace

import pytest

from app.core.nova.reasoning import ask_nova_reasoning
from app.core.nova.service import NovaCoreService
from app.core.nova.today import service
from app.core.nova.today.schemas import NovaTodayBrainRequest


SCHEDULE = (
    "Two workers can each perform one task at a time. Tasks cannot be interrupted. "
    "A takes 3 hours; B takes 2 hours; C takes 4 hours after A; D takes 3 hours after A; "
    "E takes 2 hours after B; F takes 2 hours after C, D, and E. "
    "What is the shortest possible time? Give a schedule and prove optimality."
)
BAD_ANSWER = "7 hours. Worker 1: A 0-3, C 3-4, D 4-7. Worker 2: B 0-2, E 2-4, F 4-6."


def test_provider_contract_is_bounded_and_uses_reasoning(monkeypatch):
    calls = []
    def options(**kw):
        calls.append(kw)
        return SimpleNamespace(responses=SimpleNamespace(create=create))
    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(status="completed", output_text="Fixture answer")
    monkeypatch.delenv("NOVA_REASONING_MODEL", raising=False)
    monkeypatch.delenv("NOVA_REASONING_EFFORT", raising=False)
    monkeypatch.setattr("app.ai.get_client", lambda: SimpleNamespace(with_options=options))
    assert ask_nova_reasoning(SCHEDULE) == "Fixture answer"
    assert calls[0] == {"max_retries": 0, "timeout": 35.0}
    request = calls[1]
    assert request["model"] == "gpt-6-astra"
    assert request["reasoning"] == {"effort": "medium"}
    assert request["max_output_tokens"] == 8192 and request["store"] is False
    assert "tools" not in request and "temperature" not in request
    assert request["input"] == SCHEDULE
    for rule in ("end minus start", "prerequisite", "workers never overlap", "lower bound", "base rate", "Recompute"):
        assert rule in request["instructions"]


@pytest.mark.parametrize("response", [
    SimpleNamespace(status="incomplete", output_text="An unfinished 7-hour schedule"),
    SimpleNamespace(status="completed", output_text=""),
])
def test_empty_and_incomplete_answers_are_not_published(monkeypatch, response):
    client = SimpleNamespace(with_options=lambda **kw: SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: response)))
    monkeypatch.setattr("app.ai.get_client", lambda: client)
    with pytest.raises(RuntimeError):
        ask_nova_reasoning(SCHEDULE)


def test_failure_is_a_service_error_not_a_reasoning_refusal(monkeypatch):
    monkeypatch.setattr(NovaCoreService, "_can_use_llm", lambda: True)
    def fail(*args):
        raise RuntimeError("provider error with private details")
    monkeypatch.setattr("app.core.nova.reasoning.ask_nova_reasoning", fail)
    answer, mode = NovaCoreService._llm_answer("founder_advisor", SCHEDULE, None, require_operational_next_actions=False, reasoning_profile=True)
    assert mode == "reasoning_unavailable"
    assert "service failure" in answer and "private details" not in answer
    assert "live or external" not in answer


def test_reported_schedule_followup_receives_problem_and_wrong_answer(monkeypatch):
    def forbidden(*a, **kw):
        pytest.fail("self-contained schedule must not use dashboard or web")
    monkeypatch.setattr(service, "dashboard", forbidden)
    monkeypatch.setattr(service, "fetch_web_search", forbidden)
    monkeypatch.setattr(service, "_today_government_grounded_answer", forbidden)
    calls = []
    def ask(*a, **kw):
        calls.append(kw)
        # Transport fixture only: this does not evaluate a live model's answer.
        return SimpleNamespace(answer="Fixture response", generated_at="2026-11-02T00:00:00Z", context_used={})
    monkeypatch.setattr(NovaCoreService, "ask", ask)
    question = "Check your previous schedule against every task's required duration and prerequisite."
    out = service.ask_today(None, NovaTodayBrainRequest(question=question, previous_turn={"question": SCHEDULE, "answer": BAD_ANSWER}), organization_id="fixture", user=SimpleNamespace(user_id="fixture"))
    assert calls[0]["reasoning_profile"] is True
    assert SCHEDULE in calls[0]["question"] and BAD_ANSWER in calls[0]["question"]
    assert "UNTRUSTED PREVIOUS TURN" in calls[0]["question"]
    assert out.sources == [] and out.next_actions == []


def test_missing_prior_turn_requests_context_without_capability_refusal(monkeypatch):
    monkeypatch.setattr(NovaCoreService, "ask", lambda *a, **kw: pytest.fail("ask for missing context first"))
    out = service.ask_today(None, NovaTodayBrainRequest(question="Check your previous schedule."), organization_id="fixture", user=SimpleNamespace(user_id="fixture"))
    assert "I can check" in out.answer and "paste the original problem" in out.answer


def test_stale_prior_answer_does_not_contaminate_new_question(monkeypatch):
    sentinel = "PRIVATE PRIOR ANSWER"
    calls = []
    monkeypatch.setattr(service, "_today_live_or_memory_answer", lambda *a, **kw: None)
    monkeypatch.setattr(NovaCoreService, "ask", lambda *a, **kw: calls.append(kw) or SimpleNamespace(answer="Fixture", generated_at="2026-11-02T00:00:00Z", context_used={}))
    service.ask_today(None, NovaTodayBrainRequest(question="Explain why the sky is blue", previous_turn={"question": SCHEDULE, "answer": sentinel}), organization_id="fixture", user=SimpleNamespace(user_id="fixture"))
    assert sentinel not in calls[0]["question"]


def test_context_has_explicit_size_limits():
    with pytest.raises(ValueError):
        NovaTodayBrainRequest(question="Check your previous answer", previous_turn={"question": "x" * 4001, "answer": "y"})
