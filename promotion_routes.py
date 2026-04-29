"""
promotion_routes.py  –  Class Promotion & Order of Merit
═════════════════════════════════════════════════════════
INSTALLATION (3 steps in app.py):

  1.  Near the top with other imports:
          from promotion_routes import promotion_bp

  2.  After  app.register_blueprint(api_bp) :
          app.register_blueprint(promotion_bp)

  3.  Update inject_config() to expose `now`:
          @app.context_processor
          def inject_config():
              return {
                  'CATEGORY_LABELS':    CATEGORY_LABELS,
                  'ASSESSMENT_WEIGHTS': app.config['ASSESSMENT_WEIGHTS'],
                  'LEARNING_AREAS':     app.config['LEARNING_AREAS'],
                  'CLASS_LEVELS':       app.config['CLASS_LEVELS'],
                  'now':                datetime.utcnow(),
              }

  4.  Copy admin_promote_class.html and order_of_merit.html
      into your templates/ folder.

  5.  Paste dashboard_promotion_snippet.html content into dashboard.html.
"""

from __future__ import annotations
from datetime import datetime
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, abort, current_app)
from flask_login import login_required, current_user

promotion_bp = Blueprint('promotion', __name__)

CLASS_SEQUENCE = ['Form 1', 'Form 2', 'Form 3']


# ── helpers ──────────────────────────────────────────────────────────────────

def _next_class(current_class: str):
    try:
        idx = CLASS_SEQUENCE.index(current_class)
        if idx + 1 < len(CLASS_SEQUENCE):
            return CLASS_SEQUENCE[idx + 1]
    except ValueError:
        pass
    return None


def _graduation_label(academic_year: str) -> str:
    if academic_year and '-' in academic_year:
        return f"Graduated {academic_year.split('-')[-1].strip()}"
    return f"Graduated {datetime.utcnow().year}"


def _gpa_float(gpa_val) -> float:
    try:
        return float(gpa_val)
    except (TypeError, ValueError):
        return 0.0


def _calc_gpa(student_id: int, subject: str | None = None) -> dict:
    from models import Assessment
    try:
        from template_updater import (calculate_scores_from_template,
                                      scores_from_assessments)
    except ImportError:
        return {'final_score': 0, 'gpa': 'N/A', 'grade': 'N/A', 'percentage': 0}

    qs = Assessment.query.filter_by(student_id=student_id, archived=False).all()
    if subject:
        qs = [a for a in qs if a.subject == subject]
    if not qs:
        return {'final_score': 0, 'gpa': 'N/A', 'grade': 'N/A', 'percentage': 0}
    raw = scores_from_assessments(qs)
    if not raw:
        return {'final_score': 0, 'gpa': 'N/A', 'grade': 'N/A', 'percentage': 0}
    return calculate_scores_from_template(raw)


def _build_merit_rows(view_type, class_filter, subject_filter, form_filter, top_n):
    from models import Student, Assessment
    from db import db

    if view_type == 'class':
        students = Student.query.filter_by(class_name=class_filter).all()
        subj = None
    elif view_type == 'subject' and subject_filter:
        sids = [r[0] for r in
                db.session.query(Assessment.student_id)
                .filter(Assessment.subject == subject_filter,
                        Assessment.archived == False)
                .distinct().all()]
        students = Student.query.filter(Student.id.in_(sids)).all()
        subj = subject_filter
    elif view_type == 'form':
        students = Student.query.filter_by(class_name=form_filter).all()
        subj = None
    else:
        return []

    rows = []
    for s in students:
        res = _calc_gpa(s.id, subject=subj)
        rows.append({
            'student':     s,
            'final_score': res.get('final_score', 0),
            'percentage':  res.get('percentage', 0),
            'gpa':         res.get('gpa', 'N/A'),
            'grade':       res.get('grade', 'N/A'),
            'gpa_float':   _gpa_float(res.get('gpa')),
        })

    rows.sort(key=lambda x: (x['gpa_float'], x['percentage']), reverse=True)
    rows = rows[:top_n]

    pos = 1
    for i, row in enumerate(rows):
        if i > 0 and (row['gpa_float'] == rows[i - 1]['gpa_float'] and
                      abs(row['percentage'] - rows[i - 1]['percentage']) < 0.01):
            row['position'] = rows[i - 1]['position']
        else:
            row['position'] = pos
        pos += 1

    return rows


