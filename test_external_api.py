import os
import sys
from datetime import datetime
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
# Student roster synchronization
# ---------------------------------------------------------------------------

def test_list_students(client):
    _, raw_key = create_key()
    create_student(student_number='STU001')

    response = client.get('/api/v1/students', headers=auth_headers(raw_key))

    assert response.status_code == 200
    assert response.get_json()['students'][0]['student_number'] == 'STU001'


def test_create_student(client):
    _, raw_key = create_key()

    response = client.post(
        '/api/v1/students',
        headers=auth_headers(raw_key),
        json={'student_number': 'STU002', 'name': 'John Mensah', 'class_name': 'Form 2'},
    )

    assert response.status_code == 201
    student = Student.query.filter_by(student_number='STU002').one()
    assert student.first_name == 'John'
    assert student.last_name == 'Mensah'


def test_update_student(client):
    _, raw_key = create_key()
    create_student(student_number='STU003')

    response = client.patch(
        '/api/v1/students/STU003',
        headers=auth_headers(raw_key),
        json={'first_name': 'Janet', 'class_name': 'Form 3'},
    )

    assert response.status_code == 200
    student = Student.query.filter_by(student_number='STU003').one()
    assert student.first_name == 'Janet'
    assert student.class_name == 'Form 3'


def test_bulk_students_upserts_by_student_number(client):
    _, raw_key = create_key()
    create_student(student_number='STU004')

    response = client.post(
        '/api/v1/students/bulk',
        headers=auth_headers(raw_key),
        json={'students': [
            {'student_number': 'STU004', 'name': 'Updated Doe'},
            {'student_number': 'STU005', 'name': 'New Student'},
        ]},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['created'] == 1
    assert body['updated'] == 1
    assert Student.query.filter_by(student_number='STU005').count() == 1


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


# ---------------------------------------------------------------------------
# List / get / update / delete
# ---------------------------------------------------------------------------

def create_assessment_row(student, **overrides):
    defaults = dict(
        student_id=student.id, category='ica1', subject='mathematics',
        class_name=student.class_name, score=40.0, max_score=50.0,
        term='term1', academic_year='2024-2025', session='First Term',
        assessor='Mr. Smith',
    )
    defaults.update(overrides)
    assessment = Assessment(**defaults)
    db.session.add(assessment)
    db.session.commit()
    return assessment


def test_list_assessments_empty(client):
    _, raw_key = create_key()

    response = client.get('/api/v1/assessments', headers=auth_headers(raw_key))

    assert response.status_code == 200
    body = response.get_json()
    assert body['total'] == 0
    assert body['results'] == []


def test_list_assessments_filters_by_student_number(client):
    _, raw_key = create_key()
    s1 = create_student(student_number='STU001')
    s2 = create_student(student_number='STU002')
    create_assessment_row(s1)
    create_assessment_row(s2)

    response = client.get('/api/v1/assessments?student_number=STU001', headers=auth_headers(raw_key))

    assert response.status_code == 200
    body = response.get_json()
    assert body['total'] == 1
    assert body['results'][0]['student_number'] == 'STU001'


def test_list_assessments_filters_by_term_and_academic_year(client):
    _, raw_key = create_key()
    s1 = create_student(student_number='STU001')
    create_assessment_row(s1, term='term1', academic_year='2024-2025')
    create_assessment_row(s1, term='term2', academic_year='2024-2025', subject='english')

    response = client.get(
        '/api/v1/assessments?term=term1&academic_year=2024-2025',
        headers=auth_headers(raw_key),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['total'] == 1
    assert body['results'][0]['term'] == 'term1'


def test_list_assessments_filters_by_created_after(client):
    _, raw_key = create_key()
    s1 = create_student(student_number='STU001')
    old = create_assessment_row(s1, subject='old-subject')
    old.date_recorded = datetime(2020, 1, 1)
    db.session.commit()
    create_assessment_row(s1, subject='new-subject')

    response = client.get(
        '/api/v1/assessments?created_after=2026-01-01',
        headers=auth_headers(raw_key),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['total'] == 1
    assert body['results'][0]['subject'] == 'new-subject'


def test_list_assessments_rejects_bad_date_filter(client):
    _, raw_key = create_key()

    response = client.get(
        '/api/v1/assessments?created_after=not-a-date',
        headers=auth_headers(raw_key),
    )
    assert response.status_code == 400


def test_list_assessments_pagination(client):
    _, raw_key = create_key()
    s1 = create_student(student_number='STU001')
    for i in range(5):
        create_assessment_row(s1, subject=f'subject-{i}')

    response = client.get(
        '/api/v1/assessments?limit=2&offset=1',
        headers=auth_headers(raw_key),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['total'] == 5
    assert body['count'] == 2
    assert body['limit'] == 2
    assert body['offset'] == 1


def test_list_assessments_limit_capped_at_500(client):
    _, raw_key = create_key()

    response = client.get('/api/v1/assessments?limit=10000', headers=auth_headers(raw_key))

    assert response.status_code == 200
    assert response.get_json()['limit'] == 500


def test_get_assessment_found(client):
    _, raw_key = create_key()
    s1 = create_student(student_number='STU001')
    a = create_assessment_row(s1)

    response = client.get(f'/api/v1/assessments/{a.id}', headers=auth_headers(raw_key))

    assert response.status_code == 200
    assert response.get_json()['id'] == a.id


def test_get_assessment_not_found(client):
    _, raw_key = create_key()

    response = client.get('/api/v1/assessments/999', headers=auth_headers(raw_key))
    assert response.status_code == 404


def test_update_assessment_success(client):
    _, raw_key = create_key()
    s1 = create_student(student_number='STU001')
    a = create_assessment_row(s1, score=40.0)

    response = client.put(
        f'/api/v1/assessments/{a.id}',
        headers=auth_headers(raw_key),
        json={'score': 45.0, 'assessor': 'Mrs. Jones'},
    )

    assert response.status_code == 200
    refreshed = db.session.get(Assessment, a.id)
    assert refreshed.score == 45.0
    assert refreshed.assessor == 'Mrs. Jones'


def test_update_assessment_rejects_score_above_max(client):
    _, raw_key = create_key()
    s1 = create_student(student_number='STU001')
    a = create_assessment_row(s1, score=40.0, max_score=50.0)

    response = client.put(
        f'/api/v1/assessments/{a.id}',
        headers=auth_headers(raw_key),
        json={'score': 999},
    )

    assert response.status_code == 422
    assert db.session.get(Assessment, a.id).score == 40.0


def test_update_assessment_not_found(client):
    _, raw_key = create_key()

    response = client.put('/api/v1/assessments/999', headers=auth_headers(raw_key), json={'score': 10})
    assert response.status_code == 404


def test_delete_assessment_success(client):
    _, raw_key = create_key()
    s1 = create_student(student_number='STU001')
    a = create_assessment_row(s1)
    aid = a.id

    response = client.delete(f'/api/v1/assessments/{aid}', headers=auth_headers(raw_key))

    assert response.status_code == 200
    assert response.get_json()['deleted']['id'] == aid
    assert db.session.get(Assessment, aid) is None


def test_delete_assessment_not_found(client):
    _, raw_key = create_key()

    response = client.delete('/api/v1/assessments/999', headers=auth_headers(raw_key))
    assert response.status_code == 404


def test_bulk_delete_by_explicit_ids(client):
    _, raw_key = create_key()
    s1 = create_student(student_number='STU001')
    a1 = create_assessment_row(s1, subject='math')
    a2 = create_assessment_row(s1, subject='english')
    a3 = create_assessment_row(s1, subject='science')

    response = client.post(
        '/api/v1/assessments/bulk-delete',
        headers=auth_headers(raw_key),
        json={'ids': [a1.id, a2.id, 999999]},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['deleted_count'] == 2
    assert body['not_found'] == [999999]
    assert db.session.get(Assessment, a1.id) is None
    assert db.session.get(Assessment, a2.id) is None
    assert db.session.get(Assessment, a3.id) is not None


def test_bulk_delete_rejects_empty_ids(client):
    _, raw_key = create_key()

    response = client.post(
        '/api/v1/assessments/bulk-delete',
        headers=auth_headers(raw_key),
        json={'ids': []},
    )
    assert response.status_code == 422


def test_bulk_delete_rejects_more_than_500_ids(client):
    _, raw_key = create_key()

    response = client.post(
        '/api/v1/assessments/bulk-delete',
        headers=auth_headers(raw_key),
        json={'ids': list(range(501))},
    )
    assert response.status_code == 422


def test_list_and_delete_require_auth(client):
    assert client.get('/api/v1/assessments').status_code == 401
    assert client.get('/api/v1/assessments/1').status_code == 401
    assert client.put('/api/v1/assessments/1', json={}).status_code == 401
    assert client.delete('/api/v1/assessments/1').status_code == 401
    assert client.post('/api/v1/assessments/bulk-delete', json={'ids': [1]}).status_code == 401
