import json
from io import BytesIO
from urllib.error import URLError

import pytest
from fastapi.testclient import TestClient

from app import story_engine, story_routes
from app.db import SessionLocal
from app.main import app
from app.models import Story, StoryGeneration


def sample_story(duration=45):
    # Distinct words make length/repetition boundaries deterministic without an AI request.
    return {'title': 'El alquiler', 'plan': 'Un agravio, una decisión y una consecuencia.',
            'part1': ' '.join(f'conflicto{i}' for i in range(round(duration * 2.3))) + '.',
            'part2': ' '.join(f'resolucion{i}' for i in range(round(duration * 2.3))) + '.'}


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


def test_generation_saves_linked_parts_and_preserves_old_stories(client, monkeypatch):
    result = sample_story()
    def generate(theme, duration, storage, progress):
        assert theme == 'Conflicto por el alquiler'
        assert duration == 45
        progress('Escribiendo…')
        return result
    monkeypatch.setattr(story_engine, 'generate_story', generate)
    with SessionLocal() as session:
        old = Story(genre='Drama', duration_target=30, title='Historia anterior', text='Conservar este texto.')
        session.add(old)
        session.commit()
        old_id = old.id
    response = client.post('/api/stories', data={'theme': 'Conflicto por el alquiler', 'duration': 45})
    assert response.status_code == 202
    job_id = response.json()['id']
    job = client.get('/api/story-generations/' + job_id).json()
    assert job['status'] == 'ready'
    assert [part['number'] for part in job['parts']] == [1, 2]
    assert job['parts'][0]['text'] == result['part1']
    assert job['parts'][1]['text'] == result['part2']
    assert job['parts'][0]['id'] != job['parts'][1]['id']
    stories = client.get('/api/stories').json()
    assert next(s for s in stories if s['id'] == old_id)['text'] == 'Conservar este texto.'
    assert any(j['id'] == job_id for j in client.get('/api/story-generations').json())


def test_failure_does_not_save_partial_stories(client, monkeypatch):
    def fail(*args):
        raise story_engine.StoryGenerationError('La IA no está disponible.')
    monkeypatch.setattr(story_engine, 'generate_story', fail)
    before = len(client.get('/api/stories').json())
    response = client.post('/api/stories', data={'duration': 60})
    job = client.get('/api/story-generations/' + response.json()['id']).json()
    assert job['status'] == 'failed'
    assert job['parts'] == []
    assert job['message'] == 'La IA no está disponible.'
    assert len(client.get('/api/stories').json()) == before
    assert not story_routes._generation_lock.locked()


@pytest.mark.parametrize('data', [{'duration': 0}, {'duration': 10000}, {'theme': 'x' * 701}])
def test_invalid_input_never_starts_generation(client, monkeypatch, data):
    def unexpected(*args):
        pytest.fail('Should not call the model')
    monkeypatch.setattr(story_engine, 'generate_story', unexpected)
    assert client.post('/api/stories', data=data).status_code == 422


def test_only_one_generation_at_a_time(client):
    story_routes._generation_lock.acquire()
    try:
        assert client.post('/api/stories', data={'duration': 45}).status_code == 409
    finally:
        story_routes._generation_lock.release()


def test_interrupted_generation_becomes_retryable_after_restart():
    with SessionLocal() as session:
        session.add(StoryGeneration(id='interrupted-test', theme='Tema', duration=45, status='running'))
        session.commit()
    with TestClient(app) as client:
        job = client.get('/api/story-generations/interrupted-test').json()
        assert job['status'] == 'failed'
        assert 'reinició' in job['message']
        assert job['parts'] == []


def test_unknown_generation(client):
    assert client.get('/api/story-generations/missing').status_code == 404


@pytest.mark.parametrize('duration', [30, 45, 60, 90])
def test_duration_applies_to_each_part(duration):
    result = sample_story(duration)
    assert story_engine.validate_story(result, duration) == result


def test_rejects_repeated_or_truncated_story():
    result = sample_story()
    result['part2'] = result['part1']
    with pytest.raises(ValueError, match='repetidas'):
        story_engine.validate_story(result, 45)
    result = sample_story()
    result['part2'] = result['part2'][:-1]
    with pytest.raises(ValueError, match='cortada'):
        story_engine.validate_story(result, 45)


