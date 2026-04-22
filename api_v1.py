# api_v1.py — Register as a Blueprint
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from models import Student, Assessment, Quiz, QuizAttempt

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

    subject = request.args.get('subject')
    query = Assessment.query.filter_by(student_id=student.id, archived=False)
    if subject:
        query = query.filter_by(subject=subject)

    assessments = query.order_by(Assessment.date_recorded.desc()).all()

    return jsonify({
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
