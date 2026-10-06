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


@pytest.mark.parametrize('pair_status', ['ready', 'needs_review'])
def test_pair_render_edit_and_regeneration_keep_audio(tmp_path,monkeypatch,pair_status):
    if not shutil.which('ffmpeg'):pytest.skip('FFmpeg required')
    monkeypatch.setattr(narration,'narrate',fake_voice)
    source=tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=10','-t','5','-c:v','libx264',str(source)],check=True)
    with TestClient(app) as client:
        with source.open('rb') as f:
            uploaded=client.post('/api/videos/upload',files={'file':('video.mp4',f,'video/mp4')})
            assert uploaded.status_code==200
            selected_video=uploaded.json()['id']
        with SessionLocal() as session:
            parts=[Story(title=f'Parte {i}',text='Yo hice mi trabajo.',genre='Reddit',duration_target=30) for i in (1,2)]
            session.add_all(parts);session.flush()
            ids=[p.id for p in parts]
            session.add(StoryGeneration(id='render-pair-'+pair_status,theme='Tema',duration=30,status=pair_status,title='Par',part1_id=ids[0],part2_id=ids[1]));session.commit()
        assert client.put(f'/api/stories/{ids[0]}',data={'text':'Yo cambié mi decisión.'}).status_code==200
        assert client.put(f'/api/stories/{ids[0]}',data={'text':'   '}).status_code==400
        r=client.post('/api/render-jobs',data={'generation_id':'render-pair-'+pair_status,'background_ids':json.dumps([selected_video])})
        assert r.status_code==202
        job=client.get('/api/render-jobs/'+r.json()['id']).json()
        assert job['status']=='ready',job
        assert len(job['shorts'])==2
        with SessionLocal() as session:
            for entry in job['shorts']:
                short=session.get(Short,entry['id'])
                assert {session.get(Clip,cid).source_video_id for cid in json.loads(short.sequence_json)}=={selected_video}
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
            video_id=video.id
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
        # This fake source must not leak into later real-media integration tests.
        with SessionLocal() as session:
            session.query(Clip).filter_by(source_video_id=video_id).delete()
            session.query(BackgroundVideo).filter_by(id=video_id).delete()
            session.commit()


def test_restart_marks_render_failed():
    with SessionLocal() as session:
        session.add(RenderJob(id='interrupted-render',status='running',story_ids='[]'));session.commit()
    with TestClient(app) as client:
        assert client.get('/api/render-jobs/interrupted-render').json()['status']=='failed'


@pytest.mark.parametrize('sources', [2, 3])
def test_optimizer_alternates_sources_even_with_unequal_scores(sources):
    clips = [SimpleNamespace(duration=4,similarity_group=str(i),source_video_id=i,
             times_used=0,hook_score=100 if i==1 else 0,motion_score=100 if i==1 else 0,
             visual_change_score=100 if i==1 else 0,quality_score=100 if i==1 else 0,
             cooldown_until=0) for i in range(1,sources+1)]
    starts = []
    for generation in range(sources):
        sequence = optimize(clips, 48, generation)
        ids = [c.source_video_id for c in sequence]
        starts.append(ids[0])
        assert all(a != b for a,b in zip(ids,ids[1:]))
        assert max(ids.count(i) for i in range(1,sources+1)) - min(ids.count(i) for i in range(1,sources+1)) <= 1
        assert sum(c.duration for c in sequence) >= 48
    assert len(set(starts)) == sources


def test_resume_reuses_audio_and_completed_part_and_preview_is_short(tmp_path,monkeypatch):
    spoken=[]; overlays=[]
    def voice(text,folder,storage,progress):
        spoken.append(text)
        a,c,_=fake_voice(text,folder,storage,progress)
        return a,c,30
    def background(seq,paths,output,duration,**kwargs):Path(output).write_bytes(b'background')
    def overlay(bg,a,c,output,duration):
        overlays.append(duration)
        if len(overlays)==2:raise ValueError('Interrupción de prueba')
        Path(output).write_bytes(b'video')
    monkeypatch.setattr(narration,'narrate',voice)
    monkeypatch.setattr(render_routes,'render',background)
    monkeypatch.setattr(narration,'overlay',overlay)
    with TestClient(app) as client:
        with SessionLocal() as session:
            v=BackgroundVideo(name='resume',path='/mock',status='ready');session.add(v);session.flush();vid=v.id
            session.add(Clip(source_video_id=vid,start_time=0,end_time=4,duration=4,motion_score=0,visual_change_score=0,action_onset=0,quality_score=0,hook_score=0,loop_score=0))
            parts=[Story(title='Resume',text=('Yo cuento '+str(i)+' ')*30,genre='Reddit',duration_target=30) for i in (1,2)]
            session.add_all(parts);session.flush()
            session.add(StoryGeneration(id='resume-pair',theme='Tema',duration=30,status='ready',title='Par',part1_id=parts[0].id,part2_id=parts[1].id));session.commit()
        try:
            r=client.post('/api/render-jobs',data={'generation_id':'resume-pair','background_ids':json.dumps([vid])})
            jid=r.json()['id'];job=client.get('/api/render-jobs/'+jid).json()
            assert job['status']=='failed' and job['can_resume'] and len(job['shorts'])==1
            first_id=job['shorts'][0]['id']
            render_routes.recover_renders()
            # Changing the story after interruption must not change the saved render snapshot.
            client.put('/api/stories/'+str(parts[1].id),data={'text':'Texto cambiado.'})
            assert client.post('/api/render-jobs/'+jid+'/resume').status_code==202
            job=client.get('/api/render-jobs/'+jid).json()
            assert job['status']=='ready' and len(job['shorts'])==2
            assert job['shorts'][0]['id']==first_id
            assert len(spoken)==2
            assert client.post('/api/render-jobs/'+jid+'/resume').status_code==409
            r=client.post('/api/render-jobs',data={'generation_id':'resume-pair','background_ids':json.dumps([vid]),'preview':'true'})
            job=client.get('/api/render-jobs/'+r.json()['id']).json()
            assert job['preview'] and job['status']=='ready' and len(job['shorts'])==1
            assert overlays[-1]==12 and len(spoken[-1].split())==32
        finally:
            with SessionLocal() as session:
                session.query(Clip).filter_by(source_video_id=vid).delete();session.query(BackgroundVideo).filter_by(id=vid).delete();session.commit()


def test_optimizer_prefers_unused_nonoverlapping_intervals():
    def clip(start,uses,score):
        return SimpleNamespace(duration=4,start_time=start,similarity_group=str(start),source_video_id=1,times_used=uses,hook_score=score,motion_score=score,visual_change_score=score,quality_score=score,cooldown_until=0)
    old=clip(0,10,100);fresh=clip(10,0,50);overlap=clip(11,0,90);other=clip(25,0,20)
    sequence=optimize([old,fresh,overlap,other],8)
    assert old not in sequence
    assert other in sequence
    assert not (fresh in sequence and overlap in sequence)