def test_plan_then_each_part_shares_story_context(tmp_path, monkeypatch):
    monkeypatch.setattr(story_engine, 'ensure_model', lambda *args: None)
    outline = {key: 'Detalle de ' + key for key in ('title', 'narrator', 'relationship', 'grievance', 'resource', 'clue', 'cliffhanger', 'outcome')}
    result = sample_story()
    result['part1'] = 'Yo ' + result['part1']
    result['part2'] = 'Me ' + result['part2']
    replies = iter([json.dumps(outline), result['part1'], result['part2'], '{"issues": []}'])
    calls = []
    def request(path, payload=None, timeout=10):
        calls.append((path, payload))
        if path == '/api/generate':
            assert payload['keep_alive'] == 0
            return BytesIO(b'{}')
        assert path == '/api/chat'
        return BytesIO(json.dumps({'done': True, 'message': {'content': next(replies)}}).encode())
    monkeypatch.setattr(story_engine, '_request', request)
    saved = story_engine.generate_story('Tema propio', 45, tmp_path, lambda m: None)
    assert saved['part1'] == result['part1'] and saved['part2'] == result['part2']
    assert len(calls) == 5
    assert calls[0][1]['format'] == 'json'
    assert 'format' not in calls[1][1]
    assert 'Tema propio' in calls[0][1]['messages'][1]['content']
    second_messages = calls[2][1]['messages']
    assert second_messages[2] == {'role': 'assistant', 'content': result['part1']}
    assert outline['outcome'] in second_messages[1]['content']
    assert 'Tema propio' in second_messages[1]['content']
    assert 'Tema propio' in calls[1][1]['messages'][1]['content']
    review_input = json.loads(calls[3][1]['messages'][1]['content'])
    assert review_input == {'tema_original': 'Tema propio', 'parte1': result['part1'], 'parte2': result['part2']}
    assert calls[0][1]['options']['use_mmap'] is True


def test_episode_revision_receives_actual_draft(monkeypatch):
    calls = []
    good = 'Yo ' + sample_story()['part1']
    replies = iter(['Yo me fui.', good])
    def complete(messages):
        calls.append(messages)
        return next(replies)
    monkeypatch.setattr(story_engine, 'complete', complete)
    assert story_engine.write_episode([{'role': 'user', 'content': 'Tema'}, {'role': 'assistant', 'content': 'Episodio anterior que no hay que reescribir.'}], 45, lambda m: None) == good
    assert all('Episodio anterior que no hay que reescribir.' not in m['content'] for m in calls[1])
    assert calls[1][-2]['content'] == 'Yo me fui.'
    assert 'entre' in calls[1][-1]['content']


def test_bad_output_is_retried_once_then_reported(monkeypatch):
    calls = []
    def complete(messages):
        calls.append(messages)
        return 'Yo me fui.'
    monkeypatch.setattr(story_engine, 'complete', complete)
    with pytest.raises(story_engine.StoryGenerationError, match='revisión'):
        story_engine.write_episode([], 45, lambda m: None)
    assert len(calls) == 2


def test_rejects_third_person_episode():
    with pytest.raises(ValueError, match='primera persona'):
        story_engine.validate_episode(sample_story()['part1'], 45)


def test_missing_ollama_gives_setup_instructions(tmp_path, monkeypatch):
    def offline(*args, **kwargs):
        raise URLError('offline')
    monkeypatch.setattr(story_engine, '_request', offline)
    monkeypatch.setattr(story_engine.shutil, 'which', lambda name: None)
    with pytest.raises(story_engine.StoryGenerationError, match='Rebuild Container'):
        story_engine.ensure_model(tmp_path, lambda m: None)


def test_existing_model_is_not_downloaded_again(tmp_path, monkeypatch):
    def request(path, *args, **kwargs):
        assert path == '/api/tags'
        return BytesIO(json.dumps({'models': [{'name': story_engine.MODEL}]}).encode())
    monkeypatch.setattr(story_engine, '_request', request)
    story_engine.ensure_model(tmp_path, lambda m: None)


def test_download_stream_reports_progress(tmp_path, monkeypatch):
    def request(path, *args, **kwargs):
        if path == '/api/tags':
            return BytesIO(b'{"models": []}')
        assert path == '/api/pull'
        return BytesIO(b'{"total":100,"completed":50}\n{"status":"success"}\n')
    monkeypatch.setattr(story_engine, '_request', request)
    messages = []
    story_engine.ensure_model(tmp_path, messages.append)
    assert any('50%' in m for m in messages)


