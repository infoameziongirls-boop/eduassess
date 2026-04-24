import os
import sys
import pytest

# Ensure the application root is on the import path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db, canonical_class_key, canonical_study_area_key
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


def create_admin_user():
    admin = User(username='admin_test', password_hash='x', role='admin')
    db.session.add(admin)
    db.session.commit()
    return admin


def login_as(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


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


def test_student_new_normalizes_class_and_study_area(client):
    admin = create_admin_user()
    login_as(client, admin)

    response = client.post(
        '/students/new',
        data={
            'student_number': 'STU_CAN',
            'first_name': 'Canon',
            'last_name': 'Tester',
            'middle_name': 'N',
            'class_name': 'Form 1',
            'study_area': 'science_a'
        },
        follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/students')

    student = Student.query.filter_by(student_number='STU_CAN').first()
    assert student is not None
    assert student.class_name == 'Form 1'
    assert student.study_area == 'science_a'


def test_student_edit_normalizes_class_and_study_area(client):
    admin = create_admin_user()
    student = Student(
        student_number='STU_EDIT',
        first_name='Edit',
        last_name='Tester',
        reference_number='REFEDIT',
        class_name='form1',
        study_area='science a'
    )
    db.session.add(student)
    db.session.commit()

    login_as(client, admin)

    response = client.post(
        f'/students/{student.id}/edit',
        data={
            'student_number': 'STU_EDIT',
            'first_name': 'Edit',
            'last_name': 'Tester',
            'middle_name': '',
            'class_name': 'Form 1',
            'study_area': 'science_a'
        },
        follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/students')

    student = Student.query.get(student.id)
    assert student.class_name == 'Form 1'
    assert student.study_area == 'science_a'


def test_canonical_helpers_normalize_inputs():
    assert canonical_class_key('form1') == 'Form 1'
    assert canonical_class_key('Form 2') == 'Form 2'
    assert canonical_class_key('FORM3') == 'Form 3'
    assert canonical_class_key('form 1') == 'Form 1'
    assert canonical_class_key('  form_2  ') == 'Form 2'

    assert canonical_study_area_key('science_a') == 'science_a'
    assert canonical_study_area_key('Science A') == 'science_a'
    assert canonical_study_area_key('home economics b') == 'home_economics_b'
    assert canonical_study_area_key('visual performing arts') == 'visual_performing_arts'
    assert canonical_study_area_key('  business-c  ') == 'business_c'
