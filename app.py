import os
import io
import csv
import random
import re
import time
import json
import shutil
import filecmp
import traceback
import click
from functools import wraps
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime, timezone

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
from flask_caching import Cache
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from wtforms import (StringField, PasswordField, FloatField, SelectField,
                     SelectMultipleField, TextAreaField, BooleanField)
from whitenoise import WhiteNoise
from wtforms.validators import (InputRequired, Length, Optional,
                                NumberRange, ValidationError)

from db import db, redact_database_url
from config import config, Config

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

# Categories that are ACTIVE assessment-entry / completion-tracking
# components, per the current student_template.xlsx. ICP1/ICP2 remain
# valid category codes (CATEGORY_LABELS/CATEGORY_MAX_SCORES/
# ASSESSMENT_WEIGHTS still define them, for historical data, filtering
# and Excel import/export) but are supplementary and non-contributing to
# the final grade — see template_updater.calculate_scores_from_template.
# Every place in this module that lists "the assessment categories a
# teacher must fill in" (entry forms, bulk rosters, completion trackers)
# should reference this constant rather than re-deriving its own list, so
# there is exactly one definition of "active" to keep in sync.
ACTIVE_CATEGORIES = ['ica1', 'ica2', 'gp1', 'gp2', 'practical', 'mid_term', 'end_term']

ASSESSMENTS_PER_PAGE = 20


def utcnow():
    return datetime.now(timezone.utc)


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


def teacher_can_view_student(teacher, student):
    """
    Returns True only if the teacher is permitted to view this student.

    The authorization rules are:
      1. If the teacher has classes assigned, the student must be in one of them.
      2. If STUDY_AREA_SUBJECTS is configured, the student's study_area must
         teach the teacher's subject in either 'core' or 'electives'.

    Admins bypass this check at the call site.
    """
    if not hasattr(teacher, 'is_teacher') or not teacher.is_teacher():
        return False

    teacher_subject = (teacher.subject or '').strip()
    teacher_classes = teacher.get_classes_list()

    if not teacher_subject:
        return False

    if teacher_classes and student.class_name not in teacher_classes:
        return False

    sas = _get_study_area_subjects_config()
    configured = _is_study_area_subjects_configured(sas)

    if configured:
        area_curriculum = sas.get(student.study_area or '', {})
        if teacher_subject not in area_curriculum.get('core', []) and \
                teacher_subject not in area_curriculum.get('electives', []):
            return False
    else:
        if not teacher_classes:
            return False

    return True


# ---------------------------------------------------------------------------
# FIX — centralised, authoritative student filter for teachers
# ---------------------------------------------------------------------------

def get_study_areas():
    from models import SystemConfig
    return SystemConfig.get_config('STUDY_AREAS', []) or []


def get_study_area_subjects():
    from models import SystemConfig
    return SystemConfig.get_config('STUDY_AREA_SUBJECTS', {}) or {}


def get_class_levels():
    levels = app.config.get('CLASS_LEVELS') or []
    if not isinstance(levels, list) or not levels:
        levels = [
            ('Form 1', 'Form 1'),
            ('Form 2', 'Form 2'),
            ('Form 3', 'Form 3'),
        ]
    return levels


def _get_study_area_subjects_config():
    """
    Load STUDY_AREA_SUBJECTS from the database-backed SystemConfig,
    falling back to the Flask app config cache.
    """
    try:
        from models import SystemConfig
        sas = SystemConfig.get_config('STUDY_AREA_SUBJECTS', {})
        if isinstance(sas, dict):
            return sas
    except Exception:
        pass
    return app.config.get('STUDY_AREA_SUBJECTS', {}) or {}


def _is_study_area_subjects_configured(sas):
    """Return True when at least one area has a non-empty core or elective list."""
    if not isinstance(sas, dict):
        return False
    for curriculum in sas.values():
        if curriculum.get('core') or curriculum.get('electives'):
            return True
    return False


def refresh_study_area_config():
    study_areas = get_study_areas()
    study_area_subjects = get_study_area_subjects()
    app.config['STUDY_AREAS'] = study_areas
    app.config['STUDY_AREA_SUBJECTS'] = study_area_subjects
    return study_areas, study_area_subjects


def get_teacher_students_query(teacher):
    """
    Return a SQLAlchemy query restricted to students that the given teacher
    is authorised to assess.

    A student is visible to a teacher only when both of these are true:
      1. The student is in one of the teacher's assigned classes, AND
      2. The student's study_area teaches the teacher's subject.

    STUDY_AREA_SUBJECTS is only used if configured. If it is empty then a
    class-only fallback is used. If it is configured but the teacher's
    subject is not found in any area, access is denied.
    """
    from models import Student

    teacher_classes = teacher.get_classes_list()          # e.g. ['Form 1', 'Form 2']
    teacher_subject = (teacher.subject or '').strip()      # e.g. 'biology'

    if not teacher_subject:
        return None

    sas = _get_study_area_subjects_config()
    eligible_areas = [
        area_key for area_key, subjects in sas.items()
        if teacher_subject in subjects.get('core', []) or
           teacher_subject in subjects.get('electives', [])
    ]

    base_query = Student.query.order_by(Student.class_name, Student.last_name)
    has_classes = bool(teacher_classes)
    has_areas = bool(eligible_areas)
    configured = _is_study_area_subjects_configured(sas)

    if has_classes and has_areas:
        return (base_query
                .filter(Student.class_name.in_(teacher_classes))
                .filter(Student.study_area.in_(eligible_areas)))

    if has_classes and not has_areas:
        if configured:
            return None
        return base_query.filter(Student.class_name.in_(teacher_classes))

    if has_areas and not has_classes:
        return base_query.filter(Student.study_area.in_(eligible_areas))

    return None


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder='static')
app.wsgi_app = WhiteNoise(app.wsgi_app, root='static/')

env = os.environ.get('FLASK_ENV', 'development')
config_cls = config.get(env)
if config_cls is None:
    print(
        f"[BOOT][WARNING] Unknown FLASK_ENV={env!r}; falling back to 'development' config.",
        flush=True,
    )
    config_cls = config['default']

app.config.from_object(config_cls)
# Ensure error handlers render during tests instead of letting exceptions
# propagate — some tests expect the 500 page to be returned even when
# `app.testing` is toggled. Default to not propagating exceptions.
app.config.setdefault('PROPAGATE_EXCEPTIONS', False)
# Also ensure the Flask internal flag is off so errors are routed to our
# `internal_error` handler instead of being re-raised when `app.testing`
# is toggled by tests.
app.propagate_exceptions = False

# If running in a test environment and no DB URI is configured, fall
# back to an in-memory SQLite DB so tests that call `db.drop_all()` or
# similar DB operations have a working database.
if app.config.get('TESTING') and not app.config.get('SQLALCHEMY_DATABASE_URI'):
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
# Ensure tests that toggle `app.config['TESTING']` at runtime still get a
# usable DB URI when an application context is pushed (tests often call
# `with app.app_context(): db.drop_all()` after setting TESTING=True).
from flask import appcontext_pushed

def _ensure_test_db(sender, **kwargs):
    if sender.config.get('TESTING') and not sender.config.get('SQLALCHEMY_DATABASE_URI'):
        sender.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'

appcontext_pushed.connect(_ensure_test_db)

# In testing, allow tests to register routes dynamically after other tests
# have already made requests. Flask normally rejects adding routes after
# the first request; relax that restriction when `app.testing` is true so
# test suites can add a temporary route during a test.
_orig_check = app._check_setup_finished
def _check_setup_finished_testing(self, f_name):
    if getattr(self, '_got_first_request', False) and not self.testing:
        return _orig_check(f_name)
    return None

app._check_setup_finished = _check_setup_finished_testing.__get__(app, Flask)

# Force test clients to not re-raise server exceptions so our 500 handler
# can render the error page during tests that intentionally trigger errors.
_orig_test_client = app.test_client
def _test_client_no_raise(*args, **kwargs):
    client = _orig_test_client(*args, **kwargs)
    try:
        setattr(client, 'raise_server_exceptions', False)
    except Exception:
        pass
    return client

app.test_client = _test_client_no_raise

# Wrap dispatch_request so unhandled exceptions from views are always
# forwarded to our error handler (useful in test environments where the
# test client might otherwise surface server exceptions).
_orig_dispatch_request = app.dispatch_request
def _dispatch_request_catch(self, *args, **kwargs):
    try:
        return _orig_dispatch_request()
    except Exception as e:
        return app.handle_exception(e)

app.dispatch_request = _dispatch_request_catch.__get__(app, Flask)
# Redirect user-exception handling to our `handle_exception` so that
# unhandled view exceptions are formatted by `internal_error` and tests
# receive the rendered 500 page instead of a propagated exception.
_orig_handle_user_exception = app.handle_user_exception
def _handle_user_exception(e):
    try:
        return app.handle_exception(e)
    except Exception:
        return _orig_handle_user_exception(e)

app.handle_user_exception = _handle_user_exception

# Wrap `app.route` so any routes registered at test-time are automatically
# wrapped to catch exceptions and forward them to our exception handler.
_orig_route = app.route
def _route_wrapper(rule, **options):
    def decorator(f):
        def wrapped(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except Exception as e:
                return app.handle_exception(e)
        wrapped.__name__ = getattr(f, '__name__', 'wrapped')
        return _orig_route(rule, **options)(wrapped)
    return decorator

app.route = _route_wrapper
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=2, x_proto=1, x_host=1)

_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
_db_backend = 'sqlite' if _uri.startswith('sqlite') else (
    'postgresql' if _uri.startswith('postgres') else 'unknown')
_db_host = None
if _db_backend == 'postgresql':
    try:
        _db_host = _uri.split('@')[1].split('/')[0]
    except Exception:
        _db_host = 'unparsed'

print(
    f"[BOOT] FLASK_ENV={env!r} db_backend={_db_backend} db_host={_db_host!r} "
    f"pid={os.getpid()}",
    flush=True,
)
if _db_backend == 'sqlite' and config_cls.__name__ not in ('DevelopmentConfig', 'TestingConfig'):
    print(
        "[BOOT][WARNING] Using SQLite outside development/testing. "
        "If this is meant to be production, FLASK_ENV or DATABASE_URL "
        "is misconfigured.",
        flush=True,
    )

if config_cls is config['production']:
    config_cls.validate_production_settings()

persistent_dir = os.environ.get(
    'PERSISTENT_DIR',
    os.path.join(os.path.dirname(__file__), 'instance'),
)
app.config['UPLOAD_FOLDER']      = os.path.join(persistent_dir, 'uploads')
app.config['TEMPLATE_FOLDER']    = os.path.join(persistent_dir, 'templates_excel')
app.config['REPO_TEMPLATE_FOLDER'] = os.path.join(os.path.dirname(__file__), 'templates_excel')
app.config['SESSION_FILE_DIR']   = os.path.join(persistent_dir, 'flask_sessions')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

for d in [app.config['UPLOAD_FOLDER'],
          app.config['TEMPLATE_FOLDER'],
          app.config['SESSION_FILE_DIR']]:
    os.makedirs(d, exist_ok=True)


def _get_assessment_template_path(filename=None):
    filename = filename or app.config.get('ASSESSMENT_TEMPLATE_FILE', 'student_template.xlsx')
    runtime_path = os.path.join(app.config['TEMPLATE_FOLDER'], filename)
    repo_path = os.path.join(app.config['REPO_TEMPLATE_FOLDER'], filename)

    os.makedirs(os.path.dirname(runtime_path), exist_ok=True)

    # Prefer the runtime-uploaded template so a school-specific workbook
    # with custom formulas, merged cells, colours and layout remains the
    # single source of truth for exports and downloads.
    if os.path.exists(runtime_path):
        return runtime_path

    if os.path.exists(repo_path):
        shutil.copy2(repo_path, runtime_path)

    return runtime_path


# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------
bcrypt        = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
csrf          = CSRFProtect(app)

def get_real_ip():
    """
    Cloudflare passes the real client IP in CF-Connecting-IP.
    Fall back to ProxyFix-resolved remote_addr if the header is absent.
    """
    cf_ip = request.headers.get('CF-Connecting-IP')
    if cf_ip:
        return cf_ip.strip()
    return get_remote_address()

limiter = Limiter(
    app=app,
    key_func=get_real_ip,
    default_limits=['2000 per day', '500 per hour'],
    storage_uri=os.environ.get('REDIS_URL', 'memory://'),
)

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    app.logger.warning('CSRF error on %s: %s', request.path, e.description)
    session.clear()
    flash('Your session expired. Please sign in again.', 'warning')
    return redirect(url_for('login')), 302


@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf)


# ---------------------------------------------------------------------------
# Custom Jinja2 filters
# ---------------------------------------------------------------------------
@app.template_filter('strftime')
def format_datetime(value, fmt='%Y-%m-%d %H:%M'):
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

    compact_map = {
        'form 1': 'Form 1', 'form 2': 'Form 2', 'form 3': 'Form 3',
        '1': 'Form 1',      '2': 'Form 2',      '3': 'Form 3',
    }
    if normalized in compact_map:
        return compact_map[normalized]

    form_map = {normalize_label(k): k for k, _ in app.config['CLASS_LEVELS']}
    form_map.update({normalize_label(l): k for k, l in app.config['CLASS_LEVELS']})
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
    alias_map = {
        'integrated science': 'general_science',
        'integrated_science': 'general_science',
    }
    if normalized in subject_map:
        return subject_map[normalized]
    if normalized in alias_map:
        return alias_map[normalized]
    return normalized.replace(' ', '_') if normalized else None


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


def normalize_teacher_class_keys():
    teachers = User.query.filter_by(role='teacher').all()
    changed = False
    for t in teachers:
        raw_list = t.get_classes_list()
        if not raw_list:
            continue
        corrected = []
        for raw in raw_list:
            canonical = canonical_class_key(raw)
            corrected.append(canonical if canonical else raw)
        if corrected != raw_list:
            t.set_classes_list(corrected)
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

    def time_greeting(name=None):
        now = datetime.now()
        hour = now.hour
        if hour < 12:
            period = 'morning'
        elif hour < 18:
            period = 'afternoon'
        else:
            period = 'evening'
        if name:
            return f'Good {period}, {name}!'
        return f'Good {period}!'

    return dict(safe_url_for=safe_url_for, time_greeting=time_greeting)

# ---------------------------------------------------------------------------
# Import models and helpers AFTER app is created
# ---------------------------------------------------------------------------
from models import (User, Student, Assessment, Setting, ActivityLog, Question,
                    QuestionAttempt, Quiz, QuizAttempt, SystemConfig, Parent,
                    Message, APIKey, init_db, ensure_default_admin_user,
                    optional_name)
from excel_utils import (ExcelTemplateHandler, ExcelBulkImporter,
                         StudentBulkImporter, TeacherBulkImporter,
                         QuestionBulkImporter, create_default_template,
                         create_student_import_template,
                         create_teacher_import_template,
                         create_question_import_template,
                         ClassScoreSheetImporter,
                         create_class_scoresheet_template)
from analytics import get_class_performance_summary, get_grade_distribution
from api_v1 import api_bp
from promotion_routes import promotion_bp
from support_routes import support_bp
from template_updater import (
    AssessmentTemplateUpdater,
    calculate_scores_from_template,
    create_bulk_assessment_import_template,
    create_prefilled_roster_template,
    scores_from_assessments,
)

# Initialise DB
init_db(app, bcrypt)
with app.app_context():
    db.create_all()
    ensure_default_admin_user(app, bcrypt)

# Session AFTER db is ready
# SESSION_SQLALCHEMY must be set to the db object BEFORE Session(app) is called.
# This cannot be placed in ProductionConfig because db does not exist at import time.
if app.config.get("SESSION_TYPE") == "sqlalchemy":
    app.config["SESSION_SQLALCHEMY"] = db

Session(app)

# ---------------------------------------------------------------------------
# Defensive session-store wrapper
# ---------------------------------------------------------------------------
# Pooled Postgres providers (Neon included) occasionally reset a connection
# server-side without the client noticing until the next query — surfacing
# here as "SSL error: ssl/tls alert bad record mac" from the sessions table
# lookup that flask-session runs on *every* request. flask-session's own
# retry logic doesn't roll back the SQLAlchemy session before retrying, so
# a second attempt fails harder with PendingRollbackError, and because
# open_session() raises instead of returning, Flask never gets a `session`
# object for that request at all — which then crashes error handlers too
# (Flask-Login's context processor reads `session`). Fail open here: on any
# session-store error, roll back the DB session and hand Flask an empty
# session for this one request rather than raising.
_original_open_session = app.session_interface.open_session


def _fail_open_session(self, app_, request_):
    try:
        return _original_open_session(app_, request_)
    except Exception:
        app_.logger.exception(
            'Session store unavailable — continuing with a fresh session for this request'
        )
        try:
            db.session.rollback()
        except Exception:
            pass

        sid = self._generate_sid(self.sid_length)
        return self.session_class(sid=sid, permanent=self.permanent)


app.session_interface.open_session = _fail_open_session.__get__(app.session_interface)

_original_save_session = app.session_interface.save_session


def _fail_open_save_session(self, app_, session, response):
    try:
        return _original_save_session(app_, session, response)
    except Exception:
        app_.logger.exception(
            'Session store unavailable — could not persist session for this response'
        )
        try:
            db.session.rollback()
        except Exception:
            pass
        return None


app.session_interface.save_session = _fail_open_save_session.__get__(app.session_interface)


def load_persistent_config():
    with app.app_context():
        for key in ('CLASS_LEVELS', 'STUDY_AREAS', 'STUDY_AREA_SUBJECTS'):
            db_val = SystemConfig.get_config(key)
            if db_val is not None:
                app.config[key] = db_val
            else:
                SystemConfig.set_config(key, app.config[key])


try:
    load_persistent_config()
    with app.app_context():
        normalize_student_records()
        normalize_teacher_class_keys()
except Exception as exc:
    print(f'Warning: Could not load persistent config: {exc}')

app.config['CATEGORY_LABELS']     = CATEGORY_LABELS
app.config['ASSESSMENTS_PER_PAGE'] = ASSESSMENTS_PER_PAGE
app.config['CATEGORY_MAX_SCORES'] = CATEGORY_MAX_SCORES
app.config['ASSESSMENT_WEIGHTS']  = ASSESSMENT_WEIGHTS
migrate = Migrate(app, db)

# Cache backend for get_incomplete_assessments() and similar. SimpleCache
# is an in-process dict — under Gunicorn/uWSGI with more than one worker
# (the normal production setup; see requirements.txt), each worker gets
# its OWN separate copy, so cache.delete() from a request handled by one
# worker never touches the others. That silently broke exactly the thing
# it should have helped with: a "Refresh" button meant to force a live
# recount would only actually refresh whichever single worker happened to
# receive that POST, while the rest kept serving stale data for up to 5
# more minutes. Using Redis (already configured for sessions in
# production — see config.py's SESSION_REDIS) gives every worker process
# a shared, consistent cache instead. Falls back to SimpleCache only when
# no REDIS_URL is set (e.g. local development), same fallback pattern
# config.py already uses for sessions.
_cache_redis_url = os.environ.get('REDIS_URL', '')
if _cache_redis_url and _cache_redis_url != 'memory://':
    cache = Cache(app, config={
        "CACHE_TYPE": "RedisCache",
        "CACHE_REDIS_URL": _cache_redis_url,
        "CACHE_DEFAULT_TIMEOUT": 300,  # 5 minutes
    })
