"""Original two-character dialogue previews; no claim of verified lip sync."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import tempfile
import wave
from app.core.nova.creative_studio.models import CreativeScene, new_id
from app.core.nova.creative_studio.providers import _creative_media_root_and_prefix, _resolve_creative_media_url, voice_provider
from app.core.nova.creative_studio.media_runtime import MIB, run_encoder, serialized_media
from app.core.nova.creative_studio.safety import BLOCK, screen_creative_text

# Budgets include the unchanged 96 MiB web-server reserve. Video is bounded
# to one decoder/encoder thread and zero x264 lookahead.
DRAMA_VIDEO_HEADROOM = 224 * MIB
DRAMA_AUDIO_HEADROOM = 128 * MIB

VOICES = {'alloy', 'ash', 'ballad', 'coral', 'echo', 'fable', 'nova', 'onyx', 'sage', 'shimmer'}
SAMPLE = {
    'setting': 'Luxury hotel lobby at night, golden chandelier, marble floor, blue city lights outside. Original fictional adult characters.',
    'characters': [
        {'name': 'Maya', 'description': 'Adult hotel manager, cream suit, dark hair in a neat bun, composed expression', 'voice': 'nova'},
        {'name': 'Eli', 'description': 'Adult visitor, black coat over a charcoal suit, short dark hair, holding a sealed envelope', 'voice': 'onyx'},
    ],
    'dialogue': 'Eli: Someone told me to leave this at midnight.\nMaya: That envelope was supposed to disappear.\nEli: Then why is your name on it?\nMaya: Because I wrote it.\nEli: Who were you trying to warn?\nMaya: You. The man behind you is not your driver.',
}

def fail(code, message):
    from app.core.nova.creative_studio.service import CreativeStudioError
    raise CreativeStudioError(code, message, http_status=422)


def parse_plan(payload):
    setting = str(payload.get('setting') or '').strip()
    characters = payload.get('characters') or []
    if not setting or len(setting) > 1000 or len(characters) != 2:
        fail('INVALID_DRAMA', 'Provide a setting and exactly two adult fictional characters.')
    cast = []
    for row in characters:
        name = str(row.get('name') or '').strip()
        description = str(row.get('description') or '').strip()
        voice = str(row.get('voice') or '').strip()
        if not name or len(name) > 40 or any(c in name for c in ':\n\r') or not description or len(description) > 600 or voice not in VOICES:
            fail('INVALID_CAST', 'Each character needs a name, appearance, and supported voice.')
        cast.append({'name': name, 'description': description, 'voice': voice})
    if cast[0]['name'].casefold() == cast[1]['name'].casefold() or cast[0]['voice'] == cast[1]['voice']:
        fail('INVALID_CAST', 'Use different character names and different voices.')
    dialogue = str(payload.get('dialogue') or '').strip()
    lines = []
    for raw in dialogue.splitlines():
        if not raw.strip():
            continue
        speaker, separator, text = raw.partition(':')
        match = next((r for r in cast if r['name'].casefold() == speaker.strip().casefold()), None)
        if not separator or not match or not text.strip() or len(text.strip()) > 240:
            fail('INVALID_DIALOGUE', 'Use one Name: dialogue line per shot (up to 240 characters each).')
        lines.append({'speaker': match['name'], 'text': text.strip(), 'voice': match['voice']})
    if not 2 <= len(lines) <= 12 or len({r['speaker'] for r in lines}) != 2:
        fail('INVALID_DIALOGUE', 'Provide 2–12 dialogue lines with both characters speaking.')
    safety = screen_creative_text(setting, dialogue, *(r['description'] for r in cast))
    if safety['decision'] == BLOCK:
        fail('SAFETY_BLOCK', safety['message'])
    plan = {'setting': setting, 'characters': cast, 'dialogue': dialogue, 'lines': lines}
    plan['revision'] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()[:20]
    return plan


def srt_time(seconds):
    remaining = round(seconds * 1000)
    hours, remaining = divmod(remaining, 3600000)
    minutes, remaining = divmod(remaining, 60000)
    seconds, remaining = divmod(remaining, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02},{remaining:03}'


def wrap_caption(text, font, width):
    lines, current = [], ''
    for character in text:
        if current and font.getlength(current + character) > width:
            lines.append(current.rstrip())
            current = ''
        current += character
    if current:
        lines.append(current.rstrip())
    return lines


def encode(command, *, required_headroom=DRAMA_VIDEO_HEADROOM):
    result = run_encoder(command, timeout=180, required_headroom=required_headroom)
    if result.returncode:
        raise RuntimeError('Drama media render failed: ' + (result.stderr or '')[-800:])


class ShortDramaMixin:
    def _drama_plan(self, owner_id, project_id):
        project = self._project_or_404(owner_id, project_id)
        plan = (project.metadata or {}).get('short_drama')
        if project.project_type != 'short_drama' or not plan:
            fail('DRAMA_PLAN_REQUIRED', 'Create a short drama project and save its cast and dialogue first.')
        return project, plan

    def save_drama_plan(self, owner_id, project_id, payload):
        project = self._project_or_404(owner_id, project_id)
        if project.project_type != 'short_drama':
            fail('DRAMA_PROJECT_REQUIRED', 'Create a project with type Short drama first.')
        plan = parse_plan(payload)
        previous = (project.metadata or {}).get('short_drama') or {}
        if previous.get('revision') == plan['revision']:
            return self.get_project(owner_id, project_id)
        if any(r.kind in {'audio', 'video', 'image'} for r in self.store.list_assets(project_id, owner_id)) or any(
            r.status in {'QUEUED', 'RUNNING'} for r in self.store.list_jobs(project_id, owner_id)
        ):
            fail('DRAMA_MEDIA_EXISTS', 'Create a new project to change a drama after media generation has started.')
        project.metadata = {**(project.metadata or {}), 'short_drama': plan}
        project.status = 'storyboarded'
        self.store.save_project(project)
        self.store.delete_scenes(project_id, owner_id)
        cast = '; '.join(f"{r['name']}: {r['description']}" for r in plan['characters'])
        for index, line in enumerate(plan['lines'], 1):
            prompt = (f"Cinematic realistic live-action short drama. {plan['setting']} Cast: {cast}. "
                f"Full-body two-person shot, {line['speaker']} gestures naturally while the other listens. "
                'Subtle body movement, grounded feet, natural hands, slow camera push-in. '
                'Consistent wardrobe and setting. No text, logos, subtitles or watermark.')
            self.store.save_scene(CreativeScene(id=new_id('cscene'), project_id=project_id, owner_id=owner_id,
                index=index, heading=f"{line['speaker']} — shot {index}", description=plan['setting'],
                visual_prompt=prompt, voiceover_text=line['text'], subtitle_text=f"{line['speaker']}: {line['text']}",
                duration_seconds=5, transition_note='Dialogue cut', music_mood_note='No music'))
        self._save_text_asset(owner_id=owner_id, project_id=project_id, kind='script',
            title='Short drama dialogue', content=plan['dialogue'], metadata={'drama_revision': plan['revision'], 'planning_only': True})
        return self.get_project(owner_id, project_id)

    def _drama_asset(self, owner_id, project_id, plan, kind, index):
        for row in reversed(self.store.list_assets(project_id, owner_id)):
            meta = row.metadata or {}
            if row.kind != kind or row.status != 'GENERATED' or not row.url:
                continue
            if kind == 'audio':
                matches = meta.get('drama_revision') == plan['revision'] and meta.get('line_index') == index
            else:
                provider = meta.get('provider_result') or {}
                matches = (provider.get('brief') or {}).get('scene_index') == index and provider.get('provider') != 'nova_ffmpeg_fallback'
            path = _resolve_creative_media_url(row.url)
            if matches and path and path.is_file():
                return row
        return None

    def generate_drama_voices(self, owner_id, project_id, *, job=None):
        _, plan = self._drama_plan(owner_id, project_id)
        job = job or self._start_job(owner_id, project_id, 'voice')
        ids = []
        try:
            for index, line in enumerate(plan['lines'], 1):
                previous = self._drama_asset(owner_id, project_id, plan, 'audio', index)
                if previous:
                    ids.append(previous.id)
                    continue
                result = voice_provider().generate(script=line['text'], voice=line['voice'])
                path = _resolve_creative_media_url(result.get('url'))
                if not result.get('asset_generated') or not path or not path.is_file():
                    fail('DRAMA_VOICE_FAILED', result.get('message') or 'Dialogue audio was not generated.')
                asset = self._save_text_asset(owner_id=owner_id, project_id=project_id, kind='audio',
                    title=f"{index}. {line['speaker']} dialogue", content=line['text'], url=result['url'],
                    metadata={'drama_revision': plan['revision'], 'line_index': index, 'speaker': line['speaker'], 'voice': line['voice']})
                ids.append(asset.id)
            self._finish_job(job, status='GENERATED', message='Separate character dialogue voices generated.', asset_ids=ids)
            return {'status': 'GENERATED', 'job': job.as_dict()}
        except Exception as exc:
            self._finish_job(job, status='ERROR', message=str(exc), asset_ids=ids)
            raise

    @serialized_media
    def assemble_drama(self, owner_id, project_id, *, job=None):
        project, plan = self._drama_plan(owner_id, project_id)
        job = job or self._start_job(owner_id, project_id, 'short_video_assembly')
        output = None
        try:
            import imageio_ffmpeg
            from PIL import Image, ImageDraw, ImageFont
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            pairs = []
            for index, line in enumerate(plan['lines'], 1):
                clip = self._drama_asset(owner_id, project_id, plan, 'video', index)
                audio = self._drama_asset(owner_id, project_id, plan, 'audio', index)
                if not clip or not audio:
                    fail('DRAMA_MEDIA_REQUIRED', f'Generate real AI motion and dialogue audio for shot {index} before rendering.')
                pairs.append((clip, audio, line))
            root, prefix = _creative_media_root_and_prefix()
            root.mkdir(parents=True, exist_ok=True)
            stem = f"nova-drama-{new_id('render').split('_', 1)[-1]}"
            output = root / (stem + '.mp4')
            vertical = project.platform in {'TikTok', 'Instagram', 'YouTube Shorts'}
            width, height = (720, 1280) if vertical else (1280, 720)
            timeline, captions, offset = [], [], 0.0
            with tempfile.TemporaryDirectory(prefix='nova-drama-') as tmp:
                tmp = Path(tmp)
                for index, (clip, audio, line) in enumerate(pairs, 1):
                    wav = tmp / f'{index}.wav'
                    encode([ffmpeg, '-y', '-i', str(_resolve_creative_media_url(audio.url)), '-ar', '24000', '-ac', '1', str(wav)], required_headroom=DRAMA_AUDIO_HEADROOM)
                    with wave.open(str(wav)) as recording:
                        duration = recording.getnframes() / recording.getframerate() + 0.25
                    caption = f"{line['speaker']}: {line['text']}"
                    font = ImageFont.load_default(size=30)
                    caption_lines = wrap_caption(caption, font, width - 60)
                    panel = Image.new('RGBA', (width, max(120, 55 + 40 * len(caption_lines))), (0, 0, 0, 185))
                    ImageDraw.Draw(panel).multiline_text((30, 25), '\n'.join(caption_lines),
                        font=font, fill='white', spacing=8)
                    png = tmp / f'{index}.png'
                    panel.save(png)
                    segment = tmp / f'{index}.mp4'
                    encode([ffmpeg, '-y', '-threads', '1', '-filter_complex_threads', '1',
                        '-i', str(_resolve_creative_media_url(clip.url)), '-i', str(wav), '-threads', '1', '-loop', '1', '-i', str(png),
                        '-filter_complex', f'[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps=25,tpad=stop_mode=clone:stop_duration=60[v];[v][2:v]overlay=0:H-h-65,format=yuv420p[out];[1:a]apad=pad_dur=0.25[a]',
                        '-map', '[out]', '-map', '[a]', '-t', f'{duration:.3f}', '-c:v', 'libx264', '-threads', '1', '-preset', 'veryfast', '-tune', 'zerolatency',
                        '-crf', '23', '-c:a', 'aac', '-b:a', '128k', str(segment)])
                    timeline.append({'speaker': line['speaker'], 'text': line['text'], 'start': offset, 'end': offset + duration})
                    captions.append(f'{index}\n{srt_time(offset)} --> {srt_time(offset + duration)}\n{caption}\n')
                    offset += duration
                manifest = tmp / 'segments.txt'
                manifest.write_text(''.join(f"file '{tmp / f'{i}.mp4'}'\n" for i in range(1, len(pairs) + 1)))
                encode([ffmpeg, '-y', '-f', 'concat', '-safe', '0', '-i', str(manifest), '-c', 'copy', '-movflags', '+faststart', str(output)], required_headroom=DRAMA_AUDIO_HEADROOM)
            if not output.is_file() or output.stat().st_size < 1024:
                raise RuntimeError('Final drama video is empty.')
            subtitle = root / (stem + '.srt')
            subtitle.write_text('\n'.join(captions), encoding='utf-8')
            asset = self._save_text_asset(owner_id=owner_id, project_id=project_id, kind='video',
                title='Nova Studio short drama — dialogue motion preview', content=plan['dialogue'], url=f'{prefix}/{output.name}',
                metadata={'short_drama': True, 'drama_revision': plan['revision'], 'timeline': timeline, 'duration_seconds': offset,
                    'captions_burned_in': True, 'lip_sync_verified': False, 'publish_ready': False, 'quality_state': 'PREVIEW_ONLY',
                    'subtitle_url': f'{prefix}/{subtitle.name}'})
            self._save_text_asset(owner_id=owner_id, project_id=project_id, kind='subtitle', title='Short drama captions (SRT)',
                content='\n'.join(captions), url=f'{prefix}/{subtitle.name}')
            self._finish_job(job, status='GENERATED', message='Dialogue motion preview rendered; review continuity and lip sync before publishing.', asset_ids=[asset.id])
            return {'status': 'GENERATED', 'asset': asset.as_dict(), 'url': asset.url}
        except Exception as exc:
            if output:
                output.unlink(missing_ok=True)
            self._finish_job(job, status='ERROR', message=str(exc), asset_ids=[])
            raise
