"""Durable source uploads, editable proposals and asynchronous clip exports."""
from datetime import datetime, timedelta
import json
import logging
import math
from pathlib import Path
import re
import shutil
from threading import Lock
from uuid import uuid4
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import String, Text, Integer, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from starlette.concurrency import run_in_threadpool
from .db import Base, SessionLocal
from .work_lock import compute_lock
from .video_engine import metadata
from . import clips_engine

router = APIRouter(prefix='/api/clip-projects')
_storage = None
_gate = Lock()
logger = logging.getLogger(__name__)
CHUNK = 4 * 1024**2
MAX_SIZE = 1024**3


class ClipProject(Base):
    __tablename__ = 'clip_projects'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(Integer)
    received: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(24), default='uploading')
    message: Mapped[str] = mapped_column(Text, default='Subiendo…')
    proposals: Mapped[str] = mapped_column(Text, default='[]')
    exports: Mapped[str] = mapped_column(Text, default='[]')
    revision: Mapped[int] = mapped_column(Integer, default=0)
    count: Mapped[int] = mapped_column(Integer, default=3)
    maximum: Mapped[int] = mapped_column(Integer, default=90)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


def set_storage(storage):
    global _storage
    _storage = Path(storage)
    (_storage / 'clip-projects').mkdir(parents=True, exist_ok=True)


def folder(job):
    return _storage / 'clip-projects' / job.id


def source(job):
    return folder(job) / 'source.mp4'


def get(session, id):
    job = session.get(ClipProject, id)
    if not job:
        raise HTTPException(404, 'Video de Clips no encontrado.')
    return job


def serialize(job):
    data = {k: getattr(job, k) for k in ('id', 'name', 'size', 'received', 'duration', 'status', 'message', 'revision', 'count', 'maximum')}
    return data | {'clips': json.loads(job.proposals), 'exports': json.loads(job.exports),
                   'chunk_size': CHUNK, 'source': f'/api/clip-projects/{job.id}/source' if job.duration else None}


def recover():
    with _gate, SessionLocal() as session:
        for job in session.query(ClipProject).filter(ClipProject.status.in_(['analyzing', 'exporting'])):
            job.status = 'review' if json.loads(job.proposals) else 'uploaded'
            job.message = 'El servidor se reinició. El original se conserva: podés retomar el análisis o exportar los clips.'
        session.commit()


class NewProject(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0, le=MAX_SIZE)
    count: int = Field(default=3, ge=1, le=6)
    maximum: int = Field(default=90, ge=20, le=120)


@router.post('', status_code=201)
def create(data: NewProject):
    if Path(data.name).suffix.lower() != '.mp4':
        raise HTTPException(400, 'Elegí un archivo MP4.')
    with _gate, SessionLocal() as session:
        for old in session.query(ClipProject).filter_by(status='uploading').all():
            if old.created_at < datetime.utcnow() - timedelta(days=1):
                source(old).unlink(missing_ok=True)
                old.status, old.message = 'failed', 'La subida venció. Seleccioná de nuevo el archivo.'
        session.commit()
        if session.query(ClipProject).filter_by(status='uploading').count():
            raise HTTPException(409, 'Ya hay una subida de Clips pendiente. Abrila para reanudarla o eliminarla.')
        if shutil.disk_usage(_storage).free < data.size * 2 + 256 * 1024**2:
            raise HTTPException(507, 'No hay espacio suficiente para el original y los recortes.')
        job = ClipProject(id=str(uuid4()), name=re.sub(r'[^\w. -]', '_', Path(data.name).name),
                          size=data.size, count=data.count, maximum=data.maximum)
        session.add(job)
        session.commit()
        folder(job).mkdir(parents=True, exist_ok=True)
        return serialize(job)


@router.get('')
def listing():
    with SessionLocal() as session:
        return [serialize(j) for j in session.query(ClipProject).order_by(ClipProject.created_at.desc()).limit(50)]


@router.get('/{id}')
def status(id: str):
    with SessionLocal() as session:
        return serialize(get(session, id))


