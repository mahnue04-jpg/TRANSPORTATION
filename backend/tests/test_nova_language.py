from types import SimpleNamespace

from app.core.nova.language import localized_call
from app.core.nova.today.schemas import NovaTodayBrainRequest


def test_translation_removes_preference_from_source_query_and_preserves_evidence(monkeypatch):
    questions = []
    answer = 'Review NWO-123 at https://example.com/a for $18,500. This is unverified.'
    def call(db, payload, **kwargs):
        questions.append(payload.question)
        return SimpleNamespace(answer=answer, source_href='https://example.com/a')
    monkeypatch.setattr('app.ai.ask_openai', lambda text, history: text.replace('Review', 'Revise').replace('This is unverified.', 'Esto no está verificado.'))
    result = localized_call(call, None, NovaTodayBrainRequest(question='Review my contract\nReply language: Español (es-US).'))
    assert questions == ['Review my contract']
    assert '$18,500' in result.answer
    assert 'NWO-123' in result.answer
    assert 'https://example.com/a' in result.answer
    assert 'Esto no está verificado.' in result.answer
    assert result.source_href == 'https://example.com/a'


def test_invalid_translation_keeps_original_instead_of_changing_evidence(monkeypatch):
    original = 'Amount $18,500 is unverified.'
    monkeypatch.setattr('app.ai.ask_openai', lambda text, history: 'Amount $10 is verified.')
    result = localized_call(lambda *a, **k: SimpleNamespace(answer=original), None,
        NovaTodayBrainRequest(question='Review\nReply language: Español (es-US).'))
    assert result.answer.startswith(original)
    assert 'translation is unavailable' in result.answer
