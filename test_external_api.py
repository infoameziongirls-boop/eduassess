import os
import sys
import pytest

# Ensure the application root is on the import path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import APIKey, Assessment, Student, User


@pytest.fixture(scope="function")
def app_context():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    with app.app_context():
        ext = app.extensions.get('sqlalchemy')
        if ext and hasattr(ext, '_app_engines'):
            ext._app_engines[app].clear()
            options = {'url': app.config['SQLALCHEMY_DATABASE_URI'], **ext._engine_options}
            engine = ext._make_engine(None, options, app)
            ext._app_engines[app][None] = engine
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
        if ext and hasattr(ext, '_app_engines'):
            ext._app_engines[app].clear()


@pytest.fixture(scope="function")
def client(app_context):
    return app.test_client()


def create_student(student_number='STU001', class_name='Form 1'):
    student = Student(
        first_name='Jane',
        last_name='Doe',
        student_number=student_number,
        reference_number=f'REF-{student_number}',
        class_name=class_name,
        study_area='science',
    )
    db.session.add(student)
    db.session.commit()
    return student


def create_key(name='Test integration'):
    api_key, raw_key = APIKey.generate(name=name)
    return api_key, raw_key


def auth_headers(raw_key):
    return {'Authorization': f'Bearer {raw_key}'}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def test_missing_authorization_header_is_rejected(client):
    response = client.get('/api/v1/students/lookup?student_number=STU001')
    assert response.status_code == 401


def test_malformed_authorization_header_is_rejected(client):
    response = client.get(
        '/api/v1/students/lookup?student_number=STU001',
        headers={'Authorization': 'Token abc123'},
    )
    assert response.status_code == 401


def test_unknown_api_key_is_rejected(client):
    response = client.get(
        '/api/v1/students/lookup?student_number=STU001',
        headers=auth_headers('not-a-real-key'),
    )
    assert response.status_code == 401


def test_revoked_api_key_is_rejected(client):
    api_key, raw_key = create_key()
    api_key.is_active = False
    db.session.commit()

    response = client.get(
        '/api/v1/students/lookup?student_number=STU001',
        headers=auth_headers(raw_key),
    )
    assert response.status_code == 401


def test_valid_api_key_updates_last_used_at(client):
    api_key, raw_key = create_key()
    create_student()
    assert api_key.last_used_at is None

    client.get('/api/v1/students/lookup?student_number=STU001', headers=auth_headers(raw_key))

    refreshed = db.session.get(APIKey, api_key.id)
    assert refreshed.last_used_at is not None


# ---------------------------------------------------------------------------
# Student lookup
# ---------------------------------------------------------------------------

def test_lookup_student_found(client):
    _, raw_key = create_key()
    create_student(student_number='STU001')

    response = client.get(
        '/api/v1/students/lookup?student_number=STU001',
        headers=auth_headers(raw_key),
    )
    assert response.status_code == 200
    assert response.get_json()['student_number'] == 'STU001'


def test_lookup_student_not_found(client):
    _, raw_key = create_key()

    response = client.get(
        '/api/v1/students/lookup?student_number=NOBODY',
        headers=auth_headers(raw_key),
    )
    assert response.status_code == 404


def test_lookup_student_missing_query_param(client):
    _, raw_key = create_key()

    response = client.get('/api/v1/students/lookup', headers=auth_headers(raw_key))
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Single assessment create
# ---------------------------------------------------------------------------

