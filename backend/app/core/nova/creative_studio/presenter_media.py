"""Measured presenter narration and captions that travel with the MP4."""
from __future__ import annotations
from difflib import SequenceMatcher
import json
import re
import textwrap
from pathlib import Path
from app.core.nova.creative_studio.media_runtime import MIB, run_encoder, serialized_media


def _encode(args, headroom=128 * MIB):
    import imageio_ffmpeg
    result = run_encoder([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-y', *args],
                         timeout=180, required_headroom=headroom)
    if result.returncode:
        raise RuntimeError('Presenter media processing failed: ' + result.stderr[-600:])
    return result


@serialized_media
def normalize_narration(path: Path):
    analysis = _encode(['-threads', '1', '-i', str(path), '-af',
                        'loudnorm=I=-16:TP=-1.5:LRA=7:print_format=json', '-f', 'null', '-'])
    measured, _ = json.JSONDecoder().raw_decode(analysis.stderr[analysis.stderr.rfind('{'):])
    if measured['input_i'] == '-inf':
        raise RuntimeError('Presenter narration is silent.')
    filt = ('loudnorm=I=-16:TP=-1.5:LRA=7:linear=true:'
            f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
            f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
            f"offset={measured['target_offset']}")
    target = path.with_name(path.stem + '-clear.mp3')
    _encode(['-threads', '1', '-i', str(path), '-af', filt, '-ar', '24000', '-ac', '1',
             '-codec:a', 'libmp3lame', '-b:a', '128k', str(target)])
    return target, {'target_lufs': -16, 'true_peak_limit_db': -1.5, 'original_lufs': measured['input_i']}


def caption_cues(script: str, words: list[dict], duration: float):
    """Retain every reviewed script word; align it to recognized speech times."""
    tokens = script.split()
    norm = lambda s: re.sub(r'[^\w]', '', s).casefold()
    timing = [None] * len(tokens)
    matcher = SequenceMatcher(None, [norm(t) for t in tokens],
                              [norm(str(w['word'])) for w in words], autojunk=False)
    matched = 0
    for tag, a, b, c, d in matcher.get_opcodes():
        if tag == 'equal':
            for i, j in zip(range(a, b), range(c, d)):
                timing[i] = (float(words[j]['start']), float(words[j]['end']))
                matched += 1
    if not tokens or matched < len(tokens) * .6:
        raise RuntimeError('Caption alignment needs review: speech did not sufficiently match the script.')
    i = 0
    while i < len(tokens):
        if timing[i] is not None:
            i += 1
            continue
        first = i
        while i < len(tokens) and timing[i] is None:
            i += 1
        start = timing[first - 1][1] if first else 0.
        end = timing[i][0] if i < len(tokens) else duration
        end = max(start, end)
        for k in range(first, i):
            timing[k] = (start + (end-start)*(k-first)/(i-first),
                         start + (end-start)*(k-first+1)/(i-first))
    cues, first = [], 0
    for i, token in enumerate(tokens):
        if i-first >= 7 or token.endswith(('.', '!', '?', ';', ':')) or i == len(tokens)-1:
            start = max(0., min(duration, timing[first][0]))
            end = max(start + .05, min(duration, timing[i][1]))
            cues.append({'start': start, 'end': end, 'text': ' '.join(tokens[first:i+1])})
            first = i+1
    return cues


def _time(value: float, ass=False):
    units = round(value * (100 if ass else 1000))
    hours, units = divmod(units, 360000 if ass else 3600000)
    mins, units = divmod(units, 6000 if ass else 60000)
    secs, units = divmod(units, 100 if ass else 1000)
    return f'{hours:d}:{mins:02}:{secs:02}.{units:02}' if ass else f'{hours:02}:{mins:02}:{secs:02},{units:03}'


def srt_text(cues):
    return '\n\n'.join(f"{i+1}\n{_time(c['start'])} --> {_time(c['end'])}\n{c['text']}" for i,c in enumerate(cues)) + '\n'


@serialized_media
def caption_presenter(video: Path, cues: list[dict]):
    if not cues:
        raise RuntimeError('Timed presenter captions are missing.')
    # Pad below the original frame. Never crop or cover provider watermarks.
    ass = video.with_suffix('.ass')
    lines = ['[Script Info]', 'PlayResX: 512', 'PlayResY: 640', '[V4+ Styles]',
             'Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
             'Style: Default,DejaVu Sans,23,&H00FFFFFF,&H00000000,0,1,1,0,2,20,20,22,1',
             '[Events]', 'Format: Layer, Start, End, Style, Text']
    for cue in cues:
        safe = cue['text'].replace('\\', '＼').replace('{', '｛').replace('}', '｝')
        wrapped = r'\N'.join(textwrap.wrap(safe, 36, break_long_words=True, break_on_hyphens=False))
        lines.append(f"Dialogue: 0,{_time(cue['start'],True)},{_time(cue['end'],True)},Default,{wrapped}")
    ass.write_text('\n'.join(lines), encoding='utf-8')
    srt = video.with_suffix('.srt')
    srt.write_text(srt_text(cues), encoding='utf-8')
    output = video.with_name(video.stem + '-captioned.mp4')
    # Our files have generated safe basenames. Work in their directory for the
    # subtitle filter; user narration is only in the escaped ASS file.
    escaped_path = str(ass).replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'")
    _encode(['-threads', '1', '-filter_threads', '1', '-i', str(video), '-vf',
             f"scale=512:512:force_original_aspect_ratio=decrease,pad=512:640:(ow-iw)/2:0:color=0x07111f,subtitles='{escaped_path}'",
             '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '1', '-tune', 'zerolatency',
             '-c:a', 'copy', '-movflags', '+faststart', str(output)], 192 * MIB)
    return output, srt
