import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.request import urlopen
import json

import cv2
import pytest
from fastapi.testclient import TestClient
from app.main import app

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('path,content_type', [
    ('/static/app.css', 'text/css'),
    ('/static/app.js', 'javascript'),
])
def test_static_assets(path, content_type):
    with TestClient(app) as client:
        response = client.get(path)
    assert response.status_code == 200
    assert content_type in response.headers['content-type']
    assert response.content


def test_start_from_another_directory(tmp_path):
    if not shutil.which('ffmpeg'):
        pytest.skip('FFmpeg is required for the start script')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, HOST='127.0.0.1', PORT=str(port),
               SHORTFLOW_DB_PATH=str(tmp_path / 'db.sqlite'),
               SHORTFLOW_STORAGE_DIR=str(tmp_path / 'videos'))
    with (tmp_path / 'server.log').open('w+') as log:
        process = subprocess.Popen(['bash', str(ROOT / 'start.sh')],
                                   cwd=tmp_path, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    log.seek(0)
                    pytest.fail(log.read())
                try:
                    with urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as r:
                        health = json.load(r)
                    break
                except (URLError, TimeoutError):
                    time.sleep(0.1)
            else:
                pytest.fail('Server did not start within 30 seconds')
            assert health['status'] == 'ok'
            assert health['storage_writable'] is True
            assert (tmp_path / 'db.sqlite').exists()
            assert (tmp_path / 'videos/uploads').is_dir()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def test_upload_analyze_render_download(tmp_path):
    if not shutil.which('ffmpeg'):
        pytest.skip('FFmpeg is required for video integration')
    source = tmp_path / 'sample.mp4'
    subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i',
                    'testsrc2=size=320x240:rate=10', '-t', '5',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)],
                   check=True, capture_output=True)
    with TestClient(app) as client:
        with source.open('rb') as video:
            response = client.post('/api/videos/upload',
                                   files={'file': ('sample.mp4', video, 'video/mp4')})
        assert response.status_code == 200, response.text
        assert response.json()['clips'] > 0
        response = client.post('/api/shorts', data={'duration': 1})
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'ready'
        download = client.get(response.json()['download'])
        assert download.status_code == 200
        assert download.headers['content-type'] == 'video/mp4'
    output = tmp_path / 'result.mp4'
    output.write_bytes(download.content)
    cap = cv2.VideoCapture(str(output))
    try:
        assert cap.isOpened()
        assert int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) == 1080
        assert int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) == 1920
        assert cap.get(cv2.CAP_PROP_FRAME_COUNT) > 0
    finally:
        cap.release()
