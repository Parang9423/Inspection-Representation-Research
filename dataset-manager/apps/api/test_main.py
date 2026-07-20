from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


def test_summary_shape():
    response = client.get('/api/summary')
    assert response.status_code == 200
    payload = response.json()
    assert 'totals' in payload
    assert 'groups' in payload
