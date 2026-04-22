import os
import io
import csv
import random
import re
import time
import json
from functools import wraps
from werkzeug.utils import secure_filename
from datetime import datetime

import openpyxl
from openpyxl.styles import PatternFill, Border, Side, Alignment, Font
from openpyxl.utils import get_column_letter

from flask import (Flask, render_template, redirect, url_for, flash,
                   request, send_file, abort, jsonify, session)
from flask_login import (LoginManager, login_user, login_required,
                         logout_user, current_user)
from flask_bcrypt import Bcrypt
from flask_wtf import FlaskForm, CSRFProtect
from flask_wtf.file import FileField, FileAllowed
from flask_wtf.csrf import generate_csrf, CSRFError
from flask_session import Session
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy.exc import SQLAlchemyError
from wtforms import (StringField, PasswordField, FloatField, SelectField,
                     SelectMultipleField, TextAreaField, BooleanField)
from wtforms.validators import (InputRequired, Length, Optional,
                                NumberRange, ValidationError)

from db import db
from config import config

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------
CATEGORY_LABELS = {
    'ica1':      'Individual Assessment 1',
    'ica2':      'Individual Assessment 2',
    'icp1':      'Individual Class Project 1',
    'icp2':      'Individual Class Project 2',
    'gp1':       'Group Project/Research 1',
    'gp2':       'Group Project/Research 2',
    'practical': 'Practical Portfolio',
    'mid_term':  'Mid-Semester Exam',
    'end_term':  'End of Term Exam',
}

CATEGORY_MAX_SCORES = {
    'ica1': 50, 'ica2': 50,
    'icp1': 50, 'icp2': 50,
    'gp1':  50, 'gp2':  50,
    'practical': 100, 'mid_term': 100, 'end_term': 100,
}

ASSESSMENT_WEIGHTS = {
    'ica1': 0.05, 'ica2': 0.05,
    'icp1': 0.05, 'icp2': 0.05,
    'gp1':  0.05, 'gp2':  0.05,
    'practical': 0.10, 'mid_term': 0.10, 'end_term': 0.50,
}

ASSESSMENTS_PER_PAGE = 20


# ---------------------------------------------------------------------------
# File validation
# ---------------------------------------------------------------------------
def validate_excel_file(form, field):
    if not field.data:
        return
    allowed_mimes = [
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.ms-excel',
    ]
    if hasattr(field.data, 'content_type') and field.data.content_type not in allowed_mimes:
        raise ValidationError('Only Excel files (.xlsx, .xls) are allowed.')
    filename = field.data.filename.lower()
    if not (filename.endswith('.xlsx') or filename.endswith('.xls')):
        raise ValidationError('Invalid file extension. Only .xlsx and .xls are allowed.')
    try:
        field.data.seek(0)
        magic_bytes = field.data.read(8)
        field.data.seek(0)
        xlsx_sig = b'PK\x03\x04'
        xls_sig  = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
        if not (magic_bytes.startswith(xlsx_sig) or magic_bytes.startswith(xls_sig)):
            raise ValidationError('File content does not match Excel format.')
    except ValidationError:
        raise
    except Exception:
        raise ValidationError('Unable to validate file. Please try again.')


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder='public')

env = os.environ.get('FLASK_ENV', 'development')
app.config.from_object(config[env])

if env == 'production':
    config[env].validate_production_settings()

persistent_dir = os.environ.get(
    'PERSISTENT_DIR',
    os.path.join(os.path.dirname(__file__), 'instance'),
)
app.config['UPLOAD_FOLDER']      = os.path.join(persistent_dir, 'uploads')
app.config['TEMPLATE_FOLDER']    = os.path.join(persistent_dir, 'templates_excel')
app.config['SESSION_FILE_DIR']   = os.path.join(persistent_dir, 'flask_sessions')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

for d in [app.config['UPLOAD_FOLDER'],
          app.config['TEMPLATE_FOLDER'],
          app.config['SESSION_FILE_DIR']]:
    os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------
bcrypt       = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
csrf         = CSRFProtect(app)

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=['200 per day', '50 per hour'],
    storage_uri=os.environ.get('REDIS_URL', 'memory://'),
)

# Initialise DB
init_db(app, bcrypt)
with app.app_context():
    db.create_all()

# Session must come AFTER db is initialised
app.config['SESSION_SQLALCHEMY'] = db
Session(app)


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    app.logger.warning('CSRF error on %s: %s', request.path, e.description)
    flash('Your session token expired. Please try again.', 'warning')
    return redirect(request.referrer or url_for('login')), 302


@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf)


# ---------------------------------------------------------------------------
# Custom Jinja2 filters
# ---------------------------------------------------------------------------
@app.template_filter('strftime')
def format_datetime(value, fmt='%Y-%m-%d %H:%M'):
    """Format datetime using strftime"""
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    try:
        return value.strftime(fmt)
    except AttributeError:
        return str(value)


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------
def normalize_label(value):
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    value = value.replace('_', ' ').replace('-', ' ').lower()
    value = re.sub(r'\s+', ' ', value)
    value = re.sub(r'(\D)(\d)', r'\1 \2', value)
    value = re.sub(r'(\d)(\D)', r'\1 \2', value)
    return value.strip()


def canonical_class_key(raw_value):
    normalized = normalize_label(raw_value)
    if not normalized:
        return None
    form_map = {normalize_label(k): k for k, _ in app.config['CLASS_LEVELS']}
    form_map.update({normalize_label(l): k for k, l in app.config['CLASS_LEVELS']})
    numeric_map = {'1': 'Form 1', '2': 'Form 2', '3': 'Form 3'}
    if normalized in numeric_map:
        return numeric_map[normalized]
    return form_map.get(normalized)


def canonical_study_area_key(raw_value):
    normalized = normalize_label(raw_value)
    if not normalized:
        return None
    study_map = {normalize_label(k): k for k, _ in app.config['STUDY_AREAS']}
    study_map.update({normalize_label(l): k for k, l in app.config['STUDY_AREAS']})
    return study_map.get(normalized, normalized.replace(' ', '_') if normalized else None)


def canonical_subject_key(raw_value):
    normalized = normalize_label(raw_value)
    if not normalized:
        return None
    subject_map = {normalize_label(k): k for k, _ in app.config['LEARNING_AREAS']}
    subject_map.update({normalize_label(l): k for k, l in app.config['LEARNING_AREAS']})
    return subject_map.get(normalized, normalized.replace(' ', '_') if normalized else None)


def normalize_student_records():
    students = Student.query.all()
    changed = False
    for s in students:
        cc = canonical_class_key(s.class_name)
        ca = canonical_study_area_key(s.study_area)
        if cc and s.class_name != cc:
            s.class_name = cc
            changed = True
        if ca and s.study_area != ca:
            s.study_area = ca
            changed = True
    if changed:
        db.session.commit()


@app.context_processor
def utility_processor():
    def safe_url_for(endpoint, **values):
        try:
            return url_for(endpoint, **values)
        except Exception:
            return None
    return dict(safe_url_for=safe_url_for)

# ---------------------------------------------------------------------------
# Import models and helpers AFTER app is created
# ---------------------------------------------------------------------------
# 1. Extensions (bcrypt, login_manager, csrf, limiter)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
csrf = CSRFProtect(app)
limiter = Limiter(...)

# 2. Import models BEFORE calling init_db
from models import (User, Student, Assessment, Setting, ActivityLog, Question,
                    QuestionAttempt, Quiz, QuizAttempt, SystemConfig, Parent,
                    Message, init_db)
from excel_utils import (ExcelTemplateHandler, ExcelBulkImporter,
                         StudentBulkImporter, TeacherBulkImporter,
                         QuestionBulkImporter, create_default_template,
                         create_student_import_template,
                         create_teacher_import_template,
                         create_question_import_template)
from analytics import get_class_performance_summary, get_grade_distribution
from api_v1 import api_bp
from template_updater import AssessmentTemplateUpdater

# 3. Now initialise DB
init_db(app, bcrypt)
with app.app_context():
    db.create_all()

# 4. Session AFTER db is ready
app.config['SESSION_SQLALCHEMY'] = db
Session(app)

def load_persistent_config():
    with app.app_context():
        for key in ('CLASS_LEVELS', 'STUDY_AREAS', 'STUDY_AREA_SUBJECTS'):
            db_val = SystemConfig.get_config(key)
            if db_val:
                app.config[key] = db_val
            else:
                SystemConfig.set_config(key, app.config[key])


try:
    load_persistent_config()
    with app.app_context():
        normalize_student_records()
except Exception as exc:
    print(f'Warning: Could not load persistent config: {exc}')

app.config['CATEGORY_LABELS']     = CATEGORY_LABELS
app.config['ASSESSMENTS_PER_PAGE'] = ASSESSMENTS_PER_PAGE
app.config['CATEGORY_MAX_SCORES'] = CATEGORY_MAX_SCORES
app.config['ASSESSMENT_WEIGHTS']  = ASSESSMENT_WEIGHTS
app.register_blueprint(api_bp)
migrate = Migrate(app, db)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------
def log_activity(user, action, details=None):
    if not user or not user.is_authenticated:
        return
    try:
        log_entry = ActivityLog(
            user_id=user.id, action=action, details=details,
            ip_address=request.remote_addr if request else None,
        )
        db.session.add(log_entry)
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        app.logger.error('Failed to log activity: %s', exc)


def get_incomplete_assessments():
    required = ['ica1', 'ica2', 'icp1', 'icp2', 'gp1', 'gp2',
                'practical', 'mid_term', 'end_term']
    rows = db.session.query(
        Assessment.student_id, Assessment.subject, Assessment.category
    ).filter(Assessment.archived == False).all()

    ssc = {}
    for sid, subj, cat in rows:
        if not sid or not subj or not cat:
            continue
        ssc.setdefault((sid, subj), set()).add(cat)

    if not ssc:
        return []

    student_ids = {sid for sid, _ in ssc}
    student_map = {s.id: s for s in
                   Student.query.filter(Student.id.in_(student_ids)).all()}
    result = []
    for (sid, subj), cats in ssc.items():
        missing = [c for c in required if c not in cats]
        if not missing:
            continue
        student = student_map.get(sid)
        if not student:
            continue
        result.append({'student': student, 'subject': subj,
                       'missing_categories': missing,
                       'existing_categories': sorted(cats)})
    return result


def calculate_gpa_and_grade(percent):
    if percent is None:
        return {'gpa': 'N/A', 'grade': 'N/A'}
    if percent >= 80:   return {'gpa': 4.0, 'grade': 'A1'}
    if percent >= 70:   return {'gpa': 3.5, 'grade': 'B2'}
    if percent >= 65:   return {'gpa': 3.0, 'grade': 'B3'}
    if percent >= 60:   return {'gpa': 2.5, 'grade': 'C4'}
    if percent >= 55:   return {'gpa': 2.0, 'grade': 'C5'}
    if percent >= 50:   return {'gpa': 1.5, 'grade': 'C6'}
    if percent >= 45:   return {'gpa': 1.0, 'grade': 'D7'}
    if percent >= 40:   return {'gpa': 0.5, 'grade': 'E8'}
    return {'gpa': 0.0, 'grade': 'F9'}


def generate_unique_reference_number():
    for _ in range(100):
        ref = f'STU{random.randint(100000, 999999)}'
        if not Student.query.filter_by(reference_number=ref).first():
            return ref
    return f'STU{int(time.time()) % 1000000:06d}'


def calculate_short_answer_score(answer, question):
    if not answer or not question:
        return 0.0
    norm_ans = answer.strip().lower()
    norm_exp = (question.correct_answer or '').strip().lower()
    if norm_ans == norm_exp:
        return float(question.marks or 0.0)
    keywords = question.keywords or []
    if isinstance(keywords, str):
        keywords = [keywords]
    keywords = [kw.strip().lower() for kw in keywords if kw]
    if keywords:
        matches = sum(1 for kw in keywords if kw in norm_ans)
        return round(float(question.marks or 0.0) * min(matches / len(keywords), 1.0), 1)
    if norm_exp and norm_exp in norm_ans:
        return round(float(question.marks or 0.0) * 0.75, 1)
    return 0.0


def get_student_groups(cur_user, app_config):
    by_class = {}
    by_area  = {}
    q = Student.query
    if hasattr(cur_user, 'is_teacher') and cur_user.is_teacher():
        areas = cur_user.get_assigned_study_areas(app_config)
        if areas:
            q = q.filter(Student.study_area.in_(areas))
    for s in q.all():
        cls  = s.get_class_display() or 'Unspecified'
        by_class.setdefault(cls, []).append(s)
        area = s.get_study_area_display() or 'Unspecified'
        by_area[area] = by_area.get(area, 0) + 1
    return by_class, by_area


def _get_comment(gpa):
    try:
        gpa = float(gpa)
    except (TypeError, ValueError):
        return None
    table = {4.0: 'Excellent', 3.5: 'Very Good', 3.0: 'Good',
             2.5: 'Average', 2.0: 'Below Average', 1.5: 'Credit',
             1.0: 'Satisfactory', 0.5: 'Pass'}
    return table.get(gpa, 'Fail')


