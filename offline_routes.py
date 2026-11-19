"""
offline_routes.py - additive blueprint for EduAssess.

  GET  /api/roster-tree           Form -> Learning Area -> Students (scoped to the user)
  POST /api/offline/assessment    idempotent score save used by the offline outbox
  POST /api/offline/quiz          server-side grading of a quiz taken offline

Nothing in the existing routes is modified. These endpoints are JSON-only and
return 401 (not a redirect) when the session has expired, so the browser-side
outbox knows to keep the data and ask the user to sign in again.
"""
from functools import wraps
import hashlib
import json
import math

from flask import Blueprint, jsonify, request, current_app
from flask_login import current_user
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from db import db
from models import (Student, Assessment, Quiz, Question, QuizAttempt,
                    QuestionAttempt, Setting, OfflineSubmission, utcnow)

offline_bp = Blueprint('offline', __name__)


def api_login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'ok': False, 'message': 'Session expired. Please sign in again.'}), 401
        return f(*args, **kwargs)
    return wrapper


def _err(message, code=422):
    return jsonify({'ok': False, 'message': message}), code


def _submission_details(data, kind):
    supplied_id = data.get('submission_id')
    if supplied_id is not None:
        if not isinstance(supplied_id, str) or not supplied_id.strip() or len(supplied_id) > 80:
            return None, None
        submission_id = supplied_id.strip()
    else:
        # Older queued entries predate explicit IDs. A deterministic fallback
        # lets their retries remain idempotent after this release.
        identity = {
            'user_id': current_user.id,
            'kind': kind,
            'payload': data,
        }
        encoded = json.dumps(identity, sort_keys=True, separators=(',', ':'), default=str)
        submission_id = hashlib.sha256(encoded.encode('utf-8')).hexdigest()

    payload = {key: value for key, value in data.items() if key != 'submission_id'}
    identity = {
        'user_id': current_user.id,
        'kind': kind,
        'payload': payload,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(',', ':'), default=str)
    return submission_id, hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _receipt_matches(receipt, kind, payload_hash):
    return (receipt.user_id == current_user.id
            and receipt.kind == kind
            and receipt.payload_hash == payload_hash)


# ---------------------------------------------------------------------------
# Roster tree
# ---------------------------------------------------------------------------
@offline_bp.route('/api/roster-tree')
@api_login_required
def roster_tree():
    from app import get_teacher_students_query, ACTIVE_CATEGORIES

    is_teacher = current_user.is_teacher()
    if not (is_teacher or current_user.is_admin()):
        return _err('Forbidden', 403)

    # Only the seven columns the tree needs are selected (plain rows, not
    # ORM entities): for an admin on a 5,000-student school this avoids
    # building 5,000 Student objects on every roster request.
    cols = (Student.id, Student.student_number, Student.first_name, Student.last_name,
            Student.middle_name, Student.class_name, Student.study_area)
    if is_teacher:
        q = get_teacher_students_query(current_user)   # same authorisation as the rest of the app
        students = q.with_entities(*cols).all() if q is not None else []
    else:
        students = (db.session.query(*cols)
                    .order_by(Student.class_name, Student.last_name).all())

    filled = {}
    if is_teacher and current_user.subject and students:
        rows = (db.session.query(Assessment.student_id, Assessment.category)
                .filter(Assessment.student_id.in_([s.id for s in students]),
                        Assessment.subject == current_user.subject,
                        Assessment.archived == False,  # noqa: E712
                        Assessment.category.in_(ACTIVE_CATEGORIES))
                .distinct().all())
        for sid, _cat in rows:
            filled[sid] = filled.get(sid, 0) + 1

    area_labels = dict(current_app.config.get('STUDY_AREAS', []))
    class_order = [k for k, _ in current_app.config.get('CLASS_LEVELS', [])]

    forms = {}
    probe = Student()            # transient; only used for get_class_display()
    display_cache = {}
    for s in students:
        if s.class_name not in display_cache:
            probe.class_name = s.class_name
            display_cache[s.class_name] = probe.get_class_display() or 'Unassigned'
        cls = display_cache[s.class_name]
        if cls.lower().startswith('graduated'):
            continue
        akey = s.study_area or 'unassigned'
        aname = area_labels.get(akey) or ('Unassigned' if akey == 'unassigned'
                                          else akey.replace('_', ' ').title())
        area = forms.setdefault(cls, {}).setdefault(akey, {'key': akey, 'name': aname, 'students': []})
        area['students'].append({
            'id': s.id,
            'number': s.student_number,
            'name': ' '.join(p for p in [s.last_name, s.first_name, s.middle_name] if p),
            'filled': filled.get(s.id),
        })

    def form_rank(name):
        return class_order.index(name) if name in class_order else 999

    out = []
    for cls in sorted(forms, key=lambda n: (form_rank(n), n)):
        areas = sorted(forms[cls].values(), key=lambda a: a['name'])
        for a in areas:
            a['students'].sort(key=lambda x: x['name'].lower())
            a['count'] = len(a['students'])
        out.append({'name': cls, 'count': sum(a['count'] for a in areas), 'areas': areas})

    resp = jsonify({
        'ok': True,
        'scope': 'teacher' if is_teacher else 'admin',
        'subject': (current_user.get_subject_display() if is_teacher else None),
        'required': len(ACTIVE_CATEGORIES),
        'forms': out,
    })
    resp.headers['Cache-Control'] = 'private, no-cache'
    return resp


