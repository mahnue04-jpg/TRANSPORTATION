"""Real local H.264 validation; private storage is replaced with an offline adapter."""
import hashlib
import subprocess
from types import SimpleNamespace

import pytest

from app.core.nova.creative_studio import first_shot_storage as archive
from app.core.nova.creative_studio.video_import import validate_video


@pytest.fixture
def shot(tmp_path, monkeypatch):
    path = tmp_path / 'shot.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'color=c=blue:s=160x128:r=24', '-t', '5', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', str(path)], check=True)
    monkeypatch.setattr(archive, '_resolve_creative_media_url', lambda url: path if url == '/saved.mp4' else None)
    monkeypatch.setattr(archive.storage, 'enabled', lambda: True)
    return path


def test_silent_kling_shot_archives_original_bytes_under_owner_project(shot, monkeypatch):
    calls = []
    def put(owner, project, name, path, sha, **kw):
        assert sha == hashlib.sha256(shot.read_bytes()).hexdigest()
        calls.append((owner, project, name, path.read_bytes()))
        return f'private-studio-s3://{owner}/{project}/{name}'
    monkeypatch.setattr(archive.storage, 'put_original_file', put)
    saved = archive.archive_first_shot('owner', 'project', '/saved.mp4')
    repeated = archive.archive_first_shot('owner', 'project', '/saved.mp4')
    assert saved['url'] == repeated['url']
    assert calls[0][:2] == ('owner', 'project')
    assert saved['decode_verified'] is True
    assert saved['audio_codec'] is None
    assert saved['publish_ready'] is False
    assert saved['actor_movement_verified'] is False
    # Existing finished-video imports continue to require audio.
    with pytest.raises(ValueError):
        validate_video(shot)


@pytest.mark.parametrize('case', ['disabled', 'external', 'corrupt', 'storage_failure'])
def test_archive_failure_never_claims_a_saved_file(shot, monkeypatch, case):
    def forbidden(*a, **kw):
        raise AssertionError('No upload expected')
    monkeypatch.setattr(archive.storage, 'put_original_file', forbidden)
    url = '/saved.mp4'
    if case == 'disabled':
        monkeypatch.setattr(archive.storage, 'enabled', lambda: False)
    elif case == 'external':
        url = 'https://provider.invalid/video.mp4'
    elif case == 'corrupt':
        shot.write_bytes(b'not a playable video')
    else:
        def unavailable(*a, **kw):
            raise archive.storage.PrivateStorageError('unavailable')
        monkeypatch.setattr(archive.storage, 'put_original_file', unavailable)
    with pytest.raises((ValueError, archive.storage.PrivateStorageError)):
        archive.archive_first_shot('owner', 'project', url)


@pytest.mark.parametrize('storage_ok', [True, False])
def test_completed_task_handoff_preserves_job_and_recovers_without_new_render(monkeypatch, tmp_path, storage_ok):
    from app.core.nova.creative_studio import service, store
    from app.core.nova.creative_studio.models import CreativeAsset
    from app.core.nova.creative_studio import first_shot_readiness as readiness
    # Exercise the real service resume path. The provider adapter rejects POSTs.
    image = SimpleNamespace(id='image-1', kind='image', status='GENERATED', url='/image.png', metadata={})
    pending = CreativeAsset(id='video-1', project_id='project', owner_id='owner', kind='video',
                            title='Pending', content='', status='PROCESSING', url=None,
                            metadata={'provider_result': {'status': 'PROCESSING', 'task_id': 'same-task',
                                      'provider': 'fal_kling_video', 'brief': {'scene_index': 1}}})
    project = SimpleNamespace(id='project', title='Film', objective='Motion', platform='YouTube',
                              project_type='short_video', metadata={'first_shot_paid_claim': {
                                  'reference_image_asset_id': 'image-1', 'state': 'POST_ATTEMPTED'}})
    class Store:
        def list_assets(self, *a): return [image, pending]
        def list_scenes(self, *a): return [SimpleNamespace(index=1, heading='Scene', visual_prompt='Walk', description='')]
        def get_project(self, *a): return project
        def save_asset(self, asset): return asset
    monkeypatch.setattr(store, 'DbCreativeStudioStore', Store)
    monkeypatch.setattr(readiness, 'first_shot_readiness', lambda **kw: {'status': 'READY_TO_REQUEST', 'reference_image_asset_id': 'image-1'})
    monkeypatch.setattr(archive.storage, 'enabled', lambda: True)
    def generate(*, brief):
        assert brief['resume_task_id'] == 'same-task'
        return {'status': 'GENERATED', 'task_id': 'same-task', 'url': '/saved.mp4',
                'asset_generated': True, 'provider': 'fal_kling_video', 'brief': brief}
    provider = SimpleNamespace(provider_id='fal_kling_video', status=lambda: SimpleNamespace(status='AVAILABLE'), generate=generate)
    monkeypatch.setattr(service, 'video_provider', lambda: provider)
    def save(*a):
        if not storage_ok: raise RuntimeError('storage outage')
        return {'url': 'private-studio-s3://owner/project/imported_video_x.mp4', 'sha256': 'a'*64}
    monkeypatch.setattr(archive, 'archive_first_shot', save)
    job = SimpleNamespace(as_dict=lambda: {'id': 'same-job'})
    finishes = []
    fake = SimpleNamespace(store=Store(), _project_or_404=lambda *a: project,
                           preflight_quote=lambda *a: {'owner_budget_confirmed': True},
                           _brief_for=lambda *a: None,
                           _finish_job=lambda job, **kw: finishes.append(kw))
    result = service.CreativeStudioService.request_video_generation(
        fake, 'owner', 'project', job=job, single_shot_reference_id='image-1')
    assert result['asset']['id'] == 'video-1'
    if storage_ok:
        assert result['asset']['url'].startswith('private-studio-s3://owner/project/')
        assert result['asset']['metadata']['sha256'] == 'a'*64
        assert finishes[-1]['status'] == 'GENERATED'
    else:
        assert result['asset']['url'] is None
        assert result['asset']['metadata']['provider_result']['task_id'] == 'same-task'
        assert result['asset']['status'] == 'PROCESSING'
        assert finishes[-1]['status'] == 'RUNNING'
