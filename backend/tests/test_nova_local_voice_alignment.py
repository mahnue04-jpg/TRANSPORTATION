"""Native caption timing must preserve written text and reject fabricated timing."""
import hashlib
from types import SimpleNamespace

import pytest
from local_voice_alignment import native_chunk_words, script_alignment, checked_caption_result


def word(text, start, end):
    return {"word": text, "start": start, "end": end}


def test_pronunciation_and_domain_expansions_keep_original_caption_words():
    native = [word("Meet", 0, .2), word("Amih", .2, .4), word("core", .4, .7),
              word("Get", .8, 1), word("Amih-core", 1, 1.4),
              word("dot", 1.4, 1.6), word("com", 1.6, 1.9)]
    result = script_alignment("Meet AMICOR. GetAmiCore.com!", native, 2)
    assert [w["word"] for w in result["words"]] == ["Meet", "AMICOR.", "GetAmiCore.com!"]
    assert result["words"][1] == word("AMICOR.", .2, .7)
    assert [c["text"] for c in result["caption_cues"]] == ["Meet AMICOR.", "GetAmiCore.com!"]
    assert result["words"][-1]["end"] == 1.9


def test_chunk_offsets_follow_pcm_lengths_and_only_allow_small_frame_rounding():
    tokens = [SimpleNamespace(text="Nova", start_ts=.1, end_ts=1.025)]
    assert native_chunk_words(tokens, 2, 1) == [word("Nova", 2.1, 3)]
    tokens[0].end_ts = 1.2
    with pytest.raises(ValueError): native_chunk_words(tokens, 2, 1)


@pytest.mark.parametrize("native", [[], [word("wrong", 0, .2)],
    [word("Hello", 0, .2)], [word("Hello", 0, .4), word("Nova", .3, .6)],
    [word("Hello", 0, float("nan")), word("Nova", .3, .6)],
    [word("Hello", 0, .2), word("Nova", .3, 2)],
    [word("Hello", 0, .2), word("Nova", .3, .6), word("extra", .6, .8)]])
def test_missing_mismatched_overlapping_or_nonfinite_timing_is_not_guessed(native):
    with pytest.raises(ValueError): script_alignment("Hello Nova", native, 1)


def signed_alignment():
    script = "Hello AMICOR."
    data = script_alignment(script, [word("Hello", 0, .2), word("Amih-core", .2, .5)], .6)
    data.update(audio_sha256="sample-audio-hash",
                script_sha256=hashlib.sha256(script.encode()).hexdigest())
    return data, script


@pytest.mark.parametrize("field,value", [("audio_sha256", "wrong"),
    ("script_sha256", "wrong"), ("duration_seconds", .7),
    ("duration_seconds", float("nan")), ("alignment_source", "estimated"),
    ("alignment_available", False)])
def test_parent_checks_provenance_before_accepting_captions(field, value):
    data, script = signed_alignment(); data[field] = value
    with pytest.raises(ValueError): checked_caption_result(data, script, .6, "sample-audio-hash")


def test_parent_rebuilds_cues_instead_of_trusting_child_caption_text():
    data, script = signed_alignment()
    data["caption_cues"] = [{"text": "Unrelated content", "start": 0, "end": 99}]
    result = checked_caption_result(data, script, .6, "sample-audio-hash")
    assert result["caption_cues"] == [{"text": script, "start": 0, "end": .5}]
    data["words"][0]["word"] = "Changed"
    with pytest.raises(ValueError): checked_caption_result(data, script, .6, "sample-audio-hash")
