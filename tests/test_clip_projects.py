import json
import math
from pathlib import Path
import shutil
import subprocess
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import clips_routes as routes, clips_engine as engine
from app.db import SessionLocal


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(engine, 'unload', lambda model: None)
    with TestClient(app) as client:
        yield client
    with SessionLocal() as session:
        for row in session.query(routes.ClipProject):
            shutil.rmtree(routes.folder(row), ignore_errors=True)
        session.query(routes.ClipProject).delete()
        session.commit()


@pytest.fixture
def video(tmp_path):
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg required')
    path = tmp_path / 'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=10',
                    '-f','lavfi','-i','sine=frequency=440:sample_rate=22050','-t','5',
                    '-c:v','libx264','-c:a','aac',str(path)],check=True)
    return path.read_bytes()


def new(client, data=b'abc'):
    r=client.post('/api/clip-projects',json={'name':'video.mp4','size':len(data)})
    assert r.status_code==201,r.text
    return r.json()['id']


def upload(client, video):
    id=new(client,video)
    assert client.post(f'/api/clip-projects/{id}/complete').status_code==409
    for offset in range(0,len(video),4096):
        block=video[offset:offset+4096]
        r=client.put(f'/api/clip-projects/{id}/chunks?offset={offset}',content=block)
        assert r.status_code==200,r.text
        assert client.put(f'/api/clip-projects/{id}/chunks?offset={offset}',content=block).json()==r.json()
    r=client.post(f'/api/clip-projects/{id}/complete')
    assert r.status_code==200,r.text
    return id


def cuts(client,id,clips,revision=0):
    return client.put(f'/api/clip-projects/{id}/clips',json={'revision':revision,'clips':clips})


def test_roundtrip_precise_export_original_audio_and_range(client,video):
    id=upload(client,video)
    preview=client.get(f'/api/clip-projects/{id}/source',headers={'Range':'bytes=0-99'})
    assert preview.status_code==206
    assert preview.content==video[:100]
    clips=[{'start':.3,'end':2.2,'title':'Primero'},{'start':2.2,'end':4.7,'title':'Continuación'}]
    saved=cuts(client,id,clips).json()
    assert saved['revision']==1
    assert client.post(f'/api/clip-projects/{id}/export',json={'revision':0}).status_code==409
    r=client.post(f'/api/clip-projects/{id}/export',json={'revision':1,'vertical':True})
    assert r.status_code==202,r.text
    job=client.get(f'/api/clip-projects/{id}').json()
    assert job['status']=='ready',job
    assert len(job['exports'])==2
    with SessionLocal() as session:
        row=session.get(routes.ClipProject,id)
        assert routes.source(row).read_bytes()==video
        for exported,cut in zip(job['exports'],clips):
            path=routes.folder(row)/exported['name']
            info=engine.metadata(path) if hasattr(engine,'metadata') else routes.metadata(path)
            assert (info['width'],info['height'])==(720,1280)
            assert abs(info['duration']-(cut['end']-cut['start']))<.15
            result=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-f','null','-'],capture_output=True)
            assert result.returncode==0,result.stderr
            assert client.get(exported['download']).status_code==200
    assert client.get(f'/api/clip-projects/{id}/files/source.mp4').status_code==404
    assert not routes.compute_lock.locked()


@pytest.mark.parametrize('clips',[
    [{'start':0,'end':6,'title':'Fuera'}],
    [{'start':2,'end':1,'title':'Invertido'}],
    [{'start':0,'end':3,'title':'A'},{'start':2,'end':4,'title':'B'}],
    [{'start':0,'end':.2,'title':'Corto'}],
    []])
def test_invalid_edits_do_not_change_saved_clips(client,video,clips):
    id=upload(client,video)
    assert cuts(client,id,clips).status_code==422
    assert client.get(f'/api/clip-projects/{id}').json()['revision']==0


def test_upload_bounds_and_delete_pending(client):
    assert client.post('/api/clip-projects',json={'name':'x.mp4','size':routes.MAX_SIZE+1}).status_code==422
    assert client.post('/api/clip-projects',json={'name':'x.exe','size':3}).status_code==400
    id=new(client)
    assert client.put(f'/api/clip-projects/{id}/chunks?offset=-1',content=b'a').status_code==400
    assert client.put(f'/api/clip-projects/{id}/chunks?offset=1',content=b'a').status_code==409
    assert client.put(f'/api/clip-projects/{id}/chunks',content=b'a'*(routes.CHUNK+1)).status_code==413
    assert client.put(f'/api/clip-projects/{id}/chunks',content=b'').status_code==400
    assert client.post('/api/clip-projects',json={'name':'other.mp4','size':5}).status_code==409
    assert client.delete(f'/api/clip-projects/{id}').status_code==200
    assert client.get(f'/api/clip-projects/{id}').status_code==404