def test_overlong_episode_is_shortened_not_expanded(monkeypatch):
    messages_seen=[]
    good='Yo '+sample_story()['part1']
    replies=iter(['Yo '+('palabra '*180)+'.', good])
    def complete(messages):
        messages_seen.append(messages)
        return next(replies)
    monkeypatch.setattr(story_engine, 'complete', complete)
    assert story_engine.write_episode([],45,lambda m:None)==good
    assert 'Recortá' in messages_seen[1][-1]['content']
    assert 'no agregues escenas' in messages_seen[1][-1]['content']


def test_model_memory_failure_explains_cause(monkeypatch):
    from urllib.error import HTTPError
    def fail(*args, **kwargs):
        raise HTTPError('http://127.0.0.1:11434/api/chat',500,'Internal error',{},BytesIO(b'{"error":"model requires more system memory"}'))
    monkeypatch.setattr(story_engine, '_request', fail)
    with pytest.raises(story_engine.StoryGenerationError, match='suficiente memoria'):
        story_engine.complete([])


def test_continuity_repair_passes_corrected_first_part_to_second(monkeypatch):
    draft = sample_story()
    repaired = {'part1': 'Yo ' + draft['part1'], 'part2': 'Me ' + draft['part2']}
    verdicts = iter(['{"issues": ["Cambió hermano por hermana"]}', '{"issues": []}'])
    reviews, revisions = [], []
    def review(messages, json_mode=False):
        assert json_mode
        reviews.append(json.loads(messages[1]['content']))
        return next(verdicts)
    def write(messages, duration, progress):
        revisions.append(messages[1]['content'])
        return repaired['part1' if len(revisions) == 1 else 'part2']
    monkeypatch.setattr(story_engine, 'complete', review)
    monkeypatch.setattr(story_engine, 'write_episode', write)
    result = story_engine.review_and_repair('Mi hermano me pidió dinero', draft, 45, lambda m: None)
    assert result['part1'] == repaired['part1']
    assert result['part2'] == repaired['part2']
    assert repaired['part1'] in revisions[1]
    assert 'Mi hermano me pidió dinero' in revisions[0]
    assert reviews[1]['parte1'] == repaired['part1']
    assert reviews[1]['parte2'] == repaired['part2']


def test_unresolved_contradictions_fail_after_one_repair(monkeypatch):
    calls = []
    def review(*args, **kwargs):
        calls.append(1)
        return '{"issues": ["El personaje aparece en un lugar sin explicación"]}'
    monkeypatch.setattr(story_engine, 'complete', review)
    # Keep the two parts distinct while simulating a reviewer that still rejects them.
    drafts = iter(['Yo ' + sample_story()['part1'], 'Me ' + sample_story()['part2']])
    monkeypatch.setattr(story_engine, 'write_episode', lambda *args: next(drafts))
    with pytest.raises(story_engine.StoryGenerationError, match='contradicciones'):
        story_engine.review_and_repair('Tema', sample_story(), 45, lambda m: None)
    assert len(calls) == 2


@pytest.mark.parametrize('review', ['{}', '{"issues": "ninguna"}', '{"issues": [false]}'])
def test_invalid_review_is_not_treated_as_approval(monkeypatch, review):
    monkeypatch.setattr(story_engine, 'complete', lambda *args, **kwargs: review)
    with pytest.raises(ValueError, match='revisión'):
        story_engine.review_and_repair('Tema', sample_story(), 45, lambda m: None)


def test_review_schema_and_load_wait_are_sent_to_ollama(monkeypatch):
    def request(path, payload=None, timeout=10):
        assert path == '/api/chat'
        assert timeout == 1200
        assert payload['format'] == story_engine.REVIEW_SCHEMA
        assert payload['options']['temperature'] == 0
        assert payload['options']['use_mmap'] is True
        return BytesIO(json.dumps({'done': True, 'message': {'content': json.dumps({'issues': []})}}).encode())
    monkeypatch.setattr(story_engine, '_request', request)
    assert json.loads(story_engine.complete([], story_engine.REVIEW_SCHEMA)) == {'issues': []}


def test_load_timeout_is_explained_separately(monkeypatch):
    from urllib.error import HTTPError
    def request(*args, **kwargs):
        raise HTTPError('http://127.0.0.1:11434/api/chat',500,'Internal error',{},
                        BytesIO(b'{"error":"timed out waiting for llama-server to start - "}'))
    monkeypatch.setattr(story_engine, '_request', request)
    with pytest.raises(story_engine.StoryGenerationError, match='tiempo de carga'):
        story_engine.complete([])