# ---------------------------------------------------------------------------
# Forms
# ---------------------------------------------------------------------------
class StudentLoginForm(FlaskForm):
    identifier = StringField(
        'Student Number or Reference Number',
        validators=[InputRequired(), Length(min=1, max=50)],
        render_kw={'placeholder': 'Enter your Student Number or Reference Number'},
    )


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[InputRequired(), Length(min=3, max=80)])
    password = PasswordField('Password', validators=[InputRequired(), Length(min=4)])


class UserForm(FlaskForm):
    username = StringField('Username', validators=[InputRequired(), Length(min=3)])
    password = PasswordField('Password', validators=[InputRequired(), Length(min=6)])
    role     = SelectField('Role', choices=app.config['USER_ROLES'])
    subject  = SelectField('Subject (for teachers)',
                           choices=[('', '-- Not Applicable --')] + app.config['LEARNING_AREAS'],
                           validators=[Optional()])
    classes  = SelectMultipleField('Classes (for teachers)',
                                   choices=app.config['CLASS_LEVELS'],
                                   validators=[Optional()])


class EditUserForm(FlaskForm):
    role    = SelectField('Role', choices=app.config['USER_ROLES'])
    subject = SelectField('Subject (for teachers)',
                          choices=[('', '-- Not Applicable --')] + app.config['LEARNING_AREAS'],
                          validators=[Optional()])
    classes = SelectMultipleField('Classes (for teachers)',
                                  choices=app.config['CLASS_LEVELS'],
                                  validators=[Optional()])


class PasswordResetForm(FlaskForm):
    password = PasswordField('New Password', validators=[InputRequired(), Length(min=6)])


class StudentForm(FlaskForm):
    student_number = StringField('Student Number',
                                 validators=[InputRequired(), Length(min=1, max=50)])
    first_name  = StringField('First name',  validators=[InputRequired()])
    last_name   = StringField('Last name',   validators=[InputRequired()])
    middle_name = StringField('Middle name', validators=[Optional()])
    class_name  = SelectField('Class',
                              choices=[('', '-- Select Class --')] + app.config['CLASS_LEVELS'],
                              validators=[Optional()])
    study_area  = SelectField('Study/Learning Area',
                              choices=[('', '-- Select Study Area --')] + app.config['STUDY_AREAS'],
                              validators=[Optional()])


class AssessmentForm(FlaskForm):
    student_number   = StringField('Student Number',   validators=[Optional()])
    student_name     = StringField('Student Name',     validators=[InputRequired()])
    reference_number = StringField('Reference Number', validators=[Optional()])
    category  = SelectField('Category',
                            choices=app.config['ASSESSMENT_CATEGORIES'],
                            validators=[InputRequired()])
    subject   = SelectField('Subject',
                            choices=[('', '-- Select Subject --')] + app.config['LEARNING_AREAS'],
                            validators=[InputRequired()])
    class_name = SelectField('Class',
                             choices=[('', '-- Select Class --')] + app.config['CLASS_LEVELS'],
                             validators=[Optional()])
    score     = FloatField('Score', validators=[InputRequired(), NumberRange(min=0)])
    max_score = SelectField('Max Score', choices=[(50, '50'), (100, '100')],
                            coerce=int, validators=[InputRequired()], default=100)
    term          = SelectField('Term', choices=app.config['TERMS'],
                                validators=[InputRequired()])
    academic_year = StringField('Academic Year', validators=[Optional()])
    session       = StringField('Session',       validators=[Optional()])
    assessor      = StringField('Assessor',      validators=[Optional()])
    comments      = TextAreaField('Comments',    validators=[Optional()])


class TeacherAssignmentForm(FlaskForm):
    subject = SelectField('Subject',
                          choices=[('', '-- Select Subject --')] + app.config['LEARNING_AREAS'],
                          validators=[InputRequired()])
    classes = SelectMultipleField('Classes', choices=app.config['CLASS_LEVELS'],
                                  validators=[Optional()])


class AssessmentFilterForm(FlaskForm):
    subject    = SelectField('Subject',
                             choices=[('', '-- All Subjects --')] + app.config['LEARNING_AREAS'],
                             validators=[Optional()])
    class_name = SelectField('Class',
                             choices=[('', '-- All Classes --')] + app.config['CLASS_LEVELS'],
                             validators=[Optional()])
    category   = SelectField('Category',
                             choices=[('', '-- All Categories --')] + app.config['ASSESSMENT_CATEGORIES'],
                             validators=[Optional()])


class BulkImportForm(FlaskForm):
    excel_file = FileField('Excel File', validators=[
        InputRequired(), FileAllowed(['xlsx', 'xls'], 'Excel files only!'),
        validate_excel_file,
    ])


class StudentBulkImportForm(FlaskForm):
    excel_file = FileField('Excel File', validators=[
        InputRequired(), FileAllowed(['xlsx', 'xls'], 'Excel files only!'),
        validate_excel_file,
    ])


class UserBulkImportForm(FlaskForm):
    excel_file = FileField('Excel File', validators=[
        InputRequired(), FileAllowed(['xlsx', 'xls'], 'Excel files only!'),
        validate_excel_file,
    ])


class QuestionBulkImportForm(FlaskForm):
    excel_file = FileField('Excel File', validators=[
        InputRequired(), FileAllowed(['xlsx', 'xls'], 'Excel files only!'),
        validate_excel_file,
    ])


class SettingsForm(FlaskForm):
    current_term         = SelectField('Current Term', choices=app.config['TERMS'],
                                       validators=[InputRequired()])
    current_academic_year = StringField('Current Academic Year',
                                        validators=[InputRequired()])
    current_session      = StringField('Current Session', validators=[InputRequired()])
    assessment_active    = BooleanField('Assessment Entry Active', default=True)


class QuestionForm(FlaskForm):
    question_text = TextAreaField('Question Text',
                                  validators=[InputRequired(), Length(min=10, max=1000)])
    question_type = SelectField('Question Type', choices=[
        ('mcq',          'Multiple Choice Question'),
        ('true_false',   'True/False'),
        ('short_answer', 'Short Answer'),
    ], validators=[InputRequired()])
    options        = TextAreaField('Options (MCQ only)', validators=[Optional()])
    correct_answer = StringField('Correct Answer', validators=[InputRequired()])
    marks          = FloatField('Marks',
                                validators=[InputRequired(), NumberRange(min=0.1, max=100)],
                                default=1.0)
    keywords    = TextAreaField('Keywords (Short Answer)', validators=[Optional()])
    difficulty  = SelectField('Difficulty', choices=[
        ('easy', 'Easy'), ('medium', 'Medium'), ('hard', 'Hard'),
    ], validators=[InputRequired()])
    explanation = TextAreaField('Explanation (Optional)',
                                validators=[Optional(), Length(max=500)])


class QuizForm(FlaskForm):
    title       = StringField('Quiz Title',
                              validators=[InputRequired(), Length(min=3, max=200)])
    subject     = SelectField('Subject', validators=[InputRequired()])
    description = TextAreaField('Description', validators=[Optional(), Length(max=500)])
    questions   = SelectMultipleField('Questions', validators=[InputRequired()])
    time_limit  = FloatField('Time Limit (minutes)',
                             validators=[Optional(), NumberRange(min=1, max=180)])
    is_active   = BooleanField('Active', default=True)


# ---------------------------------------------------------------------------
# Login manager & decorators
# ---------------------------------------------------------------------------
@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except Exception:
        return None


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if not current_user.is_admin():
            abort(403)
        return f(*args, **kwargs)
    return wrapped


def teacher_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_teacher():
            abort(403)
        return f(*args, **kwargs)
    return wrapped


def student_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_student():
            abort(403)
        return f(*args, **kwargs)
    return wrapped


