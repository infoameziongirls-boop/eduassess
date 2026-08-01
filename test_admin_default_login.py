import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app, bcrypt
from models import User, ensure_default_admin_user


def test_ensure_default_admin_user_creates_admin_when_other_users_exist():
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    with app.app_context():
        User.query.delete()
        from db import db
        db.session.commit()

        teacher = User(username='teacher1', password_hash=bcrypt.generate_password_hash('pw').decode('utf-8'), role='teacher')
        db.session.add(teacher)
        db.session.commit()

        ensure_default_admin_user(app, bcrypt)

        admin = User.query.filter_by(username='admin').first()
        assert admin is not None
        assert admin.role == 'admin'
        assert admin.check_password('Admin@123', bcrypt)
