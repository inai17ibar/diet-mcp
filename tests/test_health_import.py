import os
import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient
from diet_mcp import db
from diet_mcp.health_import import import_health, health_week_summary

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DIET_MCP_DB_PATH', str(tmp_path / 'diet.db'))
    monkeypatch.setenv('DIET_HEALTH_IMPORT_TOKEN', 'health-only')
    monkeypatch.setenv('DIET_MCP_API_KEY', 'main-key')
    with TestClient(Starlette(routes=[Route('/import', import_health, methods=['POST']), Route('/week', health_week_summary)])) as c:
        yield c

H = {'Authorization': 'Bearer health-only'}
R = {'Authorization': 'Bearer main-key'}

def test_credentials_are_separate(client):
    assert client.post('/import', json={}).status_code == 401
    assert client.post('/import', json={}, headers=R).status_code == 401
    assert client.get('/week', headers=H).status_code == 401
    assert client.get('/week', headers=R).status_code == 200

def test_retry_update_and_missing(client):
    payload = {'daily': [{'date': '2026-11-09', 'steps': 5300, 'active_energy_kcal': 250}],
               'weights': [{'measured_at': '2026-11-10T07:00:00+09:00', 'weight_kg': 95}]}
    for _ in range(2):
        assert client.post('/import', json=payload, headers=H).status_code == 200
    assert client.post('/import', json={'daily': [{'date': '2026-11-09', 'steps': 6000}]}, headers=H).status_code == 200
    summary = client.get('/week?date=2026-11-10', headers=R).json()
    assert summary['steps'] == {'average': 6000, 'recorded_days': 1}
    assert summary['daily'][0]['active_energy_kcal'] == 250
    assert summary['daily'][1]['steps'] is None
    assert summary['weight_kg'] == {'average': 95, 'recorded_days': 1}
    assert summary['food']['average_calories'] is None
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM health_weights').fetchone()[0] == 1

def test_timezone_and_daily_weight_average(client):
    weights = [{'measured_at': t, 'weight_kg': v} for t, v in [
        ('2026-11-08T15:00:00Z', 94), ('2026-11-09T12:00:00Z', 96),
        ('2026-11-10T00:00:00Z', 97), ('2026-11-15T15:00:00Z', 150)]]
    assert client.post('/import', json={'weights': weights}, headers=H).status_code == 200
    summary = client.get('/week?date=2026-11-09', headers=R).json()
    assert summary['weight_kg'] == {'average': 96, 'recorded_days': 2}

@pytest.mark.parametrize('payload', [
    {'daily': [{'date': 'bad', 'steps': 1}]},
    {'daily': [{'date': '2026-11-09', 'steps': -1}]},
    {'daily': [{'date': '2026-11-09', 'steps': 1.5}]},
    {'weights': [{'measured_at': '2026-11-09T07:00:00', 'weight_kg': 95}]},
    {'weights': [{'measured_at': '2026-11-09T07:00:00Z', 'weight_kg': float('inf')}]},
    {'daily': [{'date': '2026-11-09', 'steps': 10}, {'date': '2026-11-09', 'steps': 20}]},
    {'daily': [{'date': '2026-11-09', 'steps': 10}, {'date': 'bad'}]},
])
def test_invalid_batch_is_atomic(client, payload):
    import json
    response = client.post('/import', content=json.dumps(payload), headers=H)
    assert response.status_code == 400
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM health_daily').fetchone()[0] == 0

def test_malformed_and_oversized(client):
    assert client.post('/import', content='{', headers=H).status_code == 400
    assert client.post('/import', content='x' * 256001, headers=H).status_code == 413


@pytest.mark.parametrize("steps", [0.0, 24.0, 5300.0])
def test_integral_float_steps(client, steps):
    response = client.post('/import', json={'daily': [{'date': '2026-11-09', 'steps': steps}]}, headers=H)
    assert response.status_code == 200
    summary = client.get('/week?date=2026-11-09', headers=R).json()
    assert summary['daily'][0]['steps'] == int(steps)


@pytest.mark.parametrize("steps", [True, 1.5, "24 count", [24], {"value": 24}])
def test_steps_error_identifies_field_without_echoing_health_data(client, steps):
    response = client.post('/import', json={'daily': [{'date': '2026-11-09', 'steps': steps}]}, headers=H)
    assert response.status_code == 400
    assert response.json()['issues'][0]['field'] == 'daily.0.steps'
    assert 'input' not in response.text
    assert '2026-11-09' not in response.text
    assert 'health-only' not in response.text
    assert '24 count' not in response.text


def test_date_error_is_actionable(client):
    response = client.post('/import', json={'daily': [{'date': '', 'steps': 24}]}, headers=H)
    assert response.status_code == 400
    assert response.json()['issues'][0]['field'] == 'daily.0.date'
    assert 'yyyy-MM-dd' in response.json()['issues'][0]['hint']


def test_unknown_field_name_is_not_echoed(client):
    response = client.post('/import', json={'private-health-text': 95}, headers=H)
    assert response.status_code == 400
    assert 'private-health-text' not in response.text
