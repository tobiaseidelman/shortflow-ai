from pathlib import Path
import shutil
import subprocess
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import upload_routes as uploads
from app.db import SessionLocal
from app.models import UploadJob, BackgroundVideo


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client
        with SessionLocal() as session:
            for job in session.query(UploadJob):
                uploads.staging(job).unlink(missing_ok=True)
            session.query(UploadJob).delete()
            session.commit()


@pytest.fixture
def video(tmp_path):
    if not shutil.which('ffmpeg'):
        pytest.skip('FFmpeg required')
    path=tmp_path/'video.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=10','-t','5','-c:v','libx264',str(path)],check=True)
    return path.read_bytes()


def create(client, size, name='video.mp4'):
    response=client.post('/api/uploads',json={'name':name,'size':size})
    assert response.status_code==201,response.text
    return response.json()['id']


def put(client,id,offset,data):
    return client.put(f'/api/uploads/{id}/chunks?offset={offset}',content=data)


def test_chunked_video_reassembles_exactly_and_indexes_clips(client, video):
    id=create(client,len(video))
    assert client.post(f'/api/uploads/{id}/complete').status_code==409
    assert put(client,id,7,b'wrong order').status_code==409
    offset=0
    for start in range(0,len(video),4096):
        chunk=video[start:start+4096]
        r=put(client,id,offset,chunk)
        assert r.status_code==200
        assert put(client,id,offset,chunk).json()==r.json()  # lost reply retry
        offset+=len(chunk)
    assert client.post(f'/api/uploads/{id}/complete').status_code==202
    job=client.get(f'/api/uploads/{id}').json()
    assert job['status']=='ready',job
    with SessionLocal() as session:
        row=session.get(BackgroundVideo,job['video_id'])
        assert Path(row.path).read_bytes()==video
    rows=client.get('/api/videos').json()
    assert next(v for v in rows if v['id']==job['video_id'])['clips']>0
    assert not uploads.compute_lock.locked()
    assert client.post(f'/api/uploads/{id}/complete').json()['video_id']==job['video_id']


def test_bounds_and_duplicate_conflicts(client):
    assert client.post('/api/uploads',json={'name':'video.mp4','size':uploads.MAX_BYTES+1}).status_code==422
    assert client.post('/api/uploads',json={'name':'script.py','size':3}).status_code==400
    id=create(client,739_000_000)
    assert put(client,id,0,b'').status_code==400
    assert put(client,id,0,b'a'*(uploads.CHUNK_BYTES+1)).status_code==413
    assert put(client,id,0,b'abc').status_code==200
    assert put(client,id,0,b'xyz').status_code==409
    assert put(client,id,-1,b'abc').status_code==400
    assert put(client,id,739_000_000,b'abc').status_code==400
    assert client.post('/api/uploads',json={'name':'other.mp4','size':10}).status_code==409
    assert client.delete(f'/api/uploads/{id}').status_code==200
    assert put(client,id,3,b'x').status_code==409
    assert client.get('/api/uploads/unknown').status_code==404


def test_corrupt_file_fails_without_polluting_library(client):
    before=client.get('/api/videos').json()
    id=create(client,10)
    put(client,id,0,b'notavideo!')
    client.post(f'/api/uploads/{id}/complete')
    result=client.get(f'/api/uploads/{id}').json()
    assert result['status']=='failed'
    assert client.get('/api/videos').json()==before
    with SessionLocal() as session:
        assert not uploads.staging(session.get(UploadJob,id)).exists()
    assert not uploads.compute_lock.locked()


def test_completed_transfer_can_wait_for_compute_slot(client, video):
    id=create(client,len(video))
    put(client,id,0,video)
    uploads.compute_lock.acquire()
    try:
        assert client.post(f'/api/uploads/{id}/complete').status_code==409
        assert client.get(f'/api/uploads/{id}').json()['received']==len(video)
    finally:
        uploads.compute_lock.release()
    client.post(f'/api/uploads/{id}/complete')
    assert client.get(f'/api/uploads/{id}').json()['status']=='ready'


def test_restart_preserves_partial_upload_and_cleans_interrupted_analysis(client):
    id=create(client,6)
    put(client,id,0,b'abc')
    uploads.recover_uploads()
    assert client.get(f'/api/uploads/{id}').json()['received']==3
    assert put(client,id,3,b'def').status_code==200
    with SessionLocal() as session:
        job=session.get(UploadJob,id)
        job.status='analyzing'
        session.commit()
        path=uploads.staging(job)
    uploads.recover_uploads()
    assert not path.exists()
    assert client.get(f'/api/uploads/{id}').json()['status']=='failed'


def test_uncommitted_file_tail_is_replaced_on_retry(client):
    id=create(client,6)
    put(client,id,0,b'abc')
    with SessionLocal() as session:
        path=uploads.staging(session.get(UploadJob,id))
    with path.open('ab') as stream:stream.write(b'partial uncommitted data')
    assert put(client,id,3,b'def').status_code==200
    assert path.read_bytes()==b'abcdef'
