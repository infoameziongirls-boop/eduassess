from app import app, db, User, Student, Assessment, export_student_excel
from test_excel_exports import _create_minimal_school_template, _setup_db_with_template
from flask_login import login_user
from pathlib import Path
import shutil

root = Path('tmp_route')
if root.exists():
    shutil.rmtree(root)
root.mkdir()
_create_minimal_school_template(str(root / 'student_template.xlsx'))
_setup_db_with_template(app, root)
print('template exists', (root / 'student_template.xlsx').exists())
print('TEMPLATE_FOLDER', app.config['TEMPLATE_FOLDER'])
print('tpl path exists', (Path(app.config['TEMPLATE_FOLDER']) / 'student_template.xlsx').exists())
with app.app_context():
    admin_user = User(username='admin_test', password_hash='x', role='admin')
    db.session.add(admin_user)
    db.session.commit()
    student = Student(first_name='Jane', last_name='Doe', student_number='STU100', class_name='form1', study_area='mathematics')
    db.session.add(student)
    db.session.commit()
    assessment = Assessment(student_id=student.id, category='ica1', subject='mathematics', class_name='form1', score=40.0, max_score=50.0, teacher_id=admin_user.id)
    db.session.add(assessment)
    db.session.commit()
    with app.test_request_context():
        login_user(admin_user)
        try:
            resp = export_student_excel(student.id)
            print('status', resp.status_code)
            print('location', resp.headers.get('Location'))
            print(resp.get_data(as_text=True))
        except Exception:
            import traceback
            traceback.print_exc()
