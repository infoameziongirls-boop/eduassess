import os
import sys
sys.path.insert(0, os.getcwd())
from app import app
from models import Student, User, SystemConfig

with app.app_context():
    print('student count:', Student.query.count())
    print('student classes:', sorted({s.class_name for s in Student.query.all()}))
    print('student study areas:', sorted({s.study_area for s in Student.query.all()}))
    print('teacher usernames/subjects:', [(u.username, u.subject) for u in User.query.filter_by(role='teacher').all()])
    print('STUDY_AREAS:', SystemConfig.get_config('STUDY_AREAS', []))
    print('STUDY_AREA_SUBJECTS:', SystemConfig.get_config('STUDY_AREA_SUBJECTS', {}))
