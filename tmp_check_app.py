import os
from app import app
from models import User

os.chdir(r'C:\Users\HP\Documents\school_assess_app_EXPERIMENTAL_ver_1')
with app.app_context():
    admin = User.query.filter_by(role='admin').first()
    print('admin exists:', bool(admin))
    if admin:
        print('admin username:', admin.username)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin.id)
        sess['_fresh'] = True
    r = client.get('/admin/class-register')
    print('/admin/class-register status:', r.status_code)
    print('body snippet:', r.data.decode('utf-8')[:300].replace('\n', ' '))
