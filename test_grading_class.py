import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db, calculate_gpa_and_grade, get_grade_class_division
from models import Student, User


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


def test_grading_class_derived_from_overall_final_pct(client, monkeypatch):
    # create a student and corresponding user
    student = Student(first_name='GTest', last_name='User', student_number='GT001', reference_number='REFGT', class_name='Form 1', study_area='Science')
    db.session.add(student)
    db.session.commit()
    user = User(username=student.student_number, password_hash='x', role='student')
    db.session.add(user)
    db.session.commit()

    # monkeypatch Student.calculate_final_grade to return a known overall percent
    expected_percent = 72.0
    monkeypatch.setattr(Student, 'calculate_final_grade', lambda self, subject=None, teacher_id=None: expected_percent)

    # compute expected division from helper functions
    expected_gpa_grade = calculate_gpa_and_grade(expected_percent)
    expected_division = get_grade_class_division(expected_gpa_grade['gpa'])

    # simulate logged-in student session
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True

    res = client.get('/student/dashboard')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert expected_division in html
