import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import User, Student

with app.app_context():
    db.create_all()
    # cleanup existing test admin
    User.query.filter_by(username='__local_admin_test__').delete()
    db.session.commit()
    admin = User(username='__local_admin_test__', password_hash='x', role='admin')
    db.session.add(admin)
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin.id)
        sess['_fresh'] = True

    r = client.get('/admin/class-register')
    print('Status:', r.status_code)
    print('Length:', len(r.data))
    print(r.data.decode('utf-8')[:2000].replace('\n',' '))
