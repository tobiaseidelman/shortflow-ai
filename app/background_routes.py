"""Explicit background selection and non-destructive removal of baked-in side bars."""
import json
from pathlib import Path
import cv2
from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Query, Response
from .db import SessionLocal
from .models import BackgroundVideo, BackgroundFraming, Clip, ShortBackgrounds, BackgroundAnalysis

router = APIRouter()


def selected_clips(session, raw=''):
    available = session.query(Clip).join(BackgroundVideo).filter(BackgroundVideo.status == 'ready').all()
    versions={r.video_id: set(json.loads(r.clip_ids)) for r in session.query(BackgroundAnalysis).all() if r.clip_ids != '[]'}
    available=[c for c in available if c.source_video_id not in versions or c.id in versions[c.source_video_id]]
    if not raw:
        if not available:
            raise HTTPException(400, 'Primero agregá y analizá un fondo.')
        return available
    try:
        ids = json.loads(raw)
        if not isinstance(ids, list) or not ids or any(type(i) is not int or i <= 0 for i in ids):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(400, 'Elegí al menos un fondo válido.')
    ready = {c.source_video_id for c in available}
    if not set(ids) <= ready:
        raise HTTPException(400, 'Uno de los fondos elegidos no está analizado o ya no está disponible.')
    return [c for c in available if c.source_video_id in ids]


def crop_settings(session):
    return {r.video_id: r.side_percent for r in session.query(BackgroundFraming).all()}


def remember_selection(session, short_id, clips):
    row = session.get(ShortBackgrounds, short_id)
    if row is None:
        row = ShortBackgrounds(short_id=short_id)
        session.add(row)
    row.video_ids = json.dumps(sorted({c.source_video_id for c in clips}))


@router.put('/api/videos/{video_id}/framing')
def save_framing(video_id: int, side_percent: float = Form(..., ge=0, le=40)):
    with SessionLocal() as session:
        if not session.get(BackgroundVideo, video_id):
            raise HTTPException(404, 'Fondo no encontrado.')
        row = session.get(BackgroundFraming, video_id)
        if row is None:
            row = BackgroundFraming(video_id=video_id)
            session.add(row)
        row.side_percent = side_percent
        session.commit()
    return {'side_percent': side_percent}


@router.get('/api/videos/{video_id}/preview')
def preview(video_id: int, side_percent: float = Query(0, ge=0, le=40), second: float = Query(1, ge=0)):
    with SessionLocal() as session:
        video = session.get(BackgroundVideo, video_id)
        if not video or not Path(video.path).is_file():
            raise HTTPException(404, 'Fondo no encontrado.')
        path, duration = video.path, video.duration
    cap = cv2.VideoCapture(path)
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, min(second, max(0, duration-.2))*1000)
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok:
        raise HTTPException(422, 'No se pudo leer la vista previa.')
    height, width = frame.shape[:2]
    edge = int(width * side_percent / 100 / 2) * 2
    frame = frame[:, edge:width-edge]
    height, width = frame.shape[:2]
    frame = cv2.resize(frame, (max(1, round(width*min(1, 720/width))), max(1, round(height*min(1, 720/width)))))
    ok, data = cv2.imencode('.jpg', frame)
    if not ok:
        raise HTTPException(422, 'No se pudo crear la vista previa.')
    return Response(data.tobytes(), media_type='image/jpeg', headers={'Cache-Control': 'no-store'})


def reanalyze_video(video_id):
    from .video_engine import analyze
    from .work_lock import compute_lock
    try:
        with SessionLocal() as session:
            video=session.get(BackgroundVideo,video_id)
            rows=analyze(video.path)
            if not rows: raise ValueError('No se encontraron tomas utilizables.')
            clips=[Clip(source_video_id=video_id,**row) for row in rows]
            session.add_all(clips);session.flush()
            analysis=session.get(BackgroundAnalysis,video_id)
            analysis.clip_ids=json.dumps([c.id for c in clips])
            analysis.status='ready';analysis.message='Tomas actualizadas. Se usarán en los próximos videos.'
            session.commit()
    except Exception:
        with SessionLocal() as session:
            row=session.get(BackgroundAnalysis,video_id)
            row.status='failed';row.message='No se pudo actualizar el análisis. El fondo anterior se conserva.'
            session.commit()
    finally:
        compute_lock.release()


@router.post('/api/videos/{video_id}/reanalyze',status_code=202)
def start_reanalysis(video_id: int,tasks: BackgroundTasks):
    from .work_lock import compute_lock
    if not compute_lock.acquire(blocking=False):
        raise HTTPException(409,'Hay otro trabajo en curso. Esperá a que termine.')
    try:
        with SessionLocal() as session:
            video=session.get(BackgroundVideo,video_id)
            if not video or video.status!='ready': raise HTTPException(404,'Fondo listo no encontrado.')
            row=session.get(BackgroundAnalysis,video_id)
            if row is None: row=BackgroundAnalysis(video_id=video_id);session.add(row)
            row.status='running';row.message='Analizando tomas…';session.commit()
        tasks.add_task(reanalyze_video,video_id)
        return {'status':'running'}
    except Exception:
        compute_lock.release();raise


@router.get('/api/videos/{video_id}/analysis')
def analysis_status(video_id: int):
    with SessionLocal() as session:
        row=session.get(BackgroundAnalysis,video_id)
        if not row: raise HTTPException(404,'Análisis no encontrado.')
        return {'status':row.status,'message':row.message}
