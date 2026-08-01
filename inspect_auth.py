from app import app
from models import User

with app.app_context():
    users = User.query.order_by(User.id).all()
    print('DB', app.config['SQLALCHEMY_DATABASE_URI'])
    for u in users:
        print(u.id, u.username, u.role, (u.password_hash or '')[:80])
    print('admin count', User.query.filter_by(role='admin').count())
