from app import app, calculate_total_grade_points, canonical_subject_key
from db import db
from models import Student, Assessment
import tempfile, os

app.config['TESTING'] = True
fd, path = tempfile.mkstemp(suffix='.db')
os.close(fd)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
with app.app_context():
    db.drop_all()
    db.create_all()
    student = Student(first_name='John', last_name='Doe', student_number='STU001', class_name='form1', study_area='science')
    db.session.add(student)
    db.session.commit()

    def create(subject, final_score):
        for cat in ['ica1', 'ica2', 'icp1', 'icp2', 'gp1', 'gp2', 'practical', 'mid_term']:
            db.session.add(Assessment(student_id=student.id, category=cat, score=45, max_score=100, subject=subject, teacher_id=1))
        db.session.add(Assessment(student_id=student.id, category='end_term', score=final_score, max_score=100, subject=subject, teacher_id=1))
        db.session.commit()

    create('English Language', 72)
    create('Mathematics', 68)
    create('Social Studies', 72)
    create('ICT', 60)
    create('Physics', 80)
    create('Biology', 72)
    create('Chemistry', 68)
    create('Additional Mathematics', 68)

    subject_results = student.calculate_subject_final_grades()
    print(subject_results)
    subject_grade_points = {}
    for subject_result in subject_results.values():
        subject_key = canonical_subject_key(subject_result.get('subject') or subject_result.get('subject_key'))
        grade_point = subject_result.get('grade_point')
        if subject_key and grade_point is not None:
            subject_grade_points[subject_key] = grade_point
    print('subject_grade_points', subject_grade_points)
    print('total', calculate_total_grade_points(student))
