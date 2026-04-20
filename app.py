from db import db
import os
import openpyxl
from openpyxl.styles import PatternFill, Border, Side, Alignment, Font
from openpyxl.utils import get_column_letter
from template_updater import AssessmentTemplateUpdater

import io
import csv
import random
import re
import time
from functools import wraps
from werkzeug.utils import secure_filename
from datetime import datetime

from flask import Flask, render_template, redirect, url_for, flash, request, send_file, abort, jsonify, session
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from flask_wtf import FlaskForm, CSRFProtect
from flask_wtf.file import FileField, FileAllowed
from flask_wtf.csrf import generate_csrf
from flask_session import Session
from flask_migrate import Migrate
from wtforms import StringField, PasswordField, FloatField, SelectField, SelectMultipleField, DateField, TextAreaField, BooleanField
from wtforms.validators import InputRequired, Length, Optional, NumberRange

from config import config

# Define category labels for easy access
CATEGORY_LABELS = {
    'ica1': 'Individual Assessment 1',
    'ica2': 'Individual Assessment 2',
    'icp1': 'Individual Class Project 1',
    'icp2': 'Individual Class Project 2',
    'gp1': 'Group Project/Research 1',
    'gp2': 'Group Project/Research 2',
    'practical': 'Practical Portfolio',
    'mid_term': 'Mid-Semester Exam',
    'end_term': 'End of Term Exam'
}
from models import User, Student, Assessment, Setting, ActivityLog, Question, QuestionAttempt, Quiz, QuizAttempt, init_db
from excel_utils import ExcelTemplateHandler, ExcelBulkImporter, StudentBulkImporter, TeacherBulkImporter, QuestionBulkImporter, create_default_template, create_student_import_template, create_teacher_import_template, create_question_import_template

def get_incomplete_assessments():
    """Get students with incomplete assessments"""
    required_categories = ['ica1', 'ica2', 'icp1', 'icp2', 'gp1', 'gp2', 'practical', 'mid_term', 'end_term']
    
    # Get all students with assessments
    students_with_assessments = db.session.query(Student).join(Assessment)\
        .filter(Assessment.archived == False)\
        .distinct().all()
    
    incomplete_students = []
    
    for student in students_with_assessments:
        # Get all subjects this student has assessments in
        subjects = db.session.query(Assessment.subject)\
            .filter(Assessment.student_id == student.id)\
            .filter(Assessment.archived == False)\
            .distinct().all()
        
        subjects = [s[0] for s in subjects]
        
        for subject in subjects:
            # Get existing categories for this subject
            existing_categories = db.session.query(Assessment.category)\
                .filter(Assessment.student_id == student.id)\
                .filter(Assessment.subject == subject)\
                .filter(Assessment.archived == False)\
                .distinct().all()
            
            existing_categories = [c[0] for c in existing_categories]
            
            # Find missing categories
            missing_categories = [cat for cat in required_categories if cat not in existing_categories]
            
            if missing_categories:
                incomplete_students.append({
                    'student': student,
                    'subject': subject,
                    'missing_categories': missing_categories,
                    'existing_categories': existing_categories
                })
    
    return incomplete_students

# Application Factory
# -------------------------
app = Flask(__name__, static_folder='public')

# Load configuration
env = os.environ.get('FLASK_ENV', 'development')
app.config.from_object(config[env])

# Force SECRET_KEY directly from environment at runtime.
# This MUST come after from_object() so it always overrides the class-level value.
# Render injects env vars before the process starts, so this always works.
_secret_key = os.environ.get('SECRET_KEY', '').strip()
if _secret_key:
    app.secret_key = _secret_key
    app.config['SECRET_KEY'] = _secret_key
else:
    _fallback = 'fallback-dev-secret-do-not-use-in-production-xyz123'
    app.secret_key = _fallback
    app.config['SECRET_KEY'] = _fallback
    print(f"[WARNING] SECRET_KEY env var not found! Using fallback. Set SECRET_KEY in Render dashboard.")

