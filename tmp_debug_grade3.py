from app import app, calculate_total_grade_points
from models import db, Student, Assessment

with app.app_context():
    db.drop_all()
    db.create_all()
    s = Student(first_name='John', last_name='Doe', student_number='STU001', class_name='form1', study_area='mathematics')
    db.session.add(s)
    db.session.commit()

    def build_subject(subject, final_score):
        if final_score >= 72:
            scores = [45,45,45,45,45,45,45,45]
        elif final_score >= 68:
            scores = [40,40,40,40,40,40,50,50]
        else:
            scores = [30,30,30,30,30,30,30,30]
        categories = ['ica1','ica2','icp1','icp2','gp1','gp2','practical','mid_term']
        for cat, score in zip(categories, scores):
            a = Assessment(student_id=s.id, category=cat, subject=subject, score=score, max_score=100, teacher_id=1)
            db.session.add(a)
        a = Assessment(student_id=s.id, category='end_term', subject=subject, score=final_score, max_score=100, teacher_id=1)
        db.session.add(a)

    for subject, final in [
        ('English Language',72),
        ('Mathematics',68),
        ('Integrated Science',60),
        ('Social Studies',72),
        ('Elective 1',80),
        ('Elective 2',72),
        ('Elective 3',68),
        ('Elective 4',68),
    ]:
        build_subject(subject, final)
    db.session.commit()

    print('study_area_subjects', app.config.get('STUDY_AREA_SUBJECTS'))
    print('subject_results', s.calculate_subject_final_grades())
    print('total_points', calculate_total_grade_points(s))
    print('final_grade', s.calculate_final_grade())