def test_analysis_failure_keeps_original_and_allows_retry(client,video,monkeypatch):
    id=upload(client,video)
    def fail(*args):raise ValueError('No hay suspenso claro.')
    monkeypatch.setattr(engine,'propose',fail)
    assert client.post(f'/api/clip-projects/{id}/analyze').status_code==202
    job=client.get(f'/api/clip-projects/{id}').json()
    assert job['status']=='uploaded'
    assert job['message']=='No hay suspenso claro.'
    assert client.get(job['source']).content==video
    monkeypatch.setattr(engine,'propose',lambda *args:[{'start':0,'end':3,'title':'Prueba','reason':'Pendiente'}])
    assert client.post(f'/api/clip-projects/{id}/analyze').status_code==202
    job=client.get(f'/api/clip-projects/{id}').json()
    assert job['status']=='review' and job['clips'][0]['title']=='Prueba'
    assert not routes.compute_lock.locked()


def test_lock_revision_and_restart(client,video):
    id=upload(client,video)
    routes.compute_lock.acquire()
    try:assert client.post(f'/api/clip-projects/{id}/analyze').status_code==409
    finally:routes.compute_lock.release()
    saved=cuts(client,id,[{'start':0,'end':3,'title':'Guardado'}]).json()
    assert cuts(client,id,[{'start':1,'end':4,'title':'Viejo'}]).status_code==409
    with SessionLocal() as session:
        job=session.get(routes.ClipProject,id);job.status='exporting';session.commit()
    assert client.delete(f'/api/clip-projects/{id}').status_code==409
    assert cuts(client,id,[{'start':1,'end':4,'title':'Ocupado'}],1).status_code==409
    routes.recover()
    job=client.get(f'/api/clip-projects/{id}').json()
    assert job['status']=='review' and job['clips']==saved['clips']
    assert client.get(job['source']).content==video


def test_partial_export_survives_failure(client,video,monkeypatch):
    id=upload(client,video)
    cuts(client,id,[{'start':0,'end':2,'title':'Uno'},{'start':2,'end':4,'title':'Dos'}])
    real=engine.export_clip;counter=[]
    def export(*args):
        counter.append(1)
        if len(counter)>1:raise RuntimeError('disk full')
        real(*args)
    monkeypatch.setattr(engine,'export_clip',export)
    client.post(f'/api/clip-projects/{id}/export',json={'revision':1,'vertical':False})
    job=client.get(f'/api/clip-projects/{id}').json()
    assert job['status']=='review' and len(job['exports'])==1
    assert client.get(job['exports'][0]['download']).status_code==200
    assert not routes.compute_lock.locked()


def test_model_cannot_invent_timestamps_or_reveal_inside_clip():
    sentences=[{'id':i,'start':i*5,'end':i*5+4,'text':f'Frase {i}.'} for i in range(10)]
    good={'start_id':0,'end_id':3,'reveal_id':4,'title':'Desafío','reason':'El resultado viene después.'}
    result=engine.validate_proposals({'clips':[good,good]},sentences,50)
    assert len(result)==1 and result[0]['end']==19
    for change in ({'start_id':-1},{'end_id':2.5},{'reveal_id':3},{'reveal_id':100},{'start_id':True},{'title':None}):
        assert engine.validate_proposals({'clips':[good|change]},sentences,50)==[]
    assert engine.validate_proposals({'clips':[good]},sentences,50,maximum=12)==[]


def test_export_cleanup_on_timeout(tmp_path,monkeypatch):
    dest=tmp_path/'clip.mp4'
    def fail(*args,**kwargs):
        (tmp_path/'clip.partial.mp4').write_bytes(b'incomplete')
        raise subprocess.TimeoutExpired('ffmpeg',900)
    monkeypatch.setattr(subprocess,'run',fail)
    with pytest.raises(subprocess.TimeoutExpired):engine.export_clip('source.mp4',dest,0,5,True)
    assert not dest.exists() and not (tmp_path/'clip.partial.mp4').exists()


