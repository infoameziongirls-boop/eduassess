from datetime import datetime, timezone
import os
import re
import time
import math
import secrets
import hashlib
from db import db
from flask_login import UserMixin
from sqlalchemy.exc import OperationalError
from sqlalchemy import inspect, text
import json

def utcnow():
    return datetime.now(timezone.utc)


class SubjectArea:
    CORE_SUBJECTS = ['Mathematics', 'English Language', 'General Science', 'Social Studies']
    SCIENCES = ['Biology', 'Chemistry', 'Physics', 'Additional Mathematics']
    ARTS_HUMANITIES = ['History', 'Geography', 'Economics', 'Government', 'Lit in English']
    BUSINESS = ['Business Management', 'Accounting', 'Computing in Business']


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default="teacher")
    subject = db.Column(db.String(100), nullable=True)
    class_name = db.Column(db.String(50), nullable=True)
    classes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    last_login = db.Column(db.DateTime, nullable=True)

    assessments = db.relationship(
        "Assessment",
        backref="assigned_teacher",
        foreign_keys="Assessment.teacher_id",
        lazy=True
    )

    def get_classes_list(self):
        if self.classes:
            try:
                return json.loads(self.classes)
            except json.JSONDecodeError:
                return []
        elif self.class_name:
            return [self.class_name]
        return []

    def set_classes_list(self, classes_list):
        if classes_list and isinstance(classes_list, list):
            self.classes = json.dumps(classes_list)
        else:
            self.classes = None

    def check_password(self, password, bcrypt):
        return bcrypt.check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.role == "admin"

    def is_teacher(self):
        return self.role == "teacher"

    def is_student(self):
        return self.role == "student"

    def is_parent(self):
        return self.role == "parent"

    def get_subject_display(self):
        if not self.subject:
            return None
        return self.subject.replace('_', ' ').title()

    def get_assigned_study_areas(self, config=None):
        if not self.subject or not self.is_teacher():
            return []

        if config is None:
            study_area_subjects = SystemConfig.get_config('STUDY_AREA_SUBJECTS', {})
        else:
            study_area_subjects = config.get('STUDY_AREA_SUBJECTS') if isinstance(config, dict) else config.get('STUDY_AREA_SUBJECTS')
            if not study_area_subjects:
                study_area_subjects = SystemConfig.get_config('STUDY_AREA_SUBJECTS', {})

        if not study_area_subjects:
            return []

        assigned_areas = []
        for area_key, subjects in study_area_subjects.items():
            if self.subject in subjects.get('core', []) or self.subject in subjects.get('electives', []):
                assigned_areas.append(area_key)
        return assigned_areas

    def can_access_student(self, student, config):
        if not self.is_teacher() or not self.subject:
            return False

        teacher_subject = (self.subject or '').strip()
        teacher_classes = self.get_classes_list()

        if teacher_classes and student.class_name not in teacher_classes:
            return False

        sas = {}
        try:
            sas = SystemConfig.get_config('STUDY_AREA_SUBJECTS', {})
        except Exception:
            pass

        if not sas and isinstance(config, dict):
            sas = config.get('STUDY_AREA_SUBJECTS', {}) or {}

        if sas:
            area_curriculum = sas.get(student.study_area or '', {})
            if teacher_subject not in area_curriculum.get('core', []) and \
                    teacher_subject not in area_curriculum.get('electives', []):
                return False

        return True

    def __repr__(self):
        return f"<User id={self.id}>"


