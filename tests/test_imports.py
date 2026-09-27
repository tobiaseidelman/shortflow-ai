import json
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import import_routes, video_import
from app.db import SessionLocal
from app.models import BackgroundVideo, Clip, ImportSource, VideoImportJob

URL = 'https://youtu.be/J9dvPQuHz-I?si=e18ZSn8MWE4K59ft'


@pytest.mark.parametrize('url', [URL, 'https://www.youtube.com/watch?v=J9dvPQuHz-I&list=PLignore',
                                 'https://m.youtube.com/shorts/J9dvPQuHz-I'])
def test_canonical_video_only(url):
    assert video_import.youtube_url(url) == 'https://www.youtube.com/watch?v=J9dvPQuHz-I'


@pytest.mark.parametrize('url', ['http://127.0.0.1/video', 'file:///etc/passwd',
    'https://youtube.com.evil.example/watch?v=J9dvPQuHz-I',
    'https://user:password@youtube.com/watch?v=J9dvPQuHz-I',
    'https://youtube.com:443/watch?v=J9dvPQuHz-I', 'https://youtube.com/playlist?list=123'])
def test_rejects_non_video_urls(url):
    with pytest.raises(video_import.ImportFailure):
        video_import.youtube_url(url)


def test_requires_rights_before_download(monkeypatch):
    monkeypatch.setattr(import_routes, 'download_video', lambda *a: pytest.fail('Must not download'))
    with TestClient(app) as client:
        assert client.post('/api/import-url', data={'url': URL}).status_code == 400
        assert client.post('/api/import-url', data={'url': 'http://localhost', 'rights': True}).status_code == 400


def test_import_analyzes_real_video_and_persists_clips(tmp_path, monkeypatch):
    if not shutil.which('ffmpeg'):
        pytest.skip('FFmpeg required')
    sample = tmp_path / 'sample.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10',
                    '-t', '5', '-c:v', 'libx264', str(sample)], check=True)
    def download(url, directory):
        assert url == video_import.youtube_url(URL)
        target = Path(directory) / 'source.mp4'
        shutil.copyfile(sample, target)
        return target, '<b>Video title</b>'
    monkeypatch.setattr(import_routes, 'download_video', download)
    with TestClient(app) as client:
        response = client.post('/api/import-url', data={'url': URL, 'rights': True})
        assert response.status_code == 202
        job = client.get('/api/imports/' + response.json()['id']).json()
        assert job['status'] == 'ready', job
        video = next(v for v in client.get('/api/videos').json() if v['id'] == job['video_id'])
        assert video['clips'] > 0 and video['duration'] == pytest.approx(5)
        assert video['name'] == '<b>Video title</b>'
        with SessionLocal() as session:
            saved = session.get(BackgroundVideo, job['video_id'])
            assert Path(saved.path).exists()
            assert session.query(Clip).filter_by(source_video_id=saved.id).count() > 0
        assert not import_routes._lock.locked()


def test_failure_cleans_temp_and_can_retry(monkeypatch):
    directories = []
    def fail(url, directory):
        directories.append(Path(directory))
        (Path(directory) / 'source.part').write_bytes(b'partial')
        raise video_import.ImportFailure('YouTube pide iniciar sesión.')
    monkeypatch.setattr(import_routes, 'download_video', fail)
    with TestClient(app) as client:
        before = len(client.get('/api/videos').json())
        for _ in range(2):
            response = client.post('/api/import-url', data={'url': URL, 'rights': True})
            job = client.get('/api/imports/' + response.json()['id']).json()
            assert job['status'] == 'failed' and 'iniciar sesión' in job['message']
        assert len(client.get('/api/videos').json()) == before
    assert all(not path.exists() for path in directories)
    assert not import_routes._lock.locked()


def test_interrupted_import_is_recoverable():
    from datetime import datetime
    with SessionLocal() as session:
        source = ImportSource(url=URL, platform='youtube', status='running', rights_declared_at=datetime.utcnow())
        session.add(source);session.flush()
        session.add(VideoImportJob(id='interrupted-import', source_id=source.id, status='running'))
        session.commit()
    with TestClient(app) as client:
        assert client.get('/api/imports/interrupted-import').json()['status'] == 'failed'
        assert client.get('/api/imports/missing').status_code == 404
        import_routes._lock.acquire()
        try:
            assert client.post('/api/import-url', data={'url': URL, 'rights': True}).status_code == 409
        finally:
            import_routes._lock.release()


def test_downloader_is_bounded_and_uses_no_shell(tmp_path, monkeypatch):
    def run(command, **kwargs):
        assert kwargs['timeout'] == 1200 and not kwargs.get('shell')
        assert '--ignore-config' in command and '--no-playlist' in command
        assert command[command.index('--download-sections') + 1] == '*0-600'
        assert command[-1] == video_import.youtube_url(URL)
        (tmp_path / 'source.mp4').write_bytes(b'video')
        (tmp_path / 'source.info.json').write_text(json.dumps({'duration': 3627, 'title': 'Soap'}))
        return subprocess.CompletedProcess(command, 0, '', '')
    monkeypatch.setattr(video_import.subprocess, 'run', run)
    path, title = video_import.download_video(URL, tmp_path)
    assert path.name == 'source.mp4' and title == 'Soap'


def test_downloader_reports_access_restrictions(tmp_path, monkeypatch):
    monkeypatch.setattr(video_import.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess([], 1, '', 'Sign in to confirm you are not a bot'))
    with pytest.raises(video_import.ImportFailure, match='iniciar sesión'):
        video_import.download_video(URL, tmp_path)
