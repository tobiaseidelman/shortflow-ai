"""Persistent progress for a single background video import at a time."""
from datetime import datetime
from pathlib import Path
import logging
from tempfile import TemporaryDirectory
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException
from .db import SessionLocal
from .models import BackgroundVideo, Clip, ImportSource, VideoImportJob
from .video_import import download_video, youtube_url, ImportFailure
from .video_engine import analyze, metadata

router = APIRouter()
_lock = Lock()
_storage = None
logger = logging.getLogger(__name__)


def set_storage(path):
    global _storage
    _storage = Path(path)


def recover_imports():
    with SessionLocal() as session:
        for job in session.query(VideoImportJob).filter_by(status='running').all():
            job.status = 'failed'
            job.message = 'El servidor se reinició. Volvé a importar el enlace.'
            source = session.get(ImportSource, job.source_id)
            source.status = 'failed'
        session.commit()


def serialize(job):
    return {'id': job.id, 'status': job.status, 'message': job.message, 'video_id': job.video_id}


def run_import(job_id):
    destination = None
    try:
        with SessionLocal() as session:
            job = session.get(VideoImportJob, job_id)
            url = session.get(ImportSource, job.source_id).url
            job.message = 'Descargando el video de YouTube… Puede tardar varios minutos.'
            session.commit()
        with TemporaryDirectory(prefix='youtube-', dir=_storage / 'temp') as temp:
            downloaded, title = download_video(url, temp)
            with SessionLocal() as session:
                session.get(VideoImportJob, job_id).message = 'Descarga lista. Analizando el video y detectando clips…'
                session.commit()
            video_metadata = metadata(downloaded)
            clips = analyze(downloaded)
            if not clips:
                raise ImportFailure('El video no contiene clips utilizables. Probá otro fondo.')
            destination = _storage / 'uploads' / (job_id + downloaded.suffix)
            downloaded.replace(destination)
            with SessionLocal() as session:
                job = session.get(VideoImportJob, job_id)
                video = BackgroundVideo(name=title, path=str(destination), **{k: video_metadata[k] for k in ('duration', 'width', 'height')},
                                        size=destination.stat().st_size, status='ready')
                session.add(video)
                session.flush()
                session.add_all([Clip(source_video_id=video.id, **clip) for clip in clips])
                job.video_id = video.id
                job.status = 'ready'
                job.message = f'Fondo importado: {len(clips)} clips disponibles.'
                session.get(ImportSource, job.source_id).status = 'ready'
                session.commit()
                destination = None
    except Exception as exc:
        logger.exception('Video import failed: %s', job_id)
        with SessionLocal() as session:
            job = session.get(VideoImportJob, job_id)
            job.status = 'failed'
            job.message = str(exc) if isinstance(exc, ImportFailure) else 'No se pudo analizar o guardar el video. Probá otro enlace o subí el archivo.'
            session.get(ImportSource, job.source_id).status = 'failed'
            session.commit()
    finally:
        if destination:
            destination.unlink(missing_ok=True)
        _lock.release()


@router.post('/api/import-url', status_code=202)
def import_url(background_tasks: BackgroundTasks, url: str = Form(..., max_length=2000), rights: bool = Form(False)):
    if not rights:
        raise HTTPException(400, 'Tenés que confirmar que contás con autorización para reutilizar el contenido.')
    try:
        canonical = youtube_url(url)
    except ImportFailure as exc:
        raise HTTPException(400, str(exc)) from exc
    if not _lock.acquire(blocking=False):
        raise HTTPException(409, 'Ya hay un fondo importándose. Esperá a que termine.')
    try:
        with SessionLocal() as session:
            source = ImportSource(url=canonical, platform='youtube', rights_declared_at=datetime.utcnow(), status='running')
            session.add(source)
            session.flush()
            job = VideoImportJob(id=str(uuid4()), source_id=source.id, status='running', message='Preparando la descarga…')
            session.add(job)
            session.commit()
            response = serialize(job)
        background_tasks.add_task(run_import, job.id)
        return response
    except Exception:
        _lock.release()
        raise


@router.get('/api/imports')
def list_imports():
    with SessionLocal() as session:
        return [serialize(job) for job in session.query(VideoImportJob).order_by(VideoImportJob.created_at.desc()).limit(20)]


@router.get('/api/imports/{job_id}')
def get_import(job_id: str):
    with SessionLocal() as session:
        job = session.get(VideoImportJob, job_id)
        if not job:
            raise HTTPException(404, 'Importación no encontrada.')
        return serialize(job)
