from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app import voice
from app.core.nova.workspace import service
from app.core.nova.workspace.schemas import NovaWorkspaceBrainRequest


@pytest.mark.parametrize('code,name', [('ar','Arabic'),('fr','French'),('es','Spanish')])
def test_answer_language_controls_customer_drafts(monkeypatch, code, name):
    calls = []
    monkeypatch.setattr('app.ai.ask_openai', lambda prompt: calls.append(prompt) or 'Translated draft')
    request = NovaWorkspaceBrainRequest(question='Make a blank checklist', answer_language=code)
    result = service._answer_workspace_task(request.question, 'Easy Care · PCA', request.answer_language)
    assert result == 'Translated draft'
    assert f'Answer in {name}.' in calls[0]
    assert 'Never rewrite original saved records' in calls[0]


def test_unrecognized_language_is_rejected():
    with pytest.raises(ValidationError):
        NovaWorkspaceBrainRequest(question='hello', answer_language='unknown')
    with pytest.raises(ValidationError):
        voice.VoiceSpeakRequest(text='hello', language='unknown')


def test_arabic_synthesis_preserves_text_and_sends_language_instructions(monkeypatch):
    create = Mock(return_value=b'ID3audio')
    monkeypatch.setattr(voice, '_openai_available', lambda: True)
    monkeypatch.setattr(voice, 'OpenAI', lambda **kwargs: SimpleNamespace(audio=SimpleNamespace(speech=SimpleNamespace(create=create))))
    monkeypatch.setattr(voice, 'OPENAI_TTS_MODEL', 'gpt-4o-mini-tts')
    audio, mime = voice._synthesize_openai('مرحبا عيسى', 'ar')
    assert audio == b'ID3audio'
    assert mime == 'audio/mpeg'
    assert create.call_args.kwargs['input'] == 'مرحبا عيسى'
    assert 'Arabic' in create.call_args.kwargs['instructions']


def test_azure_uses_somali_voice_and_escapes_ssml(monkeypatch):
    post = Mock(return_value=SimpleNamespace(status_code=200, content=b'audio'))
    monkeypatch.setattr(voice, '_azure_available', lambda: True)
    monkeypatch.setattr(voice.requests, 'post', post)
    voice._synthesize_azure('Isa & <tag> qoraal', 'so')
    body = post.call_args.kwargs['data'].decode()
    assert "xml:lang='so-SO'" in body
    assert 'so-SO-UbaxNeural' in body
    assert '&amp;' in body and '&lt;tag&gt;' in body


def test_somali_prefers_configured_native_voice(monkeypatch):
    azure = Mock(return_value=(b'audio','audio/mpeg'))
    openai = Mock()
    monkeypatch.setattr(voice, '_synthesize_azure', azure)
    monkeypatch.setattr(voice, '_synthesize_openai', openai)
    result = voice.voice_speak(voice.VoiceSpeakRequest(text='Salaan Isa', language='so'))
    assert result.provider == 'azure_neural_voice'
    azure.assert_called_once_with('Salaan Isa','so')
    openai.assert_not_called()