class Student(UserMixin, db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    student_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    first_name = db.Column(db.String(120), nullable=False)
    last_name = db.Column(db.String(120), nullable=False)
    middle_name = db.Column(db.String(120), nullable=True)
    class_name = db.Column(db.String(50), nullable=True)
    reference_number = db.Column(db.String(50), unique=True, nullable=True, index=True)
    date_of_birth = db.Column(db.Date, nullable=True)
    study_area = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    assessments = db.relationship(
        "Assessment",
        backref="student",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="Assessment.date_recorded.desc()"
    )

    question_attempts = db.relationship(
        "QuestionAttempt",
        backref="student",
        cascade="all, delete-orphan",
        lazy=True
    )

    quiz_attempts = db.relationship(
        "QuizAttempt",
        backref="student",
        cascade="all, delete-orphan",
        lazy=True
    )

    def full_name(self):
        if self.middle_name:
            return f"{self.first_name} {self.middle_name} {self.last_name}"
        return f"{self.first_name} {self.last_name}"

    def get_class_display(self):
        if not self.class_name:
            return None
        # After data normalisation all values are canonical (e.g. 'Form 1')
        # Keep compact key fallback only as a safety net
        compact_map = {
            'form1': 'Form 1',
            'form2': 'Form 2',
            'form3': 'Form 3',
        }
        return compact_map.get(self.class_name.lower().replace(' ', ''), self.class_name)

    def get_study_area_display(self):
        if not self.study_area:
            return None
        return self.study_area.replace('_', ' ').title()

    def get_assessments_for_template(self, subject=None):
        query = Assessment.query.filter_by(student_id=self.id)
        if subject:
            query = query.filter_by(subject=subject)
        assessments = query.all()
        template_data = {
            'ica1': 0, 'ica2': 0, 'icp1': 0, 'icp2': 0,
            'gp1': 0, 'gp2': 0, 'practical': 0,
            'mid_term': 0, 'end_term': 0
        }
        for assessment in assessments:
            category = assessment.category
            if category in template_data:
                template_data[category] = assessment.score
        return template_data

    def get_assessment_summary(self, subject=None, teacher_id=None):
        assessments = self.assessments
        if subject:
            assessments = [a for a in assessments if a.subject == subject]
        if teacher_id:
            assessments = [a for a in assessments if a.teacher_id == teacher_id]
        summary = {}
        for assessment in assessments:
            cat = assessment.category
            if cat not in summary:
                summary[cat] = {"count": 0, "total_score": 0.0, "total_max": 0.0, "avg_percent": 0.0}
            summary[cat]["count"] += 1
            summary[cat]["total_score"] += assessment.score
            summary[cat]["total_max"] += assessment.max_score
        for cat, data in summary.items():
            if data["count"] > 0:
                total_percentage = 0.0
                for assessment in assessments:
                    if assessment.category == cat:
                        if assessment.max_score > 0:
                            total_percentage += (assessment.score / assessment.max_score) * 100
                data["avg_percent"] = total_percentage / data["count"]
        return summary

    def get_assessment_summary_from_list(self, assessment_list, subject=None, teacher_id=None):
        """
        Compute assessment summary from an already-fetched list,
        avoiding a second database round-trip.
        """
        filtered = assessment_list
        if subject:
            filtered = [a for a in filtered if a.subject == subject]
        if teacher_id:
            filtered = [a for a in filtered if a.teacher_id == teacher_id]
        summary = {}
        for assessment in filtered:
            cat = assessment.category
            if cat not in summary:
                summary[cat] = {"count": 0, "total_score": 0.0,
                                "total_max": 0.0, "avg_percent": 0.0}
            summary[cat]["count"]       += 1
            summary[cat]["total_score"] += assessment.score
            summary[cat]["total_max"]   += assessment.max_score
        for cat, data in summary.items():
            if data["count"] > 0:
                total_pct = sum(
                    (a.score / a.max_score) * 100
                    for a in filtered
                    if a.category == cat and a.max_score > 0
                )
                data["avg_percent"] = total_pct / data["count"]
        return summary

    def get_subject_summary(self, teacher_id=None):
        assessments = self.assessments
        if teacher_id:
            assessments = [a for a in assessments if a.teacher_id == teacher_id]
        summary = {}
        for assessment in assessments:
            subject = assessment.subject
            if subject not in summary:
                summary[subject] = {"count": 0, "total_score": 0.0, "total_max": 0.0, "avg_percent": 0.0, "assessments": []}
            summary[subject]["count"] += 1
            summary[subject]["total_score"] += assessment.score
            summary[subject]["total_max"] += assessment.max_score
            summary[subject]["assessments"].append(assessment)
        for subject, data in summary.items():
            if data["count"] > 0:
                data["avg_percent"] = data["total_score"] / data["count"]
        return summary

    def calculate_subject_final_grades(self, teacher_id=None):
        from app import GRADE_POINT_MAP, normalize_label
        from template_updater import calculate_scores_from_template, scores_from_assessments

        query = [a for a in self.assessments if not a.archived]
        if teacher_id:
            query = [a for a in query if a.teacher_id == teacher_id]

        subject_groups = {}
        for assessment in query:
            if not assessment.subject:
                continue
            subject_key = normalize_label(assessment.subject)
            if not subject_key:
                continue
            subject_groups.setdefault(subject_key, []).append(assessment)

        results = {}
        for subject_key, assessments in subject_groups.items():
            raw_scores = scores_from_assessments(assessments)
            if not raw_scores:
                continue
            result = calculate_scores_from_template(raw_scores)
            grade = result['grade']
            results[subject_key] = {
                'subject': assessments[0].subject,
                'subject_key': subject_key,
                'final_percent': float(result['final_score']),
                'grade': grade,
                'gpa': result['gpa'],
                'grade_point': GRADE_POINT_MAP.get(grade),
            }
        return results

    def calculate_final_grade(self, subject=None, teacher_id=None):
        from template_updater import calculate_scores_from_template, scores_from_assessments
        if subject:
            query = [a for a in self.assessments if not a.archived]
            query = [a for a in query if a.subject == subject]
            if teacher_id:
                query = [a for a in query if a.teacher_id == teacher_id]
            if not query:
                return None
            raw_scores = scores_from_assessments(query)
            if not raw_scores:
                return None
            result = calculate_scores_from_template(raw_scores)
            return float(result['final_score'])

        subject_results = self.calculate_subject_final_grades(teacher_id=teacher_id)
        if not subject_results:
            return None
        final_scores = [data['final_percent'] for data in subject_results.values()]
        if not final_scores:
            return None
        return round(sum(final_scores) / len(final_scores), 2)

    def get_gpa_and_grade(self, subject=None, teacher_id=None):
        final_score = self.calculate_final_grade(subject=subject, teacher_id=teacher_id)
        if final_score is None:
            return {'gpa': 'N/A', 'grade': 'N/A'}
        from app import calculate_gpa_and_grade
        return calculate_gpa_and_grade(final_score)

    def get_overall_summary(self, subject=None, teacher_id=None):
        from template_updater import (calculate_scores_from_template,
                                       scores_from_assessments, CATEGORY_MAX)
        query = [a for a in self.assessments if not a.archived]
        if subject:
            query = [a for a in query if a.subject == subject]
        if teacher_id:
            query = [a for a in query if a.teacher_id == teacher_id]

        empty = {
            'ica1': 0, 'ica2': 0, 'ica_total': 0,
            'icp1': 0, 'icp2': 0, 'icp_total': 0,
            'gp1':  0, 'gp2':  0, 'gp_total':  0,
            'practical': 0, 'mid_term': 0,
            'total_class_score': 0, 'pct_100': 0, 'avg_class_score': 0,
            'end_term': 0, 'avg_exam_score': 0,
            'final_score': 0, 'percentage': 0,
            'gpa': 'N/A', 'grade': 'N/A',
            'has_data': False,
        }
        if not query:
            return empty
        raw_scores = scores_from_assessments(query)
        if not raw_scores:
            return empty
        result = calculate_scores_from_template(raw_scores)
        return {
            'ica1':              raw_scores.get('ica1', 0),
            'ica2':              raw_scores.get('ica2', 0),
            'ica_total':         result['ica_total'],
            'icp1':              raw_scores.get('icp1', 0),
            'icp2':              raw_scores.get('icp2', 0),
            'icp_total':         result['icp_total'],
            'gp1':               raw_scores.get('gp1', 0),
            'gp2':               raw_scores.get('gp2', 0),
            'gp_total':          result['gp_total'],
            'practical':         raw_scores.get('practical', 0),
            'mid_term':          raw_scores.get('mid_term', 0),
            'total_class_score': result['total_class_score'],
            'pct_100':           result['pct_100'],
            'avg_class_score':   result['avg_class_score'],
            'end_term':          raw_scores.get('end_term', 0),
            'avg_exam_score':    result['avg_exam_score'],
            'final_score':       result['final_score'],
            'percentage':        result['percentage'],
            'gpa':               result['gpa'],
            'grade':             result['grade'],
            'has_data':          True,
        }

    def to_template_dict(self, subject=None):
        from template_updater import scores_from_assessments, CATEGORY_MAX
        query = [a for a in self.assessments if not a.archived]
        if subject:
            query = [a for a in query if a.subject == subject]
        raw = scores_from_assessments(query)
        return {
            'student_number': self.student_number or '',
            'last_name':      self.last_name or '',
            'first_name':     self.first_name or '',
            'middle_name':    self.middle_name or '',
            'ref_id':         self.reference_number or '',
            'study_area':     self.get_study_area_display() or '',
            'ica1':           raw.get('ica1',      0),
            'ica2':           raw.get('ica2',      0),
            'icp1':           raw.get('icp1',      0),
            'icp2':           raw.get('icp2',      0),
            'gp1':            raw.get('gp1',       0),
            'gp2':            raw.get('gp2',       0),
            'practical':      raw.get('practical', 0),
            'mid_term':       raw.get('mid_term',  0),
            'end_term':       raw.get('end_term',  0),
        }


class Assessment(db.Model):
    __tablename__ = "assessments"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    category = db.Column(db.String(20), nullable=False, index=True)
    subject = db.Column(db.String(120), nullable=False, index=True)
    class_name = db.Column(db.String(50), nullable=True, index=True)
    score = db.Column(db.Float, nullable=False)
    max_score = db.Column(db.Float, nullable=False, default=100.0)
    term = db.Column(db.String(32), nullable=True)
    academic_year = db.Column(db.String(32), nullable=True)
    session = db.Column(db.String(32), nullable=True)
    assessor = db.Column(db.String(120), nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    comments = db.Column(db.Text, nullable=True)
    date_recorded = db.Column(db.DateTime, default=utcnow, index=True)
    archived = db.Column(db.Boolean, default=False, index=True)

    def get_percentage(self):
        if self.max_score and self.max_score > 0:
            return round((self.score / self.max_score) * 100, 2)
        return 0.0

    def get_grade_letter(self):
        percentage = self.get_percentage()
        if percentage >= 90:   return "A+"
        elif percentage >= 80: return "A"
        elif percentage >= 75: return "B+"
        elif percentage >= 70: return "B"
        elif percentage >= 65: return "C+"
        elif percentage >= 60: return "C"
        elif percentage >= 55: return "D+"
        elif percentage >= 50: return "D"
        else:                  return "F"

    def get_grade_point(self):
        percentage = self.get_percentage()
        if percentage >= 80:   return 4.0
        elif percentage >= 75: return 3.5
        elif percentage >= 70: return 3.0
        elif percentage >= 65: return 2.5
        elif percentage >= 60: return 2.0
        elif percentage >= 55: return 1.5
        elif percentage >= 50: return 1.0
        else:                  return 0.0

    def get_subject_display(self):
        return self.subject.replace('_', ' ').title()

    def __repr__(self):
        return f"<Assessment {self.category} - {self.subject}: {self.score}/{self.max_score}>"


class APIKey(db.Model):
    """Bearer token for the external results-entry API (see
    EXTERNAL_RESULTS_API_INTEGRATION.md). Only a SHA-256 hash of the key is
    ever stored — the raw key is generated once (via `flask create-api-key`),
    shown to the operator on the terminal, and cannot be recovered from the
    database afterwards. Rotate a compromised key by deactivating it and
    generating a new one, rather than trying to change the stored value."""
    __tablename__ = "api_keys"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    key_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    key_prefix = db.Column(db.String(12), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    last_used_at = db.Column(db.DateTime, nullable=True)

    owner = db.relationship("User", foreign_keys=[user_id])

    @staticmethod
    def hash_key(raw_key):
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    @classmethod
    def generate(cls, name, user=None):
        """Create and persist a new key, returning (APIKey, raw_key). The
        raw key is only ever available here — the caller must display it
        immediately, it is never stored or retrievable again."""
        raw_key = secrets.token_urlsafe(32)
        api_key = cls(
            name=name,
            key_hash=cls.hash_key(raw_key),
            key_prefix=raw_key[:8],
            user_id=user.id if user else None,
        )
        db.session.add(api_key)
        db.session.commit()
        return api_key, raw_key

    def touch(self):
        self.last_used_at = utcnow()

    def __repr__(self):
        return f"<APIKey {self.key_prefix}... name={self.name!r} active={self.is_active}>"


class Setting(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    current_term = db.Column(db.String(32), nullable=False, default='term1')
    current_academic_year = db.Column(db.String(32), nullable=False, default='2024-2025')
    current_session = db.Column(db.String(32), nullable=False, default='First Term')
    assessment_active = db.Column(db.Boolean, default=True)

    # ------------------------------------------------------------------ #
    # Results release control
    #   - results_released:      manual admin override switch. If True,
    #                             results are visible regardless of the
    #                             scheduled date.
    #   - results_release_date:  optional future datetime (UTC). Once
    #                             "now" passes this, results become
    #                             visible automatically even if the admin
    #                             never flips the manual switch.
    #   - results_released_at:   audit timestamp of when results actually
    #                             became visible (set the moment either
    #                             the manual switch is flipped on or the
    #                             scheduled date is first observed to have
    #                             passed).
    #   - results_released_by:   admin user who triggered the manual
    #                             release ("Release Now"). Null if the
    #                             release happened purely via the
    #                             scheduled date.
    # ------------------------------------------------------------------ #
    results_released = db.Column(db.Boolean, nullable=False, default=False)
    results_release_date = db.Column(db.DateTime, nullable=True)
    results_released_at = db.Column(db.DateTime, nullable=True)
    results_released_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    releaser = db.relationship("User", foreign_keys=[results_released_by])

    def is_results_visible(self):
        """True if students should currently be able to see their results."""
        if self.results_released:
            return True
        if self.results_release_date and utcnow() >= self._aware(self.results_release_date):
            return True
        return False

    @staticmethod
    def _aware(dt):
        """Treat naive datetimes stored in the DB as UTC for comparison."""
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    def release_now(self, admin_user=None):
        """Manually release results immediately."""
        self.results_released = True
        self.results_released_at = utcnow()
        self.results_released_by = admin_user.id if admin_user else None

    def unrelease(self):
        """Hide results again (manual switch off). Does not clear the
        scheduled date — if that date has already passed, results will
        still show as released via is_results_visible()."""
        self.results_released = False
        self.results_released_at = None
        self.results_released_by = None

    def __repr__(self):
        return f"<Setting term={self.current_term}, year={self.current_academic_year}>"


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    timestamp = db.Column(db.DateTime, default=utcnow, index=True)

    user = db.relationship(
        "User",
        foreign_keys=[user_id],
        backref=db.backref("activity_logs", lazy="dynamic", cascade="all, delete-orphan"),
    )

    def __repr__(self):
        username = self.user.username if self.user else "Unknown"
        return f"<ActivityLog {username} - {self.action} at {self.timestamp}>"


class Question(db.Model):
    __tablename__ = "questions"

    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(120), nullable=False, index=True)
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(20), nullable=False, default="mcq")
    options = db.Column(db.JSON, nullable=True)
    correct_answer = db.Column(db.String(500), nullable=False)
    marks = db.Column(db.Float, nullable=False, default=1.0)
    keywords = db.Column(db.JSON, nullable=True)
    difficulty = db.Column(db.String(20), nullable=False, default="medium")
    explanation = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")
    rejection_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    creator = db.relationship("User", foreign_keys=[created_by], backref="created_questions")
    approver = db.relationship("User", foreign_keys=[approved_by], backref="approved_questions")

    def is_approved(self):
        return self.status == "approved"

    def can_edit(self, user):
        if user.is_admin():
            return True
        if user.is_teacher() and user.id == self.created_by and self.status == "pending":
            return True
        return False

    def can_approve(self, user):
        return user.is_admin() or (user.is_teacher() and user.subject == self.subject)

    def get_subject_display(self):
        return self.subject.replace('_', ' ').title()

    @property
    def normalized_options(self):
        if not self.options:
            return []
        if isinstance(self.options, list):
            return self.options
        if isinstance(self.options, str):
            return [line.strip() for line in self.options.split('\n') if line.strip()]
        return []

    def __repr__(self):
        return f"<Question {self.id} - {self.subject}: {self.question_text[:50]}...>"


class QuestionAttempt(db.Model):
    __tablename__ = "question_attempts"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    quiz_attempt_id = db.Column(db.Integer, db.ForeignKey("quiz_attempts.id"), nullable=True)
    student_answer = db.Column(db.String(500), nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False)
    score = db.Column(db.Float, nullable=False, default=0.0)
    attempted_at = db.Column(db.DateTime, default=utcnow)
    time_taken = db.Column(db.Integer, nullable=True)

    question = db.relationship("Question", backref="attempts")

    def __repr__(self):
        return f"<QuestionAttempt student={self.student_id} question={self.question_id} correct={self.is_correct}>"


class Quiz(db.Model):
    __tablename__ = "quizzes"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    subject = db.Column(db.String(120), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    questions = db.Column(db.JSON, nullable=False)
    time_limit = db.Column(db.Integer, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    creator = db.relationship("User", foreign_keys=[created_by], backref="created_quizzes")

    def get_subject_display(self):
        return self.subject.replace('_', ' ').title()

    def __repr__(self):
        return f"<Quiz {self.title} - {self.subject}>"


class QuizAttempt(db.Model):
    __tablename__ = "quiz_attempts"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quizzes.id"), nullable=False)
    score = db.Column(db.Float, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    correct_answers = db.Column(db.Integer, nullable=False)
    started_at = db.Column(db.DateTime, default=utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    time_taken = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), default="in_progress")
    answers_json = db.Column(db.Text, nullable=True)
    remaining_time = db.Column(db.Integer, nullable=True)

    quiz = db.relationship("Quiz", backref="attempts")

    def get_percentage(self):
        if self.total_questions > 0:
            return (self.correct_answers / self.total_questions) * 100
        return 0

    def __repr__(self):
        return f"<QuizAttempt student={self.student_id} quiz={self.quiz_id} score={self.score}>"


class SystemConfig(db.Model):
    __tablename__ = 'system_config'
    id = db.Column(db.Integer, primary_key=True)
    config_key = db.Column(db.String(100), unique=True, nullable=False)
    config_value = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    @staticmethod
    def get_config(key, default=None):
        config_entry = SystemConfig.query.filter_by(config_key=key).first()
        if config_entry:
            try:
                return json.loads(config_entry.config_value)
            except json.JSONDecodeError:
                return config_entry.config_value
        return default

    @staticmethod
    def set_config(key, value):
        config_entry = SystemConfig.query.filter_by(config_key=key).first()
        if config_entry:
            config_entry.config_value = json.dumps(value) if not isinstance(value, str) else value
        else:
            config_entry = SystemConfig(
                config_key=key,
                config_value=json.dumps(value) if not isinstance(value, str) else value
            )
            db.session.add(config_entry)
        db.session.commit()
        return value

    @staticmethod
    def get_all_configs():
        configs = {}
        for config_entry in SystemConfig.query.all():
            try:
                configs[config_entry.config_key] = json.loads(config_entry.config_value)
            except json.JSONDecodeError:
                configs[config_entry.config_key] = config_entry.config_value
        return configs


# --------------------------------------------------------------------------- #
#  Association table  (must appear BEFORE Parent model)
# --------------------------------------------------------------------------- #

parent_student = db.Table(
    "parent_student",
    db.Column("parent_id",  db.Integer, db.ForeignKey("parents.id"),  primary_key=True),
    db.Column("student_id", db.Integer, db.ForeignKey("students.id"), primary_key=True),
)


class Parent(db.Model):
    __tablename__ = "parents"

    id      = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    students = db.relationship("Student", secondary=parent_student, backref="parents")


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    message_type = db.Column(db.String(20), default="notification")  # notification, update, alert
    is_read = db.Column(db.Boolean, default=False)
    is_broadcast = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    sender = db.relationship("User", foreign_keys=[sender_id], backref="sent_messages")
    recipient = db.relationship("User", foreign_keys=[recipient_id], backref="received_messages")

    def __repr__(self):
        return f"<Message id={self.id} subject='{self.subject}'>"


class SupportTicket(db.Model):
    __tablename__ = "support_tickets"

    id            = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    user_id       = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    subject       = db.Column(db.String(200), nullable=False)
    description   = db.Column(db.Text, nullable=False)
    category      = db.Column(db.String(50), nullable=False, default="general")
    priority      = db.Column(db.String(20), nullable=False, default="medium")
    status        = db.Column(db.String(20), nullable=False, default="open", index=True)
    assigned_to   = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    browser_info  = db.Column(db.String(300), nullable=True)
    page_url      = db.Column(db.String(500), nullable=True)
    created_at    = db.Column(db.DateTime, default=utcnow, index=True)
    updated_at    = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    resolved_at   = db.Column(db.DateTime, nullable=True)

    submitter    = db.relationship("User", foreign_keys=[user_id],  backref="submitted_tickets")
    assignee     = db.relationship("User", foreign_keys=[assigned_to], backref="assigned_tickets")
    replies      = db.relationship("TicketReply", backref="ticket",
                                   cascade="all, delete-orphan",
                                   order_by="TicketReply.created_at")

    CATEGORIES = [
        ("bug",          "Bug / Error"),
        ("access",       "Login / Access Issue"),
        ("data",         "Data / Assessment Issue"),
        ("performance",  "Performance Problem"),
        ("feature",      "Feature Request"),
        ("general",      "General Enquiry"),
    ]

    PRIORITIES = [
        ("low",      "Low"),
        ("medium",   "Medium"),
        ("high",     "High"),
        ("critical", "Critical"),
    ]

    STATUSES = [
        ("open",        "Open"),
        ("in_progress", "In Progress"),
        ("waiting",     "Waiting on User"),
        ("resolved",    "Resolved"),
        ("closed",      "Closed"),
    ]

    def priority_color(self):
        return {"low": "success", "medium": "warning",
                "high": "danger", "critical": "dark"}.get(self.priority, "secondary")

    def status_color(self):
        return {"open": "primary", "in_progress": "info",
                "waiting": "warning", "resolved": "success",
                "closed": "secondary"}.get(self.status, "secondary")

    def __repr__(self):
        return f"<SupportTicket {self.ticket_number} – {self.status}>"


class TicketReply(db.Model):
    __tablename__ = "ticket_replies"

    id         = db.Column(db.Integer, primary_key=True)
    ticket_id  = db.Column(db.Integer, db.ForeignKey("support_tickets.id"),
                           nullable=False, index=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    message    = db.Column(db.Text, nullable=False)
    is_internal = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    author = db.relationship("User", foreign_keys=[user_id], backref="ticket_replies")

    def __repr__(self):
        return f"<TicketReply ticket={self.ticket_id} by user={self.user_id}>"


def ensure_default_admin_user(app, bcrypt):
    with app.app_context():
        default_username = app.config.get("DEFAULT_ADMIN_USERNAME", "admin")
        default_password = app.config.get("DEFAULT_ADMIN_PASSWORD", "Admin@123")

        admin = User.query.filter_by(username=default_username).first()
        if admin is None:
            hashed = bcrypt.generate_password_hash(default_password).decode("utf-8")
            admin = User(
                username=default_username,
                password_hash=hashed,
                role="admin"
            )
            db.session.add(admin)
            db.session.commit()
            print(f"Created default admin account: {default_username}")
            return admin

        if admin.role != "admin":
            admin.role = "admin"
            if not admin.password_hash:
                admin.password_hash = bcrypt.generate_password_hash(default_password).decode("utf-8")
            db.session.commit()
            print(f"Upgraded existing user to admin: {default_username}")

        if not admin.password_hash:
            admin.password_hash = bcrypt.generate_password_hash(default_password).decode("utf-8")
            db.session.commit()

        return admin


def ensure_settings_columns():
    """
    Safely add the results-release columns to an existing settings table.

    Must use the correct type name for whichever database is connected —
    Postgres/Neon does NOT understand "DATETIME" (that's SQLite's
    spelling; Postgres uses "TIMESTAMP") — and must never let a migration
    hiccup crash app boot, since this runs on every startup via init_db().
    """
    try:
        inspector = inspect(db.engine)
        if not inspector.has_table('settings'):
            return

        dialect = db.engine.dialect.name  # 'postgresql' or 'sqlite'
        columns = {column['name'] for column in inspector.get_columns('settings')}

        if dialect == 'postgresql':
            type_map = {
                'results_released':     'BOOLEAN DEFAULT FALSE',
                'results_release_date': 'TIMESTAMP',
                'results_released_at':  'TIMESTAMP',
                'results_released_by':  'INTEGER',
            }
        else:
            type_map = {
                'results_released':     'BOOLEAN DEFAULT 0',
                'results_release_date': 'DATETIME',
                'results_released_at':  'DATETIME',
                'results_released_by':  'INTEGER',
            }

        for column_name, column_type in type_map.items():
            if column_name in columns:
                continue
            db.session.execute(text(f'ALTER TABLE settings ADD COLUMN {column_name} {column_type}'))

        db.session.commit()

        db.session.execute(text(
            "UPDATE settings SET results_released = FALSE WHERE results_released IS NULL"
            if dialect == 'postgresql' else
            "UPDATE settings SET results_released = 0 WHERE results_released IS NULL"
        ))
        db.session.commit()

    except Exception as exc:
        # Never let a migration hiccup crash app boot / cause a restart
        # loop. Log it and let the app start anyway.
        db.session.rollback()
        print(f"[ensure_settings_columns] WARNING: could not sync columns: {exc}")


def init_db(app, bcrypt):
    if not app.extensions.get('sqlalchemy'):
        db.init_app(app)

    with app.app_context():
        print(f"Initializing database at: {app.config['SQLALCHEMY_DATABASE_URI']}")

        ext = app.extensions.get('sqlalchemy')
        if ext:
            try:
                ext._app_engines[app].clear()
            except Exception:
                pass
            try:
                options = {'url': app.config['SQLALCHEMY_DATABASE_URI'], **ext._engine_options}
                engine = ext._make_engine(None, options, app)
                ext._app_engines[app][None] = engine
            except Exception:
                pass

        max_retries = 5
        for attempt in range(max_retries):
            try:
                db.create_all()
                print("Database tables created successfully")
                break
            except OperationalError as e:
                if attempt == max_retries - 1:
                    print(f"Failed to connect to database after {max_retries} attempts")
                    raise
                print(f"Database not ready, retrying in 2 seconds... ({attempt+1}/{max_retries})")
                time.sleep(2)

        ensure_settings_columns()

        if not Setting.query.first():
            default_settings = Setting(
                current_term='term1',
                current_academic_year='2024-2025',
                current_session='First Term'
            )
            db.session.add(default_settings)
            db.session.commit()
            print("Default settings created")

        ensure_default_admin_user(app, bcrypt)
