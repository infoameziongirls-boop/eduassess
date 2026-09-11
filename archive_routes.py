"""
archive_routes.py  –  Graduated Students Archive
══════════════════════════════════════════════════
Browse graduated classes as year "folders" and view each graduate's
final (Form 3) transcript, reconstructed from their archived
assessments. Uses the existing "Graduated <year>" class_name string
that promotion_routes.execute_promotion() already produces when Form 3
is promoted — no schema changes, no migration.

INSTALLATION (3 steps in app.py):

  1.  Near the top with other blueprint imports:
          from archive_routes import archive_bp

  2.  After  app.register_blueprint(promotion_bp) :
          app.register_blueprint(archive_bp)

  3.  Copy admin/archive_index.html, admin/archive_roster.html and
      admin/archive_transcript.html into your templates/ folder
      (adjust the {% extends %} at the top of each to match your
      actual base template name if it isn't "base.html").

NOTE: app.py's get_incomplete_assessments() imports GRADUATION_PREFIX
from this module to exclude graduated students from the "Students
Needing Attention" panel — keep that name if you rename anything here.
"""
from __future__ import annotations
from datetime import datetime, timezone

from flask import Blueprint, render_template, abort, current_app
from flask_login import login_required, current_user
from sqlalchemy import func

archive_bp = Blueprint('archive', __name__, url_prefix='/admin/archive')

# The exact prefix promotion_routes._graduation_label() writes into
# Student.class_name, e.g. "Graduated 2025". Keep these in sync if
# that function's format ever changes.
GRADUATION_PREFIX = 'Graduated '

# The class a student was in immediately before graduating — i.e.
# promotion_routes.CLASS_SEQUENCE[-1]. Assessments recorded under this
# class_name, now archived, are that student's final-year results.
FINAL_ACTIVE_CLASS = 'Form 3'


def utcnow():
    return datetime.now(timezone.utc)


def _is_graduated_label(class_name) -> bool:
    return bool(class_name) and class_name.startswith(GRADUATION_PREFIX)


def _year_sort_key(label: str):
    """Sort 'Graduated 2025' style labels newest-first; anything that
    doesn't parse falls back to the end of the list rather than erroring."""
    tail = label.replace(GRADUATION_PREFIX, '').strip()
    try:
        return -int(tail)
    except ValueError:
        return 0


def _academic_year_sort_key(label: str):
    try:
        return -int(str(label).split('-', 1)[0])
    except (TypeError, ValueError):
        return 0


def _term_label(term: str) -> str:
    labels = {'term1': 'Semester 1', 'term2': 'Semester 2', 'term3': 'Semester 3'}
    return labels.get(term, term.replace('_', ' ').title() if term else 'Unspecified Semester')


def _term_sort_key(term: str):
    configured = [key for key, _ in current_app.config.get('TERMS', [])]
    try:
        return (configured.index(term), '')
    except ValueError:
        return (len(configured), term or '')


def _archive_rows(academic_year=None, term=None, class_label=None):
    """Return archived assessment rows that belong to the graduated archive."""
    from models import Assessment, Student

    query = (Assessment.query
             .join(Student, Student.id == Assessment.student_id)
             .filter(Assessment.archived == True,
                     Student.class_name.ilike(f'{GRADUATION_PREFIX}%')))
    if academic_year:
        query = query.filter(Assessment.academic_year == academic_year)
    if term:
        query = query.filter(Assessment.term == term)
    if class_label:
        query = query.filter(Student.class_name == class_label)
    return query.all()


def _archive_years():
    rows = _archive_rows()
    grouped = {}
    for assessment in rows:
        year = assessment.academic_year or 'Unspecified Academic Year'
        grouped.setdefault(year, set()).add(assessment.student_id)
    return [
        {'label': year, 'count': len(student_ids)}
        for year, student_ids in sorted(
            grouped.items(), key=lambda item: _academic_year_sort_key(item[0])
        )
    ]


def _calc_final_transcript(student_id: int, academic_year=None, term=None):
    """Reconstruct a graduated student's final-year results from their
    archived FINAL_ACTIVE_CLASS assessments. Read-only — never touches
    non-archived data and never modifies anything."""
    from models import Assessment
    from app import GRADE_POINT_MAP, normalize_label
    from template_updater import calculate_scores_from_template, scores_from_assessments

    assessments = (Assessment.query
                   .filter_by(student_id=student_id,
                              class_name=FINAL_ACTIVE_CLASS,
                              archived=True)
                   .all())
    if academic_year:
        assessments = [a for a in assessments if a.academic_year == academic_year]
    if term:
        assessments = [a for a in assessments if a.term == term]

    subject_groups = {}
    for a in assessments:
        if not a.subject:
            continue
        key = normalize_label(a.subject)
        if not key:
            continue
        subject_groups.setdefault(key, []).append(a)

    subjects = {}
    for key, items in subject_groups.items():
        raw = scores_from_assessments(items)
        if not raw:
            continue
        result = calculate_scores_from_template(raw)
        grade = result['grade']
        subjects[key] = {
            'subject':       items[0].subject,
            'final_percent': float(result['final_score']),
            'grade':         grade,
            'gpa':           result['gpa'],
            'grade_point':   GRADE_POINT_MAP.get(grade),
        }

    overall_percent = None
    if subjects:
        percents = [s['final_percent'] for s in subjects.values()]
        overall_percent = round(sum(percents) / len(percents), 2)

    return {
        'subjects':        dict(sorted(subjects.items(), key=lambda kv: kv[1]['subject'])),
        'overall_percent': overall_percent,
        'has_data':        bool(subjects),
    }


