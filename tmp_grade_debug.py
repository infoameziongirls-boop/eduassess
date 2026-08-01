from app import app, calculate_total_grade_points
from models import db, Student, Assessment

app.config['TESTING'] = True
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

with app.app_context():
    db.drop_all()
    db.create_all()

    s = Student(
        first_name='John',
        last_name='Doe',
        student_number='STU_DEBUG_001',
        class_name='form1',
        study_area='mathematics'
    )
    db.session.add(s)
    db.session.commit()

    def build_subject(subject, final_score):
        if final_score >= 72:
            scores = [45, 45, 45, 45, 45, 45, 45, 45]
        elif final_score >= 68:
            scores = [40, 40, 40, 40, 40, 40, 50, 50]
        else:
            scores = [30, 30, 30, 30, 30, 30, 30, 30]
        categories = ['ica1', 'ica2', 'icp1', 'icp2', 'gp1', 'gp2', 'practical', 'mid_term']
        for cat, score in zip(categories, scores):
            a = Assessment(student_id=s.id, category=cat, subject=subject, score=score, max_score=100, teacher_id=1)
            db.session.add(a)
        a = Assessment(student_id=s.id, category='end_term', subject=subject, score=final_score, max_score=100, teacher_id=1)
        db.session.add(a)

    for subject, final in [
        ('English Language', 72),
        ('Mathematics', 68),
        ('Integrated Science', 60),
        ('Social Studies', 72),
        ('Elective 1', 80),
        ('Elective 2', 72),
        ('Elective 3', 68),
        ('Elective 4', 68),
    ]:
        build_subject(subject, final)

    db.session.commit()

    subject_results = s.calculate_subject_final_grades()
    print('app config URI:', app.config['SQLALCHEMY_DATABASE_URI'])
    print('subject_results:')
    for key, result in subject_results.items():
        print(' ', key, result)
    print('total_points:', calculate_total_grade_points(s))