def parent_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'parent':
            abort(403)
        return f(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# Context processors
# ---------------------------------------------------------------------------
@app.context_processor
def inject_config():
    return {
        'CATEGORY_LABELS':    CATEGORY_LABELS,
        'ASSESSMENT_WEIGHTS': app.config['ASSESSMENT_WEIGHTS'],
        'LEARNING_AREAS':     app.config['LEARNING_AREAS'],
        'CLASS_LEVELS':       app.config['CLASS_LEVELS'],
    }


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(403)
def forbidden(e):
    return render_template('403.html'), 403


@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_error(e):
    db.session.rollback()
    return render_template('500.html'), 500




def cleanup_orphaned_assessments():
    """Remove assessments with missing students (orphaned records)"""
    from models import Assessment, Student, db
    try:
        orphaned = db.session.query(Assessment).filter(
            ~Assessment.student_id.in_(db.session.query(Student.id))
        ).delete(synchronize_session=False)
        if orphaned > 0:
            db.session.commit()
            print(f"Cleaned {orphaned} orphaned assessments")
        return orphaned
    except Exception as e:
        print(f"Error cleaning assessments: {e}")
        db.session.rollback()
        return 0

@app.route('/health')
def health_check():
    try:
        db.session.execute(db.text('SELECT 1'))
        db_status = 'healthy'
    except Exception as exc:
        db_status = f'unhealthy: {exc}'
    return jsonify({
        'status': 'ok' if db_status == 'healthy' else 'error',
        'database': db_status,
        'timestamp': datetime.utcnow().isoformat(),
    })


# ---------------------------------------------------------------------------
# Authentication routes
# ---------------------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data.strip()).first()
        if user and user.check_password(form.password.data, bcrypt):
            login_user(user)
            log_activity(user, 'login', f'User {user.username} logged in')
            flash('Logged in successfully', 'success')
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template('login.html', form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully', 'info')
    return redirect(url_for('login'))


@app.route('/student/login', methods=['GET', 'POST'])
@limiter.limit('20 per minute')
def student_login():
    if current_user.is_authenticated:
        if hasattr(current_user, 'is_student') and current_user.is_student():
            return redirect(url_for('student_dashboard'))
        return redirect(url_for('dashboard'))

    form = StudentLoginForm()
    if form.validate_on_submit():
        identifier = (form.identifier.data or '').strip()
        student = Student.query.filter(
            db.or_(
                db.func.lower(db.func.trim(Student.student_number)) == identifier.lower(),
                db.func.lower(db.func.trim(Student.reference_number)) == identifier.lower(),
            )
        ).first()

        if not student:
            flash('No student record found for that identifier.', 'danger')
            return render_template('student_login.html', form=form)

        snum = (student.student_number or '').strip()
        if not snum:
            flash('Incomplete student record. Contact the administrator.', 'danger')
            return render_template('student_login.html', form=form)

        try:
            user = User.query.filter_by(username=snum).first()
            if not user:
                pw_hash = bcrypt.generate_password_hash(snum).decode('utf-8')
                user = User(username=snum, password_hash=pw_hash, role='student')
                db.session.add(user)
                db.session.commit()
            elif user.role != 'student':
                flash('This identifier belongs to a non-student account.', 'danger')
                return render_template('student_login.html', form=form)
            login_user(user)
            log_activity(user, 'student_login',
                         f'Student {student.full_name()} ({snum}) logged in')
            flash(f'Welcome, {student.first_name}.', 'success')
            return redirect(url_for('student_dashboard'))
        except Exception as exc:
            db.session.rollback()
            app.logger.error('Student login error for %r: %s', identifier, exc)
            flash('A system error occurred. Please try again.', 'danger')

    return render_template('student_login.html', form=form)


@app.route('/student/logout')
@login_required
def student_logout():
    logout_user()
    flash('Logged out successfully', 'info')
    return redirect(url_for('student_login'))


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Dashboard routes
# ---------------------------------------------------------------------------
@app.route('/')
@login_required
def dashboard():
    if hasattr(current_user, 'is_student') and current_user.is_student():
        return redirect(url_for('student_dashboard'))

    student_count    = Student.query.count()
    assessment_count = Assessment.query.filter_by(archived=False).count()
    users_count      = User.query.count()
    incomplete_list  = get_incomplete_assessments()

    if hasattr(current_user, 'is_teacher') and current_user.is_teacher():
        assigned = set(current_user.get_assigned_study_areas(app.config))
        if assigned:
            incomplete_list = [i for i in incomplete_list if i['subject'] in assigned]
        recent = Assessment.query.filter_by(teacher_id=current_user.id, archived=False) \
                                 .order_by(Assessment.date_recorded.desc()).limit(8).all()
    else:
        recent = Assessment.query.filter_by(archived=False) \
                                 .order_by(Assessment.date_recorded.desc()).limit(8).all()
    
    # Filter out assessments with missing students to avoid template errors
    recent = [a for a in recent if a.student is not None]

    students_by_class, students_by_area = get_student_groups(current_user, app.config)

    return render_template(
        'dashboard.html',
        student_count=student_count,
        assessment_count=assessment_count,
        users_count=users_count,
        affected_students_count=len(incomplete_list),
        incomplete_students=incomplete_list,
        recent=recent,
        teacher_student_summaries=None,
        grouped_students=None,
        students_by_class=students_by_class,
        students_by_area=students_by_area,
    )


@app.route('/dashboard')
@login_required
def dashboard_redirect():
    return redirect(url_for('dashboard'))


@app.route('/student/dashboard')
@login_required
@student_required
def student_dashboard():
    student = Student.query.filter(
        db.func.trim(Student.student_number) == (current_user.username or '').strip()
    ).first()
    if not student:
        logout_user()
        flash('Student record not found. Contact the administrator.', 'danger')
        return redirect(url_for('student_login'))

    subject_f  = request.args.get('subject', '')
    class_f    = request.args.get('class', '')
    category_f = request.args.get('category', '')

    q = Assessment.query.filter_by(student_id=student.id, archived=False)
    if subject_f:  q = q.filter_by(subject=subject_f)
    if class_f:    q = q.filter_by(class_name=class_f)
    if category_f: q = q.filter_by(category=category_f)
    assessments = q.order_by(Assessment.date_recorded.desc()).all()

    subjects   = sorted({a.subject    for a in student.assessments if a.subject})
    classes    = sorted({a.class_name for a in student.assessments if a.class_name})
    categories = sorted({a.category   for a in student.assessments if a.category})

    quiz_attempts = QuizAttempt.query.filter_by(student_id=student.id) \
                                     .order_by(QuizAttempt.completed_at.desc()).all()
    quiz_details  = {}
    for att in quiz_attempts:
        q_obj = Quiz.query.get(att.quiz_id)
        if q_obj:
            quiz_details[att.id] = q_obj

    # Build per-teacher / per-subject results
    src = student.assessments
    if subject_f:
        src = [a for a in src if a.subject == subject_f]
    teacher_subjects = {}
    for a in src:
        if a.archived:
            continue
        teacher_subjects.setdefault(a.teacher_id, {}).setdefault(a.subject, []).append(a)

    teacher_results = {}
    for tid, subj_data in teacher_subjects.items():
        teacher = User.query.get(tid)
        tname = teacher.username if teacher else f'Teacher {tid}'
        teacher_results[tname] = {}
        for sname, alist in subj_data.items():
            fp = student.calculate_final_grade(subject=sname, teacher_id=tid)
            gr = calculate_gpa_and_grade(fp)
            teacher_results[tname][sname] = {
                'final_percent': fp, 'gpa': gr['gpa'],
                'grade': gr['grade'], 'assessments': alist,
            }

    summary      = student.get_assessment_summary()
    final_pct    = student.calculate_final_grade()
    gpa_grade    = student.get_gpa_and_grade()

    if assessments:
        total_max = sum(a.max_score for a in assessments if a.max_score)
        total_got = sum(a.score     for a in assessments if a.score)
        avg_score = (total_got / total_max * 100) if total_max else 0.0
    else:
        avg_score = 0.0

    filt_res   = calculate_gpa_and_grade(avg_score)
    comment    = _get_comment(gpa_grade['gpa']) if gpa_grade['gpa'] != 'N/A' else None

    return render_template(
        'student_dashboard.html',
        student=student, assessments=assessments,
        teacher_results=teacher_results, summary=summary,
        final_percent=final_pct, gpa_grade=gpa_grade, comment=comment,
        subjects=subjects, classes=classes, categories=categories,
        selected_subject=subject_f, selected_class=class_f,
        selected_category=category_f,
        average_score=avg_score,
        filtered_gpa=filt_res['gpa'], filtered_grade=filt_res['grade'],
        quiz_attempts=quiz_attempts, quiz_details=quiz_details,
    )


@app.route('/parent/dashboard')
@login_required
@parent_required
def parent_dashboard():
    parent = Parent.query.filter_by(user_id=current_user.id).first_or_404()
    students_data = []
    for s in parent.students:
        students_data.append({
            'student': s,
            'final_grade': s.calculate_final_grade(),
            'recent_assessments': Assessment.query.filter_by(
                student_id=s.id, archived=False
            ).order_by(Assessment.date_recorded.desc()).limit(5).all(),
        })
    return render_template('parent_dashboard.html', students_data=students_data)


@app.route('/analytics')
@login_required
def analytics_dashboard():
    if current_user.is_student():
        abort(403)
    subject    = request.args.get('subject')
    class_name = request.args.get('class')
    tid        = current_user.id if current_user.is_teacher() else None
    return render_template(
        'analytics.html',
        performance_summary=get_class_performance_summary(
            class_name=class_name, subject=subject, teacher_id=tid),
        grade_distribution=get_grade_distribution(
            subject=subject, class_name=class_name, teacher_id=tid),
        selected_subject=subject,
        selected_class=class_name,
    )


# ---------------------------------------------------------------------------
# Student management routes
# ---------------------------------------------------------------------------
@app.route('/students')
@login_required
def students():
    search   = request.args.get('search', '').strip()
    group_by = request.args.get('group_by', 'none')
    sort_by  = request.args.get('sort_by',  'name')

    q = Student.query
    
    # Filter by teacher's class and subject if user is a teacher
    if hasattr(current_user, 'is_teacher') and current_user.is_teacher():
        areas = current_user.get_assigned_study_areas(app.config)
        teacher_classes = current_user.get_classes_list()
        
        filters = []
        if areas:
            filters.append(Student.study_area.in_(areas))
        if teacher_classes:
            filters.append(Student.class_name.in_(teacher_classes))
        
        if filters:
            q = q.filter(db.and_(*filters))
    
    if search:
        q = q.filter(
            db.or_(
                Student.student_number.ilike(f'%{search}%'),
                Student.first_name.ilike(f'%{search}%'),
                Student.last_name.ilike(f'%{search}%'),
                Student.reference_number.ilike(f'%{search}%'),
            )
        )
    all_students = q.order_by(Student.class_name, Student.last_name).all()

    if group_by == 'class':
        grouped = {}
        for s in all_students:
            grouped.setdefault(s.get_class_display() or 'Unspecified', []).append(s)
    elif group_by == 'study_area':
        grouped = {}
        for s in all_students:
            grouped.setdefault(s.get_study_area_display() or 'Unassigned', []).append(s)
    else:
        grouped = {'All Students': all_students}

    def sort_key(s):
        if sort_by == 'name':
            return (s.last_name or '', s.first_name or '')
        if sort_by == 'class':
            return s.get_class_display() or ''
        return s.get_study_area_display() or ''

    sorted_groups = {gn: sorted(gs, key=sort_key)
                     for gn, gs in grouped.items()}
    if group_by in ('class', 'study_area'):
        sorted_groups = dict(sorted(sorted_groups.items()))

    return render_template('students.html',
                           student_groups=sorted_groups,
                           current_group_by=group_by,
                           current_sort_by=sort_by)


@app.route('/students/new', methods=['GET', 'POST'])
@login_required
def student_new():
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)
    form = StudentForm()
    if form.validate_on_submit():
        if Student.query.filter_by(student_number=form.student_number.data.strip()).first():
            flash('Student number already exists', 'warning')
        else:
            ref = generate_unique_reference_number()
            s = Student(
                student_number=form.student_number.data.strip(),
                first_name=form.first_name.data.strip(),
                last_name=form.last_name.data.strip(),
                middle_name=form.middle_name.data.strip() if form.middle_name.data else None,
                class_name=form.class_name.data or None,
                study_area=form.study_area.data or None,
                reference_number=ref,
            )
            db.session.add(s)
            db.session.commit()
            log_activity(current_user, 'create_student',
                         f'Created {s.full_name()} ({s.student_number})')
            flash(f'Student added. Reference Number: {ref}', 'success')
            return redirect(url_for('students'))
    return render_template('student_form.html', form=form, student=None)


@app.route('/students/<int:student_id>/edit', methods=['GET', 'POST'])
@login_required
def student_edit(student_id):
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)
    student = Student.query.get_or_404(student_id)
    form = StudentForm(obj=student)
    if form.validate_on_submit():
        student.student_number = form.student_number.data.strip()
        student.first_name  = form.first_name.data.strip()
        student.last_name   = form.last_name.data.strip()
        student.middle_name = form.middle_name.data.strip() if form.middle_name.data else None
        student.class_name  = form.class_name.data or None
        student.study_area  = form.study_area.data or None
        db.session.commit()
        log_activity(current_user, 'edit_student', f'Edited {student.full_name()}')
        flash(f'{student.full_name()} updated', 'success')
        return redirect(url_for('students'))
    return render_template('student_form.html', form=form, student=student)


@app.route('/students/<int:student_id>/delete', methods=['POST'])
@login_required
@admin_required
def student_delete(student_id):
    """Delete a student and all associated data"""
    try:
        student = Student.query.get_or_404(student_id)
        name = student.full_name()
        num  = student.student_number
        
        # Delete in order of dependencies to avoid locking issues
        # Delete quiz attempts first (depends on questions)
        QuizAttempt.query.filter_by(student_id=student_id).delete()
        
        # Delete question attempts
        QuestionAttempt.query.filter_by(student_id=student_id).delete()
        
        # Delete assessments (they have cascading delete to their children)
        Assessment.query.filter_by(student_id=student_id).delete()
        
        # Finally delete the student
        db.session.delete(student)
        db.session.commit()
        
        log_activity(current_user, 'delete_student', f'Deleted {name} ({num})')
        flash(f'Student {name} deleted', 'success')
    except Exception as exc:
        db.session.rollback()
        app.logger.error(f'Error deleting student {student_id}: {str(exc)}')
        flash(f'Error deleting student: {str(exc)}', 'error')
    return redirect(url_for('students'))


@app.route('/students/<int:student_id>')
@login_required
def student_view(student_id):
    student = Student.query.get_or_404(student_id)
    subject = request.args.get('subject')

    if subject:
        assessments = [a for a in student.assessments if a.subject == subject]
    elif hasattr(current_user, 'is_teacher') and current_user.is_teacher():
        assessments = [a for a in student.assessments
                       if a.teacher_id == current_user.id]
        if current_user.subject:
            assessments = [a for a in assessments
                           if a.subject == current_user.subject]
    else:
        assessments = student.assessments

    tid       = current_user.id if current_user.is_teacher() else None
    summary   = student.get_assessment_summary(subject, teacher_id=tid)
    final_pct = student.calculate_final_grade(subject=subject, teacher_id=tid)

    summary_list = [
        {'category': cat, 'count': d.get('count', 0),
         'avg_percent': round(d.get('avg_percent', 0.0), 1)}
        for cat, d in summary.items()
    ]

    all_subjects = sorted({a.subject for a in student.assessments
                           if (a.teacher_id == current_user.id
                               if current_user.is_teacher() else True)})

    gr = calculate_gpa_and_grade(final_pct)
    letter_grade = gr['grade'] if final_pct is not None else None
    gpa          = gr['gpa']   if final_pct is not None else None
    comment      = _get_comment(gpa)

    teacher_results = None
    if current_user.is_admin():
        ts = {}
        for a in assessments:
            ts.setdefault(a.teacher_id, {}).setdefault(a.subject, []).append(a)
        teacher_results = {}
        for tid2, sd in ts.items():
            t2 = User.query.get(tid2)
            tname = t2.username if t2 else f'Teacher {tid2}'
            teacher_results[tname] = {}
            for sname, alist in sd.items():
                fp2 = student.calculate_final_grade(subject=sname, teacher_id=tid2)
                gr2 = calculate_gpa_and_grade(fp2)
                teacher_results[tname][sname] = {
                    'final_percent': fp2, 'gpa': gr2['gpa'],
                    'grade': gr2['grade'], 'assessments': alist,
                }

    return render_template(
        'student_view.html',
        student=student, assessments=assessments,
        teacher_results=teacher_results, summary=summary,
        summary_list=summary_list, final_percent=final_pct,
        letter_grade=letter_grade, gpa=gpa, comment=comment,
        subject=subject, all_subjects=all_subjects,
        study_areas_dict=dict(app.config['STUDY_AREAS']),
        CATEGORY_LABELS=app.config['CATEGORY_LABELS'],
    )


@app.route('/students/<int:student_id>/detail')
@login_required
def student_detail(student_id):
    return student_view(student_id)


@app.route('/students/bulk-import', methods=['GET', 'POST'])
@login_required
def student_bulk_import():
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)
    form = StudentBulkImportForm()
    if form.validate_on_submit():
        file     = form.excel_file.data
        filepath = os.path.join(app.config['UPLOAD_FOLDER'],
                                secure_filename(file.filename))
        file.save(filepath)
        try:
            data_list = StudentBulkImporter(filepath).import_students()
            for item in data_list:
                item['class_name'] = canonical_class_key(item.get('class_name'))
                item['study_area'] = canonical_study_area_key(item.get('study_area'))
            ok = 0; errors = []
            for data in data_list:
                try:
                    if Student.query.filter_by(
                            student_number=data['student_number']).first():
                        errors.append(f"{data['student_number']} already exists")
                        continue
                    db.session.add(Student(
                        student_number=(data.get('student_number') or '').strip(),
                        first_name=(data.get('first_name') or '').strip(),
                        last_name=(data.get('last_name') or '').strip(),
                        middle_name=(data.get('middle_name') or '').strip() or None,
                        class_name=(data.get('class_name') or '').strip() or None,
                        study_area=(data.get('study_area') or '').strip() or None,
                        reference_number=generate_unique_reference_number(),
                    ))
                    ok += 1
                except Exception as exc:
                    errors.append(str(exc))
            db.session.commit()
            os.remove(filepath)
            flash(f'Imported {ok} students. {len(errors)} errors.', 'success')
            if errors:
                flash('Errors: ' + '; '.join(errors[:5]), 'warning')
            return redirect(url_for('students'))
        except Exception as exc:
            flash(f'Error: {exc}', 'danger')
    return render_template('student_bulk_import.html', form=form)


