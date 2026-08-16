# api_v1.py — Register as a Blueprint
from datetime import datetime
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request
from flask_login import login_required, current_user

from db import db
from models import APIKey, Student, Assessment, Quiz, QuizAttempt, Setting

api_bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')


@api_bp.route('/student/profile')
@login_required
def student_profile():
    """Mobile: Get current student's profile"""
    if not current_user.is_student():
        return jsonify({'error': 'Forbidden'}), 403

    student = Student.query.filter_by(
        student_number=current_user.username
    ).first_or_404()

    return jsonify({
        'student_number': student.student_number,
        'full_name': student.full_name(),
        'class': student.get_class_display(),
        'study_area': student.get_study_area_display(),
        'reference_number': student.reference_number
    })


@api_bp.route('/student/assessments')
@login_required
def student_assessments_api():
    """Mobile: Get current student's assessments"""
    if not current_user.is_student():
        return jsonify({'error': 'Forbidden'}), 403

    student = Student.query.filter_by(
        student_number=current_user.username
    ).first_or_404()

    settings = Setting.query.first()
    if not settings or not settings.is_results_visible():
        return jsonify({
            'released': False,
            'release_date': settings.results_release_date.isoformat()
                             if settings and settings.results_release_date else None,
            'message': 'Results have not been released yet.',
            'assessments': []
        })

    subject = request.args.get('subject')
    query = Assessment.query.filter_by(student_id=student.id, archived=False)
    if subject:
        query = query.filter_by(subject=subject)

    assessments = query.order_by(Assessment.date_recorded.desc()).all()

    return jsonify({
        'released': True,
        'assessments': [
            {
                'id': a.id,
                'category': a.category,
                'subject': a.subject,
                'score': a.score,
                'max_score': a.max_score,
                'percentage': round(a.get_percentage(), 2),
                'grade': a.get_grade_letter(),
                'term': a.term,
                'date': a.date_recorded.strftime('%Y-%m-%d')
            }
            for a in assessments
        ]
    })


# ---------------------------------------------------------------------------
# External results-entry API (see EXTERNAL_RESULTS_API_INTEGRATION.md)
#
# Separate auth track from the student-facing routes above: those use
# session-based @login_required, this uses a Bearer API key issued via
# `flask create-api-key`. Keys are looked up by SHA-256 hash — the raw key
# is never stored, see APIKey.generate() in models.py.
# ---------------------------------------------------------------------------

