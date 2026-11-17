import importlib.util
import os
import re
import sys

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from flask import g

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, bcrypt, db
from models import Student, User


@pytest.fixture
def auth_app():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    with app.app_context():
        ext = app.extensions.get('sqlalchemy')
        if ext and hasattr(ext, '_app_engines'):
            ext._app_engines[app].clear()
            options = {'url': app.config['SQLALCHEMY_DATABASE_URI'], **ext._engine_options}
            ext._app_engines[app][None] = ext._make_engine(None, options, app)
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
        if ext and hasattr(ext, '_app_engines'):
            ext._app_engines[app].clear()


def _login_as(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
        if user.is_student():
            session['student_auth_version'] = user.auth_version
    g.pop('_login_user', None)


def _make_student_record(number):
    student = Student(
        student_number=number,
        reference_number='REF-' + number,
        first_name='Test',
        last_name='Student',
        class_name='Form 1',
        study_area='science_a',
    )
    db.session.add(student)
    db.session.flush()
    return student


def test_legacy_student_credentials_remain_disabled_until_issued(auth_app):
    student = _make_student_record('AUTH-LEGACY')
    user = User(
        username=student.student_number,
        password_hash=bcrypt.generate_password_hash('legacy-password-123').decode(),
        role='student',
        credentials_enabled=False,
        must_change_password=True,
    )
    db.session.add(user)
    db.session.commit()

    response = auth_app.test_client().post(
        '/student/login',
        data={'identifier': student.student_number, 'password': 'legacy-password-123'},
    )

    assert response.status_code == 200
    assert b'Student access is not activated' in response.data


def test_admin_issues_temporary_password_and_stale_sessions_are_invalidated(auth_app):
    admin = User(
        username='auth-admin',
        password_hash=bcrypt.generate_password_hash('admin-password-123').decode(),
        role='admin',
    )
    student = _make_student_record('AUTH-ISSUED')
    student_user = User(
        username=student.student_number,
        password_hash=bcrypt.generate_password_hash('old-student-password-123').decode(),
        role='student',
    )
    db.session.add_all([admin, student_user])
    db.session.commit()

    client = auth_app.test_client()
    login_response = client.post(
        '/student/login',
        data={
            'identifier': student.student_number,
            'password': 'old-student-password-123',
        },
    )
    assert login_response.status_code == 302
    assert login_response.headers['Location'].endswith('/student/dashboard')

    with client.session_transaction() as session:
        old_auth_version = session['student_auth_version']
        session['_user_id'] = str(admin.id)
        session.pop('student_auth_version', None)
    g.pop('_login_user', None)
    issue_response = client.post(
        f'/students/{student.id}/issue_login_password'
    )

    assert issue_response.status_code == 200, (
        issue_response.headers.get('X-EduAssess-User'),
        issue_response.data[:1000],
    )
    assert 'no-store' in issue_response.headers['Cache-Control'].lower()
    temporary_password_match = re.search(
        rb'id="temporary-password"[^>]*value="([^"]+)"', issue_response.data
    )
    assert temporary_password_match
    temporary_password = temporary_password_match.group(1).decode()

    db.session.refresh(student_user)
    assert student_user.credentials_enabled is True
    assert student_user.must_change_password is True
    assert student_user.temporary_password_used is False
    assert student_user.check_password(temporary_password, bcrypt)

    with client.session_transaction() as session:
        session['_user_id'] = str(student_user.id)
        session['student_auth_version'] = old_auth_version
    g.pop('_login_user', None)
    stale_response = client.get('/student/dashboard')
    assert stale_response.status_code == 302
    assert '/student/login' in stale_response.headers['Location']

    temporary_login = client.post(
        '/student/login',
        data={
            'identifier': student.student_number,
            'password': temporary_password,
        },
    )
    assert temporary_login.status_code == 302
    assert temporary_login.headers['Location'].endswith('/student/change-password')
    db.session.refresh(student_user)
    assert student_user.temporary_password_used is True

    change_page = client.get('/student/change-password')
    assert change_page.status_code == 200
    assert 'no-store' in change_page.headers['Cache-Control'].lower()
    change_response = client.post(
        '/student/change-password',
        data={
            'password': 'A-new-long-password-123',
            'confirm_password': 'A-new-long-password-123',
        },
    )

    assert change_response.status_code == 302
    assert change_response.headers['Location'].endswith('/student/dashboard')
    db.session.refresh(student_user)
    assert student_user.must_change_password is False
    assert student_user.temporary_password_used is False
    assert student_user.check_password('A-new-long-password-123', bcrypt)


def test_temporary_password_cannot_be_reused_after_sign_out(auth_app):
    student = _make_student_record('AUTH-ONE-TIME')
    temporary_password = 'temporary-password-123'
    user = User(
        username=student.student_number,
        password_hash=bcrypt.generate_password_hash(temporary_password).decode(),
        role='student',
        credentials_enabled=True,
        must_change_password=True,
    )
    db.session.add(user)
    db.session.commit()
    client = auth_app.test_client()

    first_login = client.post(
        '/student/login',
        data={
            'identifier': student.student_number,
            'password': temporary_password,
        },
    )
    assert first_login.status_code == 302
    assert first_login.headers['Location'].endswith('/student/change-password')
    db.session.refresh(user)
    assert user.temporary_password_used is True

    client.get('/student/logout')
    second_login = client.post(
        '/student/login',
        data={
            'identifier': student.student_number,
            'password': temporary_password,
        },
    )

    assert second_login.status_code == 200
    assert b'temporary password has already been used' in second_login.data


def test_teacher_cannot_issue_student_password(auth_app):
    student = _make_student_record('AUTH-FORBIDDEN')
    teacher = User(
        username='auth-teacher',
        password_hash='unused',
        role='teacher',
    )
    db.session.add(teacher)
    db.session.commit()
    client = auth_app.test_client()
    _login_as(client, teacher)

    response = client.post(f'/students/{student.id}/issue_login_password')

    assert response.status_code == 403
    assert User.query.filter_by(username=student.student_number).first() is None


def test_student_cannot_view_another_students_profile(auth_app):
    own = _make_student_record('AUTH-OWN')
    other = _make_student_record('AUTH-OTHER')
    user = User(
        username=own.student_number,
        password_hash='unused',
        role='student',
    )
    db.session.add(user)
    db.session.commit()
    client = auth_app.test_client()
    _login_as(client, user)

    response = client.get(f'/students/{other.id}')

    assert response.status_code == 403


def test_auth_migration_disables_existing_student_accounts():
    migration_path = os.path.join(
        os.path.dirname(__file__),
        'migrations',
        'versions',
        '8f2d4a6c1b90_student_password_auth.py',
    )
    spec = importlib.util.spec_from_file_location('student_auth_migration', migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(sa.text(
            'CREATE TABLE users (id INTEGER PRIMARY KEY, role VARCHAR(20) NOT NULL)'
        ))
        connection.execute(sa.text(
            "INSERT INTO users (id, role) VALUES (1, 'admin'), (2, 'student')"
        ))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()

        rows = connection.execute(sa.text(
            'SELECT role, must_change_password, credentials_enabled, '
            'temporary_password_used, auth_version FROM users ORDER BY id'
        )).all()

    assert rows[0] == ('admin', 0, 1, 0, 1)
    assert rows[1] == ('student', 1, 0, 0, 2)