def _all_subjects():
    from models import Assessment
    from db import db
    try:
        results = (db.session.query(Assessment.subject)
                   .filter(Assessment.archived == False,
                           Assessment.subject.isnot(None))
                   .distinct().all())
        return sorted({r[0] for r in results if r[0]})
    except Exception:
        return []


# ── Promotion views ───────────────────────────────────────────────────────────

@promotion_bp.route('/admin/promote-class')
@login_required
def promote_class_view():
    from models import Student, Setting, Assessment, ActivityLog
    from db import db
    from sqlalchemy import func
    
    if not current_user.is_admin():
        abort(403)

    settings   = Setting.query.first()
    current_ay = settings.current_academic_year if settings else '2024-2025'
    current_term = settings.current_term if settings else 'term1'

    # Parse current AY to compute next AY
    try:
        parts = current_ay.split('-')
        if len(parts) == 2:
            next_year = int(parts[1]) + 1
            next_academic_year = f'{next_year}-{next_year + 1}'
        else:
            next_academic_year = current_ay
    except (ValueError, IndexError):
        next_academic_year = current_ay

    # Compute class-level statistics
    total_students = Student.query.count()
    class_levels = ['Form 1', 'Form 2', 'Form 3']
    
    class_student_counts = {}
    class_assessment_counts = {}
    class_completion = {}
    
    for cls in class_levels:
        # Student count per class
        student_count = Student.query.filter_by(class_name=cls).count()
        class_student_counts[cls] = student_count
        
        # Assessment count per class
        assessment_count = (Assessment.query
                           .filter_by(class_name=cls, archived=False)
                           .count())
        class_assessment_counts[cls] = assessment_count
        
        # Completion percentage (students with at least one assessment)
        students_with_assessments = (db.session
            .query(func.count(Assessment.student_id.distinct()))
            .filter_by(class_name=cls, archived=False)
            .scalar() or 0)
        completion_pct = int((students_with_assessments / student_count * 100) if student_count > 0 else 0)
        class_completion[cls] = completion_pct

    # Promotion history from ActivityLog
    promotion_history = []
    activity_records = (ActivityLog.query
        .filter(ActivityLog.action == 'class_promotion')
        .order_by(ActivityLog.timestamp.desc())
        .limit(10)
        .all())
    
    for record in activity_records:
        try:
            # Parse details: 'Promoted X students: Form 1 → Form 2 (AY 2024-2025)'
            details = record.details or ''
            promotion_history.append({
                'date': record.timestamp.strftime('%d %b %Y %H:%M') if record.timestamp else 'N/A',
                'details': details,
                'promoted_by': record.user.first_name if record.user else 'Unknown',
            })
        except Exception:
            pass

    return render_template(
        'promote_class.html',
        total_students=total_students,
        class_levels=class_levels,
        class_student_counts=class_student_counts,
        class_assessment_counts=class_assessment_counts,
        class_completion=class_completion,
        current_academic_year=current_ay,
        current_term=current_term,
        next_academic_year=next_academic_year,
        terms=current_app.config.get('TERMS', []),
        promotion_history=promotion_history,
        now=datetime.utcnow(),
    )


