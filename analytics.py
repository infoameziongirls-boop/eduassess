# analytics.py
from models import Assessment, Student
from db import db
from sqlalchemy import func


def get_class_performance_summary(class_name=None, subject=None, teacher_id=None):
    """
    Returns per-class, per-subject aggregate statistics.
    All parameters are optional filters.
    """
    query = db.session.query(
        Assessment.class_name,
        Assessment.subject,
        func.count(Assessment.id).label('total_assessments'),
        func.avg(Assessment.score / Assessment.max_score * 100).label('avg_percentage'),
        func.min(Assessment.score / Assessment.max_score * 100).label('min_percentage'),
        func.max(Assessment.score / Assessment.max_score * 100).label('max_percentage'),
        func.count(db.distinct(Assessment.student_id)).label('student_count')
    ).filter(Assessment.archived == False)

    if class_name:
        query = query.filter(Assessment.class_name == class_name)
    if subject:
        query = query.filter(Assessment.subject == subject)
    if teacher_id:
        query = query.filter(Assessment.teacher_id == teacher_id)

    return query.group_by(
        Assessment.class_name,
        Assessment.subject
    ).all()


def get_grade_distribution(subject=None, class_name=None, teacher_id=None):
    """Returns count of students per grade band."""
    students = Student.query
    if class_name:
        students = students.filter_by(class_name=class_name)
    students = students.all()

    distribution = {
        'A1': 0, 'B2': 0, 'B3': 0, 'C4': 0,
        'C5': 0, 'C6': 0, 'D7': 0, 'E8': 0, 'F9': 0
    }

    for student in students:
        final = student.calculate_final_grade(
            subject=subject,
            teacher_id=teacher_id
        )
        if final is None:
            continue
        if final >= 80:
            distribution['A1'] += 1
        elif final >= 70:
            distribution['B2'] += 1
        elif final >= 65:
            distribution['B3'] += 1
        elif final >= 60:
            distribution['C4'] += 1
        elif final >= 55:
            distribution['C5'] += 1
        elif final >= 50:
            distribution['C6'] += 1
        elif final >= 45:
            distribution['D7'] += 1
        elif final >= 40:
            distribution['E8'] += 1
        else:
            distribution['F9'] += 1

    return distribution