def chunk(id, offset, body):
    with _gate, SessionLocal() as session:
        job = get(session, id)
        if job.status != 'uploading':
            raise HTTPException(409, 'El archivo ya está subido.')
        if offset < 0 or offset + len(body) > job.size:
            raise HTTPException(400, 'Fragmento fuera del archivo.')
        path = source(job)
        if offset < job.received and offset + len(body) <= job.received and path.exists():
            with path.open('rb') as stream:
                stream.seek(offset)
                if stream.read(len(body)) == body:
                    return serialize(job)
        if offset != job.received:
            raise HTTPException(409, 'La posición cambió. Volvé a elegir el mismo archivo para reanudar.')
        if job.received and (not path.exists() or path.stat().st_size < job.received):
            raise HTTPException(409, 'Faltan datos en el servidor. Eliminá esta subida y volvé a empezar.')
        with path.open('r+b' if path.exists() else 'w+b') as stream:
            stream.truncate(job.received)
            stream.seek(job.received)
            stream.write(body)
        job.received += len(body)
        session.commit()
        return serialize(job)


@router.put('/{id}/chunks')
async def put_chunk(id: str, request: Request, offset: int = 0):
    body = bytearray()
    async for block in request.stream():
        if len(body) + len(block) > CHUNK:
            raise HTTPException(413, 'Cada fragmento admite hasta 4 MB.')
        body.extend(block)
    if not body:
        raise HTTPException(400, 'Fragmento vacío.')
    return await run_in_threadpool(chunk, id, offset, bytes(body))


@router.post('/{id}/complete')
def complete(id: str):
    with _gate, SessionLocal() as session:
        job = get(session, id)
        if job.status != 'uploading':
            return serialize(job)
        path = source(job)
        if job.received != job.size or not path.exists() or path.stat().st_size != job.size:
            raise HTTPException(409, 'Todavía faltan partes del video.')
        info = metadata(path)
        if not math.isfinite(info['duration']) or not 3 <= info['duration'] <= clips_engine.MAX_DURATION or min(info['width'], info['height']) < 1:
            raise HTTPException(400, 'Usá un MP4 reproducible de entre 3 segundos y 30 minutos.')
        job.duration, job.status = info['duration'], 'uploaded'
        job.message = 'Original guardado. Buscá momentos con IA o marcá los recortes.'
        session.commit()
        return serialize(job)


def progress(id, message):
    with SessionLocal() as session:
        job = get(session, id)
        job.message = message
        session.commit()


def analyze_job(id):
    try:
        with SessionLocal() as session:
            job = get(session, id)
            args = (source(job), folder(job), job.duration, job.count, job.maximum, _storage)
        clips = clips_engine.propose(*args, lambda message: progress(id, message))
        with SessionLocal() as session:
            job = get(session, id)
            job.proposals = json.dumps(clips, ensure_ascii=False)
            job.revision += 1
            job.status = 'review'
            job.message = f'{len(clips)} propuestas listas. Revisá el contexto y el final antes de exportar: la IA puede equivocarse.'
            session.commit()
    except Exception as exc:
        logger.exception('Clip analysis failed: %s', id)
        with SessionLocal() as session:
            job = get(session, id)
            job.status = 'review' if json.loads(job.proposals) else 'uploaded'
            job.message = str(exc)[:600] if isinstance(exc, (ValueError, clips_engine.story_engine.StoryGenerationError)) else 'El análisis no terminó. El original está guardado; podés reintentar o marcar los cortes.'
            session.commit()
    finally:
        clips_engine.unload(clips_engine.VISION_MODEL)
        clips_engine.unload(clips_engine.story_engine.MODEL)
        compute_lock.release()


def reserve(job):
    if job.status in ('uploading', 'analyzing', 'exporting', 'failed') or not job.duration:
        raise HTTPException(409, 'Terminá la subida o la tarea actual primero.')
    if not compute_lock.acquire(blocking=False):
        raise HTTPException(409, 'Hay otra tarea de IA o video en curso. Esperá a que termine.')


@router.post('/{id}/analyze', status_code=202)
def analyze(id: str, tasks: BackgroundTasks):
    with _gate, SessionLocal() as session:
        job = get(session, id)
        reserve(job)
        try:
            job.status, job.message = 'analyzing', 'Preparando análisis de audio e imágenes…'
            session.commit()
            tasks.add_task(analyze_job, id)
            return serialize(job)
        except Exception:
            compute_lock.release()
            raise


