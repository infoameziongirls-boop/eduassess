# api_v1.py — Register as a Blueprint
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
