from app import app, db, build_student_aggregate_metrics
from models import Student
from unittest.mock import patch

with app.app_context():
    db.drop_all()
    db.create_all()
    student = Student(first_name='GTest', last_name='User', student_number='GT001', reference_number='REFGT', class_name='Form 1', study_area='Science')
    db.session.add(student)
    db.session.commit()
    with patch.object(Student, 'calculate_final_grade', return_value=72.0):
        print(build_student_aggregate_metrics(student))
