from datetime import datetime
import os
import time
import math
from db import db
from flask_login import UserMixin
from sqlalchemy.exc import OperationalError
import json


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
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

    def get_assigned_study_areas(self, config):
        if not self.subject or not self.is_teacher():
            return []
        study_area_subjects = config.get('STUDY_AREA_SUBJECTS') if isinstance(config, dict) else config.get('STUDY_AREA_SUBJECTS')
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

        teacher_classes = self.get_classes_list()
        if teacher_classes and student.class_name in teacher_classes:
            return True

        if student.study_area:
            assigned_areas = self.get_assigned_study_areas(config)
            if student.study_area in assigned_areas:
                return True

        from models import Assessment
        existing_assessment = Assessment.query.filter_by(
            student_id=student.id,
            teacher_id=self.id,
            subject=self.subject
        ).first()
        return existing_assessment is not None

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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

    def calculate_final_grade(self, subject=None, teacher_id=None):
        from template_updater import calculate_scores_from_template, scores_from_assessments
        query = [a for a in self.assessments if not a.archived]
        if subject:
            query = [a for a in query if a.subject == subject]
        if teacher_id:
            query = [a for a in query if a.teacher_id == teacher_id]
        if not query:
            return None
        raw_scores = scores_from_assessments(query)
        if not raw_scores:
            return None
        result = calculate_scores_from_template(raw_scores)
        return result['final_score']

    def get_gpa_and_grade(self, subject=None, teacher_id=None):
        summary = self.get_overall_summary(subject=subject, teacher_id=teacher_id)
        return {'gpa': summary['gpa'], 'grade': summary['grade']}

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
            'name':       self.full_name(),
            'ref_id':     self.reference_number or '',
            'study_area': self.get_study_area_display() or '',
            'ica1':       raw.get('ica1',      0),
            'ica2':       raw.get('ica2',      0),
            'icp1':       raw.get('icp1',      0),
            'icp2':       raw.get('icp2',      0),
            'gp1':        raw.get('gp1',       0),
            'gp2':        raw.get('gp2',       0),
            'practical':  raw.get('practical', 0),
            'mid_term':   raw.get('mid_term',  0),
            'end_term':   raw.get('end_term',  0),
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
    date_recorded = db.Column(db.DateTime, default=datetime.utcnow, index=True)
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


class Setting(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    current_term = db.Column(db.String(32), nullable=False, default='term1')
    current_academic_year = db.Column(db.String(32), nullable=False, default='2024-2025')
    current_session = db.Column(db.String(32), nullable=False, default='First Term')
    assessment_active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f"<Setting term={self.current_term}, year={self.current_academic_year}>"


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    attempted_at = db.Column(db.DateTime, default=datetime.utcnow)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
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
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship("User", foreign_keys=[user_id], backref="ticket_replies")

    def __repr__(self):
        return f"<TicketReply ticket={self.ticket_id} by user={self.user_id}>"


def init_db(app, bcrypt):
    if not app.extensions.get('sqlalchemy'):
        db.init_app(app)

    with app.app_context():
        print(f"Initializing database at: {app.config['SQLALCHEMY_DATABASE_URI']}")

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

        if not Setting.query.first():
            default_settings = Setting(
                current_term='term1',
                current_academic_year='2024-2025',
                current_session='First Term'
            )
            db.session.add(default_settings)
            db.session.commit()
            print("Default settings created")

        if User.query.count() == 0:
            default_username = app.config.get("DEFAULT_ADMIN_USERNAME", "admin")
            default_password = app.config.get("DEFAULT_ADMIN_PASSWORD", "Admin@123")

            hashed = bcrypt.generate_password_hash(default_password).decode("utf-8")
            admin = User(
                username=default_username,
                password_hash=hashed,
                role="admin"
            )
            db.session.add(admin)
            db.session.commit()

            print(f"\n{'='*60}")
            print(f"Created default admin account:")
            print(f"  Username: {default_username}")
            print(f"  Password: {default_password}")
            print(f"  ** CHANGE THIS PASSWORD IMMEDIATELY **")
            print(f"{'='*60}\n")
