"""Map native speech-model token times back to the unchanged written script.

No transcription service, guessed spacing, model imports or network calls.
Missing/mismatched timing must not be presented as aligned captions.
"""
import math
import unicodedata

from .local_voice import spoken_text

SOURCE = "kokoro_native_token_durations"


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKD", str(text)).casefold()
                   if c.isalnum())


def native_chunk_words(tokens, offset, duration):
    if not tokens:
        raise ValueError("Native speech token timings are missing.")
    words, previous = [], 0.0
    for token in tokens:
        text = str(token.text)
        if not normalized(text):
            continue
        start, end = float(token.start_ts), float(token.end_ts)
        if (not all(math.isfinite(t) for t in (start, end))
                or start < 0 or end <= start or start < previous - 1e-6
                or end > duration + 0.075):
            raise ValueError("Native speech token timings are invalid.")
        end = min(end, duration)  # Native frame rounding may exceed PCM by one frame.
        if end <= start:
            raise ValueError("Native speech token falls outside the audio.")
        words.append({"word": text, "start": offset + start, "end": offset + end})
        previous = end
    if not words:
        raise ValueError("Native speech token timings are empty.")
    return words


def script_alignment(script, native_words, duration):
    if not math.isfinite(duration) or duration <= 0 or not native_words:
        raise ValueError("Audio duration and native words are required.")
    words, cursor, previous = [], 0, 0.0
    for text in script.split():
        expected = normalized(spoken_text(text))
        if not expected:
            if words:
                words[-1]["word"] += " " + text
            else:
                raise ValueError("Leading standalone punctuation needs caption review.")
            continue
        first, combined = cursor, ""
        while cursor < len(native_words) and combined != expected:
            token = native_words[cursor]
            part = normalized(token["word"])
            start, end = float(token["start"]), float(token["end"])
            if (not part or not all(math.isfinite(t) for t in (start, end))
                    or start < previous - 1e-6 or end <= start or end > duration):
                raise ValueError("Native speech timing is invalid or non-monotonic.")
            combined += part
            if not expected.startswith(combined):
                raise ValueError("Native speech tokens do not match the written script.")
            previous, cursor = end, cursor + 1
        if combined != expected:
            raise ValueError("Native speech timing does not cover the full script.")
        words.append({"word": text, "start": native_words[first]["start"],
                      "end": native_words[cursor - 1]["end"]})
    if cursor != len(native_words) or not words:
        raise ValueError("Native speech has unmatched or missing words.")
    cues = caption_cues_from_words(words, duration)
    return {"alignment_available": True, "alignment_source": SOURCE,
            "duration_seconds": duration, "words": words, "caption_cues": cues}


def caption_cues_from_words(words, duration):
    if not math.isfinite(duration) or duration <= 0 or not 0 < len(words) <= 1600:
        raise ValueError("Invalid caption duration or word count.")
    previous = 0.0
    for word in words:
        start, end = float(word["start"]), float(word["end"])
        if (not str(word["word"]).strip() or not all(math.isfinite(t) for t in (start, end))
                or start < previous - 1e-6 or end <= start or end > duration):
            raise ValueError("Invalid caption word timing.")
        previous = end
    cues, first = [], 0
    for i, word in enumerate(words):
        if i - first >= 6 or word["word"].endswith((".", "!", "?", ";", ":")) or i == len(words) - 1:
            cues.append({"start": words[first]["start"], "end": word["end"],
                         "text": " ".join(w["word"] for w in words[first:i + 1])})
            first = i + 1
    return cues


def checked_caption_result(data, script, duration, audio_sha256):
    """Validate child metadata against the actual WAV and exact input text."""
    import hashlib
    if (data.get("alignment_available") is not True or data.get("alignment_source") != SOURCE
            or data.get("audio_sha256") != audio_sha256
            or data.get("script_sha256") != hashlib.sha256(script.encode("utf-8")).hexdigest()
            or not math.isfinite(float(data.get("duration_seconds", -1)))
            or abs(float(data["duration_seconds"]) - duration) > 1e-6):
        raise ValueError("Caption timing does not belong to this audio and script.")
    words = data["words"]
    if " ".join(str(w["word"]) for w in words) != " ".join(script.split()):
        raise ValueError("Caption words differ from the written script.")
    cues = caption_cues_from_words(words, duration)
    return {"caption_cues": cues, "word_timestamps": words,
            "caption_alignment": True, "alignment_source": SOURCE}