@app.route('/users/bulk-import', methods=['GET', 'POST'])
@login_required
@admin_required
def user_bulk_import():
    form = UserBulkImportForm()
    if form.validate_on_submit():
        file     = form.excel_file.data
        filepath = os.path.join(app.config['UPLOAD_FOLDER'],
                                secure_filename(file.filename))
        file.save(filepath)
        try:
            users_data = TeacherBulkImporter(filepath).import_teachers()
            ok = 0; errors = []
            for data in users_data:
                username = (data.get('username') or '').strip()
                if not username:
                    errors.append('Missing username'); continue
                if User.query.filter_by(username=username).first():
                    errors.append(f'{username} already exists'); continue
                role = (data.get('role') or 'teacher').lower()
                if role not in ('teacher', 'admin'):
                    role = 'teacher'
                pw = (data.get('password') or
                      app.config.get('DEFAULT_STUDENT_PASSWORD', 'Teacher@123')).strip()
                user = User(
                    username=username,
                    password_hash=bcrypt.generate_password_hash(pw).decode('utf-8'),
                    role=role,
                    subject=canonical_subject_key(data.get('subject')),
                )
                ck = []
                if data.get('classes'):
                    for rc in re.split(r'[;,]', data['classes']):
                        c = canonical_class_key(rc)
                        if c: ck.append(c)
                if ck:
                    user.set_classes_list(sorted(set(ck)))
                db.session.add(user)
                ok += 1
            db.session.commit()
            os.remove(filepath)
            flash(f'Imported {ok} users. {len(errors)} errors.', 'success')
            if errors:
                flash('Errors: ' + '; '.join(errors[:5]), 'warning')
            return redirect(url_for('users'))
        except Exception as exc:
            db.session.rollback()
            if os.path.exists(filepath):
                os.remove(filepath)
            flash(f'Error: {exc}', 'danger')
    return render_template('user_bulk_import.html', form=form)


# ---------------------------------------------------------------------------
# Assessment routes
# ---------------------------------------------------------------------------
@app.route('/assessments')
@login_required
def assessments_list():
    page      = request.args.get('page', 1, type=int)
    subject   = request.args.get('subject', '')
    class_name = request.args.get('class', '')
    category  = request.args.get('category', '')
    per_page  = app.config['ASSESSMENTS_PER_PAGE']

    if hasattr(current_user, 'is_teacher') and current_user.is_teacher():
        q = Assessment.query.filter_by(teacher_id=current_user.id, archived=False)
    else:
        q = Assessment.query.filter_by(archived=False)

    if subject:    q = q.filter_by(subject=subject)
    if class_name: q = q.filter_by(class_name=class_name)
    if category:   q = q.filter_by(category=category)

    pagination = q.order_by(Assessment.date_recorded.desc()) \
                  .paginate(page=page, per_page=per_page, error_out=False)
    
    # Filter out assessments with missing students
    pagination.items = [a for a in pagination.items if a.student is not None]

    form = AssessmentFilterForm()
    form.subject.data    = subject
    form.class_name.data = class_name
    form.category.data   = category

    return render_template(
        'assessments.html',
        assessments=pagination.items,
        form=form, page=page, per_page=per_page,
        total=pagination.total, pagination=pagination,
        student_performance=[],
        subject_filter=subject, class_filter=class_name,
        category_filter=category, avg_score=0.0, avg_gpa=0.0,
    )


@app.route('/assessments/new', methods=['GET', 'POST'])
@login_required
def new_assessment():
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)
    form = AssessmentForm()

    # Get students based on teacher's access level
    if current_user.is_teacher():
        # Filter by subject - teacher can only assess their subject
        if not current_user.subject:
            flash('You must have a subject assigned to create assessments', 'warning')
            return redirect(url_for('teacher_subject'))
        
        # Filter by study area
        areas = current_user.get_assigned_study_areas(app.config)
        
        # Filter by class - teacher can only assess students in their assigned class(es)
        teacher_classes = current_user.get_classes_list()
        
        if areas and teacher_classes:
            # Filter by both study area AND class
            students_qs = Student.query.filter(
                Student.study_area.in_(areas),
                Student.class_name.in_(teacher_classes)
            ).order_by(Student.class_name, Student.last_name).all()
        elif areas:
            # Filter by study area only
            students_qs = Student.query.filter(
                Student.study_area.in_(areas)
            ).order_by(Student.class_name, Student.last_name).all()
        elif teacher_classes:
            # Filter by class only
            students_qs = Student.query.filter(
                Student.class_name.in_(teacher_classes)
            ).order_by(Student.class_name, Student.last_name).all()
        else:
            # No filters - teacher not properly configured
            students_qs = []
    else:
        # Admin can see all students
        students_qs = Student.query.order_by(Student.class_name, Student.last_name).limit(500).all()

    # Group students by class for dropdown
    grouped = {}
    for s in students_qs:
        class_display = s.get_class_display() or 'Unassigned'
        if class_display not in grouped:
            grouped[class_display] = []
        grouped[class_display].append(s)
    
    # Sort groups by class name
    sorted_groups = {cn: sorted(grouped[cn], key=lambda s: s.full_name())
                     for cn in sorted(grouped.keys())}

    settings = Setting.query.first()
    if current_user.is_teacher() and current_user.subject:
        form.subject.data = current_user.subject
    
    snum_param = request.args.get('student')
    student_obj = None
    if snum_param:
        student_obj = Student.query.filter_by(student_number=snum_param).first()
        if student_obj and current_user.is_teacher():
            # Verify teacher can access this student
            if not current_user.can_access_student(student_obj, app.config):
                abort(403)
        if student_obj:
            form.student_name.data = student_obj.student_number
    
    if settings:
        form.term.data          = settings.current_term
        form.academic_year.data = settings.current_academic_year
        form.session.data       = settings.current_session

    if form.validate_on_submit():
        snum    = form.student_name.data or (form.student_number.data or '').strip()
        student = Student.query.filter_by(student_number=snum).first()
        if not student:
            flash('Invalid student selected.', 'danger')
            return redirect(url_for('new_assessment'))

        # Teacher access check
        if current_user.is_teacher() and not current_user.can_access_student(student, app.config):
            flash('You do not have permission to create assessments for this student.', 'danger')
            abort(403)

        if Assessment.query.filter_by(
                student_id=student.id, category=form.category.data,
                subject=form.subject.data, term=form.term.data,
                academic_year=form.academic_year.data,
                session=form.session.data,
                teacher_id=current_user.id).first():
            flash('Assessment already exists for this student/category/term.', 'warning')
            return redirect(url_for('student_view', student_id=student.id))

        cat       = form.category.data
        max_score = app.config['CATEGORY_MAX_SCORES'].get(cat, 100.0)
        if form.score.data > max_score:
            flash(f'Score cannot exceed {max_score}', 'danger')
            return redirect(url_for('new_assessment'))

        a = Assessment(
            student=student, category=cat,
            subject=form.subject.data,
            class_name=form.class_name.data or student.class_name,
            score=float(form.score.data), max_score=max_score,
            term=form.term.data, academic_year=form.academic_year.data,
            session=form.session.data,
            assessor=form.assessor.data or current_user.username,
            teacher_id=current_user.id, comments=form.comments.data,
        )
        db.session.add(a)
        db.session.commit()
        log_activity(current_user, 'create_assessment',
                     f'Created assessment for {student.full_name()}')
        flash(f'Assessment saved for {student.full_name()}', 'success')
        return redirect(url_for('student_view', student_id=student.id))

    return render_template('assessment_form.html', form=form,
                           grouped_students=sorted_groups,
                           student_dict={},
                           student_full_name=student_obj.full_name()
                           if student_obj else None)


@app.route('/assessments/<int:assessment_id>/edit', methods=['GET', 'POST'])
@login_required
def assessment_edit(assessment_id):
    a = Assessment.query.get_or_404(assessment_id)
    if not (current_user.is_admin() or
            (current_user.is_teacher() and a.teacher_id == current_user.id)):
        abort(403)
    form = AssessmentForm(obj=a)
    students_qs = Student.query.all()
    grouped = {}
    for s in students_qs:
        grouped.setdefault(s.class_name or 'Unspecified', []).append(s)
    sorted_groups = {cn: sorted(gs, key=lambda s: s.full_name())
                     for cn in sorted(grouped)
                     for gs in [grouped[cn]]}
    form.student_name.data     = a.student.student_number
    form.student_number.data   = a.student.student_number
    form.reference_number.data = a.student.reference_number

    if form.validate_on_submit():
        snum    = form.student_name.data or (form.student_number.data or '').strip()
        student = Student.query.filter_by(student_number=snum).first()
        if not student:
            flash('Invalid student.', 'danger')
            return redirect(url_for('assessment_edit', assessment_id=assessment_id))
        cat       = form.category.data
        max_score = app.config['CATEGORY_MAX_SCORES'].get(cat, 100.0)
        if form.score.data > max_score:
            flash(f'Score cannot exceed {max_score}', 'danger')
            return redirect(url_for('assessment_edit', assessment_id=assessment_id))
        a.category     = cat
        a.subject      = form.subject.data
        a.class_name   = form.class_name.data
        a.score        = float(form.score.data)
        a.max_score    = max_score
        a.term         = form.term.data
        a.academic_year = form.academic_year.data
        a.session      = form.session.data
        a.assessor     = form.assessor.data
        a.comments     = form.comments.data
        db.session.commit()
        log_activity(current_user, 'edit_assessment',
                     f'Edited assessment for {a.student.full_name()}')
        flash('Assessment updated', 'success')
        return redirect(url_for('student_view', student_id=a.student_id))

    return render_template('assessment_form.html', form=form,
                           assessment=a, grouped_students=sorted_groups,
                           student_dict={})


@app.route('/assessments/<int:assessment_id>/delete', methods=['POST'])
@login_required
def assessment_delete(assessment_id):
    a = Assessment.query.get_or_404(assessment_id)
    if not (current_user.is_admin() or
            (current_user.is_teacher() and a.teacher_id == current_user.id)):
        abort(403)
    sid  = a.student_id
    name = a.student.full_name()
    db.session.delete(a)
    db.session.commit()
    log_activity(current_user, 'delete_assessment', f'Deleted assessment for {name}')
    flash('Assessment deleted', 'info')
    return redirect(url_for('student_view', student_id=sid))


@app.route('/assessments/<int:assessment_id>/archive', methods=['POST'])
@login_required
def assessment_archive(assessment_id):
    a = Assessment.query.get_or_404(assessment_id)
    if not (current_user.is_admin() or
            (current_user.is_teacher() and a.teacher_id == current_user.id)):
        abort(403)
    a.archived = True
    db.session.commit()
    flash('Assessment archived', 'info')
    return redirect(request.referrer or url_for('assessments_list'))


@app.route('/assessments/<int:assessment_id>/unarchive', methods=['POST'])
@login_required
def assessment_unarchive(assessment_id):
    a = Assessment.query.get_or_404(assessment_id)
    if not (current_user.is_admin() or
            (current_user.is_teacher() and a.teacher_id == current_user.id)):
        abort(403)
    a.archived = False
    db.session.commit()
    flash('Assessment restored', 'info')
    return redirect(request.referrer or url_for('assessments_list'))


@app.route('/assessments/archived')
@login_required
def assessments_archived():
    page     = request.args.get('page', 1, type=int)
    per_page = app.config['ASSESSMENTS_PER_PAGE']
    if hasattr(current_user, 'is_teacher') and current_user.is_teacher():
        q = Assessment.query.filter_by(teacher_id=current_user.id, archived=True)
    else:
        q = Assessment.query.filter_by(archived=True)
    pagination = q.order_by(Assessment.date_recorded.desc()) \
                  .paginate(page=page, per_page=per_page, error_out=False)
    return render_template('assessments.html', assessments=pagination.items,
                           pagination=pagination, form=AssessmentFilterForm(),
                           archived=True)


@app.route('/assessments/bulk-action', methods=['POST'])
@login_required
def assessment_bulk_action():
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)
    action = request.form.get('action')
    ids    = request.form.getlist('assessment_ids')
    if not ids:
        flash('No assessments selected.', 'warning')
        return redirect(request.referrer or url_for('assessments_list'))
    if action not in ('archive', 'unarchive', 'delete'):
        flash('Invalid action.', 'danger')
        return redirect(url_for('assessments_list'))
    q = Assessment.query.filter(Assessment.id.in_(ids))
    if current_user.is_teacher():
        q = q.filter_by(teacher_id=current_user.id)
    items = q.all()
    if action == 'archive':
        for a in items: a.archived = True
    elif action == 'unarchive':
        for a in items: a.archived = False
    else:
        if not current_user.is_admin(): abort(403)
        for a in items: db.session.delete(a)
    db.session.commit()
    log_activity(current_user, f'bulk_{action}',
                 f'{action}d {len(items)} assessments')
    flash(f'Successfully {action}d {len(items)} assessments.', 'success')
    return redirect(request.referrer or url_for('assessments_list'))


