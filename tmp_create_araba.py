import os
import sys
sys.path.insert(0, os.getcwd())
from app import app
from models import db, Student, Assessment, User

with app.app_context():
    print('DB URI:', app.config.get('SQLALCHEMY_DATABASE_URI'))
    print('Assessment count before:', Assessment.query.count())
    print('Student count before:', Student.query.count())
    print('User count before:', User.query.count())
    print('Sample student numbers:', [s.student_number for s in Student.query.limit(5).all()])