# Get persistent directory from environment (default to local 'instance' for development)
persistent_dir = os.environ.get('PERSISTENT_DIR', os.path.join(os.path.dirname(__file__), 'instance'))

# File upload configuration - use persistent disk in production
app.config['UPLOAD_FOLDER'] = os.path.join(persistent_dir, 'uploads')
app.config['TEMPLATE_FOLDER'] = os.path.join(persistent_dir, 'templates_excel')
app.config['SESSION_FILE_DIR'] = os.path.join(persistent_dir, 'flask_sessions')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create necessary folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['TEMPLATE_FOLDER'], exist_ok=True)
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)

# -------------------------
# Extensions
# -------------------------
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None

# CSRF protection for all forms and POST endpoints
csrf = CSRFProtect(app)

# ensure csrf_token is available in templates even if CSRFProtect fails to register
@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf)

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

    form_map = {normalize_label(key): key for key, _ in app.config['CLASS_LEVELS']}
    form_map.update({normalize_label(label): key for key, label in app.config['CLASS_LEVELS']})
    numeric_map = {'1': 'Form 1', '2': 'Form 2', '3': 'Form 3'}

    if normalized in numeric_map:
        return numeric_map[normalized]
    return form_map.get(normalized)


def canonical_study_area_key(raw_value):
    normalized = normalize_label(raw_value)
    if not normalized:
        return None

    study_map = {normalize_label(key): key for key, _ in app.config['STUDY_AREAS']}
    study_map.update({normalize_label(label): key for key, label in app.config['STUDY_AREAS']})
    return study_map.get(normalized, normalized.replace(' ', '_') if normalized else None)


def canonical_subject_key(raw_value):
    normalized = normalize_label(raw_value)
    if not normalized:
        return None

    subject_map = {normalize_label(key): key for key, _ in app.config['LEARNING_AREAS']}
    subject_map.update({normalize_label(label): key for key, label in app.config['LEARNING_AREAS']})
    return subject_map.get(normalized, normalized.replace(' ', '_') if normalized else None)


def normalize_student_records():
    """Normalize existing student records for class and study area consistency."""
    students = Student.query.all()
    changed = False

    for student in students:
        canonical_class = canonical_class_key(student.class_name)
        canonical_area = canonical_study_area_key(student.study_area)

        if canonical_class and student.class_name != canonical_class:
            student.class_name = canonical_class
            changed = True

        if canonical_area and student.study_area != canonical_area:
            student.study_area = canonical_area
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

@app.route('/')
def index():
    if current_user.is_authenticated:
        if getattr(current_user, 'is_admin', lambda: False)():
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('teacher_dashboard'))
    return redirect(url_for('login'))

@app.route('/health')
def health():
    return {'status': 'ok'}, 200


def load_persistent_config():
    with app.app_context():
        try:
            from models import SystemConfig
            persistent_config = SystemConfig.get_all_configs()
            if persistent_config:
                app.config.update(persistent_config)
                print("[OK] Persistent config loaded")
        except Exception as e:
            print(f"[WARNING] Could not load persistent config: {e}")

# Initialize database
init_db(app, bcrypt)
load_persistent_config()

# Initialize Flask-Migrate
migrate = Migrate(app, db)

# Configure session
# IMPORTANT: Render free tier has an ephemeral filesystem — sessions written
# to disk are lost on every redeploy or restart. Use signed cookies instead.
if os.environ.get('FLASK_ENV') == 'production':
    # Production: secure signed cookies (no filesystem needed)
    app.config['SESSION_TYPE'] = 'null'
    app.config['SESSION_PERMANENT'] = False
    app.config['SESSION_USE_SIGNER'] = True
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    print(f"[OK] Session configured: cookie-based (production)")
else:
    # Development: filesystem sessions as before
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_PERMANENT'] = False
    app.config['SESSION_USE_SIGNER'] = False
    print(f"[OK] Session configured: filesystem (development)")
Session(app)