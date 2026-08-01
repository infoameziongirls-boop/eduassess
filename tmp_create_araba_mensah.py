import os
import sys
sys.path.insert(0, os.getcwd())

from app import app, bcrypt, generate_unique_reference_number
from models import db, Student, User, Assessment
from template_updater import calculate_scores_from_template, scores_from_assessments

GRADE_EXAMPLES = {
    'A1': {
        'ica1': 45, 'ica2': 50, 'icp1': 50, 'icp2': 50,
        'gp1': 45, 'gp2': 45, 'practical': 45, 'mid_term': 45, 'end_term': 100,
    },
    'B2': {
        'ica1': 35, 'ica2': 35, 'icp1': 35, 'icp2': 35,
        'gp1': 35, 'gp2': 35, 'practical': 40, 'mid_term': 40, 'end_term': 90,
    },
    'B3': {
        'ica1': 30, 'ica2': 30, 'icp1': 30, 'icp2': 30,
        'gp1': 30, 'gp2': 30, 'practical': 35, 'mid_term': 35, 'end_term': 80,
    },
    'C4': {
        'ica1': 28, 'ica2': 28, 'icp1': 28, 'icp2': 28,
        'gp1': 28, 'gp2': 28, 'practical': 35, 'mid_term': 35, 'end_term': 70,
    },
    'C5': {
        'ica1': 26, 'ica2': 26, 'icp1': 26, 'icp2': 26,
        'gp1': 26, 'gp2': 26, 'practical': 30, 'mid_term': 30, 'end_term': 65,
    },
    'C6': {
        'ica1': 25, 'ica2': 25, 'icp1': 25, 'icp2': 25,
        'gp1': 25, 'gp2': 25, 'practical': 30, 'mid_term': 30, 'end_term': 65,
    },
    'D7': {
        'ica1': 20, 'ica2': 18, 'icp1': 20, 'icp2': 18,
        'gp1': 20, 'gp2': 18, 'practical': 40, 'mid_term': 41, 'end_term': 50,
    },
    'E8': {
        'ica1': 15, 'ica2': 15, 'icp1': 15, 'icp2': 15,
        'gp1': 15, 'gp2': 15, 'practical': 15, 'mid_term': 15, 'end_term': 40,
    },
    'F9': {
        'ica1': 10, 'ica2': 10, 'icp1': 10, 'icp2': 10,
        'gp1': 10, 'gp2': 10, 'practical': 10, 'mid_term': 10, 'end_term': 30,
    },
}

SUBJECT_ASSIGNMENTS = [
    ('mathematics', 'teacher1', 'A1'),
    ('english_language', 'teacher2', 'B2'),
    ('biology', None, 'B3'),
    ('chemistry', None, 'C4'),
    ('additional_mathematics', None, 'C5'),
    ('physics', None, 'C6'),
    ('geography', None, 'D7'),
    ('economics', None, 'E8'),
    ('ict', None, 'F9'),
]

CATEGORIES = ['ica1', 'ica2', 'icp1', 'icp2', 'gp1', 'gp2', 'practical', 'mid_term', 'end_term']


def create_student_and_assessments():
    with app.app_context():
        print('Deleting all existing assessments...')
        deleted = Assessment.query.delete()
        db.session.commit()
        print(f'  deleted {deleted} assessment rows.')

        student_number = 'ARABA001'
        student = Student.query.filter_by(student_number=student_number).first()
        if student:
            print('Existing student found. Reusing record:', student.full_name())
            student.first_name = 'Araba'
            student.last_name = 'Mensah'
            student.middle_name = None
            student.class_name = 'Form 3'
            student.study_area = 'science_a'
            student.reference_number = generate_unique_reference_number()
        else:
            student = Student(
                student_number=student_number,
                first_name='Araba',
                last_name='Mensah',
                middle_name=None,
                class_name='Form 3',
                study_area='science_a',
                reference_number=generate_unique_reference_number(),
            )
            db.session.add(student)

        student_user = User.query.filter_by(username=student_number).first()
        if student_user:
            print('Existing user account found for student', student_number)
            student_user.role = 'student'
        else:
            print('Creating user account for student', student_number)
            pw_hash = bcrypt.generate_password_hash(student_number).decode('utf-8')
            student_user = User(username=student_number, password_hash=pw_hash, role='student')
            db.session.add(student_user)

        db.session.commit()

        teacher_map = {u.username: u.id for u in User.query.filter(User.username.in_(['teacher1', 'teacher2'])).all()}

        print('Inserting new assessments for student', student.full_name())
        for subj, teacher_username, grade_key in SUBJECT_ASSIGNMENTS:
            raw_scores = GRADE_EXAMPLES[grade_key]
            for category in CATEGORIES:
                score = raw_scores[category]
                assessment = Assessment(
                    student_id=student.id,
                    category=category,
                    subject=subj,
                    class_name=student.class_name,
                    score=score,
                    max_score=50 if category in {'ica1', 'ica2', 'icp1', 'icp2', 'gp1', 'gp2'} else 100,
                    term='term1',
                    academic_year='2024-2025',
                    session='First Term',
                    assessor='Auto Import',
                    teacher_id=teacher_map.get(teacher_username),
                )
                db.session.add(assessment)

        db.session.commit()

        print('\nCreated student:')
        print(f'  student_number: {student.student_number}')
        print(f'  reference_number: {student.reference_number}')
        print(f'  class_name: {student.class_name}')
        print(f'  study_area: {student.study_area}')

        student = db.session.get(Student, student.id)
        summary = student.calculate_subject_final_grades()
        print('\nSubject summary:')
        for subject_key, data in sorted(summary.items()):
            print(f"  {data['subject']} ({subject_key}): final_percent={data['final_percent']} grade={data['grade']} gpa={data['gpa']} grade_point={data['grade_point']}")

        final_pct = student.calculate_final_grade()
        overall = student.get_gpa_and_grade()
        total_points = None
        try:
            total_points = __import__('app').calculate_total_grade_points(student)
        except Exception as exc:
            total_points = f'ERROR-{exc}'
        division = __import__('app').get_grade_class_division(overall['gpa'])

        print('\nAggregate values:')
        print(f'  overall_final_percent: {final_pct}')
        print(f'  overall_gpa: {overall["gpa"]}')
        print(f'  overall_grade: {overall["grade"]}')
        print(f'  grade_point_total: {total_points}')
        print(f'  class_division: {division}')

        print('\nVerification for student dashboard values:')
        all_assessments = Assessment.query.filter_by(student_id=student.id, archived=False).all()
        raw = scores_from_assessments(all_assessments)
        filtered = calculate_scores_from_template(raw)
        print(f"  template_final_score: {filtered['final_score']}")
        print(f"  template_grade: {filtered['grade']} gpa: {filtered['gpa']}")


if __name__ == '__main__':
    create_student_and_assessments()