class Cut(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    title: str = Field(min_length=1, max_length=120)
    reason: str = Field(default='', max_length=1100)


class Edits(BaseModel):
    revision: int = Field(ge=0)
    clips: list[Cut] = Field(min_length=1, max_length=12)


@router.put('/{id}/clips')
def save(id: str, data: Edits):
    with _gate, SessionLocal() as session:
        job = get(session, id)
        if job.status in ('uploading', 'analyzing', 'exporting', 'failed') or not job.duration:
            raise HTTPException(409, 'Esperá a que termine la tarea actual.')
        if data.revision != job.revision:
            raise HTTPException(409, 'Estos recortes cambiaron en otra pestaña. Volvé a abrir el video.')
        ranges = sorted(data.clips, key=lambda c: c.start)
        for i, cut in enumerate(ranges):
            if not 1 <= cut.end - cut.start <= 180 or cut.end > job.duration:
                raise HTTPException(422, 'Cada clip debe durar entre 1 y 180 segundos y quedar dentro del video.')
            if i and cut.start < ranges[i-1].end:
                raise HTTPException(422, 'Los clips se superponen. Ajustá los límites para no repetir momentos.')
        job.proposals = json.dumps([c.model_dump() for c in data.clips], ensure_ascii=False)
        job.revision += 1
        job.status, job.message = 'review', 'Recortes guardados. Exportá para descargar esta versión.'
        # Previous exports are kept but clearly carry their own revision and timecodes.
        session.commit()
        return serialize(job)


class ExportOptions(BaseModel):
    revision: int = Field(ge=0)
    vertical: bool = True


def export_job(id, revision, vertical):
    try:
        with SessionLocal() as session:
            job = get(session, id)
            cuts, path, directory = json.loads(job.proposals), source(job), folder(job)
        run = uuid4().hex
        exports = []
        for i, cut in enumerate(cuts):
            progress(id, f'Exportando clip {i+1} de {len(cuts)} con audio original…')
            name = f'{run}-{i+1}.mp4'
            clips_engine.export_clip(path, directory / name, cut['start'], cut['end'], vertical)
            exports.append({'name': name, 'title': cut['title'], 'start': cut['start'], 'end': cut['end'],
                            'revision': revision, 'download': f'/api/clip-projects/{id}/files/{name}'})
            # Keep successful outputs even if a later clip fails or the server restarts.
            with SessionLocal() as session:
                job = get(session, id)
                job.exports = json.dumps(exports)
                session.commit()
        with SessionLocal() as session:
            job = get(session, id)
            job.status, job.message = 'ready', 'Clips exportados. Podés reproducirlos y descargar cada MP4.'
            session.commit()
    except Exception:
        logger.exception('Clip export failed: %s', id)
        with SessionLocal() as session:
            job = get(session, id)
            job.status, job.message = 'review', 'La exportación se interrumpió. Conservamos el original, los cortes y los MP4 terminados. Podés reintentar.'
            session.commit()
    finally:
        compute_lock.release()


@router.post('/{id}/export', status_code=202)
def export(id: str, data: ExportOptions, tasks: BackgroundTasks):
    with _gate, SessionLocal() as session:
        job = get(session, id)
        if data.revision != job.revision or not json.loads(job.proposals):
            raise HTTPException(409, 'Guardá y revisá los recortes antes de exportar.')
        reserve(job)
        try:
            job.status, job.message = 'exporting', 'Preparando los MP4…'
            session.commit()
            tasks.add_task(export_job, id, job.revision, data.vertical)
            return serialize(job)
        except Exception:
            compute_lock.release()
            raise


@router.get('/{id}/source')
def preview(id: str):
    with SessionLocal() as session:
        job = get(session, id)
        if not job.duration or not source(job).exists():
            raise HTTPException(404, 'Original no disponible.')
        return FileResponse(source(job), media_type='video/mp4')


@router.get('/{id}/files/{name}')
def download(id: str, name: str):
    with SessionLocal() as session:
        job = get(session, id)
        if name not in [e['name'] for e in json.loads(job.exports)] or not (folder(job) / name).is_file():
            raise HTTPException(404, 'Clip no disponible.')
        return FileResponse(folder(job) / name, media_type='video/mp4', filename='clip-' + name[-5:])


@router.delete('/{id}')
def delete(id: str):
    with _gate, SessionLocal() as session:
        job = get(session, id)
        if job.status in ('analyzing', 'exporting'):
            raise HTTPException(409, 'Esperá a que termine la tarea antes de eliminar el video.')
        shutil.rmtree(folder(job), ignore_errors=True)
        session.delete(job)
        session.commit()
        return {'deleted': True}
