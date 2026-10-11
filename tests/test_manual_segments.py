import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import main
from app.db import SessionLocal
from app.models import BackgroundVideo, Clip, ManualBackgroundSegments
from app.background_routes import selected_clips
from app.work_lock import compute_lock

@pytest.fixture
def background(tmp_path):
    file = tmp_path/'source.mp4';file.write_bytes(b'0123456789')
    with SessionLocal() as s:
        video=BackgroundVideo(name='manual',path=str(file),duration=60,status='ready')
        s.add(video);s.flush()
        clip=Clip(source_video_id=video.id,start_time=0,end_time=60,duration=60,motion_score=1,visual_change_score=1,action_onset=0,quality_score=1,hook_score=1,loop_score=1)
        s.add(clip);s.commit();vid,original=video.id,clip.id
    yield vid,original
    with SessionLocal() as s:
        s.query(ManualBackgroundSegments).filter_by(video_id=vid).delete()
        s.query(Clip).filter_by(source_video_id=vid).delete()
        s.query(BackgroundVideo).filter_by(id=vid).delete();s.commit()


def test_manual_segments_persist_select_and_restore_without_destroying_history(background,monkeypatch):
    vid,original=background;url=f'/api/videos/{vid}/segments';calls=[]
    def render(seq,paths,output,duration,**kw):
        calls.append(([(c.start_time,c.end_time) for c in seq],duration));Path(output).write_bytes(b'mp4')
    monkeypatch.setattr(main,'render',render)
    with TestClient(app) as client:
        initial=client.get(url).json();assert initial['segments']==[] and not initial['manual']
        saved=client.put(url,json={'revision':'','segments':[{'start':20,'end':25},{'start':2,'end':8.75}]}).json()
        assert [s['start'] for s in saved['segments']]==[2,20]
        assert client.get(url).json()==saved
        with SessionLocal() as s:
            assert len(selected_clips(s,json.dumps([vid])))==2
            assert s.get(Clip,original) is not None
        result=client.post('/api/shorts',data={'clip_id':saved['segments'][0]['id'],'background_ids':json.dumps([vid])})
        assert result.status_code==200,result.text
        assert calls[-1]==([(2,8.75)],6.75)
        assert client.post('/api/shorts',data={'clip_id':original,'background_ids':json.dumps([vid])}).status_code==400
        # Stale tabs cannot overwrite new edits or reset them.
        assert client.put(url,json={'revision':'','segments':[{'start':0,'end':1}]}).status_code==409
        assert client.request('DELETE',url,json={'revision':''}).status_code==409
        old_id=saved['segments'][0]['id']
        edited=client.put(url,json={'revision':saved['revision'],'segments':[{'start':3,'end':9}]}).json()
        with SessionLocal() as s:assert s.get(Clip,old_id).start_time==2
        assert client.request('DELETE',url,json={'revision':edited['revision']}).status_code==200
        with SessionLocal() as s:assert [c.id for c in selected_clips(s,json.dumps([vid]))]==[original]
        assert next(v for v in client.get('/api/videos').json() if v['id']==vid)['clips']==1

@pytest.mark.parametrize('segments',[
    [],[{'start':0,'end':61}],[{'start':10,'end':9}],
    [{'start':0,'end':.1}],[{'start':True,'end':5}],
    [{'start':0,'end':4},{'start':3,'end':8}],
])
def test_invalid_intervals_leave_selection_unchanged(background,segments):
    vid,original=background
    with TestClient(app) as client:
        response=client.put(f'/api/videos/{vid}/segments',json={'revision':'','segments':segments})
        assert response.status_code==422,response.text
        with SessionLocal() as s:assert [c.id for c in selected_clips(s,json.dumps([vid]))]==[original]
        assert not compute_lock.locked()

def test_source_supports_seek_ranges_and_save_respects_active_job(background):
    vid,_=background
    with TestClient(app) as client:
        response=client.get(f'/api/videos/{vid}/source',headers={'Range':'bytes=3-6'})
        assert response.status_code==206
        assert response.content==b'3456'
        assert response.headers['content-range']=='bytes 3-6/10'
        compute_lock.acquire()
        try:
            assert client.put(f'/api/videos/{vid}/segments',json={'revision':'','segments':[{'start':0,'end':1}]}).status_code==409
        finally:compute_lock.release()

def test_export_renders_only_the_chosen_interval(background):
    import shutil, subprocess, cv2
    if not shutil.which('ffmpeg'): pytest.skip('FFmpeg required')
    vid,_=background
    with SessionLocal() as s:
        v=s.get(BackgroundVideo,vid);path=v.path;v.duration=3;s.commit()
    subprocess.run(['ffmpeg','-y','-v','error',
        '-f','lavfi','-i','color=red:s=160x90:r=10:d=1',
        '-f','lavfi','-i','color=green:s=160x90:r=10:d=1',
        '-f','lavfi','-i','color=blue:s=160x90:r=10:d=1',
        '-filter_complex','[0:v][1:v][2:v]concat=n=3:v=1:a=0[out]',
        '-map','[out]','-c:v','libx264','-pix_fmt','yuv420p',path],check=True,capture_output=True)
    with TestClient(app) as client:
        saved=client.put(f'/api/videos/{vid}/segments',json={'revision':'','segments':[{'start':1.2,'end':1.8}]}).json()
        response=client.post('/api/shorts',data={'clip_id':saved['segments'][0]['id'],'background_ids':json.dumps([vid])})
        assert response.status_code==200,response.text
        from app.models import Short
        with SessionLocal() as s: output=s.get(Short,response.json()['id']).output_path
    cap=cv2.VideoCapture(output)
    try:
        duration=cap.get(cv2.CAP_PROP_FRAME_COUNT)/cap.get(cv2.CAP_PROP_FPS)
        assert abs(duration-.6)<.04
        for t in [0,.5]:
            cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,frame=cap.read();assert ok
            b,g,r=frame[frame.shape[0]//2,frame.shape[1]//2]
            assert int(g)>int(b)+50 and int(g)>int(r)+50
    finally:cap.release()
