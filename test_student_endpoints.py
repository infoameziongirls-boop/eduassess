import os
import sys
import pytest

# Ensure the application root is on the import path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import Student, User


@pytest.fixture(scope="function")
def app_context():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture(scope="function")
def client(app_context):
    return app.test_client()


def create_student(first_name, last_name, student_number, reference_number):
    student = Student(
        first_name=first_name,
        last_name=last_name,
        student_number=student_number,
        reference_number=reference_number,
        class_name='form1',
        study_area='mathematics'
    )
    db.session.add(student)
    db.session.commit()
    return student


def test_student_login_get_shows_form(client):
    response = client.get('/student/login')

    assert response.status_code == 200
    assert b'Student Number or Reference Number' in response.data
    assert b'Enter your Student Number or Reference Number' in response.data


def test_student_login_with_trimmed_credentials_redirects_to_dashboard(client):
    create_student(
        first_name='John',
        last_name='Doe',
        student_number=' STU123 ',
        reference_number=' REF123 '
    )

    response = client.post(
        '/student/login',
        data={
            'identifier': 'STU123'
        },
        follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/student/dashboard')

    user = User.query.filter_by(username='STU123').first()
    assert user is not None
    assert user.role == 'student'


def test_student_login_unknown_identifier_shows_error(client):
    create_student(
        first_name='Jane',
        last_name='Smith',
        student_number='STU999',
        reference_number='REF999'
    )

    response = client.post(
        '/student/login',
        data={
            'identifier': 'UNKNOWN123'
        },
        follow_redirects=True
    )

    assert response.status_code == 200
    assert b'No student record was found' in response.data or b'No student record' in response.data
    assert b'Student Number or Reference Number' in response.data