def test_create_assessment_success(client):
    _, raw_key = create_key()
    create_student(student_number='STU001')

    response = client.post(
        '/api/v1/assessments/create',
        headers=auth_headers(raw_key),
        json={
            'student_number': 'STU001',
            'category': 'mid_term',
            'subject': 'mathematics',
            'score': 78.5,
            'max_score': 100,
            'term': 'term1',
            'academic_year': '2024-2025',
            'session': 'First Term',
            'assessor': 'Mr. John Smith',
        },
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body['success'] is True
    assert 'assessment_id' in body

    assessment = db.session.get(Assessment, body['assessment_id'])
    assert assessment.score == 78.5
    assert assessment.subject == 'mathematics'


def test_create_assessment_unknown_student_is_rejected(client):
    _, raw_key = create_key()

    response = client.post(
        '/api/v1/assessments/create',
        headers=auth_headers(raw_key),
        json={'student_number': 'NOBODY', 'category': 'mid_term', 'subject': 'mathematics', 'score': 50},
    )

    assert response.status_code == 422
    assert response.get_json()['success'] is False


def test_create_assessment_invalid_category_is_rejected(client):
    _, raw_key = create_key()
    create_student(student_number='STU001')

    response = client.post(
        '/api/v1/assessments/create',
        headers=auth_headers(raw_key),
        json={'student_number': 'STU001', 'category': 'not_a_real_category', 'subject': 'mathematics', 'score': 50},
    )

    assert response.status_code == 422


def test_create_assessment_score_above_max_is_rejected(client):
    _, raw_key = create_key()
    create_student(student_number='STU001')

    response = client.post(
        '/api/v1/assessments/create',
        headers=auth_headers(raw_key),
        json={
            'student_number': 'STU001', 'category': 'ica1', 'subject': 'mathematics',
            'score': 999, 'max_score': 50,
        },
    )

    assert response.status_code == 422


def test_create_assessment_reposting_updates_not_duplicates(client):
    """Re-syncing the same student/category/subject/term/year/session must
    update the existing row, not create a second one — the whole point of
    a results sync is being safely re-runnable."""
    _, raw_key = create_key()
    create_student(student_number='STU001')

    payload = {
        'student_number': 'STU001', 'category': 'mid_term', 'subject': 'mathematics',
        'score': 60, 'max_score': 100, 'term': 'term1', 'academic_year': '2024-2025',
        'session': 'First Term',
    }

    first = client.post('/api/v1/assessments/create', headers=auth_headers(raw_key), json=payload)
    assert first.status_code == 201
    first_id = first.get_json()['assessment_id']

    payload['score'] = 75
    second = client.post('/api/v1/assessments/create', headers=auth_headers(raw_key), json=payload)
    assert second.status_code == 201
    assert second.get_json()['assessment_id'] == first_id
    assert 'updated' in second.get_json()['message']

    assert Assessment.query.filter_by(student_id=Student.query.first().id).count() == 1
    assert db.session.get(Assessment, first_id).score == 75


# ---------------------------------------------------------------------------
# Bulk
# ---------------------------------------------------------------------------

def test_bulk_assessments_all_succeed(client):
    _, raw_key = create_key()
    create_student(student_number='STU001')
    create_student(student_number='STU002')

    response = client.post(
        '/api/v1/assessments/bulk',
        headers=auth_headers(raw_key),
        json={'assessments': [
            {'student_number': 'STU001', 'category': 'ica1', 'subject': 'mathematics', 'score': 40, 'max_score': 50},
            {'student_number': 'STU002', 'category': 'ica1', 'subject': 'mathematics', 'score': 45, 'max_score': 50},
        ]},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['successful'] == 2
    assert body['failed'] == 0


def test_bulk_assessments_partial_failure_returns_207(client):
    _, raw_key = create_key()
    create_student(student_number='STU001')

    response = client.post(
        '/api/v1/assessments/bulk',
        headers=auth_headers(raw_key),
        json={'assessments': [
            {'student_number': 'STU001', 'category': 'ica1', 'subject': 'mathematics', 'score': 40, 'max_score': 50},
            {'student_number': 'GHOST', 'category': 'ica1', 'subject': 'mathematics', 'score': 40, 'max_score': 50},
        ]},
    )

    assert response.status_code == 207
    body = response.get_json()
    assert body['successful'] == 1
    assert body['failed'] == 1
    assert len(body['errors']) == 1


def test_bulk_assessments_rejects_empty_array(client):
    _, raw_key = create_key()

    response = client.post(
        '/api/v1/assessments/bulk',
        headers=auth_headers(raw_key),
        json={'assessments': []},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Validate (dry run)
# ---------------------------------------------------------------------------

def test_validate_does_not_write_to_database(client):
    _, raw_key = create_key()
    create_student(student_number='STU001')

    response = client.post(
        '/api/v1/assessments/validate',
        headers=auth_headers(raw_key),
        json={'assessments': [
            {'student_number': 'STU001', 'category': 'ica1', 'subject': 'mathematics', 'score': 40, 'max_score': 50},
        ]},
    )

    assert response.status_code == 200
    assert response.get_json()['valid'] == 1
    assert Assessment.query.count() == 0


def test_validate_flags_unmapped_student(client):
    _, raw_key = create_key()

    response = client.post(
        '/api/v1/assessments/validate',
        headers=auth_headers(raw_key),
        json={'assessments': [
            {'student_number': 'GHOST', 'category': 'ica1', 'subject': 'mathematics', 'score': 40, 'max_score': 50},
        ]},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['valid'] == 0
    assert body['invalid'] == 1
    assert not body['results'][0]['valid']