# ---------------------------------------------------------------------------
# Offline assessment sync (idempotent: same key => update, never duplicate)
# ---------------------------------------------------------------------------
@offline_bp.route('/api/offline/assessment', methods=['POST'])
@api_login_required
def sync_assessment():
    from app import ACTIVE_CATEGORIES, log_activity

    if not (current_user.is_teacher() or current_user.is_admin()):
        return _err('Forbidden', 403)
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return _err('Expected a JSON body', 415)

    snum = str(d.get('student_name') or d.get('student_number') or '').strip()
    category = str(d.get('category') or '').strip()
    subject = str(d.get('subject') or '').strip()

    if current_user.is_teacher():
        if not current_user.subject:
            return _err('No subject is assigned to your account.', 403)
        subject = current_user.subject          # never trust the client for this

    if category not in ACTIVE_CATEGORIES:
        return _err('Invalid assessment category.')
    allowed_subjects = {key for key, _label in current_app.config.get('LEARNING_AREAS', [])}
    if subject not in allowed_subjects:
        return _err('Invalid subject.')
    try:
        score = float(d.get('score'))
    except (TypeError, ValueError):
        return _err('Score must be a number.')
    if not math.isfinite(score):
        return _err('Score must be a finite number.')
    max_score = current_app.config['CATEGORY_MAX_SCORES'].get(category, 100.0)
    if score < 0 or score > max_score:
        return _err(f'Score must be between 0 and {max_score:g}.')

    st = Setting.query.first()
    term = str(d.get('term') or (st.current_term if st else '')).strip()
    year = str(d.get('academic_year') or (st.current_academic_year if st else '')).strip()
    session_ = str(d.get('session') or (st.current_session if st else '')).strip()
    allowed_terms = {key for key, _label in current_app.config.get('TERMS', [])}
    if term not in allowed_terms:
        return _err('Invalid academic term.')
    if not year or len(year) > 32:
        return _err('Academic year is required and must be 32 characters or fewer.')
    if not session_ or len(session_) > 32:
        return _err('Academic session is required and must be 32 characters or fewer.')

    assessor = str(d.get('assessor') or current_user.username or '').strip()
    comments = d.get('comments')
    if len(assessor) > 120:
        return _err('Assessor name must be 120 characters or fewer.')
    if comments is not None and (not isinstance(comments, str) or len(comments) > 5000):
        return _err('Comments must be text no longer than 5000 characters.')
    submission_id, payload_hash = _submission_details(d, 'assessment')
    if not submission_id:
        return _err('Invalid submission identifier.')

    student = (Student.query.filter_by(student_number=snum)
               .with_for_update().first())
    if not student:
        return _err('Student record not found.')
    if current_user.is_teacher() and not current_user.can_access_student(student, current_app.config):
        return _err('You are not allowed to enter results for this student.', 403)
    tid = current_user.id if current_user.is_teacher() else None

    try:
        receipt = OfflineSubmission.query.filter_by(submission_id=submission_id).first()
        if receipt:
            if not _receipt_matches(receipt, 'assessment', payload_hash):
                return _err('Submission identifier was already used for different data.', 409)
            return jsonify({'ok': True, 'status': 'duplicate',
                            'message': 'Assessment was already synchronized.'})

        matches = Assessment.query.filter_by(
            student_id=student.id, category=category, subject=subject, term=term,
            academic_year=year, session=session_, teacher_id=tid, archived=False).all()
        if matches:
            duplicate = next((a for a in matches
                              if a.score == score and a.max_score == max_score), None)
            if not duplicate:
                return _err('An assessment already exists for this period. '
                            'The existing result was not changed.', 409)
            assessment = duplicate
            status = 'duplicate'
        else:
            assessment = Assessment(
                student=student, category=category, subject=subject,
                class_name=student.class_name, score=score, max_score=max_score,
                term=term, academic_year=year, session=session_, teacher_id=tid,
                assessor=assessor, comments=comments,
            )
            db.session.add(assessment)
            status = 'created'
        db.session.flush()
        db.session.add(OfflineSubmission(
            submission_id=submission_id, user_id=current_user.id,
            kind='assessment', payload_hash=payload_hash,
            result_id=assessment.id,
        ))
        db.session.commit()
        cache_backends = current_app.extensions.get('cache')
        if not cache_backends:
            raise RuntimeError('Application cache is not configured')
        for backend in cache_backends.values():
            backend.delete('incomplete_assessments')
        if status == 'created':
            log_activity(current_user, 'offline_sync_assessment',
                         f'created {category} for {student.full_name()}')
    except IntegrityError:
        db.session.rollback()
        receipt = OfflineSubmission.query.filter_by(submission_id=submission_id).first()
        if receipt and _receipt_matches(receipt, 'assessment', payload_hash):
            return jsonify({'ok': True, 'status': 'duplicate',
                            'message': 'Assessment was already synchronized.'})
        current_app.logger.exception('offline assessment sync hit a database constraint')
        return _err('Server could not save this entry. It will be retried.', 500)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('offline assessment sync failed')
        return _err('Server could not save this entry. It will be retried.', 500)

    return jsonify({'ok': True, 'status': status,
                    'message': f'{student.full_name()} saved ({status}).'})


