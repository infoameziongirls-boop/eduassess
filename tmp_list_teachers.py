import os
import sys
sys.path.insert(0, os.getcwd())
from app import app
from models import User

with app.app_context():
    print('Teachers:', [(u.username, u.subject) for u in User.query.filter_by(role='teacher').all()])
