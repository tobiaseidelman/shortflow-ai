"""Explicit background selection and non-destructive removal of baked-in side bars."""
import json
from pathlib import Path
import cv2
from fastapi import APIRouter, Form, HTTPException, Query, Response
from .db import SessionLocal
from .models import BackgroundVideo, BackgroundFraming, Clip, ShortBackgrounds

router = APIRouter()


def selected_clips(session, raw=''):
    available = session.query(Clip).join(BackgroundVideo).filter(BackgroundVideo.status == 'ready').all()
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