# ---------------------------------------------------------------------------
# User management routes
# ---------------------------------------------------------------------------
@app.route('/users')
@login_required
@admin_required
def users():
    teachers_admins = User.query.filter(User.role.in_(['admin', 'teacher'])) \
                               .order_by(User.username).all()
    students_list   = User.query.filter_by(role='student') \
                               .order_by(User.username).all()
    return render_template('users.html',
                           teachers_admins=teachers_admins,
                           students=students_list)


@app.route('/users/new', methods=['GET', 'POST'])
@login_required
@admin_required
def create_user():
    form = UserForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data.strip()).first():
            flash('Username already exists', 'warning')
        else:
            user = User(
                username=form.username.data.strip(),
                password_hash=bcrypt.generate_password_hash(
                    form.password.data).decode('utf-8'),
                role=form.role.data,
                subject=form.subject.data or None,
            )
            if form.classes.data:
                user.set_classes_list(form.classes.data)
            db.session.add(user)
            db.session.commit()
            log_activity(current_user, 'create_user',
                         f'Created {user.username} ({user.role})')
            flash(f'User {user.username} created', 'success')
            return redirect(url_for('users'))
    return render_template('user_form.html', form=form)


@app.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    form = EditUserForm(role=user.role)
    if form.validate_on_submit():
        user.role    = form.role.data
        user.subject = form.subject.data or None
        user.set_classes_list(form.classes.data) if form.classes.data else setattr(user, 'classes', None)
        db.session.commit()
        log_activity(current_user, 'edit_user', f'Edited {user.username}')
        flash(f'User {user.username} updated', 'success')
        return redirect(url_for('users'))
    form.subject.data = user.subject
    form.classes.data = user.get_classes_list()
    return render_template('edit_user.html', form=form, user=user)


@app.route('/users/<int:user_id>/reset_password', methods=['GET', 'POST'])
@login_required
@admin_required
def reset_password(user_id):
    user = User.query.get_or_404(user_id)
    form = PasswordResetForm()
    if form.validate_on_submit():
        user.password_hash = bcrypt.generate_password_hash(
            form.password.data).decode('utf-8')
        db.session.commit()
        log_activity(current_user, 'reset_password',
                     f'Reset password for {user.username}')
        flash(f'Password reset for {user.username}', 'success')
        return redirect(url_for('users'))
    return render_template('reset_password.html', form=form, user=user)


@app.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    if current_user.id == user_id:
        flash('You cannot delete your own account', 'danger')
        return redirect(url_for('users'))
    user = User.query.get_or_404(user_id)
    uname = user.username
    db.session.delete(user)
    db.session.commit()
    log_activity(current_user, 'delete_user', f'Deleted {uname}')
    flash(f'User {uname} deleted', 'info')
    return redirect(url_for('users'))

# ---------------------------------------------------------------------------
# Admin settings & class management
# ---------------------------------------------------------------------------
@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_settings():
    settings = Setting.query.first()
    if not settings:
        settings = Setting()
        db.session.add(settings)
        db.session.commit()
    form = SettingsForm(obj=settings)
    if form.validate_on_submit():
        settings.current_term          = form.current_term.data
        settings.current_academic_year = form.current_academic_year.data
        settings.current_session       = form.current_session.data
        settings.assessment_active     = form.assessment_active.data
        db.session.commit()
        flash('Settings updated', 'success')
        return redirect(url_for('admin_settings'))
    return render_template('admin_settings.html', form=form, settings=settings)


@app.route('/admin/activity-logs')
@login_required
@admin_required
def admin_activity_logs():
    page = request.args.get('page', 1, type=int)
    logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()) \
                            .paginate(page=page, per_page=50, error_out=False)
    return render_template('activity_logs.html', logs=logs)


@app.route('/admin/class-management')
@login_required
@admin_required
def class_management():
    teachers = User.query.filter_by(role='teacher').all()
    teacher_assignments = {}
    for t in teachers:
        if t.subject:
            teacher_assignments[t.id] = {
                'teacher': t, 'subject': t.subject,
                'assigned_areas': t.get_assigned_study_areas(app.config),
                'assigned_classes': t.get_classes_list(),
            }
    all_keys     = [a[0] for a in app.config['STUDY_AREAS']]
    assigned_set = set()
    for v in teacher_assignments.values():
        assigned_set.update(v['assigned_areas'])
    return render_template('class_management.html',
                           study_areas=app.config['STUDY_AREAS'],
                           study_area_subjects=app.config['STUDY_AREA_SUBJECTS'],
                           class_levels=app.config['CLASS_LEVELS'],
                           learning_areas=app.config['LEARNING_AREAS'],
                           teacher_assignments=teacher_assignments,
                           unassigned_areas=[a for a in all_keys
                                             if a not in assigned_set])


@app.route('/admin/class-register')
@login_required
@admin_required
def class_register():
    study_areas = app.config['STUDY_AREAS']
    students    = Student.query.all()
    form_levels = ['Form 1', 'Form 2', 'Form 3']
    forms_data  = {}
    for fl in form_levels:
        forms_data[fl] = {'total_students': 0, 'study_areas': {}}
        for ak, an in study_areas:
            forms_data[fl]['study_areas'][ak] = {
                'name': an, 'students': [], 'total_students': 0}

    class_keys = [l[0] for l in app.config['CLASS_LEVELS']]
    for s in students:
        cf = canonical_class_key(s.class_name)
        sf = cf if (cf and cf in class_keys) else 'Form 1'
        sa = s.study_area or 'unassigned'
        if sa not in forms_data[sf]['study_areas']:
            forms_data[sf]['study_areas'][sa] = {
                'name': sa.replace('_', ' ').title(),
                'students': [], 'total_students': 0}
        forms_data[sf]['study_areas'][sa]['students'].append(s)
        forms_data[sf]['study_areas'][sa]['total_students'] += 1
        forms_data[sf]['total_students'] += 1

    for fd in forms_data.values():
        for ad in fd['study_areas'].values():
            ad['students'].sort(key=lambda s: (s.last_name or '', s.first_name or ''))

    return render_template('class_register.html',
                           forms_data=forms_data,
                           study_areas=study_areas,
                           study_area_subjects=app.config['STUDY_AREA_SUBJECTS'])


@app.route('/admin/api/class-levels', methods=['POST'])
@login_required
@admin_required
@csrf.exempt
def manage_class_levels():
    data   = request.get_json()
    action = data.get('action')
    levels = SystemConfig.get_config('CLASS_LEVELS', [])
    if action == 'add':
        key  = data.get('key', '').strip().lower().replace(' ', '_')
        name = data.get('name', '').strip()
        if not key or not name:
            return jsonify({'success': False, 'message': 'Key and name required'})
        if any(l[0] == key for l in levels):
            return jsonify({'success': False, 'message': 'Key already exists'})
        levels.append((key, name))
        SystemConfig.set_config('CLASS_LEVELS', levels)
        app.config['CLASS_LEVELS'] = levels
        return jsonify({'success': True, 'message': f'Added {name}'})
    elif action == 'delete':
        key = data.get('key')
        new = [l for l in levels if l[0] != key]
        if len(new) < len(levels):
            SystemConfig.set_config('CLASS_LEVELS', new)
            app.config['CLASS_LEVELS'] = new
            return jsonify({'success': True, 'message': 'Deleted'})
    return jsonify({'success': False, 'message': 'Invalid action'})


@app.route('/admin/api/study-areas', methods=['POST'])
@login_required
@admin_required
@csrf.exempt
def manage_study_areas():
    data   = request.get_json()
    action = data.get('action')
    areas  = SystemConfig.get_config('STUDY_AREAS', [])
    if action == 'add':
        key  = data.get('key', '').strip().lower().replace(' ', '_')
        name = data.get('name', '').strip().upper()
        if not key or not name:
            return jsonify({'success': False, 'message': 'Key and name required'})
        if any(a[0] == key for a in areas):
            return jsonify({'success': False, 'message': 'Key already exists'})
        areas.append((key, name))
        SystemConfig.set_config('STUDY_AREAS', areas)
        app.config['STUDY_AREAS'] = areas
        sas = SystemConfig.get_config('STUDY_AREA_SUBJECTS', {})
        sas[key] = {'core': [], 'electives': []}
        SystemConfig.set_config('STUDY_AREA_SUBJECTS', sas)
        app.config['STUDY_AREA_SUBJECTS'] = sas
        return jsonify({'success': True, 'message': f'Added {name}'})
    elif action == 'delete':
        key = data.get('key')
        new = [a for a in areas if a[0] != key]
        if len(new) < len(areas):
            SystemConfig.set_config('STUDY_AREAS', new)
            app.config['STUDY_AREAS'] = new
            return jsonify({'success': True, 'message': 'Deleted'})
    return jsonify({'success': False, 'message': 'Invalid action'})


@app.route('/admin/api/study-area-subjects/<area_key>', methods=['GET', 'POST'])
@login_required
@admin_required
@csrf.exempt
def manage_study_area_subjects(area_key):
    sas = SystemConfig.get_config('STUDY_AREA_SUBJECTS', {})
    sas.setdefault(area_key, {'core': [], 'electives': []})
    if request.method == 'GET':
        return jsonify(sas[area_key])
    data       = request.get_json()
    subject_key = data.get('subject_key')
    action     = data.get('action')
    cfg        = sas[area_key]
    if action in ('add_core', 'add_elective'):
        bucket = 'core' if action == 'add_core' else 'electives'
        other  = 'electives' if bucket == 'core' else 'core'
        if subject_key not in cfg[bucket]:
            cfg[bucket].append(subject_key)
            if subject_key in cfg[other]:
                cfg[other].remove(subject_key)
            SystemConfig.set_config('STUDY_AREA_SUBJECTS', sas)
            app.config['STUDY_AREA_SUBJECTS'] = sas
            return jsonify({'success': True, 'message': f'Added to {bucket}'})
        return jsonify({'success': False, 'message': 'Already exists'})
    elif action == 'remove':
        removed = False
        for b in ('core', 'electives'):
            if subject_key in cfg[b]:
                cfg[b].remove(subject_key); removed = True
        if removed:
            SystemConfig.set_config('STUDY_AREA_SUBJECTS', sas)
            app.config['STUDY_AREA_SUBJECTS'] = sas
            return jsonify({'success': True, 'message': 'Removed'})
    return jsonify({'success': False, 'message': 'Invalid'})


@app.route('/admin/archive-term', methods=['POST'])
@login_required
@admin_required
def archive_term():
    s = Setting.query.first()
    if not s:
        flash('No settings found', 'danger')
        return redirect(url_for('admin_settings'))
    items = Assessment.query.filter(
        (Assessment.term != s.current_term) |
        (Assessment.academic_year != s.current_academic_year)
    ).filter_by(archived=False).all()
    for a in items:
        a.archived = True
    db.session.commit()
    flash(f'Archived {len(items)} assessments from previous terms', 'success')
    return redirect(url_for('admin_settings'))


@app.route('/users/<int:user_id>/assign-subject', methods=['GET', 'POST'])
@login_required
@admin_required
def assign_teacher_subject(user_id):
    user = User.query.get_or_404(user_id)
    if not user.is_teacher():
        flash('This user is not a teacher', 'danger')
        return redirect(url_for('users'))
    form = TeacherAssignmentForm()
    if form.validate_on_submit():
        user.subject = form.subject.data
        user.set_classes_list(form.classes.data) if form.classes.data \
            else setattr(user, 'classes', None)
        db.session.commit()
        flash(f'Subject assigned to {user.username}', 'success')
        return redirect(url_for('users'))
    form.subject.data = user.subject
    form.classes.data = user.get_classes_list()
    return render_template('teacher_subject.html', form=form, teacher=user)


@app.route('/teacher/subject', methods=['GET', 'POST'])
@login_required
@teacher_required
def teacher_subject():
    form = TeacherAssignmentForm()
    if form.validate_on_submit():
        current_user.subject = form.subject.data
        current_user.set_classes_list(form.classes.data) if form.classes.data \
            else setattr(current_user, 'classes', None)
        db.session.commit()
        flash('Subject updated', 'success')
        return redirect(url_for('dashboard'))
    form.subject.data = current_user.subject
    form.classes.data = current_user.get_classes_list()
    return render_template('teacher_subject.html', form=form, teacher=None)


