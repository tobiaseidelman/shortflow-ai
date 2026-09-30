"""Bounded, resumable uploads; analysis runs after the upload response returns."""
from datetime import datetime, timedelta
import logging
import math
from pathlib import Path
import re
import shutil
from threading import Lock
from uuid import uuid4
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from .db import SessionLocal
from .models import UploadJob, BackgroundVideo, Clip
from .video_engine import metadata, analyze
from .work_lock import compute_lock

router = APIRouter()
MAX_BYTES = 1024 ** 3
CHUNK_BYTES = 4 * 1024 ** 2
_storage = None
_gate = Lock()
logger = logging.getLogger(__name__)


def set_storage(path):
    global _storage
    _storage = Path(path)
    (_storage / 'temp' / 'uploads').mkdir(parents=True, exist_ok=True)


def staging(job):
    return _storage / 'temp' / 'uploads' / (job.id + Path(job.name).suffix.lower())


def get_job(session, job_id):
    job = session.get(UploadJob, job_id)
    if not job:
        raise HTTPException(404, 'Subida no encontrada. Seleccioná el archivo de nuevo.')
    return job


def serialize(job):
    return {key: getattr(job, key) for key in ('id', 'name', 'size', 'received', 'status', 'message', 'video_id')} | {'chunk_size': CHUNK_BYTES}


def expire_uploads(session):
    for job in session.query(UploadJob).filter(UploadJob.status == 'uploading', UploadJob.created_at < datetime.utcnow() - timedelta(days=1)):
        staging(job).unlink(missing_ok=True)
        job.status = 'failed'
        job.message = 'La subida venció después de 24 horas. Volvé a seleccionar el archivo.'


def recover_uploads():
    with _gate, SessionLocal() as session:
        expire_uploads(session)
        for job in session.query(UploadJob).filter_by(status='analyzing'):
            staging(job).unlink(missing_ok=True)
            job.status = 'failed'
            job.message = 'El servidor se reinició durante el análisis. Volvé a subir el archivo.'
        session.commit()


class NewUpload(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0, le=MAX_BYTES)


@router.post('/api/uploads', status_code=201)
def create_upload(data: NewUpload):
    name = re.sub(r'[^A-Za-z0-9._-]', '_', Path(data.name).name)
    if Path(name).suffix.lower() not in ('.mp4', '.mov', '.webm'):
        raise HTTPException(400, 'Usá un archivo MP4, MOV o WebM.')
    with _gate, SessionLocal() as session:
        expire_uploads(session)
        session.commit()
        if session.query(UploadJob).filter_by(status='uploading').count() >= 1:
            raise HTTPException(409, 'Hay una subida pendiente. Reanudala con el mismo archivo o cancelala antes de empezar otra.')
        if shutil.disk_usage(_storage).free < data.size + 128 * 1024 ** 2:
            raise HTTPException(507, 'No hay espacio suficiente en Codespaces para guardar este archivo.')
        job = UploadJob(id=str(uuid4()), name=name, size=data.size)
        session.add(job)
        session.commit()
        return serialize(job)


@router.get('/api/uploads')
def list_uploads():
    with SessionLocal() as session:
        return [serialize(j) for j in session.query(UploadJob).order_by(UploadJob.created_at.desc()).limit(20)]


@router.get('/api/uploads/{job_id}')
def upload_status(job_id: str):
    with SessionLocal() as session:
        return serialize(get_job(session, job_id))


def save_chunk(job_id, offset, body):
    with _gate, SessionLocal() as session:
        job = get_job(session, job_id)
        if job.status != 'uploading':
            raise HTTPException(409, 'Esta subida ya no recibe datos.')
        if offset < 0 or offset + len(body) > job.size:
            raise HTTPException(400, 'El fragmento supera el tamaño declarado.')
        path = staging(job)
        if offset < job.received and offset + len(body) <= job.received and path.exists():
            with path.open('rb') as stream:
                stream.seek(offset)
                if stream.read(len(body)) == body:
                    return serialize(job)  # Reply lost after a successful write: safe retry.
        if offset != job.received:
            raise HTTPException(409, 'La posición no coincide. Volvé a pulsar SUBIR Y ANALIZAR para reanudar.')
        if job.received and (not path.exists() or path.stat().st_size < job.received):
            raise HTTPException(409, 'La subida está incompleta en el servidor. Cancelala y volvé a subir.')
        with path.open('r+b' if path.exists() else 'w+b') as stream:
            # Remove uncommitted bytes left by a failed database commit.
            stream.truncate(job.received)
            stream.seek(job.received)
            stream.write(body)
        job.received += len(body)
        job.message = f'Subido {round(job.received / job.size * 100)}%'
        session.commit()
        return serialize(job)