@promotion_bp.route('/admin/promote-class/execute', methods=['POST'])
@login_required
def execute_promotion():
    from models import Student, Setting, ActivityLog
    from db import db
    if not current_user.is_admin():
        abort(403)

    source_class  = request.form.get('source_class', '').strip()
    confirm       = request.form.get('confirm', '')
    academic_year = request.form.get('academic_year', '').strip()

    if confirm != 'CONFIRM':
        flash('You must type CONFIRM to proceed.', 'danger')
        return redirect(url_for('promotion.promote_class_view'))

    if source_class not in CLASS_SEQUENCE:
        flash('Invalid source class.', 'danger')
        return redirect(url_for('promotion.promote_class_view'))

    is_graduating = (source_class == CLASS_SEQUENCE[-1])
    target_class  = (_graduation_label(academic_year)
                     if is_graduating else _next_class(source_class))

    students = Student.query.filter_by(class_name=source_class).all()
    if not students:
        flash(f'No students found in {source_class}.', 'warning')
        return redirect(url_for('promotion.promote_class_view'))

    count = 0
    for s in students:
        s.class_name = target_class
        for a in s.assessments:
            if not a.archived:
                a.archived = True
        count += 1

    # Advance academic year in Settings
    settings = Setting.query.first()
    if settings and academic_year and '-' in academic_year:
        try:
            yr = int(academic_year.split('-')[1].strip())
            settings.current_academic_year = f'{yr}-{yr + 1}'
        except (ValueError, IndexError):
            pass

    db.session.commit()

    db.session.add(ActivityLog(
        user_id=current_user.id,
        action='class_promotion',
        details=f'Promoted {count} students: {source_class} → {target_class} (AY {academic_year})',
        ip_address=request.remote_addr,
    ))
    db.session.commit()

    flash(f'✅ Promoted {count} student(s) from {source_class} to {target_class}.', 'success')
    return redirect(url_for('promotion.promote_class_view'))


# ── Order of Merit views ──────────────────────────────────────────────────────

@promotion_bp.route('/admin/order-of-merit')
@login_required
def order_of_merit():
    from models import Setting, Student, Assessment
    from db import db
    from sqlalchemy import func
    
    if not current_user.is_admin():
        abort(403)

    view      = request.args.get('view', 'all')
    sel_class = request.args.get('class_name', CLASS_SEQUENCE[0] if CLASS_SEQUENCE else '')
    sel_subject = request.args.get('subject', '')
    sel_term  = request.args.get('term', '')

    settings   = Setting.query.first()
    current_ay = settings.current_academic_year if settings else ''
    current_term = settings.current_term if settings else ''

    # Get class label for display
    selected_class_label = sel_class or 'All Classes'

    # Build merit list with required context
    merit_list = _build_merit_rows(view, sel_class, sel_subject, sel_class, 20)
    
    # Ensure merit_list items have all required fields
    for item in merit_list:
        if 'top_subjects' not in item:
            item['top_subjects'] = []
        if 'trend' not in item:
            item['trend'] = 'same'
        if 'rank_change' not in item:
            item['rank_change'] = 0

    return render_template(
        'order_of_merit.html',
        view=view,
        merit_list=merit_list,
        class_levels=current_app.config.get('CLASS_LEVELS', []),
        learning_areas=current_app.config.get('LEARNING_AREAS', []),
        terms=current_app.config.get('TERMS', []),
        selected_class=sel_class,
        selected_subject=sel_subject,
        selected_term=sel_term,
        selected_class_label=selected_class_label,
        current_academic_year=current_ay,
        subjects=_all_subjects(),
        now=datetime.utcnow(),
    )


@promotion_bp.route('/admin/order-of-merit/print')
@login_required
def order_of_merit_print():
    from models import Setting
    
    if not current_user.is_admin():
        abort(403)

    view      = request.args.get('view', 'all')
    sel_class = request.args.get('class_name', CLASS_SEQUENCE[0] if CLASS_SEQUENCE else '')
    sel_subject = request.args.get('subject', '')
    sel_term  = request.args.get('term', '')

    settings   = Setting.query.first()
    current_ay = settings.current_academic_year if settings else ''
    current_term = settings.current_term if settings else ''

    # Get class label for display
    selected_class_label = sel_class or 'All Classes'

    # Build merit list with required context
    merit_list = _build_merit_rows(view, sel_class, sel_subject, sel_class, 20)
    
    # Ensure merit_list items have all required fields
    for item in merit_list:
        if 'top_subjects' not in item:
            item['top_subjects'] = []
        if 'trend' not in item:
            item['trend'] = 'same'
        if 'rank_change' not in item:
            item['rank_change'] = 0

    return render_template(
        'order_of_merit.html',
        view=view,
        merit_list=merit_list,
        class_levels=current_app.config.get('CLASS_LEVELS', []),
        learning_areas=current_app.config.get('LEARNING_AREAS', []),
        terms=current_app.config.get('TERMS', []),
        selected_class=sel_class,
        selected_subject=sel_subject,
        selected_term=sel_term,
        selected_class_label=selected_class_label,
        current_academic_year=current_ay,
        subjects=_all_subjects(),
        now=datetime.utcnow(),
    )
