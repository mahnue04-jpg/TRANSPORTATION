"""Offline regression checks for PR406-based content/import corrections.

Run: python3 tools/check_content_import_offline.py
Uses real generation/models/video validator and exact service method ASTs.
DB/router initialization is excluded; this is not the full HTTP/SQLAlchemy suite.
No network or paid provider calls are possible in this harness.
"""
import ast
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
for name, rel in [('app','app'),('app.core','app/core'),('app.core.nova','app/core/nova'),
                  ('app.core.nova.creative_studio','app/core/nova/creative_studio')]:
    mod = ModuleType(name); mod.__path__ = [str(ROOT/'backend'/rel)]; sys.modules[name] = mod
P = 'app.core.nova.creative_studio.'
models = importlib.import_module(P+'models')
generation = importlib.import_module(P+'generation')
video_import = importlib.import_module(P+'video_import')
service_tree = ast.parse((ROOT/'backend/app/core/nova/creative_studio/service.py').read_text())
service_class = next(n for n in service_tree.body if isinstance(n,ast.ClassDef) and n.name=='CreativeStudioService')
error_class = next(n for n in service_tree.body if isinstance(n,ast.ClassDef) and n.name=='CreativeStudioError')
methods = {'_planning_content_options','generate_script','generate_caption','generate_storyboard',
           'generate_image_prompt','import_finished_video','open_asset_file'}
nodes = [copy.deepcopy(n) for n in service_class.body if isinstance(n,ast.FunctionDef) and n.name in methods]
for node in nodes: node.decorator_list=[]
ns = dict(Path=Path, tempfile=tempfile, hashlib=hashlib, Any=object, new_id=models.new_id,
          CreativeScene=models.CreativeScene, DURATIONS=models.DURATIONS, IMAGE_ASPECTS=('1:1','9:16','16:9','4:5'),
          _now=lambda:'now', BLOCK='BLOCK', screen_creative_text=lambda *a:{'decision':'ALLOW'})
ns.update({k:getattr(generation,k) for k in ['assemble_short_video','generate_content_pack']})
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),error_class,ast.ClassDef(name='ActualMethods',bases=[],keywords=[],body=nodes,decorator_list=[])],type_ignores=[])),str(ROOT/'backend/app/core/nova/creative_studio/service.py'),'exec'),ns)
Error=ns['CreativeStudioError']

class Record(SimpleNamespace):
    def as_dict(self): return vars(self).copy()

class Service(ns['ActualMethods']):
    def __init__(self,root):
        self.project=Record(id='project',owner_id='owner',project_type='explainer',title='Count apples',
            audience='Children ages 4–6',objective='Count to three',tone='gentle',platform='YouTube',duration_target=30,
            metadata={'approved_genova_narration':{'asset_id':'existing'}})
        self.brief=Record(topic='Counting to three with apples',cta='Count with your grown-up.',style='Six gentle illustrated scenes',audience='',objective='',tone='')
        self.assets=[]; self.scenes=[]; self.jobs=[]; self.store=self; self.root=root
    def _project_or_404(self,owner,pid):
        if (owner,pid)!=('owner','project'): raise Error('NOT_FOUND','Not found',http_status=404)
        return self.project
    def list_assets(self,pid,owner): self._project_or_404(owner,pid); return self.assets[:]
    def _save_text_asset(self,**kw):
        row=Record(id=models.new_id('asset'),metadata={},url=None,**{k:v for k,v in kw.items() if k not in {'metadata','url'}})
        row.metadata=kw.get('metadata',{}); row.url=kw.get('url'); self.assets.append(row); return row
    def _brief_for(self,*a): return self.brief
    def _brand_for(self,*a): return None
    def _start_job(self,*a): row=Record(id='job'); self.jobs.append(row); return row
    def _finish_job(self,*a,**kw): pass
    def save_project(self,row): return row
    def delete_scenes(self,*a): self.scenes=[]
    def save_scene(self,row): self.scenes.append(row); return row

