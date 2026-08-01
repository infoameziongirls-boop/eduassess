from app import app
from models import User, Student

with app.app_context():
    print('USERS')
    for u in User.query.all():
        print({'id': u.id, 'username': u.username, 'is_teacher': u.is_teacher(), 'is_student': u.is_student(), 'is_admin': u.is_admin(), 'role': getattr(u, 'role', None)})
    print('STUDENTS')
    for s in Student.query.limit(20).all():
        print({'id': s.id, 'student_number': s.student_number, 'first_name': s.first_name, 'last_name': s.last_name, 'class_name': s.class_name, 'study_area': s.study_area, 'reference_number': s.reference_number})
