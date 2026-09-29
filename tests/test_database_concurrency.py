import sqlite3
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy import text
from app import main
from app.db import DB, engine


def test_readers_remain_available_during_write():
    with TestClient(main.app) as client:
        writer = sqlite3.connect(DB)
        try:
            writer.execute('BEGIN EXCLUSIVE')
            writer.execute("UPDATE stories SET title=title")
            with ThreadPoolExecutor(max_workers=4) as pool:
                responses = list(pool.map(client.get, ['/api/videos', '/api/stories', '/api/imports', '/api/story-generations']))
            assert all(r.status_code == 200 for r in responses)
        finally:
            writer.rollback()
            writer.close()


def test_failed_request_rolls_back_and_releases_connection(monkeypatch):
    def failure(session):
        session.execute(text("CREATE TABLE IF NOT EXISTS rollback_probe (value TEXT)"))
        session.execute(text("INSERT INTO rollback_probe VALUES ('must roll back')"))
        raise OperationalError('SELECT', {}, sqlite3.OperationalError('database is locked'))
    with TestClient(main.app) as client:
        baseline = engine.pool.checkedout()
        monkeypatch.setattr(main, 'stats', failure)
        response = client.get('/api/dashboard')
        assert response.status_code == 503
        assert 'ocupada' in response.json()['detail']
        assert engine.pool.checkedout() == baseline
        with engine.begin() as connection:
            assert connection.execute(text('SELECT COUNT(*) FROM rollback_probe')).scalar() == 0
            connection.execute(text("INSERT INTO rollback_probe VALUES ('next request works')"))
