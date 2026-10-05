"""Create one narrated short or the two connected parts without holding HTTP open."""
import json
import logging
from pathlib import Path
from .work_lock import compute_lock
from uuid import uuid4
from fastapi import APIRouter, BackgroundTasks, Form, HTTPException
from .db import SessionLocal
from .models import Story, StoryGeneration, Short, BackgroundVideo, Clip, RenderJob, NarrationAsset, UsedClip
from . import narration
from .background_routes import selected_clips, crop_settings, remember_selection
from .video_engine import optimize, render

router = APIRouter()
_lock = compute_lock
_storage = None
logger = logging.getLogger(__name__)


def set_storage(path):
    global _storage
    _storage = Path(path)


def recover_renders():
    with SessionLocal() as session:
        for job in session.query(RenderJob).filter_by(status='running').all():
            job.status = 'failed'; job.message = 'El servidor se reinició. Volvé a generar los videos.'
        session.query(Short).filter_by(status='rendering').update({'status': 'failed'})
        session.commit()


def serialize(job):
    return {'id': job.id, 'status': job.status, 'message': job.message,
            'shorts': [{'id': sid, 'download': f'/api/shorts/{sid}/file'} for sid in json.loads(job.short_ids)]}


def run_job(job_id, snapshots, background_ids=''):
    def progress(message):
        with SessionLocal() as session:
            session.get(RenderJob, job_id).message = message
            session.commit()
    current_id = None
    try:
        for index, snapshot in enumerate(snapshots, 1):
            progress(f'Video {index} de {len(snapshots)}: preparando la narración…')
            with SessionLocal() as session:
                short = Short(story_id=snapshot['id'], duration=0, status='rendering')
                session.add(short); session.commit(); current_id = short.id
            folder = _storage / 'narration' / str(current_id)
            audio, captions, duration = narration.narrate(snapshot['text'], folder, _storage, progress)
            if duration > 600:
                raise ValueError('La narración supera 10 minutos. Acortá el texto antes de generar el video.')
            with SessionLocal() as session:
                clips = selected_clips(session, background_ids)
                sequence = optimize(clips, duration, session.query(Short).count())
                paths = {v.id: v.path for v in session.query(BackgroundVideo).all()}
                progress(f'Video {index} de {len(snapshots)}: creando fondo, voz y subtítulos…')
                background = folder / 'background.mp4'
                render(sequence, paths, background, duration, crops=crop_settings(session))
                remember_selection(session, current_id, clips)
                output = _storage / 'renders' / f'short_{current_id:04d}.mp4'
                narration.overlay(background, audio, captions, output, duration)
                background.unlink(missing_ok=True)
                short = session.get(Short, current_id)
                short.duration = duration; short.status = 'ready'; short.output_path = str(output)
                short.sequence_json = json.dumps([c.id for c in sequence])
                session.add(NarrationAsset(short_id=current_id, audio_path=str(audio), subtitle_path=str(captions), text_snapshot=snapshot['text']))
                for position, clip in enumerate(sequence):
                    clip.times_used += 1
                    session.add(UsedClip(clip_id=clip.id, short_id=current_id, position=position))
                job = session.get(RenderJob, job_id)
                job.short_ids = json.dumps(json.loads(job.short_ids) + [current_id])
                session.commit()
                current_id = None
        with SessionLocal() as session:
            job = session.get(RenderJob, job_id); job.status = 'ready'; job.message = 'Videos listos con voz y subtítulos.'
            session.commit()
    except Exception as exc:
        logger.exception('Narrated render failed: %s', job_id)
        with SessionLocal() as session:
            if current_id:
                session.get(Short, current_id).status = 'failed'
            job = session.get(RenderJob, job_id); job.status = 'failed'
            job.message = str(exc) if isinstance(exc, ValueError) else 'No se pudo completar el video. Revisá la conexión para descargar la voz, FFmpeg y el espacio disponible; podés reintentar.'
            session.commit()
    finally:
        _lock.release()


@router.post('/api/render-jobs', status_code=202)
def create_job(tasks: BackgroundTasks, story_id: int = Form(0), generation_id: str = Form(''), background_ids: str = Form('')):
    if bool(story_id) == bool(generation_id):
        raise HTTPException(400, 'Elegí una historia o un par de partes.')
    if not _lock.acquire(blocking=False):
        raise HTTPException(409, 'Ya hay una historia o video generándose. Esperá a que termine.')
    try:
        with SessionLocal() as session:
            if not session.query(Clip).first():
                raise HTTPException(400, 'Primero importá o subí un fondo de video.')
            chosen = selected_clips(session, background_ids)
            background_ids = json.dumps(sorted({c.source_video_id for c in chosen}))
            ids = [story_id]
            if generation_id:
                pair = session.get(StoryGeneration, generation_id)
                if not pair or pair.status not in ('ready', 'needs_review'):
                    raise HTTPException(404, 'No se encontró una historia completa de dos partes.')
                ids = [pair.part1_id, pair.part2_id]
            snapshots = []
            for sid in ids:
                story = session.get(Story, sid)
                if not story or not story.text.strip():
                    raise HTTPException(404, 'Historia no encontrada o vacía.')
                if len(story.text) > 6000:
                    raise HTTPException(400, 'Acortá la historia a 6000 caracteres como máximo.')
                snapshots.append({'id': sid, 'text': story.text})
            job = RenderJob(id=str(uuid4()), status='running', message='Preparando videos…', story_ids=json.dumps(ids))
            session.add(job); session.commit(); response = serialize(job)
        tasks.add_task(run_job, job.id, snapshots, background_ids)
        return response
    except Exception:
        _lock.release()
        raise


@router.get('/api/render-jobs')
def list_jobs():
    with SessionLocal() as session:
        return [serialize(j) for j in session.query(RenderJob).order_by(RenderJob.created_at.desc()).limit(20)]


@router.get('/api/render-jobs/{job_id}')
def get_job(job_id: str):
    with SessionLocal() as session:
        job = session.get(RenderJob, job_id)
        if not job: raise HTTPException(404, 'Generación no encontrada.')
        return serialize(job)


@router.put('/api/stories/{story_id}')
def edit_story(story_id: int, text: str = Form(..., min_length=1, max_length=6000)):
    if not text.strip(): raise HTTPException(400, 'La historia no puede quedar vacía.')
    with SessionLocal() as session:
        story = session.get(Story, story_id)
        if not story: raise HTTPException(404, 'Historia no encontrada.')
        story.text = text.strip(); session.commit()
    return {'status': 'saved'}
