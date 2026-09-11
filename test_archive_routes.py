import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import Assessment, Student, User


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'

    with app.app_context():
        ext = app.extensions.get('sqlalchemy')
        if ext and hasattr(ext, '_app_engines'):
            ext._app_engines[app].clear()
            options = {'url': app.config['SQLALCHEMY_DATABASE_URI'], **ext._engine_options}
            ext._app_engines[app][None] = ext._make_engine(None, options, app)
        db.create_all()
        admin = User(username='archive_admin', password_hash='x', role='admin')
        graduate = Student(
            first_name='Ama',
            last_name='Mensah',
            student_number='STU001',
            class_name='Graduated 2027',
            study_area='science_a',
        )
        db.session.add_all([admin, graduate])
        db.session.commit()
        db.session.add(Assessment(
            student_id=graduate.id,
            category='end_term',
            subject='Mathematics',
            class_name='Form 3',
            score=80,
            max_score=100,
            term='term1',
            academic_year='2026-2027',
            archived=True,
        ))
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = str(admin.id)
            session['_fresh'] = True
        yield client, graduate
        db.session.remove()
        db.drop_all()
        if ext and hasattr(ext, '_app_engines'):
            ext._app_engines[app].clear()


def test_archive_index_and_roster_render(client):
    test_client, student = client

    index_response = test_client.get('/admin/archive/')
    roster_response = test_client.get('/admin/archive/Graduated%202027')

    assert index_response.status_code == 200
    assert b'2026-2027' in index_response.data
    assert roster_response.status_code == 200
    assert student.student_number.encode() in roster_response.data


def test_archive_is_nested_by_academic_year_semester_and_class(client):
    test_client, student = client

    year_response = test_client.get('/admin/archive/year/2026-2027')
    semester_response = test_client.get('/admin/archive/year/2026-2027/semester/term1')
    class_response = test_client.get(
        '/admin/archive/year/2026-2027/semester/term1/class/Graduated%202027'
    )

    assert year_response.status_code == 200
    assert b'Semester 1' in year_response.data
    assert b'Semester 2' in year_response.data
    assert b'Semester 3' in year_response.data
    assert semester_response.status_code == 200
    assert b'Graduated 2027' in semester_response.data
    assert class_response.status_code == 200
    assert student.student_number.encode() in class_response.data