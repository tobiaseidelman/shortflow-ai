from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    response = client.get('/api/health')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] in {'ok', 'degraded'}
    assert 'ffmpeg' in data


def test_home():
    response = client.get('/')
    assert response.status_code == 200
    assert 'ShortFlow AI' in response.text
