from pathlib import Path
import json
import shutil
import subprocess
import wave
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import render_routes, narration
from app.db import SessionLocal
from app.models import BackgroundVideo, Clip, Story, StoryGeneration, NarrationAsset, Short, RenderJob
from app.video_engine import optimize, metadata


def test_optimizer_handles_one_short_clip():
    c=SimpleNamespace(duration=4,similarity_group='a',source_video_id=1,times_used=0,hook_score=70,motion_score=50,visual_change_score=30,quality_score=40,cooldown_until=0)
    sequence=optimize([c],30)
    assert sum(x.duration for x in sequence)>=30


def test_invalid_render_duration_and_upload():
    with TestClient(app) as client:
        for duration in [-1,0,1000,'nan','inf']:
            assert client.post('/api/shorts',data={'duration':duration}).status_code==422
        assert client.post('/api/videos/upload',files={'file':('broken.mp4',b'not video','video/mp4')}).status_code==400


def fake_voice(text,folder,storage,progress):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    with wave.open(str(folder/'voice.wav'),'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(22050);audio.writeframes(b'\0\0'*22050)
    subtitles=folder/'captions.ass'
    subtitles.write_text('[Script Info]\nScriptType: v4.00+\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, Bold, BorderStyle, Outline, Alignment\nStyle: Default,DejaVu Sans,30,&HFFFFFF,&H000000,-1,1,2,5\n[Events]\nFormat: Layer, Start, End, Style, Text\nDialogue: 0,0:00:00.00,0:00:01.00,Default,Prueba\n')
    return folder/'voice.wav',subtitles,1.0


def test_pair_render_edit_and_regeneration_keep_audio(tmp_path,monkeypatch):
    if not shutil.which('ffmpeg'):pytest.skip('FFmpeg required')
    monkeypatch.setattr(narration,'narrate',fake_voice)
    source=tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=10','-t','5','-c:v','libx264',str(source)],check=True)
    with TestClient(app) as client:
        with source.open('rb') as f:
            assert client.post('/api/videos/upload',files={'file':('video.mp4',f,'video/mp4')}).status_code==200
        with SessionLocal() as session:
            parts=[Story(title=f'Parte {i}',text='Yo hice mi trabajo.',genre='Reddit',duration_target=30) for i in (1,2)]
            session.add_all(parts);session.flush()
            ids=[p.id for p in parts]
            session.add(StoryGeneration(id='render-pair',theme='Tema',duration=30,status='ready',title='Par',part1_id=ids[0],part2_id=ids[1]));session.commit()
        assert client.put(f'/api/stories/{ids[0]}',data={'text':'Yo cambié mi decisión.'}).status_code==200
        assert client.put(f'/api/stories/{ids[0]}',data={'text':'   '}).status_code==400
        r=client.post('/api/render-jobs',data={'generation_id':'render-pair'})
        assert r.status_code==202
        job=client.get('/api/render-jobs/'+r.json()['id']).json()
        assert job['status']=='ready',job
        assert len(job['shorts'])==2
        sid=job['shorts'][0]['id']
        with SessionLocal() as session:
            asset=session.get(NarrationAsset,sid)
            assert asset.text_snapshot=='Yo cambié mi decisión.'
            old_audio=Path(asset.audio_path).read_bytes()
        assert client.get(job['shorts'][0]['download']).status_code==200
        def no_voice(*args):pytest.fail('Regeneration must preserve audio')
        monkeypatch.setattr(narration,'narrate',no_voice)
        regen=client.post(f'/api/shorts/{sid}/regenerate-background')
        assert regen.status_code==200,regen.text
        with SessionLocal() as session:
            assert Path(session.get(NarrationAsset,sid).audio_path).read_bytes()==old_audio
            output=Path(session.get(Short,sid).output_path)
            assert metadata(output)['duration']==pytest.approx(1,abs=.1)
        # ffmpeg must find an audio stream in the final MP4.
        subprocess.run(['ffmpeg','-v','error','-i',str(output),'-map','0:a:0','-f','null','-'],check=True,capture_output=True)


def test_render_failure_releases_lock_and_is_retryable(monkeypatch):
    def fail(*args):raise ValueError('Fallo controlado')
    monkeypatch.setattr(narration,'narrate',fail)
    with TestClient(app) as client:
        with SessionLocal() as session:
            story=Story(title='Failure test',text='Yo revisé el texto.',genre='Reddit',duration_target=30)
            video=BackgroundVideo(name='Test',path='/unused',status='ready')
            session.add_all([story,video]);session.flush()
            sid=story.id
            session.add(Clip(source_video_id=video.id,start_time=0,end_time=4,duration=4,
                             motion_score=0,visual_change_score=0,action_onset=0,quality_score=0,
                             hook_score=0,loop_score=0))
            session.commit()
        r=client.post('/api/render-jobs',data={'story_id':sid})
        assert r.status_code==202
        job=client.get('/api/render-jobs/'+r.json()['id']).json()
        assert job['status']=='failed' and job['message']=='Fallo controlado'
        assert not render_routes._lock.locked()
        assert client.get('/api/render-jobs/missing').status_code==404
        assert client.post('/api/render-jobs',data={}).status_code==400


def test_restart_marks_render_failed():
    with SessionLocal() as session:
        session.add(RenderJob(id='interrupted-render',status='running',story_ids='[]'));session.commit()
    with TestClient(app) as client:
        assert client.get('/api/render-jobs/interrupted-render').json()['status']=='failed'