# ---------------------------------------------------------------------------
# Question bank routes
# ---------------------------------------------------------------------------
@app.route('/teacher/question-bank')
@login_required
def teacher_question_bank():
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)
    page = request.args.get('page', 1, type=int)
    q = Question.query if current_user.is_admin() \
        else Question.query.filter_by(subject=current_user.subject)
    sf = request.args.get('subject')
    if sf and current_user.is_admin():
        q = q.filter_by(subject=sf)
    st = request.args.get('status')
    if st:
        q = q.filter_by(status=st)
    questions = q.order_by(Question.created_at.desc()).paginate(page=page, per_page=20)
    subjects  = ([s[0] for s in db.session.query(Question.subject).distinct().all()]
                 if current_user.is_admin() else [])
    return render_template('teacher_question_bank.html', questions=questions,
                           status_filter=st, subject_filter=sf,
                           subjects=subjects, is_admin=current_user.is_admin())


@app.route('/teacher/questions/new', methods=['GET', 'POST'])
@login_required
@teacher_required
def create_question():
    form = QuestionForm()
    if form.validate_on_submit():
        opts = ([l.strip() for l in form.options.data.split('\n') if l.strip()]
                if form.question_type.data == 'mcq' and form.options.data else None)
        kws  = ([l.strip().lower() for l in form.keywords.data.split('\n') if l.strip()]
                if form.question_type.data == 'short_answer' and form.keywords.data else None)
        db.session.add(Question(
            subject=current_user.subject,
            question_text=form.question_text.data,
            question_type=form.question_type.data,
            options=opts, correct_answer=form.correct_answer.data,
            marks=form.marks.data, keywords=kws,
            difficulty=form.difficulty.data,
            explanation=form.explanation.data,
            created_by=current_user.id,
        ))
        db.session.commit()
        flash('Question created and submitted for approval', 'success')
        return redirect(url_for('teacher_question_bank'))
    return render_template('question_form.html', form=form, title='Create Question')


@app.route('/teacher/questions/<int:question_id>/edit', methods=['GET', 'POST'])
@login_required
@teacher_required
def edit_question(question_id):
    question = Question.query.get_or_404(question_id)
    if not question.can_edit(current_user):
        abort(403)
    form = QuestionForm(obj=question)
    if isinstance(question.options, list):
        form.options.data = '\n'.join(question.options)
    if isinstance(question.keywords, list):
        form.keywords.data = '\n'.join(question.keywords)
    if form.validate_on_submit():
        question.question_text  = form.question_text.data
        question.question_type  = form.question_type.data
        question.options        = ([l.strip() for l in form.options.data.split('\n') if l.strip()]
                                   if form.question_type.data == 'mcq' else None)
        question.correct_answer = form.correct_answer.data
        question.marks          = form.marks.data
        question.keywords       = ([l.strip().lower() for l in form.keywords.data.split('\n') if l.strip()]
                                   if form.question_type.data == 'short_answer' else None)
        question.difficulty     = form.difficulty.data
        question.explanation    = form.explanation.data
        question.updated_at     = datetime.utcnow()
        db.session.commit()
        flash('Question updated', 'success')
        return redirect(url_for('teacher_question_bank'))
    return render_template('question_form.html', form=form,
                           title='Edit Question', question=question)


@app.route('/teacher/questions/<int:question_id>/delete', methods=['POST'])
@login_required
@teacher_required
def delete_question(question_id):
    question = Question.query.get_or_404(question_id)
    if not question.can_edit(current_user):
        abort(403)
    db.session.delete(question)
    db.session.commit()
    flash('Question deleted', 'success')
    return redirect(url_for('teacher_question_bank'))


@app.route('/teacher/questions/bulk_import', methods=['GET', 'POST'])
@login_required
@teacher_required
def bulk_import_questions():
    form = QuestionBulkImportForm()
    if form.validate_on_submit():
        file     = form.excel_file.data
        filepath = os.path.join(app.config['UPLOAD_FOLDER'],
                                secure_filename(file.filename))
        file.save(filepath)
        time.sleep(0.1)
        try:
            data_list = QuestionBulkImporter(filepath).import_questions()
            ok = 0; errors = []
            for d in data_list:
                try:
                    db.session.add(Question(
                        subject=current_user.subject,
                        question_text=d['question_text'],
                        question_type=d['question_type'],
                        options=d['options'],
                        correct_answer=d['correct_answer'],
                        difficulty=d.get('difficulty', 'medium'),
                        explanation=d.get('explanation'),
                        created_by=current_user.id,
                    ))
                    ok += 1
                except Exception as exc:
                    errors.append(str(exc))
            db.session.commit()
            os.remove(filepath)
            flash(f'Imported {ok} questions. {len(errors)} errors.', 'success')
            if errors:
                flash('Errors: ' + '; '.join(errors[:5]), 'warning')
            return redirect(url_for('teacher_question_bank'))
        except Exception as exc:
            flash(f'Error: {exc}', 'danger')
    return render_template('question_bulk_import.html', form=form)


@app.route('/admin/question-bank')
@login_required
@admin_required
def admin_question_bank():
    page = request.args.get('page', 1, type=int)
    sf   = request.args.get('subject')
    st   = request.args.get('status', 'pending')
    q    = Question.query
    if st: q = q.filter_by(status=st)
    if sf: q = q.filter_by(subject=sf)
    questions = q.order_by(Question.created_at.desc()).paginate(page=page, per_page=20)
    subjects  = [s[0] for s in db.session.query(Question.subject).distinct().all()]
    return render_template('admin_question_bank.html', questions=questions,
                           status_filter=st, subject_filter=sf, subjects=subjects)


@app.route('/admin/questions/<int:question_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_question(question_id):
    question = Question.query.get_or_404(question_id)
    action   = request.form.get('action')
    if action == 'approve':
        question.status = 'approved'; question.approved_by = current_user.id
        flash('Question approved', 'success')
    elif action == 'reject':
        question.status = 'rejected'; question.approved_by = current_user.id
        question.rejection_reason = request.form.get('rejection_reason')
        flash('Question rejected', 'warning')
    db.session.commit()
    return redirect(url_for('admin_question_bank'))


@app.route('/admin/questions/approve_all', methods=['POST'])
@login_required
@admin_required
def approve_all_questions():
    pending = Question.query.filter_by(status='pending').all()
    for q in pending:
        q.status = 'approved'; q.approved_by = current_user.id
    db.session.commit()
    flash(f'Approved {len(pending)} questions', 'success')
    return redirect(url_for('admin_question_bank'))


@app.route('/teacher/questions/<int:question_id>/approve', methods=['POST'])
@login_required
@teacher_required
def teacher_approve_question(question_id):
    question = Question.query.get_or_404(question_id)
    if question.subject != current_user.subject:
        abort(403)
    action = request.form.get('action')
    if action == 'approve':
        question.status = 'approved'; question.approved_by = current_user.id
        flash('Question approved', 'success')
    elif action == 'reject':
        question.status = 'rejected'; question.approved_by = current_user.id
        question.rejection_reason = request.form.get('rejection_reason')
        flash('Question rejected', 'warning')
    db.session.commit()
    return redirect(url_for('teacher_question_bank'))


@app.route('/student/questions')
@login_required
@student_required
def student_questions():
    page      = request.args.get('page', 1, type=int)
    questions = Question.query.filter_by(status='approved') \
                              .order_by(Question.created_at.desc()) \
                              .paginate(page=page, per_page=10)
    attempts  = {a.question_id: a for a in
                 QuestionAttempt.query.filter_by(student_id=current_user.id).all()}
    return render_template('student_questions.html',
                           questions=questions, attempts=attempts)


@app.route('/student/questions/<int:question_id>/attempt', methods=['POST'])
@login_required
@student_required
def attempt_question(question_id):
    question = Question.query.get_or_404(question_id)
    if question.status != 'approved':
        abort(404)
    answer = request.form.get('answer')
    if not answer:
        flash('Please provide an answer', 'danger')
        return redirect(url_for('student_questions'))
    if question.question_type == 'mcq':
        correct = answer.strip().upper() == question.correct_answer.strip().upper()
    elif question.question_type == 'true_false':
        correct = answer.lower() == question.correct_answer.lower()
    else:
        correct = answer.strip().lower() == question.correct_answer.strip().lower()
    db.session.add(QuestionAttempt(
        student_id=current_user.id, question_id=question_id,
        student_answer=answer, is_correct=correct,
    ))
    db.session.commit()
    flash('Correct!' if correct else f'Incorrect. Answer: {question.correct_answer}',
          'success' if correct else 'warning')
    return redirect(url_for('student_questions'))


# ---------------------------------------------------------------------------
# Quiz routes
# ---------------------------------------------------------------------------
@app.route('/teacher/quizzes')
@login_required
def teacher_quizzes():
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)
    quizzes = (Quiz.query if current_user.is_admin()
               else Quiz.query.filter_by(subject=current_user.subject)) \
              .order_by(Quiz.created_at.desc()).all()
    return render_template('teacher_quizzes.html', quizzes=quizzes)


@app.route('/teacher/quizzes/new', methods=['GET', 'POST'])
@login_required
def create_quiz():
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)
    form = QuizForm()
    form.subject.choices = ([(s[0], s[1]) for s in app.config['LEARNING_AREAS']]
                            if current_user.is_admin()
                            else [(current_user.subject,
                                   current_user.subject.replace('_', ' ').title())])
    if not current_user.is_admin():
        form.subject.data = current_user.subject
    subj = (request.form.get('subject') or
            (current_user.subject if current_user.is_teacher() else None))
    avail = (Question.query.filter_by(subject=subj, status='approved').all()
             if subj else [])
    form.questions.choices = [(str(q.id),
                               f"{q.question_text[:60]}… ({q.difficulty})")
                              for q in avail]
    if form.validate_on_submit():
        sel_ids = {int(x) for x in form.questions.data if str(x).isdigit()}
        valid   = [q.id for q in avail if q.id in sel_ids]
        db.session.add(Quiz(
            title=form.title.data, subject=form.subject.data,
            description=form.description.data, questions=valid,
            time_limit=int(form.time_limit.data) if form.time_limit.data else None,
            created_by=current_user.id,
        ))
        db.session.commit()
        flash('Quiz created', 'success')
        return redirect(url_for('teacher_quizzes'))
    return render_template('quiz_form.html', form=form,
                           available_questions=avail, quiz=None)


@app.route('/teacher/quizzes/<int:quiz_id>')
@login_required
def quiz_detail(quiz_id):
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)
    quiz = Quiz.query.get_or_404(quiz_id)
    if not current_user.is_admin() and quiz.subject != current_user.subject:
        abort(403)
    questions = {q.id: q for q in
                 Question.query.filter(Question.id.in_(quiz.questions)).all()}
    return render_template('quiz_detail.html', quiz=quiz, questions=questions)


@app.route('/teacher/quizzes/<int:quiz_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_quiz(quiz_id):
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)
    quiz = Quiz.query.get_or_404(quiz_id)
    if not current_user.is_admin() and quiz.subject != current_user.subject:
        abort(403)
    form = QuizForm()
    form.subject.choices = ([(s[0], s[1]) for s in app.config['LEARNING_AREAS']]
                            if current_user.is_admin()
                            else [(quiz.subject, quiz.subject.replace('_', ' ').title())])
    avail = Question.query.filter_by(subject=quiz.subject, status='approved').all()
    form.questions.choices = [(q.id, q.question_text[:60]) for q in avail]
    if form.validate_on_submit():
        quiz.title       = form.title.data
        quiz.description = form.description.data
        quiz.subject     = form.subject.data
        quiz.time_limit  = int(form.time_limit.data) if form.time_limit.data else None
        quiz.is_active   = form.is_active.data
        quiz.questions   = [int(x) for x in request.form.getlist('questions')
                            if str(x).isdigit()]
        db.session.commit()
        flash('Quiz updated', 'success')
        return redirect(url_for('teacher_quizzes'))
    form.title.data       = quiz.title
    form.description.data = quiz.description
    form.subject.data     = quiz.subject
    form.time_limit.data  = quiz.time_limit
    form.is_active.data   = quiz.is_active
    form.questions.data   = quiz.questions
    return render_template('quiz_form.html', form=form, quiz=quiz,
                           available_questions=avail)


@app.route('/teacher/quizzes/<int:quiz_id>/delete', methods=['POST'])
@login_required
def delete_quiz(quiz_id):
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)
    quiz = Quiz.query.get_or_404(quiz_id)
    if not current_user.is_admin() and quiz.subject != current_user.subject:
        abort(403)
    title = quiz.title
    QuizAttempt.query.filter_by(quiz_id=quiz_id).delete()
    db.session.delete(quiz)
    db.session.commit()
    flash(f"Quiz '{title}' deleted", 'success')
    return redirect(url_for('teacher_quizzes'))


@app.route('/teacher/quizzes/<int:quiz_id>/results')
@login_required
def quiz_results_view(quiz_id):
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)
    quiz = Quiz.query.get_or_404(quiz_id)
    if not current_user.is_admin() and quiz.subject != current_user.subject:
        abort(403)
    attempts = QuizAttempt.query.filter_by(quiz_id=quiz_id) \
                                .order_by(QuizAttempt.completed_at.desc()).all()
    pcts = [a.get_percentage() for a in attempts]
    summary_stats = {
        'total_attempts':  len(attempts),
        'avg_score':       sum(pcts) / len(pcts) if pcts else 0.0,
        'highest_score':   max(pcts) if pcts else 0.0,
        'completed_count': sum(1 for a in attempts if a.completed_at),
    }
    sids     = [a.student_id for a in attempts]
    students = {s.id: s for s in
                Student.query.filter(Student.id.in_(sids)).all()}
    return render_template('quiz_results_view.html', quiz=quiz,
                           attempts=attempts, students=students,
                           summary_stats=summary_stats)