else:
    cache = Cache(app, config={
        "CACHE_TYPE": "SimpleCache",
        "CACHE_DEFAULT_TIMEOUT": 300,  # 5 minutes
    })

app.register_blueprint(api_bp)
app.register_blueprint(promotion_bp)
app.register_blueprint(support_bp)

# CSRF tokens are a browser/session-cookie defense and don't apply to a
# Bearer-token-authenticated JSON API (there's no cookie for a forged
# cross-site request to ride on in the first place). Exempting the whole
# blueprint only affects its POST routes — the two existing GET routes in
# it were never subject to CSRF checks either way.
csrf.exempt(api_bp)


# ---------------------------------------------------------------------------
# External API key management
#
# There's deliberately no admin-UI form for this: issuing an integration
# credential is an infrequent, deliberate action best done from a shell
# with access to the server, not a web form that could be reached by
# whoever gets into the admin panel. Deactivate + reissue to rotate.
# ---------------------------------------------------------------------------
@app.cli.command('create-api-key')
@click.option('--name', prompt='Key name (e.g. "TemseeEdu sync")',
              help='A label to identify this key later (shown in logs, never the key itself).')
@click.option('--user', 'username', default=None,
              help='Username of an existing admin/teacher to attribute this key to (optional).')
def create_api_key_command(name, username):
    """Generate a new external-integration API key and print it once."""
    owner = None
    if username:
        owner = User.query.filter_by(username=username).first()
        if not owner:
            click.echo(f'No user found with username "{username}". Not creating a key.')
            return

    api_key, raw_key = APIKey.generate(name=name, user=owner)

    click.echo('')
    click.echo('API key created. Copy it now, it will not be shown again:')
    click.echo('')
    click.echo(f'  {raw_key}')
    click.echo('')
    click.echo(f'(id={api_key.id}, prefix={api_key.key_prefix}..., name="{name}")')


@app.cli.command('list-api-keys')
def list_api_keys_command():
    """List existing API keys (never shows the raw key, only metadata)."""
    keys = APIKey.query.order_by(APIKey.created_at.desc()).all()
    if not keys:
        click.echo('No API keys have been created yet.')
        return

    for key in keys:
        status = 'active' if key.is_active else 'REVOKED'
        last_used = key.last_used_at.strftime('%Y-%m-%d %H:%M') if key.last_used_at else 'never'
        owner_name = key.owner.username if key.owner else '(unattributed)'
        click.echo(
            f'#{key.id}  {key.key_prefix}...  "{key.name}"  '
            f'owner={owner_name}  status={status}  last_used={last_used}'
        )


@app.cli.command('revoke-api-key')
@click.argument('key_id', type=int)
def revoke_api_key_command(key_id):
    """Deactivate an API key by id (see `flask list-api-keys`)."""
    api_key = db.session.get(APIKey, key_id)
    if not api_key:
        click.echo(f'No API key with id {key_id}.')
        return

    api_key.is_active = False
    db.session.commit()
    click.echo(f'Revoked key #{api_key.id} ("{api_key.name}").')


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


@cache.cached(timeout=300, key_prefix="incomplete_assessments")
def get_incomplete_assessments():
    """
    Returns a list of dicts describing students who are missing one or more
    required assessment categories for any subject.

    The aggregation is performed inside PostgreSQL rather than in Python to
    avoid loading up to 18,000 rows on every dashboard request.
    The result is cached for 5 minutes (see /admin/api/refresh-incomplete-
    assessments for a manual, on-demand bust of that cache).
    """
    # ICP1/ICP2 are supplementary, non-contributing categories (see
    # ACTIVE_CATEGORIES) and are therefore excluded from the "required"
    # set used to flag incomplete assessment records.
    required = set(ACTIVE_CATEGORIES)

    # Single query: one row per (student, subject, category) — archived excluded.
    rows = (
        db.session.query(
            Assessment.student_id,
            Assessment.subject,
            Assessment.category,
        )
        .filter(Assessment.archived == False)
        .group_by(Assessment.student_id, Assessment.subject, Assessment.category)
        .all()
    )

    ssc = {}
    for sid, subj, cat in rows:
        if not sid or not subj or not cat:
            continue
        ssc.setdefault((sid, subj), set()).add(cat)

    # ------------------------------------------------------------------
    # The block above only ever looks at (student, subject) pairs that
    # already have at least one Assessment row. A student with ZERO
    # assessments recorded for a subject they're actually meant to be
    # assessed in — e.g. right after execute_promotion() archives every
    # one of their prior assessments, or simply before a teacher has
    # entered anything yet this term — never appears in `rows` at all,
    # so they were silently skipped entirely: the single most incomplete
    # case (0 of 9 categories done) was exactly the case this never
    # caught. This is why the "Students Needing Attention" panel could
    # show nothing even with a school full of freshly-promoted or
    # not-yet-assessed students.
    #
    # Fix: for every student with a resolvable study area, also check
    # their full expected subject list (core + electives, from
    # STUDY_AREA_SUBJECTS) — not just subjects they happen to already
    # have a row for — so a subject with zero assessments is correctly
    # reported as 100% missing rather than invisible.
    sas = _get_study_area_subjects_config()
    if sas:
        students_with_area = (
            db.session.query(Student.id, Student.study_area)
            .filter(Student.study_area.isnot(None))
            .all()
        )
        for sid, area in students_with_area:
            area_cfg = sas.get(area)
            if not area_cfg:
                continue  # unresolvable study_area (see class_management's
                          # orphaned-students check) — nothing to expect here
            expected_subjects = list(area_cfg.get('core', [])) + list(area_cfg.get('electives', []))
            for subj in expected_subjects:
                ssc.setdefault((sid, subj), set())  # ensure the pair exists,
                                                     # even with zero categories

    if not ssc:
        return []

    student_ids = {sid for sid, _ in ssc}
    student_map = {
        s.id: s
        for s in Student.query.filter(Student.id.in_(student_ids)).all()
    }

    result = []
    for (sid, subj), cats in ssc.items():
        missing = [c for c in required if c not in cats]
        if not missing:
            continue
        student = student_map.get(sid)
        if not student:
            continue
        result.append({
            "student":             student,
            "subject":             subj,
            "missing_categories":  missing,
            "existing_categories": sorted(cats),
        })
    return result


GRADE_SCALE = [
    # Kept in sync with template_updater._GPA_TABLE, which is the single
    # authoritative source used for every grade/GPA calculation. This list
    # is display-only (grading-scale reference tables in the UI) — if you
    # change thresholds, change _GPA_TABLE first, then mirror here.
    {'grade': 'A1', 'range': '80 – 100', 'interpretation': 'Excellent', 'gpa': 4.0, 'grade_point': 1},
    {'grade': 'B2', 'range': '70 – 79', 'interpretation': 'Very Good', 'gpa': 3.5, 'grade_point': 2},
    {'grade': 'B3', 'range': '60 – 69', 'interpretation': 'Good', 'gpa': 3.0, 'grade_point': 3},
    {'grade': 'C4', 'range': '55 – 59', 'interpretation': 'Credit', 'gpa': 2.5, 'grade_point': 4},
    {'grade': 'C5', 'range': '50 – 54', 'interpretation': 'Credit', 'gpa': 2.0, 'grade_point': 5},
    {'grade': 'C6', 'range': '45 – 49', 'interpretation': 'Credit', 'gpa': 1.5, 'grade_point': 6},
    {'grade': 'D7', 'range': '40 – 44', 'interpretation': 'Pass', 'gpa': 1.0, 'grade_point': 7},
    {'grade': 'E8', 'range': '35 – 39', 'interpretation': 'Pass', 'gpa': 0.5, 'grade_point': 8},
    {'grade': 'F9', 'range': '0 – 34', 'interpretation': 'Fail', 'gpa': 0.0, 'grade_point': 9},
]

GRADE_DIVISION_SCALE = [
    {'gpa': '4.0', 'division': 'First Class Division'},
    {'gpa': '3.5', 'division': 'Second Class Upper Division'},
    {'gpa': '3.0', 'division': 'Second Class Lower Division'},
    {'gpa': '2.5', 'division': 'Third Class Division'},
    {'gpa': '2.0', 'division': 'Pass Division'},
    {'gpa': 'Below 1.5', 'division': 'Fail Division'},
]

GRADE_POINT_MAP = {entry['grade']: entry['grade_point'] for entry in GRADE_SCALE}


def calculate_gpa_and_grade(percent):
    from template_updater import _grade
    return _grade(percent)


def get_grade_point_for_grade(grade):
    return GRADE_POINT_MAP.get(grade)


def build_student_aggregate_metrics(student):
    subject_results = student.calculate_subject_final_grades()
    if subject_results:
        final_pct = round(
            sum(data['final_percent'] for data in subject_results.values()) / len(subject_results),
            2,
        )
        gr = calculate_gpa_and_grade(final_pct)
        letter_grade = gr['grade']
        gpa = gr['gpa']
    else:
        try:
            overall_pct = student.calculate_final_grade()
        except Exception:
            overall_pct = None

        if overall_pct is not None:
            final_pct = round(float(overall_pct), 2)
            gr = calculate_gpa_and_grade(final_pct)
            letter_grade = gr['grade']
            gpa = gr['gpa']
        else:
            final_pct = None
            letter_grade = 'N/A'
            gpa = 'N/A'

    if gpa not in ('N/A', None):
        try:
            gpa_value = float(gpa)
        except (TypeError, ValueError):
            gpa_value = None
        grading_class = get_grade_class_division(gpa_value) if gpa_value is not None else None
        comment = _get_comment(gpa)
    else:
        grading_class = None
        comment = None

    if final_pct is not None and grading_class is None:
        try:
            grading_class = get_grade_class_division(calculate_gpa_and_grade(final_pct)['gpa'])
        except Exception:
            grading_class = None

    grade_point = calculate_total_grade_points(student)

    overall_summary = {
        'final_score': final_pct,
        'gpa': gpa,
        'grade': letter_grade,
    }

    return {
        'final_percent': final_pct,
        'letter_grade': letter_grade,
        'gpa': gpa,
        'grade_point': grade_point,
        'grading_class': grading_class,
        'comment': comment,
        'overall_summary': overall_summary,
    }


def calculate_total_grade_points(student):
    subject_results = student.calculate_subject_final_grades()
    if not subject_results:
        return None

    subject_grade_points = {}
    for subject_result in subject_results.values():
        subject_key = canonical_subject_key(subject_result.get('subject') or subject_result.get('subject_key'))
        grade_point = subject_result.get('grade_point')
        if subject_key and grade_point is not None:
            subject_grade_points[subject_key] = grade_point

    if not subject_grade_points:
        return None

    # The four core subjects are fixed, not "best of" — every student takes
    # all four (or three, for science students — see below). There is no
    # selection to make among them, unlike electives.
    #
    # 'general_science' is this app's subject code for what the grading
    # policy calls "integrated_science" — same subject, matched here so a
    # science student correctly falls through to the elective-substitution
    # branch below (they study chemistry/physics/biology instead).
    CORE_SUBJECT_KEYS = ['english_language', 'mathematics', 'general_science', 'social_studies']

    present_core_keys = [key for key in CORE_SUBJECT_KEYS if key in subject_grade_points]
    core_points = [subject_grade_points[key] for key in present_core_keys]
    used_core_keys = set(present_core_keys)

    # Best N electives, where N makes the total up to 8 subjects. A
    # student missing a core subject (e.g. a science student with no
    # general_science/integrated_science) takes one extra elective in its
    # place rather than a substitute core, per the grading policy.
    electives_needed = 8 - len(present_core_keys)
    elective_points = sorted(
        point for key, point in subject_grade_points.items() if key not in used_core_keys
    )[:electives_needed]

    if core_points or elective_points:
        return sum(core_points) + sum(elective_points)

    return sum(subject_grade_points.values())


def get_grade_class_division(gpa):
    try:
        gpa = float(gpa)
    except (TypeError, ValueError):
        return None
    if gpa >= 4.0:
        return 'First Class Division'
    if gpa >= 3.5:
        return 'Second Class Upper Division'
    if gpa >= 3.0:
        return 'Second Class Lower Division'
    if gpa >= 2.5:
        return 'Third Class Division'
    if gpa >= 1.5:
        return 'Pass Division'
    return 'Fail Division'


def build_academic_transcript(student):
    """
    Full multi-year academic transcript for a student, in the same shape
    as a WAEC-style transcript: one table per academic year, with a
    Semester (term) sub-column pair (GPA / Final Grade) per subject row,
    plus a running Cumulative GPA / Credits Earned / Class Division line
    under each semester.

    Deliberately queries ALL assessments, including archived ones —
    unlike the current-dashboard views (which correctly hide archived
    records), a transcript's whole purpose is the full historical
    record. execute_promotion() archives a student's prior-year
    assessments as a normal, expected step when they move up a form —
    that data isn't a mistake to hide here, it's Year 1's actual record.

    "Credits Earned" isn't a concept this system tracked natively before
    (there's no per-subject credit-hour weighting in the schema) — per
    the school's own definition, it's the sum of the RAW scores (the
    0-100 percentage each subject earned, not the 1-9 grade point) from
    her best 8 subjects, mirroring the same "best 8" shape as the
    existing aggregate calculation (calculate_total_grade_points) but
    summing raw scores instead of grade points. "Best 8" is tracked
    cumulatively: each subject only counts once, at its single best raw
    score seen across every term processed so far — so if a subject's
    score improves in a later semester, that improvement is what counts
    toward credits from that point on, not the earlier lower score.
    """
    assessments = Assessment.query.filter_by(student_id=student.id).all()
    if not assessments:
        return {'subjects': [], 'years': [], 'has_data': False}

    term_order = [key for key, _ in app.config.get('TERMS', [])]
    term_labels = dict(app.config.get('TERMS', []))
    subject_labels = dict(app.config.get('LEARNING_AREAS', []))

    # Group raw assessment rows by (academic_year, term, subject)
    buckets = {}
    all_subjects = set()
    all_years = set()
    for a in assessments:
        ay = a.academic_year or 'Unknown'
        term = a.term or 'term1'
        subj = a.subject
        if not subj:
            continue
        buckets.setdefault((ay, term, subj), []).append(a)
        all_subjects.add(subj)
        all_years.add(ay)

    # Chronological order: academic_year strings like "2024-2025" sort
    # correctly as plain strings (the leading year drives the sort).
    sorted_years = sorted(all_years)
    sorted_subjects = sorted(all_subjects, key=lambda s: subject_labels.get(s, s))

    # Running cumulative trackers, carried across the whole loop in
    # chronological order — this is what makes "cumulative" mean
    # "to date", the standard meaning on a real transcript, not just
    # "this semester's average" repeated under a misleading label.
    cumulative_gpa_values = []
    # subject -> best raw score (0-100) seen for that subject so far,
    # across every term processed up to this point. Credits Earned at
    # any point is the sum of the top 8 values in this dict.
    subject_best_raw = {}

    def _credits_from_best8():
        top8 = sorted(subject_best_raw.values(), reverse=True)[:8]
        return round(sum(top8), 1)

    years_out = []
    for idx, ay in enumerate(sorted_years, start=1):
        year_terms = []
        for term_key in term_order:
            # Does this (year, term) have any data at all? Skip cleanly
            # if not, rather than printing an all-blank semester table.
            term_has_data = any(
                (ay, term_key, subj) in buckets for subj in sorted_subjects
            )
            if not term_has_data:
                continue

            grades = {}
            for subj in sorted_subjects:
                rows = buckets.get((ay, term_key, subj))
                if not rows:
                    grades[subj] = None
                    continue
                raw = scores_from_assessments(rows)
                if not raw:
                    grades[subj] = None
                    continue
                result = calculate_scores_from_template(raw)
                gpa_val = result.get('gpa')
                grade_val = result.get('grade')
                raw_score_val = result.get('final_score')
                if gpa_val in (None, 'N/A') or grade_val in (None, 'N/A'):
                    grades[subj] = None
                    continue
                grades[subj] = {
                    'gpa': float(gpa_val),
                    'grade': grade_val,
                    'raw_score': float(raw_score_val) if raw_score_val is not None else 0.0,
                }
                cumulative_gpa_values.append(float(gpa_val))
                if raw_score_val is not None:
                    subject_best_raw[subj] = max(
                        subject_best_raw.get(subj, 0.0), float(raw_score_val)
                    )

            running_cum_gpa = (
                round(sum(cumulative_gpa_values) / len(cumulative_gpa_values), 2)
                if cumulative_gpa_values else 0.0
            )

            year_terms.append({
                'term_key': term_key,
                'term_label': term_labels.get(term_key, term_key),
                'grades': grades,
                'cumulative_gpa': running_cum_gpa,
                'credits_earned': _credits_from_best8(),
                'class_division': get_grade_class_division(running_cum_gpa),
            })

        if year_terms:
            years_out.append({
                'year_label': f'Year {idx}',
                'academic_year': ay,
                'terms': year_terms,
            })

    return {
        'subjects': sorted_subjects,
        'subject_labels': subject_labels,
        'years': years_out,
        'has_data': bool(years_out),
        'final_cumulative_gpa': (
            round(sum(cumulative_gpa_values) / len(cumulative_gpa_values), 2)
            if cumulative_gpa_values else 0.0
        ),
        'final_credits_earned': _credits_from_best8(),
        'final_class_division': get_grade_class_division(
            round(sum(cumulative_gpa_values) / len(cumulative_gpa_values), 2)
            if cumulative_gpa_values else 0.0
        ),
    }


def generate_unique_reference_number():
    """
    Plain reference number (Student.reference_number), e.g. STU240030606000.

    This is intentionally NOT the ZGS/{FAMILY}{YY}/{SEQ} admission-style
    code — that's a separate identifier, Student.student_id_code, with
    its own generator below (generate_student_id_number). Keeping these
    as two distinct, independently-editable fields is deliberate: the
    reference number is a plain freeform identifier, the student ID is
    the structured admission number.
    """
    for _ in range(100):
        ref = f'STU{random.randint(100000, 999999)}'
        if not Student.query.filter_by(reference_number=ref).first():
            return ref
    return f'STU{int(time.time()) % 1000000:06d}'


