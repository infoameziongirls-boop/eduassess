from app import app
from models import User

with app.test_client() as client:
    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
        print('admin_exists', admin is not None)
    resp = client.post('/login', data={'username': 'admin', 'password': 'Admin@123'}, follow_redirects=False)
    print('status', resp.status_code)
    print('location', resp.headers.get('Location'))
