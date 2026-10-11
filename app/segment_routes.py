"""Non-destructive manual background intervals with optimistic edit protection."""
import json
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ConfigDict
from .db import SessionLocal
from .models import BackgroundVideo, Clip, ManualBackgroundSegments
from .work_lock import compute_lock

router = APIRouter()

class Interval(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    start: float = Field(ge=0, strict=True)
    end: float = Field(gt=0, strict=True)

class SegmentEdit(BaseModel):
    revision: str = Field(max_length=36)
    segments: list[Interval] = Field(min_length=1, max_length=200)

class Revision(BaseModel):
    revision: str = Field(max_length=36)

def ready_video(session, video_id):
    video = session.get(BackgroundVideo, video_id)
    if not video or video.status != 'ready':
        raise HTTPException(404, 'Fondo listo no encontrado.')
    return video

def snapshot(session, video):
    row = session.get(ManualBackgroundSegments, video.id)
    ids = json.loads(row.clip_ids) if row else []
    clips = [session.get(Clip, cid) for cid in ids]
    return {'video_id': video.id, 'duration': video.duration, 'revision': row.revision if row else '',
            'manual': bool(row), 'source': f'/api/videos/{video.id}/source',
            'segments': [{'id': c.id, 'start': c.start_time, 'end': c.end_time} for c in clips if c]}

@router.get('/api/videos/{video_id}/source')
def source(video_id: int):
    with SessionLocal() as session:
        video = ready_video(session, video_id)
        path = Path(video.path)
        if not path.is_file(): raise HTTPException(404, 'No se encontró el archivo del fondo.')
    # FileResponse supports byte ranges, so seeking does not download the full file.
    media = {'.mp4':'video/mp4', '.mov':'video/quicktime', '.webm':'video/webm'}.get(path.suffix.lower(), 'application/octet-stream')
    return FileResponse(path, media_type=media)

@router.get('/api/videos/{video_id}/segments')
def segments(video_id: int):
    with SessionLocal() as session:
        return snapshot(session, ready_video(session, video_id))

@router.put('/api/videos/{video_id}/segments')
def save_segments(video_id: int, edit: SegmentEdit):
    if not compute_lock.acquire(blocking=False):
        raise HTTPException(409, 'Hay otro trabajo en curso. Esperá a que termine para guardar.')
    try:
        with SessionLocal() as session:
            video = ready_video(session, video_id)
            row = session.get(ManualBackgroundSegments, video_id)
            if edit.revision != (row.revision if row else ''):
                raise HTTPException(409, 'Los fragmentos cambiaron en otra pestaña. Volvé a abrir el editor.')
            intervals = sorted((round(s.start, 3), round(s.end, 3)) for s in edit.segments)
            last_end = -1
            for start, end in intervals:
                if end > video.duration or not .25 <= end-start <= 300:
                    raise HTTPException(422, 'Cada fragmento debe durar entre 0,25 y 300 segundos y estar dentro del video.')
                if start < last_end:
                    raise HTTPException(422, 'Los fragmentos no pueden superponerse. Ajustá el inicio o el final.')
                last_end = end
            old = [session.get(Clip, cid) for cid in json.loads(row.clip_ids)] if row else []
            previous = {(c.start_time, c.end_time): c for c in old if c}
            clips = []
            for start, end in intervals:
                clip = previous.get((start, end))
                if clip is None:
                    clip = Clip(source_video_id=video_id, start_time=start, end_time=end, duration=end-start,
                                motion_score=50, visual_change_score=50, action_onset=0,
                                quality_score=50, hook_score=50, loop_score=50, similarity_group='manual')
                    session.add(clip)
                clips.append(clip)
            session.flush()
            if row is None:
                row = ManualBackgroundSegments(video_id=video_id)
                session.add(row)
            row.clip_ids = json.dumps([c.id for c in clips]); row.revision = str(uuid4())
            session.commit()
            return snapshot(session, video)
    finally:
        compute_lock.release()

@router.delete('/api/videos/{video_id}/segments')
def reset_segments(video_id: int, edit: Revision):
    if not compute_lock.acquire(blocking=False):
        raise HTTPException(409, 'Hay otro trabajo en curso. Esperá a que termine.')
    try:
        with SessionLocal() as session:
            video = ready_video(session, video_id)
            row = session.get(ManualBackgroundSegments, video_id)
            if edit.revision != (row.revision if row else ''):
                raise HTTPException(409, 'Los fragmentos cambiaron en otra pestaña. Volvé a abrir el editor.')
            if row: session.delete(row)
            session.commit()
            return snapshot(session, video)
    finally:
        compute_lock.release()