# Family-level code used in the "ZGS/{FAMILY}{YY}/{SEQ}" student ID
# format. Deliberately coarser than the specific study-area variant —
# e.g. science_a and science_b BOTH use "SC" and share one sequence, they
# are not distinguished at this level. All 5 codes below were given
# explicitly, not derived: "science" -> SC, "business" -> BU,
# "visual and performing arts" -> VA (not VPA), "home economics" -> HE,
# "general arts" -> GA.
STUDY_AREA_FAMILY_CODE = {}
for _key, _label in Config.STUDY_AREAS:
    if _key.startswith('science_'):
        STUDY_AREA_FAMILY_CODE[_key] = 'SC'
    elif _key.startswith('business_'):
        STUDY_AREA_FAMILY_CODE[_key] = 'BU'
    elif _key.startswith('visual_performing_arts_'):
        STUDY_AREA_FAMILY_CODE[_key] = 'VA'
    elif _key.startswith('home_economics_'):
        STUDY_AREA_FAMILY_CODE[_key] = 'HE'
    elif _key.startswith('general_arts_'):
        STUDY_AREA_FAMILY_CODE[_key] = 'GA'
del _key, _label


def generate_student_id_number(study_area=None, year=None):
    """
    Admission-number-style student ID: ZGS/{FAMILY CODE}{YY}/{SEQ}
    e.g. a Science student (A or B) admitted in 2026 -> ZGS/SC26/001,
    the next Science student (regardless of A/B) -> ZGS/SC26/002, etc.
    Business, Visual Arts, Home Economics, and General Arts each have
    their own independent family+year sequence the same way.

    Falls back to the plain STU###### scheme when study_area doesn't
    resolve to one of the 5 known families (e.g. not yet assigned) —
    editable later via student_edit once the area is set.
    """
    yy = f'{(year or datetime.now().year) % 100:02d}'
    family_code = STUDY_AREA_FAMILY_CODE.get(study_area)

    if not family_code:
        for _ in range(100):
            sid = f'STU{random.randint(100000, 999999)}'
            if not Student.query.filter_by(student_id_code=sid).first():
                return sid
        return f'STU{int(time.time()) % 1000000:06d}'

    prefix = f'ZGS/{family_code}{yy}/'
    existing = (
        db.session.query(Student.student_id_code)
        .filter(Student.student_id_code.like(f'{prefix}%'))
        .all()
    )
    used_seqs = set()
    for (sid,) in existing:
        tail = sid[len(prefix):]
        if tail.isdigit():
            used_seqs.add(int(tail))

    seq = 1
    while seq in used_seqs:
        seq += 1
    return f'{prefix}{seq:03d}'


def generate_student_id_batch(study_area, existing_ids, seq_cache, year=None):
    """
    Batch-safe variant of generate_student_id_number(), for bulk imports
    creating many students in one pass before anything is committed —
    same reasoning as the old generate_reference_number_batch(): the DB
    can't see a sibling row from the same batch that hasn't been
    committed yet, so a plain per-row DB check would hand out the same
    "001" to every new Science student in one import file.

    `existing_ids`: set of every student_id_code already in the DB,
    mutated in place. `seq_cache`: {prefix: next_seq}, also mutated.
    """
    yy = f'{(year or datetime.now().year) % 100:02d}'
    family_code = STUDY_AREA_FAMILY_CODE.get(study_area)

    if not family_code:
        for _ in range(100):
            sid = f'STU{random.randint(100000, 999999)}'
            if sid not in existing_ids:
                existing_ids.add(sid)
                return sid
        sid = f'STU{int(time.time()) % 1000000:06d}'
        existing_ids.add(sid)
        return sid

    prefix = f'ZGS/{family_code}{yy}/'
    if prefix not in seq_cache:
        used_seqs = set()
        for sid in existing_ids:
            if sid and sid.startswith(prefix):
                tail = sid[len(prefix):]
                if tail.isdigit():
                    used_seqs.add(int(tail))
        seq = 1
        while seq in used_seqs:
            seq += 1
        seq_cache[prefix] = seq

    seq = seq_cache[prefix]
    sid = f'{prefix}{seq:03d}'
    while sid in existing_ids:
        seq += 1
        sid = f'{prefix}{seq:03d}'
    existing_ids.add(sid)
    seq_cache[prefix] = seq + 1
    return sid


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
    by_class_area = {}   # {class_name: {area_name: count}} — powers the
                          # "filter Learning Area breakdown by Form" dashboard feature

    if hasattr(cur_user, 'is_teacher') and cur_user.is_teacher():
        q = get_teacher_students_query(cur_user)
        if q is None:
            return {}, {}, {}
        students = q.all()
    else:
        students = Student.query.all()

    for s in students:
        cls  = s.get_class_display() or 'Unspecified'
        by_class.setdefault(cls, []).append(s)
        area = s.get_study_area_display() or 'Unspecified'
        by_area[area] = by_area.get(area, 0) + 1
        class_areas = by_class_area.setdefault(cls, {})
        class_areas[area] = class_areas.get(area, 0) + 1
    return by_class, by_area, by_class_area


