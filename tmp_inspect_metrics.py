from app import app, db, build_student_aggregate_metrics
from models import Student, User

with app.app_context():
    db.drop_all()
    db.create_all()
    student = Student(first_name='GTest', last_name='User', student_number='GT001', reference_number='REFGT', class_name='Form 1', study_area='Science')
    db.session.add(student)
    db.session.commit()
    user = User(username=student.student_number, password_hash='x', role='student')
    db.session.add(user)
    db.session.commit()
    print('student calc', student.calculate_final_grade())
    print('metrics', build_student_aggregate_metrics(student))
