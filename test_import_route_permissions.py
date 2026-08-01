import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from models import User
from flask_bcrypt import Bcrypt

bcrypt = Bcrypt(app)


def test_import_excel_requires_teacher_or_admin():
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    with app.app_context():
        db.drop_all()
        db.create_all()

        teacher = User(
            username='perm_teacher',
            password_hash=bcrypt.generate_password_hash('Test@123'),
            role='teacher',
            subject='mathematics',
        )
        student = User(
            username='perm_student',
            password_hash=bcrypt.generate_password_hash('Test@123'),
            role='student',
        )
        db.session.add_all([teacher, student])
        db.session.commit()
        teacher_id = teacher.id
        student_id = student.id

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['_user_id'] = str(student_id)
            sess['_fresh'] = True

        response = client.get('/import/excel')
        assert response.status_code == 403

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True

        response = client.get('/import/excel')
        assert response.status_code == 200