@archive_bp.route('/')
@login_required
def archive_index():
    if not current_user.is_admin():
        abort(403)
    years = _archive_years()

    return render_template('archive_index.html', years=years, now=utcnow())


@archive_bp.route('/year/<path:academic_year>')
@login_required
def archive_year(academic_year):
    if not current_user.is_admin():
        abort(403)
    rows = _archive_rows(academic_year=academic_year)
    grouped = {}
    for assessment in rows:
        term = assessment.term or 'unspecified'
        grouped.setdefault(term, set()).add(assessment.student_id)
    # Always expose every configured semester, even before scores have been
    # entered for it. This keeps the archive structure predictable.
    for term, _label in current_app.config.get('TERMS', []):
        grouped.setdefault(term, set())
    semesters = [
        {'key': term, 'label': _term_label(term), 'count': len(student_ids)}
        for term, student_ids in sorted(grouped.items(), key=lambda item: _term_sort_key(item[0]))
    ]
    return render_template(
        'archive_semesters.html', academic_year=academic_year,
        semesters=semesters, now=utcnow()
    )


@archive_bp.route('/year/<path:academic_year>/semester/<path:term>')
@login_required
def archive_semester(academic_year, term):
    if not current_user.is_admin():
        abort(403)
    rows = _archive_rows(academic_year=academic_year, term=term)
    grouped = {}
    for assessment in rows:
        grouped.setdefault(assessment.student.class_name, set()).add(assessment.student_id)
    classes = [
        {'label': label, 'count': len(student_ids)}
        for label, student_ids in sorted(grouped.items(), key=lambda item: _year_sort_key(item[0]))
    ]
    return render_template(
        'archive_classes.html', academic_year=academic_year, term=term,
        term_label=_term_label(term), classes=classes, now=utcnow()
    )


@archive_bp.route('/<path:label>')
@login_required
def archive_roster(label):
    from models import Student

    if not current_user.is_admin():
        abort(403)
    if not _is_graduated_label(label):
        abort(404)

    students = (
        Student.query
        .filter_by(class_name=label)
        .order_by(Student.last_name, Student.first_name)
        .all()
    )

    return render_template('archive_roster.html', label=label, students=students, now=utcnow())


@archive_bp.route('/year/<path:academic_year>/semester/<path:term>/class/<path:label>')
@login_required
def archive_class_roster(academic_year, term, label):
    from models import Student

    if not current_user.is_admin() or not _is_graduated_label(label):
        abort(404)
    student_ids = {a.student_id for a in _archive_rows(academic_year, term, label)}
    students = (Student.query.filter(Student.id.in_(student_ids))
                .order_by(Student.last_name, Student.first_name).all()) if student_ids else []
    return render_template(
        'archive_roster.html', label=label, students=students,
        academic_year=academic_year, term=term, term_label=_term_label(term),
        now=utcnow()
    )


@archive_bp.route('/<path:label>/student/<int:student_id>')
@login_required
def archive_transcript(label, student_id):
    from models import Student

    if not current_user.is_admin():
        abort(403)
    if not _is_graduated_label(label):
        abort(404)

    student = Student.query.get_or_404(student_id)
    if student.class_name != label:
        # Prevents /archive/Graduated 2025/student/<id-from-a-different-year>
        # from resolving — keeps the URL's year folder and the student's
        # actual record honest with each other.
        abort(404)

    transcript = _calc_final_transcript(student.id)

    return render_template(
        'archive_transcript.html',
        label=label, student=student, transcript=transcript, now=utcnow(),
    )


@archive_bp.route('/year/<path:academic_year>/semester/<path:term>/class/<path:label>/student/<int:student_id>')
@login_required
def archive_class_transcript(academic_year, term, label, student_id):
    from models import Student

    if not current_user.is_admin() or not _is_graduated_label(label):
        abort(404)
    student = Student.query.get_or_404(student_id)
    if student.class_name != label:
        abort(404)
    if not any(a.student_id == student.id for a in _archive_rows(academic_year, term, label)):
        abort(404)
    return render_template(
        'archive_transcript.html', label=label, student=student,
        academic_year=academic_year, term=term, term_label=_term_label(term),
        transcript=_calc_final_transcript(student.id, academic_year, term),
        now=utcnow(),
    )
