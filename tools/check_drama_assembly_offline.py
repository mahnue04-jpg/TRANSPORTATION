"""Exercise the actual drama assembler with local fixtures, never providers.

Run: python3 tools/check_drama_assembly_offline.py
Requires ffmpeg, ffprobe and Pillow. Loads the exact assembly method AST;
Storage, job bookkeeping and encoder invocation are test adapters; the
production memory-headroom watchdog is not covered by this harness.
Colored fixture clips and tones are not AI animation or verified narration.
"""
import ast
import array
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'backend/app/core/nova/creative_studio/drama.py'
FFMPEG = shutil.which('ffmpeg')
FFPROBE = shutil.which('ffprobe')
runtime_spec = importlib.util.spec_from_file_location(
    'drama_test_media_runtime', SOURCE.with_name('media_runtime.py'))
runtime = importlib.util.module_from_spec(runtime_spec)
runtime_spec.loader.exec_module(runtime)


def command(args):
    return subprocess.run(args, check=True, capture_output=True, timeout=180)


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nova-drama-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        tree = ast.parse(SOURCE.read_text())
        mixin = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ShortDramaMixin')
        method = next(n for n in mixin.body if isinstance(n, ast.FunctionDef) and n.name == 'assemble_drama')
        helpers = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'srt_time', 'wrap_caption'}]
        self.encoded = []

        def encode(args, **kwargs):
            self.encoded.append(args)
            command(args)

        def fail(code, message):
            raise ValueError(code + ': ' + message)

        self.scope = dict(Path=Path, tempfile=tempfile, wave=wave, encode=encode, fail=fail,
                          serialized_media=runtime.serialized_media,
                          DRAMA_AUDIO_HEADROOM=0, new_id=lambda _: 'render_fixture',
                          _resolve_creative_media_url=lambda url: Path(url),
                          _creative_media_root_and_prefix=lambda: (self.root, '/media/test'))
        exec(compile(ast.fix_missing_locations(ast.Module(body=helpers + [method], type_ignores=[])),
                     str(SOURCE), 'exec'), self.scope)
        self.lines = [{'speaker': 'Pip' if i % 2 == 0 else 'Luna',
                       'text': f'Scene {i + 1}: count the apples.'} for i in range(6)]
        self.plan = dict(revision='fixture', lines=self.lines,
                         dialogue='\n'.join(f"{r['speaker']}: {r['text']}" for r in self.lines))
        self.saved, self.finished, self.media = [], [], {}

        def save(**kwargs):
            self.saved.append(kwargs)
            return SimpleNamespace(id=f'asset_{len(self.saved)}', url=kwargs.get('url'),
                                   as_dict=lambda: kwargs)

        self.service = SimpleNamespace(
            _drama_plan=lambda *args: (SimpleNamespace(platform='YouTube'), self.plan),
            _start_job=lambda *args: 'job',
            _drama_asset=lambda owner, project, plan, kind, index: self.media.get((kind, index)),
            _save_text_asset=save,
            _finish_job=lambda *args, **kwargs: self.finished.append(kwargs))
        # Adapter only selects the installed local ffmpeg; no package download.
        shim = ModuleType('imageio_ffmpeg')
        shim.get_ffmpeg_exe = lambda: FFMPEG
        self.modules = patch.dict(sys.modules, {'imageio_ffmpeg': shim})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_missing_media_cannot_create_a_completed_video(self):
        with self.assertRaisesRegex(ValueError, 'DRAMA_MEDIA_REQUIRED'):
            self.scope['assemble_drama'](self.service, 'owner', 'project')
        self.assertEqual(self.encoded, [])
        self.assertEqual(self.saved, [])
        self.assertEqual(self.finished[-1]['status'], 'ERROR')

    def test_six_scenes_audio_captions_and_thirty_second_mp4(self):
        colors = ['red', 'green', 'blue', 'yellow', 'magenta', 'cyan']
        for index, color in enumerate(colors, 1):
            clip = self.root / f'clip{index}.mp4'
            audio = self.root / f'audio{index}.wav'
            command([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                     f'color=c={color}:s=320x180:r=25:d=1', '-c:v', 'libx264',
                     '-threads', '1', '-pix_fmt', 'yuv420p', str(clip)])
            command([FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                     f'sine=frequency={220 + index * 80}:duration=4.75',
                     '-ar', '24000', '-ac', '1', str(audio)])
            self.media['video', index] = SimpleNamespace(url=str(clip))
            self.media['audio', index] = SimpleNamespace(url=str(audio))

        result = self.scope['assemble_drama'](self.service, 'owner', 'project')
        self.assertEqual(result['status'], 'GENERATED')
        output = self.root / Path(result['url']).name
        info = json.loads(command([FFPROBE, '-v', 'error', '-show_streams',
                                   '-show_format', '-of', 'json', str(output)]).stdout)
        self.assertEqual({s['codec_type'] for s in info['streams']}, {'video', 'audio'})
        self.assertAlmostEqual(float(info['format']['duration']), 30, delta=0.12)
        command([FFMPEG, '-v', 'error', '-i', str(output), '-f', 'null', '-'])
        meta = self.saved[0]['metadata']
        self.assertFalse(meta['publish_ready'])
        self.assertFalse(meta['lip_sync_verified'])
        self.assertEqual(meta['quality_state'], 'PREVIEW_ONLY')
        self.assertTrue(meta['captions_burned_in'])
        self.assertEqual(len(meta['timeline']), 6)
        subtitle = (self.root / Path(meta['subtitle_url']).name).read_text()
        pixels = []
        for index, (row, line) in enumerate(zip(meta['timeline'], self.lines)):
            self.assertEqual(row['text'], line['text'])
            self.assertEqual(row['speaker'], line['speaker'])
            self.assertEqual((row['start'], row['end']), (index * 5, (index + 1) * 5))
            self.assertIn(f"{line['speaker']}: {line['text']}", subtitle)
            # Sample above the caption panel: each segment must retain its own color.
            pixels.append(command([FFMPEG, '-v', 'error', '-ss', str(index * 5 + 1),
                                   '-i', str(output), '-frames:v', '1', '-vf',
                                   'crop=2:2:100:100,format=rgb24', '-f', 'rawvideo', '-']).stdout)
            audio = command([FFMPEG, '-v', 'error', '-ss', str(index * 5 + 1),
                             '-i', str(output), '-t', '0.5', '-vn', '-ar', '8000',
                             '-ac', '1', '-f', 's16le', '-']).stdout
            samples = array.array('h', audio)
            if sys.byteorder != 'little':
                samples.byteswap()
            crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
            self.assertAlmostEqual(crossings * 2, 220 + (index + 1) * 80, delta=6)
            caption_pixels = command([FFMPEG, '-v', 'error', '-ss', str(index * 5 + 1),
                                      '-i', str(output), '-frames:v', '1', '-vf',
                                      'crop=1220:100:30:535,format=rgb24',
                                      '-f', 'rawvideo', '-']).stdout
            white_pixels = sum(min(caption_pixels[p:p + 3]) > 220
                               for p in range(0, len(caption_pixels), 3))
            self.assertGreater(white_pixels, 50, 'Caption text must be visible in every scene')
        self.assertEqual(len(set(pixels)), 6)
        self.assertIn('00:00:25,000 --> 00:00:30,000', subtitle)
        self.assertEqual(self.finished[-1]['status'], 'GENERATED')


if __name__ == '__main__':
    if not FFMPEG or not FFPROBE:
        raise SystemExit('Install ffmpeg and ffprobe before running this offline check.')
    unittest.main(verbosity=2)