SCRIPT='One apple. Add one more. Now there are two. Add one more apple. Count one, two, three! Great counting!'
class PlanningTests(unittest.TestCase):
    def setUp(self): self.svc=Service(Path('.'))
    def test_missing_lesson_script_stops_all_planners_before_jobs(self):
        for name in ['generate_script','generate_caption','generate_storyboard','generate_image_prompt']:
            with self.subTest(name=name), self.assertRaises(Error) as caught:
                getattr(self.svc,name)('owner','project')
            self.assertEqual(caught.exception.code,'LESSON_SCRIPT_REQUIRED')
        self.assertEqual(self.svc.jobs,[])
    def test_all_explainer_planners_preserve_lesson_without_advertising(self):
        self.svc._save_text_asset(kind='presenter_script',content=SCRIPT)
        script=self.svc.generate_script('owner','project')['pack']
        self.assertEqual(script['voiceover_script'],SCRIPT)
        self.assertEqual(script['subtitle_caption_text'],SCRIPT)
        story=self.svc.generate_storyboard('owner','project')
        self.assertEqual(len(story['scenes']),6)
        self.assertAlmostEqual(sum(s['duration_seconds'] for s in story['scenes']),30)
        self.assertEqual(' '.join(s['voiceover_text'] for s in story['scenes']),SCRIPT)
        self.assertEqual(len(set(s['visual_prompt'] for s in story['scenes'])),6)
        self.assertFalse(story['assembly']['timing_verified'])
        caption=self.svc.generate_caption('owner','project')['pack']
        prompt=self.svc.generate_image_prompt('owner','project')['asset']['content']
        all_text=json.dumps([story,caption,prompt])
        for unwanted in ['AI operations workspace','busywork','getamicor.com','research, admin']:
            self.assertNotIn(unwanted,all_text)
    def test_latest_saved_script_and_owner_scope(self):
        self.svc._save_text_asset(kind='presenter_script',content='Old lesson.')
        self.svc._save_text_asset(kind='presenter_script',content=SCRIPT)
        self.assertEqual(self.svc._planning_content_options('owner',self.svc.project)['reviewed_script'],SCRIPT)
        with self.assertRaises(Error): self.svc.generate_storyboard('other','project')
    def test_existing_marketing_path_still_works_without_lesson(self):
        self.svc.project.project_type='short_video'
        self.svc.brief.topic='AMICOR Nova operations'
        result=self.svc.generate_storyboard('owner','project')
        self.assertIn('Busywork piles up fast',result['assembly']['full_script'])

class ImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(); cls.root=Path(cls.temp.name)
        cls.clip=cls.root/'fixture.mp4'
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=blue:s=160x160:r=10',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=24000','-t','0.5',
            '-threads','1','-c:v','libx264','-c:a','aac','-movflags','+faststart',str(cls.clip)],check=True)
        cls.data=cls.clip.read_bytes()
    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(); self.root=Path(self.directory.name)
        self.svc=Service(self.root)
        media=ModuleType(P+'providers')
        media._creative_media_root_and_prefix=lambda:(self.root,'/media/test')
        media._resolve_creative_media_url=lambda url: self.root/Path(url).name if url else None
        sys.modules[media.__name__]=media
        ns['_creative_media_root_and_prefix']=media._creative_media_root_and_prefix
        ns['_resolve_creative_media_url']=media._resolve_creative_media_url
        ns['_download_filename']=lambda title,suffix,**kw:'imported'+suffix
    def tearDown(self): self.directory.cleanup()
    def test_real_import_reuse_download_and_no_implicit_approval(self):
        before=copy.deepcopy(self.svc.project.metadata)
        result=self.svc.import_finished_video('owner','project',self.data,content_type='video/mp4')
        asset=result['asset']; self.assertTrue(asset['metadata']['decode_verified'])
        for flag in ['publish_ready','commercial_complete','captions_verified','lip_sync_verified','provider_clearance_verified','paid_request_submitted']:
            self.assertFalse(asset['metadata'][flag])
        path,mime,name=self.svc.open_asset_file('owner','project',asset['id'])
        self.assertEqual(path.read_bytes(),self.data); self.assertEqual(mime,'video/mp4')
        self.assertEqual(self.svc.project.metadata,before)
        second=self.svc.import_finished_video('owner','project',self.data,content_type='video/mp4')
        self.assertTrue(second['reused']); self.assertEqual(second['asset']['id'],asset['id'])
        self.assertEqual(len(self.svc.assets),1)
        with self.assertRaises(Error): self.svc.open_asset_file('other','project',asset['id'])
    def test_invalid_and_unauthorized_uploads_leave_no_files_or_assets(self):
        for owner,data,mime in [('other',self.data,'video/mp4'),('owner',b'not a movie','video/mp4'),
                                 ('owner',self.data,'video/webm'),('owner',b'','video/mp4'),
                                 ('owner',self.data[:100],'video/mp4')]:
            with self.subTest(owner=owner,mime=mime,length=len(data)),self.assertRaises(Error):
                self.svc.import_finished_video(owner,'project',data,content_type=mime)
        self.assertEqual(list(self.root.iterdir()),[]); self.assertEqual(self.svc.assets,[])
    def test_oversize_file_blocked_before_decode(self):
        from unittest.mock import patch
        with patch.object(video_import,'MAX_VIDEO_BYTES',1), self.assertRaises(Error):
            self.svc.import_finished_video('owner','project',self.data,content_type='video/mp4')
        self.assertEqual(self.svc.assets,[])
    def test_missing_audio_rejected(self):
        silent=self.root/'silent.mp4'
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(self.clip),'-an','-c:v','copy',str(silent)],check=True)
        with self.assertRaises(ValueError): video_import.validate_video(silent)
    def test_failed_asset_persistence_removes_media(self):
        self.svc._save_text_asset=lambda **kw: (_ for _ in ()).throw(RuntimeError('DB unavailable'))
        with self.assertRaises(RuntimeError): self.svc.import_finished_video('owner','project',self.data,content_type='video/mp4')
        self.assertEqual(list(self.root.iterdir()),[])

