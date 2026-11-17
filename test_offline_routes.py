import os

import pytest

from app import app, db
from models import (
    Assessment,
    OfflineSubmission,
    Question,
    QuestionAttempt,
    Quiz,
    QuizAttempt,
    Setting,
    Student,
    User,
)


@pytest.fixture
def offline_records():
    if os.environ.get('EDUASSESS_OFFLINE_TESTS') != '1':
        pytest.skip('set EDUASSESS_OFFLINE_TESTS=1 with the isolated offline test database')
    if 'offline-audit-tests.db' not in app.config['SQLALCHEMY_DATABASE_URI']:
        pytest.skip('refusing to alter a database not named offline-audit-tests.db')
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SESSION_COOKIE_SECURE'] = False

    with app.app_context():
        db.drop_all()
        db.create_all()
        admin = User(username='offline-admin', password_hash='unused', role='admin')
        student_user = User(
            username='OFFLINE-TEST-1', password_hash='unused', role='student'
        )
        student_user_2 = User(
            username='OFFLINE-TEST-2', password_hash='unused', role='student'
        )
        teacher = User(
            username='offline-teacher', password_hash='unused', role='teacher',
            subject='mathematics', class_name='Form 1',
        )
        teacher.set_classes_list(['Form 1'])
        db.session.add_all([admin, student_user, student_user_2, teacher])
        db.session.flush()

        students = [
            Student(student_number='OFFLINE-TEST-1', first_name='Test',
                    last_name='One', class_name='Form 1', study_area='science_a'),
            Student(student_number='OFFLINE-TEST-2', first_name='Test',
                    last_name='Two', class_name='Form 1', study_area='science_a'),
            Student(student_number='OFFLINE-TEST-3', first_name='Test',
                    last_name='Three', class_name='Form 2', study_area='science_a'),
        ]
        db.session.add_all(students)
        db.session.add(Setting(
            current_term='term1',
            current_academic_year='2026-2027',
            current_session='First Term',
        ))
        db.session.flush()

        question = Question(
            subject='mathematics',
            question_text='What is one plus one?',
            question_type='mcq',
            options=['A. 1', 'B. 2'],
            correct_answer='B',
            marks=1,
            created_by=admin.id,
            status='approved',
        )
        db.session.add(question)
        db.session.flush()
        quiz = Quiz(
            title='Offline route test',
            subject='mathematics',
            questions=[question.id],
            created_by=admin.id,
            is_active=True,
        )
        db.session.add(quiz)
        db.session.commit()

        ids = {
            'admin': admin.id,
            'teacher': teacher.id,
            'student_user': student_user.id,
            'students': {s.student_number: s.id for s in students},
            'quiz': quiz.id,
            'question': question.id,
        }

    yield ids

    with app.app_context():
        db.session.remove()
        db.drop_all()


def _client(user_id=None):
    client = app.test_client()
    if user_id is not None:
        with client.session_transaction() as session:
            session['_user_id'] = str(user_id)
            session['_fresh'] = True
            with app.app_context():
                user = db.session.get(User, user_id)
                if user and user.is_student():
                    session['student_auth_version'] = user.auth_version
    return client


def _assessment_payload(student_number, submission_id='assessment-test-1', score=37.5):
    return {
        'submission_id': submission_id,
        'student_name': student_number,
        'category': 'ica1',
        'subject': 'mathematics',
        'score': score,
        'term': 'term1',
        'academic_year': '2026-2027',
        'session': 'First Term',
        'assessor': 'offline-admin',
        'comments': '',
    }


