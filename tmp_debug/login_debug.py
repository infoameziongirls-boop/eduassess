from app import app, db, bcrypt
from models import User

admin_username = 'admin_test'
admin_password = 'AdminPass123'

with app.app_context():
    admin = User.query.filter_by(username=admin_username).first()
    print('admin exists:', bool(admin))
    if admin:
        print('role:', admin.role)
        print('password_hash:', admin.password_hash[:60])
    else:
        print('admin user not found')
    print('db uri:', app.config.get('SQLALCHEMY_DATABASE_URI'))
    print('testing:', app.config.get('TESTING'))
    print('csrf enabled:', app.config.get('WTF_CSRF_ENABLED'))

with app.test_client() as client:
    get_resp = client.get('/login')
    print('\nGET /login status:', get_resp.status_code)
    print('contains csrf hidden input:', b'name="csrf_token"' in get_resp.data)
    print('GET /login body snippet:')
    print(get_resp.data[:400].decode('utf-8', errors='replace'))

    post_resp = client.post('/login', data={'username': admin_username, 'password': admin_password}, follow_redirects=True)
    print('\nPOST /login status:', post_resp.status_code)
    body = post_resp.data.decode('utf-8', errors='replace')
    print('contains invalid credentials:', 'Invalid credentials' in body)
    print('contains Logged in successfully:', 'Logged in successfully' in body)
    print('contains dashboard:', 'Dashboard' in body)
    print('POST /login body snippet:')
    print(body[:1200])