def require_api_key(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({
                'error': 'Missing or malformed Authorization header. Expected: Bearer <API_KEY>'
            }), 401

        raw_key = auth_header[len('Bearer '):].strip()
        if not raw_key:
            return jsonify({'error': 'Missing API key'}), 401

        api_key = APIKey.query.filter_by(
            key_hash=APIKey.hash_key(raw_key), is_active=True
        ).first()

        if not api_key:
            return jsonify({'error': 'Invalid or inactive API key'}), 401

        api_key.touch()
        db.session.commit()
        g.api_key = api_key

        return f(*args, **kwargs)
    return wrapped


def _valid_categories():
    return set(current_app.config.get('CATEGORY_MAX_SCORES', {}).keys())


def _validate_assessment_payload(payload):
    """Shared validation for create/bulk/validate. Returns (student, errors)
    — student is None if not found or if validation failed before lookup."""
    errors = []

    student_number = (payload.get('student_number') or '').strip()
    category = (payload.get('category') or '').strip()
    subject = (payload.get('subject') or '').strip()

    if not student_number:
        errors.append('student_number is required')
    if not category:
        errors.append('category is required')
    elif category not in _valid_categories():
        errors.append(f'category must be one of: {", ".join(sorted(_valid_categories()))}')
    if not subject:
        errors.append('subject is required')

    score = payload.get('score')
    if score is None:
        errors.append('score is required')
    else:
        try:
            score = float(score)
            if score < 0:
                errors.append('score cannot be negative')
        except (TypeError, ValueError):
            errors.append('score must be a number')

    max_score = payload.get('max_score')
    if max_score is not None:
        try:
            max_score = float(max_score)
        except (TypeError, ValueError):
            errors.append('max_score must be a number')

    if (
        isinstance(score, (int, float))
        and isinstance(max_score, (int, float))
        and score > max_score
    ):
        errors.append('score cannot exceed max_score')

    student = None
    if student_number and not errors:
        student = Student.query.filter_by(student_number=student_number).first()
        if not student:
            errors.append(f'No student found with student_number "{student_number}"')

    return student, errors


def _upsert_assessment(payload, student):
    """Create or update the matching Assessment row. Re-syncing the same
    student/category/subject/term/academic_year/session updates the
    existing row in place rather than erroring — a results sync is expected
    to be re-run as scores are corrected, unlike the one-shot Excel import
    this logic is adapted from."""
    category = payload['category'].strip()
    subject = payload['subject'].strip()
    term = payload.get('term')
    academic_year = payload.get('academic_year')
    session_value = payload.get('session')
    max_score = payload.get('max_score')
    default_max = current_app.config.get('CATEGORY_MAX_SCORES', {}).get(category, 100.0)

    assessment = Assessment.query.filter_by(
        student_id=student.id,
        category=category,
        subject=subject,
        term=term,
        academic_year=academic_year,
        session=session_value,
    ).first()

    status = 'updated' if assessment else 'created'

    if not assessment:
        assessment = Assessment(
            student_id=student.id,
            category=category,
            subject=subject,
            class_name=student.class_name,
            term=term,
            academic_year=academic_year,
            session=session_value,
        )
        db.session.add(assessment)

    assessment.score = float(payload['score'])
    assessment.max_score = float(max_score) if max_score is not None else float(default_max)
    assessment.assessor = payload.get('assessor')
    if payload.get('comments'):
        assessment.comments = payload['comments']

    return assessment, status


@api_bp.route('/students/lookup', methods=['GET'])
@require_api_key
def lookup_student():
    student_number = (request.args.get('student_number') or '').strip()
    if not student_number:
        return jsonify({'error': 'student_number query parameter is required'}), 400

    student = Student.query.filter_by(student_number=student_number).first()
    if not student:
        return jsonify({'error': f'No student found with student_number "{student_number}"'}), 404

    return jsonify({
        'student_number': student.student_number,
        'full_name': student.full_name(),
        'class': student.get_class_display(),
        'study_area': student.get_study_area_display(),
    })


@api_bp.route('/assessments/validate', methods=['POST'])
@require_api_key
def validate_assessments():
    """Dry run: checks every item the same way create/bulk would, but never
    writes to the database. Lets an integration catch unmapped students or
    bad categories before actually pushing scores."""
    payload = request.get_json(silent=True) or {}
    items = payload.get('assessments')
    if items is None:
        items = [payload] if payload else []

    results = []
    valid_count = 0

    for item in items:
        student, errors = _validate_assessment_payload(item)
        ok = not errors
        if ok:
            valid_count += 1
        results.append({
            'student_number': item.get('student_number'),
            'category': item.get('category'),
            'valid': ok,
            'errors': errors,
        })

    return jsonify({
        'success': True,
        'valid': valid_count,
        'invalid': len(results) - valid_count,
        'results': results,
    })


@api_bp.route('/assessments/create', methods=['POST'])
@require_api_key
def create_assessment():
    payload = request.get_json(silent=True) or {}
    student, errors = _validate_assessment_payload(payload)

    if errors:
        return jsonify({'success': False, 'errors': errors}), 422

    assessment, status = _upsert_assessment(payload, student)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': f'Assessment {status} successfully',
        'assessment_id': assessment.id,
    }), 201


@api_bp.route('/assessments/bulk', methods=['POST'])
@require_api_key
def bulk_assessments():
    payload = request.get_json(silent=True) or {}
    items = payload.get('assessments')

    if not isinstance(items, list) or not items:
        return jsonify({
            'success': False,
            'errors': ['Request body must include a non-empty "assessments" array'],
        }), 422

    successful = 0
    failed = 0
    errors = []
    results = []

    for item in items:
        student, item_errors = _validate_assessment_payload(item)

        if item_errors:
            failed += 1
            errors.append(f'{item.get("student_number", "unknown")}: {"; ".join(item_errors)}')
            results.append({
                'student_number': item.get('student_number'),
                'category': item.get('category'),
                'status': 'failed',
                'errors': item_errors,
            })
            continue

        assessment, status = _upsert_assessment(item, student)
        successful += 1
        results.append({
            'student_number': item.get('student_number'),
            'category': item.get('category'),
            'status': status,
            'assessment_id': assessment.id,
        })

    db.session.commit()

    return jsonify({
        'success': True,
        'successful': successful,
        'failed': failed,
        'errors': errors,
        'results': results,
    }), 200 if failed == 0 else 207


def _serialize_assessment(a):
    return {
        'id': a.id,
        'student_number': a.student.student_number if a.student else None,
        'student_name': a.student.full_name() if a.student else None,
        'category': a.category,
        'subject': a.subject,
        'class_name': a.class_name,
        'score': a.score,
        'max_score': a.max_score,
        'term': a.term,
        'academic_year': a.academic_year,
        'session': a.session,
        'assessor': a.assessor,
        'comments': a.comments,
        'date_recorded': a.date_recorded.isoformat() if a.date_recorded else None,
    }