# ---------------------------------------------------------------------------
# Offline quiz submission (graded on the server, exactly like take_quiz)
# ---------------------------------------------------------------------------
@offline_bp.route('/api/offline/quiz', methods=['POST'])
@api_login_required
def sync_quiz():
    from app import calculate_short_answer_score
    from flask import url_for

    if not current_user.is_student():
        return _err('Forbidden', 403)
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return _err('Expected a JSON body', 415)

    try:
        quiz = db.session.get(Quiz, int(d.get('quiz_id')))
    except (TypeError, ValueError):
        quiz = None
    if not quiz or not quiz.is_active:
        return _err('This quiz is no longer available.', 404)

    student = Student.query.filter(
        db.func.trim(Student.student_number) == (current_user.username or '').strip()).first()
    if not student:
        return _err('Student record not found.', 404)

    answers = d.get('answers')
    if not isinstance(answers, dict):
        return _err('Quiz answers must be a JSON object.')
    try:
        time_taken = int(d.get('time_taken') or 0)
    except (TypeError, ValueError):
        return _err('Quiz time must be a non-negative integer.')
    if time_taken < 0 or time_taken > 2_147_483_647:
        return _err('Quiz time must be a non-negative integer.')

    try:
        question_ids = [int(qid) for qid in quiz.questions]
    except (TypeError, ValueError):
        return _err('Quiz question list is invalid.', 409)
    if len(set(question_ids)) != len(question_ids):
        return _err('Quiz contains duplicate questions.', 409)
    valid_answer_keys = {str(qid) for qid in question_ids}
    if any(key not in valid_answer_keys for key in answers):
        return _err('Quiz contains answers for unknown questions.')
    for answer in answers.values():
        if not isinstance(answer, (str, int, float, bool)) or len(str(answer)) > 500:
            return _err('Each answer must be text no longer than 500 characters.')

    submission_id, payload_hash = _submission_details(d, 'quiz')
    if not submission_id:
        return _err('Invalid submission identifier.')

    try:
        student = (Student.query.filter_by(id=student.id)
                   .with_for_update().populate_existing().first())
        receipt = OfflineSubmission.query.filter_by(submission_id=submission_id).first()
        if receipt:
            if not _receipt_matches(receipt, 'quiz', payload_hash):
                return _err('Submission identifier was already used for different data.', 409)
            attempt = db.session.get(QuizAttempt, receipt.result_id)
            redirect = (url_for('quiz_attempt_review', attempt_id=attempt.id)
                        if attempt else url_for('student_quizzes'))
            return jsonify({'ok': True, 'status': 'duplicate',
                            'message': 'Quiz was already submitted.',
                            'redirect': redirect})

        done = QuizAttempt.query.filter_by(student_id=student.id, quiz_id=quiz.id,
                                           status='completed').first()
        if done:
            db.session.add(OfflineSubmission(
                submission_id=submission_id, user_id=current_user.id,
                kind='quiz', payload_hash=payload_hash, result_id=done.id,
            ))
            db.session.commit()
            return jsonify({'ok': True, 'status': 'duplicate',
                            'message': 'Quiz was already submitted.',
                            'redirect': url_for('quiz_attempt_review', attempt_id=done.id)})

        questions = {q.id: q for q in
                     Question.query.filter(Question.id.in_(question_ids)).all()}
        if set(questions) != set(question_ids):
            return _err('This quiz has changed and cannot be graded safely.', 409)

        attempt = QuizAttempt.query.filter_by(student_id=student.id, quiz_id=quiz.id,
                                              status='in_progress').first()
        if not attempt:
            attempt = QuizAttempt(student_id=student.id, quiz_id=quiz.id, score=0.0,
                                  total_questions=len(question_ids), correct_answers=0,
                                  started_at=utcnow())
            db.session.add(attempt)
            db.session.flush()

        total = 0.0
        correct_count = 0
        for qid in question_ids:
            ans = answers.get(str(qid))
            q = questions[qid]
            if ans in (None, ''):
                continue
            ans = str(ans)
            if q.question_type == 'mcq':
                ok = ans.strip().upper() == q.correct_answer.strip().upper()
                score = q.marks if ok else 0.0
            elif q.question_type == 'true_false':
                ok = ans.lower() == q.correct_answer.lower()
                score = q.marks if ok else 0.0
            else:
                score = calculate_short_answer_score(ans, q)
                ok = score > 0
            total += score
            correct_count += 1 if score > 0 else 0
            db.session.add(QuestionAttempt(student_id=student.id, question_id=q.id,
                                           quiz_attempt_id=attempt.id, student_answer=ans,
                                           is_correct=ok, score=score))
        attempt.score = total
        attempt.correct_answers = correct_count
        attempt.completed_at = utcnow()
        attempt.time_taken = time_taken
        attempt.status = 'completed'
        attempt.answers_json = None
        db.session.flush()
        db.session.add(OfflineSubmission(
            submission_id=submission_id, user_id=current_user.id,
            kind='quiz', payload_hash=payload_hash, result_id=attempt.id,
        ))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        receipt = OfflineSubmission.query.filter_by(submission_id=submission_id).first()
        if receipt and _receipt_matches(receipt, 'quiz', payload_hash):
            attempt = db.session.get(QuizAttempt, receipt.result_id)
            redirect = (url_for('quiz_attempt_review', attempt_id=attempt.id)
                        if attempt else url_for('student_quizzes'))
            return jsonify({'ok': True, 'status': 'duplicate',
                            'message': 'Quiz was already submitted.',
                            'redirect': redirect})
        current_app.logger.exception('offline quiz sync hit a database constraint')
        return _err('Server could not save this quiz. It will be retried.', 500)
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('offline quiz sync failed')
        return _err('Server could not save this quiz. It will be retried.', 500)

    return jsonify({'ok': True, 'status': 'created', 'message': 'Quiz submitted.',
                    'redirect': url_for('quiz_attempt_review', attempt_id=attempt.id)})
