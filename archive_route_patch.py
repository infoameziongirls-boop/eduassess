# ─────────────────────────────────────────────────────────────────────────────
# ARCHIVE ROUTE  —  paste this into app.py, replacing the existing
# assessments_archived() function (search for  def assessments_archived)
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/assessments/archived')
@login_required
@admin_required          # archive view is admin-only
def assessments_archived():
    """
    Dedicated archive container.
    Admins can browse, search, filter, restore, or delete archived assessments.
    """
    from sqlalchemy import func

    page         = request.args.get('page',          1,  type=int)
    per_page     = app.config['ASSESSMENTS_PER_PAGE']
    search       = request.args.get('search',       '').strip()
    sel_subject  = request.args.get('subject',      '').strip()
    sel_class    = request.args.get('class_name',   '').strip()
    sel_term     = request.args.get('term',         '').strip()
    sel_year     = request.args.get('academic_year','').strip()
    group        = request.args.get('group',        'all').strip()

    # ── Base query: all archived assessments ──────────────────────────────────
    q = Assessment.query.filter_by(archived=True)

    # ── Optional group filter (by term+year key) ──────────────────────────────
    if group and group != 'all':
        # key format: "2024-2025__term1"
        parts = group.split('__')
        if len(parts) == 2:
            q = q.filter_by(academic_year=parts[0], term=parts[1])

    # ── Text / field filters ──────────────────────────────────────────────────
    if search:
        q = q.join(Student, Assessment.student_id == Student.id).filter(
            db.or_(
                Student.first_name.ilike(f'%{search}%'),
                Student.last_name.ilike(f'%{search}%'),
                Student.student_number.ilike(f'%{search}%'),
            )
        )
    if sel_subject:  q = q.filter_by(subject=sel_subject)
    if sel_class:    q = q.filter_by(class_name=sel_class)
    if sel_term:     q = q.filter_by(term=sel_term)
    if sel_year:     q = q.filter_by(academic_year=sel_year)

    pagination = (q.order_by(Assessment.date_recorded.desc())
                   .paginate(page=page, per_page=per_page, error_out=False))

    # Filter out orphaned records (missing students) to prevent template errors
    pagination.items = [a for a in pagination.items if a.student is not None]

    # ── Hero / KPI stats ──────────────────────────────────────────────────────
    total_archived    = Assessment.query.filter_by(archived=True).count()
    archived_students = (db.session.query(func.count(Assessment.student_id.distinct()))
                           .filter_by(archived=True).scalar() or 0)

    # Distinct (academic_year, term) pairs that have archived records
    archived_pairs = (db.session.query(Assessment.academic_year, Assessment.term)
                       .filter_by(archived=True)
                       .group_by(Assessment.academic_year, Assessment.term)
                       .order_by(Assessment.academic_year.desc(), Assessment.term)
                       .all())
    archived_terms = len(archived_pairs)

    last_record = (Assessment.query.filter_by(archived=True)
                    .order_by(Assessment.date_recorded.desc()).first())
    last_archive_date = (last_record.date_recorded.strftime('%d %b %Y')
                         if last_record else None)

    # ── Term summary cards (one card per distinct year+term) ─────────────────
    term_label_map = dict(app.config.get('TERMS', []))
    term_summary = []
    for year, term in archived_pairs:
        count = (Assessment.query
                   .filter_by(archived=True, academic_year=year, term=term)
                   .count())
        stu_count = (db.session.query(func.count(Assessment.student_id.distinct()))
                      .filter_by(archived=True, academic_year=year, term=term)
                      .scalar() or 0)
        term_summary.append({
            'key':           f'{year}__{term}',
            'academic_year': year or '—',
            'term':          term or '—',
            'term_label':    term_label_map.get(term, (term or '').replace('term', 'Term ')),
            'count':         count,
            'student_count': stu_count,
        })

    return render_template(
        'archive_view.html',
        assessments=pagination.items,
        pagination=pagination,

        # Filter form state
        search=search,
        selected_subject=sel_subject,
        selected_class=sel_class,
        selected_term=sel_term,
        selected_year=sel_year,
        group=group,

        # Config lists for filter dropdowns
        learning_areas=app.config['LEARNING_AREAS'],
        class_levels=app.config['CLASS_LEVELS'],
        terms=app.config.get('TERMS', []),

        # Hero KPIs
        total_archived=total_archived,
        archived_students=archived_students,
        archived_terms=archived_terms,
        last_archive_date=last_archive_date,

        # Tab / summary data
        term_summary=term_summary,
    )


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN SETTINGS — add this link inside your admin_settings.html template
# so admins can navigate directly to the archive from the settings page.
#
# Paste the snippet below inside your admin_settings template, near the
# "archive_term" form / button section:
# ─────────────────────────────────────────────────────────────────────────────
"""
{# In admin_settings.html — add this button wherever the archive section is #}
<a href="{{ url_for('assessments_archived') }}"
   class="btn btn-outline-secondary btn-sm mt-2">
  🗄 View Archive Container
</a>
"""

# ─────────────────────────────────────────────────────────────────────────────
# PROMOTION ROUTE CONTEXT — your promotion_routes.py promote_class_view()
# should pass the variables below.  Add them to the render_template() call.
# ─────────────────────────────────────────────────────────────────────────────
"""
VARIABLES REQUIRED BY promote_class.html
─────────────────────────────────────────
total_students        → Student.query.count()
class_levels          → app.config['CLASS_LEVELS']
class_student_counts  → {cls_key: count, ...}  e.g. {'Form 1': 42, ...}
class_assessment_counts → {cls_key: count, ...}
class_completion      → {cls_key: percent_int, ...}
current_academic_year → settings.current_academic_year
current_term          → settings.current_term
next_academic_year    → computed e.g. '2025-2026'
terms                 → app.config['TERMS']
promotion_history     → list of objects/dicts with:
                         .date, .classes (list), .academic_year,
                         .student_count, .promoted_by
"""

# ─────────────────────────────────────────────────────────────────────────────
# ORDER OF MERIT ROUTE — your promotion_routes.py order_of_merit() should
# pass the variables below.
# ─────────────────────────────────────────────────────────────────────────────
"""
VARIABLES REQUIRED BY order_of_merit.html
──────────────────────────────────────────
view                  → request.args.get('view', 'all')
merit_list            → list of objects/dicts with:
                         .student (Student model instance)
                         .final_score (float, 0–100)
                         .grade (str, e.g. 'A1')
                         .gpa (float or str)
                         .top_subjects (list of subject name strings)
                         .trend ('up' | 'down' | 'same')
                         .rank_change (int, absolute positions moved)
class_levels          → app.config['CLASS_LEVELS']
learning_areas        → app.config['LEARNING_AREAS']
terms                 → app.config['TERMS']
selected_class        → request.args.get('class_name', '')
selected_subject      → request.args.get('subject', '')
selected_term         → request.args.get('term', '')
selected_class_label  → human label for the selected class
current_academic_year → settings.current_academic_year
"""