@api_bp.route('/assessments', methods=['GET'])
@require_api_key
def list_assessments():
    """Filtered, paginated listing — the read side of this API, added after
    a sync run created duplicate rows because the caller's term/academic_year
    labels didn't match what was already stored. This is what lets an
    integration audit what it actually wrote (or what anything wrote) before
    touching it further, instead of guessing from write-side responses
    alone."""
    query = Assessment.query.join(Student)

    filters = {
        'student_number': lambda v: query.filter(Student.student_number == v),
        'category': lambda v: query.filter(Assessment.category == v),
        'subject': lambda v: query.filter(Assessment.subject == v),
        'term': lambda v: query.filter(Assessment.term == v),
        'academic_year': lambda v: query.filter(Assessment.academic_year == v),
        'session': lambda v: query.filter(Assessment.session == v),
        'assessor': lambda v: query.filter(Assessment.assessor == v),
    }
    for param, apply in filters.items():
        value = request.args.get(param)
        if value:
            query = apply(value)

    for param, column in (('created_after', Assessment.date_recorded), ('created_before', Assessment.date_recorded)):
        value = request.args.get(param)
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return jsonify({'error': f'{param} must be an ISO date/datetime, e.g. 2026-08-15'}), 400
        query = query.filter(column >= parsed) if param == 'created_after' else query.filter(column <= parsed)

    total = query.count()

    try:
        limit = min(int(request.args.get('limit', 50)), 500)
        offset = max(int(request.args.get('offset', 0)), 0)
    except ValueError:
        return jsonify({'error': 'limit and offset must be integers'}), 400

    rows = query.order_by(Assessment.date_recorded.desc()).offset(offset).limit(limit).all()

    return jsonify({
        'total': total,
        'count': len(rows),
        'limit': limit,
        'offset': offset,
        'results': [_serialize_assessment(a) for a in rows],
    })


@api_bp.route('/assessments/<int:assessment_id>', methods=['GET'])
@require_api_key
def get_assessment(assessment_id):
    assessment = Assessment.query.get(assessment_id)
    if not assessment:
        return jsonify({'error': f'No assessment with id {assessment_id}'}), 404

    return jsonify(_serialize_assessment(assessment))


@api_bp.route('/assessments/<int:assessment_id>', methods=['PUT', 'PATCH'])
@require_api_key
def update_assessment(assessment_id):
    assessment = Assessment.query.get(assessment_id)
    if not assessment:
        return jsonify({'error': f'No assessment with id {assessment_id}'}), 404

    payload = request.get_json(silent=True) or {}
    errors = []

    if 'score' in payload:
        try:
            score = float(payload['score'])
            if score < 0:
                errors.append('score cannot be negative')
        except (TypeError, ValueError):
            errors.append('score must be a number')
            score = None
    else:
        score = assessment.score

    if 'max_score' in payload:
        try:
            max_score = float(payload['max_score'])
        except (TypeError, ValueError):
            errors.append('max_score must be a number')
            max_score = None
    else:
        max_score = assessment.max_score

    if isinstance(score, (int, float)) and isinstance(max_score, (int, float)) and score > max_score:
        errors.append('score cannot exceed max_score')

    if errors:
        return jsonify({'success': False, 'errors': errors}), 422

    assessment.score = score
    assessment.max_score = max_score
    if 'assessor' in payload:
        assessment.assessor = payload['assessor']
    if 'comments' in payload:
        assessment.comments = payload['comments']

    db.session.commit()

    return jsonify({'success': True, 'message': 'Assessment updated successfully', 'assessment': _serialize_assessment(assessment)})


@api_bp.route('/assessments/<int:assessment_id>', methods=['DELETE'])
@require_api_key
def delete_assessment(assessment_id):
    assessment = Assessment.query.get(assessment_id)
    if not assessment:
        return jsonify({'error': f'No assessment with id {assessment_id}'}), 404

    deleted = _serialize_assessment(assessment)
    db.session.delete(assessment)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Assessment deleted', 'deleted': deleted})


@api_bp.route('/assessments/bulk-delete', methods=['POST'])
@require_api_key
def bulk_delete_assessments():
    """Deliberately ID-only, no filter-based mass delete. The caller is
    expected to have already listed and reviewed exactly which rows they
    mean via GET /assessments — that review step is the safety rail, not
    anything enforced here beyond requiring explicit ids. Capped at 500 per
    call, same as the list endpoint's page size, so a single request can't
    silently touch more than a caller could have actually reviewed."""
    payload = request.get_json(silent=True) or {}
    ids = payload.get('ids')

    if not isinstance(ids, list) or not ids:
        return jsonify({'success': False, 'errors': ['Request body must include a non-empty "ids" array']}), 422

    if len(ids) > 500:
        return jsonify({'success': False, 'errors': ['Cannot delete more than 500 ids in a single call']}), 422

    deleted = []
    not_found = []

    for raw_id in ids:
        try:
            assessment_id = int(raw_id)
        except (TypeError, ValueError):
            not_found.append(raw_id)
            continue

        assessment = Assessment.query.get(assessment_id)
        if not assessment:
            not_found.append(assessment_id)
            continue

        deleted.append(_serialize_assessment(assessment))
        db.session.delete(assessment)

    db.session.commit()

    return jsonify({
        'success': True,
        'deleted_count': len(deleted),
        'not_found': not_found,
        'deleted': deleted,
    })
