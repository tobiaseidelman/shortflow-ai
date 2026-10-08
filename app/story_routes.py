"""Durable paired-story jobs, separate from existing stories and videos."""
from contextlib import asynccontextmanager
import logging
from .work_lock import compute_lock
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException
from .db import SessionLocal
from .models import Story, StoryGeneration, BackgroundAnalysis
from . import story_engine

router = APIRouter()
_generation_lock = compute_lock
_storage = None
logger = logging.getLogger(__name__)
DEFAULT_THEMES = (
    'Mi compañero de apartamento alquilaba mi habitación cuando yo viajaba. Descubrí una reseña con una foto de mi escritorio. Ambos figuramos en el contrato y quiero recuperar mi privacidad.',
    'Mi jefa presentó mi propuesta como propia. En una reunión, el cliente me preguntó por un cálculo que solo yo había preparado. El historial del documento conserva mis cambios.',
    'Mi hermana vendió una bicicleta que le había prestado. Me enteré porque el comprador me escribió para pedirme la factura. Ella decía que yo se la había regalado.',
    'Un vecino se quejaba del ruido de mi perro, pero yo no tengo mascotas. Al revisar las horas de sus reclamos descubrí quién estaba entrando a mi patio compartido.',
    'Organicé un viaje con amigos y uno cambió el alojamiento sin consultarnos. La confirmación llegó a mi correo y mostraba que había reservado una habitación privada con el dinero común.',
    'Mi pareja le contó a su familia que yo había renunciado a mi trabajo para vivir de ella. Durante una cena me pidieron explicaciones. Yo seguía trabajando y pagando mi parte de los gastos.',
)



@asynccontextmanager
async def lifespan(app):
    from .upload_routes import recover_uploads
    recover_uploads()
    from .import_routes import recover_imports
    recover_imports()
    from .render_routes import recover_renders
    recover_renders()
    # start.sh runs one worker. A restart interrupts in-process jobs, not saved stories.
    with SessionLocal() as session:
        session.query(BackgroundAnalysis).filter_by(status='running').update({'status':'failed','message':'El análisis se interrumpió. Tocá ACTUALIZAR TOMAS para retomarlo.'})
        session.query(StoryGeneration).filter(StoryGeneration.status == 'running').update({
            'status': 'failed', 'message': 'El servidor se reinició durante la generación. Volvé a intentarlo.'})
        session.commit()
    yield
    story_engine.stop_server()


def set_storage(path):
    global _storage
    _storage = path


def run_generation(job_id):
    def progress(message):
        with SessionLocal() as session:
            job = session.get(StoryGeneration, job_id)
            job.message = message
            session.commit()
    try:
        with SessionLocal() as session:
            job = session.get(StoryGeneration, job_id)
            theme, duration = job.theme, job.duration
        result = story_engine.generate_story(theme, duration, _storage, progress)
        with SessionLocal() as session:
            job = session.get(StoryGeneration, job_id)
            parts = [Story(genre='Reddit', duration_target=duration,
                           title=f"{result['title']} — Parte {number}", text=result[f'part{number}'])
                     for number in (1, 2)]
            session.add_all(parts)
            session.flush()
            job.part1_id, job.part2_id = (p.id for p in parts)
            issues = result.get('review_issues', [])
            job.title = result['title']
            job.status = 'needs_review' if issues else 'ready'
            job.message = ('Borrador guardado. Revisá estas observaciones de la IA antes de crear los videos:\n' +
                           '\n'.join('• ' + issue for issue in issues)) if issues else 'Las dos partes están listas.'
            session.commit()
    except Exception as exc:
        logger.exception('Story generation failed: %s', job_id)
        with SessionLocal() as session:
            job = session.get(StoryGeneration, job_id)
            job.status = 'failed'
            job.message = str(exc) if isinstance(exc, story_engine.StoryGenerationError) else 'No se pudo guardar la historia. Volvé a intentarlo.'
            session.commit()
    finally:
        _generation_lock.release()


def serialize(job, session):
    parts = []
    for number, story_id in ((1, job.part1_id), (2, job.part2_id)):
        story = session.get(Story, story_id) if story_id else None
        if story:
            parts.append({'number': number, 'id': story.id, 'title': story.title, 'text': story.text,
                          'duration': story.duration_target, 'words': len(story.text.split())})
    return {'id': job.id, 'title': job.title, 'theme': job.theme, 'duration': job.duration,
            'status': job.status, 'message': job.message, 'parts': parts}


@router.post('/api/stories', status_code=202)
def create_story(background_tasks: BackgroundTasks, theme: str = Form('', max_length=700),
                 duration: int = Form(90)):
    if duration not in (30, 45, 60, 90, 120):
        raise HTTPException(422, 'Elegí 30, 45, 60, 90 o 120 segundos por parte.')
    if not _generation_lock.acquire(blocking=False):
        raise HTTPException(409, 'Ya hay una historia o video generándose. Esperá a que termine.')
    try:
        with SessionLocal() as session:
            recent = {row.theme for row in session.query(StoryGeneration).order_by(StoryGeneration.created_at.desc()).limit(5)}
            suggested = next((item for item in DEFAULT_THEMES if item not in recent), DEFAULT_THEMES[0])
            job = StoryGeneration(id=str(uuid4()), theme=theme.strip() or suggested,
                                  duration=duration, status='running', message='Preparando la historia…')
            session.add(job)
            session.commit()
            result = serialize(job, session)
        background_tasks.add_task(run_generation, job.id)
        return result
    except Exception:
        _generation_lock.release()
        raise


@router.get('/api/story-generations')
def list_generations():
    with SessionLocal() as session:
        jobs = session.query(StoryGeneration).order_by(StoryGeneration.created_at.desc()).limit(50).all()
        return [serialize(job, session) for job in jobs]


@router.get('/api/story-generations/{job_id}')
def get_generation(job_id: str):
    with SessionLocal() as session:
        job = session.get(StoryGeneration, job_id)
        if not job:
            raise HTTPException(404, 'Historia no encontrada.')
        return serialize(job, session)