def test_automatic_pipeline_requires_visual_review(tmp_path,monkeypatch):
    sentences=[{'id':i,'start':i*5,'end':i*5+4,'text':f'Frase {i}.'} for i in range(10)]
    monkeypatch.setattr(engine,'transcribe',lambda *args:sentences)
    monkeypatch.setattr(engine.story_engine,'ensure_model',lambda *args:None)
    monkeypatch.setattr(engine,'unload',lambda *args:None)
    evidence=[]
    def visual(source,proposals,duration,progress):
        evidence.append(True)
        for item in proposals:item['visual']='La caja sigue cerrada antes del corte.'
    monkeypatch.setattr(engine,'visual_evidence',visual)
    answers=iter([json.dumps({'clips':[{'start_id':0,'end_id':3,'reveal_id':4,'title':'Caja','reason':'Falta abrirla.'}]}),
                  json.dumps({'keep':True,'reason':'No se ve aún el contenido.'})])
    monkeypatch.setattr(engine.story_engine,'complete',lambda *args:next(answers))
    result=engine.propose('video.mp4',tmp_path,50,3,90,tmp_path,lambda _:None)
    assert evidence and len(result)==1 and result[0]['end']==19
    assert 'Frase 0.' in result[0]['context']
    answers=iter([json.dumps({'clips':[{'start_id':0,'end_id':3,'reveal_id':4,'title':'Caja','reason':'Falta abrirla.'}]}),
                  json.dumps({'keep':False,'reason':'Ya se ve el resultado.'})])
    with pytest.raises(ValueError,match='revisión visual'):
        engine.propose('video.mp4',tmp_path,50,3,90,tmp_path,lambda _:None)


def test_transcription_joins_asr_chunks_at_sentence_boundaries(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace as NS
    monkeypatch.setattr(engine,'unload',lambda *args:None)
    monkeypatch.setattr(engine,'audio_samples',lambda *args:engine.np.zeros(16000,dtype=engine.np.float32))
    class Whisper:
        def __init__(self,*args,**kwargs):assert kwargs['compute_type']=='int8'
        def transcribe(self,*args,**kwargs):
            assert kwargs['word_timestamps'] is True
            return iter([
                NS(end=2,words=[NS(start=0,end=1,word='Esperá'),NS(start=1,end=2,word=' que')]),
                NS(end=9,words=[NS(start=2,end=3,word=' abra.'),NS(start=4,end=6,word='¿Ganó?'),NS(start=7,end=9,word='Sí.')])]),None
    monkeypatch.setitem(sys.modules,'faster_whisper',NS(WhisperModel=Whisper))
    result=engine.transcribe('source.mp4',tmp_path,lambda _:None)
    assert result[0]=={'id':0,'start':0,'end':3,'text':'Esperá que abra.'}
    assert len(result)==3
    monkeypatch.setitem(sys.modules,'faster_whisper',None)
    assert engine.transcribe('source.mp4',tmp_path,lambda _:None)==result


def test_real_mp4_audio_normalized_without_decoder_api(client,video,tmp_path):
    path=tmp_path/'source.mp4';path.write_bytes(video)
    samples=engine.audio_samples(path,tmp_path)
    assert samples.dtype==engine.np.float32
    assert abs(len(samples)/16000-5)<.1
    assert abs(samples).max()>.01
    assert not (tmp_path/'speech.pcm').exists()


def test_proposal_retries_short_cut_without_relaxing_limits(tmp_path,monkeypatch):
    sentences=[{'id':i,'start':i*5,'end':i*5+4,'text':f'Frase {i}.'} for i in range(6)]
    monkeypatch.setattr(engine,'transcribe',lambda *args:sentences)
    monkeypatch.setattr(engine.story_engine,'ensure_model',lambda *args:None)
    monkeypatch.setattr(engine,'unload',lambda *args:None)
    monkeypatch.setattr(engine,'visual_evidence',lambda *args:None)
    short={'start_id':2,'end_id':3,'reveal_id':4,'title':'Caja','reason':'Falta abrirla.'}
    answers=iter([json.dumps({'clips':[short]}), json.dumps({'clips':[short|{'start_id':0}]}),
                  json.dumps({'keep':True,'reason':'Sigue cerrada.'})])
    calls=[]
    def complete(messages,schema):
        calls.append(list(messages))
        return next(answers)
    monkeypatch.setattr(engine.story_engine,'complete',complete)
    result=engine.propose('video.mp4',tmp_path,30,1,90,tmp_path,lambda _:None)
    assert result[0]['start']==0 and result[0]['end']==19
    assert len(calls[1])==4 and '12 y 90' in calls[1][-1]['content']
    assert (tmp_path/'proposal-0-0.json').exists()
