import json

from app import app


def test_health_endpoint_reports_db_diagnostics():
    with app.test_client() as client:
        response = client.get('/health')

    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, dict)
    assert payload.get('status') == 'ok'
    assert payload.get('db_backend') in {'sqlite', 'postgresql', 'unknown'}
    assert 'db_host' in payload
    assert 'pid' in payload
    assert isinstance(payload['pid'], int)

    if payload['db_backend'] == 'postgresql':
        assert payload['db_host'] is not None
        assert payload['db_host'] != ''
