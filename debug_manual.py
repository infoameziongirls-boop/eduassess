from app import app, db, User, Student, Assessment
from test_excel_exports import _create_minimal_school_template, _setup_db_with_template
from flask_login import login_user
from pathlib import Path
import shutil, os
from template_updater import AssessmentTemplateUpdater

root = Path('tmp_manual')
if root.exists():
    shutil.rmtree(root)
root.mkdir()
_create_minimal_school_template(str(root / 'student_template.xlsx'))
_setup_db_with_template(app, root)
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
    settings = None
    try:
        settings = db.session.query(app.config.get('SQLALCHEMY_DATABASE_URI')).first()
    except Exception:
        settings = None
    tpl_path = os.path.join(app.config['TEMPLATE_FOLDER'], 'student_template.xlsx')
    print('tpl_path', tpl_path, os.path.exists(tpl_path))
    try:
        exp_subj = student.study_area
        upd = AssessmentTemplateUpdater(tpl_path)
        upd.load_template()
        print('loaded template')
        upd.update_school_info(subject=exp_subj, term_year='First Term 2024-2025', form=student.class_name)
        print('updated header')
        sd = student.to_template_dict('mathematics')
        sd['sheet_subject'] = exp_subj
        sd['sheet_class'] = student.class_name or ''
        upd.add_students_batch([sd], per_sheet=True)
        print('added students batch')
        out_path = str(root / 'out.xlsx')
        upd.save_workbook(out_path)
        print('saved out', os.path.exists(out_path), out_path)
    except Exception:
        import traceback
        traceback.print_exc()