@app.route('/teacher/quiz-results')
@login_required
def teacher_quiz_results():
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)
    sf = request.args.get('subject', '')
    q  = Quiz.query
    if current_user.is_teacher():
        q = q.filter_by(subject=current_user.subject)
    elif sf:
        q = q.filter_by(subject=sf)
    quizzes  = q.order_by(Quiz.created_at.desc()).all()
    quiz_ids = [qz.id for qz in quizzes]
    attempts = QuizAttempt.query.filter(QuizAttempt.quiz_id.in_(quiz_ids)) \
                                .order_by(QuizAttempt.completed_at.desc()).all()
    abq = {}; qs = {}
    for a in attempts:
        abq.setdefault(a.quiz_id, []).append(a)
        if a.quiz_id not in qs:
            qs[a.quiz_id] = {'total_attempts': 0, 'avg_score': 0.0,
                             'highest_score': 0.0, 'completed_count': 0}
        qs[a.quiz_id]['total_attempts'] += 1
        pct = a.get_percentage()
        qs[a.quiz_id]['avg_score'] += pct
        qs[a.quiz_id]['highest_score'] = max(qs[a.quiz_id]['highest_score'], pct)
        if a.completed_at:
            qs[a.quiz_id]['completed_count'] += 1
    for qid, s in qs.items():
        if s['total_attempts']:
            s['avg_score'] /= s['total_attempts']
    sids     = list({a.student_id for a in attempts})
    students = {s.id: s for s in
                Student.query.filter(Student.id.in_(sids)).all()}
    return render_template('teacher_quiz_results.html',
                           quizzes=quizzes, attempts_by_quiz=abq,
                           students=students, quiz_summaries=qs,
                           all_subjects=app.config['LEARNING_AREAS'],
                           subject_filter=sf)


@app.route('/student/quizzes')
@login_required
@student_required
def student_quizzes():
    student = Student.query.filter(
        db.func.trim(Student.student_number) == (current_user.username or '').strip()
    ).first()
    if not student:
        flash('Student record not found', 'danger')
        return redirect(url_for('student_dashboard'))
    quizzes  = Quiz.query.filter_by(is_active=True) \
                         .order_by(Quiz.created_at.desc()).all()
    attempts = {a.quiz_id: a for a in
                QuizAttempt.query.filter_by(student_id=student.id).all()}
    return render_template('student_quizzes.html',
                           quizzes=quizzes, attempts=attempts)


@app.route('/student/quizzes/<int:quiz_id>/take', methods=['GET', 'POST'])
@login_required
@student_required
def take_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    if not quiz.is_active:
        abort(404)
    student = Student.query.filter(
        db.func.trim(Student.student_number) == (current_user.username or '').strip()
    ).first()
    if not student:
        flash('Student record not found', 'danger')
        return redirect(url_for('student_dashboard'))
    if QuizAttempt.query.filter_by(student_id=student.id,
                                   quiz_id=quiz_id, status='completed').first():
        flash('You have already taken this quiz', 'warning')
        return redirect(url_for('student_quizzes'))
    attempt = QuizAttempt.query.filter_by(student_id=student.id,
                                          quiz_id=quiz_id,
                                          status='in_progress').first()
    if not attempt:
        attempt = QuizAttempt(
            student_id=student.id, quiz_id=quiz_id,
            score=0.0, total_questions=len(quiz.questions),
            correct_answers=0,
            remaining_time=quiz.time_limit * 60 if quiz.time_limit else None,
            started_at=datetime.utcnow(),
        )
        db.session.add(attempt)
        db.session.commit()

    questions = {q.id: q for q in
                 Question.query.filter(Question.id.in_(quiz.questions)).all()}
    saved = json.loads(attempt.answers_json) if attempt.answers_json else {}

    if request.method == 'POST':
        total_score = 0.0; total_marks = 0.0; qr = {}
        for qid in quiz.questions:
            ans = request.form.get(f'answer_{qid}')
            if not ans:
                continue
            q_obj = questions.get(int(qid))
            if not q_obj:
                continue
            if q_obj.question_type == 'mcq':
                correct = ans.strip().upper() == q_obj.correct_answer.strip().upper()
                score   = q_obj.marks if correct else 0.0
            elif q_obj.question_type == 'true_false':
                correct = ans.lower() == q_obj.correct_answer.lower()
                score   = q_obj.marks if correct else 0.0
            else:
                score   = calculate_short_answer_score(ans, q_obj)
                correct = score > 0
            total_score += score; total_marks += q_obj.marks
            qr[qid] = {'student_answer': ans, 'score': score,
                       'max_marks': q_obj.marks,
                       'correct_answer': q_obj.correct_answer}
            db.session.add(QuestionAttempt(
                student_id=student.id, question_id=qid,
                quiz_attempt_id=attempt.id, student_answer=ans,
                is_correct=correct, score=score,
            ))
        attempt.score          = total_score
        attempt.correct_answers = sum(1 for r in qr.values() if r['score'] > 0)
        attempt.completed_at   = datetime.utcnow()
        attempt.time_taken     = (int((attempt.completed_at -
                                       attempt.started_at).total_seconds())
                                  if attempt.started_at else 0)
        attempt.status         = 'completed'
        attempt.answers_json   = None
        db.session.commit()
        session['quiz_results'] = {
            'quiz_id': quiz_id, 'quiz_title': quiz.title,
            'score': total_score, 'total_marks': total_marks,
            'percentage': round((total_score / total_marks) * 100, 1)
                          if total_marks else 0,
            'completed_at': datetime.utcnow().timestamp(),
            'question_results': qr,
        }
        session.modified = True
        return redirect(url_for('quiz_results'))
    return render_template('take_quiz.html', quiz=quiz,
                           questions=questions, attempt=attempt,
                           saved_answers=saved)


@app.route('/student/quizzes/<int:quiz_id>/save_progress', methods=['POST'])
@login_required
@student_required
def save_quiz_progress(quiz_id):
    student = Student.query.filter(
        db.func.trim(Student.student_number) == (current_user.username or '').strip()
    ).first()
    if not student:
        return jsonify({'success': False}), 400
    attempt = QuizAttempt.query.filter_by(student_id=student.id,
                                          quiz_id=quiz_id,
                                          status='in_progress').first()
    if not attempt:
        return jsonify({'success': False}), 400
    answers = {k.replace('answer_', ''): v
               for k, v in request.form.items() if k.startswith('answer_')}
    attempt.answers_json  = json.dumps(answers)
    attempt.remaining_time = int(request.form.get('remaining_time', 0))
    db.session.commit()
    return jsonify({'success': True})


@app.route('/quiz/results')
@login_required
@student_required
def quiz_results():
    qr = session.get('quiz_results')
    if not qr:
        flash('No quiz results available', 'warning')
        return redirect(url_for('student_quizzes'))
    if time.time() - qr.get('completed_at', 0) > 7200:
        session.pop('quiz_results', None)
        flash('Quiz results have expired', 'info')
        return redirect(url_for('student_quizzes'))
    quiz      = Quiz.query.get_or_404(qr['quiz_id'])
    questions = {q.id: q for q in
                 Question.query.filter(Question.id.in_(quiz.questions)).all()}
    fmt = datetime.fromtimestamp(qr.get('completed_at', 0)).strftime('%Y-%m-%d %H:%M')
    return render_template('quiz_results.html', quiz_results=qr,
                           quiz=quiz, questions=questions,
                           completed_at_formatted=fmt)


@app.route('/student/quiz-attempt/<int:attempt_id>/review')
@login_required
@student_required
def quiz_attempt_review(attempt_id):
    student = Student.query.filter(
        db.func.trim(Student.student_number) == (current_user.username or '').strip()
    ).first()
    if not student:
        flash('Student record not found', 'danger')
        return redirect(url_for('student_dashboard'))
    attempt = QuizAttempt.query.filter_by(id=attempt_id,
                                          student_id=student.id).first()
    if not attempt:
        flash('Attempt not found', 'danger')
        return redirect(url_for('student_dashboard'))
    quiz = Quiz.query.get(attempt.quiz_id)
    if not quiz:
        flash('Quiz not found', 'danger')
        return redirect(url_for('student_dashboard'))
    questions = {q.id: q for q in
                 Question.query.filter(Question.id.in_(quiz.questions)).all()}
    qa_map    = {qa.question_id: qa for qa in
                 QuestionAttempt.query.filter_by(quiz_attempt_id=attempt_id).all()}
    return render_template('quiz_attempt_review.html', attempt=attempt,
                           quiz=quiz, questions=questions,
                           question_attempts=qa_map)


# ---------------------------------------------------------------------------
# Export / Import / Download routes
# ---------------------------------------------------------------------------
@app.route('/export/csv')
@login_required
def export_csv():
    if not (current_user.is_admin() or current_user.is_teacher()):
        abort(403)
    q = Assessment.query.filter_by(archived=False)
    if current_user.is_teacher():
        q = q.filter_by(teacher_id=current_user.id)
    assessments = q.order_by(Assessment.date_recorded.desc()).all()
    si = io.StringIO()
    w  = csv.writer(si)
    w.writerow(['student_number', 'name', 'category', 'subject', 'score',
                'max_score', 'percentage', 'term', 'academic_year',
                'session', 'assessor', 'teacher', 'comments', 'date_recorded'])
    for a in assessments:
        tname = a.assigned_teacher.username if a.assigned_teacher else 'N/A'
        w.writerow([a.student.student_number, a.student.full_name(), a.category,
                    a.subject, a.score, a.max_score,
                    f'{a.get_percentage():.2f}', a.term,
                    a.academic_year, a.session, a.assessor, tname,
                    a.comments, a.date_recorded.strftime('%Y-%m-%d %H:%M:%S')])
    mem = io.BytesIO()
    mem.write(si.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, as_attachment=True,
                     download_name='assessments_export.csv',
                     mimetype='text/csv')


@app.route('/export/student/<int:student_id>/csv')
@login_required
def export_student_csv(student_id):
    if not (current_user.is_admin() or current_user.is_teacher()):
        abort(403)
    student = Student.query.get_or_404(student_id)
    subject = request.args.get('subject')
    q = Assessment.query.filter_by(student_id=student.id, archived=False)
    if current_user.is_teacher():
        q = q.filter_by(teacher_id=current_user.id)
        if current_user.subject:
            q = q.filter_by(subject=current_user.subject)
    if subject:
        q = q.filter_by(subject=subject)
    si = io.StringIO()
    w  = csv.writer(si)
    w.writerow(['category', 'subject', 'class', 'score', 'max_score',
                'percentage', 'grade', 'term', 'academic_year',
                'session', 'assessor', 'teacher', 'comments', 'date_recorded'])
    for a in q.all():
        tname = a.assigned_teacher.username if a.assigned_teacher else 'N/A'
        w.writerow([a.category, a.subject, a.class_name,
                    a.score, a.max_score, f'{a.get_percentage():.2f}',
                    a.get_grade_letter(), a.term, a.academic_year,
                    a.session, a.assessor, tname, a.comments,
                    a.date_recorded.strftime('%Y-%m-%d %H:%M:%S')])
    mem = io.BytesIO()
    mem.write(si.getvalue().encode('utf-8'))
    mem.seek(0)
    sub_s = f'_{subject}' if subject else ''
    return send_file(mem, as_attachment=True,
                     download_name=f'{student.student_number}_{student.last_name}_assessments{sub_s}.csv',
                     mimetype='text/csv')