def test_assessment_sync_is_idempotent_and_does_not_overwrite_existing_results(offline_records):
    client = _client(offline_records['admin'])
    payload = _assessment_payload('OFFLINE-TEST-1')

    first = client.post('/api/offline/assessment', json=payload)
    retry = client.post('/api/offline/assessment', json=payload)

    assert first.status_code == 200
    assert first.json['status'] == 'created'
    assert retry.status_code == 200
    assert retry.json['status'] == 'duplicate'
    with app.app_context():
        assert Assessment.query.filter_by(
            student_id=offline_records['students']['OFFLINE-TEST-1'],
            category='ica1',
            subject='mathematics',
        ).count() == 1
        assert OfflineSubmission.query.filter_by(kind='assessment').count() == 1

    changed_payload = dict(payload, score=12.0)
    changed = client.post('/api/offline/assessment', json=changed_payload)
    assert changed.status_code == 409
    with app.app_context():
        result = Assessment.query.filter_by(
            student_id=offline_records['students']['OFFLINE-TEST-1'],
            category='ica1',
            subject='mathematics',
        ).one()
        assert result.score == 37.5


def test_assessment_rejects_non_finite_scores_and_unauthorized_teacher_access(offline_records):
    admin = _client(offline_records['admin'])
    invalid = admin.post(
        '/api/offline/assessment',
        json=_assessment_payload('OFFLINE-TEST-1', score='nan'),
    )
    assert invalid.status_code == 422

    teacher = _client(offline_records['teacher'])
    forbidden = teacher.post(
        '/api/offline/assessment',
        json=_assessment_payload('OFFLINE-TEST-3', submission_id='teacher-test'),
    )
    assert forbidden.status_code == 403
    with app.app_context():
        assert Assessment.query.count() == 0


def test_quiz_sync_retry_creates_one_attempt_and_one_question_result(offline_records):
    client = _client(offline_records['student_user'])
    payload = {
        'submission_id': 'quiz-test-1',
        'quiz_id': offline_records['quiz'],
        'answers': {str(offline_records['question']): 'B'},
        'time_taken': 10,
        'student_id': offline_records['students']['OFFLINE-TEST-2'],
    }

    first = client.post('/api/offline/quiz', json=payload)
    retry = client.post('/api/offline/quiz', json=payload)

    assert first.status_code == 200
    assert first.json['status'] == 'created'
    assert retry.status_code == 200
    assert retry.json['status'] == 'duplicate'
    with app.app_context():
        student = Student.query.filter_by(student_number='OFFLINE-TEST-1').one()
        assert QuizAttempt.query.filter_by(
            student_id=student.id, quiz_id=offline_records['quiz']
        ).count() == 1
        assert QuizAttempt.query.filter_by(
            student_id=offline_records['students']['OFFLINE-TEST-2'],
            quiz_id=offline_records['quiz'],
        ).count() == 0
        assert QuestionAttempt.query.filter_by(student_id=student.id).count() == 1
        assert OfflineSubmission.query.filter_by(kind='quiz').count() == 1


def test_offline_sync_endpoints_require_authentication(offline_records):
    client = _client()

    assessment = client.post('/api/offline/assessment', json={})
    quiz = client.post('/api/offline/quiz', json={})

    assert assessment.status_code == 401
    assert quiz.status_code == 401


def test_student_can_reopen_quiz_list_with_an_in_progress_attempt(offline_records):
    client = _client(offline_records['student_user'])
    take = client.get(f"/student/quizzes/{offline_records['quiz']}/take")
    listing = client.get('/student/quizzes')

    assert take.status_code == 200
    assert listing.status_code == 200
    assert b'Resume Quiz' in listing.data


def test_simultaneous_assessment_syncs_for_distinct_students(offline_records):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(2)

    def submit(student_number, submission_id):
        client = _client(offline_records['admin'])
        barrier.wait()
        return client.post(
            '/api/offline/assessment',
            json=_assessment_payload(student_number, submission_id),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda args: submit(*args),
            [
                ('OFFLINE-TEST-1', 'parallel-1'),
                ('OFFLINE-TEST-2', 'parallel-2'),
            ],
        ))

    assert results == [200, 200]
    with app.app_context():
        assert Assessment.query.filter(
            Assessment.student_id.in_([
                offline_records['students']['OFFLINE-TEST-1'],
                offline_records['students']['OFFLINE-TEST-2'],
            ])
        ).count() == 2
