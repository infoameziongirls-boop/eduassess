from app import app
from models import User

with app.app_context():
    print('STUDY_AREAS', 'STUDY_AREAS' in app.config, 'STUDY_AREA_SUBJECTS' in app.config)
    teachers = User.query.filter_by(role='teacher').all()
    print('teacher_count', len(teachers))
    for t in teachers:
        print('T', t.id, t.username, t.subject, t.classes, t.class_name)
        try:
            print(' areas', t.get_assigned_study_areas(app.config))
        except Exception as e:
            print(' err', repr(e))
    fn = app.view_functions['class_management']
    try:
        print('call result type', type(fn.__wrapped__.__wrapped__()))
    except Exception as e:
        import traceback
        traceback.print_exc()