@router.put('/api/uploads/{job_id}/chunks')
async def put_chunk(job_id: str, request: Request, offset: int = 0):
    body = bytearray()
    async for block in request.stream():
        if len(body) + len(block) > CHUNK_BYTES:
            raise HTTPException(413, 'Cada fragmento puede ocupar como máximo 4 MB.')
        body.extend(block)
    if not body:
        raise HTTPException(400, 'El fragmento está vacío.')
    return await run_in_threadpool(save_chunk, job_id, offset, bytes(body))


def process_upload(job_id):
    destination = None
    source = None
    try:
        with SessionLocal() as session:
            job = get_job(session, job_id)
            source = staging(job)
            name, size = job.name, job.size
        info = metadata(source)
        if not math.isfinite(info['duration']) or info['duration'] < 1 or min(info['width'], info['height']) < 1:
            raise ValueError('No se pudo leer el video. Verificá que el archivo MP4 se reproduzca completo.')
        clips = analyze(source)
        if not clips:
            raise ValueError('El video no tiene clips utilizables. Usá un fondo de al menos 5 segundos.')
        destination = _storage / 'uploads' / (job_id + Path(name).suffix.lower())
        source.replace(destination)
        with SessionLocal() as session:
            video = BackgroundVideo(name=name, path=str(destination), size=size, status='ready',
                                    **{key: info[key] for key in ('duration', 'width', 'height')})
            session.add(video)
            session.flush()
            session.add_all([Clip(source_video_id=video.id, **clip) for clip in clips])
            job = get_job(session, job_id)
            job.video_id, job.status = video.id, 'ready'
            job.message = f'Fondo listo: {len(clips)} clips disponibles.'
            session.commit()
        destination = None
    except Exception as exc:
        logger.exception('Upload analysis failed: %s', job_id)
        with SessionLocal() as session:
            job = get_job(session, job_id)
            job.status = 'failed'
            job.message = str(exc) if isinstance(exc, ValueError) else 'No se pudo analizar o guardar el fondo. Revisá la terminal y el espacio disponible.'
            session.commit()
    finally:
        if source:
            source.unlink(missing_ok=True)
        if destination:
            destination.unlink(missing_ok=True)
        compute_lock.release()


@router.post('/api/uploads/{job_id}/complete', status_code=202)
def complete_upload(job_id: str, tasks: BackgroundTasks):
    with _gate, SessionLocal() as session:
        job = get_job(session, job_id)
        if job.status in ('analyzing', 'ready'):
            return serialize(job)
        if job.status != 'uploading':
            raise HTTPException(409, job.message)
        if job.received != job.size or not staging(job).exists() or staging(job).stat().st_size != job.size:
            raise HTTPException(409, 'Todavía faltan partes del archivo.')
        if not compute_lock.acquire(blocking=False):
            raise HTTPException(409, 'El archivo está subido. Esperá a que termine la historia o video actual y pulsá SUBIR Y ANALIZAR otra vez.')
        try:
            job.status = 'analyzing'
            job.message = 'Archivo recibido. Analizando el fondo… Podés seguir usando la web.'
            session.commit()
            result = serialize(job)
            tasks.add_task(process_upload, job.id)
            return result
        except Exception:
            compute_lock.release()
            raise


@router.delete('/api/uploads/{job_id}')
def cancel_upload(job_id: str):
    with _gate, SessionLocal() as session:
        job = get_job(session, job_id)
        if job.status not in ('uploading', 'failed'):
            raise HTTPException(409, 'El archivo ya se está analizando o está listo.')
        staging(job).unlink(missing_ok=True)
        job.status, job.message = 'failed', 'Subida cancelada.'
        session.commit()
    return {'status': 'cancelled'}