class StoryStyleTests(unittest.TestCase):
    def test_story_thumbnail_uses_saved_cast_setting_and_dialogue(self):
        for setting in ['Gentle 2D cartoon orchard.', 'Realistic community garden drama.']:
            with self.subTest(setting=setting):
                svc = Service(Path('.'))
                svc.project.project_type = 'short_drama'
                svc.project.title = 'Sharing apples'
                plan = {'setting': setting, 'characters': [
                    {'name': 'Pip', 'description': 'Orange fox with blue scarf'},
                    {'name': 'Luna', 'description': 'Lavender rabbit'}],
                    'lines': [{'text': 'We have four apples.'}]}
                svc._drama_plan = lambda *args: (svc.project, plan)
                result = svc.generate_image_prompt('owner', 'project', aspect_ratio='16:9')
                prompt = result['asset']['content']
                for expected in [setting, 'Pip', 'Luna', 'Orange fox', 'four apples', '16:9']:
                    self.assertIn(expected, prompt)
                self.assertNotIn('Educational thumbnail', prompt)
                self.assertNotIn('getamicor.com', prompt)
                self.assertNotIn('business operations', prompt)
                self.assertFalse(result['asset']['metadata']['media_generated'])
                self.assertIsNone(result['url'])

    def test_story_thumbnail_requires_a_saved_plan_before_starting_job(self):
        svc = Service(Path('.'))
        svc.project.project_type = 'short_drama'
        def missing(*args):
            raise Error('DRAMA_PLAN_REQUIRED', 'Save cast and dialogue first.', http_status=422)
        svc._drama_plan = missing
        with self.assertRaises(Error):
            svc.generate_image_prompt('owner', 'project')
        self.assertEqual(svc.jobs, [])

    def test_resaving_legacy_plan_rebuilds_prompts_without_editing_dialogue(self):
        tree = ast.parse((ROOT/'backend/app/core/nova/creative_studio/drama.py').read_text())
        parser = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'parse_plan')
        voices = next(n for n in tree.body if isinstance(n, ast.Assign) and
                      any(isinstance(t, ast.Name) and t.id == 'VOICES' for t in n.targets))
        scope = dict(ns, hashlib=hashlib, json=json)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[voices, parser], type_ignores=[])),
                     'drama.py', 'exec'), scope)
        payload = {'setting': 'Gentle 2D cartoon orchard.', 'characters': [
            {'name': 'Pip', 'description': 'Orange fox', 'voice': 'nova'},
            {'name': 'Luna', 'description': 'Lavender rabbit', 'voice': 'onyx'}],
            'dialogue': 'Pip: One apple.\nLuna: Two apples.'}
        current = scope['parse_plan'](payload)
        legacy = {k: v for k, v in current.items() if k not in {'revision', 'visual_prompt_version'}}
        legacy_revision = hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()[:20]
        self.assertEqual(current['visual_prompt_version'], 2)
        self.assertNotEqual(current['revision'], legacy_revision)
        self.assertEqual(current['dialogue'], payload['dialogue'])
        self.assertEqual(scope['parse_plan'](payload)['revision'], current['revision'])

    def test_saved_story_style_is_not_overridden_by_live_action(self):
        tree = ast.parse((ROOT/'backend/app/core/nova/creative_studio/drama.py').read_text())
        mixin = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ShortDramaMixin')
        method = next(n for n in mixin.body if isinstance(n, ast.FunctionDef) and n.name == 'save_drama_plan')
        scope = dict(ns, parse_plan=lambda payload: payload)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
                     str(ROOT/'backend/app/core/nova/creative_studio/drama.py'), 'exec'), scope)
        for setting in ['Original gentle 2D cartoon in a sunny orchard.',
                        'Family-friendly realistic drama in a community garden.']:
            with self.subTest(setting=setting):
                svc = Service(Path('.'))
                svc.project.project_type = 'short_drama'
                svc.list_jobs = lambda *args: []
                svc.get_project = lambda *args: svc.project.as_dict()
                lines = [{'speaker': 'Pip' if i % 2 == 0 else 'Luna',
                          'text': f'Count apple {i + 1}.'} for i in range(6)]
                plan = {'setting': setting, 'characters': [
                    {'name': 'Pip', 'description': 'Orange fox with blue scarf'},
                    {'name': 'Luna', 'description': 'Lavender rabbit with green overalls'}],
                    'revision': 'test', 'lines': lines, 'dialogue': 'Saved dialogue'}
                scope['save_drama_plan'](svc, 'owner', 'project', plan)
                self.assertEqual(len(svc.scenes), 6)
                for scene, line in zip(svc.scenes, lines):
                    self.assertIn(setting, scene.visual_prompt)
                    self.assertNotIn('Cinematic realistic live-action', scene.visual_prompt)
                    self.assertIn('Orange fox with blue scarf', scene.visual_prompt)
                    self.assertEqual(scene.voiceover_text, line['text'])
                    self.assertEqual(scene.subtitle_text, f"{line['speaker']}: {line['text']}")

if __name__=='__main__': unittest.main(verbosity=2)