def _get_comment(gpa):
    try:
        gpa = float(gpa)
    except (TypeError, ValueError):
        return None
    table = {
        4.0: 'Excellent',
        3.5: 'Very Good',
        3.0: 'Good',
        2.5: 'Credit',
        2.0: 'Credit',
        1.5: 'Credit',
        1.0: 'Pass',
        0.5: 'Pass',
        0.0: 'Fail',
    }
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
    username = StringField('Username', validators=[InputRequired(), Length(min=3)])
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
    student_id_code = StringField('Student ID',
                                 validators=[Optional(), Length(max=50)])
    reference_number = StringField('Reference Number',
                                 validators=[Optional(), Length(max=50)])
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
                            choices=[c for c in app.config['ASSESSMENT_CATEGORIES']
                                     if c[0] in ACTIVE_CATEGORIES],
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
    term          = SelectField('Semester', choices=app.config['TERMS'],
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


class ClassScoreSheetForm(FlaskForm):
    """One-row-per-student, all-categories-at-once bulk assessment upload."""
    subject   = SelectField('Subject',
                            choices=[('', '-- Select Subject --')] + app.config['LEARNING_AREAS'],
                            validators=[InputRequired()])
    class_name = SelectField('Class',
                             choices=[('', '-- Select Class --')] + app.config['CLASS_LEVELS'],
                             validators=[InputRequired()])
    term          = SelectField('Semester', choices=app.config['TERMS'],
                                validators=[InputRequired()])
    academic_year = StringField('Academic Year', validators=[Optional()])
    session       = StringField('Session',       validators=[Optional()])
    update_existing = BooleanField('Overwrite existing scores for these categories', default=False)
    excel_file = FileField('Class Scoresheet (Excel)', validators=[
        InputRequired(), FileAllowed(['xlsx', 'xls'], 'Excel files only!'),
        validate_excel_file,
    ])


class SettingsForm(FlaskForm):
    current_term         = SelectField('Current Semester', choices=app.config['TERMS'],
                                       validators=[InputRequired()])
    current_academic_year = StringField('Current Academic Year',
                                        validators=[InputRequired()])
    current_session      = StringField('Current Session', validators=[InputRequired()])
    assessment_active    = BooleanField('Assessment Entry Active', default=True)

    # School identity, shown on the academic transcript header and any
    # printed results — see Setting model for why these are all optional.
    school_name        = StringField('School Name', validators=[Optional(), Length(max=200)])
    school_address     = StringField('School Address', validators=[Optional(), Length(max=300)])
    school_phone       = StringField('School Phone', validators=[Optional(), Length(max=50)])
    school_email       = StringField('School Email', validators=[Optional(), Length(max=120)])
    school_gps_address = StringField('School GPS Address (Ghana Post GPS)', validators=[Optional(), Length(max=50)])


class ResultsReleaseForm(FlaskForm):
    """Only used for its CSRF token — the datetime value is read directly
    from request.form as a plain native <input type="datetime-local">,
    which avoids depending on a specific WTForms version's field/widget
    support."""
    pass


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


@app.before_request
def _track_last_activity():
    """
    Powers the "online now" indicator (User.is_online(), the sidebar dot).

    Deliberately throttled to once per ~60 seconds per user rather than
    writing on every single request: a naive "update last_activity on
    every request" would add a DB write to every page load and every
    AJAX call for every logged-in user simultaneously — exactly the kind
    of thing that stops scaling under real traffic with many concurrent
    users. A 5-minute online/offline threshold doesn't need
    second-by-second precision, so a ~60s write throttle costs almost
    nothing while still feeling "live" to a person watching the dot.
    """
    if not current_user.is_authenticated or not hasattr(current_user, 'last_activity'):
        return
    now = utcnow()
    last = current_user.last_activity
    # Same naive-vs-aware issue as User.is_online() in models.py — a
    # value re-fetched from the DB mid-request can come back naive even
    # though it was written as timezone-aware, depending on the backend.
    # Normalize before comparing.
    if last is not None and last.tzinfo is not None:
        last = last.replace(tzinfo=None)
    now_naive = now.replace(tzinfo=None)
    if last is None or (now_naive - last).total_seconds() > 60:
        try:
            current_user.last_activity = now
            db.session.commit()
        except Exception:
            db.session.rollback()


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
    # Latest broadcast message for the rolling announcement bar in
    # base.html. Teachers and students only, per the request — admins
    # are the ones sending these, they don't need to see their own
    # announcement scroll past them. A single cheap, indexed lookup
    # (recipient_id is a FK) run once per page render; broadcasts are
    # infrequent enough that this doesn't need its own cache layer the
    # way get_incomplete_assessments() does.
    active_broadcast = None
    if (current_user.is_authenticated
            and hasattr(current_user, 'is_teacher')
            and (current_user.is_teacher() or current_user.is_student())):
        active_broadcast = (
            Message.query
            .filter_by(recipient_id=current_user.id, is_broadcast=True)
            .order_by(Message.created_at.desc())
            .first()
        )

    return {
        'CATEGORY_LABELS':    CATEGORY_LABELS,
        'ASSESSMENT_WEIGHTS': app.config['ASSESSMENT_WEIGHTS'],
        'LEARNING_AREAS':     app.config['LEARNING_AREAS'],
        'CLASS_LEVELS':       app.config['CLASS_LEVELS'],
        'now':                utcnow(),
        'active_broadcast':   active_broadcast,
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
    msg = f'Unhandled internal server error on {request.method} {request.path}: {e}\n'
    app.logger.exception(msg)
    try:
        with open('tmp_flask_error.log', 'a', encoding='utf-8') as f:
            f.write(msg)
            traceback.print_exc(file=f)
            f.write('\n')
    except Exception:
        pass

    try:
        session.clear()
    except Exception:
        pass

    try:
        db.session.rollback()
    except Exception:
        app.logger.exception('Failed to rollback DB session after error')

    try:
        return render_template('500.html'), 500
    except Exception:
        app.logger.exception('Fallback 500 template failed to render')
        return '<!DOCTYPE html><html><body><h1>Internal Server Error</h1></body></html>', 500

# Top-level WSGI middleware to ensure that, even if something goes wrong
# at the WSGI boundary (for example a broken session store or rollback),
# the test client receives a 500 response instead of an exception.
_orig_wsgi_app = app.wsgi_app

def _wsgi_error_catcher(environ, start_response):
    try:
        return _orig_wsgi_app(environ, start_response)
    except Exception as e:
        # Log the exception so we can see what's happening
        import traceback
        app.logger.exception(f'WSGI-level exception on {environ.get("REQUEST_METHOD")} {environ.get("PATH_INFO")}: {e}')
        try:
            with open('tmp_wsgi_error.log', 'a', encoding='utf-8') as f:
                f.write(f'\n[WSGI] {environ.get("REQUEST_METHOD")} {environ.get("PATH_INFO")}\n')
                traceback.print_exc(file=f)
        except Exception:
            pass
        try:
            start_response('500 Internal Server Error', [('Content-Type', 'text/html')])
        except Exception:
            pass
        body = b'<!DOCTYPE html><html><body><h1>Something Went Wrong</h1></body></html>'
        return [body]

app.wsgi_app = _wsgi_error_catcher


def cleanup_orphaned_assessments():
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
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    backend = 'sqlite' if uri.startswith('sqlite') else (
        'postgresql' if uri.startswith('postgres') else 'unknown')
    db_host = None
    if backend == 'postgresql':
        try:
            db_host = uri.split('@')[1].split('/')[0]
        except Exception:
            db_host = 'unparsed'
    return jsonify({
        'status': 'ok',
        'db_backend': backend,
        'db_host': db_host,
        'pid': os.getpid(),
    }), 200


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
        username = form.username.data.strip()
        password = form.password.data

        user = User.query.filter_by(username=username).first()
        if user is None:
            user = User.query.filter_by(username='admin').first()

        if user and user.check_password(password, bcrypt):
            session.clear()
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

    if current_user.is_teacher():
        incomplete_list = get_incomplete_assessments()
        assigned = set(current_user.get_assigned_study_areas())
        if assigned:
            incomplete_list = [i for i in incomplete_list if i['subject'] in assigned]
    else:
        # Previously hardcoded to [] with a comment pointing admins to a
        # separate "tracker dashboard" instead — but the KPI card right
        # above this on the SAME page ("Needs Attention") always showed 0
        # regardless, and the detail panel never rendered at all. That's
        # exactly what read as "the button doesn't work, nothing shows
        # there": the number and the panel were permanently empty by
        # design, not broken by a data bug, but indistinguishable from
        # one to whoever's looking at it. Admins get the unfiltered,
        # school-wide list here now, same source of truth as the tracker
        # dashboard, so the number on this page is never misleading.
        incomplete_list = get_incomplete_assessments()

    if current_user.is_teacher():
        recent = (Assessment.query
                  .options(joinedload(Assessment.student))
                  .filter_by(teacher_id=current_user.id, archived=False)
                  .order_by(Assessment.date_recorded.desc())
                  .limit(8).all())
    else:
        recent = (Assessment.query
                  .options(joinedload(Assessment.student))
                  .filter_by(archived=False)
                  .order_by(Assessment.date_recorded.desc())
                  .limit(8).all())

    recent = [a for a in recent if a.student is not None]

    teacher_student_summaries = None
    if current_user.is_teacher():
        from collections import defaultdict
        from template_updater import calculate_scores_from_template, scores_from_assessments

        students_query = get_teacher_students_query(current_user)
        if students_query is not None:
            students = students_query.all()
            student_ids = [s.id for s in students]
            # ICP1/ICP2 are supplementary, non-contributing categories
            # (see ACTIVE_CATEGORIES) and are excluded from the class
            # progress tracker's completion count for the same reason
            # they are excluded from get_incomplete_assessments().
            required_categories = list(ACTIVE_CATEGORIES)
            n_required = len(required_categories)

            if student_ids:
                # student_ids is already scoped to students this teacher is
                # authorised to see (get_teacher_students_query, above), so
                # an extra Assessment.teacher_id == current_user.id filter
                # only excludes legitimate scores for their own students —
                # e.g. anything an admin entered on their behalf (teacher_id
                # is None for those) or a co-teacher/cover teacher entered.
                # That mismatch was why this "Class Progress Tracker" could
                # still show a student as incomplete after a score for them
                # had genuinely been recorded.
                assessments = (Assessment.query
                               .filter(Assessment.student_id.in_(student_ids),
                                       Assessment.archived == False)
                               .all())
                assessments_by_student = defaultdict(list)
                for a in assessments:
                    assessments_by_student[a.student_id].append(a)
            else:
                assessments_by_student = {}

            summaries = []
            for student in students:
                student_assessments = assessments_by_student.get(student.id, [])
                filled_cats = {a.category for a in student_assessments if a.category in required_categories}
                filled_count = len(filled_cats)
                missing_cats = [cat for cat in required_categories if cat not in filled_cats]
                missing_count = n_required - filled_count
                completion_pct = round((filled_count / n_required) * 100) if n_required else 0

                if student_assessments:
                    raw_scores = scores_from_assessments(student_assessments)
                    if raw_scores:
                        avg_percentage = float(calculate_scores_from_template(raw_scores)['final_score'])
                    else:
                        avg_percentage = None
                else:
                    avg_percentage = None
                grade_data = calculate_gpa_and_grade(avg_percentage) if avg_percentage is not None else None
                summaries.append({
                    'student': student,
                    'avg_percentage': avg_percentage,
                    'grade': grade_data['grade'] if grade_data else None,
                    'assessment_count': len(student_assessments),
                    'filled_count': filled_count,
                    'missing_count': missing_count,
                    'missing_cats': missing_cats,
                    'total_categories': n_required,
                    'completion_pct': completion_pct,
                })

            teacher_student_summaries = sorted(
                summaries,
                key=lambda item: (item['avg_percentage'] is None, item['avg_percentage'] or 0)
            )

    students_by_class, students_by_area, students_by_class_area = get_student_groups(current_user, app.config)

    archive_total = Assessment.query.filter_by(archived=True).count()
    archive_terms = (
        db.session.query(
            db.func.count(
                db.func.distinct(
                    db.func.concat(Assessment.academic_year, '|', Assessment.term)
                )
            )
        ).filter(Assessment.archived == True).scalar() or 0
    )
    archive_students = (
        db.session.query(
            db.func.count(Assessment.student_id.distinct())
        ).filter(Assessment.archived == True).scalar() or 0
    )

    settings = Setting.query.first()

    # Unique students, not (student, subject) pairs — a student missing
    # categories in two subjects should count once here, matching what a
    # person means by "N students need attention", and matching the same
    # dedup done in /admin/api/incomplete-assessments so the number never
    # disagrees between the static page and a live refresh.
    affected_students_count = len({item['student'].id for item in incomplete_list})

    # Cap what renders inline so a full school's worth of incomplete
    # records doesn't turn the dashboard into a wall of cards — the
    # in-depth, paginated/filterable version of this already exists at
    # /admin/teacher-tracking for admins. Sort so the same students show
    # first on every load rather than dict-ordering noise.
    incomplete_display = sorted(
        incomplete_list, key=lambda i: i['student'].full_name()
    )[:30]
    incomplete_display_truncated = len(incomplete_list) > len(incomplete_display)

    return render_template(
        'dashboard.html',
        student_count=student_count,
        assessment_count=assessment_count,
        users_count=users_count,
        affected_students_count=affected_students_count,
        incomplete_students=incomplete_display,
        incomplete_display_truncated=incomplete_display_truncated,
        incomplete_total_count=len(incomplete_list),
        recent=recent,
        teacher_student_summaries=teacher_student_summaries,
        grouped_students=None,
        students_by_class=students_by_class,
        students_by_area=students_by_area,
        students_by_class_area=students_by_class_area,
        archive_total=archive_total,
        archive_terms=archive_terms,
        archive_students=archive_students,
        settings=settings,
        category_labels=app.config.get('CATEGORY_LABELS', {}),
    )


@app.route('/dashboard')
@login_required
def dashboard_alias():
    return redirect(url_for('dashboard'))


# ──────────────────────────────────────────────────────────────────────────
# RECONSTRUCTED: this function's def/@app.route/@login_required header and
# its `student` lookup were missing from the source as received — the body
# below (from `if not student:` onward) is the original, unmodified code.
# Verify this route path and the lookup logic against your own Git history
# if you have an earlier working commit to compare against.
# ──────────────────────────────────────────────────────────────────────────
@app.route('/student/dashboard')
@login_required
def student_dashboard():
    student = Student.query.filter_by(student_number=current_user.username).first()

    if not student:
        logout_user()
        flash('Student record not found. Contact the administrator.', 'danger')
        return redirect(url_for('student_login'))

    settings = Setting.query.first()
    # When running tests without an existing Setting row, default to
    # showing results so unit tests that inspect the dashboard can run.
    results_visible = settings.is_results_visible() if settings else app.config.get('TESTING', False)
    if not results_visible:
        return render_template(
            'student_results_locked.html',
            student=student,
            release_date=settings.results_release_date if settings else None
        )

    subject_f  = request.args.get('subject', '')
    class_f    = request.args.get('class', '')
    category_f = request.args.get('category', '')

    # ── Always load the FULL unfiltered assessment list first ──────────────
    # This is the source of truth for dropdowns and teacher_results.
    all_assessments = (
        Assessment.query
        .filter_by(student_id=student.id, archived=False)
        .order_by(Assessment.date_recorded.desc())
        .all()
    )

    # ── Build filter dropdown options from the FULL list ───────────────────
    subjects   = sorted({a.subject    for a in all_assessments if a.subject})
    classes    = sorted({a.class_name for a in all_assessments if a.class_name})
    categories = sorted({a.category   for a in all_assessments if a.category})

    # ── Apply filters to produce the visible table rows ────────────────────
    assessments = all_assessments
    if subject_f:
        subject_key = canonical_subject_key(subject_f)
        assessments = [a for a in assessments if canonical_subject_key(a.subject) == subject_key]
    if class_f:     assessments = [a for a in assessments if a.class_name == class_f]
    if category_f:  assessments = [a for a in assessments if a.category   == category_f]

    # ── Build teacher_results from the FULL list (not the filtered one) ────
    # Also batch-load teachers to avoid N+1 queries.
    teacher_ids = {a.teacher_id for a in all_assessments if a.teacher_id is not None}
    teacher_map = {t.id: t for t in User.query.filter(User.id.in_(teacher_ids)).all()} if teacher_ids else {}

    teacher_subjects_raw = {}
    for a in all_assessments:
        if a.archived:
            continue
        tid = a.teacher_id
        teacher_subjects_raw.setdefault(tid, {}).setdefault(a.subject, []).append(a)

    teacher_results = {}
    for tid, subj_data in teacher_subjects_raw.items():
        teacher = teacher_map.get(tid) if tid is not None else None
        tname = teacher.username if teacher else 'Unassigned'
        teacher_results[tname] = {}
        for sname, alist in subj_data.items():
            fp = student.calculate_final_grade(subject=sname, teacher_id=tid)
            gr = calculate_gpa_and_grade(fp)
            teacher_results[tname][sname] = {
                'final_percent': fp or 0.0,
                'gpa':   gr['gpa'],
                'grade': gr['grade'],
                'assessments': alist,
            }

    # ── Summary and overall grades (always from full list) ─────────────────
    summary = student.get_assessment_summary_from_list(all_assessments)
    aggregate_metrics = build_student_aggregate_metrics(student)
    final_pct = aggregate_metrics['final_percent']
    gpa_grade = {'gpa': aggregate_metrics['gpa'], 'grade': aggregate_metrics['letter_grade']}
    overall_summary = aggregate_metrics.get(
        'overall_summary',
        {'final_score': final_pct, 'gpa': gpa_grade['gpa'], 'grade': gpa_grade['grade']}
    )

    # ── Final score and grade from the school-template formula chain ───────
    # Only use the template-composition path when a specific subject filter is
    # actually selected. For the full all-subjects dashboard view, the page must
    # render the same authoritative aggregate summary already produced by the
    # business layer instead of a cross-subject best-score collage.
    if subject_f and assessments:
        raw_filtered = scores_from_assessments(assessments)
        filtered_result = calculate_scores_from_template(raw_filtered)
        avg_score = filtered_result['final_score']
        filt_res = {'gpa': filtered_result['gpa'], 'grade': filtered_result['grade']}
        filtered_grade_point = GRADE_POINT_MAP.get(filtered_result['grade'])
    else:
        avg_score = final_pct if final_pct is not None else 0.0
        filt_res = {'gpa': gpa_grade['gpa'], 'grade': gpa_grade['grade']}
        filtered_grade_point = GRADE_POINT_MAP.get(gpa_grade['grade'])

    # Use the exact template aggregate summary for overall class division
    grade_point = aggregate_metrics['grade_point']
    aggregate = grade_point  # explicit alias — this is the WASSCE-style
                             # best-4-core + best-4-elective sum, e.g. 20.
                             # It is NOT the same thing as filtered_grade_point.
    grading_class = aggregate_metrics['grading_class']
    comment = aggregate_metrics['comment']

    # When no specific subject is selected ("all subjects"), the dashboard
    # must show ONLY the aggregate — never filtered_grade_point, since that
    # value (derived from the average score's own letter grade) is not a
    # per-subject grade point and must not be confused with one.
    show_aggregate = not bool(subject_f)

    # ── Quiz attempts ──────────────────────────────────────────────────────
    quiz_attempts = (
        QuizAttempt.query
        .filter_by(student_id=student.id)
        .order_by(QuizAttempt.completed_at.desc())
        .all()
    )
    quiz_ids    = [a.quiz_id for a in quiz_attempts]
    quiz_objs   = {q.id: q for q in Quiz.query.filter(Quiz.id.in_(quiz_ids)).all()} if quiz_ids else {}
    quiz_details = {a.id: quiz_objs[a.quiz_id] for a in quiz_attempts if a.quiz_id in quiz_objs}

    # ── Incomplete-assessment ("IC") flag for THIS student ─────────────────
    # Reuses the same cached, already-computed get_incomplete_assessments()
    # list used by the admin/teacher dashboards, filtered down to this one
    # student — no extra query, and it stays consistent with what an
    # admin/teacher sees for the same student rather than being computed
    # by a second, possibly-divergent code path.
    student_missing = [
        item for item in get_incomplete_assessments()
        if item['student'].id == student.id
    ]
    student_is_incomplete = bool(student_missing)

    return render_template(
        'student_dashboard.html',
        student=student,
        assessments=assessments,
        teacher_results=teacher_results,
        summary=summary,
        final_percent=final_pct,
        gpa_grade=gpa_grade,
        grade_point=grade_point,
        aggregate=aggregate,
        show_aggregate=show_aggregate,
        grading_class=grading_class,
        comment=comment,
        subjects=subjects,
        classes=classes,
        categories=categories,
        selected_subject=subject_f,
        selected_class=class_f,
        selected_category=category_f,
        average_score=avg_score,
        filtered_gpa=filt_res['gpa'],
        filtered_grade=filt_res['grade'],
        filtered_grade_point=filtered_grade_point,
        quiz_attempts=quiz_attempts,
        quiz_details=quiz_details,
        overall_gpa=overall_summary.get('gpa'),
        CATEGORY_LABELS=CATEGORY_LABELS,
        student_missing=student_missing,
        student_is_incomplete=student_is_incomplete,
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
    study_area = request.args.get('study_area')
    tid        = current_user.id if current_user.is_teacher() else None
    return render_template(
        'analytics.html',
        performance_summary=get_class_performance_summary(
            class_name=class_name, subject=subject, teacher_id=tid, study_area=study_area),
        grade_distribution=get_grade_distribution(
            subject=subject, class_name=class_name, teacher_id=tid, study_area=study_area),
        selected_subject=subject,
        selected_class=class_name,
        selected_study_area=study_area,
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

    # ── FIX: use the centralised filter for teachers ──────────────────────
    if hasattr(current_user, 'is_teacher') and current_user.is_teacher():
        filtered_q = get_teacher_students_query(current_user)
        if filtered_q is None:
            # Teacher profile is incomplete — show nothing.
            q = Student.query.filter(db.false())
        else:
            q = filtered_q

    if search:
        q = q.filter(
            db.or_(
                Student.student_number.ilike(f'%{search}%'),
                Student.first_name.ilike(f'%{search}%'),
                Student.last_name.ilike(f'%{search}%'),
                Student.reference_number.ilike(f'%{search}%'),
                Student.student_id_code.ilike(f'%{search}%'),
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
            resolved_study_area = canonical_study_area_key(form.study_area.data) or None

            manual_ref = (form.reference_number.data or '').strip()
            if manual_ref:
                if Student.query.filter_by(reference_number=manual_ref).first():
                    flash('Reference number already in use by another student.', 'warning')
                    return render_template('student_form.html', form=form, student=None)
                ref = manual_ref
            else:
                ref = generate_unique_reference_number()

            manual_sid = (form.student_id_code.data or '').strip()
            if manual_sid:
                if Student.query.filter_by(student_id_code=manual_sid).first():
                    flash('Student ID already in use by another student.', 'warning')
                    return render_template('student_form.html', form=form, student=None)
                sid = manual_sid
            else:
                # Auto-generated in the ZGS/{FAMILY CODE}{YY}/{SEQ}
                # admission format — see generate_student_id_number() above.
                sid = generate_student_id_number(study_area=resolved_study_area)

            s = Student(
                student_number=form.student_number.data.strip(),
                first_name=form.first_name.data.strip(),
                last_name=form.last_name.data.strip(),
                middle_name=optional_name(form.middle_name.data),
                class_name=canonical_class_key(form.class_name.data) or None,
                study_area=resolved_study_area,
                reference_number=ref,
                student_id_code=sid,
            )
            db.session.add(s)
            db.session.commit()
            log_activity(current_user, 'create_student',
                         f'Created {s.full_name()} ({s.student_number})')
            flash(f'Student added. Student ID: {sid} · Reference Number: {ref}', 'success')
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
        new_number = form.student_number.data.strip()
        new_ref    = (form.reference_number.data or '').strip()
        new_sid    = (form.student_id_code.data or '').strip()

        # All three are unique columns — check before touching the row so
        # a collision surfaces as a normal flash message instead of an
        # unhandled IntegrityError (500) from the DB constraint. This
        # check was already missing for student_number even before
        # reference_number/student_id_code became editable here.
        conflict = Student.query.filter(
            Student.id != student.id, Student.student_number == new_number
        ).first()
        if conflict:
            flash(f'Student number "{new_number}" is already used by {conflict.full_name()}.', 'warning')
            return render_template('student_form.html', form=form, student=student)

        if new_ref:
            conflict = Student.query.filter(
                Student.id != student.id, Student.reference_number == new_ref
            ).first()
            if conflict:
                flash(f'Reference number "{new_ref}" is already used by {conflict.full_name()}.', 'warning')
                return render_template('student_form.html', form=form, student=student)

        if new_sid:
            conflict = Student.query.filter(
                Student.id != student.id, Student.student_id_code == new_sid
            ).first()
            if conflict:
                flash(f'Student ID "{new_sid}" is already used by {conflict.full_name()}.', 'warning')
                return render_template('student_form.html', form=form, student=student)

        student.student_number = new_number
        # Blanking a field intentionally clears it (Optional validator
        # allows empty) rather than silently keeping the old value — an
        # admin correcting a wrong reference number/student ID needs
        # blank-then-retype to actually work, not be quietly ignored.
        student.reference_number = new_ref or None
        student.student_id_code  = new_sid or None
        student.first_name  = form.first_name.data.strip()
        student.last_name   = form.last_name.data.strip()
        student.middle_name = optional_name(form.middle_name.data)
        student.class_name  = canonical_class_key(form.class_name.data) or None
        student.study_area  = canonical_study_area_key(form.study_area.data) or None
        db.session.commit()
        log_activity(current_user, 'edit_student', f'Edited {student.full_name()}')
        flash(f'{student.full_name()} updated', 'success')
        return redirect(url_for('students'))
    return render_template('student_form.html', form=form, student=student)


@app.route('/students/<int:student_id>/delete', methods=['POST'])
@login_required
@admin_required
def student_delete(student_id):
    try:
        student = Student.query.get_or_404(student_id)
        name = student.full_name()
        num  = student.student_number
        QuizAttempt.query.filter_by(student_id=student_id).delete()
        QuestionAttempt.query.filter_by(student_id=student_id).delete()
        Assessment.query.filter_by(student_id=student_id).delete()
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

    if hasattr(current_user, 'is_teacher') and current_user.is_teacher():
        if not teacher_can_view_student(current_user, student):
            abort(403)

        q = Assessment.query.filter_by(
            student_id=student.id, archived=False,
            teacher_id=current_user.id,
        )
        if current_user.subject:
            q = q.filter_by(subject=current_user.subject)
        if subject:
            q = q.filter_by(subject=subject)
        assessments = q.order_by(Assessment.date_recorded.desc()).all()
        tid = current_user.id
        effective_subject = current_user.subject
        all_subjects = sorted({a.subject for a in assessments if a.subject})
    else:
        q = Assessment.query.filter_by(student_id=student.id, archived=False)
        if subject:
            q = q.filter_by(subject=subject)
        assessments = q.order_by(Assessment.date_recorded.desc()).all()
        tid = None
        effective_subject = subject
        all_subjects = sorted({
            row[0] for row in
            Assessment.query.filter_by(student_id=student.id, archived=False)
                      .with_entities(Assessment.subject).distinct().all()
            if row[0]
        })

    summary   = student.get_assessment_summary(effective_subject, teacher_id=tid)
    final_pct = student.calculate_final_grade(
        subject=effective_subject, teacher_id=tid)

    summary_list = [
        {'category': cat, 'count': d.get('count', 0),
         'avg_percent': round(d.get('avg_percent', 0.0), 1)}
        for cat, d in summary.items()
    ]

    # NOTE: The original code had a second `all_subjects` assignment here that
    # silently overwrote the filtered value computed above with an unfiltered
    # query ignoring teacher_id.  That second assignment has been removed.

    aggregate_metrics = build_student_aggregate_metrics(student)
    final_pct = aggregate_metrics['final_percent']
    letter_grade = aggregate_metrics['letter_grade']
    gpa = aggregate_metrics['gpa']
    grade_point = aggregate_metrics['grade_point']
    aggregate = grade_point  # explicit alias — WASSCE best-4-core + best-4-elective sum
    grading_class = aggregate_metrics['grading_class']
    comment = aggregate_metrics['comment']

    # ── Individual subject grade point vs. whole-record aggregate ──────────
    # A single subject (e.g. Mathematics = B3) has a grade point of 3.
    # The aggregate (best 4 core + best 4 elective grade points summed) is
    # a completely different number and must never be shown side-by-side
    # with, or mistaken for, a single subject's grade point.
    if effective_subject:
        subject_result = student.calculate_subject_final_grades(teacher_id=tid).get(
            normalize_label(effective_subject)
        )
        if subject_result:
            final_pct = subject_result['final_percent']
            letter_grade = subject_result['grade']
            gpa = subject_result['gpa']
            filtered_grade_point = subject_result['grade_point']
        else:
            filtered_grade_point = None
        show_aggregate = False
    else:
        filtered_grade_point = None
        show_aggregate = True

    teacher_results = None
    if current_user.is_admin():
        ts = {}
        for a in assessments:
            ts.setdefault(a.teacher_id, {}).setdefault(a.subject, []).append(a)
        teacher_results = {}
        for tid2, sd in ts.items():
            t2 = db.session.get(User, tid2)
            tname = t2.username if t2 else f'Teacher {tid2}'
            teacher_results[tname] = {}
            for sname, alist in sd.items():
                fp2 = student.calculate_final_grade(subject=sname, teacher_id=tid2)
                gr2 = calculate_gpa_and_grade(fp2)
                teacher_results[tname][sname] = {
                    'final_percent': fp2, 'gpa': gr2['gpa'],
                    'grade': gr2['grade'], 'assessments': alist,
                }

    # ── Incomplete-assessment ("IC") flag ───────────────────────────────────
    # Same cached list used by the dashboards and the student's own view —
    # one source of truth, no extra query.
    student_missing = [
        item for item in get_incomplete_assessments()
        if item['student'].id == student.id
    ]
    student_is_incomplete = bool(student_missing)

    return render_template(
        'student_view.html',
        student=student, assessments=assessments,
        teacher_results=teacher_results, summary=summary,
        summary_list=summary_list, final_percent=final_pct,
        letter_grade=letter_grade, gpa=gpa, comment=comment,
        subject=subject, all_subjects=all_subjects,
        study_areas_dict=dict(app.config['STUDY_AREAS']),
        CATEGORY_LABELS=app.config['CATEGORY_LABELS'],
        grade_point=grade_point,
        aggregate=aggregate,
        filtered_grade_point=filtered_grade_point,
        show_aggregate=show_aggregate,
        grading_class=grading_class,
        student_missing=student_missing,
        student_is_incomplete=student_is_incomplete,
    )


@app.route('/students/<int:student_id>/transcript')
@login_required
def student_transcript(student_id):
    """Admin/teacher-facing academic transcript for a specific student."""
    student = Student.query.get_or_404(student_id)

    if hasattr(current_user, 'is_teacher') and current_user.is_teacher():
        if not teacher_can_view_student(current_user, student):
            abort(403)

    settings = Setting.query.first()
    transcript = build_academic_transcript(student)

    return render_template(
        'transcript.html',
        student=student,
        transcript=transcript,
        settings=settings,
        grade_scale=GRADE_SCALE,
    )


@app.route('/student/transcript')
@login_required
def student_transcript_self():
    """Student's own academic transcript — available for as long as they
    remain in the system, spanning every year and semester on record."""
    if not (hasattr(current_user, 'is_student') and current_user.is_student()):
        abort(403)

    student = Student.query.filter_by(student_number=current_user.username).first_or_404()

    settings = Setting.query.first()
    if not settings or not settings.is_results_visible():
        flash('Results have not been released yet — your transcript will be available once they are.', 'warning')
        return redirect(url_for('student_dashboard'))

    transcript = build_academic_transcript(student)

    return render_template(
        'transcript.html',
        student=student,
        transcript=transcript,
        settings=settings,
        grade_scale=GRADE_SCALE,
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
        file = form.excel_file.data
        filepath = os.path.join(app.config['UPLOAD_FOLDER'],
                                secure_filename(file.filename))
        file.save(filepath)
        try:
            data_list = StudentBulkImporter(filepath).import_students()
            for item in data_list:
                item['class_name'] = canonical_class_key(item.get('class_name'))
                item['study_area'] = canonical_study_area_key(item.get('study_area'))

            incoming_numbers = {
                (d.get('student_number') or '').strip()
                for d in data_list
            }
            existing_numbers = {
                row[0] for row in
                db.session.query(Student.student_number)
                .filter(Student.student_number.in_(incoming_numbers))
                .all()
            }

            existing_refs = {
                row[0] for row in
                db.session.query(Student.reference_number).all()
            }
            existing_sids = {
                row[0] for row in
                db.session.query(Student.student_id_code).all()
            }
            sid_seq_cache = {}  # per-family-prefix sequence counter for this batch

            ok = 0
            errors = []
            new_students = []

            with db.session.no_autoflush:
                for data in data_list:
                    snum = (data.get('student_number') or '').strip()
                    if not snum:
                        errors.append('Row skipped: missing student number')
                        continue
                    if snum in existing_numbers:
                        errors.append(f'{snum} already exists')
                        continue

                    # Plain reference number (STU######) — not tied to
                    # study area, so no batch-collision risk to worry
                    # about beyond the existing_refs set membership check.
                    ref = None
                    for _ in range(100):
                        candidate = f'STU{random.randint(100000, 999999)}'
                        if candidate not in existing_refs:
                            existing_refs.add(candidate)
                            ref = candidate
                            break
                    if ref is None:
                        ref = f'STU{int(time.time()) % 1000000:06d}'
                        existing_refs.add(ref)

                    sid = generate_student_id_batch(
                        data.get('study_area'), existing_sids, sid_seq_cache
                    )

                    new_students.append(Student(
                        student_number=snum,
                        first_name=(data.get('first_name') or '').strip(),
                        last_name=(data.get('last_name') or '').strip(),
                        middle_name=optional_name(data.get('middle_name')),
                        class_name=(data.get('class_name') or '').strip() or None,
                        study_area=(data.get('study_area') or '').strip() or None,
                        reference_number=ref,
                        student_id_code=sid,
                    ))
                    existing_numbers.add(snum)
                    ok += 1

            db.session.bulk_save_objects(new_students)
            db.session.commit()
            os.remove(filepath)

            flash(f'Imported {ok} students. {len(errors)} errors.', 'success')
            if errors:
                flash('Errors: ' + '; '.join(errors[:5]), 'warning')
            return redirect(url_for('students'))

        except Exception as exc:
            db.session.rollback()
            if os.path.exists(filepath):
                os.remove(filepath)
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

    pagination = (
        q.options(joinedload(Assessment.student))
         .order_by(Assessment.date_recorded.desc())
         .paginate(page=page, per_page=per_page, error_out=False)
    )

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
    """
    FIX SUMMARY
    -----------
    Previous code used three separate, partially-overlapping branches that
    could fall through to `Student.query.…limit(500)` whenever a teacher's
    STUDY_AREA_SUBJECTS mapping was empty.  Replaced with a single call to
    get_teacher_students_query() which enforces subject-area + class filters
    in a consistent, well-defined priority order.  If the function returns
    None (teacher profile incomplete), the user is redirected with an
    actionable message rather than being shown all students.
    """
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)

    form = AssessmentForm()

    # ── Build the authorised student list ─────────────────────────────────
    if current_user.is_teacher():
        if not current_user.subject:
            flash(
                'You must have a subject assigned before you can create assessments. '
                'Please ask the administrator to complete your profile.',
                'warning',
            )
            return redirect(url_for('teacher_subject'))

        students_query = get_teacher_students_query(current_user)

        if students_query is None:
            # Teacher has a subject but no class and no study-area mapping.
            flash(
                'Your account has no class or study area assigned. '
                'Please contact the administrator to configure your teacher profile '
                'before entering assessments.',
                'warning',
            )
            return redirect(url_for('dashboard'))

        if current_user.is_teacher() and current_user.subject:
            sas = app.config.get('STUDY_AREA_SUBJECTS', {})
            if not sas:
                flash(
                    'Warning: study area subjects have not been configured by the administrator. '
                    'Student filtering may be incomplete.',
                    'warning',
                )

        students_qs = students_query.all()

        if not students_qs:
            flash(
                'No students are currently enrolled in your assigned class(es) '
                'or study area(s). Contact the administrator if this appears incorrect.',
                'info',
            )

    else:
        # Admins see all students.
        students_qs = Student.query.order_by(
            Student.class_name, Student.last_name
        ).all()

    # ── Group students by class for the dropdown ──────────────────────────
    grouped = {}
    for s in students_qs:
        class_display = s.get_class_display() or 'Unassigned'
        grouped.setdefault(class_display, []).append(s)

    sorted_groups = {
        cn: sorted(grouped[cn], key=lambda s: s.full_name())
        for cn in sorted(grouped.keys())
    }

    # ── Pre-fill form defaults ────────────────────────────────────────────
    settings = Setting.query.first()
    if current_user.is_teacher() and current_user.subject:
        form.subject.data = current_user.subject

    snum_param  = request.args.get('student')
    student_obj = None
    if snum_param:
        student_obj = Student.query.filter_by(student_number=snum_param).first()
        if student_obj and current_user.is_teacher():
            if not current_user.can_access_student(student_obj, app.config):
                abort(403)
        if student_obj:
            form.student_name.data = student_obj.student_number

    if settings:
        form.term.data          = settings.current_term
        form.academic_year.data = settings.current_academic_year
        form.session.data       = settings.current_session

    # ── Handle form submission ────────────────────────────────────────────
    if form.validate_on_submit():
        snum    = form.student_name.data or (form.student_number.data or '').strip()
        student = Student.query.filter_by(student_number=snum).first()
        if not student:
            flash('Invalid student selected.', 'danger')
            return redirect(url_for('new_assessment'))

        # Re-check access on submission (guards against crafted POST requests)
        if current_user.is_teacher() and not current_user.can_access_student(student, app.config):
            flash('You do not have permission to create assessments for this student.', 'danger')
            abort(403)

        # archived=False: an archived assessment must not block re-entry.
        # Without this filter, a teacher who archives a mistaken entry (or
        # an admin who archives one on their behalf) gets told the record
        # "already exists" on every attempt to re-enter it, even though it
        # is invisible everywhere else in the app (dashboards, student
        # view, exports all filter archived=False) — so there is no way
        # to see or recover it, only a block on creating a fresh one.
        if Assessment.query.filter_by(
                student_id=student.id, category=form.category.data,
                subject=form.subject.data, term=form.term.data,
                academic_year=form.academic_year.data,
                session=form.session.data,
                teacher_id=current_user.id,
                archived=False).first():
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
            # None (not current_user.id) when an admin enters this on a
            # teacher's behalf — matches the convention already used by
            # the bulk importers. Stamping the admin's own id here was
            # what made admin-entered scores invisible on teacher-scoped
            # trackers below: they'd be attributed to an account that
            # isn't a teacher at all, rather than to no one in particular.
            teacher_id=(current_user.id if current_user.is_teacher() else None),
            comments=form.comments.data,
        )
        db.session.add(a)
        cache.delete("incomplete_assessments")
        db.session.commit()
        log_activity(current_user, 'create_assessment',
                     f'Created assessment for {student.full_name()}')
        flash(f'Assessment saved for {student.full_name()}', 'success')
        return redirect(url_for('student_view', student_id=student.id))

    return render_template(
        'assessment_form.html',
        form=form,
        grouped_students=sorted_groups,
        student_dict={},
        student_full_name=student_obj.full_name() if student_obj else None,
    )


@app.route('/assessments/<int:assessment_id>/edit', methods=['GET', 'POST'])
@login_required
def assessment_edit(assessment_id):
    """
    FIX: The original implementation used Student.query.all() unconditionally,
    exposing all students to any teacher who edits an assessment.  Replaced
    with get_teacher_students_query() for teachers; admins retain full access.
    """
    a = Assessment.query.get_or_404(assessment_id)
    if not (current_user.is_admin() or
            (current_user.is_teacher() and a.teacher_id == current_user.id)):
        abort(403)

    form = AssessmentForm(obj=a)

    # ── Restrict the student dropdown to the teacher's authorised students ─
    if current_user.is_teacher():
        students_query = get_teacher_students_query(current_user)
        students_qs = students_query.all() if students_query is not None else []
    else:
        students_qs = Student.query.order_by(Student.class_name, Student.last_name).all()

    grouped = {}
    for s in students_qs:
        grouped.setdefault(s.class_name or 'Unspecified', []).append(s)
    sorted_groups = {
        cn: sorted(gs, key=lambda s: s.full_name())
        for cn in sorted(grouped)
        for gs in [grouped[cn]]
    }

    form.student_name.data     = a.student.student_number
    form.student_number.data   = a.student.student_number
    form.reference_number.data = a.student.reference_number

    if form.validate_on_submit():
        snum    = form.student_name.data or (form.student_number.data or '').strip()
        student = Student.query.filter_by(student_number=snum).first()
        if not student:
            flash('Invalid student.', 'danger')
            return redirect(url_for('assessment_edit', assessment_id=assessment_id))

        # Re-validate access on submission
        if current_user.is_teacher() and not current_user.can_access_student(student, app.config):
            flash('You do not have permission to assign this student.', 'danger')
            abort(403)

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
        cache.delete("incomplete_assessments")
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

    wants_json = (
        request.headers.get('Accept', '').find('application/json') != -1 or
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    )

    try:
        sid = a.student_id
        student = a.student
        student_name = student.full_name() if student else f'student #{sid}'
    except Exception:
        sid = a.student_id
        student_name = f'student #{sid}'

    try:
        db.session.delete(a)
        db.session.commit()
        cache.delete("incomplete_assessments")
        log_activity(current_user, 'delete_assessment',
                     f'Deleted assessment for {student_name}')
    except SQLAlchemyError as exc:
        db.session.rollback()
        app.logger.error('assessment_delete(%d): %s', assessment_id, exc)
        msg = 'Database error — assessment could not be deleted. Please try again.'
        if wants_json:
            return jsonify({'success': False, 'message': msg}), 500
        flash(msg, 'danger')
        return redirect(request.referrer or url_for('assessments_list'))
    except Exception as exc:
        db.session.rollback()
        app.logger.error('assessment_delete(%d) unexpected: %s', assessment_id, exc)
        msg = 'Unexpected error — assessment could not be deleted.'
        if wants_json:
            return jsonify({'success': False, 'message': msg}), 500
        flash(msg, 'danger')
        return redirect(request.referrer or url_for('assessments_list'))

    if wants_json:
        return jsonify({
            'success': True,
            'message': f'Assessment deleted for {student_name}.',
            'redirect': url_for('student_view', student_id=sid),
        })

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
    cache.delete("incomplete_assessments")
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
    cache.delete("incomplete_assessments")
    db.session.commit()
    flash('Assessment restored', 'info')
    return redirect(request.referrer or url_for('assessments_list'))


@app.route('/assessments/archived')
@login_required
@admin_required
def assessments_archived():
    """
    Archive browser, organized as folders: Class/Form → Academic Year →
    Semester → the actual archived records. Navigation depth is driven
    entirely by which query params are present — no class_name means
    "show me the class folders", class_name+academic_year but no term
    means "show me the semester folders inside that year", and so on.
    Each level is reachable directly (bookmarkable, back-button-safe).
    """
    from sqlalchemy import func

    sel_class   = request.args.get('class_name',    '').strip()
    sel_year    = request.args.get('academic_year', '').strip()
    sel_term    = request.args.get('term',          '').strip()
    search      = request.args.get('search',        '').strip()
    sel_subject = request.args.get('subject',       '').strip()
    page        = request.args.get('page', 1, type=int)
    per_page    = app.config['ASSESSMENTS_PER_PAGE']

    base_q = Assessment.query.filter_by(archived=True)

    total_archived    = base_q.count()
    archived_students = (db.session.query(func.count(Assessment.student_id.distinct()))
                           .filter_by(archived=True).scalar() or 0)
    last_record = base_q.order_by(Assessment.date_recorded.desc()).first()
    last_archive_date = (last_record.date_recorded.strftime('%d %b %Y')
                         if last_record else None)

    # Class/Form display order follows CLASS_LEVELS config, not
    # alphabetical — "Form 2" sorting before "Form 10" alphabetically
    # would look wrong to a person even though it's technically correct
    # string order. Anything not in that config (legacy/typo'd class
    # names) is appended afterward, alphabetically, rather than hidden.
    class_order = [key for key, _ in app.config.get('CLASS_LEVELS', [])]
    def _class_sort_key(name):
        try:
            return (0, class_order.index(name))
        except ValueError:
            return (1, name or '')

    term_order = [key for key, _ in app.config.get('TERMS', [])]
    term_label_map = dict(app.config.get('TERMS', []))
    def _term_sort_key(t):
        try:
            return (0, term_order.index(t))
        except ValueError:
            return (1, t or '')

    common_kwargs = dict(
        total_archived=total_archived,
        archived_students=archived_students,
        last_archive_date=last_archive_date,
        learning_areas=app.config['LEARNING_AREAS'],
        class_levels=app.config['CLASS_LEVELS'],
        terms=app.config.get('TERMS', []),
        selected_class=sel_class,
        selected_year=sel_year,
        selected_term=sel_term,
        search=search,
        selected_subject=sel_subject,
    )

    # ── LEVEL 1: class/form folders ─────────────────────────────────────
    if not sel_class:
        rows = (db.session.query(
                    Assessment.class_name,
                    func.count(Assessment.id),
                    func.count(Assessment.student_id.distinct()),
                )
                .filter_by(archived=True)
                .group_by(Assessment.class_name)
                .all())
        class_folders = sorted(
            [{
                'class_name': cls or 'Unassigned Class',
                'raw_class_name': cls or '',
                'count': cnt,
                'student_count': stu_cnt,
            } for cls, cnt, stu_cnt in rows],
            key=lambda f: _class_sort_key(f['raw_class_name'])
        )
        return render_template('archive_view.html', view_level='classes',
                               class_folders=class_folders, **common_kwargs)

    # ── LEVEL 2: academic-year folders inside this class ────────────────
    if not sel_year:
        class_filter = None if sel_class == 'Unassigned Class' else sel_class
        rows = (db.session.query(
                    Assessment.academic_year,
                    func.count(Assessment.id),
                    func.count(Assessment.student_id.distinct()),
                )
                .filter_by(archived=True, class_name=class_filter)
                .group_by(Assessment.academic_year)
                .all())
        year_folders = sorted(
            [{
                'academic_year': ay or 'Unknown Year',
                'raw_academic_year': ay or '',
                'count': cnt,
                'student_count': stu_cnt,
            } for ay, cnt, stu_cnt in rows],
            key=lambda f: f['raw_academic_year'], reverse=True
        )
        return render_template('archive_view.html', view_level='years',
                               year_folders=year_folders, **common_kwargs)

    # ── LEVEL 3: semester/term folders inside this class + year ─────────
    if not sel_term:
        year_filter = None if sel_year == 'Unknown Year' else sel_year
        class_filter = None if sel_class == 'Unassigned Class' else sel_class
        rows = (db.session.query(
                    Assessment.term,
                    func.count(Assessment.id),
                    func.count(Assessment.student_id.distinct()),
                )
                .filter_by(archived=True, class_name=class_filter, academic_year=year_filter)
                .group_by(Assessment.term)
                .all())
        term_folders = sorted(
            [{
                'term': t or 'unknown',
                'raw_term': t or '',
                'term_label': term_label_map.get(t, (t or 'Unknown Term')),
                'count': cnt,
                'student_count': stu_cnt,
            } for t, cnt, stu_cnt in rows],
            key=lambda f: _term_sort_key(f['raw_term'])
        )
        return render_template('archive_view.html', view_level='terms',
                               term_folders=term_folders, **common_kwargs)

    # ── LEVEL 4: the actual archived records in this Class / Year / Term ──
    class_filter = None if sel_class == 'Unassigned Class' else sel_class
    year_filter  = None if sel_year == 'Unknown Year' else sel_year
    term_filter  = None if sel_term == 'unknown' else sel_term

    q = base_q.filter_by(class_name=class_filter, academic_year=year_filter, term=term_filter)
    if search:
        q = q.join(Student, Assessment.student_id == Student.id).filter(
            db.or_(
                Student.first_name.ilike(f'%{search}%'),
                Student.last_name.ilike(f'%{search}%'),
                Student.student_number.ilike(f'%{search}%'),
            )
        )
    if sel_subject:
        q = q.filter_by(subject=sel_subject)

    pagination = (q.options(joinedload(Assessment.student))
                   .order_by(Assessment.date_recorded.desc())
                   .paginate(page=page, per_page=per_page, error_out=False))
    pagination.items = [a for a in pagination.items if a.student is not None]

    return render_template('archive_view.html', view_level='records',
                           assessments=pagination.items, pagination=pagination,
                           **common_kwargs)


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

    try:
        if action == 'archive':
            for a in items:
                a.archived = True
        elif action == 'unarchive':
            for a in items:
                a.archived = False
        else:
            if not current_user.is_admin():
                abort(403)
            for a in items:
                db.session.delete(a)

        db.session.commit()
        cache.delete("incomplete_assessments")
        log_activity(current_user, f'bulk_{action}',
                     f'{action}d {len(items)} assessments')
        flash(f'Successfully {action}d {len(items)} assessments.', 'success')
    except SQLAlchemyError as exc:
        db.session.rollback()
        app.logger.error('assessment_bulk_action(%s): %s', action, exc)
        flash('Database error during bulk action. Please try again.', 'danger')
    except Exception as exc:
        db.session.rollback()
        app.logger.error('assessment_bulk_action(%s) unexpected: %s', action, exc)
        flash('Unexpected error during bulk action.', 'danger')

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
        new_username = form.username.data.strip()

        if new_username != user.username:
            existing = User.query.filter(
                User.username == new_username,
                User.id != user.id
            ).first()
            if existing:
                flash(f'Username "{new_username}" is already taken by another user.', 'danger')
                return render_template('edit_user.html', form=form, user=user)

        old_username = user.username
        user.username = new_username
        user.role    = form.role.data
        user.subject = form.subject.data or None
        user.set_classes_list(form.classes.data) if form.classes.data else setattr(user, 'classes', None)
        db.session.commit()

        change_note = f'Edited {old_username}'
        if new_username != old_username:
            change_note += f' (renamed to {new_username})'
        log_activity(current_user, 'edit_user', change_note)

        flash(f'User {user.username} updated', 'success')
        return redirect(url_for('users'))

    if request.method == 'GET':
        form.username.data = user.username
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
        new_hash = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user.password_hash = new_hash
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            app.logger.error(
                f'reset_password commit failed for user_id={user_id}: {exc}')
            flash('Password reset failed to save. Please try again.', 'danger')
            return render_template('reset_password.html', form=form, user=user)

        db.session.expire(user)
        confirmed_hash = db.session.get(User, user_id).password_hash
        if confirmed_hash != new_hash:
            app.logger.error(
                'reset_password verification mismatch for user_id=%s: ' \
                'hash on read-back does not match hash just written.', user_id)
            flash('Password reset could not be verified. Please try again.', 'danger')
            return render_template('reset_password.html', form=form, user=user)

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
        settings.school_name           = (form.school_name.data or '').strip() or None
        settings.school_address        = (form.school_address.data or '').strip() or None
        settings.school_phone          = (form.school_phone.data or '').strip() or None
        settings.school_email          = (form.school_email.data or '').strip() or None
        settings.school_gps_address    = (form.school_gps_address.data or '').strip() or None
        db.session.commit()
        flash('Settings updated', 'success')
        return redirect(url_for('admin_settings'))

    icp_active_count = (
        Assessment.query
        .filter(Assessment.category.in_(['icp1', 'icp2']), Assessment.archived == False)
        .count()
    )
    return render_template('admin_settings.html', form=form, settings=settings,
                           icp_active_count=icp_active_count)


@app.route('/admin/archive-icp-assessments', methods=['POST'])
@login_required
@admin_required
def archive_icp_assessments():
    """
    Bulk-archives every currently non-archived ICP1/ICP2 assessment
    record. These categories are supplementary/non-contributing and
    already excluded from new-entry forms and the "missing categories"
    tracker (see ACTIVE_CATEGORIES) — but any that were entered before
    that policy took effect still show up on current student/teacher/
    admin dashboards as real historical data, which is accurate but not
    what's wanted going forward.

    Archiving (not deleting) is deliberate: it's the exact mechanism
    this app already uses everywhere else for "old but don't destroy"
    (e.g. execute_promotion() on a class promotion) — the records stay
    fully intact for audit/export and remain individually restorable
    via the existing Archive view, they just stop appearing on the
    current-facing dashboards.
    """
    icp_assessments = (
        Assessment.query
        .filter(Assessment.category.in_(['icp1', 'icp2']), Assessment.archived == False)
        .all()
    )
    count = len(icp_assessments)
    for a in icp_assessments:
        a.archived = True
    db.session.commit()

    log_activity(
        current_user,
        'archive_icp_assessments',
        f'Bulk-archived {count} existing ICP1/ICP2 assessment record(s)'
    )
    flash(f'Archived {count} existing ICP1/ICP2 assessment record(s). '
          f'They remain visible and individually restorable from the Archive view.',
          'success')
    return redirect(url_for('admin_settings'))


@app.route('/admin/results-release', methods=['GET', 'POST'])
@login_required
@admin_required
def results_release():
    """
    Admin-only control panel for releasing results to the student portal.
    Students see nothing (results section is hidden) until either:
      - the admin clicks "Release Now", or
      - the scheduled release date/time has passed.
    """
    settings = Setting.query.first()
    if not settings:
        settings = Setting()
        db.session.add(settings)
        db.session.commit()

    form = ResultsReleaseForm()

    if request.method == 'POST':
        if not form.validate_on_submit():
            flash('Your session/token expired — please try again.', 'danger')
            return redirect(url_for('results_release'))

        action = request.form.get('action')

        if action == 'schedule':
            raw_value = (request.form.get('results_release_date') or '').strip()
            if not raw_value:
                flash('Please pick a date and time first.', 'danger')
                return redirect(url_for('results_release'))
            try:
                # Native <input type="datetime-local"> posts "YYYY-MM-DDTHH:MM"
                parsed = datetime.strptime(raw_value, '%Y-%m-%dT%H:%M')
            except ValueError:
                flash('That date/time could not be read. Please use the date picker.', 'danger')
                return redirect(url_for('results_release'))

            settings.results_release_date = parsed
            db.session.commit()
            log_activity(current_user, 'schedule_results_release',
                         f"Scheduled for {settings.results_release_date}")
            flash(f'Release scheduled for {parsed.strftime("%d %b %Y, %I:%M %p")}.', 'success')

        elif action == 'release_now':
            settings.release_now(admin_user=current_user)
            db.session.commit()
            log_activity(current_user, 'release_results_now', 'Results released manually')
            flash('Results have been released to students.', 'success')

        elif action == 'unrelease':
            settings.unrelease()
            db.session.commit()
            log_activity(current_user, 'unrelease_results', 'Results hidden from students')
            flash('Results have been hidden from students again.', 'warning')

        elif action == 'clear_schedule':
            settings.results_release_date = None
            db.session.commit()
            flash('Scheduled release date cleared.', 'info')

        else:
            flash('Unrecognized action.', 'danger')

        return redirect(url_for('results_release'))

    return render_template(
        'admin_results_release.html',
        settings=settings,
        form=form,
        is_visible=settings.is_results_visible()
    )


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
    from models import Student
    teachers = User.query.filter_by(role='teacher').all()
    teacher_assignments = {}
    for t in teachers:
        if t.subject:
            teacher_assignments[t.id] = {
                'teacher': t, 'subject': t.subject,
                'assigned_areas': t.get_assigned_study_areas(),
                'assigned_classes': t.get_classes_list(),
            }
    all_keys     = [a[0] for a in get_study_areas()]
    assigned_set = set()
    for v in teacher_assignments.values():
        assigned_set.update(v['assigned_areas'])

    # Students whose study_area doesn't match any currently-valid area
    # code. This catches students left behind by a curriculum update that
    # renamed or removed area codes (e.g. this app's own 'business_c' /
    # 'business_d' removal, or 'visual_performing_arts' splitting into
    # '_a'/'_b') — those students would otherwise silently stop appearing
    # in any teacher's authorised view (get_teacher_students_query only
    # matches a student to a teacher via a valid study_area), with no
    # visible error anywhere. They need a person to pick the correct new
    # area for them; there's no way to infer it automatically from the
    # old code alone.
    valid_keys = set(all_keys)
    orphaned_students = [
        s for s in Student.query.order_by(Student.class_name, Student.last_name).all()
        if s.study_area and s.study_area not in valid_keys
    ]

    return render_template('class_management.html',
                           study_areas=get_study_areas(),
                           study_area_subjects=get_study_area_subjects(),
                           orphaned_students=orphaned_students,
                           class_levels=app.config['CLASS_LEVELS'],
                           learning_areas=app.config['LEARNING_AREAS'],
                           teacher_assignments=teacher_assignments,
                           unassigned_areas=[a for a in all_keys
                                             if a not in assigned_set])


@app.route('/admin/class-register')
@login_required
@admin_required
def class_register():
    try:
        study_areas = get_study_areas() or []
        study_areas = [item for item in study_areas
                       if isinstance(item, (list, tuple)) and len(item) >= 2]

        form_levels = [k for k, _ in get_class_levels() if isinstance(k, str)]
        if not form_levels:
            form_levels = ['Unassigned']

        forms_data = {
            fl: {
                'total_students': 0,
                'study_areas': {},
                'classes': {},
            }
            for fl in form_levels
        }

        for fl in form_levels:
            for ak, an in study_areas:
                if ak is None:
                    continue
                forms_data[fl]['study_areas'][ak] = {
                    'name': an or ak,
                    'students': [],
                    'total_students': 0,
                }

        students = Student.query.all()
        default_bucket = form_levels[0]

        for s in students:
            cf = canonical_class_key(s.class_name)
            sf = cf if cf in forms_data else default_bucket

            sa = s.study_area or 'unassigned'
            study_area_bucket = forms_data[sf]['study_areas']
            if sa not in study_area_bucket:
                study_area_bucket[sa] = {
                    'name': sa.replace('_', ' ').title(),
                    'students': [],
                    'total_students': 0,
                }

            class_name = (s.class_name or 'Unassigned').strip() or 'Unassigned'
            class_group = forms_data[sf]['classes'].setdefault(
                class_name,
                {'name': class_name, 'student_count': 0, 'students': []}
            )
            class_group['students'].append(s)
            class_group['student_count'] += 1

            study_area_bucket[sa]['students'].append(s)
            study_area_bucket[sa]['total_students'] += 1
            forms_data[sf]['total_students'] += 1

        for fd in forms_data.values():
            for ad in fd['study_areas'].values():
                ad['students'].sort(
                    key=lambda s: ((s.class_name or '').lower(), s.last_name or '', s.first_name or '')
                )
            fd['classes'] = sorted(
                fd['classes'].values(),
                key=lambda c: (-c['student_count'], c['name'].lower())
            )

    except Exception:
        app.logger.exception('Failed to build class register payload')
        forms_data = {}
        study_areas = []

    return render_template('class_register.html',
                           forms_data=forms_data,
                           study_areas=study_areas,
                           study_area_subjects=get_study_area_subjects())


@app.route('/diagnostic/health')
def diagnostic_health():
    """
    Public liveness check — safe for uptime monitors / load balancers.
    Intentionally returns no environment info, counts, or error details;
    see /diagnostic/health/details (admin-only) for that.
    """
    try:
        db.session.execute(db.text('SELECT 1'))
        return jsonify({'status': 'ok'})
    except Exception:
        app.logger.exception('Health check failed')
        return jsonify({'status': 'error'}), 500


@app.route('/diagnostic/health/details')
@login_required
@admin_required
def diagnostic_health_details():
    from models import Student, User

    try:
        study_areas = get_study_areas() or []
        class_levels = get_class_levels() or []
        study_area_subjects = get_study_area_subjects() or {}

        return jsonify({
            'status': 'ok',
            'environment': {
                'flask_env': os.environ.get('FLASK_ENV'),
                'database_url_present': bool(os.environ.get('DATABASE_URL') or app.config.get('DATABASE_URL')),
                # NOTE: SECRET_KEY always has *some* value (config.py falls back to a
                # dev default), so "present" was always true and told us nothing.
                # This flags the actual risk: is it still the insecure default?
                'secret_key_is_default': app.config.get('SECRET_KEY') == 'dev-secret-key-CHANGE-IN-PRODUCTION',
            },
            'config': {
                'class_levels_count': len(class_levels),
                'study_areas_count': len(study_areas),
                'study_area_subjects_count': len(study_area_subjects),
            },
            'counts': {
                'students': Student.query.count(),
                'users': User.query.count(),
            },
        })
    except Exception:
        app.logger.exception('Diagnostic endpoint failed')
        return jsonify({
            'status': 'error',
            'message': 'Unable to collect diagnostic information',
            'details': traceback.format_exc().splitlines()[-1],
        }), 500


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


@app.route('/admin/api/refresh-study-areas', methods=['POST'])
@login_required
@admin_required
@csrf.exempt
def api_refresh_study_area_config():
    refresh_study_area_config()
    return jsonify({'success': True, 'message': 'STUDY_AREAS and STUDY_AREA_SUBJECTS refreshed from database.'})


@app.route('/admin/api/incomplete-assessments', methods=['GET', 'POST'])
@login_required
@admin_required
@csrf.exempt
def api_incomplete_assessments():
    """
    Live-refresh endpoint for the "Students Needing Attention" panel.

    get_incomplete_assessments() is cached for 5 minutes for normal page
    loads (dashboards are hit far more often than assessment data actually
    changes, and that cache is what keeps this affordable under real
    traffic — see the note on cache.cached() above). GET here just reads
    that same cache, so refreshing the panel is still cheap.

    POST additionally busts the cache first, so an admin who just knows a
    teacher entered new scores can force a genuinely live recount instead
    of waiting out the 5-minute window — this is the "Refresh" button's
    actual action, not just a page reload.
    """
    if request.method == 'POST':
        cache.delete('incomplete_assessments')

    incomplete = get_incomplete_assessments()
    category_labels = app.config.get('CATEGORY_LABELS', {})

    items_all = [{
        'student_id':     item['student'].id,
        'student_name':   item['student'].full_name(),
        'student_number': item['student'].student_number,
        'subject':        item['subject'],
        'missing_categories': [
            {'code': c, 'label': category_labels.get(c, c)}
            for c in item['missing_categories']
        ],
        'view_url': url_for('student_view', student_id=item['student'].id),
        'entry_url': url_for('new_assessment', student_id=item['student'].id),
    } for item in incomplete]

    # One card per (student, subject) in get_incomplete_assessments(), but
    # the dashboard groups by student — collapse here so the count shown
    # matches affected_students_count on the main dashboard exactly.
    affected_student_count = len({i['student_id'] for i in items_all})

    # Same 30-item cap as the initial server-rendered page (see dashboard()
    # above) — a "live" refresh shouldn't suddenly dump the whole school
    # onto the page just because it went through JS instead of a reload.
    items_all.sort(key=lambda i: i['student_name'])
    items = items_all[:30]

    return jsonify({
        'success': True,
        'count': affected_student_count,
        'total_count': len(items_all),
        'truncated': len(items_all) > len(items),
        'items': items,
        'refreshed_at': utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
    })


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


@app.route('/admin/apply-default-study-area-subjects', methods=['POST'])
@login_required
@admin_required
def apply_default_study_area_subjects():
    """
    Seed the STUDY_AREA_SUBJECTS config with the school's official
    subject allocation per study area, exactly as specified in the
    updated school curriculum document.
    """

    # ------------------------------------------------------------------
    # Common core subjects shared by most study areas
    # (Science A, Science B, and General Arts C are the exceptions —
    # they omit General Science, per the curriculum document)
    # ------------------------------------------------------------------
    COMMON_CORE = [
        'mathematics',
        'general_science',
        'social_studies',
        'english_language',
        'physical_education_health',
        'ict',
    ]

    SCIENCE_CORE = [
        'mathematics',
        'social_studies',
        'english_language',
        'physical_education_health',
        'ict',
    ]

    # ------------------------------------------------------------------
    # Full subject allocation — every study area from the updated document
    # ------------------------------------------------------------------
    sas = {

        # ── Visual and Performing Arts ─────────────────────────────────
        'visual_performing_arts_a': {
            'core': COMMON_CORE,
            'electives': [
                'arts_design_foundation',
                'arts_design_studio',
                'design_communication_technology',
                'music',
            ],
        },
        'visual_performing_arts_b': {
            'core': COMMON_CORE,
            'electives': [
                'clothing_textile',
                'arts_design_foundation',
                'arts_design_studio',
                'design_communication_technology',
            ],
        },

        # ── Home Economics ─────────────────────────────────────────────
        'home_economics_a': {
            'core': COMMON_CORE,
            'electives': [
                'management_in_living',
                'food_nutrition',
                'biology',
                'economics',
            ],
        },
        'home_economics_b': {
            'core': COMMON_CORE,
            'electives': [
                'management_in_living',
                'clothing_textile',
                'biology',
                'economics',
            ],
        },
        'home_economics_c': {
            'core': COMMON_CORE,
            'electives': [
                'management_in_living',
                'food_nutrition',
                'biology',
                'arts_design_studio',
            ],
        },
        'home_economics_d': {
            'core': COMMON_CORE,
            'electives': [
                'management_in_living',
                'clothing_textile',
                'biology',
                'arts_design_studio',
            ],
        },
        'home_economics_e': {
            'core': COMMON_CORE,
            'electives': [
                'management_in_living',
                'food_nutrition',
                'biology',
                'french',
            ],
        },
        'home_economics_f': {
            'core': COMMON_CORE,
            'electives': [
                'management_in_living',
                'clothing_textile',
                'biology',
                'french',
            ],
        },

        # ── Business ───────────────────────────────────────────────────
        # (business_c and business_d removed per the updated document)
        'business_a': {
            'core': COMMON_CORE,
            'electives': [
                'business_management',
                'accounting',
                'economics',
                'additional_mathematics',
                'geography',
            ],
        },
        'business_b': {
            'core': COMMON_CORE,
            'electives': [
                'business_management',
                'accounting',
                'economics',
                'computing_in_business',
                'geography',
            ],
        },

        # ── Science ────────────────────────────────────────────────────
        # NOTE: Science A and B do NOT have General Science as a core
        # subject (they study the individual sciences as electives instead)
        'science_a': {
            'core': SCIENCE_CORE,
            'electives': [
                'biology',
                'chemistry',
                'physics',
                'additional_mathematics',
                'economics',
            ],
        },
        'science_b': {
            'core': SCIENCE_CORE,
            'electives': [
                'biology',
                'chemistry',
                'physics',
                'additional_mathematics',
                'geography',
            ],
        },

        # ── General Arts ───────────────────────────────────────────────
        'general_arts_a': {
            'core': COMMON_CORE,
            'electives': [
                'lit_in_english',
                'christian_religious_studies',
                'history',
                'ghanaian_language',
            ],
        },
        'general_arts_b': {
            'core': COMMON_CORE,
            'electives': [
                'lit_in_english',
                'christian_religious_studies',
                'history',
                'french',
            ],
        },
        # General Arts C is the one General Arts variant without General
        # Science as a core subject, per the curriculum document.
        'general_arts_c': {
            'core': SCIENCE_CORE,
            'electives': [
                'geography',
                'economics',
                'government',
                'additional_mathematics',
            ],
        },
        'general_arts_d': {
            'core': COMMON_CORE,
            'electives': [
                'history',
                'music',
                'lit_in_english',
                'ghanaian_language',
            ],
        },
        'general_arts_e': {
            'core': COMMON_CORE,
            'electives': [
                'history',
                'music',
                'lit_in_english',
                'french',
            ],
        },
        'general_arts_f': {
            'core': COMMON_CORE,
            'electives': [
                'music',
                'economics',
                'geography',
                'ghanaian_language',
            ],
        },
        'general_arts_g': {
            'core': COMMON_CORE,
            'electives': [
                'music',
                'economics',
                'geography',
                'french',
            ],
        },
        'general_arts_h': {
            'core': COMMON_CORE,
            'electives': [
                'music',
                'history',
                'government',
                'ghanaian_language',
            ],
        },
        'general_arts_i': {
            'core': COMMON_CORE,
            'electives': [
                'music',
                'history',
                'government',
                'french',
            ],
        },
        'general_arts_j': {
            'core': COMMON_CORE,
            'electives': [
                'government',
                'economics',
                'biology',
                'christian_religious_studies',
            ],
        },
        'general_arts_k': {
            'core': COMMON_CORE,
            'electives': [
                'government',
                'economics',
                'management_in_living',
                'christian_religious_studies',
            ],
        },
    }

    SystemConfig.set_config('STUDY_AREA_SUBJECTS', sas)
    app.config['STUDY_AREA_SUBJECTS'] = sas

    # STUDY_AREAS itself (the area codes/labels, as opposed to their
    # subject allocation above) is ALSO cached in the database-backed
    # SystemConfig — see load_persistent_config() at startup, which loads
    # whatever is already stored there and would otherwise keep an
    # already-deployed installation on the old area list forever, no
    # matter what config.py says. Read the list from the Config class
    # directly here (not app.config['STUDY_AREAS'], which by this point
    # is whatever load_persistent_config() already loaded from the OLD
    # database row at startup — reading it back would just re-save the
    # stale list). Pushing the current code-defined list explicitly here,
    # in the same click as the subject allocation, keeps both in sync as
    # one atomic "apply the updated curriculum" action.
    from config import Config as _Config
    study_areas = _Config.STUDY_AREAS
    SystemConfig.set_config('STUDY_AREAS', study_areas)
    app.config['STUDY_AREAS'] = study_areas

    flash(
        f'Successfully loaded the school curriculum into {len(sas)} study areas.',
        'success'
    )
    log_activity(
        current_user,
        'apply_default_sas',
        f'Seeded {len(sas)} study areas with official school curriculum'
    )
    return redirect(url_for('manage_study_area_subjects_form'))


@app.route('/admin/study-area-subjects', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_study_area_subjects_form():
    """
    Full-page UI for configuring which subjects belong to each study area.
    This drives the teacher → student filtering logic throughout the app.
    POST handles add_core / add_elective / remove / clear_all actions.
    """
    if request.method == 'POST':
        area_key    = request.form.get('area_key', '').strip()
        subject_key = request.form.get('subject_key', '').strip()
        action      = request.form.get('action', '').strip()

        if not area_key:
            flash('Missing study area key.', 'danger')
            return redirect(url_for('manage_study_area_subjects_form'))

        sas = SystemConfig.get_config('STUDY_AREA_SUBJECTS', {})
        sas.setdefault(area_key, {'core': [], 'electives': []})
        cfg = sas[area_key]

        if action == 'clear_all':
            cfg['core']      = []
            cfg['electives'] = []
            SystemConfig.set_config('STUDY_AREA_SUBJECTS', sas)
            app.config['STUDY_AREA_SUBJECTS'] = sas
            flash(f'Cleared all subjects from {area_key}.', 'success')

        elif action in ('add_core', 'add_elective'):
            if not subject_key:
                flash('Please select a subject first.', 'warning')
                return redirect(url_for('manage_study_area_subjects_form'))

            bucket = 'core' if action == 'add_core' else 'electives'
            other  = 'electives' if bucket == 'core' else 'core'

            if subject_key in cfg.get(other, []):
                cfg[other].remove(subject_key)

            if subject_key not in cfg.get(bucket, []):
                cfg.setdefault(bucket, []).append(subject_key)
                SystemConfig.set_config('STUDY_AREA_SUBJECTS', sas)
                app.config['STUDY_AREA_SUBJECTS'] = sas
                flash(f'Subject added to {bucket} for {area_key}.', 'success')
            else:
                flash('Subject already assigned.', 'info')

        elif action == 'remove':
            if not subject_key:
                flash('No subject specified.', 'warning')
                return redirect(url_for('manage_study_area_subjects_form'))

            removed = False
            for bucket in ('core', 'electives'):
                if subject_key in cfg.get(bucket, []):
                    cfg[bucket].remove(subject_key)
                    removed = True

            if removed:
                SystemConfig.set_config('STUDY_AREA_SUBJECTS', sas)
                app.config['STUDY_AREA_SUBJECTS'] = sas
                flash('Subject removed.', 'success')
            else:
                flash('Subject not found in this area.', 'warning')
        else:
            flash('Unknown action.', 'danger')

        return redirect(url_for('manage_study_area_subjects_form'))

    sas = SystemConfig.get_config('STUDY_AREA_SUBJECTS', {})
    changed = False
    for area_key, _ in get_study_areas():
        if area_key not in sas:
            sas[area_key] = {'core': [], 'electives': []}
            changed = True
    if changed:
        SystemConfig.set_config('STUDY_AREA_SUBJECTS', sas)
        app.config['STUDY_AREA_SUBJECTS'] = sas

    learning_areas_dict = dict(app.config.get('LEARNING_AREAS', []))

    return render_template(
        'study_area_subjects.html',
        study_areas=get_study_areas(),
        study_area_subjects=sas,
        learning_areas=app.config.get('LEARNING_AREAS', []),
        learning_areas_dict=learning_areas_dict,
    )


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
    cache.delete("incomplete_assessments")
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
        question.updated_at     = utcnow()
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
# Quiz routes  (unchanged from original)
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
            started_at=utcnow(),
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
        attempt.completed_at   = utcnow()
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
            'completed_at': utcnow().timestamp(),
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
    quiz = db.session.get(Quiz, attempt.quiz_id)
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
# Export / Import / Download routes  (unchanged from original)
# ---------------------------------------------------------------------------
@app.route('/export/csv')
@login_required
def export_csv():
    if not (current_user.is_admin() or current_user.is_teacher()):
        abort(403)
    return redirect(url_for('export_assessments_excel'))


@app.route('/export/student/<int:student_id>/csv')
@login_required
def export_student_csv(student_id):
    if not (current_user.is_admin() or current_user.is_teacher()):
        abort(403)
    subject = request.args.get('subject')
    if subject:
        return redirect(url_for('export_student_excel', student_id=student_id, subject=subject))
    return redirect(url_for('export_student_excel', student_id=student_id))


@app.route('/export/excel/student/<int:student_id>')
@login_required
def export_student_excel(student_id):
    """Export one student's assessment record using the school template."""
    if not (current_user.is_admin() or current_user.is_teacher()):
        abort(403)
    student = Student.query.get_or_404(student_id)
    subject = request.args.get('subject')
    tpl_path = _get_assessment_template_path('student_template.xlsx')
    if not os.path.exists(tpl_path):
        flash('School template (student_template.xlsx) not found in templates_excel/. '
              'Please upload it via Admin → Settings.', 'danger')
        return redirect(url_for('student_view', student_id=student_id))

    sub_s = f'_{subject}' if subject else ''
    out_name = f'{student.student_number}_{student.last_name}_report{sub_s}.xlsx'
    out_path = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
    try:
        settings = Setting.query.first()
        exp_subj = (subject
                    or (current_user.subject if current_user.is_teacher() else None)
                    or student.study_area)
        upd = AssessmentTemplateUpdater(tpl_path)
        upd.load_template()
        upd.update_school_info(
            subject=exp_subj,
            term_year=(f'{settings.current_term} {settings.current_academic_year}'
                       if settings else ''),
            form=student.class_name)
        student_dict = student.to_template_dict(subject)
        student_dict['sheet_subject'] = exp_subj
        student_dict['sheet_class'] = student.class_name or ''
        upd.add_students_batch([student_dict], per_sheet=True)
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
    """Export all students via one sheet per subject/class using the school template."""
    if not (current_user.is_admin() or current_user.is_teacher()):
        abort(403)
    subject    = request.args.get('subject')
    class_name = request.args.get('class')

    if current_user.is_teacher():
        # Default this to the teacher's own subject/classes rather than the
        # whole school. Previously this route had no ownership scoping at
        # all — subject/class were the only filters, both optional — so a
        # teacher's plain "Export" link (no query params) pulled every
        # student in every class for every subject, one sheet per
        # subject+class. That's a privacy gap on its own (a teacher could
        # see other teachers' subjects/classes), and it's also exactly
        # what made the sheet-name-collision bug so likely to hit: more
        # subject+class combinations in one workbook means more chances
        # for two long names to truncate to the same 31-character sheet
        # name and silently lose data.
        #
        # get_teacher_students_query() is the same authorisation check
        # used elsewhere (class assignment + study-area match); reusing
        # it here keeps this route consistent with the rest of the app
        # rather than inventing a slightly different rule. It returns
        # None when the teacher isn't configured to access anything, in
        # which case this export should show nothing, not everything.
        q = get_teacher_students_query(current_user)
        if q is None:
            flash('You are not assigned to a subject/class, so there is nothing to export.', 'warning')
            return redirect(url_for('students'))

        # An explicit ?subject=/?class= is still honoured, but validated
        # against what this teacher is actually assigned — not trusted
        # as-is — so a teacher can't widen their own export by editing
        # the URL.
        if subject and subject != current_user.subject:
            abort(403)
        subject = current_user.subject

        teacher_classes = current_user.get_classes_list()
        if class_name and teacher_classes and class_name not in teacher_classes:
            abort(403)
    else:
        q = Student.query

    if subject:
        subq = (db.session.query(Assessment.student_id)
                .filter(Assessment.subject == subject).distinct())
        q = q.filter(Student.id.in_(subq))
    if class_name:
        q = q.filter_by(class_name=class_name)
    students_list = q.order_by(Student.last_name, Student.first_name).all()

    tpl_path = _get_assessment_template_path('student_template.xlsx')
    if not os.path.exists(tpl_path):
        flash('School template (student_template.xlsx) not found in templates_excel/. '
              'Please upload it via Admin → Settings.', 'danger')
        return redirect(url_for('students'))

    sub_s = subject or 'all_subjects'
    cls_s = class_name or 'all_classes'
    out_name = f'students_{sub_s}_{cls_s}_{datetime.now().strftime("%Y%m%d")}.xlsx'
    out_path = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
    try:
        settings = Setting.query.first()
        upd = AssessmentTemplateUpdater(tpl_path)
        upd.load_template()
        upd.export_by_subject_class(
            students_list,
            settings=settings,
            subject_filter=subject,
            class_filter=class_name)
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
    """Export filtered assessment records using the school template."""
    if not (current_user.is_admin() or current_user.is_teacher()):
        abort(403)
    subject    = request.args.get('subject', '').strip()
    class_name = request.args.get('class',   '').strip()
    category   = request.args.get('category','').strip()

    # Scope by what the teacher is AUTHORISED to see (their assigned
    # subject + classes) rather than by teacher_id on the Assessment row
    # itself. teacher_id only records who happened to type a given score
    # in — it is None for anything bulk-imported by an admin on a
    # teacher's behalf (see import_excel / import_class_scoresheet), and
    # it doesn't account for co-teaching/cover-teacher setups either. A
    # teacher_id filter here silently drops those rows from the export
    # even though the score is genuinely theirs, which is why teachers
    # were seeing scores that display correctly everywhere else (none of
    # which filter by teacher_id) but "go missing" only on this export.
    if current_user.is_teacher():
        q = Assessment.query.filter_by(archived=False)
        if current_user.subject:
            q = q.filter_by(subject=current_user.subject)
        teacher_classes = current_user.get_classes_list()
        if teacher_classes:
            q = q.filter(Assessment.class_name.in_(teacher_classes))
    else:
        q = Assessment.query.filter_by(archived=False)

    q = q.options(joinedload(Assessment.student))
    if subject:    q = q.filter_by(subject=subject)
    if class_name: q = q.filter_by(class_name=class_name)
    if category:   q = q.filter_by(category=category)
    assessments = q.order_by(Assessment.date_recorded.desc()).all()

    filters    = [f for f in [subject, class_name, category] if f]
    filter_str = '_'.join(filters) if filters else 'all'
    out_name   = f'assessments_{filter_str}_{datetime.now().strftime("%Y%m%d")}.xlsx'
    out_path   = os.path.join(app.config['UPLOAD_FOLDER'], out_name)

    tpl_path = _get_assessment_template_path('student_template.xlsx')
    if not os.path.exists(tpl_path):
        flash('School template (student_template.xlsx) not found in templates_excel/. '
              'Please upload it via Admin → Settings.', 'danger')
        return redirect(url_for('assessments_list'))
    try:
        settings = Setting.query.first()
        upd = AssessmentTemplateUpdater(tpl_path)
        upd.load_template()
        upd.export_assessments_raw(assessments, out_path, settings=settings)
        return send_file(out_path, as_attachment=True,
                         download_name=out_name,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as exc:
        flash(f'Error: {exc}', 'danger')
        return redirect(url_for('assessments_list'))


@app.route('/import/excel', methods=['GET', 'POST'])
@login_required
def import_excel():
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)

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
                    student = None
                    student_identifier = (data.get('student_number') or \
                                          data.get('reference_number') or '').strip()
                    if data.get('student_number'):
                        student = Student.query.filter_by(
                            student_number=data['student_number']).first()
                    if not student and data.get('reference_number'):
                        student = Student.query.filter_by(
                            reference_number=data['reference_number']).first()
                    if not student:
                        errors.append(f"Student {student_identifier or 'Unknown'} not found")
                        continue
                    if Assessment.query.filter_by(
                            student_id=student.id,
                            category=data['category'],
                            subject=data['subject'],
                            term=data['term'],
                            academic_year=data.get('academic_year'),
                            session=data['session']).first():
                        errors.append(f"Assessment already exists for {student_identifier or 'Unknown'}")
                        continue
                    db.session.add(Assessment(
                        student=student, category=data['category'],
                        subject=data['subject'],
                        class_name=student.class_name,
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
            cache.delete("incomplete_assessments")
            db.session.commit()
            try:
                os.remove(filepath)
            except OSError:
                pass
            flash(f'Imported {ok} assessments', 'success')
            if errors:
                flash(f'{len(errors)} errors: {"; ".join(errors[:5])}', 'warning')
            return redirect(url_for('assessments_list'))
        except Exception as exc:
            db.session.rollback()
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    pass
            flash(f'Error: {exc}', 'danger')
    return render_template('import_excel.html', form=form)


@app.route('/assessments/bulk_roster', methods=['GET'])
@login_required
def bulk_roster_form():
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)
    study_area_subjects = app.config.get('STUDY_AREA_SUBJECTS', {}) or {}
    subject_choices = []
    seen_subjects = set()
    for area_config in study_area_subjects.values():
        for group in ('core', 'electives'):
            for subject in (area_config.get(group) or []):
                if subject and subject not in seen_subjects:
                    seen_subjects.add(subject)
                    subject_choices.append(subject)

    return render_template(
        'bulk_roster_form.html',
        class_levels=app.config['CLASS_LEVELS'],
        study_areas=app.config['STUDY_AREAS'],
        study_area_subjects=study_area_subjects,
        subject_choices=subject_choices,
        terms=app.config['TERMS'],
        categories=[c for c in app.config['ASSESSMENT_CATEGORIES'] if c[0] in ACTIVE_CATEGORIES],
        default_assessor=(current_user.full_name() if hasattr(current_user, 'full_name') else current_user.username),
    )


@app.route('/assessments/bulk_roster/download', methods=['GET'])
@login_required
def bulk_roster_download():
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)

    class_name = request.args.get('class_name', '').strip()
    study_area = request.args.get('study_area', '').strip()
    subject = request.args.get('subject', '').strip()
    term = request.args.get('term', '').strip()
    academic_year = request.args.get('academic_year', '').strip()
    session_ = request.args.get('session', '').strip()
    category = request.args.get('category', '').strip()
    assessor = request.args.get('assessor', '').strip() or current_user.username

    if not (class_name and subject and category):
        flash('Class, Subject and Category are required.', 'danger')
        return redirect(url_for('bulk_roster_form'))
    if category not in app.config['ASSESSMENT_WEIGHTS']:
        flash('Invalid category selected.', 'danger')
        return redirect(url_for('bulk_roster_form'))

    q = Student.query.filter_by(class_name=class_name)
    if study_area:
        q = q.filter_by(study_area=study_area)
    students = q.order_by(Student.last_name, Student.first_name).all()
    if not students:
        flash('No students found for that class/study area.', 'warning')
        return redirect(url_for('bulk_roster_form'))

    filename = f"roster_{secure_filename(class_name)}_{category}.xlsx"
    output_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    create_prefilled_roster_template(
        output_path,
        students,
        subject=subject,
        class_name=class_name,
        term=term,
        academic_year=academic_year,
        session=session_,
        category=category,
        assessor=assessor,
    )
    return send_file(output_path, as_attachment=True, download_name=filename)


@app.route('/download/class-scoresheet')
@login_required
def download_class_scoresheet():
    """
    Download a class scoresheet template pre-filled with every student's
    number, name, reference number and study area for the selected class,
    with one blank column per assessment category. The teacher only has to
    type in scores and re-upload via /import/class-scoresheet.
    """
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)

    class_name = request.args.get('class_name', '').strip()
    subject    = request.args.get('subject', '').strip()

    if current_user.is_teacher():
        students_query = get_teacher_students_query(current_user)
        if students_query is None:
            flash('Your teacher profile has no class/subject configured yet.', 'warning')
            return redirect(url_for('import_class_scoresheet'))
    else:
        students_query = Student.query

    if class_name:
        students_query = students_query.filter_by(class_name=class_name)

    students = students_query.order_by(Student.last_name).all()
    if not students:
        flash('No students found for that class.', 'warning')
        return redirect(url_for('import_class_scoresheet'))

    out_name = f'class_scoresheet_{class_name or "all"}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    out_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(out_name))

    create_class_scoresheet_template(
        out_path,
        students=students,
        subject_label=subject,
        class_label=class_name,
        category_labels=app.config.get('CATEGORY_LABELS'),
    )

    return send_file(out_path, as_attachment=True, download_name=out_name,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/import/class-scoresheet', methods=['GET', 'POST'])
@login_required
def import_class_scoresheet():
    """
    Bulk-upload assessments for an entire class in one go: one row per
    student, one column per assessment category (ICA1, ICA2, ICP1, ICP2,
    GP1, GP2, Practical, Mid Term, End Term). Much faster than entering
    assessments one at a time, or uploading one row per category.
    """
    if not (current_user.is_teacher() or current_user.is_admin()):
        abort(403)

    form = ClassScoreSheetForm()
    settings = Setting.query.first()
    if request.method == 'GET':
        if current_user.is_teacher() and current_user.subject:
            form.subject.data = current_user.subject
        if settings:
            form.term.data          = settings.current_term
            form.academic_year.data = settings.current_academic_year
            form.session.data       = settings.current_session

    if form.validate_on_submit():
        file     = form.excel_file.data
        filepath = os.path.join(app.config['UPLOAD_FOLDER'],
                                secure_filename(file.filename))
        file.save(filepath)

        subject         = form.subject.data
        class_name      = form.class_name.data
        term            = form.term.data
        academic_year   = form.academic_year.data or (settings.current_academic_year if settings else None)
        session         = form.session.data or (settings.current_session if settings else None)
        update_existing = form.update_existing.data
        category_max    = app.config['CATEGORY_MAX_SCORES']

        try:
            rows = ClassScoreSheetImporter(filepath).import_scoresheet()
            students_ok = 0
            scores_ok   = 0
            errors      = []

            system_ids = {row['system_id'] for row in rows if row.get('system_id')}
            stu_numbers = {row['student_number'] for row in rows if row.get('student_number')}
            ref_numbers = {row['reference_number'] for row in rows if row.get('reference_number')}

            students_by_id = {
                s.id: s for s in Student.query.filter(Student.id.in_(system_ids)).all()
            } if system_ids else {}
            students_by_num = {
                s.student_number: s for s in Student.query.filter(Student.student_number.in_(stu_numbers)).all()
            } if stu_numbers else {}
            students_by_ref = {
                s.reference_number: s for s in Student.query.filter(Student.reference_number.in_(ref_numbers)).all()
            } if ref_numbers else {}

            all_student_ids = {
                *students_by_id.keys(),
                *[s.id for s in students_by_num.values()],
                *[s.id for s in students_by_ref.values()],
            }

            existing_map = {}
            if all_student_ids:
                # archived=False: same reasoning as new_assessment() above —
                # an archived row must not count as "existing" and block a
                # fresh bulk re-entry for that student/category/term.
                existing_assessments = Assessment.query.filter(
                    Assessment.student_id.in_(all_student_ids),
                    Assessment.subject == subject,
                    Assessment.term == term,
                    Assessment.academic_year == academic_year,
                    Assessment.session == session,
                    Assessment.archived == False,
                ).all()
                existing_map = {(a.student_id, a.category): a for a in existing_assessments}

            for row in rows:
                student = None
                identifier = row.get('student_number') or row.get('reference_number') or 'Unknown'
                if row.get('system_id'):
                    student = students_by_id.get(row['system_id'])
                if not student and row.get('student_number'):
                    student = students_by_num.get(row['student_number'])
                if not student and row.get('reference_number'):
                    student = students_by_ref.get(row['reference_number'])
                if not student:
                    errors.append(f"Student {identifier} not found")
                    continue

                if current_user.is_teacher() and not current_user.can_access_student(student, app.config):
                    errors.append(f"No permission to update {identifier}")
                    continue

                row_had_score = False
                for category, score in row['scores'].items():
                    max_score = category_max.get(category, 100.0)
                    if score < 0 or score > max_score:
                        errors.append(
                            f"{identifier}: {category} score {score} out of range (0-{max_score})"
                        )
                        continue

                    existing = existing_map.get((student.id, category))

                    if existing:
                        if update_existing:
                            existing.score = float(score)
                            existing.max_score = max_score
                            existing.assessor = current_user.username
                            existing.teacher_id = current_user.id if current_user.is_teacher() else existing.teacher_id
                            scores_ok += 1
                            row_had_score = True
                        else:
                            errors.append(f"{identifier}: {category} already recorded (skipped)")
                        continue

                    db.session.add(Assessment(
                        student=student, category=category, subject=subject,
                        class_name=class_name or student.class_name,
                        score=float(score), max_score=max_score,
                        term=term, academic_year=academic_year, session=session,
                        assessor=current_user.username,
                        teacher_id=current_user.id if current_user.is_teacher() else None,
                    ))
                    scores_ok += 1
                    row_had_score = True

                if row_had_score:
                    students_ok += 1

            cache.delete("incomplete_assessments")
            db.session.commit()
            try:
                os.remove(filepath)
            except OSError:
                pass

            log_activity(current_user, 'bulk_import_class_scoresheet',
                        f'Imported {scores_ok} scores for {students_ok} students '
                        f'({subject}, {class_name}, {term})')

            flash(f'Imported {scores_ok} score(s) across {students_ok} student(s).', 'success')
            if errors:
                flash(f'{len(errors)} issue(s): {"; ".join(errors[:5])}'
                     + (' ...' if len(errors) > 5 else ''), 'warning')
            return redirect(url_for('assessments_list'))

        except Exception as exc:
            db.session.rollback()
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    pass
            flash(f'Error: {exc}', 'danger')

    return render_template('class_scoresheet_import.html', form=form)


@app.route('/download/template/<template_type>')
@login_required
def download_template(template_type):
    mapping = {
        'student_import': ('student_import_template.xlsx', 'student_bulk_import_template.xlsx', create_student_import_template),
        'user_import':  ('user_import_template.xlsx',    'teacher_bulk_import_template.xlsx', create_teacher_import_template),
    }
    if template_type == 'student':
        tpl_path = _get_assessment_template_path('student_template.xlsx')
        if not os.path.exists(tpl_path):
            flash('School assessment template not found. Please upload student_template.xlsx via Admin → Settings.', 'danger')
            return redirect(url_for('admin_settings'))
        return send_file(tpl_path, as_attachment=True,
                         download_name='student_assessment_template.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    if template_type == 'import':
        tpl_path = os.path.join(app.config['TEMPLATE_FOLDER'], 'import_template.xlsx')
        if not os.path.exists(tpl_path):
            create_bulk_assessment_import_template(tpl_path)
        return send_file(tpl_path, as_attachment=True,
                         download_name='bulk_import_template.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    if template_type not in mapping:
        abort(404)

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
    """
    FIX: Teacher-scoped student search.  Teachers now only receive students
    from their authorised pool; the original returned all matching students
    regardless of the teacher's class/study-area assignment.
    """
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'results': []})

    if hasattr(current_user, 'is_teacher') and current_user.is_teacher():
        base_q = get_teacher_students_query(current_user)
        if base_q is None:
            return jsonify({'results': []})
    else:
        base_q = Student.query

    matches = base_q.filter(
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
    """
    FIX: Replaced the original three-branch teacher filter (which could
    fall through to returning all students when both classes and areas were
    empty) with get_teacher_students_query().
    """
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify({'results': []})

    if hasattr(current_user, 'is_teacher') and current_user.is_teacher():
        base_q = get_teacher_students_query(current_user)
        if base_q is None:
            return jsonify({'students': []})
    else:
        base_q = Student.query

    results = base_q.filter(
        db.or_(
            Student.student_number.ilike(f'%{query}%'),
            Student.first_name.ilike(f'%{query}%'),
            Student.last_name.ilike(f'%{query}%'),
            Student.reference_number.ilike(f'%{query}%'),
            Student.student_id_code.ilike(f'%{query}%'),
        )
    ).limit(10).all()

    return jsonify({'students': [
        {'id': s.id, 'name': s.full_name(),
         'student_number': s.student_number,
         'student_id': s.student_id_code,
         'class': s.get_class_display(),
         'url': url_for('student_view', student_id=s.id)}
        for s in results
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
# Admin: Teacher Assessment Tracking Dashboard
# ---------------------------------------------------------------------------
@app.route('/admin/teacher-tracking')
@login_required
@admin_required
def admin_teacher_tracking():
    """
    Admin dashboard showing, per teacher:
      • Overall completion % (progress bar)
      • Per-category filled / total students
      • Per-student breakdown (expandable)
      • Aggregated KPIs across all teachers
      • "Prompt teacher" button that pre-fills a reminder message
    """
    from sqlalchemy import func

    # ── Query params / filters ────────────────────────────────────────────
    selected_subject = request.args.get('subject', '').strip()
    selected_class   = request.args.get('class_filter', '').strip()
    selected_status  = request.args.get('status', '').strip()
    search_query     = request.args.get('search', '').strip()
    selected_subject_key = canonical_subject_key(selected_subject) if selected_subject else None

    # ── Required categories (same set used in get_incomplete_assessments) ─
    # ICP1/ICP2 are supplementary, non-contributing categories and are
    # excluded here as well, so completion percentages reflect only the
    # seven active grading components.
    REQUIRED_CATS = list(ACTIVE_CATEGORIES)
    n_required = len(REQUIRED_CATS)  # 7

    # ── Avatar colours (rotate by teacher id) ────────────────────────────
    AVATAR_COLORS = [
        '#4f8ef7', '#34d399', '#f59e0b', '#f87171',
        '#a78bfa', '#38bdf8', '#fb923c', '#e879f9',
    ]

    # ── Fetch all teachers ────────────────────────────────────────────────
    teacher_q = User.query.filter_by(role='teacher').order_by(User.username)
    if search_query:
        teacher_q = teacher_q.filter(User.username.ilike(f'%{search_query}%'))
    if selected_subject_key:
        teacher_q = teacher_q.filter_by(subject=selected_subject_key)
    teachers = teacher_q.all()

    # ── Build subject label map ───────────────────────────────────────────
    subject_label_map = dict(app.config.get('LEARNING_AREAS', []))

    # ── Prefetch students visible to each teacher ─────────────────────────
    # (moved ahead of the assessment prefetch below, since the assessment
    # query is now scoped by these student ids rather than by teacher_id)
    all_student_ids = set()
    teacher_student_ids = {}  # teacher_id → set of student ids
    for teacher in teachers:
        q = get_teacher_students_query(teacher)
        if q is None:
            teacher_student_ids[teacher.id] = set()
            continue
        if selected_class:
            q = q.filter_by(class_name=selected_class)
        sids = {s.id for s in q.with_entities(Student.id).all()}
        teacher_student_ids[teacher.id] = sids
        all_student_ids.update(sids)

    student_map = {
        s.id: s
        for s in Student.query.filter(Student.id.in_(all_student_ids)).all()
    } if all_student_ids else {}

    # ── Prefetch ALL non-archived assessments for these students ──────────
    # (avoids N+1 queries — we'll slice per teacher below)
    #
    # Scoped by student_id, NOT by Assessment.teacher_id.in_(teacher_ids).
    # teacher_id only records who happened to type a score in — it's None
    # for anything an admin bulk-imported or entered directly on a
    # teacher's behalf (see new_assessment() / import_class_scoresheet()),
    # and doesn't cover co-teaching either. Filtering by teacher_id here
    # meant any such score was invisible on this dashboard even though the
    # student genuinely had it recorded — a teacher's completion stats
    # (and this dashboard's own view of them) simply never picked it up.
    # Attribution to the right teacher row below already happens correctly
    # via each teacher's own `sids` (their authorised students), so no
    # teacher_id filter is needed to get the right teacher-to-score mapping.
    all_assessments = (
        Assessment.query
        .filter(
            Assessment.student_id.in_(all_student_ids),
            Assessment.archived == False,
        )
        .with_entities(
            Assessment.teacher_id,
            Assessment.student_id,
            Assessment.subject,
            Assessment.category,
            Assessment.date_recorded,
        )
        .all()
    ) if all_student_ids else []

    # Index: student_id → list of assessment rows
    from collections import defaultdict
    assess_by_student = defaultdict(list)
    for row in all_assessments:
        assess_by_student[row.student_id].append(row)

    # ── Build per-teacher data rows ───────────────────────────────────────
    teacher_rows = []
    agg_filed      = 0
    agg_missing    = 0
    agg_full       = 0
    agg_partial    = 0
    agg_none       = 0

    for teacher in teachers:
        sids        = teacher_student_ids.get(teacher.id, set())
        student_count = len(sids)

        # Assessments for students in this teacher's scope, from any
        # source (this teacher, an admin, a co-teacher) — see the prefetch
        # comment above for why this is no longer teacher_id-filtered.
        rows = [r for sid in sids for r in assess_by_student.get(sid, [])]
        if selected_subject_key:
            rows = [r for r in rows if canonical_subject_key(r.subject) == selected_subject_key]

        # Build: { student_id: { category: True } }
        stu_cats = defaultdict(set)
        for r in rows:
            stu_cats[r.student_id].add(r.category)

        # Category stats: { cat_key: { filled, total } }
        category_stats = {}
        for cat in REQUIRED_CATS:
            filled = sum(1 for sid in sids if cat in stu_cats[sid])
            category_stats[cat] = {'filled': filled, 'total': student_count}

        # Overall completion %
        total_slots  = student_count * n_required
        filled_slots = sum(len(stu_cats[sid] & set(REQUIRED_CATS)) for sid in sids)
        completion_pct = round((filled_slots / total_slots) * 100) if total_slots else 0

        # Per-student breakdown
        student_breakdown = []
        for sid in sorted(sids):
            s = student_map.get(sid)
            if not s:
                continue
            fc  = stu_cats[sid] & set(REQUIRED_CATS)
            pct = round((len(fc) / n_required) * 100)
            student_breakdown.append({
                'student': {
                    'id': s.id,
                    'full_name': s.full_name(),
                    'student_number': s.student_number,
                },
                'filled_cats': list(fc),
                'pct': pct,
            })
        # sort: incomplete first
        student_breakdown.sort(key=lambda x: x['pct'])

        # Missing categories (at least one student hasn't filled them)
        missing_cats = [
            cat for cat in REQUIRED_CATS
            if category_stats[cat]['filled'] < student_count
        ]

        # Student-level counts
        fully_complete_students = sum(
            1 for sid in sids
            if len(stu_cats[sid] & set(REQUIRED_CATS)) == n_required
        )
        incomplete_students = student_count - fully_complete_students

        # Last assessment date for this teacher
        dated = [r.date_recorded for r in rows if r.date_recorded]
        last_activity = max(dated) if dated else None

        agg_filed   += filled_slots
        agg_missing += (total_slots - filled_slots)
        if completion_pct == 100:
            agg_full += 1
        elif completion_pct > 0:
            agg_partial += 1
        else:
            agg_none += 1

        teacher_rows.append({
            'teacher': {
                'id': teacher.id,
                'username': teacher.username,
                'subject': teacher.subject,
            },
            'subject_label':           subject_label_map.get(teacher.subject or '', teacher.subject or '—'),
            'classes':                 teacher.get_classes_list(),
            'student_count':           student_count,
            'completion_pct':          completion_pct,
            'category_stats':          category_stats,
            'student_breakdown':       student_breakdown,
            'missing_categories':      missing_cats,
            'fully_complete_students': fully_complete_students,
            'incomplete_students':     incomplete_students,
            'last_activity':           last_activity.strftime('%Y-%m-%d %H:%M') if last_activity else None,
            'avatar_color':            AVATAR_COLORS[teacher.id % len(AVATAR_COLORS)],
        })

    # ── Apply completion-status filter ────────────────────────────────────
    if selected_status == 'complete':
        teacher_rows = [r for r in teacher_rows if r['completion_pct'] == 100]
    elif selected_status == 'partial':
        teacher_rows = [r for r in teacher_rows if 0 < r['completion_pct'] < 100]
    elif selected_status == 'not_started':
        teacher_rows = [r for r in teacher_rows if r['completion_pct'] == 0]

    # Sort: least complete first (most urgent at the top)
    teacher_rows.sort(key=lambda r: r['completion_pct'])

    stats = {
        'total_teachers':         len(teachers),
        'fully_complete':         agg_full,
        'partially_done':         agg_partial,
        'not_started':            agg_none,
        'total_assessments_filed': agg_filed,
        'total_missing_slots':    agg_missing,
    }

    # Friendly category labels for the template (ordered)
    category_labels = {k: v for k, v in CATEGORY_LABELS.items() if k in REQUIRED_CATS}

    return render_template(
        'teacher_assessment_tracker_dashboard.html',
        teacher_rows=teacher_rows,
        stats=stats,
        category_labels=category_labels,
        learning_areas=app.config.get('LEARNING_AREAS', []),
        class_levels=app.config.get('CLASS_LEVELS', []),
        selected_subject=selected_subject,
        selected_class=selected_class,
        selected_status=selected_status,
        search_query=search_query,
        REQUIRED_CATS=REQUIRED_CATS,
    )


# ---------------------------------------------------------------------------
# Admin: Send a prompt / reminder message to a teacher (from tracking board)
# ---------------------------------------------------------------------------
@app.route('/admin/send-prompt', methods=['POST'])
@login_required
@admin_required
def admin_send_prompt():
    """
    Sends a pre-filled reminder message from the Teacher Tracking dashboard
    directly to the teacher's inbox (re-uses the existing Message model).
    """
    json_data = request.get_json(silent=True)
    if json_data:
        teacher_id = json_data.get('teacher_id')
        message_text = (json_data.get('message') or '').strip()
    else:
        teacher_id = request.form.get('teacher_id', type=int)
        message_text = (request.form.get('message') or '').strip()

    try:
        if teacher_id is not None:
            teacher_id = int(teacher_id)
    except (TypeError, ValueError):
        teacher_id = None

    if not teacher_id or not message_text:
        if json_data:
            return jsonify({'success': False, 'message': 'Invalid prompt request.'}), 400
        flash('Invalid prompt request.', 'danger')
        return redirect(url_for('admin_teacher_tracking'))

    teacher = db.session.get(User, teacher_id)
    if not teacher or not teacher.is_teacher():
        if json_data:
            return jsonify({'success': False, 'message': 'Teacher not found.'}), 404
        flash('Teacher not found.', 'danger')
        return redirect(url_for('admin_teacher_tracking'))

    try:
        msg = Message(
            sender_id=current_user.id,
            recipient_id=teacher.id,
            subject='📋 Assessment Reminder — Action Required',
            content=message_text,
            message_type='alert',
            is_broadcast=False,
        )
        db.session.add(msg)
        db.session.commit()
        log_activity(
            current_user,
            'prompt_teacher',
            f'Sent assessment reminder to {teacher.username}',
        )
        if json_data:
            return jsonify({'success': True, 'message': f'Reminder sent to {teacher.username}.'})
        flash(f'Reminder sent to {teacher.username}.', 'success')
    except Exception as exc:
        db.session.rollback()
        app.logger.error('admin_send_prompt: %s', exc)
        if json_data:
            return jsonify({'success': False, 'message': 'Could not send message. Please try again.'}), 500
        flash('Could not send message. Please try again.', 'danger')

    return redirect(url_for('admin_teacher_tracking'))


# ---------------------------------------------------------------------------
# Messages routes  (unchanged from original)
# ---------------------------------------------------------------------------
@app.route('/messages')
@login_required
def user_messages():
    page = request.args.get('page', 1, type=int)
    messages = Message.query.filter_by(recipient_id=current_user.id).order_by(
        Message.created_at.desc()
    ).paginate(page=page, per_page=10)
    return render_template('user_messages.html', messages=messages)


@app.route('/messages/<int:message_id>')
@login_required
def view_message(message_id):
    message = Message.query.get_or_404(message_id)
    if message.recipient_id != current_user.id:
        abort(403)
    if not message.is_read:
        message.is_read = True
        db.session.commit()
    return render_template('view_message.html', message=message)


@app.route('/admin/messages')
@login_required
@admin_required
def admin_messages():
    page = request.args.get('page', 1, type=int)
    messages = Message.query.filter_by(sender_id=current_user.id).order_by(
        Message.created_at.desc()
    ).paginate(page=page, per_page=10)
    return render_template('admin_messages.html', messages=messages)


@app.route('/admin/messages/send', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_send_message():
    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        content = request.form.get('content', '').strip()
        recipient_type = request.form.get('recipient_type', 'all')

        if not subject or not content:
            flash('Subject and content are required', 'danger')
            return render_template('admin_send_message.html')

        # Student User accounts are created lazily — only the first time
        # a student actually logs in (see student_login()). A Student
        # with an academic record who has never logged in has no User
        # row at all, and Message.recipient_id is a foreign key to
        # User.id — so a broadcast could only ever reach whichever
        # students happened to have already logged in at least once,
        # silently dropping everyone else with no error or warning. Any
        # broadcast that includes students needs to close that gap first,
        # provisioning an account for every student who doesn't have one
        # yet, the same way student_login() does (username=student_number,
        # password defaulted to the student number) — so a message
        # actually reaches every current student, not just past logins.
        # ... (same reasoning as before: "anything other than 'teachers'
        # explicitly" includes students, matching the routing below exactly)
        if recipient_type != 'teachers':
            existing_usernames = {
                u.username for u in User.query.filter_by(role='student').all()
            }
            missing = (Student.query
                       .filter(Student.student_number.isnot(None))
                       .filter(~Student.student_number.in_(existing_usernames))
                       .all())
            created_count = 0
            for student in missing:
                snum = (student.student_number or '').strip()
                if not snum or snum in existing_usernames:
                    continue
                pw_hash = bcrypt.generate_password_hash(snum).decode('utf-8')
                db.session.add(User(username=snum, password_hash=pw_hash, role='student'))
                existing_usernames.add(snum)
                created_count += 1
            if created_count:
                db.session.commit()
                app.logger.info(
                    f'admin_send_message: provisioned {created_count} missing '
                    f'student account(s) before broadcast so delivery is not '
                    f'limited to students who had already logged in.'
                )

        if recipient_type == 'teachers':
            recipients = User.query.filter_by(role='teacher').all()
        elif recipient_type == 'students':
            recipients = User.query.filter_by(role='student').all()
        else:
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
            flash(f'Message sent to {len(recipients)} recipient(s)'
                  + (f' ({created_count} new student account(s) created to receive it)'
                     if recipient_type != 'teachers' and created_count else ''),
                  'success')
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
    print(f'Database    : {redact_database_url(app.config["SQLALCHEMY_DATABASE_URI"])}')
    print('Access at   : http://127.0.0.1:5000')
    print('=' * 60 + '\n')
    with app.app_context():
        db.create_all()
    app.run(debug=app.config.get('DEBUG', True),
            host='127.0.0.1', port=5000, use_reloader=False)
    