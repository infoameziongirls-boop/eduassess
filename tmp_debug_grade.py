from app import app, calculate_total_grade_points
from models import db, Student, Assessment

with app.app_context():
    db.drop_all()
    db.create_all()
    s = Student(first_name='John', last_name='Doe', student_number='STU001', class_name='form1', study_area='mathematics')
    db.session.add(s)
    db.session.commit()

    def add(category, score, subject='Mathematics', max_score=100, teacher_id=1):
        a = Assessment(student_id=s.id, category=category, subject=subject, score=score, max_score=max_score, teacher_id=teacher_id)
        db.session.add(a)
        db.session.commit()
        return a

    add('ica1', 25)
    add('ica2', 25)
    add('icp1', 25)
    add('icp2', 25)
    add('end_term', 100)

    print('subject_results', s.calculate_subject_final_grades())
    print('final_grade', s.calculate_final_grade())
    print('gpa', s.get_gpa_and_grade())
    print('total_points', calculate_total_grade_points(s))
