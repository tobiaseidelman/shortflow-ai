import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import main
from app.db import SessionLocal
from app.models import BackgroundVideo, Clip, ShortBackgrounds
from app.video_engine import render


def test_selection_is_enforced_and_remembered(monkeypatch, tmp_path):
    calls=[]
    def fake_render(sequence, paths, output, duration, **kwargs):
        calls.append({c.source_video_id for c in sequence})
        Path(output).write_bytes(b'mp4')
    monkeypatch.setattr(main, 'render', fake_render)
    with SessionLocal() as session:
        videos=[BackgroundVideo(name='choice',path=str(tmp_path/'video'),status='ready') for _ in range(2)]
        session.add_all(videos);session.flush();ids=[v.id for v in videos]
        for v in videos:
            session.add(Clip(source_video_id=v.id,start_time=0,end_time=4,duration=4,motion_score=1,visual_change_score=1,action_onset=0,quality_score=1,hook_score=1,loop_score=1))
        session.commit()
    try:
        with TestClient(app) as client:
            for raw in ('[]','[true]','[999999]','oops'):
                assert client.post('/api/shorts',data={'background_ids':raw,'duration':1}).status_code==400
                assert client.post('/api/render-jobs',data={'background_ids':raw,'story_id':999999}).status_code==400
            result=client.post('/api/shorts',data={'background_ids':json.dumps(ids[:1]),'duration':1})
            assert result.status_code==200, result.text
            sid=result.json()['id']
            assert calls[-1]=={ids[0]}
            assert client.post(f'/api/shorts/{sid}/regenerate-background').status_code==200
            assert calls[-1]=={ids[0]}
            assert client.post(f'/api/shorts/{sid}/regenerate-background',data={'background_ids':json.dumps(ids[1:])}).status_code==200
            assert calls[-1]=={ids[1]}
            with SessionLocal() as session:
                assert json.loads(session.get(ShortBackgrounds,sid).video_ids)==ids[1:]
    finally:
        with SessionLocal() as session:
            session.query(Clip).filter(Clip.source_video_id.in_(ids)).delete()
            session.query(BackgroundVideo).filter(BackgroundVideo.id.in_(ids)).delete()
            session.commit()


def test_crop_preview_and_render_remove_baked_in_borders(tmp_path):
    if not shutil.which('ffmpeg'):pytest.skip('FFmpeg required')
    frame=np.zeros((180,320,3),dtype=np.uint8);frame[:]=(0,0,255);frame[:,80:240]=(0,200,0)
    image=tmp_path/'source.png';cv2.imwrite(str(image),frame)
    source=tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-loop','1','-i',str(image),'-t','0.3','-c:v','libx264','-pix_fmt','yuv420p',str(source)],check=True,capture_output=True)
    with SessionLocal() as session:
        v=BackgroundVideo(name='bars',path=str(source),duration=.3,status='ready');session.add(v);session.commit();vid=v.id
    with TestClient(app) as client:
        assert client.put(f'/api/videos/{vid}/framing',data={'side_percent':41}).status_code==422
        assert client.put(f'/api/videos/{vid}/framing',data={'side_percent':25}).status_code==200
        row=next(v for v in client.get('/api/videos').json() if v['id']==vid)
        assert row['side_percent']==25
        preview=client.get(f'/api/videos/{vid}/preview?side_percent=25&second=0')
        assert preview.status_code==200
        decoded=cv2.imdecode(np.frombuffer(preview.content,np.uint8),cv2.IMREAD_COLOR)
        assert decoded.shape[1]==160
    out=tmp_path/'result.mp4'
    render([SimpleNamespace(duration=.3,start_time=0,source_video_id=vid)],{vid:source},out,.2,crops={vid:25})
    cap=cv2.VideoCapture(str(out));ok,result=cap.read();cap.release()
    assert ok
    # Both the foreground AND blurred fill must come from the cropped image.
    assert result[:,:,2].mean()<15
    assert result[:,:,1].mean()>180


def test_analysis_keeps_shots_and_does_not_cut_ordinary_motion(monkeypatch):
    from app import video_engine
    monkeypatch.setattr(video_engine,'metadata',lambda _: {'duration':30})
    samples=[(i*.35,2,6,100) for i in range(86)]
    samples[43]=(15.05,2,80,100)
    monkeypatch.setattr(video_engine,'_sample',lambda _:samples)
    clips=video_engine.analyze('unused')
    assert [(c['start_time'],c['end_time']) for c in clips]==[(0,15.05),(15.05,30)]
    samples[43]=(15.05,2,8,100)
    assert len(video_engine.analyze('unused'))==1


def test_reanalysis_preserves_history_and_replaces_selection(monkeypatch):
    from app import video_engine
    from app.models import BackgroundAnalysis
    from app.background_routes import selected_clips
    from app.work_lock import compute_lock
    fields=dict(start_time=0,end_time=20,duration=20,motion_score=1,visual_change_score=1,action_onset=0,quality_score=1,hook_score=1,loop_score=1)
    monkeypatch.setattr(video_engine,'analyze',lambda _: [fields])
    with SessionLocal() as session:
        v=BackgroundVideo(name='old-analysis',path='/mock',status='ready');session.add(v);session.flush();vid=v.id
        old=Clip(source_video_id=vid,**fields);session.add(old);session.flush();old_id=old.id;session.commit()
    try:
        with TestClient(app) as client:
            assert client.post(f'/api/videos/{vid}/reanalyze').status_code==202
            assert client.get(f'/api/videos/{vid}/analysis').json()['status']=='ready'
            assert not compute_lock.locked()
            with SessionLocal() as session:
                assert session.get(Clip,old_id) is not None
                selected=selected_clips(session,json.dumps([vid]))
                assert len(selected)==1 and selected[0].id!=old_id
            def fail(_):raise ValueError('bad video')
            monkeypatch.setattr(video_engine,'analyze',fail)
            client.post(f'/api/videos/{vid}/reanalyze')
            assert client.get(f'/api/videos/{vid}/analysis').json()['status']=='failed'
            with SessionLocal() as session:
                assert len(selected_clips(session,json.dumps([vid])))==1
            assert not compute_lock.locked()
    finally:
        with SessionLocal() as session:
            session.query(BackgroundAnalysis).filter_by(video_id=vid).delete()
            session.query(Clip).filter_by(source_video_id=vid).delete()
            session.query(BackgroundVideo).filter_by(id=vid).delete();session.commit()