@app.route('/export/excel/student/<int:student_id>')
@login_required
def export_student_excel(student_id):
    if not (current_user.is_admin() or current_user.is_teacher()):
        abort(403)
    student = Student.query.get_or_404(student_id)
    subject = request.args.get('subject')
    tpl_path = os.path.join(app.config['TEMPLATE_FOLDER'], 'student_template.xlsx')
    if not os.path.exists(tpl_path):
        create_default_template(tpl_path)
    sub_s = f'_{subject}' if subject else ''
    out_name = f'{student.student_number}_{student.last_name}_report{sub_s}.xlsx'
    out_path = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
    try:
        settings = Setting.query.first()
        upd = AssessmentTemplateUpdater(tpl_path)
        upd.load_template()
        if settings:
            exp_subj = (subject or
                        (current_user.subject if current_user.is_teacher() else None) or
                        student.study_area)
            upd.update_school_info(
                subject=exp_subj,
                term_year=f'{settings.current_term} {settings.current_academic_year}',
                form=student.class_name)
        upd.add_student(10, student.to_template_dict(subject))
        upd.save_workbook(out_path)
        return send_file(out_path, as_attachment=True,
                         download_name=out_name,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as exc:
        flash(f'Error exporting to Excel: {exc}', 'danger')
        return redirect(url_for('student_view', student_id=student_id))


@app.route('/export/excel/all-students')
@login_required
def export_all_students_excel():
    if not (current_user.is_admin() or current_user.is_teacher()):
        abort(403)
    subject    = request.args.get('subject')
    class_name = request.args.get('class')
    q = Student.query
    if subject:
        subq = db.session.query(Assessment.student_id) \
                         .filter(Assessment.subject == subject).distinct()
        q = q.filter(Student.id.in_(subq))
    if class_name:
        q = q.filter_by(class_name=class_name)
    students_list = q.order_by(Student.last_name, Student.first_name).all()
    tpl_path = os.path.join(app.config['TEMPLATE_FOLDER'], 'student_template.xlsx')
    if not os.path.exists(tpl_path):
        create_default_template(tpl_path)
    sub_s = subject or 'all_subjects'
    cls_s = class_name or 'all_classes'
    out_name = f'students_{sub_s}_{cls_s}_{datetime.now().strftime("%Y%m%d")}.xlsx'
    out_path = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
    try:
        settings = Setting.query.first()
        upd = AssessmentTemplateUpdater(tpl_path)
        upd.load_template()
        if settings:
            upd.update_school_info(
                subject=subject or 'All Subjects',
                term_year=f'{settings.current_term} {settings.current_academic_year}',
                form=class_name or 'All Classes')
        upd.add_students_batch([s.to_template_dict() for s in students_list])
        upd.save_workbook(out_path)
        return send_file(out_path, as_attachment=True,
                         download_name=out_name,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as exc:
        flash(f'Error exporting to Excel: {exc}', 'danger')
        return redirect(url_for('students'))


@app.route('/export/assessments/excel')
@login_required
def export_assessments_excel():
    if not (current_user.is_admin() or current_user.is_teacher()):
        abort(403)
    from openpyxl import Workbook
    subject    = request.args.get('subject', '').strip()
    class_name = request.args.get('class',   '').strip()
    category   = request.args.get('category','').strip()
    q = (Assessment.query.filter_by(teacher_id=current_user.id, archived=False)
         if current_user.is_teacher()
         else Assessment.query.filter_by(archived=False))
    if subject:    q = q.filter_by(subject=subject)
    if class_name: q = q.filter_by(class_name=class_name)
    if category:   q = q.filter_by(category=category)
    assessments = q.order_by(Assessment.date_recorded.desc()).all()
    filters     = [f for f in [subject, class_name, category] if f]
    filter_str  = '_'.join(filters) if filters else 'all'
    out_name    = f'assessments_{filter_str}_{datetime.now().strftime("%Y%m%d")}.xlsx'
    out_path    = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
    try:
        wb = Workbook(); ws = wb.active; ws.title = 'Assessments'
        headers = ['Student Number', 'Student Name', 'Subject', 'Category',
                   'Score', 'Max Score', 'Percentage', 'Grade', 'Class',
                   'Term', 'Academic Year', 'Session', 'Assessor', 'Date Recorded']
        for col, h in enumerate(headers, 1):
            ws.cell(row=1, column=col, value=h)
        for row, a in enumerate(assessments, 2):
            for col, val in enumerate([
                a.student.student_number, a.student.full_name(),
                a.subject, a.category, a.score, a.max_score,
                round(a.get_percentage(), 2), a.get_grade_letter(),
                a.class_name, a.term, a.academic_year, a.session,
                a.assessor, a.date_recorded.strftime('%Y-%m-%d %H:%M:%S'),
            ], 1):
                ws.cell(row=row, column=col, value=val)
        wb.save(out_path)
        return send_file(out_path, as_attachment=True,
                         download_name=out_name,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as exc:
        flash(f'Error: {exc}', 'danger')
        return redirect(url_for('assessments_list'))


@app.route('/import/excel', methods=['GET', 'POST'])
@login_required
def import_excel():
    form = BulkImportForm()
    if form.validate_on_submit():
        file     = form.excel_file.data
        filepath = os.path.join(app.config['UPLOAD_FOLDER'],
                                secure_filename(file.filename))
        file.save(filepath)
        try:
            data_list = ExcelBulkImporter(filepath).import_assessments()
            ok = 0; errors = []
            for data in data_list:
                try:
                    student = Student.query.filter_by(
                        student_number=data['student_number']).first()
                    if not student:
                        errors.append(f"Student {data['student_number']} not found")
                        continue
                    if Assessment.query.filter_by(
                            student_id=student.id,
                            category=data['category'],
                            subject=data['subject'],
                            term=data['term'],
                            academic_year=data.get('academic_year'),
                            session=data['session']).first():
                        errors.append(f"Assessment already exists for {data['student_number']}")
                        continue
                    db.session.add(Assessment(
                        student=student, category=data['category'],
                        subject=data['subject'],
                        score=float(data['score']),
                        max_score=float(data['max_score']),
                        term=data['term'],
                        academic_year=data.get('academic_year'),
                        session=data['session'],
                        assessor=data['assessor'],
                        teacher_id=current_user.id if current_user.is_teacher() else None,
                        comments=data['comments'],
                    ))
                    ok += 1
                except Exception as exc:
                    errors.append(str(exc))
            db.session.commit()
            os.remove(filepath)
            flash(f'Imported {ok} assessments', 'success')
            if errors:
                flash(f'{len(errors)} errors: {"; ".join(errors[:5])}', 'warning')
            return redirect(url_for('assessments_list'))
        except Exception as exc:
            db.session.rollback()
            if os.path.exists(filepath): os.remove(filepath)
            flash(f'Error: {exc}', 'danger')
    return render_template('import_excel.html', form=form)


@app.route('/download/template/<template_type>')
@login_required
def download_template(template_type):
    mapping = {
        'student':      ('student_template.xlsx',        'student_assessment_template.xlsx',       create_default_template),
        'student_import': ('student_import_template.xlsx', 'student_bulk_import_template.xlsx',    create_student_import_template),
        'user_import':  ('user_import_template.xlsx',    'teacher_bulk_import_template.xlsx',      create_teacher_import_template),
    }
    if template_type not in mapping and template_type != 'import':
        abort(404)
    if template_type == 'import':
        tpl_path = os.path.join(app.config['TEMPLATE_FOLDER'], 'import_template.xlsx')
        if not os.path.exists(tpl_path):
            flash('Import template not found.', 'danger')
            return redirect(url_for('import_excel'))
        return send_file(tpl_path, as_attachment=True,
                         download_name='bulk_import_template.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    fname, dname, creator = mapping[template_type]
    tpl_path = os.path.join(app.config['TEMPLATE_FOLDER'], fname)
    if not os.path.exists(tpl_path):
        creator(tpl_path)
    return send_file(tpl_path, as_attachment=True, download_name=dname,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/download/question_template')
@login_required
@teacher_required
def download_question_template():
    tpl_path = os.path.join(app.config['TEMPLATE_FOLDER'],
                            'question_import_template.xlsx')
    if not os.path.exists(tpl_path):
        create_question_import_template(tpl_path)
    return send_file(tpl_path, as_attachment=True,
                     download_name='question_bulk_import_template.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/upload/template', methods=['GET', 'POST'])
@login_required
@admin_required
def upload_template():
    if request.method == 'POST':
        f = request.files.get('template_file')
        if not f or f.filename == '':
            flash('No file selected', 'danger')
            return redirect(request.url)
        if f.filename.endswith('.xlsx'):
            f.save(os.path.join(app.config['TEMPLATE_FOLDER'],
                                secure_filename('student_template.xlsx')))
            flash('Template uploaded', 'success')
            return redirect(url_for('dashboard'))
    return render_template('upload_template.html')


# ---------------------------------------------------------------------------
# API search endpoints
# ---------------------------------------------------------------------------
@app.route('/api/live-data')
@login_required
def live_data():
    if hasattr(current_user, 'is_student') and current_user.is_student():
        return jsonify({'error': 'Access denied'}), 403
    incomplete = get_incomplete_assessments()
    return jsonify({
        'student_count':            Student.query.count(),
        'assessment_count':         Assessment.query.filter_by(archived=False).count(),
        'users_count':              User.query.count(),
        'affected_students_count':  len(incomplete),
        'incomplete_students_count': len(incomplete),
    })


@app.route('/api/student_search')
@login_required
def student_search():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'results': []})
    matches = Student.query.filter(
        db.or_(
            Student.student_number.ilike(f'%{query}%'),
            Student.first_name.ilike(f'%{query}%'),
            Student.last_name.ilike(f'%{query}%'),
        )
    ).limit(10).all()
    return jsonify({'results': [
        {'student_number': s.student_number, 'name': s.full_name(),
         'reference_number': s.reference_number}
        for s in matches
    ]})


@app.route('/api/search')
@login_required
def global_search():
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify({'results': []})
    q = Student.query.filter(
        db.or_(
            Student.student_number.ilike(f'%{query}%'),
            Student.first_name.ilike(f'%{query}%'),
            Student.last_name.ilike(f'%{query}%'),
            Student.reference_number.ilike(f'%{query}%'),
        )
    )
    if current_user.is_teacher():
        areas = current_user.get_assigned_study_areas(app.config)
        if areas:
            q = q.filter(Student.study_area.in_(areas))
    return jsonify({'students': [
        {'id': s.id, 'name': s.full_name(),
         'student_number': s.student_number,
         'class': s.get_class_display(),
         'url': url_for('student_view', student_id=s.id)}
        for s in q.limit(10).all()
    ]})


@app.route('/api/teacher/assessments')
@login_required
@teacher_required
def teacher_assessments_api():
    if not current_user.subject:
        return jsonify({'assessments': []})
    assessments = Assessment.query.filter_by(
        subject=current_user.subject, teacher_id=current_user.id
    ).order_by(Assessment.date_recorded.desc()).limit(50).all()
    return jsonify({'assessments': [
        {'student_name': a.student.full_name(),
         'student_number': a.student.student_number,
         'category': a.category, 'score': a.score,
         'max_score': a.max_score, 'percentage': a.get_percentage(),
         'class_name': a.class_name,
         'date': a.date_recorded.strftime('%Y-%m-%d')}
        for a in assessments
    ]})


# ---------------------------------------------------------------------------
# Messages routes
# ---------------------------------------------------------------------------
@app.route('/messages')
@login_required
def user_messages():
    """Display user's messages with pagination"""
    page = request.args.get('page', 1, type=int)
    messages = Message.query.filter_by(recipient_id=current_user.id).order_by(
        Message.created_at.desc()
    ).paginate(page=page, per_page=10)
    return render_template('user_messages.html', messages=messages)


@app.route('/messages/<int:message_id>')
@login_required
def view_message(message_id):
    """View a specific message"""
    message = Message.query.get_or_404(message_id)
    
    # Check if current user is the recipient
    if message.recipient_id != current_user.id:
        abort(403)
    
    # Mark as read
    if not message.is_read:
        message.is_read = True
        db.session.commit()
    
    return render_template('view_message.html', message=message)


@app.route('/admin/messages')
@login_required
@admin_required
def admin_messages():
    """Admin view for broadcast messages"""
    page = request.args.get('page', 1, type=int)
    # Show messages sent by current admin
    messages = Message.query.filter_by(sender_id=current_user.id).order_by(
        Message.created_at.desc()
    ).paginate(page=page, per_page=10)
    return render_template('admin_messages.html', messages=messages)


@app.route('/admin/messages/send', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_send_message():
    """Admin send broadcast message to users"""
    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        content = request.form.get('content', '').strip()
        recipient_type = request.form.get('recipient_type', 'all')  # all, teachers, students
        
        if not subject or not content:
            flash('Subject and content are required', 'danger')
            return render_template('admin_send_message.html')
        
        # Get recipients based on type
        if recipient_type == 'teachers':
            recipients = User.query.filter_by(role='teacher').all()
        elif recipient_type == 'students':
            # For students, we need to send to the Student User accounts
            recipients = User.query.filter_by(role='student').all()
        else:  # all
            recipients = User.query.filter(User.role.in_(['teacher', 'student'])).all()
        
        try:
            for recipient in recipients:
                message = Message(
                    sender_id=current_user.id,
                    recipient_id=recipient.id,
                    subject=subject,
                    content=content,
                    message_type='notification',
                    is_broadcast=True
                )
                db.session.add(message)
            db.session.commit()
            flash(f'Message sent to {len(recipients)} recipient(s)', 'success')
            return redirect(url_for('admin_messages'))
        except Exception as e:
            db.session.rollback()
            app.logger.error(f'Error sending broadcast message: {e}')
            flash('Error sending message', 'danger')
    
    return render_template('admin_send_message.html')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    print('\n' + '=' * 60)
    print('EduAssess – Development Server')
    print('=' * 60)
    print(f'Environment : {env}')
    print(f'Database    : {app.config["SQLALCHEMY_DATABASE_URI"]}')
    print('Access at   : http://127.0.0.1:5000')
    print('=' * 60 + '\n')
    with app.app_context():
        db.create_all()
    app.run(debug=app.config.get('DEBUG', True),
            host='127.0.0.1', port=5000, use_reloader=False)
